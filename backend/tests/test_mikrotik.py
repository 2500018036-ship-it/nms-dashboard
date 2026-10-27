import asyncio
import json
import os
import ssl
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from app.config import Settings
from app.monitoring.mikrotik import MikroTik, error_category, MAX_ROWS, LOGIN_TIMEOUT, READ_TIMEOUT
from app.monitoring.mikrotik_catalog import SECTIONS
from app.telegram.mikrotik import parse_args, render, help_text
from app.telegram.formatting import format_messages
from app.telegram.handlers import Handlers
from app.services.health import Monitoring
from app.storage.database import Database
from app.ai.tool_registry import Registry
from app.ai.agent import needs_current_data

ENV={'MIKROTIK_USER':'monitor','MIKROTIK_PASSWORD':'dummy','MIKROTIK_PORT':'8728',
    'MIKROTIK_ALLOW_PLAINTEXT':'true','MIKROTIK_NETWORK_DETAILS_ENABLED':'true'}

class RouterFixture:
    def __init__(self, rows=None, policy='read,api', failures=None):
        self.rows=rows or {}
        self.failures=failures or {}
        self.policy=policy
        self.requests=[]
        self.consumed=0
        self.pool=Mock()
        self.pool.get_api.return_value.get_resource.side_effect=self.resource

    def resource(self,path):
        def call(command,args,query=None):
            self.requests.append((path,command,args,query))
            assert command=='print'
            if path=='/user':return [{'name':'monitor','group':'nms'}]
            if path=='/user/group':return [{'name':'nms','policy':self.policy}]
            raise AssertionError('data must use streaming API')
        def call_async(command,args,query=None):
            self.requests.append((path,command,args,query))
            assert command=='print'
            if path in self.failures:raise self.failures[path]
            rows=self.rows.get(path,[])
            if callable(rows):rows=rows()
            def stream():
                for row in rows:
                    self.consumed+=1
                    if not query or all(str(row.get(k))==v for k,v in query.items()):yield row
            return stream()
        return NS(call=call,call_async=call_async)

def router(**kwargs):
    return MikroTik(Settings('token',frozenset({1}),'key',('model',),mikrotik_readonly=True,**kwargs))

class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_permission_cache_expires_and_does_not_allow_device_writes(self):
        fx=RouterFixture({'/system/resource':[{'cpu-load':'1'}],'/interface':[{'name':'ether1','running':'true'}]});obj=router()
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool):
            await obj.collect('system',fresh=True);await obj.collect('interfaces',fresh=True)
            self.assertEqual(sum(path=='/user/group' for path,_,_,_ in fx.requests),1)
            key,at,grants=obj.policy_cache;obj.policy_cache=(key,at-61,grants)
            await obj.collect('system',fresh=True)
            self.assertEqual(sum(path=='/user/group' for path,_,_,_ in fx.requests),2)
        self.assertTrue(all(command=='print' for _,command,_,_ in fx.requests))

    async def test_explicit_elevated_read_adapter_still_only_uses_print(self):
        fx=RouterFixture({'/system/resource':[{'cpu-load':'1'}]},policy='read,api,write,policy,reboot,password,sensitive')
        with patch.dict(os.environ,{'MIKROTIK_MONITOR_ALLOW_ELEVATED':'true'}):value=await self.query(fx)
        self.assertEqual(value['status'],'UP');self.assertEqual(value['credential_privilege'],'elevated-read-adapter')
        self.assertTrue(all(command=='print' for _,command,_,_ in fx.requests))

    async def query(self, fixture, section='system', **kwargs):
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fixture.pool):
            return await router().query(section,**kwargs)

    async def test_each_catalog_section_is_whitelisted_print_only(self):
        for section,spec in SECTIONS.items():
            with self.subTest(section=section):
                fields={key:'1' for key in spec.fields.split(',')}
                fields.update(name='ether1',password='hidden',secret='hidden',**{'private-key':'hidden'})
                fx=RouterFixture({spec.path:[fields]})
                with patch('app.monitoring.mikrotik.time.sleep'):
                    value=await self.query(fx,section)
                self.assertEqual(value['status'],'UP')
                self.assertNotIn('hidden',json.dumps(value))
                for path,cmd,args,query in fx.requests:
                    self.assertEqual(cmd,'print')
                    self.assertIn('.proplist',args)
                    self.assertTrue(set(args)<={'.proplist','stats'})
                fx.pool.disconnect.assert_called_once()

    async def test_cache_pagination_and_exact_filter(self):
        fx=RouterFixture({'/ip/dhcp-server/lease':[{'address':f'192.0.2.{i}','status':'bound'} for i in range(23)]})
        obj=router()
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool) as connect:
            first=await obj.query('dhcp_leases',filter_field='status',filter_value='bound')
            second=await obj.query('dhcp_leases',offset=10,filter_field='status',filter_value='bound')
            last=await obj.query('dhcp_leases',offset=20,filter_field='status',filter_value='bound')
        self.assertEqual(connect.call_count,1)
        path='/ip/dhcp-server/lease'
        self.assertEqual(first['resources'][path]['next_offset'],10)
        self.assertEqual(second['data'][path][0]['address'],'192.0.2.10')
        self.assertEqual(last['resources'][path]['total'],23)
        self.assertFalse(last['resources'][path]['has_more'])
        self.assertIn({'status':'bound'},[r[3] for r in fx.requests])

    async def test_stream_scan_stops_without_claiming_total(self):
        fx=RouterFixture({'/ip/arp':({'address':f'192.0.2.{i}'} for i in range(10000))})
        value=await self.query(fx,'arp')
        meta=value['resources']['/ip/arp']
        self.assertEqual(fx.consumed,MAX_ROWS+1)
        self.assertIsNone(meta['total'])
        self.assertTrue(meta['scan_truncated'])
        self.assertTrue(meta['has_more'])
        self.assertLess(len(json.dumps(value)),22000)

    async def test_long_fields_and_worst_case_page_are_bounded(self):
        fields={key:'x'*1000 for key in SECTIONS['firewall_nat'].fields.split(',')}
        fx=RouterFixture({'/ip/firewall/nat':[fields]*30})
        value=await self.query(fx,'firewall_nat')
        meta=value['resources']['/ip/firewall/nat']
        self.assertTrue(meta['fields_truncated'])
        self.assertEqual(meta['next_offset'],meta['returned'])
        self.assertLess(len(json.dumps(value)),22000)

    async def test_interface_allowlist_applies(self):
        fx=RouterFixture({'/interface':[{'name':'ether1'},{'name':'ether2'}]})
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool):
            value=await router(mikrotik_interfaces=('ether2',)).query('interfaces')
        self.assertEqual(value['data']['/interface'],[{'name':'ether2'}])

    async def test_rate_units_and_counter_reset(self):
        clock=NS(value=100.)
        calls=iter([[{'name':'ether1','rx-byte':'100','tx-byte':'200'}],
                    [{'name':'ether1','rx-byte':'150','tx-byte':'10'}]])
        fx=RouterFixture({'/interface':lambda:next(calls)})
        fake_time=NS(monotonic=lambda:clock.value,sleep=lambda seconds:setattr(clock,'value',clock.value+seconds))
        with patch('app.monitoring.mikrotik.time',fake_time):
            value=await self.query(fx,'traffic',filter_field='name',filter_value='ether1')
        row=value['data']['/interface'][0]
        self.assertEqual(row['rx_bits_per_second'],400.)
        self.assertIsNone(row['tx_bits_per_second'])
        self.assertEqual(row['sample_seconds'],1.)

    async def test_invalid_filters_and_sections_do_not_connect(self):
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool') as connect:
            for kwargs in [dict(section='/system/reboot'),dict(section='password'),dict(section='dns',filter_field='name',filter_value='x'),
                    dict(section='interfaces',filter_field='name'),dict(section='interfaces',offset=-1),
                    dict(section='interfaces',offset=500),dict(section='interfaces',limit=True),
                    dict(section='interfaces',filter_field='name',filter_value='x\n/reboot')]:
                self.assertEqual((await router().query(**kwargs))['error'],'invalid_arguments')
        connect.assert_not_called()

    async def test_network_details_disabled(self):
        with patch.dict(os.environ,{**ENV,'MIKROTIK_NETWORK_DETAILS_ENABLED':'false'}),patch('routeros_api.RouterOsApiPool') as connect:
            self.assertEqual((await router().query('dhcp_leases'))['error'],'network_details_disabled')
        connect.assert_not_called()

    async def test_transport_gates_and_verified_tls(self):
        for env,error in [({'MIKROTIK_ALLOW_PLAINTEXT':'false'},'plaintext_not_explicitly_allowed'),
                          ({'MIKROTIK_PORT':'8729','MIKROTIK_SSL_VERIFY':'false'},'tls_verification_required')]:
            with patch.dict(os.environ,{**ENV,**env}),patch('routeros_api.RouterOsApiPool') as connect:
                self.assertEqual((await router().query('system'))['error'],error)
            connect.assert_not_called()
        fx=RouterFixture({'/system/resource':[{'cpu-load':'1'}]})
        with patch.dict(os.environ,{**ENV,'MIKROTIK_PORT':'8729','MIKROTIK_SSL_VERIFY':'true'}),patch('routeros_api.RouterOsApiPool',return_value=fx.pool) as connect:
            await router().query('system')
        context=connect.call_args.kwargs['ssl_context']
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)

    async def test_overprivileged_account_rejected_before_data(self):
        for policy in ('read,api,write','read,api,sensitive','read,api,reboot','read,api,password','read,api,policy','read,api,winbox,write','read,api,winbox,sniff','read,api,winbox,ftp','read,api,winbox,ssh','api'):
            fx=RouterFixture(policy=policy)
            value=await self.query(fx)
            self.assertEqual(value['error'],'excessive_or_unverified_permissions')
            self.assertEqual(len(fx.requests),2)

    async def test_existing_readonly_winbox_login_is_not_write_permission(self):
        fx=RouterFixture({'/system/resource':[{'cpu-load':'15'}]},policy='read,winbox,api,!write,!policy,!reboot,!password,!sensitive')
        value=await self.query(fx)
        self.assertEqual(value['status'],'UP')
        self.assertEqual(value['data']['/system/resource'][0]['cpu-load'],'15')
        self.assertTrue(all(req[1]=='print' for req in fx.requests))
        self.assertEqual(fx.pool.socket_timeout,LOGIN_TIMEOUT)
        self.assertTrue(all(0 < call.args[0] <= READ_TIMEOUT for call in fx.pool.set_timeout.call_args_list))

    async def test_slow_login_uses_separate_budget_from_read_commands(self):
        clock=NS(value=100.)
        fx=RouterFixture({'/system/resource':[{'cpu-load':'90'}]})
        api=fx.pool.get_api.return_value
        def login():
            self.assertEqual(fx.pool.socket_timeout,10.)
            clock.value+=6
            return api
        fx.pool.get_api.side_effect=login
        fake_time=NS(monotonic=lambda:clock.value)
        with patch('app.monitoring.mikrotik.time',fake_time):
            value=await self.query(fx)
        self.assertEqual(value['status'],'UP')
        self.assertTrue(all(call.args[0]<=READ_TIMEOUT for call in fx.pool.set_timeout.call_args_list))

    def test_queue_time_reduces_remaining_login_budget(self):
        fx=RouterFixture({'/system/resource':[{'cpu-load':'1'}]})
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool),patch('app.monitoring.mikrotik.time.monotonic',return_value=100.):
            value=router()._collect('system',request_deadline=102.)
        self.assertEqual(value['status'],'UP')
        self.assertEqual(fx.pool.socket_timeout,2.)
        self.assertTrue(all(call.args[0]<=2 for call in fx.pool.set_timeout.call_args_list))

    def test_login_consuming_deadline_does_not_read_account_or_data(self):
        clock=NS(value=100.)
        fx=RouterFixture()
        def login():
            clock.value=103.
            return fx.pool.get_api.return_value
        fx.pool.get_api.side_effect=login
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool),patch('app.monitoring.mikrotik.time.monotonic',side_effect=lambda:clock.value):
            value=router()._collect('system',request_deadline=102.)
        self.assertEqual(value['error'],'timeout')
        self.assertEqual(value['phase'],'account_permissions')
        self.assertFalse(fx.requests)
        fx.pool.disconnect.assert_called_once()

    async def test_login_timeout_identifies_failed_layer(self):
        fx=RouterFixture()
        fx.pool.get_api.side_effect=TimeoutError('dummy-secret')
        value=await self.query(fx)
        self.assertEqual(value['error'],'timeout')
        self.assertEqual(value['phase'],'login')
        self.assertNotIn('dummy-secret',json.dumps(value))
        self.assertEqual(fx.pool.get_api.call_count,2)
        self.assertFalse(fx.requests)

    async def test_login_timeout_retries_once_with_only_remaining_deadline(self):
        clock=NS(value=100.)
        first=RouterFixture();second=RouterFixture({'/system/resource':[{'cpu-load':'50'}]})
        def timeout():
            clock.value+=10
            raise TimeoutError('dummy-secret')
        first.pool.get_api.side_effect=timeout
        fake_time=NS(monotonic=lambda:clock.value,sleep=lambda s:setattr(clock,'value',clock.value+s))
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',side_effect=[first.pool,second.pool]) as create,patch('app.monitoring.mikrotik.time',fake_time):
            value=await router().query('system')
        self.assertEqual(value['status'],'UP')
        self.assertEqual(create.call_count,2)
        self.assertAlmostEqual(second.pool.socket_timeout,4.8)
        self.assertFalse(first.requests)
        first.pool.disconnect.assert_called_once();second.pool.disconnect.assert_called_once()

    async def test_authentication_failure_does_not_retry(self):
        fx=RouterFixture()
        fx.pool.get_api.side_effect=RuntimeError('invalid user name or password dummy-secret')
        value=await self.query(fx)
        self.assertEqual(value['error'],'authentication_failed')
        fx.pool.get_api.assert_called_once();fx.pool.disconnect.assert_called_once()
        self.assertFalse(fx.requests)

    async def test_login_retry_still_rejects_write_permission(self):
        first=RouterFixture();second=RouterFixture(policy='read,api,winbox,write')
        first.pool.get_api.side_effect=TimeoutError('dummy-secret')
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',side_effect=[first.pool,second.pool]),patch('app.monitoring.mikrotik.time.sleep'):
            value=await router().query('system')
        self.assertEqual(value['error'],'excessive_or_unverified_permissions')
        self.assertFalse(first.requests)
        self.assertEqual(len(second.requests),2)
        first.pool.disconnect.assert_called_once();second.pool.disconnect.assert_called_once()

    async def test_unsupported_menu_and_partial_system(self):
        fx=RouterFixture(failures={'/interface/wifi/registration-table':RuntimeError('no such command prefix')})
        self.assertEqual((await self.query(fx,'wifi'))['error'],'unsupported_section')
        fx=RouterFixture({'/system/resource':[{'cpu-load':'20'}]},failures={'/system/clock':RuntimeError('not enough permissions')})
        value=await self.query(fx)
        self.assertEqual(value['status'],'DEGRADED')
        self.assertEqual(value['data']['/system/resource'][0]['cpu-load'],'20')
        self.assertEqual(value['errors']['/system/clock'],'permission_denied')

    async def test_timeout_and_cleanup_error_do_not_leave_lock(self):
        fx=RouterFixture(failures={'/system/resource':TimeoutError('dummy-secret')})
        fx.pool.disconnect.side_effect=OSError('dummy-secret')
        obj=router()
        with patch.dict(os.environ,ENV),patch('routeros_api.RouterOsApiPool',return_value=fx.pool):
            first=await obj.query('system')
        self.assertNotIn('dummy-secret',json.dumps(first))
        self.assertFalse(obj.lock.locked())
        self.assertFalse(obj.async_lock.locked())

    async def test_empty_system_is_not_success(self):
        value=await self.query(RouterFixture())
        self.assertEqual(value['status'],'UNKNOWN')
        self.assertEqual(value['error'],'empty_response')

    async def test_registry_rejects_shell_url_and_wrong_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(directory)
            monitor=Monitoring(Settings('t',frozenset({1}),'k',('m',)),db)
            monitor.router.query=AsyncMock(return_value={'status':'UNKNOWN'})
            registry=Registry();monitor.register(registry)
            for args in ({'section':'/system/reboot'},{'section':'interfaces','command':'set'},
                    {'section':'dns','url':'http://evil'},{'section':'interfaces','limit':11},
                    {'section':'interfaces','filter_field':'name'},{'section':'interfaces','filter_value':'x'}):
                self.assertEqual((await registry.execute('get_mikrotik_data',json.dumps(args)))['error'],'invalid_arguments')
            monitor.router.query.assert_not_awaited()
            await registry.execute('get_mikrotik_data','{"section":"traffic","filter_field":"name","filter_value":"ether1"}')
            monitor.router.query.assert_awaited_once()
            db.close()

class TelegramRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_alias_offset_and_filter(self):
        self.assertEqual(parse_args(['dhcp','10','status=bound']),{'section':'dhcp_leases','offset':10,'filter_field':'status','filter_value':'bound'})
        self.assertEqual(parse_args(['interfaces','name="WAN','Uplink"'])['filter_value'],'WAN Uplink')
        for args in (['/system/reboot'],['interfaces','-1'],['interfaces','500'],['dns','password=x'],['interfaces','10','20']):
            with self.assertRaises(ValueError):parse_args(args)

    def test_catalog_and_unknown_are_readable(self):
        text=help_text()
        for name in SECTIONS:self.assertIn('/mikrotik '+name,text)
        value=router().failure('system','readonly_account_required')
        text=render(value,{'section':'system'})
        self.assertIn('read,api',text)
        self.assertNotIn('CPU 0',text)
        for part in format_messages(text):self.assertNotIn('**',part.plain)

    def test_result_continuation_and_html_escape(self):
        value={'status':'UP','timestamp':'2026-10-19T07:00:00+00:00','method':'API','data':{'/interface':[{'name':'<b>bad</b>`**','rx-byte':'12'}]},
            'resources':{'/interface':{'total':15,'has_more':True,'next_offset':10,'offset':0}}}
        text=render(value,{'section':'interfaces'})
        self.assertIn('/mikrotik interfaces 10',text)
        self.assertIn('RX kumulatif',text)
        self.assertNotIn('<b>bad</b>',next(format_messages(text)).html)

    async def test_direct_command_uses_collector_without_ai(self):
        config=Settings('t',frozenset({1}),'k',('m',))
        monitor=NS(router=NS(query=AsyncMock(return_value=router().failure('system','readonly_account_required'))))
        agent=NS(run=AsyncMock())
        h=Handlers(config,None,agent,monitor,None)
        update=NS(effective_user=NS(id=1),effective_chat=NS(type='private'),effective_message=NS(reply_text=AsyncMock()))
        await h.mikrotik(update,NS(args=['cpu']))
        monitor.router.query.assert_awaited_once_with(section='system')
        agent.run.assert_not_awaited()
        update.effective_message.reply_text.assert_awaited()

    def test_router_natural_questions_require_tools(self):
        for q in ('Tampilkan DHCP MikroTik','Daftar klien yang tersambung','Berapa trafik ether1?','Jelaskan konfigurasi VLAN saya'):
            self.assertTrue(needs_current_data(q))
        self.assertFalse(needs_current_data('Apa itu VLAN MikroTik?'))

    def test_classification_does_not_reveal_exception(self):
        self.assertEqual(error_category(RuntimeError('invalid user name or password dummy-secret')),'authentication_failed')
        self.assertEqual(error_category(ssl.SSLError('dummy-secret')),'tls_verification_failed')
