import asyncio
import json
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
from app.config import Settings
from app.storage.database import Database
from app.services.health import Monitoring

def inventory(**extra):return dict(name='Test',host='192.168.20.199',type='dns',methods=['dns'],interval=60,group='Test',tags=[],profile='connectivity',enabled=True,**extra)

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
