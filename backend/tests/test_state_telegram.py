import json
import os
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock,patch

from telegram.error import TimedOut,BadRequest
from app.config import Settings
from app.storage.database import Database
from app.alerts.engine import Alerts
from app.telegram.handlers import Handlers
from app.telegram.formatting import chunks
from app.logging_config import redact

class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.db=Database(self.tmp.name)
        self.cfg=Settings('t',frozenset({1}),'k',('m',))
        self.alerts=Alerts(self.cfg,self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()

    def test_alert_dedup_recovery_restart(self):
        self.assertIsNone(self.alerts.observe('dns',True,{},now=100))
        self.assertEqual(self.alerts.observe('dns',True,{},now=200)['kind'],'ALERT')
        self.assertIsNone(self.alerts.observe('dns',True,{},now=300))
        again=Alerts(self.cfg,self.db)
        self.assertIsNone(again.observe('dns',True,{},now=400))
        self.assertIsNone(again.observe('dns',None,{},now=500))
        self.assertIsNone(again.observe('dns',False,{},now=600))
        self.assertEqual(again.observe('dns',False,{},now=700)['kind'],'RECOVERY')

    def test_hysteresis(self):
        self.alerts.metric('cpu',95,90);self.alerts.metric('cpu',96,90)
        self.alerts.metric('cpu',89,90);self.alerts.metric('cpu',89,90)
        self.assertTrue(self.db.states()['cpu']['active'])
        self.alerts.metric('cpu',84,90);self.alerts.metric('cpu',84,90)
        self.assertFalse(self.db.states()['cpu']['active'])

    def test_unknown_not_recovery_or_down(self):
        row={'target':'proxmox_resources','status':'UNKNOWN','method':'api','error':'missing_readonly_token'}
        for _ in range(4):self.alerts.evaluate([row])
        self.assertFalse(self.db.states()['proxmox_resources:availability']['active'])
        self.assertFalse(self.db.states()['proxmox_resources:collector']['active'])

    def test_notification_dedup(self):
        self.alerts.observe('x',True,{},now=1);self.alerts.observe('x',True,{},now=2)
        self.assertEqual(len(self.alerts.pending()),1)
        self.alerts.attempted('x',False)
        self.assertEqual(self.alerts.pending(),[])
        self.alerts.attempted('x',True)
        self.assertEqual(self.alerts.pending(),[])

    def test_router_permission_gap_is_not_service_outage(self):
        row={'target':'mikrotik_system','status':'UNKNOWN','method':'API','error':'excessive_or_unverified_permissions'}
        for _ in range(4):self.alerts.evaluate([row])
        self.assertFalse(self.db.states()['mikrotik_system:availability']['active'])
        self.assertFalse(self.db.states()['mikrotik_system:collector']['active'])

    def test_expected_stopped_container_no_alert(self):
        row={'target':'docker','status':'UP','method':'snapshot','containers':[{'name':'restore-check','state':'exited','expected_running':False}]}
        for _ in range(3):self.alerts.evaluate([row])
        self.assertNotIn('container:restore-check',self.db.states())

    def test_storage_history_and_cleanup(self):
        self.db.save({'target':'dns','status':'UP','value':1})
        self.db.save({'target':'dns','status':'DOWN','value':2})
        self.assertEqual(self.db.history('dns')[0]['value'],2)
        self.db.db.execute('UPDATE checks SET ts=0');self.db.db.commit()
        self.db.cleanup(30)
        self.assertEqual(self.db.history('dns'),[])

class TelegramTests(unittest.IsolatedAsyncioTestCase):
    def handler(self):return Handlers(Settings('t',frozenset({1}),'k',('m',)),None,None,None,None)

    async def test_unauthorized_all_commands(self):
        h=self.handler();update=NS(effective_user=NS(id=999),effective_chat=NS(type='private'),effective_message=NS(text='test',reply_text=AsyncMock()))
        context=NS(args=['test'])
        for method in (h.start,h.status,h.diagnostics,h.history,h.ask,h.chat,h.mikrotik,h.reset,h.events,h.alerts,h.devices):await method(update,context)
        update.effective_message.reply_text.assert_not_called()

    async def test_group_denied(self):
        h=self.handler()
        self.assertFalse(h.allowed(NS(effective_user=NS(id=1),effective_chat=NS(type='group'))))

    async def test_edit_timeout_falls_back(self):
        h=self.handler();message=NS(reply_text=AsyncMock());status=NS(edit_text=AsyncMock(side_effect=TimedOut()))
        self.assertTrue(await h.deliver(message,'actual AI answer',status))
        message.reply_text.assert_awaited_once()

    async def test_send_timeout_no_blind_retry(self):
        h=self.handler();message=NS(reply_text=AsyncMock(side_effect=TimedOut()))
        self.assertFalse(await h.deliver(message,'answer'))
        self.assertEqual(message.reply_text.await_count,1)

    async def test_long_message_no_truncation(self):
        text='A😀'*4000
        parts=list(chunks(text))
        self.assertEqual(''.join(parts),text)
        self.assertTrue(all(len(p.encode('utf-16-le'))//2<=3500 for p in parts))

    async def test_rate_limit(self):
        h=self.handler();u=NS(effective_user=NS(id=1),effective_chat=NS(type='private'))
        self.assertTrue(await h.guard(u));self.assertFalse(await h.guard(u))

class ConfigTests(unittest.TestCase):
    def test_required_secrets(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):Settings.load()

    def test_valid_minimum(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','OPENROUTER_API_KEY':'dummy','ALLOWED_TELEGRAM_ID':'1'}
        with patch.dict(os.environ,env,clear=True):self.assertEqual(Settings.load().poll_interval,180)

    def test_interval_too_aggressive(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','OPENROUTER_API_KEY':'dummy','ALLOWED_TELEGRAM_ID':'1','MONITOR_INTERVAL':'5'}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaises(ValueError):Settings.load()

    def test_alert_chat_not_allowlisted(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','OPENROUTER_API_KEY':'dummy','ALLOWED_TELEGRAM_ID':'1','ALERT_CHAT_ID':'999'}
        with patch.dict(os.environ,env,clear=True):
            with self.assertRaises(ValueError):Settings.load()

    def test_redaction(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'my-super-secret'}):
            self.assertNotIn('my-super-secret',redact('error my-super-secret'))
        self.assertNotIn('123456789:abc',redact('https://api.telegram.org/bot123456789:abc/getMe'))
