import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock,patch
from app.config import Settings
from app.dashboard.platform import Platform,Forbidden,Conflict,Missing
from app.dashboard.permissions import permissions,require
from app.management.service import Management
from app.management.adapters import validate
from app.management.adapters import Adapters
from app.storage.database import Database
from app.services.health import Monitoring

def session(role='Administrator',username='admin'):return {'user':{'role':role,'username':username}}
def inventory(**extra):return dict(name='Test',host='192.168.20.199',type='dns',methods=['dns'],interval=60,group='Test',tags=[],profile='connectivity',enabled=True,**extra)

class ManagementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.cfg=Settings('t',frozenset({1}),'',('m',),data_dir=self.tmp.name)
  self.store=Platform(self.tmp.name,self.cfg);self.loop=asyncio.new_event_loop();self.thread=threading.Thread(target=self.loop.run_forever,daemon=True);self.thread.start()
  self.service=Management(self.store,loop=self.loop)
  self.service.adapters.inspect=AsyncMock(return_value={'before':{'status':'stopped'},'allowed':True,'blocker':None,'target':'192.168.20.200'})
  self.service.adapters.execute=AsyncMock(return_value={'state':'VERIFIED','after':{'status':'running'}})
  self.env=patch.dict(os.environ,{'NMS_DEVICE_WRITES_ENABLED':'true'});self.env.start()
 def tearDown(self):
  self.loop.call_soon_threadsafe(self.loop.stop);self.thread.join();self.loop.close();self.env.stop();self.tmp.cleanup()
 def preview(self):return self.service.preview({'operation':'proxmox.guest.start','params':{'node':'pve','kind':'qemu','vmid':100}},session())
 def body(self,plan):return {'phrase':'APPLY '+plan['id'],'confirmation':plan['confirmation']}
 def test_confirm_executes_once_and_persists_verified_audit(self):
  plan=self.preview();self.assertTrue(plan['allowed']);body=self.body(plan)
  self.service.confirm(plan['id'],body,session())
  for _ in range(100):
   if self.service.list(session())['items'][0]['state']!='APPLYING':break
   time.sleep(.01)
  self.assertEqual(self.service.list(session())['items'][0]['state'],'VERIFIED');self.service.adapters.execute.assert_awaited_once()
  with self.assertRaises(Conflict):self.service.confirm(plan['id'],body,session())
  self.assertNotIn(plan['confirmation'],json.dumps(self.store.audit_page({})))
  self.assertEqual(self.store.audit_page({})['total'],3)
 def test_expiry_owner_nonce_permission_and_policy_denied_without_write(self):
  plan=self.preview()
  for role in ('Viewer','Operator','Network Administrator'):
   with self.assertRaises(Forbidden):self.service.confirm(plan['id'],self.body(plan),session(role))
  with self.assertRaises(Missing):self.service.confirm(plan['id'],self.body(plan),session(username='another'))
  with self.assertRaises(ValueError):self.service.confirm(plan['id'],dict(self.body(plan),confirmation='wrong'),session())
  with self.store.db() as db:db.execute('UPDATE change_plans SET expires=0')
  with self.assertRaises(Conflict):self.service.confirm(plan['id'],self.body(plan),session())
  with patch.dict(os.environ,{'NMS_DEVICE_WRITES_ENABLED':'false'}):
   with self.assertRaises(ValueError):self.service.confirm(plan['id'],self.body(plan),session())
  self.service.adapters.execute.assert_not_called()
 def test_blocked_preview_and_connection_error_are_explicit(self):
  self.service.adapters.inspect=AsyncMock(return_value={'before':{},'allowed':False,'blocker':'power_permission_required','target':'pve'})
  plan=self.preview();self.assertFalse(plan['allowed'])
  with self.assertRaises(ValueError):self.service.confirm(plan['id'],self.body(plan),session())
  self.service.adapters.inspect=AsyncMock(side_effect=OSError('password-must-never-return'))
  self.assertEqual(self.preview()['blocker'],'device_connection_or_tls_failed')
 def test_restart_marks_interrupted_write_unknown_without_replay(self):
  plan=self.preview()
  with self.store.db() as db:db.execute("UPDATE change_plans SET state='APPLYING' WHERE id=?",(plan['id'],))
  recovered=Management(self.store,loop=self.loop);self.assertEqual(recovered.list(session())['items'][0]['state'],'UNKNOWN')
  self.service.adapters.execute.assert_not_called()
 def test_role_matrix_and_operation_schema(self):
  self.assertIn('network.change',permissions(session('Network Administrator')))
  self.assertNotIn('server.operate',permissions(session('Network Administrator')))
  self.assertNotIn('network.change',permissions(session('Server Administrator')))
  self.assertIn('credentials.manage',permissions(session('Super Administrator')))
  for operation,params in [('shell',{}),('routeros.interface.comment',{'interface':'ether1;reboot','comment':''}),('proxmox.guest.start',{'node':'../evil','kind':'qemu','vmid':100}),('proxmox.guest.start',{'node':'pve','kind':'qemu','vmid':100,'force':True})]:
   with self.assertRaises(ValueError):validate(operation,params)

class InventoryEnrollmentTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.cfg=Settings('t',frozenset({1}),'',('m',),data_dir=self.tmp.name,continuous_enabled=False)
  self.db=Database(self.tmp.name);self.monitor=Monitoring(self.cfg,self.db);self.store=self.monitor.platform
 async def asyncTearDown(self):self.db.close();self.tmp.cleanup()
 async def test_target_joins_shared_engine_and_cache_then_disable_retires(self):
  item=self.store.save('inventory',{'value':inventory(monitor_method='dns',monitor_port=53,dns_query='example.com')},'admin');target='inventory_'+item['id']
  with patch('app.monitoring.inventory.dns.probe',AsyncMock(return_value={'target':target,'status':'UP','method':'DNS','timestamp':'2026-10-26T00:00:00+00:00'})) as probe:
   await self.monitor.check(target);await self.monitor.check(target);probe.assert_awaited_once()
  item['enabled']=False;value={k:v for k,v in item.items() if k not in {'id','revision','created_at','updated_at'}}
  self.store.save('inventory',{'revision':item['revision'],'value':value},'admin',item['id'])
  self.assertEqual((await self.monitor.check(target))['error'],'target_not_allowed')
 async def test_credential_host_binding_and_ssrf(self):
  for value in [inventory(monitor_method='routeros',credential_ref='routeros-default'),inventory(monitor_method='icmp',credential_ref='proxmox-default'),dict(inventory(monitor_method='http',monitor_url='http://127.0.0.1/'))]:
   with self.assertRaises(ValueError):self.store.save('inventory',{'value':value},'admin')
 async def test_topology_inventory_reference_and_delete_dependency(self):
  item=self.store.save('inventory',{'value':inventory()},'admin')
  graph=self.store.save('topologies',{'value':{'name':'Actual inventory reference','nodes':[dict(id='test',name='DNS',kind='dns',x=100,y=100,device_id=item['id'])],'links':[]}},'admin')
  with self.assertRaises(ValueError):self.store.remove('inventory',item['id'],1,'admin')
  self.store.remove('topologies',graph['id'],1,'admin');self.store.remove('inventory',item['id'],1,'admin')
 async def test_existing_collector_reference_does_not_create_duplicate_poll(self):
  item=self.store.save('inventory',{'value':dict(inventory(),host='192.168.20.200',monitor_method='proxmox',credential_ref='proxmox-default')},'admin')
  self.assertEqual(self.store.inventory_target(item),'proxmox_resources')
  self.assertFalse(__import__('app.monitoring.inventory',fromlist=['scheduled']).scheduled(item))
 async def test_http_inventory_reuses_existing_launcher_monitor(self):
  service=self.store.save('integrations',{'value':dict(name='DNS console',url='http://192.168.20.199:5380/',kind='dns',enabled=True,monitor_enabled=True,poll_interval=60)},'admin')
  item=self.store.save('inventory',{'value':inventory(monitor_method='http',monitor_url='http://192.168.20.199:5380/')},'admin')
  self.assertEqual(self.store.inventory_target(item),'service_'+service['id'])
  with patch('app.services.health.service_probe',AsyncMock(return_value={'target':'service_'+service['id'],'status':'UP','method':'HTTP','configuration_hash':__import__('hashlib').sha256(service['url'].encode()).hexdigest()})) as probe:
   await self.monitor.check('inventory_'+item['id']);await self.monitor.check('service_'+service['id'])
   probe.assert_awaited_once()
 async def test_ai_inventory_tool_is_read_only_and_uses_bound_collector(self):
  from app.ai.tool_registry import Registry
  item=self.store.save('inventory',{'value':dict(inventory(),host='192.168.20.200',monitor_method='proxmox',credential_ref='proxmox-default')},'admin')
  registry=Registry();self.monitor.register(registry);self.monitor.check=AsyncMock(return_value={'status':'UP'})
  await registry.execute('check_inventory_device',json.dumps({'device_id':item['id']}));self.monitor.check.assert_awaited_once_with('proxmox_resources')
  rejected=await registry.execute('check_inventory_device',json.dumps({'device_id':item['id'],'command':'reboot'}));self.assertEqual(rejected['error'],'invalid_arguments')

class AdapterWriteGuardsTests(unittest.IsolatedAsyncioTestCase):
 async def test_routeros_write_preview_blocks_plaintext_before_connect(self):
  adapter=Adapters();adapter.router_api=unittest.mock.Mock()
  with patch.dict(os.environ,{'MIKROTIK_PORT':'8728'}):value=await adapter.inspect('routeros.interface.comment',{'interface':'ether1','comment':'test'})
  self.assertFalse(value['allowed']);self.assertEqual(value['blocker'],'verified_api_ssl_required_for_writes');adapter.router_api.assert_not_called()

 async def test_live_state_conflict_or_permission_prevents_mutation(self):
  adapter=Adapters();adapter.inspect=AsyncMock(return_value={'allowed':False,'blocker':'power_permission_required','before':{}})
  adapter.pve_client=unittest.mock.Mock()
  value=await adapter.execute('proxmox.guest.start',{'node':'pve','kind':'qemu','vmid':100},{'status':'stopped'})
  self.assertEqual(value['state'],'BLOCKED');adapter.pve_client.assert_not_called()
  adapter.inspect=AsyncMock(return_value={'allowed':True,'before':{'status':'running'}})
  self.assertEqual((await adapter.execute('proxmox.guest.start',{}, {'status':'stopped'}))['state'],'CONFLICT');adapter.pve_client.assert_not_called()
 async def test_proxmox_auditor_preview_never_claims_power_permission(self):
  from unittest.mock import MagicMock
  adapter=Adapters();client=MagicMock();adapter.pve_client=MagicMock(return_value=client)
  adapter.pve_get=AsyncMock(side_effect=[{'/vms/100':{'VM.Audit':1}}, {'status':'running'}])
  value=await adapter.inspect('proxmox.guest.reboot',{'node':'pve','kind':'qemu','vmid':100})
  self.assertFalse(value['allowed']);self.assertEqual(value['blocker'],'proxmox_monitoring_only_policy')
 async def test_untrusted_operation_container_is_validation_error(self):
  with self.assertRaises(ValueError):validate([], {})
