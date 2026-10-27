"""Private read API over the bot's SQLite cache, with server-side dashboard sessions."""
import base64
from collections import defaultdict, deque
from contextlib import closing
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit, parse_qs
from app import __version__
from app.dashboard import projection
from app.dashboard.sessions import Sessions
from app.dashboard.journal import Journal
from app.dashboard.platform_api import PlatformAPI
from app.dashboard.platform import Conflict,Forbidden,Missing

class Dashboard:
    def __init__(self, settings, port=8765, bind='0.0.0.0', monitor=None, agent=None, loop=None):
        self.settings, self.port, self.bind = settings, port, bind
        self.server = self.thread = None
        self.failures = defaultdict(deque); self.requests = defaultdict(deque); self.lock = threading.Lock()
        self.platform = PlatformAPI(self,monitor,agent,loop)
        self.sessions = Sessions(settings.data_dir, settings.dashboard_password)

    def allowed_targets(self):
        return self.platform.store.targets() | set(self.settings.targets) | {'debian', 'docker', 'mikrotik_system', 'mikrotik_interfaces',
            'proxmox_resources', 'wireguard', 'cisco_sf200', 'mikrotik_routes', 'network_traffic', 'mikrotik_network', 'mikrotik_vlan'}

    def snapshot(self, db):
        now = time.time()
        stored = db.execute('SELECT ts,payload FROM checks WHERE id IN (SELECT MAX(id) FROM checks GROUP BY target) ORDER BY target LIMIT 100').fetchall()
        service_intervals={'service_'+r['id']:r['poll_interval'] for r in self.platform.store.list('integrations') if r['enabled'] and r['monitor_enabled']}
        service_intervals.update({'inventory_'+r['id']:max(30,r['interval']) for r in self.platform.store.list('inventory') if r['enabled'] and r.get('monitor_method') in {'icmp','tcp','http','dns'}})
        checks=[]
        for ts,payload in stored:
            value=json.loads(payload);target=value.get('target','')
            if target.startswith(('service_','inventory_')) and target not in service_intervals:continue
            checks.append(projection.check(value,ts,now,max(self.settings.poll_interval,service_intervals.get(target,0))))
        states = []
        for key, payload in db.execute('SELECT key,payload FROM alert_state LIMIT 500'):
            value = json.loads(payload)
            if value.get('active'):
                last = value.get('last_event') or {'kind': 'ALERT', 'value': value.get('last_value') or {}}
                states.append({'key': projection.text(key), 'active': True, 'first_seen': value.get('first_seen'),
                    'last_event': projection.event(last, key, 'ALERT'),
                    'pending': projection.event(value['pending'], key) if value.get('pending') else None})
        return {'checks': checks, 'alerts': states, 'server_time': now, 'interval': self.settings.poll_interval,
            'version': __version__, 'source': 'shared-monitoring-cache'}

    def devices(self, checks):
        devices = {}
        registrations={d['host']:d for d in self.platform.store.list('inventory')}
        for row in checks:
            target = row['target']; configured = self.settings.targets.get(target, {})
            source=self.platform.store.source(target=target)
            registered=self.platform.store.get('inventory',source[1]) if source else None
            if source and not registered:continue
            host = row.get('host') or configured.get('host') or (urlsplit(configured.get('url', '')).hostname if configured.get('url') else None)
            if source and row.get('host') and row['host']!=registered['host']:continue
            if not host and (target.startswith('mikrotik_') or target in {'wireguard', 'network_traffic'}): host = os.getenv('MIKROTIK_HOST', '192.168.20.1')
            if not host and target == 'proxmox_resources': host = os.getenv('PROXMOX_HOST', '192.168.20.200')
            if not host and target in {'debian', 'docker'}: host = self.settings.targets.get('debian_ssh', {}).get('host')
            if not host: continue
            identity = 'device_' + hashlib.sha256(host.encode()).hexdigest()[:12]
            item = devices.setdefault(identity, {'id': identity, 'name': projection.text(registrations.get(host,{}).get('name') or configured.get('name') or host),
                'host': projection.text(host), 'type': 'observed', 'source': 'configured-collectors', 'collectors': [], 'statuses': [],
                'sample_epoch': None, 'methods': [],'stale_after_seconds':120,'connectivity_up':False})
            item['collectors'].append(target); item['statuses'].append(row['status'])
            if (row.get('method') or '').startswith('ICMP') and row['status']=='UP':item['connectivity_up']=True
            if row.get('method') not in item['methods']: item['methods'].append(row.get('method'))
            item['stale_after_seconds']=max(item['stale_after_seconds'],row['stale_after_seconds'])
            item['sample_epoch'] = max(item['sample_epoch'] or 0, row['sample_epoch'])
        result = []
        for item in devices.values():
            statuses = item.pop('statuses')
            connected=item.pop('connectivity_up')
            item['status'] = 'UP' if connected or all(s=='UP' for s in statuses) else 'DEGRADED' if 'UP' in statuses or 'DEGRADED' in statuses else 'DOWN' if all(s=='DOWN' for s in statuses) else 'UNKNOWN'
            item['read_state'] = 'partial_failure' if 'UP' in statuses and any(s!='UP' for s in statuses) else 'unavailable' if item['status']=='UNKNOWN' else 'offline' if item['status']=='DOWN' else 'online'
            item['scope'] = 'Hasil collector; kegagalan satu layanan tidak membuktikan host offline.'
            result.append(item)
        return result

    def data(self, path, query, session=None):
        if path.startswith('/api/platform'):return self.platform.get(path,query,session)
        journal_path = path in {'/api/logs','/api/incidents'} or path.startswith('/api/incidents/')
        allowed_query = {'target'} if path in {'/api/history', '/api/metrics'} else set()
        if not journal_path and (set(query) - allowed_query or any(len(v) != 1 for v in query.values())): raise ValueError('invalid_query')
        db_path = Path(self.settings.data_dir) / 'nms.sqlite3'
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=3)) as db:
            if journal_path:
                db.execute('BEGIN')
                journal = Journal(db)
                if path == '/api/logs': return journal.logs(query)
                if path == '/api/incidents':
                    response=journal.incidents(query);notes=self.platform.store.annotations()
                    response['acknowledgment_supported']=True
                    for item in response['items']:item['acknowledgment']={'supported':True,**(notes.get(item['id']) or {})}
                    return response
                if query: raise ValueError('invalid_query')
                response=journal.detail(path.removeprefix('/api/incidents/'))
                if response:
                    response['acknowledgment_supported']=True
                    response['incident']['acknowledgment']={'supported':True,**(self.platform.store.annotations().get(path.rsplit('/',1)[-1]) or {})}
                return response
            if path == '/api/status': return self.snapshot(db)
            if path == '/api/history':
                target = query.get('target', ['debian'])[0]
                if target not in self.allowed_targets(): raise ValueError('target_not_allowed')
                stored = db.execute('SELECT ts,payload FROM checks WHERE target=? ORDER BY id DESC LIMIT 120', (target,)).fetchall()
                points = []
                for ts, payload in reversed(stored):
                    row = projection.check(json.loads(payload), ts, time.time(), self.settings.poll_interval)
                    point = {k: row.get(k) for k in ['status', 'cpu_percent', 'memory_percent', 'latency_ms']}
                    point['time'] = row['sample_epoch']
                    if target == 'mikrotik_system' and row['reported_status'] == 'UP':
                        resource = (row.get('data', {}).get('/system/resource') or [{}])[0]
                        point['cpu_percent'] = float(resource['cpu-load']) if resource.get('cpu-load') is not None else None
                        point['memory_percent'] = 100 * (1 - int(resource['free-memory']) / int(resource['total-memory'])) if int(resource.get('total-memory') or 0) else None
                    points.append(point)
                return {'target': target, 'points': points}
            if path == '/api/events':
                return {'events': [{'time': ts, 'key': projection.text(key), 'kind': projection.text(kind), 'detail': projection.event(json.loads(value), key, kind)}
                    for ts, key, kind, value in db.execute('SELECT ts,key,kind,payload FROM events ORDER BY id DESC LIMIT 50')]}
            snapshot = self.snapshot(db)
            if path == '/api/devices': return {'devices': self.devices(snapshot['checks']), 'server_time': snapshot['server_time'], 'read_only': True}
            if path.startswith('/api/devices/'):
                identity = path.removeprefix('/api/devices/')
                if not re.fullmatch(r'device_[a-f0-9]{12}', identity): raise ValueError('invalid_device_id')
                device = next((d for d in self.devices(snapshot['checks']) if d['id'] == identity), None)
                if not device: return None
                return {'device': device, 'checks': [r for r in snapshot['checks'] if r['target'] in device['collectors']]}
            if path == '/api/metrics':
                target = query.get('target', [''])[0]
                if target not in self.allowed_targets(): raise ValueError('target_not_allowed')
                row = next((r for r in snapshot['checks'] if r['target'] == target), None)
                return {'target': target, 'check': row, 'read_state': row['read_state'] if row else 'unavailable'}
            if path == '/api/services': return {'services': [r for r in snapshot['checks'] if re.search('HTTP|DNS|TCP|ICMP', r.get('method') or '', re.I)], 'server_time': snapshot['server_time']}
            if path == '/api/health':
                try: health = json.loads((Path(self.settings.data_dir) / 'health.json').read_text())
                except (OSError, ValueError): health = {}
                ready = bool(health.get('poller_ready')) and not health.get('scheduler_error') and time.time() - health.get('at', 0) < 45
                return {'version': __version__, 'status': 'UP' if ready else 'UNKNOWN', 'source': 'shared-monitoring-cache',
                    'at': health.get('at'), 'last_cycle': health.get('last_cycle'), 'poller_ready': bool(health.get('poller_ready')),
                    'scheduler_error': bool(health.get('scheduler_error')), 'interval': self.settings.poll_interval, 'server_time': time.time()}
        raise ValueError('not_found')

    def start(self):
        owner = self; static = Path(__file__).parent / 'static'
        class Handler(BaseHTTPRequestHandler):
            server_version = 'NMS'; sys_version = ''
            def log_message(self, *args): pass
            def reply(self, code, body, content_type='application/json; charset=utf-8', cookie=None):
                if isinstance(body, dict): body = json.dumps(body, ensure_ascii=False, allow_nan=False)
                if isinstance(body, str): body = body.encode()
                self.send_response(code)
                for key, value in {'Content-Type': content_type, 'Content-Length': str(len(body)), 'Cache-Control': 'no-store',
                    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"}.items(): self.send_header(key, value)
                if cookie: self.send_header('Set-Cookie', cookie)
                if code == 429: self.send_header('Retry-After', '60')
                if code == 405: self.send_header('Allow', 'GET')
                if code == 401 and self.path == '/': self.send_header('WWW-Authenticate', 'Basic realm="NMS private", charset="UTF-8"')
                self.end_headers()
                try: self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError): pass

            def safe_request(self, post=False):
                if len(self.path) > 2048: self.reply(414, {'error': 'request_too_large'}); return False
                host = self.headers.get('Host', '')
                if not re.fullmatch(r'(localhost|127\.0\.0\.1)(:\d{1,5})?', host) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.reply(403, {'error': 'origin_denied'}); return False
                origin = self.headers.get('Origin')
                try: valid_origin = not origin or (urlsplit(origin).netloc == host and urlsplit(origin).scheme in {'http', 'https'})
                except ValueError: valid_origin = False
                if (post and not origin) or not valid_origin:
                    self.reply(403, {'error': 'origin_denied'}); return False
                return True

            def limited(self, failures=False):
                now = time.monotonic(); ip = self.client_address[0]
                session=owner.sessions.read(owner.sessions.token(self.headers.get('Cookie')))
                if session:ip='account:'+session['user']['username']
                with owner.lock:
                    entries = (owner.failures if failures else owner.requests)[ip]
                    while entries and now - entries[0] > 60: entries.popleft()
                    blocked = len(entries) >= (10 if failures else 120)
                    if not failures and not blocked: entries.append(now)
                if blocked: self.reply(429, {'error': 'rate_limit'})
                return blocked

            def basic(self):
                try:
                    auth = self.headers.get('Authorization', '')
                    if len(auth) > 512 or not auth.startswith('Basic '): return False
                    user, sep, password = base64.b64decode(auth[6:], validate=True).partition(b':')
                    return bool(sep) and (hmac.compare_digest(user, b'nms') & hmac.compare_digest(password, owner.settings.dashboard_password.encode()))
                except (ValueError, UnicodeError): return False

            def fail_auth(self):
                session=owner.sessions.read(owner.sessions.token(self.headers.get('Cookie')))
                key='account:'+session['user']['username'] if session else self.client_address[0]
                with owner.lock: owner.failures[key].append(time.monotonic())
                self.reply(401, {'error': 'authentication_required'})

            def do_GET(self):
                if not self.safe_request() or self.limited() or self.limited(True): return
                try:
                    parsed = urlsplit(self.path); query = parse_qs(parsed.query, max_num_fields=12, keep_blank_values=True)
                    session = owner.sessions.read(owner.sessions.token(self.headers.get('Cookie')))
                    if parsed.path == '/api/auth/session':
                        if query: return self.reply(400, {'error': 'invalid_request'})
                        return self.reply(200, session) if session else self.reply(401, {'error': 'authentication_required'})
                    if not session and not self.basic(): return self.fail_auth()
                    files = {'/': ('index.html', 'text/html; charset=utf-8'), '/dashboard.js': ('dashboard.js', 'text/javascript; charset=utf-8'), '/dashboard.css': ('dashboard.css', 'text/css; charset=utf-8')}
                    if parsed.path in files:
                        name, mime = files[parsed.path]; return self.reply(200, (static / name).read_bytes(), mime)
                    if parsed.path not in {'/api/status', '/api/history', '/api/events', '/api/devices', '/api/metrics', '/api/services', '/api/health','/api/logs','/api/incidents'} and not parsed.path.startswith(('/api/devices/','/api/incidents/','/api/platform')):
                        return self.reply(404, {'error': 'not_found'})
                    if parsed.path=='/api/platform/access' and session:
                        session={**session,'_access_binding':Sessions.digest(owner.sessions.token(self.headers.get('Cookie')))}
                    data = owner.data(parsed.path, query, session)
                    return self.reply(404, {'error': 'not_found'}) if data is None else self.reply(200, data)
                except Forbidden:return self.reply(403,{'error':'permission_denied'})
                except Missing:return self.reply(404,{'error':'not_found'})
                except ValueError: return self.reply(400, {'error': 'invalid_request'})
                except (sqlite3.Error, OSError, KeyError, TypeError): return self.reply(503, {'error': 'data_unavailable'})

            def do_POST(self):
                try: size = int(self.headers.get('Content-Length', '0'))
                except ValueError: return self.reply(400, {'error': 'invalid_request'})
                if not 0 <= size <= 2097152: return self.reply(413, {'error': 'request_too_large'})
                payload = self.rfile.read(size)
                if not self.safe_request(post=True) or self.limited() or self.limited(True): return
                parsed = urlsplit(self.path)
                if parsed.query or parsed.path not in {'/api/auth/login', '/api/auth/logout'} and not parsed.path.startswith('/api/platform/'): return self.reply(405, {'error': 'read_only_endpoint_required'})
                if not 1 <= size <= (2097152 if parsed.path=='/api/platform/restore' else 262144 if parsed.path.startswith('/api/platform/') else 4096): return self.reply(413, {'error': 'request_too_large'})
                if self.headers.get('Content-Type', '').split(';')[0].lower() != 'application/json' or self.headers.get('Transfer-Encoding'):
                    return self.reply(415, {'error': 'json_required'})
                try:
                    body = json.loads(payload)
                    if not isinstance(body, dict): raise ValueError()
                    if parsed.path.startswith('/api/platform/'):
                        session=owner.sessions.read(owner.sessions.token(self.headers.get('Cookie')))
                        if not session:return self.fail_auth()
                        return self.reply(200,owner.platform.post(parsed.path,body,session))
                    if parsed.path == '/api/auth/logout':
                        if body: raise ValueError()
                        owner.sessions.revoke(owner.sessions.token(self.headers.get('Cookie')))
                        return self.reply(200, {'ok': True}, cookie=Sessions.cookie())
                    if set(body) - {'username', 'password', 'remember'} or type(body.get('remember', False)) is not bool: raise ValueError()
                    username, password = body.get('username'), body.get('password')
                    if not isinstance(username, str) or not 1 <= len(username) <= 80 or not isinstance(password, str) or not 1 <= len(password) <= 512: raise ValueError()
                    result = owner.sessions.login(username, password, body.get('remember', False))
                    if not result: return self.fail_auth()
                    owner.sessions.revoke(owner.sessions.token(self.headers.get('Cookie')))
                    token, session, duration = result
                    return self.reply(200, session, cookie=Sessions.cookie(token, duration if body.get('remember') else None))
                except Forbidden:return self.reply(403,{'error':'permission_denied'})
                except Missing:return self.reply(404,{'error':'not_found'})
                except Conflict:return self.reply(409,{'error':'revision_conflict'})
                except (ValueError, UnicodeError) as exc:
                    if str(exc) in {'assistant_busy','probe_rate_limit'}:return self.reply(429,{'error':'rate_limit'})
                    from app.dashboard.models import public_validation_code
                    return self.reply(400, {'error': 'invalid_request','code':public_validation_code(exc)})
                except (sqlite3.Error, OSError): return self.reply(503, {'error': 'data_unavailable'})

            def do_PUT(self): self.reply(405, {'error': 'read_only_endpoint_required'})
            do_DELETE = do_PATCH = do_PUT

        self.server = ThreadingHTTPServer((self.bind, self.port), Handler)
        self.server.daemon_threads = True
        original = self.server.get_request
        def get_request():
            sock, addr = original(); sock.settimeout(5); return sock, addr
        self.server.get_request = get_request
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='dashboard')
        self.thread.start()
        return self.server.server_address[1]

    def stop(self):
        if self.server: self.server.shutdown(); self.server.server_close()
        if self.thread: self.thread.join(timeout=2)
