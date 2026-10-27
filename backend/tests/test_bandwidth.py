import os
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock,AsyncMock,patch
from app.config import Settings
from app.monitoring.mikrotik import MikroTik
from app.telegram.handlers import Handlers
from app.storage.database import Database
from app.main import build

def settings(**kw):return Settings('123456:fakeToken',frozenset({1}),'k',('m',),**kw)

class CapacityTests(unittest.TestCase):
    def test_only_fixed_read_monitor_and_negotiated_capacity(self):
        api=Mock();pool=Mock();router=MikroTik(settings())
        api.get_resource.return_value.call.return_value=[{'status':'link-ok','rate':'100Mbps','full-duplex':'true','advertising':'10Gbps','private-key':'never-export'}]
        row={'name':'ether3','type':'ether','running':'true'}
        router._link_rates(api,pool,[row],time.monotonic()+15)
        self.assertEqual(row['capacity_bps'],100000000)
        self.assertNotIn('advertising',str(row));self.assertNotIn('never-export',str(row))
        api.get_resource.assert_called_once_with('/interface/ethernet')
        command,arguments=api.get_resource.return_value.call.call_args.args
        self.assertEqual(command,'monitor');self.assertEqual(arguments['once'],'');self.assertEqual(arguments['numbers'],'ether3')
        router._link_rates(api,pool,[row],time.monotonic()+15)
        self.assertEqual(api.get_resource.return_value.call.call_count,1)
        row['running']='false'
        router._link_rates(api,pool,[row],time.monotonic()+15)
        self.assertIsNone(row['capacity_bps'])

    def test_missing_rate_error_and_invalid_name_never_infer_capacity(self):
        for response in ([{'status':'no-link','rate':'100Mbps'}],[{'status':'link-ok','advertising':'100Mbps'}],[]):
            api=Mock();api.get_resource.return_value.call.return_value=response
            row={'name':'ether1','type':'ether','running':'true'}
            MikroTik(settings())._link_rates(api,Mock(),[row],time.monotonic()+15)
            self.assertIsNone(row['capacity_bps'])
        api=Mock();api.get_resource.return_value.call.side_effect=TimeoutError()
        row={'name':'ether1','type':'ether','running':'true'}
        MikroTik(settings())._link_rates(api,Mock(),[row],time.monotonic()+15)
        self.assertIsNone(row['capacity_bps']);self.assertEqual(row['capacity_error'],'timeout')
        api=Mock();MikroTik(settings())._link_rates(api,Mock(),[{'name':'ether1; /system reboot','type':'ether'}],time.monotonic()+15)
        api.get_resource.assert_not_called()

class ThresholdConfigTests(unittest.TestCase):
    def test_requested_defaults_and_bad_thresholds(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','ALLOWED_TELEGRAM_ID':'1'}
        with patch.dict(os.environ,env,clear=True):
            cfg=Settings.load()
            self.assertEqual((cfg.cooldown,cfg.traffic_spike_factor,cfg.traffic_spike_seconds,cfg.bandwidth_warning,cfg.bandwidth_critical,cfg.bandwidth_seconds),(600,2,60,85,95,30))
        for extra in ({'BANDWIDTH_WARNING_PERCENT':'95','BANDWIDTH_CRITICAL_PERCENT':'90'},
                {'TRAFFIC_SPIKE_SECONDS':'0'},{'BANDWIDTH_SUSTAIN_SECONDS':'0'}):
            with patch.dict(os.environ,{**env,**extra},clear=True):
                with self.assertRaises(ValueError):Settings.load()

class CommandsTests(unittest.IsolatedAsyncioTestCase):
    async def test_commands_registered_and_unknown_devices_not_claimed_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            cfg=settings(data_dir=directory)
            app=build(cfg)
            commands={command for handler in app.handlers[0] for command in getattr(handler,'commands',[])}
            self.assertTrue({'status','alerts','history','devices','help','ask'}<=commands)
            h=app.bot_data['handlers'];h.deliver=AsyncMock()
            update=NS(effective_user=NS(id=1),effective_chat=NS(type='private'),effective_message=NS())
            await h.devices(update,NS(args=[]))
            text=h.deliver.call_args.args[1]
            self.assertIn('UNKNOWN',text);self.assertIn('Proxmox',text);self.assertIn('Cisco',text)
            h.last_requests.clear();await h.alerts(update,NS(args=[]))
            self.assertIn('0 kondisi',h.deliver.call_args.args[1])
            h.last_requests.clear();await h.history(update,NS(args=[]))
            self.assertIn('Belum ada kejadian',h.deliver.call_args.args[1])
            await app.post_shutdown(app)
