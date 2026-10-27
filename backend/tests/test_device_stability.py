import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.dashboard.device_registry import dhcp_address
from app.dashboard.platform import Platform, Conflict, Forbidden
from app.dashboard.server import Dashboard
from app.monitoring.common import result
from app.services.health import Monitoring
from app.storage.database import Database
import test_dashboard_sessions as helpers


MAC = '20:E1:5D:91:53:DC'


def device(host='192.168.10.26', **extra):
    value=dict(name='Cisco', host=host, type='switch', methods=['icmp'], interval=30,
                profile='connectivity', enabled=True, monitor_method='icmp')
    value.update(extra)
    return value


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Settings('test', frozenset({1}), '', ('m',), data_dir=self.tmp.name,
            targets={'ap': {'name': 'TLWR', 'host': '192.168.30.194', 'kind': 'icmp', 'mac_address': MAC, 'follow_dhcp': True},
                     'management': {'name': 'Management', 'host': '192.168.10.200', 'kind': 'icmp'}})
        self.store = Platform(self.tmp.name, self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_explicit_authorization_is_atomic_and_only_adds_exact_host(self):
        with self.assertRaisesRegex(ValueError, 'host_not_allowed'):
            self.store.save('inventory', {'value': device()}, 'admin')
        before = self.store.get_settings()
        with self.assertRaises(ValueError):
            self.store.save('inventory', {'value': device(interval=0), 'authorize_host': True}, 'admin')
        self.assertEqual(self.store.get_settings(), before)
        saved = self.store.save('inventory', {'value': device(), 'authorize_host': True}, 'admin')
        self.assertEqual(saved['host'], '192.168.10.26')
        self.assertEqual(set(self.store.get_settings()['value']['allowed_hosts']) - set(before['value']['allowed_hosts']), {'192.168.10.26'})
        with self.assertRaises(ValueError):
            self.store.save('inventory', {'value': device('169.254.169.254'), 'authorize_host': True}, 'admin')

    def test_seed_merges_existing_host_and_delete_does_not_reappear_on_restart(self):
        existing = self.store.save('inventory', {'value': device('192.168.30.194')}, 'admin')
        self.store.sync_inventory()
        self.assertEqual(len(self.store.list('inventory')), 2)
        item = self.store.get('inventory', existing['id'])
        self.assertEqual(item['mac_address'], MAC)
        self.assertTrue(item['follow_dhcp'])
        self.assertEqual(self.store.inventory_target(item), 'ap')
        self.store.remove('inventory', item['id'], item['revision'], 'admin')
        restarted = Platform(self.tmp.name, self.cfg)
        restarted.sync_inventory()
        self.assertIsNone(restarted.get('inventory', item['id']))
        self.assertEqual(len(restarted.list('inventory')), 1)

    def test_delete_detaches_topology_atomically_with_revision_checks(self):
        self.store.sync_inventory()
        item = self.store.list('inventory')[0]
        graph = self.store.save('topologies', {'value': dict(name='LAN', nodes=[
            dict(id='device', name='AP', kind='access-point', x=0, y=0, device_id=item['id']),
            dict(id='router', name='Router', kind='router', x=100, y=0)],
            links=[dict(id='cable', source='device', target='router', type='Ethernet', label='LAN')])}, 'admin')
        with self.assertRaises(ValueError):
            self.store.remove('inventory', item['id'], item['revision'], 'admin')
        with self.assertRaises(Conflict):
            self.store.remove('inventory', item['id'], item['revision'] + 1, 'admin', detach=True)
        self.assertEqual(self.store.get('topologies', graph['id'])['revision'], 1)
        self.store.remove('inventory', item['id'], item['revision'], 'admin', detach=True)
        reloaded = self.store.get('topologies', graph['id'])
        self.assertEqual(reloaded['revision'], 2)
        self.assertEqual([n['id'] for n in reloaded['nodes']], ['router'])
        self.assertEqual(reloaded['links'], [])

    def test_dhcp_requires_matching_unique_bound_mac_in_known_subnet(self):
        item = device('192.168.30.194', mac_address=MAC, follow_dhcp=True)
        lease = {'status': 'bound', 'mac-address': MAC, 'active-address': '192.168.10.194'}
        self.assertEqual(dhcp_address(item, [lease], self.store.configured_hosts()), '192.168.10.194')
        for invalid in [dict(lease, status='waiting'), dict(lease, **{'mac-address': 'AA:BB:CC:DD:EE:FF'}),
                        dict(lease, **{'active-address': '169.254.169.254'}), dict(lease, **{'active-address': '192.168.99.9'})]:
            self.assertIsNone(dhcp_address(item, [invalid], self.store.configured_hosts()))
        self.assertIsNone(dhcp_address(item, [lease, dict(lease, **{'active-address': '192.168.10.195'})], self.store.configured_hosts()))


class ProbeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Settings('test', frozenset({1}), '', ('m',), data_dir=self.tmp.name,
            targets={'ap': {'name': 'TLWR', 'host': '192.168.30.194', 'kind': 'icmp', 'mac_address': MAC, 'follow_dhcp': True},
                     'management': {'name': 'Management', 'host': '192.168.10.200', 'kind': 'icmp'}})
        self.db = Database(self.tmp.name)
        self.monitor = Monitoring(self.cfg, self.db)
        self.monitor.platform.sync_inventory()
        self.monitor.router.collect = AsyncMock(return_value={'status': 'UP', 'data': {'/ip/dhcp-server/lease': [
            {'status': 'bound', 'mac-address': MAC, 'active-address': '192.168.10.194'}]}})

    async def asyncTearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_failed_old_ip_follows_verified_mac_and_persists_new_ip(self):
        async def echo(target, host):
            return result(target, 'ICMP echo', 'UP' if host == '192.168.10.194' else 'DOWN', host=host)
        with patch('app.services.health.icmp.probe', side_effect=echo) as probe:
            value = await self.monitor.check('ap')
            self.assertEqual(value['status'], 'UP')
            self.assertEqual(value['host'], '192.168.10.194')
            self.assertEqual(value['address_source'], 'dhcp_mac')
            item = next(x for x in self.monitor.platform.list('inventory') if x['name'] == 'TLWR')
            self.assertEqual(item['host'], '192.168.10.194')
            self.assertIn(item['host'], self.monitor.platform.get_settings()['value']['allowed_hosts'])
            self.assertEqual(Platform(self.tmp.name, self.cfg).inventory_target(item), 'ap')
            await self.monitor.check('ap', force=True)
            calls = probe.call_count
            await self.monitor.check('ap')
            self.assertEqual(probe.call_count, calls)
            await self.monitor.check('ap', force=True)
            self.assertEqual(probe.call_count, calls + 1)

    async def test_unverified_new_address_does_not_become_up_or_rewrite_record(self):
        with patch('app.services.health.icmp.probe', side_effect=lambda target, host: result(target, 'ICMP echo', 'DOWN', host=host)):
            value = await self.monitor.check('ap')
        self.assertEqual(value['status'], 'DOWN')
        self.assertEqual(next(x for x in self.monitor.platform.list('inventory') if x['name'] == 'TLWR')['host'], '192.168.30.194')

    async def test_revoked_exact_host_does_not_bypass_probe_policy(self):
        row = self.monitor.platform.get_settings()
        row['value']['allowed_hosts'].remove('192.168.30.194')
        with self.monitor.platform.db() as db:
            db.execute('UPDATE platform_settings SET payload=? WHERE id=1', (json.dumps(row['value']),))
        with patch('app.services.health.icmp.probe', AsyncMock()) as probe:
            value = await self.monitor.check('ap')
        self.assertEqual(value['error'], 'host_not_allowed')
        probe.assert_not_awaited()

    async def test_icmp_retries_one_lost_reply_and_keeps_permission_failure_unknown(self):
        from app.monitoring.icmp import probe
        with patch('app.monitoring.icmp._probe_once', AsyncMock(side_effect=[result('ap', 'ICMP', 'DOWN'), result('ap', 'ICMP', 'UP')])) as once:
            self.assertEqual((await probe('ap', '192.168.10.194'))['status'], 'UP')
            self.assertEqual(once.await_count, 2)
        with patch('app.monitoring.icmp._probe_once', AsyncMock(return_value=result('ap', 'ICMP', error='icmp_not_permitted'))) as once:
            self.assertEqual((await probe('ap', '192.168.10.194'))['status'], 'UNKNOWN')
            once.assert_awaited_once()


class EnrollmentAPITests(unittest.TestCase):
    setUp=helpers.SessionAPITests.setUp
    tearDown=helpers.SessionAPITests.tearDown
    request=helpers.SessionAPITests.request
    def test_network_admin_cannot_silently_widen_allowlist(self):
        from app.dashboard.platform_api import PlatformAPI
        api = self.server.platform
        session = {'user': {'username': 'network', 'role': 'Network Administrator'}}
        before = api.store.get_settings()
        with self.assertRaises(Forbidden):
            api.post('/api/platform/inventory', {'value': device(), 'authorize_host': True}, session)
        self.assertEqual(api.store.get_settings(), before)

    def test_admin_gets_specific_validation_and_can_register_new_host(self):
        self.server.platform.store.bootstrap('admin-only-' + 'A' * 30)
        status, _, headers = self.request('/api/auth/login', 'POST', {'username': 'admin', 'password': 'admin-only-' + 'A' * 30})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        status, body, _ = self.request('/api/platform/inventory', 'POST', {'value': device()})
        self.assertEqual((status, body['code']), (400, 'host_not_allowed'))
        self.assertEqual(self.request('/api/platform/inventory', 'POST', {'value': device(), 'authorize_host': True})[0], 200)

    def test_reachable_host_is_not_unknown_when_resource_collector_times_out(self):
        now = time.time()
        base = dict(sample_epoch=now, stale_after_seconds=180)
        rows = [dict(base, target='host', host='192.168.20.1', status='UP', method='ICMP echo'),
                dict(base, target='mikrotik_system', status='UNKNOWN', method='RouterOS API')]
        values = self.server.devices(rows)
        self.assertEqual(values[0]['status'], 'UP')
        self.assertEqual(values[0]['read_state'], 'partial_failure')

    def test_proxy_clients_with_valid_sessions_have_separate_rate_budgets(self):
        self.server.platform.store.bootstrap('admin-only-' + 'A' * 30)
        status, _, headers = self.request('/api/auth/login', 'POST', {'username': 'admin', 'password': 'admin-only-' + 'A' * 30})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        statuses = [self.request('/api/auth/session')[0] for _ in range(121)]
        self.assertIn(429, statuses)
        self.cookie = ''
        status, _, headers = self.request('/api/auth/login', 'POST', {'username': 'nms', 'password': self.cfg.dashboard_password})
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/auth/session')[0], 200)
