import asyncio
from contextlib import closing
import json
import os
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from theaz_access import egress
from theaz_access.gateway import Gateway, Session, app
from theaz_access.policy import check_sid, load, origin, target

CONFIG=Path(__file__).resolve().parents[1]/'targets.json'


class PolicyTests(unittest.TestCase):
    def test_exact_origins_reject_loopback_metadata_userinfo_and_other_ports(self):
        selected='http://192.168.10.26/'
        self.assertEqual(egress.destination('GET',selected+'login?q=1',selected),('192.168.10.26',80,'/login?q=1'))
        for value in ('http://127.0.0.1/','http://169.254.169.254/','http://192.168.10.26:81/','http://192.168.10.27/','http://u:p@192.168.10.26/','https://192.168.10.26/'):
            with self.subTest(url=value),self.assertRaises(ValueError):egress.destination('GET',value,selected)
        self.assertEqual(egress.destination('CONNECT','192.168.20.200:8006','https://192.168.20.200:8006/'),('192.168.20.200',8006,None))
        self.assertEqual(egress.destination('CONNECT','192.168.10.26:80',selected),('192.168.10.26',80,None))
        with self.assertRaises(ValueError):egress.destination('CONNECT','192.168.10.26:22',selected)
        with self.assertRaises(ValueError):egress.destination('CONNECT','192.168.20.200:22','https://192.168.20.200:8006/')

    def test_config_is_audited_roles_are_restricted_and_ids_are_not_paths(self):
        config=load(CONFIG)
        self.assertEqual(len(config['targets']),7)
        self.assertEqual(config['max_sessions'],1)
        self.assertNotIn('Viewer',target(config,'portainer')['roles'])
        for value in ('../docker.sock','a'*31,'a'*33,'../../'):
            with self.assertRaises(ValueError):check_sid(value)
        with self.assertRaises(KeyError):target(config,'missing')
        for value in ('http://169.254.169.254/','http://127.0.0.1/','http://user:pass@192.168.20.1/'):
            with self.assertRaises(ValueError):origin(value)


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.gateway=Gateway(load(CONFIG),self.root,self.root/'audit.sqlite3','http://auth','/unused')
        application=app(self.gateway);application.cleanup_ctx.clear()
        self.client=TestClient(TestServer(application));await self.client.start_server()
        self.owner={'enabled':True,'user':{'username':'admin','role':'Administrator'},'binding':'owner-binding','expires_at':9999999999,'targets':[]}
        self.gateway.auth=AsyncMock(return_value=self.owner)
        self.gateway.control=AsyncMock(return_value={'expires':9999999999,'url':'http://192.168.20.1/'})
        self.headers={'Cookie':'nms_session=opaque','Origin':self.gateway.config['public_origin']}

    async def asyncTearDown(self):
        for item in self.gateway.sessions.values():
            if item.proxy:item.proxy.close();await item.proxy.wait_closed()
        await self.client.close()
        import gc;gc.collect()
        self.tmp.cleanup()

    async def test_mutation_and_websocket_reject_foreign_or_missing_origin(self):
        for headers in ({},{'Origin':'https://evil.test'}):
            r=await self.client.post('/access-api/sessions',json={'target':'mikrotik'},headers=headers)
            self.assertEqual(r.status,403)
        self.gateway.control.assert_not_called()

    async def test_owner_binding_blocks_another_login_and_revoked_auth(self):
        identity='a'*32
        self.gateway.sessions[identity]=Session(identity,'mikrotik','admin','another-binding',0,9999999999,9999999999,'cookie',None)
        r=await self.client.get('/access-api/sessions/'+identity,headers=self.headers)
        self.assertEqual(r.status,403)
        self.gateway.sessions.clear()
        self.gateway.auth=AsyncMock(side_effect=web.HTTPUnauthorized())
        r=await self.client.get('/access-api/catalog',headers=self.headers)
        self.assertEqual(r.status,401)

    async def test_audit_has_lifecycle_metadata_without_cookie_or_password(self):
        self.gateway.record('admin','mikrotik','b'*32,'access.started')
        r=await self.client.get('/access-api/audit',headers=self.headers)
        payload=await r.json();text=json.dumps(payload)
        self.assertEqual(payload['items'][0]['event'],'access.started')
        self.assertNotIn('cookie',text);self.assertNotIn('password',text)
        self.owner['user']['role']='Network Administrator'
        r=await self.client.get('/access-api/audit',headers=self.headers)
        self.assertEqual(r.status,403)

    async def test_expired_session_is_removed_even_when_broker_is_unavailable(self):
        identity='c'*32
        self.gateway.sessions[identity]=Session(identity,'mikrotik','admin','owner-binding',0,1,0,'private-cookie',None)
        self.gateway.control=AsyncMock(side_effect=web.HTTPServiceUnavailable())
        response=await self.client.get('/access-api/sessions/'+identity,headers=self.headers)
        self.assertEqual(response.status,410)
        self.assertNotIn(identity,self.gateway.sessions)
        self.gateway.control.assert_awaited_once()

    @unittest.skipUnless(os.name=='posix','File bridge uses Linux directory descriptors')
    async def test_files_are_owner_only_and_profiles_cannot_be_downloaded(self):
        identity='d'*32
        self.gateway.sessions[identity]=Session(identity,'mikrotik','admin','owner-binding',time.time(),9999999999,time.time(),'private-cookie',None)
        root=self.root/identity;root.mkdir()
        body=FormData();body.add_field('file',b'fixture-config',filename='router.cfg',content_type='application/octet-stream')
        response=await self.client.post('/access-api/sessions/'+identity+'/upload',data=body,headers=self.headers)
        self.assertEqual(response.status,200)
        self.assertTrue((await response.json())['remote_path'].startswith('/run/session/uploads/'))
        downloads=root/'downloads';downloads.mkdir();(downloads/'backup.cfg').write_bytes(b'fixture-download')
        response=await self.client.get('/access-api/sessions/'+identity+'/downloads/backup.cfg',headers=self.headers)
        self.assertEqual(await response.read(),b'fixture-download')
        (downloads/'profile-link').symlink_to(root/'start.json')
        response=await self.client.get('/access-api/sessions/'+identity+'/downloads/profile-link',headers=self.headers)
        self.assertEqual(response.status,404)
        os.mkfifo(downloads/'pipe')
        response=await asyncio.wait_for(self.client.get('/access-api/sessions/'+identity+'/downloads/pipe',headers=self.headers),2)
        self.assertEqual(response.status,403)
        response=await self.client.get('/access-api/sessions/'+identity+'/downloads/%2e%2e%2fprofile',headers=self.headers)
        self.assertNotEqual(response.status,200)
        self.gateway.auth=AsyncMock(return_value={**self.owner,'binding':'other-login'})
        response=await self.client.get('/access-api/sessions/'+identity+'/downloads/backup.cfg',headers=self.headers)
        self.assertEqual(response.status,403)

    @unittest.skipUnless(os.name=='posix','Unix browser channel requires Linux')
    async def test_display_relays_binary_and_revocation_disconnects_it(self):
        identity='e'*32
        root=self.root/identity;root.mkdir()
        received=asyncio.Event()
        async def browser(reader,writer):
            try:
                writer.write(b'RFB 003.008\n');await writer.drain()
                if await reader.read(3)==b'key':received.set()
                await reader.read()
            finally:writer.close();await writer.wait_closed()
        server=await asyncio.start_unix_server(browser,path=str(root/'vnc.sock'))
        self.gateway.sessions[identity]=Session(identity,'mikrotik','admin','owner-binding',time.time(),9999999999,time.time(),'private-cookie',None)
        sweeper=None
        try:
            websocket=await self.client.ws_connect('/access-api/sessions/'+identity+'/display',headers=self.headers,protocols=('binary',))
            self.assertEqual((await websocket.receive()).data,b'RFB 003.008\n')
            await websocket.send_bytes(b'key');await asyncio.wait_for(received.wait(),2)
            self.gateway.auth=AsyncMock(side_effect=web.HTTPUnauthorized())
            sweeper=asyncio.create_task(self.gateway.sweep())
            message=await asyncio.wait_for(websocket.receive(),13)
            self.assertEqual(message.type,web.WSMsgType.CLOSE)
            await websocket.close()
            for _ in range(20):
                if identity not in self.gateway.sessions:break
                await asyncio.sleep(.05)
            self.assertNotIn(identity,self.gateway.sessions)
        finally:
            if sweeper:sweeper.cancel();await asyncio.gather(sweeper,return_exceptions=True)
            server.close();await server.wait_closed()
