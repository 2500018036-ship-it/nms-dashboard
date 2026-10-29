import asyncio
import base64
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.dashboard.device_backups import DeviceConfigBackups
from app.storage.database import Database
from app.services.health import Monitoring


def router_inventory(name='MikroTik'):
    return {'name': name, 'host': '192.168.20.1', 'type': 'router', 'vendor': 'MikroTik',
        'model': 'RouterOS', 'methods': ['api'], 'interval': 60, 'group': 'LAN', 'tags': [],
        'profile': 'network', 'enabled': True, 'credential_ref': 'routeros-default',
        'monitor_method': 'routeros'}


class DeviceConfigBackupsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key = base64.urlsafe_b64encode(b'B' * 32).decode().rstrip('=')
        self.env = patch.dict(os.environ, {'NMS_CREDENTIALS_KEY': self.key, 'MIKROTIK_HOST': '192.168.20.1'})
        self.env.start()
        self.cfg = Settings('t', frozenset({1}), '', ('m',), data_dir=self.tmp.name, continuous_enabled=False)
        self.database = Database(self.tmp.name)
        self.monitor = Monitoring(self.cfg, self.database)
        self.backups: DeviceConfigBackups = self.monitor.device_backups
        self.device = self.monitor.platform.save('inventory', {'value': router_inventory()}, 'admin')
        self.export = AsyncMock(return_value='/system identity\nset name=router')
        self.monitor.router.export_configuration = self.export

    async def asyncTearDown(self):
        self.database.close()
        self.env.stop()
        self.tmp.cleanup()

    async def capture(self, text=None):
        if text is not None:
            self.export.return_value = text
        run = self.backups._new_run(self.device['id'], 'admin', 'manual')
        return await self.backups._execute(run, self.device['id'], 'admin')

    async def test_encrypted_version_compare_download_and_confirmed_manual_restore(self):
        first = await self.capture('/system identity\nset name=router')
        second = await self.capture('/system identity\nset name=router-2')
        self.assertEqual(first['state'], 'COMPLETE')
        self.assertEqual(second['state'], 'COMPLETE')
        entry = self.backups._metadata(first['backup_id'])
        encrypted = (self.backups.root / entry['file_name']).read_bytes()
        self.assertNotIn(b'/system identity', encrypted)
        self.assertEqual(self.backups._read(first['backup_id'])[1], '/system identity\nset name=router')
        file = self.backups.download(first['backup_id'], 'admin')
        self.assertEqual(base64.b64decode(file['content_b64']), b'/system identity\nset name=router')
        diff = self.backups.compare(first['backup_id'], second['backup_id'], 'admin')
        self.assertFalse(diff['same'])
        self.assertIn('-set name=router', diff['diff'])
        with self.assertRaisesRegex(ValueError, 'restore_confirmation_required'):
            self.backups.prepare_restore(first['backup_id'], 'RESTORE wrong', 'admin')
        restore = self.backups.prepare_restore(first['backup_id'], 'RESTORE ' + first['backup_id'], 'admin')
        self.assertEqual(restore['mode'], 'manual-native-gui')
        self.assertEqual(base64.b64decode(restore['content_b64']), b'/system identity\nset name=router')
        self.assertFalse(hasattr(self.monitor.router, 'apply_configuration'))
        self.assertEqual(self.backups.run_status(first['id'])['state'], 'COMPLETE')

    async def test_retention_scheduler_and_duplicate_device_run_guard(self):
        self.backups.save_policy(self.device['id'], {'enabled': True, 'interval_seconds': 3600, 'retention_versions': 2}, 'admin')
        with self.backups.store.db() as db:
            db.execute('UPDATE device_backup_policies SET next_due=0 WHERE inventory_id=?', (self.device['id'],))
        await self.backups.run_due()
        first_version = self.backups.catalog()['devices'][0]['versions'][0]
        self.assertEqual(first_version['format'], 'rsc')
        first_file = self.backups._metadata(first_version['id'])['file_name']
        active = self.backups._new_run(self.device['id'], 'admin', 'manual')
        self.assertEqual(self.backups._new_run(self.device['id'], 'admin', 'manual'), active)
        with self.backups.store.db() as db:
            db.execute("UPDATE device_backup_runs SET status='FAILED',finished=? WHERE id=?", (1, active))
        await self.capture('/system identity\nset name=second')
        await self.capture('/system identity\nset name=third')
        versions = self.backups.catalog()['devices'][0]['versions']
        self.assertEqual(len(versions), 2)
        self.assertNotIn(first_version['id'], [version['id'] for version in versions])
        self.assertFalse((self.backups.root / first_file).exists())
        self.assertEqual(self.export.await_count, 3)

    async def test_unsupported_devices_fail_closed_and_policy_bounds_are_enforced(self):
        unsupported = self.monitor.platform.save('inventory', {'value': {
            'name': 'Cisco', 'host': '192.168.10.26', 'type': 'switch', 'methods': ['icmp'],
            'interval': 60, 'profile': 'connectivity', 'enabled': True}}, 'admin')
        catalog = self.backups.catalog()
        self.assertFalse(next(row for row in catalog['devices'] if row['device']['id'] == unsupported['id'])['supported'])
        with self.assertRaisesRegex(ValueError, 'backup_unsupported'):
            self.backups.save_policy(unsupported['id'], {'enabled': True, 'interval_seconds': 3600, 'retention_versions': 10}, 'admin')
        with self.assertRaisesRegex(ValueError, 'invalid_number'):
            self.backups.save_policy(self.device['id'], {'enabled': True, 'interval_seconds': 30, 'retention_versions': 1}, 'admin')
        self.assertEqual(self.export.await_count, 0)


class RouterOSExportGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_requires_verified_read_only_account_before_export_command(self):
        from app.monitoring.mikrotik import MikroTik
        cfg = Settings('t', frozenset({1}), '', ('m',), mikrotik_readonly=True)
        router = MikroTik(cfg)
        router.collect = AsyncMock(return_value={'status': 'DEGRADED', 'credential_privilege': 'read-only'})
        with patch.object(router, '_export_configuration', return_value='/system identity') as command:
            self.assertEqual(await router.export_configuration(), '/system identity')
            command.assert_called_once()
        router.collect = AsyncMock(return_value={'status': 'UP', 'credential_privilege': 'elevated-read-adapter'})
        with patch.object(router, '_export_configuration') as command:
            with self.assertRaisesRegex(RuntimeError, 'readonly_account_required'):
                await router.export_configuration()
            command.assert_not_called()
