import asyncio
from collections import OrderedDict
from copy import deepcopy
import json
import hashlib
import logging
import os
import re
import ssl
import threading
import time

import routeros_api
from app.monitoring.common import result
from app.monitoring.mikrotik_catalog import SECTIONS, LEGACY_NETWORK, ERROR_HINTS

MAX_ROWS = 500
CACHE_SECONDS = 30
PAGE_BUDGET = 14000
LOGIN_TIMEOUT = 10.0
READ_TIMEOUT = 5.0
COLLECT_SECONDS = 15.0
REQUEST_SECONDS = 19.0
ALLOWED_READONLY_POLICIES = frozenset({'read','api','test','winbox'})
log = logging.getLogger(__name__)


def error_category(exc):
    # Classify internally; raw RouterOS exceptions can contain commands/arguments.
    message = str(exc).lower()
    if isinstance(exc, TimeoutError) or 'timed out' in message:
        return 'timeout'
    if isinstance(exc, ssl.SSLError):
        return 'tls_verification_failed'
    if any(word in message for word in ('invalid user', 'invalid password', 'cannot log in', 'authentication')):
        return 'authentication_failed'
    if any(word in message for word in ('not enough permissions', 'permission denied', 'not permitted')):
        return 'permission_denied'
    if any(word in message for word in ('no such command', 'not supported', 'unknown command')):
        return 'unsupported_section'
    return 'connection_failed'


class MikroTik:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.async_lock = asyncio.Lock()
        self.snapshots = OrderedDict()
        self.link_samples = {}
        self.policy_cache = None

    def failure(self, section, error, phase=None):
        value = result('mikrotik', 'RouterOS API', section=section, error=error,
            detail=ERROR_HINTS.get(error, 'Data MikroTik belum tersedia.'))
        if phase:
            value['phase']=phase
            log.warning('mikrotik_failed section=%s phase=%s category=%s',section,phase,error)
        return value

    async def query(self, section, offset=0, limit=10, filter_field='', filter_value=''):
        if not isinstance(section, str) or section not in SECTIONS or type(limit) is not int or not 1 <= limit <= 10:
            return self.failure(section, 'invalid_arguments')
        return await self.collect(section, offset, limit, filter_field, filter_value)

    async def collect(self, section='system', offset=0, limit=100, filter_field='', filter_value='',fresh=False):
        if not isinstance(section, str):
            return self.failure('invalid', 'invalid_arguments')
        names = LEGACY_NETWORK if section == 'network' else (section,)
        if (any(name not in SECTIONS for name in names) or type(offset) is not int or not 0 <= offset < MAX_ROWS
                or type(limit) is not int or not 1 <= limit <= 100
                or not isinstance(filter_field, str) or not isinstance(filter_value, str)
                or bool(filter_field) != bool(filter_value) or len(filter_value) > 80
                or any(ord(c) < 32 for c in filter_value)
                or (filter_field and (len(names) != 1 or filter_field not in SECTIONS[names[0]].filters))):
            return self.failure(section, 'invalid_arguments')
        if not self.settings.mikrotik_readonly:
            return self.failure(section, 'readonly_account_required')
        if any(SECTIONS[name].network for name in names) and os.getenv('MIKROTIK_NETWORK_DETAILS_ENABLED', 'false').lower() != 'true':
            return self.failure(section, 'network_details_disabled')
        if not os.getenv('MIKROTIK_USER') or not os.getenv('MIKROTIK_PASSWORD'):
            return self.failure(section, 'missing_credentials')
        # Include time waiting for another section in the overall request budget.
        # Authentication on small RouterOS devices can take several seconds.
        request_deadline = time.monotonic() + REQUEST_SECONDS
        try:
            await asyncio.wait_for(self.async_lock.acquire(), COLLECT_SECONDS)
        except asyncio.TimeoutError:
            return self.failure(section, 'collector_busy')
        try:
            key = (section, filter_field, filter_value)
            snapshot = self.snapshots.get(key)
            if not fresh and snapshot and time.monotonic() - snapshot[0] < CACHE_SECONDS:
                value = deepcopy(snapshot[1])
                age = round(time.monotonic() - snapshot[0], 2)
            else:
                value = await asyncio.to_thread(self._collect, section, filter_field, filter_value, request_deadline)
                age = 0
                if value['status'] in {'UP', 'DEGRADED'}:
                    self.snapshots[key] = (time.monotonic(), deepcopy(value))
                    self.snapshots.move_to_end(key)
                    while len(self.snapshots) > 4:
                        self.snapshots.popitem(last=False)
            return self._page(value, offset, limit, age)
        finally:
            self.async_lock.release()

    @staticmethod
    def _page(value, offset, limit, age):
        if 'data' not in value:
            return value
        value['cache_age_seconds'] = age
        used = 0
        for path, rows in value['data'].items():
            page = []
            for row in rows[offset:offset+limit]:
                size = len(json.dumps(row, ensure_ascii=False))
                if used + size > PAGE_BUDGET:
                    break
                page.append(row)
                used += size
            value['data'][path] = page
            meta = value['resources'][path]
            more = offset + len(page) < len(rows)
            meta.update(offset=offset, returned=len(page), has_more=more or meta['scan_truncated'],
                next_offset=offset+len(page) if more else None)
            if not page and offset:
                meta['error'] = 'page_out_of_range'
            if meta['scan_truncated']:
                meta['hint'] = 'Batas 500 baris tercapai. Gunakan filter; data tidak lengkap.'
        value['scope'] = ('Pembacaan ini bukan pembuktian konektivitas VLAN/routing/DNS. '
            'Counter bytes/packets kumulatif; hanya traffic menghitung bit/detik. '
            'Periksa has_more, next_offset, scan_truncated dan fields_truncated sebelum menyebut daftar lengkap.')
        return value

    @staticmethod
    def _bound_timeout(pool, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        pool.set_timeout(min(READ_TIMEOUT, remaining))

    def _read(self, api, pool, path, fields, query, deadline, stats=False):
        arguments = {'.proplist': fields}
        if stats:
            arguments['stats'] = ''
        rows, shortened = [], False
        # Stop after 501 rows; disconnect in finally cancels remaining print output.
        self._bound_timeout(pool, deadline)
        stream = iter(api.get_resource(path).call_async('print', arguments, query))
        for index in range(MAX_ROWS + 1):
            self._bound_timeout(pool, deadline)
            try:
                row = next(stream)
            except StopIteration:
                break
            if index >= MAX_ROWS:
                return rows, True, shortened
            selected = {}
            for key in fields.split(','):
                actual='id' if key=='.id' and 'id' in row else key
                if actual in row:
                    raw = str(row[actual])
                    shortened |= len(raw) > 160
                    selected['id' if key=='.id' else key] = ''.join(c for c in raw[:160] if c.isprintable())
            rows.append(selected)
        return rows, False, shortened

    def _link_rates(self,api,pool,rows,deadline):
        """Fixed read-only Ethernet monitor. Never infer capacity from advertising."""
        for row in rows:
            name=row.get('name','')
            if row.get('type')!='ether' or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',name):continue
            cached=self.link_samples.get(name,{})
            if time.monotonic()-cached.get('at',0)>60 or cached.get('running')!=row.get('running'):
                sample={'at':time.monotonic(),'running':row.get('running'),'error':None}
                try:
                    self._bound_timeout(pool,deadline)
                    response=api.get_resource('/interface/ethernet').call('monitor',
                        {'numbers':name,'once':'','.proplist':'name,status,rate,full-duplex,auto-negotiation'})
                    if len(response)!=1:raise ValueError('invalid_monitor_response')
                    data=response[0]
                    sample['link']={k:str(data[k])[:80] for k in ('status','rate','full-duplex','auto-negotiation') if k in data}
                    match=re.fullmatch(r'(\d+(?:\.\d+)?)([kMGT]?)bps',str(data.get('rate','')))
                    if data.get('status')=='link-ok' and match:
                        capacity=float(match[1])*{'':1,'k':1000,'M':10**6,'G':10**9,'T':10**12}[match[2]]
                        if 0<capacity<=10**12:sample['capacity_bps']=capacity
                except Exception as exc:
                    sample['error']=error_category(exc)
                self.link_samples[name]=sample;cached=sample
            row['link_monitor']=cached.get('link',{})
            row['capacity_bps']=cached.get('capacity_bps') if row.get('running')=='true' else None
            row['capacity_age_seconds']=round(time.monotonic()-cached['at'],2)
            if cached.get('error'):row['capacity_error']=cached['error']

    def _collect(self, section, filter_field='', filter_value='', request_deadline=None):
        if not self.lock.acquire(blocking=False):
            return self.failure(section, 'collector_busy')
        pool = None
        phase = 'transport'
        try:
            port = int(os.getenv('MIKROTIK_PORT', '8729'))
            use_ssl = port == 8729
            if use_ssl and os.getenv('MIKROTIK_SSL_VERIFY', 'true').lower() != 'true':
                return self.failure(section, 'tls_verification_required')
            if not use_ssl and os.getenv('MIKROTIK_ALLOW_PLAINTEXT', 'false').lower() != 'true':
                return self.failure(section, 'plaintext_not_explicitly_allowed')
            context = ssl.create_default_context(cafile=os.getenv('MIKROTIK_CA_FILE') or None) if use_ssl else None
            deadline = min(time.monotonic() + COLLECT_SECONDS,
                request_deadline if request_deadline is not None else float('inf'))
            for attempt in range(2):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                pool = routeros_api.RouterOsApiPool(os.getenv('MIKROTIK_HOST', '192.168.20.1'),
                    username=os.environ['MIKROTIK_USER'], password=os.environ['MIKROTIK_PASSWORD'],
                    port=port, use_ssl=use_ssl, ssl_verify=True, ssl_verify_hostname=True,
                    ssl_context=context, plaintext_login=True)
                pool.socket_timeout = min(LOGIN_TIMEOUT, remaining)
                phase = 'login'
                login_started = time.monotonic()
                try:
                    api = pool.get_api()
                except Exception as exc:
                    # Retry only a timed-out login, before any permission/data
                    # query. The second attempt shares the original deadline.
                    if attempt or error_category(exc) != 'timeout':
                        raise
                    pool.disconnect()
                    pool = None
                    log.warning('mikrotik_login_retry category=timeout attempt=2')
                    time.sleep(min(.2, max(0, deadline-time.monotonic())))
                    continue
                log.info('mikrotik_api_login duration_ms=%s attempt=%s',
                    round((time.monotonic()-login_started)*1000), attempt+1)
                break
            fingerprint=hashlib.sha256((os.getenv('MIKROTIK_HOST','192.168.20.1')+'\0'+os.environ['MIKROTIK_USER']+'\0'+os.environ['MIKROTIK_PASSWORD']+'\0'+str(port)+'\0'+os.getenv('MIKROTIK_MONITOR_ALLOW_ELEVATED','false')).encode()).digest()
            if self.policy_cache and self.policy_cache[0]==fingerprint and time.monotonic()-self.policy_cache[1]<60:
                granted=set(self.policy_cache[2]);elevated=bool(granted-ALLOWED_READONLY_POLICIES)
            else:
                phase = 'account_permissions'
                self._bound_timeout(pool, deadline)
                users = api.get_resource('/user').call('print', {'.proplist':'name,group'}, {'name':os.environ['MIKROTIK_USER']})
                if len(users) != 1 or not users[0].get('group'):
                    return self.failure(section, 'cannot_verify_account',phase)
                phase = 'group_permissions'
                self._bound_timeout(pool, deadline)
                groups = api.get_resource('/user/group').call('print', {'.proplist':'name,policy'}, {'name':users[0]['group']})
                policy = set(groups[0].get('policy', '').split(',')) if len(groups) == 1 else set()
                granted = {p for p in policy if p and not p.startswith('!')}
                # WinBox is a login method, not configuration write permission. Existing
                # read-only GUI access does not authorize any extra API command here.
                elevated=bool(granted-ALLOWED_READONLY_POLICIES)
                if not {'read','api'} <= granted or elevated and os.getenv('MIKROTIK_MONITOR_ALLOW_ELEVATED','false').lower()!='true':
                    value=self.failure(section, 'excessive_or_unverified_permissions',phase)
                    value['rejected_policies']=sorted(granted-ALLOWED_READONLY_POLICIES)
                    return value
                self.policy_cache=(fingerprint,time.monotonic(),frozenset(granted))
            phase = 'read_data'
            data, resources, errors = {}, {}, {}
            names = LEGACY_NETWORK if section == 'network' else (section,)
            specs = [(SECTIONS[name].path, SECTIONS[name].fields, SECTIONS[name].stats) for name in names]
            if section == 'system':
                specs = [('/system/identity','name',False), *specs, ('/system/clock','time,date,time-zone-name',False)]
            query = {filter_field:filter_value} if filter_field else {}
            for index, (path, fields, stats) in enumerate(specs):
                if time.monotonic() > deadline:
                    errors[path] = 'timeout'
                    break
                try:
                    rows, capped, shortened = self._read(api, pool, path, fields, query, deadline, stats)
                    if path == '/system/resource' and not rows:
                        errors[path] = 'empty_response'
                        continue
                    if path == '/interface' and self.settings.mikrotik_interfaces:
                        rows = [r for r in rows if r.get('name') in self.settings.mikrotik_interfaces]
                    if section=='interfaces' and self.settings.continuous_enabled:
                        self._link_rates(api,pool,rows,deadline)
                    if section == 'traffic' and not capped and rows:
                        # Only print commands, never an unbounded monitor stream or script.
                        first = {r['name']:r for r in rows if 'name' in r}
                        sample_start = time.monotonic()
                        time.sleep(1)
                        rows, capped, second_shortened = self._read(api, pool, path, fields, query, deadline, stats)
                        elapsed = time.monotonic() - sample_start
                        shortened |= second_shortened
                        rows = [r for r in rows if r.get('name') in first]
                        for row in rows:
                            for direction in ('rx','tx'):
                                try:
                                    delta = int(row[direction+'-byte']) - int(first[row['name']][direction+'-byte'])
                                    rate = round(delta*8/elapsed, 2) if delta >= 0 else None
                                except (KeyError, ValueError):
                                    rate = None
                                row[direction+'_bits_per_second'] = rate
                            row['sample_seconds'] = round(elapsed, 3)
                            row['rate_sample_valid'] = all(row[d+'_bits_per_second'] is not None for d in ('rx','tx'))
                    data[path] = rows
                    lower_bound = len(rows) + (1 if capped and not (path == '/interface' and self.settings.mikrotik_interfaces) else 0)
                    resources[path] = {'total':None if capped else len(rows), 'total_at_least':lower_bound,
                        'scan_truncated':capped, 'fields_truncated':shortened}
                    if capped:
                        # This connection is no longer at a sentence boundary: do not reuse.
                        for remaining_path, _, _ in specs[index+1:]:
                            errors[remaining_path] = 'response_limit'
                        break
                except Exception as exc:
                    category = error_category(exc)
                    if category=='permission_denied':self.policy_cache=None
                    errors[path] = category
                    if category not in {'unsupported_section','permission_denied'}:
                        break
            if not data:
                return self.failure(section, next(iter(errors.values()), 'connection_failed'))
            if section == 'system' and not any(data.values()):
                return self.failure(section, 'empty_response')
            value = result('mikrotik', 'RouterOS API-SSL' if use_ssl else 'RouterOS API internal TANPA TLS',
                'DEGRADED' if errors else 'UP', section=section, data=data, resources=resources)
            value['credential_privilege']='elevated-read-adapter' if elevated else 'read-only'
            if errors:
                value['errors'] = errors
                value['detail'] = 'Hasil parsial; menu yang gagal belum memiliki data yang dapat dipastikan.'
            if section == 'traffic':
                value['rate_method'] = 'Selisih counter byte RX/TX × 8 / selang aktual dua print, sekitar 1 detik; bukan rata-rata jangka panjang.'
            return value
        except Exception as exc:
            return self.failure(section, error_category(exc),phase)
        finally:
            try:
                if pool:
                    pool.disconnect()
            except Exception:
                pass
            finally:
                self.lock.release()
