"""Linux-only integration test: real sandboxed Chromium, isolated network and native GUI traffic."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from aiohttp import web
from theaz_access.egress import serve


async def main():
    visited={'redirect':False,'cookie':False,'websocket':False}
    async def first(request):
        visited['redirect']=True
        response=web.HTTPFound('/native/gui')
        response.set_cookie('native_session','fixture-private',httponly=True,path='/')
        raise response
    async def gui(request):
        visited['cookie']=request.cookies.get('native_session')=='fixture-private'
        return web.Response(text='''<!doctype html><title>Original native GUI fixture</title><h1>Original native GUI</h1><script>
        const ws=new WebSocket('ws://'+location.host+'/native/ws');ws.onopen=()=>ws.send('native-ping');
        ws.onmessage=(e)=>document.body.dataset.native=e.data;
        </script>''',content_type='text/html',headers={'X-Frame-Options':'DENY','Content-Security-Policy':"frame-ancestors 'none'"})
    async def ws(request):
        connection=web.WebSocketResponse();await connection.prepare(request)
        async for message in connection:
            if message.data=='native-ping':
                visited['websocket']=True;await connection.send_str('native-pong')
        return connection
    application=web.Application();application.router.add_get('/',first);application.router.add_get('/native/gui',gui);application.router.add_get('/native/ws',ws)
    runner=web.AppRunner(application,access_log=None);await runner.setup()
    site=web.TCPSite(runner,'0.0.0.0',18090);await site.start()
    bridge=subprocess.check_output(['docker','network','inspect','bridge','--format','{{(index .IPAM.Config 0).Gateway}}'],text=True).strip()
    with tempfile.TemporaryDirectory(prefix='theaz-access-smoke-') as directory:
        root=Path(directory);root.chmod(0o700);os.chown(root,31000,31000)
        (root/'start.json').write_text(json.dumps({'url':f'http://{bridge}:18090/','tls_spki':[]}))
        proxy=await serve(root/'egress.sock',f'http://{bridge}:18090/')
        os.chown(root/'egress.sock',31000,31000);os.chmod(root/'egress.sock',0o600)
        name='theaz-access-smoke'
        command=['docker','run','-d','--name',name,'--network','none','--user','31000:31000','--read-only','--init',
          '--cap-drop','ALL','--security-opt','no-new-privileges:true','--security-opt','seccomp='+str(Path('access/worker/seccomp.json').resolve()),
          '--memory','1g','--cpus','1','--pids-limit','256','--shm-size','128m','--tmpfs','/tmp:rw,nosuid,nodev,size=128m,mode=1777',
          '--mount','type=bind,src='+directory+',dst=/run/session','theaz-access-worker:test']
        try:
            await asyncio.to_thread(subprocess.run,command,check=True,stdout=subprocess.DEVNULL)
            for _ in range(120):
                if all(visited.values()):break
                if (root/'state.json').exists() and json.loads((root/'state.json').read_text()).get('state')=='failed':
                    # Only fixture traffic is present; useful CI diagnostics, no production data.
                    diagnostic = root/'fixture-runtime.log'
                    subprocess.run(['docker','cp',name+':/tmp/browser-runtime.log',str(diagnostic)],check=False)
                    if diagnostic.exists():print(diagnostic.read_text(errors='replace'),flush=True)
                    raise AssertionError('Browser sandbox/runtime failed')
                await asyncio.sleep(0.5)
            assert all(visited.values()),visited
            reader,writer=await asyncio.open_unix_connection(str(root/'vnc.sock'))
            banner=await asyncio.wait_for(reader.readexactly(12),5)
            assert banner.startswith(b'RFB 003.')
            writer.close();await writer.wait_closed()
            details=json.loads(subprocess.check_output(['docker','inspect',name],text=True))[0]
            assert details['HostConfig']['NetworkMode']=='none'
            assert not details['NetworkSettings']['Ports']
            assert details['HostConfig']['ReadonlyRootfs']
            assert details['Config']['User']=='31000:31000'
            print('REAL_BROWSER_REDIRECT_COOKIE_WEBSOCKET_RFB_OK',flush=True)
        finally:
            await asyncio.to_thread(subprocess.run,['docker','rm','-f',name],check=False,stdout=subprocess.DEVNULL)
            proxy.close();await proxy.wait_closed()
    await runner.cleanup()


asyncio.run(main())
