import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from app.config import Settings
from app.alerts.network import NetworkEvents
from app.alerts.outbox import Outbox
from app.services.scheduler import Scheduler
from app.storage.database import Database

def settings(**kw):return Settings('t',frozenset({1}),'',('m',),continuous_enabled=True,**kw)

class ZeroTrafficTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(self.temp.name)
        self.cfg=settings();self.engine=NetworkEvents(self.cfg,self.db)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def sample(self,rx,tx,at,running=True):return self.engine.idle.observe('ether4',rx,tx,at,running)

    def test_zero_five_minutes_and_recovery_one_minute_only_once(self):
        for at in range(0,300,15):self.sample(0,0,at)
        self.assertEqual(self.db.events(),[])
        self.sample(0,0,300)
        self.assertEqual(self.db.events()[0]['kind'],'ALERT')
        self.assertEqual(self.db.events()[0]['value']['sustained_seconds'],300)
        for at in (315,330,345):self.sample(0,0,at)
        self.assertEqual(len(self.db.events()),1)
        for at in (360,375,390,405):self.sample(1,0,at)
        self.assertEqual(len(self.db.events()),1)
        self.sample(1,0,420)
        self.assertEqual([e['kind'] for e in self.db.events()],['RECOVERY','ALERT'])
        self.assertEqual(self.db.events()[0]['first_seen'],0)
        for at in (435,450,465):self.sample(0,1,at)
        self.assertEqual(len(self.db.events()),2)

    def test_ordinary_fluctuations_and_one_busy_direction_never_alert(self):
        for at in range(0,1200,15):
            rx=(0,2500,36000,120000,10000000)[(at//15)%5]
            self.sample(rx,1,at)
        self.assertEqual(self.db.events(),[])
        # Real counter calculation, new default disables old baseline rules.
        counters=100
        for at in range(0,1200,15):
            counters+=(100,20000,2,10000000)[(at//15)%4]
            self.engine.interfaces([{'name':'ether3','type':'ether','running':'true','disabled':'false',
                'rx-byte':str(counters),'tx-byte':str(counters),'link-downs':'0'}],at)
        self.assertEqual(self.db.events(),[])

    def test_missing_reset_gap_and_down_are_not_zero_or_recovery(self):
        for at in range(0,300,15):self.sample(0,0,at)
        self.sample(None,None,300);self.sample(0,0,315)
        self.assertEqual(self.db.events(),[])
        self.sample(0,0,1000)  # Long gap starts a new interval.
        self.assertEqual(self.db.events(),[])
        for at in range(1015,1301,15):self.sample(0,0,at)
        self.assertEqual(len(self.db.events()),1)
        self.sample(None,None,1315);self.sample(0,0,1330,False)
        self.assertTrue(self.db.states()['network:idle:ether4']['active'])
        self.assertEqual(len(self.db.events()),1)
        for at in (1345,1360,1375):self.sample(1,1,at)
        self.sample(0,0,1390)  # Interrupt the recovery interval.
        for at in (1405,1420,1435,1450):self.sample(1,1,at)
        self.assertEqual(len(self.db.events()),1)
        self.sample(1,1,1465)
        self.assertEqual(self.db.events()[0]['kind'],'RECOVERY')

    def test_restart_preserves_timer_and_confirmed_incident(self):
        for at in range(100,400,15):self.sample(0,0,at)
        self.db.close();self.db=Database(self.temp.name)
        self.engine=NetworkEvents(self.cfg,self.db);self.sample(0,0,400)
        self.assertEqual(self.db.events()[0]['first_seen'],100)
        NetworkEvents(self.cfg,self.db).idle.observe('ether4',0,0,415)
        self.assertEqual(len(self.db.events()),1)
        self.assertEqual(len(self.db.events(component='mikrotik')),1)

    def test_link_down_still_immediate_and_idle_requires_running(self):
        row={'name':'ether4','type':'ether','running':'true','disabled':'false','rx-byte':'100','tx-byte':'100'}
        self.engine.interfaces([row],0)
        self.engine.interfaces([{**row,'running':'false'}],15)
        self.assertEqual(self.db.events()[0]['key'],'network:link:ether4')
        self.assertEqual(self.db.events()[0]['kind'],'ALERT')
        for at in range(30,700,15):self.engine.interfaces([{**row,'running':'false'}],at)
        self.assertEqual(len(self.db.events()),1)

class QuietDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(self.temp.name)
        self.outbox=Outbox(self.db)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def add(self,kind,stamp,incident,key='network:idle:ether4'):
        return self.db.event(key,kind,{'key':key,'kind':kind,'time':stamp,'first_seen':incident,'value':{}})

    def test_cooldown_survives_recovery_restart_and_suppresses_orphan_recovery(self):
        self.add('ALERT',300,0);self.add('RECOVERY',360,0)
        self.add('ALERT',660,360);self.add('RECOVERY',720,360)
        self.add('ALERT',900,600);self.add('RECOVERY',960,600)
        self.outbox.stage()
        again=Outbox(self.db)
        pending=again.pending()
        self.assertEqual([e['kind'] for i,e in pending],['ALERT','RECOVERY','ALERT','RECOVERY'])
        self.assertEqual(dict(self.db.db.execute('select status,count(*) from notifications group by status')),{'pending':4,'suppressed':2})

    def test_other_devices_and_real_link_changes_bypass_idle_cooldown(self):
        for key in ('network:idle:ether4','network:idle:ether3','network:link:ether1'):
            self.add('ALERT',300,0,key);self.add('RECOVERY',360,0,key)
        self.outbox.stage()
        self.assertEqual(len(self.outbox.pending()),6)

    def test_recovery_waits_for_alert_transport_and_skips_failed_alert(self):
        identity=self.add('ALERT',300,0);recovery=self.add('RECOVERY',360,0)
        self.outbox.stage();self.outbox.mark([identity],'retry')
        self.assertEqual(self.outbox.pending(),[])
        for _ in range(4):self.outbox.mark([identity],'retry')
        self.assertEqual(self.outbox.pending(now=1e12),[])
        self.assertEqual(self.db.db.execute('select status from notifications where event_id=?',(recovery,)).fetchone()[0],'suppressed')

    async def test_old_noisy_alerts_cancelled_personal_client_observation_only(self):
        targets={'phone':{'name':'Phone','host':'192.168.30.196','kind':'icmp','alert_on_unreachable':False},
            'server':{'name':'Server','host':'192.168.20.195','kind':'icmp','alert_on_unreachable':True}}
        self.add('ALERT',100,90,'network:traffic:ether4:rx')
        self.add('ALERT',100,90,'network:device:phone')
        self.add('ALERT',100,90,'network:link:ether1')
        self.outbox.stage()
        for key in ('network:traffic:ether4:rx','network:device:phone'):
            self.db.set_state(key,{'active':True,'current':'DOWN'})
        bot=NS(send_message=AsyncMock())
        scheduler=Scheduler(settings(targets=targets,alerts=True,alert_chat_id=1),self.db,None,bot)
        self.assertFalse(self.db.states()['network:device:phone']['active'])
        self.assertFalse(self.db.states()['network:traffic:ether4:rx']['active'])
        for target in ('phone','server'):
            for status in ('UP','DOWN','DOWN','UP','UP','DOWN','DOWN'):
                scheduler.observe_devices([{'target':target,'status':status,'method':'ICMP echo','host':targets[target]['host']}])
        self.assertEqual(len(self.db.events(component='devices')),5)  # phone history + retirement; three real server transitions.
        phone_events=[e for e in self.db.events(30) if e['key']=='network:device:phone']
        self.assertEqual([e['kind'] for e in phone_events],['RETIRED','ALERT'])
        self.add('RECOVERY',400,90,'network:traffic:ether4:rx')
        await scheduler.flush_notifications()
        bot.send_message.assert_awaited_once()
        text=bot.send_message.call_args.kwargs['text']
        self.assertNotIn('network:device:phone',text);self.assertNotIn('network:traffic:',text)
        self.assertIn('network:link:ether1',text)
        self.assertTrue(all(status=='suppressed' for (status,) in self.db.db.execute("select status from notifications where payload like '%network:traffic:%'")))

class QuietConfigTests(unittest.TestCase):
    def test_defaults_device_flag_and_bounds(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','ALLOWED_TELEGRAM_ID':'1','CONTINUOUS_ENABLED':'true',
            'NETWORK_CONFIG_FILE':str(Path(__file__).resolve().parents[1]/'network.json')}
        with patch.dict(os.environ,env,clear=True):
            cfg=Settings.load()
            self.assertEqual((cfg.traffic_zero_seconds,cfg.traffic_resume_seconds,cfg.traffic_baseline_alerts),(300,60,False))
            self.assertFalse(cfg.targets['client_iphone']['alert_on_unreachable'])
            self.assertTrue(cfg.targets['host_debian']['alert_on_unreachable'])
        for extra in ({'TRAFFIC_ZERO_SECONDS':'0'},{'TRAFFIC_RESUME_SECONDS':'0'}):
            with patch.dict(os.environ,{**env,**extra},clear=True):
                with self.assertRaises(ValueError):Settings.load()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'network.json';path.write_text(json.dumps({'devices':{'x':{'host':'192.168.1.2','alert_on_unreachable':'false'}}}))
            with patch.dict(os.environ,{**env,'NETWORK_CONFIG_FILE':str(path)},clear=True):
                with self.assertRaises(ValueError):Settings.load()
