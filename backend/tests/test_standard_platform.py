import asyncio
import base64
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import AsyncMock,patch
from app.config import Settings
from app.dashboard.platform import Platform
from app.dashboard.credentials import CredentialVault
from app.dashboard.discovery import save as discover,read as discovery
from app.dashboard.hierarchy import hierarchy
from app.dashboard.operational_reset import prepare,verify,apply,plan
from app.monitoring.snmp_resources import storage_metrics
from app.storage.database import Database
from app.telegram.control import TelegramControl

def inventory(**extra):
    return dict({'name':'Device','host':'192.168.20.199','type':'router','methods':['snmp'],'interval':60,'profile':'network','enabled':True,'monitor_method':'snmp'},**extra)

class StandardPlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cfg=Settings('t',frozenset({12}),'',('m',),data_dir=self.tmp.name)
        self.db=Database(self.tmp.name);self.store=Platform(self.tmp.name,self.cfg)
        self.env=patch.dict(os.environ,{'NMS_CREDENTIALS_KEY':base64.urlsafe_b64encode(b'A'*32).decode()});self.env.start()
    def tearDown(self):self.db.close();self.env.stop();self.tmp.cleanup()

    def test_new_api_requires_scoped_explicit_approval(self):
        value=inventory(host='192.168.20.1',monitor_method='routeros',methods=['api'],credential_ref='routeros-default')
        with self.assertRaisesRegex(ValueError,'optional_api_approval_required'):self.store.save('inventory',{'value':value},'admin')
        self.store.approve_optional_api({'method':'routeros','host':'192.168.20.1','reason':'Read-only export is not available using standard SNMP.','confirmation':'SETUJUI API 192.168.20.1'},'admin')
        device=self.store.save('inventory',{'value':value},'admin')
        self.assertEqual(device['monitor_method'],'routeros')
        self.assertFalse(self.store.optional_api_approved('proxmox','192.168.20.200'))

    def test_per_device_idempotency_does_not_duplicate_after_network_retry(self):
        body={'value':inventory(),'request_id':'a'*32}
        first=self.store.save('inventory',body,'admin');second=self.store.save('inventory',body,'admin')
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(self.store.list('inventory')),1)

    def test_discovery_survives_disabling_categories_and_is_invalidated_by_address(self):
        device=self.store.save('inventory',{'value':inventory()},'admin')
        discover(self.store,device,{'status':'UP','cpu_percent':0,'interfaces':[{'name':'eth0','rx_bps':0}]},complete=True)
        changed={**device,'monitor_categories':[]}
        self.assertIn('cpu',discovery(self.store,changed)['categories'])
        self.assertIn('bandwidth',discovery(self.store,changed)['categories'])
        self.assertIsNone(discovery(self.store,{**changed,'host':'192.168.20.198'}))

    def test_physical_count_and_components_are_separate_with_independent_targets(self):
        parent=self.store.save('inventory',{'value':inventory(type='server')},'admin')
        child=self.store.save('inventory',{'value':inventory(name='DNS service',type='service',component_kind='service',parent_id=parent['id'],monitor_method='tcp',methods=['tcp'],monitor_port=53)},'admin')
        result=hierarchy(self.store,lambda d:{'telemetry':{},'id':d['id']})
        self.assertEqual(result['physical_count'],1);self.assertEqual(result['servers'][0]['children'][0]['device']['id'],child['id'])
        self.assertNotEqual(self.store.inventory_target(parent),self.store.inventory_target(child))
        with self.assertRaisesRegex(ValueError,'parent_has_components'):self.store.remove('inventory',parent['id'],1,'admin')

    def test_telegram_token_encryption_binding_role_and_revocation_use_same_accounts(self):
        control=TelegramControl(self.store,self.cfg)
        self.assertEqual(control.user(12)['role'],'Read-only operator')
        token='123456789:'+'B'*35
        control.settings({'revision':1,'enabled':True,'token':token},'admin')
        self.assertEqual(control.token(),token);self.assertNotIn(token,json.dumps(control.public()))
        self.assertNotIn(token.encode(),self.store.path.read_bytes())
        self.store.save_user({'username':'viewer1','name':'Viewer','role':'Viewer','enabled':True,'password':'C'*24},'admin')
        control.binding({'telegram_id':34,'username':'viewer1','enabled':True,'notify':True,'confirmation':'34'},'admin')
        self.assertEqual(control.user(34)['role'],'Viewer');self.assertIn(34,control.recipients())
        with self.assertRaisesRegex(ValueError,'user_confirmation_required'):self.store.save_user({'username':'viewer1','name':'Viewer','role':'Administrator','enabled':True,'revision':1},'admin')
        self.store.save_user({'username':'viewer1','name':'Viewer','role':'Viewer','enabled':False,'revision':1,'confirmation':'viewer1'},'admin')
        self.assertIsNone(control.user(34));self.assertNotIn(34,control.recipients())

    def test_portal_not_active_without_verification_or_after_url_changes(self):
        from app.dashboard.portal import public,initialize
        device=self.store.save('inventory',{'value':inventory(dashboard_url='http://192.168.20.199:5380/')},'admin')
        initialize(self.store)
        target=lambda:next(v for v in public(self.store) if v['id']==device['id'])
        self.assertFalse(target()['available'])
        with self.store.db() as db:db.execute('INSERT INTO portal_checks VALUES(?,?,?,?)',(device['id'],device['dashboard_url'],time.time(),json.dumps({'reachable':True,'http_status':200,'connect_ip':'192.168.20.199'})))
        self.assertTrue(target()['available'])
        value={k:v for k,v in device.items() if k not in {'id','revision','created_at','updated_at'}};value['dashboard_url']='http://192.168.20.199:5381/'
        self.store.save('inventory',{'revision':1,'value':value},'admin',device['id'])
        self.assertFalse(target()['available'])

    def test_reset_backup_integrity_and_missing_approval_fail_closed(self):
        self.store.save('inventory',{'value':inventory()},'admin')
        auth=Path(self.tmp.name)/'dashboard-auth.sqlite3'
        with closing(sqlite3.connect(auth)) as db:db.execute('CREATE TABLE sessions(id TEXT)')
        target=Path(self.tmp.name)/'operational-reset'/'candidate'
        manifest=prepare(self.tmp.name,target)
        self.assertEqual(verify(target)['id'],manifest['id'])
        with self.assertRaisesRegex(ValueError,'explicit_reset_confirmation_required'):apply(self.tmp.name,target,'')
        self.assertEqual(len(self.store.list('inventory')),1)
        with open(target/'nms.sqlite3','ab') as stream:stream.write(b'tampered')
        with self.assertRaisesRegex(ValueError,'backup_integrity_failed'):verify(target)

    def test_backup_reads_a_consistent_wal_snapshot_while_polling_writes(self):
        live=Path(self.tmp.name)/'concurrent.sqlite3'
        with closing(sqlite3.connect(live)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('CREATE TABLE samples(id INTEGER PRIMARY KEY,payload BLOB)')
            db.executemany('INSERT INTO samples VALUES(?,?)',((i,b'x'*4096) for i in range(1000)))
            db.execute('CREATE TABLE counter(value INTEGER)');db.execute('INSERT INTO counter VALUES(0)');db.commit()
        stop=threading.Event();started=threading.Event();failures=[]
        def polling():
            try:
                with closing(sqlite3.connect(live,timeout=10)) as db:
                    while not stop.is_set():
                        with db:db.execute('UPDATE counter SET value=value+1')
                        started.set();stop.wait(.002)
            except Exception as exc:failures.append(exc)
        writer=threading.Thread(target=polling,daemon=True);writer.start()
        try:
            self.assertTrue(started.wait(5))
            target=Path(self.tmp.name)/'operational-reset'/'live-polling'
            manifest=prepare(self.tmp.name,target)
            self.assertEqual(manifest['files']['concurrent.sqlite3']['sqlite_integrity'],'ok')
            with closing(sqlite3.connect(target/'concurrent.sqlite3')) as saved:
                self.assertEqual(saved.execute('SELECT COUNT(*) FROM samples').fetchone()[0],1000)
                self.assertGreaterEqual(saved.execute('SELECT value FROM counter').fetchone()[0],1)
        finally:
            stop.set();writer.join(10)
        self.assertFalse(writer.is_alive());self.assertEqual(failures,[])

    @unittest.skipIf(os.name=='nt','Offline singleton lock is Linux fcntl, verified by Docker/CI')
    def test_reset_on_fixture_preserves_accounts_settings_audit_and_stops_reseeding(self):
        self.store.bootstrap('D'*30);self.store.sync_inventory();settings=self.store.get_settings();audit_before=self.store.audit_page({})['total']
        target=Path(self.tmp.name)/'operational-reset'/'approved-fixture';manifest=prepare(self.tmp.name,target)
        result=apply(self.tmp.name,target,'RESET THEAZ NMS '+manifest['id'])
        self.assertTrue(result['reset_executed']);self.assertEqual(self.store.list('inventory'),[])
        restored=Platform(self.tmp.name,self.cfg);restored.sync_inventory()
        self.assertEqual(restored.list('inventory'),[]);self.assertEqual(restored.list('integrations'),[])
        self.assertEqual(restored.get_settings(),settings);self.assertIsNotNone(restored.user('admin'))
        self.assertGreater(restored.audit_page({})['total'],audit_before)
        self.assertTrue(restored.inventory_authoritative())

    def test_host_resources_units_and_absent_oid_do_not_invent_metrics(self):
        values=storage_metrics([{'index':'1','type':'1.3.6.1.2.1.25.2.1.2','units':'1024','size':'100','used':'25'},
            {'index':'2','type':'1.3.6.1.2.1.25.2.1.4','name':'/','units':'4096','size':'100','used':'50'},
            {'index':'3','type':'1.3.6.1.2.1.25.2.1.4','units':'noSuchObject','size':'0','used':'0'}])
        self.assertEqual(values['memory_percent'],25);self.assertEqual(values['disks'][0]['total'],409600)
        self.assertEqual(storage_metrics([]),{})

    def test_dashboard_without_telegram_credentials_can_start(self):
        with patch.dict(os.environ,{'DASHBOARD_ENABLED':'true','DASHBOARD_PASSWORD':'E'*30},clear=True):
            config=Settings.load();self.assertEqual(config.telegram_token,'');self.assertEqual(config.allowed_ids,frozenset())

if __name__=='__main__':unittest.main()
