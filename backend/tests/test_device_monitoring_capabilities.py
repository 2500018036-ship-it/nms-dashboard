import asyncio
import base64
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.dashboard.credentials import CredentialVault
from app.dashboard.platform import Platform
from app.dashboard import models
from app.monitoring import snmp
from app.monitoring import ssh
from app.monitoring import inventory
from app.services.scheduler import Scheduler
from app.monitoring.device_capabilities import detect, telemetry


class DeviceMonitoringCapabilityTests(unittest.TestCase):
    def test_capabilities_are_only_reported_from_observed_fields(self):
        icmp={'status':'UP','latency_ms':2.5,'method':'ICMP'}
        self.assertEqual(detect(icmp),['network_status','latency'])
        router={'status':'UP','data':{'/system/resource':[{'cpu-load':'9','total-memory':'100','free-memory':'25'}],
            '/interface':[{'name':'ether1','rx-byte':'1000','tx-byte':'500','rx_bits_per_second':4000}],
            '/interface/vlan':[{'name':'v10','vlan-id':'10'}],'/ip/route':[{'dst-address':'0.0.0.0/0'}]}}
        self.assertEqual(detect(router),['network_status','system_information','cpu','memory','interfaces','traffic','bandwidth','vlan','routing'])
        details=telemetry(router)
        self.assertEqual(details['cpu_percent'],9.0)
        self.assertEqual(details['memory_percent'],75.0)
        self.assertEqual(details['interfaces'][0]['rx_bps'],4000)

    def test_monitor_category_schema_and_snmp_scheduling(self):
        value=models.record('inventory',{'name':'Switch','host':'192.168.10.26','type':'switch','vendor':'Cisco','methods':['snmp'],
            'interval':60,'profile':'network','enabled':True,'monitor_method':'snmp','monitor_port':161,
            'monitor_categories':['network_status','system_information','interfaces']},['192.168.10.26'],())
        self.assertEqual(value['monitor_categories'],['network_status','system_information','interfaces'])
        self.assertEqual(value['monitor_port'],161)
        ssh_value=models.record('inventory',{'name':'Linux','host':'192.0.2.10','type':'server','vendor':'Debian','methods':['ssh'],
            'interval':60,'profile':'host','enabled':True,'monitor_method':'ssh'},['192.0.2.10'],())
        self.assertEqual(ssh_value['monitor_port'],22)
        self.assertEqual(ssh_value['monitor_categories'],['network_status','system_information','cpu','memory','storage','interfaces','traffic','bandwidth'])
        with self.assertRaisesRegex(ValueError,'invalid_monitor_categories'):
            models.record('inventory',{'name':'Switch','host':'192.168.10.26','type':'switch','vendor':'Cisco','methods':['snmp'],
                'interval':60,'profile':'network','enabled':True,'monitor_method':'snmp','monitor_categories':['arbitrary_command']},['192.168.10.26'],())

    def test_ssh_method_is_scheduled_and_receives_only_per_device_categories(self):
        value=models.record('inventory',{'name':'Linux','host':'192.0.2.10','type':'server','vendor':'Debian','model':'12',
            'methods':['ssh'],'interval':60,'profile':'host','enabled':True,'monitor_method':'ssh','monitor_port':22,
            'monitor_categories':['cpu','memory']},['192.0.2.10'],())
        value['id']='a'*24
        self.assertTrue(inventory.scheduled(value))
        with patch('app.monitoring.inventory.ssh.probe',new=AsyncMock(return_value={'target':'inventory_'+'a'*24,'status':'UP'})) as probe:
            asyncio.run(inventory.collect(value,['192.0.2.10'],{'ssh':{'username':'nms-ro'}},{'timestamp':'old'}))
        self.assertEqual(probe.await_args.args[4],['cpu','memory'])
        self.assertEqual(probe.await_args.args[5],{'timestamp':'old'})


class SnmpReadOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_snmpv2c_reads_system_and_bounded_if_mib_and_reports_rates_only_when_observed(self):
        class Value:
            def __init__(self,value):self.value=value
            def prettyPrint(self):return str(self.value)
        calls=[]
        async def fake_get(engine,auth,address,context,*varbinds,**kwargs):
            calls.append(len(varbinds))
            if len(calls)==1:
                values=['Cisco switch','1.3.6.1.4.1.9','12345','switch-1','1']
            else:
                values=['GigabitEthernet1','1','1000','10000','20000']
            return None,0,0,[(None,Value(value)) for value in values]
        with patch('pysnmp.hlapi.v3arch.asyncio.UdpTransportTarget.create',new=AsyncMock(return_value=object())), \
                patch('pysnmp.hlapi.v3arch.asyncio.get_cmd',new=fake_get):
            result=await snmp.probe('inventory_test','192.0.2.1',161,{'version':'v2c','community':'read-only-test'},
                ['system_information','interfaces','traffic','bandwidth'])
        self.assertEqual(result['status'],'UP')
        self.assertEqual(result['system_info']['name'],'switch-1')
        self.assertEqual(result['interfaces'][0]['name'],'GigabitEthernet1')
        self.assertNotIn('rx_bps',result['interfaces'][0])
        self.assertEqual(calls,[5,5])

    async def test_bandwidth_requires_two_real_counter_samples_and_uses_elapsed_time(self):
        class Value:
            def __init__(self,value):self.value=value
            def prettyPrint(self):return str(self.value)
        calls=0
        async def fake_get(engine,auth,address,context,*varbinds,**kwargs):
            nonlocal calls
            calls+=1
            values=['RouterOS','1.3.6.1.4.1.14988','10000','router-1','1'] if calls==1 else ['ether1','1','1000','10000','20000']
            return None,0,0,[(None,Value(value)) for value in values]
        previous={'timestamp':(datetime.now(timezone.utc)-timedelta(seconds=10)).isoformat(),
            'interfaces':[{'index':1,'rx_bytes':5000,'tx_bytes':6000}]}
        with patch('pysnmp.hlapi.v3arch.asyncio.UdpTransportTarget.create',new=AsyncMock(return_value=object())), \
                patch('pysnmp.hlapi.v3arch.asyncio.get_cmd',new=fake_get):
            result=await snmp.probe('inventory_test','192.0.2.1',161,{'version':'v2c','community':'read-only-test'},
                ['interfaces','traffic','bandwidth'],previous)
        interface=result['interfaces'][0]
        self.assertGreater(interface['rx_bps'],0)
        self.assertGreater(interface['tx_bps'],0)
        self.assertGreaterEqual(interface['sample_seconds'],9)
        self.assertIn('bandwidth',detect(result))

    async def test_missing_snmp_secrets_return_explicit_state_without_network_request(self):
        with patch('pysnmp.hlapi.v3arch.asyncio.get_cmd') as get:
            result=await snmp.probe('inventory_test','192.0.2.1',161,{},['network_status'])
        self.assertEqual(result['error'],'missing_snmp_credentials')
        get.assert_not_called()


class SshReadOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def test_ssh_uses_pinned_host_key_and_fixed_commands_only(self):
        import asyncssh
        public_key=asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode().split()
        output='NMS_CPU\ncpu 100 0 50 800 20 0 0 0 0 0\n'
        class Reply:
            exit_status=0
            stdout=output
        class Connection:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):return None
            async def run(self,command,**kwargs):
                self.command=command
                return Reply()
        connection=Connection()
        with patch('asyncssh.connect',return_value=connection) as connect:
            result=await ssh.probe('inventory_test','192.0.2.1',22,{'username':'nms-ro','password':'secret',
                'host_key_type':public_key[0],'host_key_data':public_key[1]},['cpu','shell_injection; touch /tmp/pwned'])
        self.assertEqual(result['status'],'UP')
        self.assertEqual(result['cpu_counters'],{'total':970,'idle':820})
        self.assertIn('NMS_CPU',connection.command)
        self.assertNotIn('shell_injection',connection.command)
        self.assertEqual(connect.call_args.kwargs['known_hosts'].__class__.__name__,'SSHKnownHosts')
        self.assertEqual(connect.call_args.kwargs['client_keys'],[])
        self.assertIsNone(connect.call_args.kwargs['agent_path'])
        self.assertIsNone(connect.call_args.kwargs['config'])
        self.assertFalse(connect.call_args.kwargs['request_pty'])

    async def test_ssh_cpu_rate_requires_two_real_samples_and_linux_metadata_is_detected(self):
        output='NMS_UNAME\nLinux host 6.1 x86_64 GNU/Linux\nNMS_UPTIME\n12345.00 222.0\nNMS_CPU\ncpu 200 0 100 1600 40 0 0 0 0 0\nNMS_MEM\nMemTotal:       1000 kB\nMemAvailable:    250 kB\nNMS_DF\nFilesystem 1B-blocks Used Available Use% Mounted on\n/dev/sda1 10000 4000 6000 40% /\nNMS_NET\nInter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n eth0: 2000 0 0 0 0 0 0 0 3000 0 0 0 0 0 0 0\n'
        previous={'cpu_counters':{'total':970,'idle':820},'sample_epoch':__import__('time').time()-10,
            'interfaces':[{'name':'eth0','rx_bytes':1000,'tx_bytes':2000}]}
        sampled=ssh._read_metrics(output,previous)
        self.assertGreater(sampled['cpu_percent'],0)
        self.assertGreater(sampled['interfaces'][0]['rx_bps'],0)
        self.assertEqual(sampled['memory_percent'],75.0)
        self.assertEqual(sampled['disks'][0]['path'],'/')
        self.assertIn('cpu',detect(sampled))
        self.assertIn('bandwidth',detect(sampled))

    async def test_ssh_refuses_windows_and_unpinned_hosts_before_connecting(self):
        with patch('asyncssh.connect') as connect:
            windows=await ssh.probe('inventory_test','192.0.2.1',22,{},['cpu'],vendor='Microsoft',model='Windows Server')
            missing=await ssh.probe('inventory_test','192.0.2.1',22,{'username':'nms-ro','password':'secret'},['cpu'])
        self.assertEqual(windows['error'],'ssh_unsupported_os')
        self.assertEqual(missing['error'],'missing_ssh_credentials')
        connect.assert_not_called()

    async def test_inventory_worker_uses_direct_device_interval_without_polling_shared_targets(self):
        class StopLoop(Exception):pass
        direct={'enabled':True,'monitor_method':'ssh','interval':15,'id':'a'*24}
        shared={'enabled':True,'monitor_method':'routeros','interval':30,'id':'b'*24}
        class Platform:
            def list(self,collection):return [direct,shared]
            def inventory_target(self,item):return 'inventory_'+item['id'] if item is direct else 'mikrotik_system'
        monitor=type('Monitor',(),{'platform':Platform(),'check':AsyncMock(return_value={'status':'UP'})})()
        scheduler=Scheduler.__new__(Scheduler);scheduler.platform=monitor.platform;scheduler.monitor=monitor
        scheduler.settings=type('Settings',(),{'poll_interval':60})()
        with patch('app.services.scheduler.asyncio.sleep',new=AsyncMock(side_effect=StopLoop)) as sleep:
            with self.assertRaises(StopLoop):await scheduler.inventory_polling()
        monitor.check.assert_awaited_once_with('inventory_'+'a'*24)
        self.assertGreaterEqual(sleep.await_args.args[0],14.9)
        self.assertLessEqual(sleep.await_args.args[0],15)


class CredentialVaultSnmpTests(unittest.TestCase):
    def test_snmp_secrets_are_validated_encrypted_and_read_only_available_to_collector(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'NMS_CREDENTIALS_KEY':base64.urlsafe_b64encode(b'K'*32).decode().rstrip('=')}):
            store=Platform(directory);vault=CredentialVault(store);identity='inv_'+'a'*24
            record={'gui':{'username':'','password':'','fields':[]},'wifi_networks':[],'custom_fields':[],
                'snmp':{'version':'v3','community':'','username':'nms-ro','auth_protocol':'sha','auth_secret':'auth-secret-123',
                    'privacy_protocol':'aes128','privacy_secret':'privacy-secret-456'}}
            vault.save('inventory',identity,record,'admin')
            loaded=vault.collector_credentials('inventory',identity)
            self.assertEqual(loaded['snmp']['username'],'nms-ro')
            with store.db() as db:
                ciphertext=db.execute('SELECT ciphertext FROM credential_records WHERE target_type=? AND target_id=?',('inventory',identity)).fetchone()[0]
            self.assertNotIn(b'auth-secret-123',ciphertext)
            self.assertNotIn(b'privacy-secret-456',ciphertext)
            record['snmp']['community']='public'
            with self.assertRaisesRegex(ValueError,'invalid_credentials'):vault.validate(record)

    def test_ssh_credentials_are_encrypted_and_host_key_is_validated(self):
        import asyncssh
        public_key=asyncssh.generate_private_key('ssh-ed25519').export_public_key().decode().split()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ,{'NMS_CREDENTIALS_KEY':base64.urlsafe_b64encode(b'K'*32).decode().rstrip('=')}):
            store=Platform(directory);vault=CredentialVault(store);identity='inv_'+'b'*24
            record={'gui':{'username':'','password':'','fields':[]},'wifi_networks':[],'custom_fields':[],
                'ssh':{'username':'nms-ro','password':'ssh-secret-123','host_key_type':public_key[0],'host_key_data':public_key[1]}}
            vault.save('inventory',identity,record,'admin')
            self.assertEqual(vault.collector_credentials('inventory',identity)['ssh']['username'],'nms-ro')
            with store.db() as db:
                ciphertext=db.execute('SELECT ciphertext FROM credential_records WHERE target_type=? AND target_id=?',('inventory',identity)).fetchone()[0]
            self.assertNotIn(b'ssh-secret-123',ciphertext)
            record['ssh']['host_key_data']='not a public key!!!!'
            with self.assertRaisesRegex(ValueError,'invalid_credentials'):vault.validate(record)


if __name__=='__main__':
    unittest.main()
