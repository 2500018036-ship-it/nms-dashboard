from contextlib import closing
import json
import tempfile
import time
import unittest
from app.dashboard.journal import Journal, params
from app.storage.database import Database
from app.storage import incidents
from app.alerts.outbox import Outbox
from app.alerts.engine import Alerts
from app.alerts.network import NetworkEvents
from app.config import Settings
import test_dashboard_sessions as sessions_tests

class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.db=Database(self.tmp.name)
        self.journal=Journal(self.db.db)
    def tearDown(self): self.db.close();self.tmp.cleanup()
    def add(self, kind, key='dns:availability', **extra):
        return self.db.event(key,kind,{'kind':kind,'key':key,'time':time.time(),'value':{},**extra})
    def test_stable_identity_escalation_recovery_restart_and_new_incident(self):
        first=self.add('ALERT',severity='WARNING',first_seen=100)
        self.add('ALERT',severity='CRITICAL',first_seen=100)
        self.add('RECOVERY',severity='INFO',first_seen=100)
        result=self.journal.incidents({})['items'][0]
        self.assertEqual(result['id'],'inc_event_'+str(first));self.assertEqual(result['severity'],'CRITICAL')
        self.assertEqual(result['status'],'RECOVERED');self.assertEqual(result['first_seen'],100)
        self.assertEqual(len(self.journal.detail(result['id'])['incident']['timeline']),3)
        self.db.close();self.db=Database(self.tmp.name);self.journal=Journal(self.db.db)
        self.assertEqual(self.journal.incidents({})['items'][0]['id'],result['id'])
        again=self.add('ALERT',first_seen=200)
        self.assertNotEqual('inc_event_'+str(again),result['id'])
        self.assertEqual(self.journal.incidents({'status':['ACTIVE']})['total'],1)
    def test_retirement_and_partial_recovery_are_not_fabricated_outages(self):
        self.add('ALERT');self.add('RETIRED',reason='policy_disabled')
        item=self.journal.incidents({})['items'][0]
        self.assertEqual(item['status'],'RETIRED');self.assertNotEqual(item['resolution_source'],'monitoring_recovery')
        self.add('RECOVERY','orphan')
        item=self.journal.incidents({'q':['orphan']})['items'][0]
        self.assertTrue(item['partial_history']);self.assertEqual(item['severity'],'UNKNOWN')
    def test_backfill_does_not_replay_telegram_and_is_idempotent(self):
        box=Outbox(self.db);self.add('ALERT');box.stage()
        cursor=self.db.metadata('notification_cursor')
        self.db.db.execute('DELETE FROM incident_events');self.db.db.execute('DELETE FROM incidents')
        self.db.db.execute("DELETE FROM metadata WHERE key='incident_projection_v1'");self.db.db.commit()
        incidents.initialize(self.db.db);incidents.initialize(self.db.db)
        self.assertEqual(self.journal.incidents({})['total'],1)
        self.assertEqual(self.db.metadata('notification_cursor'),cursor)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertEqual(len(box.pending()),1)
    def test_active_incident_survives_retention_with_partial_timeline(self):
        self.add('ALERT');self.db.db.execute('UPDATE events SET ts=0');self.db.db.commit()
        self.db.cleanup(1)
        result=self.journal.incidents({})['items'][0]
        self.assertEqual(result['status'],'ACTIVE');self.assertTrue(result['partial_history'])
    def test_restart_catches_events_written_by_older_version_without_notification_replay(self):
        self.add('ALERT')
        now=time.time()
        self.db.db.execute('INSERT INTO events VALUES(?,?,?,?,?)',(999,now,'dns:availability','RECOVERY',json.dumps({'time':now})))
        self.db.db.commit();self.db.close();self.db=Database(self.tmp.name);self.journal=Journal(self.db.db)
        item=self.journal.incidents({})['items'][0]
        self.assertEqual(item['status'],'RECOVERED')
        self.assertEqual(len(self.journal.detail(item['id'])['incident']['timeline']),2)
    def test_repeated_condition_hysteresis_and_delivery_share_one_engine(self):
        cfg=Settings('t',frozenset({1}),'',('m',)); engine=Alerts(cfg,self.db);box=Outbox(self.db)
        for value in (91,92,92,91,89,87):engine.metric('debian:memory',value,90)
        self.assertEqual(len(self.db.events()),1)
        for value in (84,84):engine.metric('debian:memory',value,90)
        box.stage();box.stage()
        self.assertEqual(self.journal.incidents({})['total'],1)
        self.assertEqual(self.journal.incidents({})['items'][0]['status'],'RECOVERED')
        self.assertEqual(len(box.pending()),2)
    def test_network_confirmation_preserves_first_seen_including_zero(self):
        cfg=Settings('t',frozenset({1}),'',('m',));engine=NetworkEvents(cfg,self.db)
        engine.change('link','UP',{},'up','r',now=0,bad=False)
        engine.change('link','DOWN',{},'down','r',now=10,bad=True,required=2)
        engine.change('link','DOWN',{},'down','r',now=20,bad=True,required=2)
        engine.change('link','UP',{},'up','r',now=30,bad=False)
        self.assertEqual([e['first_seen'] for e in self.db.events()],[10,10])
    def test_logs_are_real_paginated_filtered_and_sanitized(self):
        for n in range(6):self.db.save({'target':'debian','status':'UP','method':'host snapshot','cpu_percent':n,'password':'must-not-leak','raw_logs':'must-not-leak'})
        self.add('ALERT',value={'threshold':90,'password':'must-not-leak'})
        first=self.journal.logs({'page_size':['3']});second=self.journal.logs({'page_size':['3'],'page':['2']})
        self.assertEqual(first['total'],7);self.assertFalse({i['id'] for i in first['items']}&{i['id'] for i in second['items']})
        self.assertNotIn('must-not-leak',json.dumps(first))
        self.assertEqual(self.journal.logs({'source':['monitoring-events']})['total'],1)
        self.assertEqual(self.journal.logs({'q':['debian'],'severity':['INFO']})['total'],6)
        self.assertEqual(self.journal.logs({'category':['syslog']})['total'],0)
        self.assertFalse(next(s for s in first['sources'] if s['id']=='syslog')['available'])
        self.assertEqual(self.journal.logs({'q':["' OR 1=1 --"]})['total'],0)
        self.assertEqual(self.journal.logs({'to':['1'],'from':['0']})['total'],0)
    def test_query_validation_and_incident_id_allowlist(self):
        for q in ({'page':['0']},{'page_size':['101']},{'q':['a'*121]},{'from':['0'],'to':[str(int(time.time()))]},
                  {'severity':['ERROR']},{'page':['1','2']},{'url':['http://evil.example']}):
            with self.assertRaises(ValueError):params(q,'logs')
        with self.assertRaises(ValueError):self.journal.detail('../../etc/passwd')
        self.assertIsNone(self.journal.detail('inc_event_99999'))

class JournalAPITests(unittest.TestCase):
    setUp = sessions_tests.SessionAPITests.setUp
    tearDown = sessions_tests.SessionAPITests.tearDown
    request = sessions_tests.SessionAPITests.request
    login = sessions_tests.SessionAPITests.login
    def test_journal_routes_require_auth_and_reject_mutations(self):
        for path in ['/api/logs','/api/incidents','/api/incidents/inc_event_1']:
            self.assertEqual(self.request(path)[0],401)
        self.login()
        self.assertEqual(self.request('/api/logs?page_size=10&category=monitoring&severity=INFO&q=debian&from=1')[0],400) # window >31 days
        for path in ['/api/logs','/api/incidents']:
            self.assertEqual(self.request(path)[0],200)
            self.assertEqual(self.request(path,'POST',{})[0],405)
        self.assertEqual(self.request('/api/incidents/inc_event_99999')[0],404)
        self.assertEqual(self.request('/api/logs?page=0')[0],400)
        self.assertEqual(self.request('/api/incidents?status=resolved')[0],400)
