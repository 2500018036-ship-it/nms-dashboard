import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock,patch
from telegram.error import TimedOut
from telegram.ext import ExtBot
from app.config import Settings
from app.main import build

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_checked_before_background_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Settings('123456:fakeToken',frozenset({1}),'dummy',('model',),data_dir=directory)
            heartbeat=Path(directory)/'health.json'
            heartbeat.write_text('{"poller_ready":true}')
            app=build(cfg)
            self.assertFalse(heartbeat.exists())
            with patch.object(ExtBot,'get_me',AsyncMock()) as get_me:
                await app.post_init(app)
                get_me.assert_awaited_once()
                self.assertEqual({task.get_name() for task in app.bot_data['tasks']},{'monitor-scheduler','heartbeat','device-config-backups','notification-worker'})
                await app.post_stop(app)
                self.assertNotIn('tasks',app.bot_data)
                await app.post_shutdown(app)

    async def test_identity_failure_creates_no_orphan_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=Settings('123456:fakeToken',frozenset({1}),'dummy',('model',),data_dir=directory)
            app=build(cfg)
            with patch.object(ExtBot,'get_me',AsyncMock(side_effect=TimedOut())):
                with self.assertRaises(TimedOut):await app.post_init(app)
                self.assertNotIn('tasks',app.bot_data)
                await app.post_shutdown(app)
