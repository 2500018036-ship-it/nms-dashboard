import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,Mock,patch
from telegram.error import TimedOut,RetryAfter
from app.config import Settings
from app.storage.database import Database
from app.alerts.engine import Alerts
from app.alerts.network import NetworkEvents,duration
from app.alerts.outbox import Outbox
from app.services.scheduler import Scheduler
from app.services.network import NetworkService
from app.services.health import Monitoring
from app.monitoring.interface_events import InterfaceEvents
from app.monitoring import icmp
from app.ai.agent import needs_current_data

def settings(**kw):return Settings('t',frozenset({1}),'k',('m',),**kw)
def interface(running='true',counter=1000,downs=0,name='ether2'):
    return {'id':'*2','name':name,'type':'ether','running':running,'disabled':'false','rx-byte':str(counter),'tx-byte':str(counter),'link-downs':str(downs)}

class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(self.temp.name)
        self.cfg=settings(continuous_enabled=True,traffic_baseline_alerts=True);self.engine=NetworkEvents(self.cfg,self.db)
    def tearDown(self):self.db.close();self.temp.cleanup()

    def test_baseline_down_is_quiet_and_plug_unplug_recovery_is_durable(self):
        self.engine.interfaces([interface('false')],100)
        self.assertEqual(self.db.events(),[])
        self.engine.interfaces([interface()],115)
        self.engine.interfaces([interface('false')],130)
        self.engine.interfaces([interface()],145)
        self.assertEqual([e['kind'] for e in reversed(self.db.events())],['CHANGE','ALERT','RECOVERY'])
        again=NetworkEvents(self.cfg,self.db);again.interfaces([interface()],160)
        self.assertEqual(len(self.db.events()),3)

    def test_native_event_and_older_poll_do_not_create_false_recovery(self):
        self.engine.interfaces([interface()],100)
        self.engine.link(interface('false'),110,'RouterOS /interface/listen')
        self.engine.interfaces([interface()],105)
        self.assertEqual(self.db.states()['network:link:ether2']['current'],'DOWN')
        self.assertEqual(len(self.db.events()),1)

    def test_rate_uses_actual_elapsed_and_counter_reset_is_unknown(self):
        self.engine.interfaces([interface(counter=100)],100)
        rates=self.engine.interfaces([interface(counter=1100)],110)
        self.assertEqual(rates[0]['rx_bps'],800)
        rates=self.engine.interfaces([interface(counter=10)],120)
        self.assertIsNone(rates[0]['rx_bps'])

    def test_wireguard_counter_rate_is_not_a_physical_link_claim(self):
        row={**interface(name='wg-azure',counter=100),'type':'wg'}
        self.engine.interfaces([row],100)
        rates=self.engine.interfaces([{**row,'rx-byte':'1100'}],110)
        self.assertEqual(rates[0]['rx_bps'],800)
        self.assertNotIn('network:link:wg-azure',self.db.states())
        rates=self.engine.interfaces([interface(counter=1000)],500)
        self.assertIsNone(rates[0]['rx_bps'])

    def test_brief_drop_between_polls_uses_link_down_counter(self):
        self.engine.interfaces([interface()],100)
        self.engine.interfaces([interface(counter=1200,downs=1)],115)
        self.assertEqual(self.db.events()[0]['value']['link_downs_delta'],1)
        self.engine.interfaces([interface(counter=1400,downs=1)],130)
        self.assertEqual(len(self.db.events()),1)

    def test_spike_dedup_hysteresis_and_recovery(self):
        for n in range(0,75,15):self.engine.traffic('ether1','rx',200000,n)
        for n in range(75,135,15):self.engine.traffic('ether1','rx',2000000,n)
        self.assertEqual(self.db.events(),[])  # Not sustained for 60 seconds yet.
        self.engine.traffic('ether1','rx',2000000,135)
        self.assertEqual(len(self.db.events()),1)
        self.assertEqual(self.db.events()[0]['kind'],'ALERT')
        for n in range(150,195,15):self.engine.traffic('ether1','rx',500000,n)
        self.assertEqual(len(self.db.events()),1)  # Above recovery hysteresis (1.5x).
        self.engine.traffic('ether1','rx',200000,195);self.engine.traffic('ether1','rx',200000,210)
        self.assertEqual(self.db.events()[0]['kind'],'RECOVERY')

    def test_spike_strictly_over_two_times_baseline_and_survives_restart(self):
        for n in range(0,75,15):self.engine.traffic('ether1','rx',2000000,n)
        for n in range(75,150,15):self.engine.traffic('ether1','rx',4000000,n)
        self.assertEqual(self.db.events(),[])
        # Fresh warm baseline, then a 2.5x spike; restart retains the timer.
        self.db.set_state('network:traffic:ether1:rx',{'points':[2000000]*5,'active':False,'current':'normal'})
        for n in (150,165,180):self.engine.traffic('ether1','rx',5000000,n)
        NetworkEvents(self.cfg,self.db).traffic('ether1','rx',5000000,195)
        self.assertEqual(self.db.events(),[])
        self.engine.traffic('ether1','rx',5000000,210)
        self.assertEqual(self.db.events()[0]['value']['sustained_seconds'],60)

    def test_missing_spike_sample_restarts_confirmation(self):
        for n in range(0,75,15):self.engine.traffic('ether1','rx',2000000,n)
        for n in (75,90,105):self.engine.traffic('ether1','rx',5000000,n)
        self.engine.traffic('ether1','rx',None,120)
        self.engine.traffic('ether1','rx',5000000,135)
        self.assertEqual(self.db.events(),[])

    def test_bandwidth_sustained_warning_critical_hysteresis_and_recovery(self):
        def observe(percent,now,engine=None):
            (engine or self.engine).bandwidth('ether3',{'utilization_percent':percent,'capacity_bps':100000000,
                'rx_percent':percent,'tx_percent':1,'duplex':'full'},now)
        observe(85,0);observe(85,15);observe(85,30)
        self.assertEqual(self.db.events(),[])
        observe(86,45);observe(89,60)
        self.assertEqual(self.db.events(),[])
        observe(89,75,NetworkEvents(self.cfg,self.db))
        self.assertEqual(self.db.events()[0]['severity'],'WARNING')
        observe(96,90);observe(99,105);observe(98,120)
        self.assertEqual(self.db.events()[0]['severity'],'CRITICAL')
        for n in (135,150,165):observe(92,n)
        self.assertEqual(len(self.db.events()),2)  # Retain critical until <=90.
        observe(None,180);observe(70,195);observe(70,210)
        self.assertEqual(len(self.db.events()),2)
        observe(70,225)
        self.assertEqual(self.db.events()[0]['kind'],'RECOVERY')
        self.assertEqual(self.db.events()[0]['first_seen'],45)

    def test_bandwidth_missing_capacity_and_counter_reset_never_become_zero(self):
        first={**interface(counter=0),'capacity_bps':100000000,'capacity_age_seconds':0,'link_monitor':{'full-duplex':'true'}}
        self.engine.interfaces([first],100)
        rates=self.engine.interfaces([{**first,'rx-byte':'112500000','tx-byte':'112500000'}],115)
        self.assertEqual(rates[0]['utilization_percent'],60)  # Full duplex, not RX+TX=120%.
        self.assertEqual(rates[0]['rx_percent'],60)
        rates=self.engine.interfaces([{**first,'capacity_bps':None,'rx-byte':'225000000','tx-byte':'225000000'}],130)
        self.assertIsNone(rates[0]['utilization_percent'])
        rates=self.engine.interfaces([{**first,'rx-byte':'1'}],145)
        self.assertIsNone(rates[0]['utilization_percent'])

    def test_bandwidth_half_duplex_and_long_sample_gap(self):
        first={**interface(counter=0),'capacity_bps':100000000,'capacity_age_seconds':0,'link_monitor':{'full-duplex':'false'}}
        self.engine.interfaces([first],100)
        rates=self.engine.interfaces([{**first,'rx-byte':'37500000','tx-byte':'37500000'}],115)
        self.assertEqual(rates[0]['utilization_percent'],40)
        for now in (130,145):self.engine.bandwidth('ether2',{'utilization_percent':99},now)
        self.engine.bandwidth('ether2',{'utilization_percent':99},205)
        self.assertEqual(self.db.events(),[])  # Gap breaks sustained timer.

    def test_failed_collector_breaks_sustain_without_false_recovery(self):
        for now in (100,115):self.engine.bandwidth('ether3',{'utilization_percent':99},now)
        self.engine.missing_sample()
        self.engine.bandwidth('ether3',{'utilization_percent':99},130)
        self.assertEqual(self.db.events(),[])
        for now in (145,160):self.engine.bandwidth('ether3',{'utilization_percent':99},now)
        self.assertTrue(self.db.states()['network:bandwidth:ether3']['active'])
        self.engine.missing_sample()
        self.assertTrue(self.db.states()['network:bandwidth:ether3']['active'])
        self.assertEqual(len(self.db.events()),1)

    def test_idle_baseline_is_not_anomaly_and_missing_is_not_zero(self):
        for n in range(6):self.engine.traffic('ether2','rx',0,n)
        for n in range(6,10):self.engine.traffic('ether2','rx',10000000,n)
        self.assertEqual(self.db.events(),[])
        self.engine.traffic('ether2','rx',None,20)
        self.assertEqual(self.db.events(),[])

    def test_drop_requires_two_samples(self):
        for n in range(5):self.engine.traffic('ether1','tx',2000000,n)
        self.engine.traffic('ether1','tx',0,5);self.assertEqual(self.db.events(),[])
        self.engine.traffic('ether1','tx',0,6)
        self.assertEqual(self.db.events()[0]['title'],'Penurunan trafik')

    def test_routes_sorted_and_partial_results_do_not_signal_deletion(self):
        rows=[{'dst-address':'0.0.0.0/0','gateway':'192.0.2.1'},{'dst-address':'10.0.0.0/24','gateway':'wg1'}]
        def value(rows):return {'status':'UP','data':{'/ip/route':rows},'resources':{'/ip/route':{'has_more':False}}}
        self.engine.routes(value(rows),100);self.engine.routes(value(list(reversed(rows))),110)
        self.assertEqual(self.db.events(),[])
        self.engine.routes({'status':'UNKNOWN'},120)
        partial=value([]);partial['resources']['/ip/route']['has_more']=True;self.engine.routes(partial,130)
        self.assertEqual(self.db.events(),[])
        self.engine.routes(value([rows[1]]),140);self.assertEqual(len(self.db.events()),1)

    def test_wireguard_uses_handshake_not_interface_running(self):
        def peer(age,keepalive='25s'):return {'status':'UP','peers':[{'id':'*1','name':'peer1','interface':'wg-azure','disabled':'false','handshake_age_seconds':age,'persistent-keepalive':keepalive}]}
        self.engine.wireguard(peer(5),100)
        self.engine.wireguard(peer(300),200);self.engine.wireguard(peer(360),260)
        self.assertEqual(self.db.events()[0]['kind'],'ALERT')
        self.engine.wireguard(peer(None),270);self.assertEqual(len(self.db.events()),1)
        self.engine.wireguard(peer(5),300);self.engine.wireguard(peer(6),360)
        self.assertEqual(self.db.events()[0]['kind'],'RECOVERY')
        self.engine.wireguard(peer(1000,'0s'),400);self.assertEqual(len(self.db.events()),2)

    def test_time_is_wib_regardless_host_timezone(self):
        event=self.engine.emit('test','ALERT','Simulasi','Perangkat uji',{},0)
        text=Alerts.text(event)
        self.assertIn('01/01/1970 07:00:00 WIB',text)
        self.assertIn('Keparahan: WARNING',text)
        self.assertIn('BELUM PULIH',text)

    def test_incident_component_includes_interface_and_traffic(self):
        self.engine.interfaces([interface()],100);self.engine.interfaces([interface('false')],115)
        values=self.db.events(component='mikrotik')
        self.assertEqual(len(values),1);self.assertIn('network:link:',values[0]['key'])

    def test_removed_container_retires_incident_without_fake_recovery(self):
        self.db.set_state('container:old',{'active':True})
        alerts=Alerts(self.cfg,self.db)
        alerts.evaluate([{'target':'docker','method':'collector','status':'UP','containers':[],'scan_truncated':True}])
        self.assertTrue(self.db.states()['container:old']['active'])
        alerts.evaluate([{'target':'docker','method':'collector','status':'UP','containers':[],'scan_truncated':False}])
        self.assertFalse(self.db.states()['container:old']['active'])
        self.assertEqual(self.db.events()[0]['kind'],'RETIRED')

    def test_duration_parser(self):
        self.assertEqual(duration('1w2d3h4m5s'),788645)
        self.assertEqual(duration('250ms'),.25)
        self.assertIsNone(duration('never'));self.assertIsNone(duration('invalid'))

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Database(self.temp.name)
        self.cfg=settings(alerts=True,alert_chat_id=1);self.queue=Outbox(self.db)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def add(self,kind='ALERT',now=100):
        self.db.event('x',kind,{'key':'x','kind':kind,'time':now,'first_seen':100,'value':{}})

    def test_down_and_recovery_are_both_queued_even_during_cooldown(self):
        self.add();self.add('RECOVERY',110);self.queue.stage();self.queue.stage()
        self.assertEqual(len(self.queue.pending()),2)
        again=Outbox(self.db);self.assertEqual(len(again.pending()),2)

    def test_cooldown_persists_and_other_device_escalation_recovery_bypass_it(self):
        self.add(now=100);self.queue.stage()
        self.add(now=110);Outbox(self.db).stage()
        self.assertEqual(dict(self.db.db.execute('select status,count(*) from notifications group by status')),{'pending':1,'suppressed':1})
        self.db.event('y','ALERT',{'key':'y','kind':'ALERT','time':115,'value':{}})
        self.db.event('x','ALERT',{'key':'x','kind':'ALERT','time':120,'severity':'CRITICAL','value':{}})
        self.add('RECOVERY',130);self.add(now=140)
        self.queue.stage()
        self.assertEqual(len(self.queue.pending()),5)
        self.add(now=739);self.queue.stage()
        self.assertEqual(self.db.db.execute("select count(*) from notifications where status='suppressed'").fetchone()[0],2)
        self.add(now=740);self.queue.stage()
        self.assertEqual(len(self.queue.pending()),6)

    def test_different_routing_change_is_not_suppressed_by_cooldown(self):
        for now,address in ((100,'192.0.2.1'),(110,'192.0.2.2'),(120,'192.0.2.2')):
            self.db.event('route','CHANGE',{'key':'route','kind':'CHANGE','time':now,'value':{'gateway':address}})
        self.queue.stage()
        self.assertEqual(len(self.queue.pending()),2)

    def test_failures_are_bounded_and_timeout_is_not_retried(self):
        self.add();self.queue.stage();identity=self.queue.pending()[0][0]
        for _ in range(5):self.queue.mark([identity],'retry','NetworkError')
        self.assertEqual(self.queue.pending(now=1e12),[])
        self.assertEqual(self.db.db.execute('select status from notifications').fetchone()[0],'failed')
        self.add('RECOVERY',200);self.queue.stage();identity=self.queue.pending()[0][0]
        self.queue.mark([identity],'uncertain','TimedOut');self.assertEqual(self.queue.pending(now=1e12),[])

    async def test_notifier_has_no_ai_dependency_and_records_ambiguous_send(self):
        bot=NS(send_message=AsyncMock(side_effect=TimedOut()))
        scheduler=Scheduler(self.cfg,self.db,None,bot)
        self.add();await scheduler.flush_notifications()
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(self.db.db.execute('select status from notifications').fetchone()[0],'uncertain')
        await scheduler.flush_notifications();self.assertEqual(bot.send_message.await_count,1)

    async def test_successful_notification_once_with_recovery(self):
        bot=NS(send_message=AsyncMock())
        scheduler=Scheduler(self.cfg,self.db,None,bot)
        self.add();self.add('RECOVERY',110)
        await scheduler.flush_notifications();await scheduler.flush_notifications()
        self.assertEqual(bot.send_message.await_count,1)
        self.assertEqual(self.db.db.execute("select count(*) from notifications where status='sent'").fetchone()[0],2)

    async def test_telegram_retry_after_is_respected(self):
        scheduler=Scheduler(self.cfg,self.db,None,NS(send_message=AsyncMock(side_effect=RetryAfter(600))))
        self.add();await scheduler.flush_notifications()
        self.assertEqual(self.queue.pending(now=__import__('time').time()+300),[])
        self.assertEqual(len(self.queue.pending(now=__import__('time').time()+1000)),1)

    def test_pending_legacy_notification_is_migrated(self):
        self.db.db.execute("DELETE FROM metadata WHERE key='notification_cursor'");self.db.db.commit()
        alerts=Alerts(self.cfg,self.db);alerts.observe('x',True,{},now=100);alerts.observe('x',True,{},now=110)
        migrated=Outbox(self.db);migrated.stage()
        self.assertEqual(len(migrated.pending()),1)

    def test_notifications_disabled_does_not_send_old_backlog_when_enabled(self):
        self.add();self.queue.stage(False);self.queue.stage(True);self.assertEqual(self.queue.pending(),[])

    def test_retention_does_not_reset_event_ids_or_lose_future_notifications(self):
        self.add();self.queue.stage()
        first=self.queue.pending()[0][0]
        self.db.db.execute('DELETE FROM events');self.db.db.commit()
        self.add('RECOVERY',200);self.queue.stage()
        identities=[identity for identity,event in self.queue.pending()]
        self.assertEqual(identities,[first,first+1])

class ICMPTests(unittest.IsolatedAsyncioTestCase):
    async def test_unprivileged_icmp_and_matching_payload(self):
        fake=Mock();sent=[]
        async def send(sock,packet):sent.append(packet)
        async def receive(sock,n):return b'\0\0'+sent[0][2:]
        loop=NS(sock_sendall=send,sock_recv=receive)
        with patch('app.monitoring.icmp.socket.socket',return_value=fake) as create,patch('app.monitoring.icmp.asyncio.get_running_loop',return_value=loop):
            value=await icmp.probe('device','192.168.20.1')
        self.assertEqual(value['status'],'UP');self.assertEqual(create.call_args.args[1],__import__('socket').SOCK_DGRAM)
        fake.close.assert_called_once()

    async def test_permission_failure_is_unknown_not_host_down(self):
        with patch('app.monitoring.icmp.socket.socket',side_effect=PermissionError()):value=await icmp.probe('x','192.168.20.1')
        self.assertEqual(value['status'],'UNKNOWN')

class EventStreamTests(unittest.TestCase):
    def test_elevated_credential_opt_in_keeps_stream_read_only(self):
        pool=Mock();requests=[]
        watcher=InterfaceEvents(settings(mikrotik_readonly=True),lambda row,now:watcher.stopping.set())
        def resource(path):
            def call(cmd,args,query=None):
                requests.append((path,cmd));return [{'group':'nms'}] if path=='/user' else [{'policy':'read,api,write,policy,sensitive'}]
            def stream(cmd,args):
                requests.append((path,cmd));return iter([{'name':'ether1','running':'true'}])
            return NS(call=call,call_async=stream)
        pool.get_api.return_value.get_resource.side_effect=resource
        env={'MIKROTIK_USER':'dummy','MIKROTIK_PASSWORD':'dummy','MIKROTIK_PORT':'8728','MIKROTIK_ALLOW_PLAINTEXT':'true','MIKROTIK_MONITOR_ALLOW_ELEVATED':'true'}
        with patch.dict(os.environ,env),patch('routeros_api.RouterOsApiPool',return_value=pool),patch('app.monitoring.interface_events.threading.Timer'):watcher._run()
        self.assertEqual(requests,[('/user','print'),('/user/group','print'),('/interface','listen')])

    def test_stream_only_prints_permissions_and_listens_to_fixed_fields(self):
        pool=Mock();requests=[]
        received=[]
        def callback(row,now):received.append(row);watcher.stopping.set()
        watcher=InterfaceEvents(settings(mikrotik_readonly=True),callback)
        def resource(path):
            def call(cmd,args,query=None):
                requests.append((path,cmd))
                return [{'group':'nms'}] if path=='/user' else [{'policy':'read,api,winbox'}]
            def stream(cmd,args):
                requests.append((path,cmd));self.assertNotIn('private-key',args['.proplist'])
                return iter([{'name':'ether2','running':'false','private-key':'never-export'}])
            return NS(call=call,call_async=stream)
        pool.get_api.return_value.get_resource.side_effect=resource
        env={'MIKROTIK_USER':'dummy','MIKROTIK_PASSWORD':'dummy','MIKROTIK_PORT':'8728','MIKROTIK_ALLOW_PLAINTEXT':'true'}
        with patch.dict(os.environ,env),patch('routeros_api.RouterOsApiPool',return_value=pool),patch('app.monitoring.interface_events.threading.Timer'):
            watcher._run()
        self.assertEqual(requests,[('/user','print'),('/user/group','print'),('/interface','listen')])
        self.assertNotIn('private-key',received[0])

class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_overview_keeps_every_target_and_stays_within_tool_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory);monitor=Monitoring(settings(continuous_enabled=True),db)
            containers=[{'name':'container-'+str(i)+'x'*100,'state':'running','health':'healthy','cpu_percent':1,'memory_bytes':1000,
                'restart_count':0,'image':'x'*1000,'raw_secret':'must-not-export'} for i in range(100)]
            rows=[{'target':'docker','status':'UP','method':'snapshot','containers':containers}]
            rows.extend({'target':'device-'+str(i),'status':'UNKNOWN' if i==0 else 'UP','method':'ICMP','error':'icmp_not_permitted' if i==0 else None} for i in range(24))
            monitor.all=AsyncMock(return_value={'results':rows,'counts':{'UP':24,'UNKNOWN':1}})
            value=await monitor.overview()
            encoded=json.dumps(value,ensure_ascii=False)
            self.assertLess(len(encoded),20000)
            self.assertEqual([r['target'] for r in value['results']],[r['target'] for r in rows])
            self.assertEqual(value['results'][1]['status'],'UNKNOWN')
            self.assertEqual(value['results'][0]['containers_available'],100)
            self.assertTrue(value['summary_only']);self.assertNotIn('must-not-export',encoded)
            db.close()

    async def test_partial_event_uses_interface_id_and_deduplicates_repeated_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory);cfg=settings(continuous_enabled=True)
            monitor=NS(cache={})
            scheduler=Scheduler(cfg,db,monitor,None)
            service=NetworkService(cfg,db,monitor,scheduler)
            service.rows={'ether2':interface()}
            service.events.interfaces([interface()],100)
            await service.event_once({'id':'*2','running':'false'},110)
            await service.event_once({'id':'*2','running':'false'},111)
            self.assertEqual(len(db.events()),1)
            self.assertEqual(db.events()[0]['value']['source'],'RouterOS /interface/listen')
            db.close()

class NetworkConfigTests(unittest.TestCase):
    def test_incident_explanation_requires_evidence_but_definition_does_not(self):
        self.assertTrue(needs_current_data('Jelaskan kejadian terakhir'))
        self.assertTrue(needs_current_data('Jelaskan riwayat gangguan'))
        self.assertFalse(needs_current_data('Apa itu notifikasi monitoring?'))
    def test_ai_key_is_optional_for_observational_bot(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','ALLOWED_TELEGRAM_ID':'1'}
        with patch.dict(os.environ,env,clear=True):self.assertEqual(Settings.load().api_key,'')
    def test_inventory_rejects_ssrf_and_public_addresses(self):
        env={'TELEGRAM_BOT_TOKEN':'dummy','OPENROUTER_API_KEY':'dummy','ALLOWED_TELEGRAM_ID':'1','CONTINUOUS_ENABLED':'true'}
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'network.json'
            for address in ('169.254.169.254','127.0.0.1','8.8.8.8','http://192.168.1.1','0.0.0.0','240.0.0.1'):
                path.write_text(json.dumps({'devices':{'device':{'host':address}}}))
                with patch.dict(os.environ,{**env,'NETWORK_CONFIG_FILE':str(path)},clear=True):
                    with self.assertRaises(ValueError):Settings.load()
            path.write_text(json.dumps({'devices':{'device':{'host':'192.168.30.194'}}}))
            with patch.dict(os.environ,{**env,'NETWORK_CONFIG_FILE':str(path)},clear=True):
                self.assertEqual(Settings.load().targets['device']['kind'],'icmp')
