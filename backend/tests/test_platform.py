import asyncio
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch,AsyncMock,Mock
from app.config import Settings
from app.storage.database import Database
from app.dashboard import models
from app.dashboard.platform import Platform,Conflict
from app.dashboard.credentials import CredentialVault,CredentialVaultUnavailable
from app.dashboard.sessions import Sessions
from app.dashboard.reports import report
from app.alerts.outbox import Outbox
import test_dashboard_sessions as helpers

class PlatformStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Settings('x',frozenset({1}),'',('m',),data_dir=self.tmp.name,poll_interval=60)
        self.store=Platform(self.tmp.name,self.cfg)
    def tearDown(self):self.tmp.cleanup()
    def service(self):return dict(name='DNS dashboard',url='http://192.168.20.199:5380/',kind='dns',enabled=True,monitor_enabled=False,collector='technitium_dns')
    def test_seed_and_crud_survive_restart_with_optimistic_lock(self):
        item=self.store.save('integrations',{'value':self.service()},'admin')
        self.assertEqual(Platform(self.tmp.name).get('integrations',item['id'])['name'],'DNS dashboard')
        value=self.service();value['enabled']=False
        self.assertEqual(self.store.save('integrations',{'revision':1,'value':value},'admin',item['id'])['revision'],2)
        with self.assertRaises(Conflict):self.store.save('integrations',{'revision':1,'value':value},'admin',item['id'])
        with self.assertRaises(Conflict):self.store.remove('integrations',item['id'],1,'admin')
        self.store.remove('integrations',item['id'],2,'admin');self.assertIsNone(self.store.get('integrations',item['id']))
        self.assertEqual(self.store.audit_page({})['total'],3)
    def test_service_url_ssrf_and_secret_fields_rejected(self):
        for address in ('http://127.0.0.1/','http://169.254.169.254/','http://192.168.20.199@evil.test/','javascript:alert(1)','http://192.168.20.199/?token=secret','http://user:pass@192.168.20.199/','http://192.168.20.199/#token','https://evil.test/'):
            with self.subTest(address=address),self.assertRaises(ValueError):self.store.save('integrations',{'value':dict(self.service(),url=address)},'admin')
        with self.assertRaises(ValueError):self.store.save('integrations',{'value':dict(self.service(),password='never')},'admin')
    def test_settings_apply_only_supported_fields_and_revision(self):
        old=self.store.get_settings();value=old['value'];value['poll_interval']=120
        saved=self.store.save_settings({'revision':old['revision'],'value':value},'admin')
        self.assertIsNone(saved['applied_at']);self.store.apply(self.cfg);self.assertEqual(self.cfg.poll_interval,120)
        self.assertIsNotNone(self.store.get_settings()['applied_at'])
        for key,val in [('poll_interval',0),('timezone','evil'),('retention_days',999),('alerts','true')]:
            with self.subTest(key=key),self.assertRaises(ValueError):models.settings(dict(value,**{key:val}))
        with self.assertRaises(ValueError):models.settings(dict(value,router_password='secret'))
    def test_topology_roundtrip_positions_edges_and_invalid_references(self):
        value={'name':'LAN','nodes':[{'id':'router','name':'MikroTik','kind':'router','x':230,'y':160,'collector':'mikrotik_system'}, {'id':'pve','name':'Proxmox','kind':'proxmox','x':510,'y':200}],'links':[{'id':'e1','source':'router','target':'pve','type':'Ethernet','label':'LAN'}]}
        item=self.store.save('topologies',{'value':value},'admin')
        reloaded=Platform(self.tmp.name).get('topologies',item['id']);self.assertEqual(reloaded['nodes'][0]['x'],230);self.assertEqual(reloaded['links'][0]['target'],'pve')
        value['links'][0]['target']='missing'
        with self.assertRaises(ValueError):self.store.save('topologies',{'revision':1,'value':value},'admin',item['id'])
        self.assertEqual(self.store.get('topologies',item['id'])['revision'],1)
    def test_export_restore_is_atomic_and_has_no_credentials(self):
        backup=self.store.export_config();self.assertNotIn('password',json.dumps(backup));self.assertNotIn('hash',json.dumps(backup))
        self.assertTrue(self.store.restore(backup,'admin')['ok'])
        backup['collections']['topologies']=[{'id':'bad','name':'bad','nodes':[{}],'links':[]}]
        before=self.store.list('integrations')
        with self.assertRaises(ValueError):self.store.restore(backup,'admin')
        self.assertEqual(self.store.list('integrations'),before)
    def test_restore_keeps_revisions_monotonic_and_rejects_monitor_limit_bypass(self):
        before=self.store.list('integrations')[0];backup=self.store.export_config()
        self.store.restore(backup,'admin');self.assertGreater(self.store.get('integrations',before['id'])['revision'],before['revision'])
        sample=self.service();sample.update(collector='',monitor_enabled=True)
        backup=self.store.export_config();backup['collections']['integrations']=[dict(sample,id='svc_'+str(i)) for i in range(41)]
        with self.assertRaises(ValueError):self.store.restore(backup,'admin')

    def test_inventory_validation_and_duplicate(self):
        value=dict(name='Router',host='192.168.20.1',type='router',vendor='',model='',methods=['api'],interval=60,group='LAN',tags=['core'],profile='network',enabled=True)
        self.store.save('inventory',{'value':value},'admin')
        with self.assertRaises(Conflict):self.store.save('inventory',{'value':value},'admin')
        self.assertEqual(len(self.store.list('inventory')),1)
    def test_accounts_password_hash_and_session_revocation(self):
        self.store.bootstrap('admin-test-'+'A'*30)
        sessions=Sessions(self.tmp.name,'viewer-test-'+'B'*30)
        login=sessions.login('admin','admin-test-'+'A'*30);self.assertEqual(login[1]['user']['role'],'Administrator')
        self.store.save_user(dict(username='operator1',name='Operator',role='Operator',enabled=True,password='test-only-'+'C'*30),'admin')
        userlogin=sessions.login('operator1','test-only-'+'C'*30);self.assertIsNotNone(sessions.read(userlogin[0]))
        self.store.save_user(dict(username='operator1',name='Operator',role='Read-only operator',enabled=False,revision=1),'admin')
        self.assertIsNone(sessions.read(userlogin[0]))
        self.assertNotIn('test-only-',json.dumps(self.store.users()))
        with self.store.db() as db:
            raw=db.execute('SELECT hash FROM accounts WHERE username=?',('operator1',)).fetchone()[0]
        self.assertEqual(len(raw),64);self.assertNotIn('test-only-',raw)
        self.assertIsNone(sessions.login('unknown','bad'))
    def test_migrate_legacy_sessions(self):
        p=Path(self.tmp.name)/'dashboard-auth.sqlite3'
        with closing(sqlite3.connect(p)) as db:db.execute('CREATE TABLE sessions(digest TEXT PRIMARY KEY,created REAL,seen REAL,expires REAL,idle INTEGER)')
        session=Sessions(self.tmp.name,'x'*30);login=session.login('nms','x'*30)
        self.assertEqual(session.read(login[0])['user']['username'],'nms')
    def test_maintenance_prefix_and_time_boundaries(self):
        self.store.save('maintenance',{'value':dict(name='Router upkeep',scope='network:link:ether4',start=100,end=200,enabled=True)},'admin')
        self.assertTrue(self.store.maintenance('network:link:ether4',100));self.assertFalse(self.store.maintenance('network:link:ether3',150));self.assertFalse(self.store.maintenance('network:link:ether4',200))

class CredentialVaultTests(unittest.TestCase):
    def test_aes_gcm_roundtrip_redaction_aad_and_fail_closed(self):
        key=base64.urlsafe_b64encode(b'A'*32).decode().rstrip('=')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'NMS_CREDENTIALS_KEY':key}):
            store=Platform(directory);vault=CredentialVault(store)
            value={'gui':{'username':'router-admin','password':'gui-secret','fields':[{'id':'api-token','label':'Token API','type':'api_key','value':'custom-secret'}]},
                'wifi_networks':[{'id':'ssid1','ssid':'Homelab-5G','password':'wifi-secret'}], 'custom_fields':[{'id':'ssh-user','label':'SSH username','type':'username','value':'azril'}],
                'snmp':dict(CredentialVault.EMPTY['snmp']),'ssh':dict(CredentialVault.EMPTY['ssh'])}
            vault.save('integration','int_'+'a'*24,value,'admin')
            self.assertEqual(vault.read('integration','int_'+'a'*24,'admin')['credentials'],value)
            with store.db() as db:
                nonce,ciphertext=db.execute('SELECT nonce,ciphertext FROM credential_records').fetchone()
                audit=json.dumps(store.audit_page({}))
            self.assertEqual(len(nonce),12);self.assertNotIn(b'gui-secret',ciphertext);self.assertNotIn(b'wifi-secret',ciphertext);self.assertNotIn('custom-secret',audit)
            with store.db() as db:db.execute('UPDATE credential_records SET target_id=?',('int_'+'b'*24,))
            with self.assertRaises(CredentialVaultUnavailable):vault.read('integration','int_'+'b'*24,'admin')
            with patch.dict(os.environ, {'NMS_CREDENTIALS_KEY':base64.urlsafe_b64encode(b'B'*32).decode().rstrip('=')}):
                with self.assertRaises(CredentialVaultUnavailable):vault.read('integration','int_'+'b'*24,'admin')
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'NMS_CREDENTIALS_KEY':''}):
            with self.assertRaises(CredentialVaultUnavailable):CredentialVault(Platform(directory)).read('device','device_'+'a'*12,'admin')

    def test_custom_field_schema_is_strict(self):
        invalid=[{'gui':{'username':'','password':'','fields':[{'id':'bad','label':'key','type':'shell','value':'x'}]},'wifi_networks':[],'custom_fields':[]},
            {'gui':{'username':'','password':'','fields':[]},'wifi_networks':[{'id':'x','ssid':'ssid','password':'pw','username':'admin'}],'custom_fields':[]}]
        for value in invalid:
            with self.subTest(value=value),self.assertRaises(ValueError):CredentialVault.validate(value)


class PlatformAPITests(unittest.TestCase):
    setUp=helpers.SessionAPITests.setUp;tearDown=helpers.SessionAPITests.tearDown;request=helpers.SessionAPITests.request;login=helpers.SessionAPITests.login
    def admin(self):
        self.server.platform.store.bootstrap('test-admin-'+'X'*30)
        code,_,headers=self.request('/api/auth/login','POST',dict(username='admin',password='test-admin-'+'X'*30))
        self.assertEqual(code,200);self.cookie=headers['Set-Cookie'].split(';')[0]
    def test_network_admin_config_scope_cannot_cross_into_security_or_server_writes(self):
        self.server.platform.store.save_user(dict(username='netadmin',name='Network Admin',role='Network Administrator',enabled=True,password='test-only-'+'N'*30),'admin')
        code,_,headers=self.request('/api/auth/login','POST',dict(username='netadmin',password='test-only-'+'N'*30))
        self.assertEqual(code,200);self.cookie=headers['Set-Cookie'].split(';')[0]
        value=dict(name='Router',host='192.168.20.1',type='router',methods=['api'],interval=60,profile='network',enabled=True)
        self.assertEqual(self.request('/api/platform/inventory','POST',{'value':value})[0],200)
        self.assertEqual(self.request('/api/platform/settings','POST',{})[0],403)
        self.assertEqual(self.request('/api/platform/users')[0],403)
        self.assertEqual(self.request('/api/platform/audit')[0],200)
        self.assertEqual(self.request('/api/platform/management/preview','POST',dict(operation='proxmox.guest.start',params=dict(node='pve',kind='qemu',vmid=100)))[0],403)
        self.admin()
        self.assertEqual(self.request('/api/platform/management/preview','POST',dict(operation='proxmox.guest.start',params=dict(node='pve',kind='qemu',vmid=100)))[0],404)
    def test_auth_and_rbac_enforced_on_server(self):
        self.assertEqual(self.request('/api/platform')[0],401)
        self.login();self.assertFalse(self.request('/api/platform')[1]['capabilities']['manage'])
        for path in ('/api/platform/topologies','/api/platform/settings','/api/platform/users'):
            self.assertEqual(self.request(path,'POST',{})[0],403)
        self.assertEqual(self.request('/api/platform/users')[0],403)
        self.admin();self.assertTrue(self.request('/api/platform')[1]['capabilities']['manage'])
        self.assertEqual(self.request('/api/platform/users')[0],200)
    def test_device_backup_routes_require_backup_role_and_audit_scope(self):
        self.login()
        self.assertEqual(self.request('/api/platform/device-backups')[0],403)
        self.assertEqual(self.request('/api/platform/device-backups/inv_'+'a'*24+'/run','POST',{})[0],403)
        self.admin()
        fake=Mock()
        fake.catalog.return_value={'devices':[],'runs':[],'restore_mode':'manual-native-gui'}
        fake.start_manual.return_value={'id':'run_'+'b'*24,'state':'RUNNING'}
        fake.save_policy.return_value={'enabled':True}
        fake.prepare_restore.return_value={'mode':'manual-native-gui'}
        self.server.platform.device_backups=fake
        self.assertEqual(self.request('/api/platform/device-backups')[0],200)
        self.assertEqual(self.request('/api/platform/device-backups/inv_'+'a'*24+'/run','POST',{})[0],200)
        self.assertEqual(self.request('/api/platform/device-backups/inv_'+'a'*24+'/policy','POST',{'enabled':True,'interval_seconds':3600,'retention_versions':5})[0],200)
        self.assertEqual(self.request('/api/platform/device-backups/backup_'+'c'*24+'/restore','POST',{'confirmation':'RESTORE backup_'+'c'*24})[0],200)
    def test_topology_api_conflict_and_delete(self):
        self.admin();value=dict(name='Test',nodes=[],links=[])
        code,item,_=self.request('/api/platform/topologies','POST',{'value':value});self.assertEqual(code,200)
        url='/api/platform/topologies/'+item['id']
        self.assertEqual(self.request(url)[1]['item']['name'],'Test')
        self.assertEqual(self.request(url,'POST',dict(revision=99,value=value))[0],409)
        self.assertEqual(self.request(url+'/delete','POST',dict(revision=1))[0],200)
        self.assertEqual(self.request(url)[0],404)
    def test_csrf_for_admin_config_and_unknown_fields(self):
        self.admin()
        self.assertEqual(self.request('/api/platform/topologies','POST',dict(value=dict(name='x',nodes=[],links=[])),{'Origin':'https://evil.test'})[0],403)
        self.assertEqual(self.request('/api/platform/topologies','POST',dict(value=dict(name='x',nodes=[],links=[],shell='uname')))[0],400)
    def test_ack_is_persistent_and_does_not_resolve_or_notify(self):
        self.db.event('test','ALERT',dict(kind='ALERT',time=time.time(),key='test',value={'status':'DOWN'}))
        self.admin();inc=self.request('/api/incidents')[1]['items'][0]
        count=self.db.db.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        self.assertEqual(self.request('/api/platform/acknowledge/'+inc['id'],'POST',{'note':'Investigating'})[0],200)
        detail=self.request('/api/incidents/'+inc['id'])[1]
        self.assertEqual(detail['incident']['acknowledgment']['actor'],'admin')
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],count)
    def test_configured_service_test_uses_cache_without_probe(self):
        self.admin()
        value=dict(name='Debian',url='http://192.168.20.195/',kind='server',enabled=True,collector='debian')
        code,item,_=self.request('/api/platform/integrations','POST',{'value':value});self.assertEqual(code,200)
        with patch('app.dashboard.platform_api.probe',AsyncMock()) as probe:
            result=self.request('/api/platform/integrations/'+item['id']+'/test','POST',{})
        self.assertEqual(result[1]['source'],'shared-monitoring-cache');probe.assert_not_called()
    def test_batch_import_validates_all_before_writing(self):
        self.admin();value=dict(name='Router',host='192.168.20.1',type='router',methods=['api'],interval=60,profile='network',enabled=True)
        self.assertEqual(self.request('/api/platform/inventory/import','POST',dict(devices=[value,dict(value,host='127.0.0.1')]))[0],400)
        self.assertEqual(self.server.platform.store.list('inventory'),[])
    def test_assistant_unavailable_is_explicit_and_no_question_in_audit(self):
        self.login();self.assertEqual(self.request('/api/platform/ask','POST',{'question':'Secret example question'})[0],400)
        self.assertNotIn('Secret example question',json.dumps(self.server.platform.store.audit_page({})))
    def test_credentials_api_is_admin_only_separate_and_fails_closed(self):
        key=base64.urlsafe_b64encode(b'C'*32).decode().rstrip('=')
        with patch.dict(os.environ,{'NMS_CREDENTIALS_KEY':key}):
            self.admin()
            code,item,_=self.request('/api/platform/integrations','POST',{'value':dict(name='DNS dashboard',url='http://192.168.20.199:5380/',kind='dns',enabled=True)})
            self.assertEqual(code,200)
            path='/api/platform/credentials/integration/'+item['id']
            value={'gui':{'username':'dns-admin','password':'gui-secret','fields':[]},'wifi_networks':[{'id':'ssid-a','ssid':'Home-5G','password':'wifi-secret'}], 'custom_fields':[], 'snmp':dict(CredentialVault.EMPTY['snmp']), 'ssh':dict(CredentialVault.EMPTY['ssh'])}
            self.assertEqual(self.request(path,'POST',{'credentials':value})[0],200)
            self.assertEqual(self.request(path)[1]['credentials'],value)
            for route in ('/api/platform','/api/platform/integrations','/api/devices','/api/services'):
                self.assertNotIn('gui-secret',json.dumps(self.request(route)[1]))
                self.assertNotIn('wifi-secret',json.dumps(self.request(route)[1]))
            device_id='device_'+'d'*12
            with patch.object(self.server,'devices',return_value=[{'id':device_id}]):
                device_path='/api/platform/credentials/device/'+device_id
                self.assertEqual(self.request(device_path,'POST',{'credentials':value})[0],200)
                self.assertEqual(self.request(device_path)[1]['credentials'],value)
            self.assertEqual(self.request('/api/platform/credentials/device/'+'device_'+'e'*12)[0],404)
            self.login()
            self.assertEqual(self.request(path)[0],403)
            self.assertEqual(self.request(path,'POST',{'credentials':value})[0],403)
            self.admin()
            with patch.dict(os.environ,{'NMS_CREDENTIALS_KEY':''}):self.assertEqual(self.request(path)[0],503)

class ReportTests(unittest.TestCase):
    def test_qemu_disk_counters_are_not_filesystem_usage(self):
        with tempfile.TemporaryDirectory() as d:
            db=Database(d)
            db.save(dict(target='proxmox_resources',status='UP',guests=[dict(id='qemu/100',cpu=.1,mem=1024,maxmem=2048,disk=0,maxdisk=4096)]))
            value=report(db.db,{'target':['proxmox_resources'],'resource':['qemu/100']},{'proxmox_resources'},60)
            self.assertIsNone(value['points'][0]['storage_percent'])
            self.assertEqual(value['points'][0]['memory_percent'],50)
            db.close()

    def test_real_samples_gaps_unknown_and_missing_values(self):
        with tempfile.TemporaryDirectory() as d:
            db=Database(d);now=time.time()
            for i,status in enumerate(('UP','DOWN','UNKNOWN')):
                db.save(dict(target='debian',status=status,cpu_percent=12 if status=='UP' else None))
            value=report(db.db,{'target':['debian'],'from':[str(now-3600)],'to':[str(time.time()+1)]},{'debian'},60)
            self.assertEqual(value['sample_availability_percent'],50);self.assertEqual(value['samples'],3)
            self.assertLess(value['coverage_percent'],1);self.assertIsNone(value['points'][0]['memory_percent'])
            with self.assertRaises(ValueError):report(db.db,{'target':['unallowed']},{'debian'},60)
            db.close()

class MaintenanceOutboxTests(unittest.TestCase):
    def test_muting_and_one_resume_after_restart_keep_same_incident(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory);muted=True
            box=Outbox(db,silenced=lambda key:muted)
            db.set_state('debian:cpu',{'active':True})
            event=dict(key='debian:cpu',kind='ALERT',time=time.time(),first_seen=100,value={'value':99})
            db.event('debian:cpu','ALERT',event);box.stage();self.assertEqual(box.pending(),[])
            identity=db.db.execute('SELECT id FROM incidents').fetchone()[0]
            muted=False;restarted=Outbox(db,silenced=lambda key:False);restarted.stage();self.assertEqual(len(restarted.pending()),1)
            restarted.stage();self.assertEqual(len(restarted.pending()),1)
            self.assertEqual(db.db.execute('SELECT id FROM incidents').fetchone()[0],identity);db.close()
    def test_recovery_during_maintenance_does_not_send_lonely_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory);muted=True;box=Outbox(db,silenced=lambda key:muted)
            for kind in ('ALERT','RECOVERY'):
                db.event('test',kind,dict(key='test',kind=kind,time=time.time(),first_seen=100))
            db.set_state('test',{'active':False});box.stage();muted=False;box.stage();self.assertEqual(box.pending(),[]);db.close()

class ProbeSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_integration_tool_uses_existing_collector_and_rejects_unknown_id(self):
        from app.services.health import Monitoring
        from app.ai.tool_registry import Registry
        with tempfile.TemporaryDirectory() as directory:
            cfg=Settings('x',frozenset({1}),'',('m',),data_dir=directory);database=Database(directory);monitor=Monitoring(cfg,database)
            item=monitor.platform.save('integrations',{'value':dict(name='Debian',url='http://192.168.20.195/',kind='server',enabled=True,collector='debian')},'admin')
            registry=Registry();monitor.register(registry);monitor.check=AsyncMock(return_value={'target':'debian','status':'UP'})
            value=await registry.execute('check_integration',json.dumps({'integration_id':item['id']}))
            self.assertEqual(value['status'],'UP');monitor.check.assert_awaited_once_with('debian')
            rejected=await registry.execute('check_integration',json.dumps({'integration_id':'unknown'}));self.assertEqual(rejected['error'],'target_not_allowed')
            database.close()

    async def test_embedding_checks_respect_device_headers(self):
        from app.monitoring.service_probe import probe
        from unittest.mock import Mock
        loop=asyncio.get_running_loop()
        for header,expected in [(b'',True),(b'X-Frame-Options: SAMEORIGIN\r\n',False),(b"Content-Security-Policy: frame-ancestors 'self'\r\n",False)]:
            reader=Mock();reader.readuntil=AsyncMock(return_value=b'HTTP/1.1 200 OK\r\n'+header+b'Content-Length: 0\r\n\r\n')
            writer=Mock();writer.drain=AsyncMock();writer.wait_closed=AsyncMock()
            with patch.object(loop,'getaddrinfo',AsyncMock(return_value=[(2,1,6,'',('192.168.20.199',5380))])),patch('asyncio.open_connection',AsyncMock(return_value=(reader,writer))):
                value=await probe('test','http://192.168.20.199:5380/',{'192.168.20.199'})
            self.assertEqual(value['embedding_supported'],expected);self.assertEqual(value['status'],'UP')
            self.assertEqual(len(value['configuration_hash']),64)

    async def test_dns_resolution_to_loopback_is_rejected_before_connect(self):
        from app.monitoring.service_probe import probe
        loop=asyncio.get_running_loop()
        with patch.object(loop,'getaddrinfo',AsyncMock(return_value=[(2,1,6,'',('127.0.0.1',80))])),patch('asyncio.open_connection',AsyncMock()) as connection:
            result=await probe('test','http://allowed.test/',{'allowed.test'})
        connection.assert_not_called();self.assertEqual(result['status'],'DOWN')

if __name__=='__main__':unittest.main()

