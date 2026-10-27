import base64
from http.client import HTTPConnection
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.config import Settings
from app.dashboard.server import Dashboard
from app.storage.database import Database

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Settings('t',frozenset({1}),'k',('m',),data_dir=self.tmp.name,dashboard=True,dashboard_password='A'*32)
        self.db=Database(self.tmp.name)
        self.db.save({'target':'debian','method':'snapshot','timestamp':'2026-10-19T00:00:00Z','status':'UP','cpu_percent':10,'memory_percent':30})
        self.server=Dashboard(self.cfg,port=0,bind='127.0.0.1')
        self.port=self.server.start()

    def tearDown(self):
        self.server.stop();self.db.close();self.tmp.cleanup()

    def request(self,path='/',auth=True,headers=None,method='GET'):
        c=HTTPConnection('127.0.0.1',self.port,timeout=3)
        h={'Host':'localhost'}
        if method == 'POST': h['Origin'] = 'http://localhost'
        if auth:h['Authorization']='Basic '+base64.b64encode(('nms:'+self.cfg.dashboard_password).encode()).decode()
        h.update(headers or {})
        c.request(method,path,headers=h);r=c.getresponse();body=r.read();status=r.status;response_headers=dict(r.getheaders());c.close()
        return status,body,response_headers

    def test_auth_required(self):
        self.assertEqual(self.request(auth=False)[0],401)
        self.assertEqual(self.request(headers={'Authorization':'Basic '+base64.b64encode(b'nms:bad').decode()})[0],401)

    def test_status_and_history_readonly(self):
        status,body,headers=self.request('/api/status')
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['checks'][0]['cpu_percent'],10)
        self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('/api/history?target=debian')[0],200)
        self.assertEqual(self.request('/api/events')[0],200)
        self.assertEqual(self.request('/api/status',method='POST')[0],405)

    def test_target_and_path_allowlist(self):
        self.assertEqual(self.request('/api/history?target=../../etc/shadow')[0],400)
        self.assertEqual(self.request('/../../.env')[0],404)

    def test_cross_site_and_host_denied(self):
        self.assertEqual(self.request(headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request(headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request(headers={'Sec-Fetch-Site':'cross-site'})[0],403)

    def test_bruteforce_limited(self):
        for _ in range(10):self.request(auth=False)
        self.assertEqual(self.request(auth=False)[0],429)

    def test_html_css_js_served(self):
        for path in ('/','/dashboard.css','/dashboard.js'):
            self.assertEqual(self.request(path)[0],200)

class HostCollectorSecurityTests(unittest.TestCase):
    def test_endpoint_allowlist(self):
        path=Path('/app/deploy/host_collector.py')
        if not path.exists():path=Path(__file__).resolve().parents[1]/'deploy/host_collector.py'
        spec=importlib.util.spec_from_file_location('host_collector',path)
        collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
        with patch.object(collector,'UnixConnection') as connection:
            for endpoint in ['/containers/create','/containers/abc/exec','/images/json','/volumes','/containers/'+('a'*64)+'/start']:
                with self.assertRaises(ValueError):collector.docker_get(endpoint)
            connection.assert_not_called()

    def test_dashboard_weak_password_rejected(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','OPENROUTER_API_KEY':'dummy','ALLOWED_TELEGRAM_ID':'1','DASHBOARD_ENABLED':'true','DASHBOARD_PASSWORD':'weak'}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaises(ValueError):Settings.load()
