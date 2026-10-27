from contextlib import closing
from http.client import HTTPConnection
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from app.config import Settings
from app.dashboard.server import Dashboard
from app.dashboard.sessions import Sessions
from app.dashboard.projection import check
from app.storage.database import Database

class SessionAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Settings('dummy', frozenset({1}), '', ('m',), data_dir=self.tmp.name, dashboard=True, dashboard_password='test-only-' + 'A' * 32)
        self.db = Database(self.tmp.name)
        self.db.save({'target': 'debian', 'status': 'UP', 'method': 'host snapshot', 'cpu_percent': 7, 'password': 'must-not-leak', 'raw_logs': 'must-not-leak'})
        self.server = Dashboard(self.cfg, port=0, bind='127.0.0.1'); self.port = self.server.start()
        self.cookie = ''

    def tearDown(self):
        self.server.stop(); self.db.close(); self.tmp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        connection = HTTPConnection('127.0.0.1', self.port, timeout=3)
        h = {'Host': 'localhost', 'Cookie': self.cookie}
        if method == 'POST': h.update({'Origin': 'http://localhost', 'Content-Type': 'application/json'})
        h.update(headers or {})
        connection.request(method, path, json.dumps(body) if body is not None else None, headers=h)
        response = connection.getresponse(); data = response.read(); status = response.status; rh = dict(response.getheaders()); connection.close()
        return status, json.loads(data), rh

    def login(self, remember=False):
        status, body, headers = self.request('/api/auth/login', 'POST', {'username': 'nms', 'password': self.cfg.dashboard_password, 'remember': remember})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        return body, headers

    def test_login_cookie_session_reload_and_logout_revocation(self):
        self.assertEqual(self.request('/api/auth/session')[0], 401)
        body, headers = self.login()
        self.assertEqual(body['user']['role'], 'Read-only operator')
        self.assertIn('HttpOnly', headers['Set-Cookie']); self.assertIn('SameSite=Strict', headers['Set-Cookie'])
        self.assertNotIn('Max-Age', headers['Set-Cookie'])
        self.assertEqual(self.request('/api/auth/session')[0], 200)
        self.assertEqual(self.request('/api/status')[0], 200)
        old = self.cookie
        self.assertEqual(self.request('/api/auth/logout', 'POST', {})[0], 200)
        self.cookie = old
        self.assertEqual(self.request('/api/auth/session')[0], 401)
        self.assertEqual(self.request('/api/status')[0], 401)

    def test_wrong_password_and_admin_bypass_rejected(self):
        for username, password in [('admin', ''), ('admin', 'abcdef'), ('nms', 'abcdef'), ('nms', self.cfg.dashboard_password + ' ')]:
            self.assertIn(self.request('/api/auth/login', 'POST', {'username': username, 'password': password})[0], (400, 401))

    def test_remember_cookie_and_hashed_persistent_storage(self):
        _, headers = self.login(True)
        self.assertIn('Max-Age=604800', headers['Set-Cookie'])
        with closing(self.server.sessions.connect()) as db:
            digest = db.execute('SELECT digest FROM sessions').fetchone()[0]
        self.assertNotIn(digest, self.cookie)
        restarted = Sessions(self.tmp.name, self.cfg.dashboard_password)
        self.assertIsNotNone(restarted.read(self.cookie.split('=', 1)[1]))

    def test_idle_absolute_expiry_and_credential_rotation(self):
        self.login()
        token = self.cookie.split('=', 1)[1]
        with closing(self.server.sessions.connect()) as db:
            db.execute('UPDATE sessions SET seen=?', (time.time() - 1900,)); db.commit()
        self.assertIsNone(self.server.sessions.read(token))
        self.login()
        with closing(self.server.sessions.connect()) as db:
            db.execute('UPDATE sessions SET expires=0'); db.commit()
        self.assertEqual(self.request('/api/auth/session')[0], 401)
        self.login(); rotated = Sessions(self.tmp.name, 'different-' + 'B' * 32)
        self.assertIsNone(rotated.read(self.cookie.split('=', 1)[1]))

    def test_origin_json_schema_and_size_protection(self):
        credentials = {'username': 'nms', 'password': self.cfg.dashboard_password}
        for origin in ['', 'https://evil.example', 'http://[invalid']:
            self.assertEqual(self.request('/api/auth/login', 'POST', credentials, {'Origin': origin})[0], 403)
        self.assertEqual(self.request('/api/auth/login', 'POST', credentials, {'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/auth/login', 'POST', {**credentials, 'role': 'admin'})[0], 400)
        self.assertEqual(self.request('/api/auth/login', 'POST', {**credentials, 'remember': 'true'})[0], 400)
        self.assertEqual(self.request('/api/auth/login', 'POST', {'username': 'nms', 'password': 'x' * 5000})[0], 413)

    def test_bruteforce_rate_limit(self):
        for _ in range(10): self.request('/api/auth/login', 'POST', {'username': 'nms', 'password': 'wrong'})
        self.assertEqual(self.request('/api/auth/login', 'POST', {'username': 'nms', 'password': 'wrong'})[0], 429)

    def test_read_endpoints_require_auth_and_do_not_modify_cache(self):
        for path in ['/api/devices', '/api/metrics?target=debian', '/api/services', '/api/health']:
            self.assertEqual(self.request(path)[0], 401)
        before = self.db.db.execute('SELECT COUNT(*) FROM checks').fetchone()[0]
        self.login()
        for path in ['/api/devices', '/api/metrics?target=debian', '/api/services', '/api/health']:
            self.assertEqual(self.request(path)[0], 200)
        self.assertEqual(self.db.db.execute('SELECT COUNT(*) FROM checks').fetchone()[0], before)
        self.assertNotIn('must-not-leak', json.dumps(self.request('/api/status')[1]))
        self.assertEqual(self.request('/api/devices', 'POST', {})[0], 405)
        self.assertEqual(self.request('/api/metrics?target=debian&target=docker')[0], 400)
        self.assertEqual(self.request('/api/status?password=ignored')[0], 400)

    def test_device_details_and_allowlist(self):
        self.login()
        devices = self.request('/api/devices')[1]['devices']
        self.assertTrue(devices)
        self.assertEqual(self.request('/api/devices/' + devices[0]['id'])[0], 200)
        self.assertEqual(self.request('/api/devices/device_000000000000')[0], 404)
        self.assertEqual(self.request('/api/devices/../../etc/passwd')[0], 400)
        self.assertEqual(self.request('/api/metrics?target=../../etc/passwd')[0], 400)

    def test_per_collector_poll_interval_controls_freshness(self):
        now=time.time();value=check({'target':'service_test','status':'UP'},now-300,now,900)
        self.assertFalse(value['stale']);self.assertEqual(value['stale_after_seconds'],2700)
        self.assertTrue(check({'target':'service_test','status':'UP'},now-2800,now,900)['stale'])

    def test_projection_drops_nested_secrets_and_preserves_staleness(self):
        row = {'target': 'mikrotik_system', 'status': 'UP', 'timestamp': '2000-01-01T00:00:00Z',
            'data': {'/system/resource': [{'cpu-load': 8, 'password': 'secret'}], '/private': [{'token': 'secret'}]},
            'containers': [{'name': 'app', 'cpu_percent': 125, 'password': 'secret'}]}
        value = check(row, time.time(), time.time(), 30)
        self.assertTrue(value['stale']); self.assertEqual(value['status'], 'UNKNOWN'); self.assertEqual(value['read_state'], 'stale')
        self.assertNotIn('secret', json.dumps(value)); self.assertEqual(value['containers'][0]['cpu_percent'], 125)

    def test_legacy_alerts_and_recovery_keep_telegram_rule_metadata(self):
        self.db.set_state('mikrotik:storage', {'active': True, 'first_seen': 123, 'last_value': {'value': 97, 'token': 'must-not-leak'}})
        self.db.event('mikrotik:storage', 'RECOVERY', {'kind': 'RECOVERY', 'value': {'value': 70}, 'recovered_at': 456})
        self.login()
        active = self.request('/api/status')[1]['alerts'][0]
        self.assertIsNone(active['pending'])
        self.assertEqual(active['last_event']['severity'], 'CRITICAL')
        self.assertEqual(active['last_event']['device'], 'mikrotik')
        self.assertNotIn('must-not-leak', json.dumps(active))
        recovery = self.request('/api/events')[1]['events'][0]['detail']
        self.assertEqual(recovery['severity'], 'INFO')
        self.assertEqual(recovery['title'], 'Layanan pulih')

    def test_explicit_event_metadata_is_preserved_and_unknown_kind_stays_unknown(self):
        from app.dashboard.projection import event
        projected = event({'title': 'Link down', 'severity': 'CRITICAL', 'device': 'Router'}, 'network:link:ether1', 'ALERT')
        self.assertEqual(projected['severity'], 'CRITICAL')
        self.assertEqual(projected['device'], 'Router')
        self.assertEqual(event({'reason': 'retired', 'password': 'secret'}, 'legacy', 'RETIRED'), {})

if __name__ == '__main__': unittest.main()
