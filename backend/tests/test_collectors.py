import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock,Mock,patch
import httpx
import dns.exception
from dns.exception import Timeout as DNSTimeout

from app.config import Settings
from app.monitoring import tcp,dns,web,proxmox
from app.monitoring.docker_monitor import read_snapshot
from app.monitoring.mikrotik import MikroTik
from app.storage.database import Database
from app.services.health import Monitoring
from app.ai.tool_registry import Registry

CLIENT=httpx.AsyncClient
def fake_client(handler):
    return lambda **kwargs:CLIENT(**kwargs,transport=httpx.MockTransport(handler))

class CollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_monitoring_gives_router_sections_separate_timeout_windows(self):
        import asyncio
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory)
            monitor=Monitoring(Settings('t',frozenset({1}),'k',('m',)),db)
            active=0
            router_order=[]
            async def check(target):
                nonlocal active
                if target in {'mikrotik_system','mikrotik_interfaces'}:
                    self.assertEqual(active,0,'Router checks must not compete for the same timeout budget')
                    active+=1;router_order.append(target)
                    await asyncio.sleep(.02)
                    active-=1
                return {'target':target,'status':'UP'}
            monitor.check=check
            value=await monitor.all()
            expected=list(monitor.settings.targets)+['mikrotik_system','mikrotik_interfaces','proxmox_resources','docker','debian']
            self.assertEqual(router_order,['mikrotik_system','mikrotik_interfaces'])
            self.assertEqual([r['target'] for r in value['results']],expected)
            self.assertEqual(value['counts'],{'UP':len(expected)})
            db.close()

    async def test_router_concurrent_sections_are_serialized(self):
        import asyncio
        import time
        cfg=Settings('t',frozenset({1}),'k',('m',),mikrotik_readonly=True)
        api=Mock()
        def resource(path):
            values={'/user':[{'group':'nms'}],'/user/group':[{'policy':'read,api'}],'/interface':[{'name':'ether1','running':'true'}],'/system/resource':[{'cpu-load':'1'}]}
            return Mock(call=Mock(return_value=values.get(path,[])),call_async=Mock(side_effect=lambda *a:iter(values.get(path,[]))))
        api.get_resource.side_effect=resource
        pool=Mock()
        def get_api():time.sleep(.03);return api
        pool.get_api.side_effect=get_api
        router=MikroTik(cfg)
        with patch.dict(os.environ,{'MIKROTIK_USER':'monitor','MIKROTIK_PASSWORD':'test','MIKROTIK_ALLOW_PLAINTEXT':'true','MIKROTIK_PORT':'8728'}),patch('routeros_api.RouterOsApiPool',return_value=pool):
            rows=await asyncio.gather(router.collect('system'),router.collect('interfaces'))
        self.assertEqual([r['status'] for r in rows],['UP','UP'])

    async def test_tcp_up(self):
        writer=Mock();writer.wait_closed=AsyncMock()
        with patch('asyncio.open_connection',AsyncMock(return_value=(None,writer))):
            self.assertEqual((await tcp.probe('x','127.0.0.1',80))['status'],'UP')
        writer.close.assert_called_once()

    async def test_tcp_timeout(self):
        with patch('asyncio.open_connection',AsyncMock(side_effect=TimeoutError())):
            self.assertEqual((await tcp.probe('x','127.0.0.1',80))['status'],'DOWN')

    async def test_dns_success(self):
        with patch('dns.asyncresolver.Resolver.resolve',AsyncMock(return_value=['93.184.216.34'])):
            r=await dns.probe('dns','192.168.20.199',53,'example.com')
        self.assertEqual(r['status'],'UP');self.assertEqual(r['answers'],['93.184.216.34'])

    async def test_dns_timeout(self):
        with patch('dns.asyncresolver.Resolver.resolve',AsyncMock(side_effect=DNSTimeout())):
            self.assertEqual((await dns.probe('dns','192.168.20.199',53,'example.com'))['status'],'DOWN')

    async def test_web_codes_and_no_redirect(self):
        for code,status in [(200,'UP'),(302,'UP'),(401,'DEGRADED'),(500,'DOWN')]:
            calls=[]
            def handle(request):
                calls.append(str(request.url));return httpx.Response(code,headers={'location':'http://169.254.169.254/'})
            with patch('app.monitoring.web.httpx.AsyncClient',fake_client(handle)):
                self.assertEqual((await web.probe('web','http://allowlisted/'))['status'],status)
            self.assertEqual(calls,['http://allowlisted/'])

    async def test_web_tls_failure(self):
        def fail(request):raise httpx.ConnectError('CERTIFICATE_VERIFY_FAILED',request=request)
        with patch('app.monitoring.web.httpx.AsyncClient',fake_client(fail)):
            self.assertEqual((await web.probe('web','https://allowlisted/'))['status'],'UNKNOWN')

    async def test_proxmox_missing_credentials(self):
        with patch.dict(os.environ,{},clear=True):self.assertEqual((await proxmox.collect())['error'],'missing_readonly_token')

    async def test_proxmox_resources(self):
        resources=[{'type':'node','node':'pve','status':'online','cpu':.25},{'type':'qemu','vmid':100,'id':'qemu/100','node':'pve','name':'vm','status':'running'},{'type':'storage','id':'storage/pve/local','disk':10,'maxdisk':100}]
        def handle(request):
            if request.url.path.endswith('/permissions'):data={'/':{'Sys.Audit':1,'VM.Audit':1,'Datastore.Audit':1}}
            elif request.url.path.endswith('/version'):data={'version':'9.0'}
            elif request.url.path.endswith('/resources'):data=resources
            else:data=[{'type':'vzdump','status':'OK'}]
            return httpx.Response(200,json={'data':data})
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test@pve!monitor','PROXMOX_TOKEN_SECRET':'test'}),patch('app.monitoring.proxmox.httpx.AsyncClient',fake_client(handle)):
            r=await proxmox.collect()
        self.assertEqual(r['status'],'UP');self.assertEqual(r['guests'][0]['vmid'],100)

    async def test_proxmox_denied(self):
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test','PROXMOX_TOKEN_SECRET':'test'}),patch('app.monitoring.proxmox.httpx.AsyncClient',fake_client(lambda request:httpx.Response(403))):
            value=await proxmox.collect()
            self.assertEqual(value['status'],'UNKNOWN');self.assertEqual(value['error'],'permission_denied')

    async def test_proxmox_excessive_permission_stops_before_resource_collection(self):
        paths=[]
        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200,json={'data':{'/':{'Sys.Audit':1,'VM.PowerMgmt':1}}})
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test@pve!monitor','PROXMOX_TOKEN_SECRET':'secret','PROXMOX_SSL_VERIFY':'true'}),patch('app.monitoring.proxmox.httpx.AsyncClient',fake_client(handle)):
            value=await proxmox.collect()
        self.assertEqual(value['error'],'excessive_or_unverified_permissions')
        self.assertEqual(paths,['/api2/json/access/permissions'])

    async def test_proxmox_401_is_authentication_failure_and_safe(self):
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test@pve!monitor','PROXMOX_TOKEN_SECRET':'secret','PROXMOX_SSL_VERIFY':'true'}),patch('app.monitoring.proxmox.httpx.AsyncClient',fake_client(lambda request:httpx.Response(401))):
            value=await proxmox.collect()
        self.assertEqual(value['error'],'authentication_failed');self.assertNotIn('secret',json.dumps(value))

    async def test_proxmox_tls_error_is_specific_and_never_exports_credentials(self):
        def fail(request):raise httpx.ConnectError('CERTIFICATE_VERIFY_FAILED',request=request)
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test','PROXMOX_TOKEN_SECRET':'secret-never-show'}),patch('app.monitoring.proxmox.httpx.AsyncClient',fake_client(fail)):
            value=await proxmox.collect()
        self.assertEqual(value['error'],'tls_verification_failed');self.assertNotIn('secret-never-show',json.dumps(value))

    async def test_proxmox_tls_bypass_is_rejected_without_sending_token(self):
        with patch.dict(os.environ,{'PROXMOX_TOKEN_ID':'test','PROXMOX_TOKEN_SECRET':'secret','PROXMOX_SSL_VERIFY':'false'}),patch('app.monitoring.proxmox.httpx.AsyncClient') as client:
            value=await proxmox.collect()
        self.assertEqual(value['error'],'tls_verification_required');client.assert_not_called()

    async def test_router_permission_gate(self):
        cfg=Settings('t',frozenset({1}),'k',('m',))
        self.assertEqual((await MikroTik(cfg).collect())['error'],'readonly_account_required')

    async def test_router_mock_resource_and_permissions(self):
        cfg=Settings('t',frozenset({1}),'k',('m',),mikrotik_readonly=True)
        def resource(path):
            values={'/user':[{'name':'monitor','group':'nms'}],'/user/group':[{'name':'nms','policy':'read,api'}],'/system/identity':[{'name':'router','secret':'must_not_export'}],'/system/resource':[{'cpu-load':'15','total-memory':'100','free-memory':'60'}],'/system/clock':[{'time':'10:00'}]}
            return Mock(call=Mock(return_value=values[path]),call_async=Mock(side_effect=lambda *a:iter(values[path])))
        pool=Mock();pool.get_api.return_value.get_resource.side_effect=resource
        env={'MIKROTIK_USER':'monitor','MIKROTIK_PASSWORD':'test','MIKROTIK_PORT':'8728','MIKROTIK_ALLOW_PLAINTEXT':'true'}
        with patch.dict(os.environ,env),patch('routeros_api.RouterOsApiPool',return_value=pool):
            r=await MikroTik(cfg).collect()
        self.assertEqual(r['status'],'UP');self.assertNotIn('secret',json.dumps(r))
        pool.disconnect.assert_called_once()

    async def test_router_excess_permissions_rejected(self):
        cfg=Settings('t',frozenset({1}),'k',('m',),mikrotik_readonly=True)
        pool=Mock();pool.get_api.return_value.get_resource.side_effect=lambda path:Mock(call=Mock(return_value=[{'group':'read'}] if path=='/user' else [{'policy':'read,api,reboot,sensitive'}]))
        with patch.dict(os.environ,{'MIKROTIK_USER':'monitor','MIKROTIK_PASSWORD':'test','MIKROTIK_ALLOW_PLAINTEXT':'true','MIKROTIK_PORT':'8728'}),patch('routeros_api.RouterOsApiPool',return_value=pool):
            self.assertEqual((await MikroTik(cfg).collect())['error'],'excessive_or_unverified_permissions')

    async def test_allowlist(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Settings('t',frozenset({1}),'k',('m',),data_dir=directory)
            db=Database(directory);monitor=Monitoring(cfg,db);reg=Registry();monitor.register(reg)
            for target in ['169.254.169.254','http://evil','../../etc/shadow']:
                self.assertEqual((await reg.execute('check_service',json.dumps({'target':target})))['error'],'invalid_arguments')
            db.close()

class SnapshotTests(unittest.TestCase):
    def test_snapshot_and_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json'
            sample={'collected_at':time.time(),'docker':{'status':'UP','containers':[{'name':'db','state':'running'}]},'host':{'cpu_percent':12}}
            path.write_text(json.dumps(sample))
            self.assertEqual(read_snapshot(directory,'docker')['status'],'UP')
            self.assertEqual(read_snapshot(directory,'debian')['cpu_percent'],12)
            sample['collected_at']-=300;path.write_text(json.dumps(sample))
            self.assertEqual(read_snapshot(directory,'docker')['error'],'stale_snapshot')

    def test_missing(self):
        self.assertEqual(read_snapshot('/nonexistent','docker')['status'],'UNKNOWN')
