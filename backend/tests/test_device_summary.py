import tempfile,time,unittest
from types import SimpleNamespace
from app.config import Settings
from app.storage.database import Database
from app.dashboard.platform_api import PlatformAPI
from app.dashboard.device_summary import summarize


class DeviceSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Settings('test',frozenset({1}),'',('m',),data_dir=self.tmp.name,poll_interval=60)
        self.db=Database(self.tmp.name);self.api=PlatformAPI(SimpleNamespace(settings=self.cfg))
        self.api.store.sync_inventory()
        self.devices={i['host']:i for i in self.api.store.list('inventory')}
        self.router=self.devices['192.168.20.1']
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def sample(self,target,**values):
        self.db.save(dict(target=target,status='UP',method='read-only test',**values))
    def test_legacy_icmp_or_tcp_inventory_shows_owned_router_api_and_all_interfaces(self):
        self.sample('mikrotik',host=self.router['host'])
        self.sample('mikrotik_system',data={'/system/resource':[{'cpu-load':'19','total-memory':'1000','free-memory':'600','total-hdd-space':'2000','free-hdd-space':'1000'}]})
        self.sample('mikrotik_interfaces',data={'/interface':[{'name':'ether'+str(i),'running':'true','rx-byte':str(i),'tx-byte':'99'} for i in range(40)]})
        self.sample('debian',cpu_percent=91)
        value=self.api.inventory_status(self.router)
        self.assertEqual(value['telemetry']['cpu_percent'],19)
        self.assertEqual(value['telemetry']['memory_percent'],40)
        self.assertEqual(len(value['telemetry']['interfaces']),40)
        self.assertIn('interfaces',value['enabled_categories'])
        self.assertNotIn('debian',[c['target'] for c in value['collectors']])
        self.assertEqual(value['metric_sources']['cpu_percent']['collector'],'mikrotik_system')
    def test_proxmox_and_debian_do_not_exchange_guests_or_containers(self):
        self.sample('proxmox_resources',nodes=[dict(node='pve',cpu=.4,mem=200,maxmem=1000)],guests=[dict(vmid=100,name='vm',type='qemu',maxmem=1000,mem=100,netin=30,netout=40)])
        self.sample('docker',containers=[dict(name='nms',state='running',memory_bytes=123)])
        prox=self.api.inventory_status(self.devices['192.168.20.200'])
        host=self.api.inventory_status(self.devices['192.168.20.195'])
        self.assertEqual(prox['telemetry']['guests'][0]['netin'],30)
        self.assertNotIn('containers',prox['telemetry'])
        self.assertEqual(host['telemetry']['containers'][0]['name'],'nms')
        self.assertNotIn('guests',host['telemetry'])
    def test_old_ip_stale_and_disabled_samples_never_supply_metrics(self):
        self.sample('mikrotik_system',host='192.168.20.99',cpu_percent=90)
        value=self.api.inventory_status(self.router)
        self.assertNotIn('cpu_percent',value['telemetry'])
        self.sample('mikrotik_system',cpu_percent=70)
        with self.db.db:self.db.db.execute("UPDATE checks SET ts=? WHERE target='mikrotik_system'",(time.time()-10000,))
        self.assertNotIn('cpu_percent',self.api.inventory_status(self.router)['telemetry'])
        self.assertEqual(self.api.inventory_status({**self.router,'enabled':False})['collectors'],[])
    def test_explicit_empty_categories_stay_disabled_and_newer_rates_win(self):
        item=dict(id='inv',host='192.168.20.1',name='Router',enabled=True,monitor_categories=[])
        samples={'snmp':dict(status='UP',sample_epoch=100,interfaces=[dict(name='ether1',rx_bps=10,mtu=1500)]),'api':dict(status='UP',sample_epoch=110,interfaces=[dict(name='ether1',rx_bps=30,tx_bps=40)])}
        value=summarize(item,'snmp',samples)
        self.assertEqual(value['enabled_categories'],[])
        self.assertIn('interfaces',value['supported_categories'])
        self.assertEqual(value['telemetry']['interfaces'][0]['rx_bps'],30)
        self.assertEqual(value['telemetry']['interfaces'][0]['mtu'],1500)
    def test_switching_method_does_not_validate_new_capabilities_against_old_ping(self):
        self.sample('mikrotik',host=self.router['host'])
        self.api.validate_monitor_categories({**self.router,'monitor_method':'snmp','monitor_categories':['network_status','interfaces']},self.router['id'])
