import copy
import tempfile
import unittest
from app.config import Settings
from app.dashboard.platform import Platform
from app.dashboard import models
from app.dashboard.topology_verification import verify
import test_dashboard_sessions as helpers


class TopologyVerificationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Settings('test',frozenset({1}),'',('m',),data_dir=self.tmp.name,targets={
            'mikrotik':dict(name='router',host='192.168.20.1',port=8291,kind='tcp'),
            'peer':dict(name='switch',host='192.168.20.2',kind='icmp')})
        self.store=Platform(self.tmp.name,self.cfg);self.store.sync_inventory()
        byhost={item['host']:item for item in self.store.list('inventory')}
        self.a,self.b=byhost['192.168.20.1'],byhost['192.168.20.2']
        self.graph=dict(name='Test',nodes=[dict(id='a',name='Router',kind='router',device_id=self.a['id'],x=100,y=100),dict(id='b',name='Switch',kind='switch',device_id=self.b['id'],x=500,y=100)],links=[dict(id='e',source='a',target='b',type='Ethernet',label='',source_port='ether2')])
        self.samples={target:dict(status='UP',sample_epoch=990,stale_after_seconds=180,stale=False,interfaces=[],data={}) for target in ('mikrotik','peer','mikrotik_interfaces','mikrotik_neighbors')}
        self.samples['mikrotik_neighbors']['data']={'/ip/neighbor':[dict(address=self.b['host'],interface='ether2',**{'discovered-by':'lldp'})]}
        self.samples['mikrotik_interfaces']['data']={'/interface':[dict(name='ether2',running='true',**{'rx-byte':'123','tx-byte':'456'})]}
    def tearDown(self):self.tmp.cleanup()
    def check(self):return verify(self.graph,self.store,self.samples,1000)
    def test_verified_relationship_has_bounded_expiry_and_real_port_counters(self):
        row=self.check();self.assertTrue(row['valid']);self.assertTrue(row['links'][0]['animate'])
        self.assertEqual(row['links'][0]['expires_at'],1110)
        self.assertEqual(row['links'][0]['traffic'],{'rx-byte':'123','tx-byte':'456'})
        self.assertEqual(row['links'][0]['evidence'][0]['remote_host'],self.b['host'])
    def test_ping_up_mndp_or_manual_evidence_never_prove_cable(self):
        self.graph['links'][0]['evidence']='verified'
        for protocol in ('','mndp'):
            self.samples['mikrotik_neighbors']['data']['/ip/neighbor'][0]['discovered-by']=protocol
            self.assertFalse(self.check()['links'][0]['animate'])
        self.samples.pop('mikrotik_neighbors');self.assertFalse(self.check()['valid'])
    def test_stale_future_disabled_and_port_down_block_animation(self):
        original=copy.deepcopy(self.samples)
        for key,patch in [('mikrotik_neighbors',dict(sample_epoch=800)),('peer',dict(status='DOWN')),('peer',dict(sample_epoch=1050)),('mikrotik_interfaces',dict(stale=True))]:
            self.samples=copy.deepcopy(original);self.samples[key].update(patch)
            self.assertFalse(self.check()['links'][0]['animate'])
        self.samples=original;self.samples['mikrotik_interfaces']['data']['/interface'][0]['running']='false'
        self.assertFalse(self.check()['links'][0]['verified'])
    def test_wrong_port_ip_and_foreign_collector_are_not_accepted(self):
        self.graph['links'][0]['source_port']='ether5';self.assertEqual(self.check()['links'][0]['status'],'MISMATCH')
        self.graph['links'][0]['source_port']='ether2';self.graph['nodes'][1]['collector']='mikrotik_interfaces'
        self.assertFalse(self.check()['nodes'][1]['recognized']);self.assertFalse(self.check()['valid'])
        self.graph['nodes'][1].pop('collector');self.samples['peer']['host']='192.168.20.99'
        self.assertFalse(self.check()['nodes'][1]['recognized'])
    def test_target_port_requires_reciprocal_neighbor_and_route_needs_specific_evidence(self):
        self.graph['links'][0]['target_port']='port1';self.assertFalse(self.check()['valid'])
        self.samples['peer'].update(interfaces=[dict(name='port1',status='UP')],data={'/ip/neighbor':[dict(address=self.a['host'],interface='port1',**{'discovered-by':'cdp'})]})
        self.assertTrue(self.check()['valid'])
        self.graph['links'][0]['type']='Routing';self.assertFalse(self.check()['valid'])
    def test_view_and_waypoints_survive_real_sqlite_roundtrip(self):
        self.graph['view']=dict(x=-123.5,y=40.25,zoom=.25)
        self.graph['links'][0]['points']=[dict(x=200,y=300)]
        saved=self.store.save('topologies',{'value':self.graph},'tester')
        restored=Platform(self.tmp.name).get('topologies',saved['id'])
        self.assertEqual(restored['view'],self.graph['view']);self.assertEqual(restored['links'][0]['points'],self.graph['links'][0]['points'])
        for zoom in (float('nan'),float('inf'),0,100):
            self.graph['view']['zoom']=zoom
            with self.assertRaises(ValueError):models.record('topologies',self.graph,[],self.store.targets())
    def test_guest_reference_never_inherits_parent_management_ip_or_link(self):
        self.graph['nodes'][1].update(resource_id='qemu/100',collector='proxmox_resources')
        self.samples['proxmox_resources']=dict(status='UP',sample_epoch=990,guests=[dict(id='qemu/100',status='running')])
        row=self.check()
        self.assertTrue(row['nodes'][1]['recognized']);self.assertFalse(row['nodes'][1]['ready'])
        self.assertNotIn('host',row['nodes'][1]);self.assertFalse(row['links'][0]['verified'])


class TopologyHTTPTests(unittest.TestCase):
    setUp=helpers.SessionAPITests.setUp
    tearDown=helpers.SessionAPITests.tearDown
    request=helpers.SessionAPITests.request
    login=helpers.SessionAPITests.login
    def test_verification_uses_authenticated_bounded_post_and_audits_result(self):
        value=dict(name='Manual',nodes=[dict(id='n',name='Unbound',kind='router',x=10,y=10)],links=[])
        path='/api/platform/topology-verify'
        self.assertEqual(self.request(path,'POST',dict(value=value))[0],401)
        self.login()
        status,body,_=self.request(path,'POST',dict(value=value))
        self.assertEqual(status,200);self.assertFalse(body['valid']);self.assertFalse(body['nodes'][0]['recognized'])
        self.assertEqual(self.server.platform.store.audit_page({})['items'][0]['action'],'topology.verify')
        self.assertEqual(self.request(path,'POST',dict(value=value),headers={'Origin':'https://untrusted.example'})[0],403)
