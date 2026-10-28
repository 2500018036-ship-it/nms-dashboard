"""Sequential unauthenticated native rendering checks; changes no device settings."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from theaz_access.broker import Broker
from theaz_access.egress import serve
from theaz_access.policy import load


async def main():
    config=load('access/targets.json')
    image=os.environ['ACCESS_TEST_WORKER_IMAGE']
    output=Path(os.environ['ACCESS_TEST_OUTPUT']).resolve();output.mkdir(mode=0o700,parents=True,exist_ok=True)
    broker=Broker(config,'/unused',image,'/unused',os.environ['ACCESS_INVENTORY_DB'])
    results=[]
    for target in config['targets']:
        try:selected=broker.selected(target['id'])
        except (ValueError, OSError) as error:
            value={'target':target['id'],'exit':1,'browser_error':True,'error':type(error).__name__,'authenticated_login':'NOT_TESTED'}
            results.append(value);print(json.dumps(value),flush=True);continue
        with tempfile.TemporaryDirectory(prefix='theaz-native-page-') as directory:
            root=Path(directory);os.chown(root,31000,31000);root.chmod(0o700)
            (root/'start.json').write_text(json.dumps(selected))
            proxy=await serve(root/'egress.sock',selected['url']);os.chown(root/'egress.sock',31000,31000);os.chmod(root/'egress.sock',0o600)
            name='theaz-native-probe-'+target['id']
            command=['docker','run','--rm','--name',name,'--network','none','--user','31000:31000','--read-only','--init',
                '--cap-drop','ALL','--security-opt','no-new-privileges:true','--security-opt','seccomp='+str(Path('access/worker/seccomp.json').resolve()),
                '--memory','1g','--cpus','0.75','--pids-limit','256','--tmpfs','/tmp:rw,nosuid,nodev,size=128m,mode=1777',
                '--mount','type=bind,src='+directory+',dst=/run/session',
                '--mount','type=bind,src='+str(Path('access/tests/probe_page.py').resolve())+',dst=/opt/probe_page.py,readonly',
                '--entrypoint','python3',image,'/opt/probe_page.py']
            try:
                process=await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.PIPE)
                await asyncio.wait_for(process.communicate(),60)
                value=json.loads((root/'result.json').read_text()) if (root/'result.json').exists() else {'exit':process.returncode,'browser_error':True}
                value.update({'target':target['id'],'url':selected['url'],'authenticated_login':'NOT_TESTED'})
                if (root/'page.png').exists():shutil.copyfile(root/'page.png',output/(target['id']+'.png'))
                results.append(value);print(json.dumps(value),flush=True)
            except (TimeoutError, OSError, ValueError) as error:
                value={'target':target['id'],'url':selected['url'],'exit':1,'browser_error':True,'error':type(error).__name__,'authenticated_login':'NOT_TESTED'}
                results.append(value);print(json.dumps(value),flush=True)
            finally:
                await asyncio.to_thread(subprocess.run,['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                proxy.close();await proxy.wait_closed()
    (output/'native-results.json').write_text(json.dumps(results,indent=2))
    if any(r['exit'] or r.get('browser_error') or not r.get('screenshot') for r in results):raise SystemExit(1)


asyncio.run(main())
