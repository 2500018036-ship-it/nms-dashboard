import asyncio
import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from app.ai.agent import Agent
from app.ai.client import AIError
from app.ai.context import ContextStore,reference
from app.ai.evidence import finish
from app.ai.tool_registry import Registry,Tool
from app.config import Settings
from app.telegram.handlers import Handlers
from app.telegram.formatting import format_messages

class Call:
    def __init__(self,name,args,identity='call1'):
        self.id,self.type=identity,'function'
        self.function=NS(name=name,arguments=json.dumps(args))
    def model_dump(self,**kwargs):return {'id':self.id,'type':self.type,'function':{'name':self.function.name,'arguments':self.function.arguments}}

def message(text=None,calls=None):return NS(content=text,tool_calls=calls)

def page(offset=0,total=25,limit=10):
    count=min(limit,max(0,total-offset))
    return {'target':'mikrotik','section':'dhcp_leases','status':'UP','timestamp':'2026-10-19T07:00:00+00:00',
        'data':{'/ip/dhcp-server/lease':[{'address':f'192.0.2.{i}','host-name':f'client-{i}'} for i in range(offset,offset+count)]},
        'resources':{'/ip/dhcp-server/lease':{'offset':offset,'total':total,'returned':count,'has_more':offset+count<total,'next_offset':offset+count if offset+count<total else None,'scan_truncated':False,'fields_truncated':False}}}

def entry(result,args=None,name='get_mikrotik_data'):
    return {'tool':name,'arguments':args or {'section':'dhcp_leases'},'result':result}

class ContextTests(unittest.TestCase):
    def test_user_isolation_expiry_copy_and_reset(self):
        clock=NS(value=100)
        store=ContextStore(clock=lambda:clock.value)
        ref=reference('get_mikrotik_data',{'section':'dhcp_leases'},page())
        store.set(1,[ref])
        self.assertEqual(store.get(2),[])
        self.assertNotIn('192.0.2.',json.dumps(store.get(1)))
        copied=store.get(1);copied[0]['arguments']['section']='changed'
        self.assertEqual(store.get(1)[0]['arguments']['section'],'dhcp_leases')
        clock.value+=601
        self.assertEqual(store.get(1),[])
        store.set(1,[ref]);version=store.version(1);store.clear(1)
        store.set(1,[ref],expected_version=version)
        self.assertEqual(store.get(1),[])

    def test_context_bound_and_dedup_pages(self):
        store=ContextStore(max_users=2)
        refs=[reference('get_mikrotik_data',{'section':'dhcp_leases','offset':offset},page(offset,total=100)) for offset in (0,10,20)]
        store.set(1,refs)
        self.assertEqual(len(store.get(1)),1)
        self.assertEqual(store.get(1)[0]['next_offset'],30)
        store.set(2,refs);store.set(3,refs)
        self.assertEqual(store.get(1),[])

    def test_bad_tool_arguments_are_not_context(self):
        self.assertIsNone(reference('shell',{'command':'secret'},{'status':'UP'}))
        self.assertIsNone(reference('get_mikrotik_data',{}, {'error':'invalid_arguments'}))
        ref=reference('check_service',{'target':'docker','password':'secret'},{'status':'UP'})
        self.assertNotIn('password',ref['arguments'])

class EvidenceTests(unittest.TestCase):
    def test_all_returned_records_not_only_model_summary(self):
        answer=finish('Ringkasan singkat.',[entry(page(total=25))],True)
        for i in range(10):self.assertIn(f'`client-{i}`',answer)
        self.assertIn('daftar belum lengkap',answer)
        self.assertIn('/mikrotik dhcp_leases 10',answer)

    def test_latest_page_controls_completeness(self):
        answer=finish('Data.',[entry(page(0)),entry(page(10),{'section':'dhcp_leases','offset':10}),entry(page(20),{'section':'dhcp_leases','offset':20})],True)
        self.assertNotIn('daftar belum lengkap',answer)
        for i in range(25):self.assertIn(f'`client-{i}`',answer)

    def test_repeated_first_page_does_not_move_cursor_back(self):
        values=[entry(page(0)),entry(page(10),{'section':'dhcp_leases','offset':10}),entry(page(20),{'section':'dhcp_leases','offset':20}),entry(page(0))]
        self.assertNotIn('daftar belum lengkap',finish('Data.',values,True))
        store=ContextStore()
        store.set(1,[reference(v['tool'],v['arguments'],v['result']) for v in values])
        self.assertIsNone(store.get(1)[0]['next_offset'])

    def test_nested_container_fields_are_readable_without_dict_repr(self):
        value={'target':'docker','status':'UP','containers':[{'name':'db','ports':[{'host_ip':'127.0.0.1','port':3306}],'log_markers':{'error':2}}]}
        answer=finish('Container.',[entry(value,name='check_service')],True)
        self.assertIn('host_ip: `127.0.0.1`',answer)
        self.assertNotIn("{'host_ip'",answer)
        self.assertNotIn("{'error'",answer)

    def test_all_endpoint_nested_limits_are_visible(self):
        answer=finish('Ringkasan.',[entry({'results':[page()]},args={},name='check_all_endpoints')])
        self.assertIn('/mikrotik dhcp_leases 10',answer)

    def test_long_detail_is_not_cut_at_summary_limit(self):
        value=page(total=10)
        for index,row in enumerate(value['data']['/ip/dhcp-server/lease']):
            row['comment']='x'*160
            row['host-name']=f'client-{index}-'+'h'*150
        answer=finish('Data.',[entry(value)],True)
        self.assertGreater(len(answer),2500)
        parts=list(format_messages(answer))
        self.assertGreater(len(parts),1)
        combined=''.join(p.plain for p in parts)
        for i in range(10):self.assertIn(f'client-{i}',combined)

    def test_mixed_success_does_not_hide_unconfigured_proxmox(self):
        values=[entry({'target':'docker','status':'UP','containers':[{'name':'app','state':'running','health':'not_configured'}]},name='check_service'),
            entry({'target':'proxmox_resources','status':'UNKNOWN','error':'missing_readonly_token'},name='check_service')]
        answer=finish('Semua layanan sehat.\nVM 100 di Proxmox running.',values)
        self.assertNotIn('Semua layanan sehat',answer)
        self.assertNotIn('VM 100',answer)
        self.assertIn('Belum disiapkan',answer)
        self.assertIn('`app`',answer)

    def test_all_unknown_overrides_fabricated_model_values(self):
        result={'target':'proxmox_resources','status':'UNKNOWN','error':'missing_readonly_token'}
        answer=finish('CPU Proxmox 99%.',[entry(result)])
        self.assertNotIn('99%',answer)
        self.assertIn('belum cukup',answer)

    def test_partial_and_scan_field_limits_always_visible(self):
        value=page()
        meta=value['resources']['/ip/dhcp-server/lease'];meta.update(scan_truncated=True,fields_truncated=True)
        value['errors']={'/system/health':'unsupported_section'}
        answer=finish('Ringkasan.',[entry(value)])
        self.assertIn('500 baris',answer)
        self.assertIn('dipotong',answer)
        self.assertIn('Menu tidak tersedia',answer)

    def test_debian_all_fields_and_empty_results(self):
        value={'target':'debian','status':'UP','cpu_percent':12,'memory_percent':34,'disks':[{'path':'/','used_percent':50}]}
        answer=finish('Data server.',[entry(value,name='check_service')],True)
        self.assertIn('cpu_percent: `12`',answer)
        self.assertIn('used_percent: `50`',answer)
        self.assertEqual(finish('DNS adalah...',[]),'DNS adalah...')

class AgentContextTests(unittest.IsolatedAsyncioTestCase):
    def registry(self,total=25):
        reg=Registry()
        schema={'type':'object','properties':{'section':{'enum':['dhcp_leases','system']},'offset':{'type':'integer'}},'required':['section'],'additionalProperties':False}
        async def collect(section,offset=0):
            if section=='system':
                return {'target':'mikrotik','section':'system','status':'UP','data':{'/system/resource':[{'total-memory':'100','free-memory':'40','cpu-load':'20'}]},'resources':{}}
            return page(offset,total)
        reg.add(Tool('get_mikrotik_data','read',schema,collect))
        return reg

    async def test_full_request_fetches_pages_and_shows_every_record(self):
        client=NS(complete=AsyncMock(side_effect=[message(calls=[Call('get_mikrotik_data',{'section':'dhcp_leases'})]),message('Berikut datanya.')]))
        trace=[]
        answer=await Agent(client,self.registry()).run('Tampilkan semua lease DHCP MikroTik saya',trace=trace)
        for i in range(25):self.assertIn(f'`client-{i}`',answer)
        self.assertNotIn('daftar belum lengkap',answer)
        self.assertEqual(len(trace),3)
        self.assertEqual(client.complete.await_count,2)
        payload=json.loads(client.complete.call_args.args[0][-1]['content'])
        self.assertEqual(len(payload['pages']),3)

    async def test_auto_pages_bounded_and_continue_uses_correct_offset(self):
        client=NS(complete=AsyncMock(side_effect=[message(calls=[Call('get_mikrotik_data',{'section':'dhcp_leases'})]),message('Data DHCP.')]))
        trace=[];agent=Agent(client,self.registry(total=100))
        answer=await agent.run('Tampilkan semua DHCP MikroTik saya',trace=trace)
        self.assertEqual(len(trace),6)
        self.assertIn('/mikrotik dhcp_leases 60',answer)
        self.assertNotIn('/mikrotik dhcp_leases 10`',answer)
        store=ContextStore();store.set(1,trace)
        count=client.complete.await_count
        next_trace=[]
        answer=await agent.run('lanjutkan',context=store.get(1),trace=next_trace)
        self.assertEqual(client.complete.await_count,count)
        self.assertIn('`client-60`',answer)
        self.assertNotIn('`client-0`',answer)
        self.assertEqual(next_trace[0]['arguments']['offset'],60)

    async def test_followup_reference_is_not_old_monitoring_data(self):
        context=[{'tool':'get_mikrotik_data','arguments':{'section':'system'},'next_offset':None}]
        client=NS(complete=AsyncMock())
        reg=self.registry();collect=reg.tools['get_mikrotik_data'].handler
        reg.tools['get_mikrotik_data'].handler=AsyncMock(side_effect=collect)
        answer=await Agent(client,reg).run('RAMnya?',context=context)
        client.complete.assert_not_awaited()
        reg.tools['get_mikrotik_data'].handler.assert_awaited_once_with(section='system')
        self.assertIn('total-memory: `100`',answer)
        self.assertNotIn('cpu-load',answer)

    async def test_docker_ram_followup_cannot_switch_to_debian(self):
        reg=Registry();handler=AsyncMock(return_value={'target':'docker','status':'UP','containers':[{'name':'app','memory_bytes':1048576,'cpu_percent':12}]})
        reg.add(Tool('check_service','read',{'type':'object','properties':{'target':{'enum':['docker','debian']}},'required':['target']},handler))
        client=NS(complete=AsyncMock())
        context=[reference('check_service',{'target':'docker'},{'status':'UP'})]
        answer=await Agent(client,reg).run('RAMnya berapa?',context=context)
        handler.assert_awaited_once_with(target='docker')
        client.complete.assert_not_awaited()
        self.assertIn('memory_bytes: `1048576`',answer)
        self.assertNotIn('cpu_percent',answer)

    async def test_ambiguous_followup_asks_target_without_guessing(self):
        client=NS(complete=AsyncMock())
        context=[reference('check_service',{'target':'docker'},{'status':'UP'}),reference('check_service',{'target':'debian'},{'status':'UP'})]
        answer=await Agent(client,self.registry()).run('RAMnya?',context=context)
        self.assertIn('perangkat mana',answer)
        client.complete.assert_not_awaited()

    async def test_conceptual_question_with_context_does_not_require_tool(self):
        client=NS(complete=AsyncMock(return_value=message('DNS menerjemahkan nama.')))
        context=[reference('check_service',{'target':'docker'},{'status':'UP'})]
        await Agent(client,self.registry()).run('Apa itu DNS?',context=context)
        self.assertEqual(client.complete.call_args.args[2],'auto')

    async def test_proxmox_http_is_not_vm_health_when_not_setup(self):
        reg=Registry();reg.add(Tool('check_service','read',{'type':'object','properties':{'target':{'enum':['proxmox']}},'required':['target']},AsyncMock(return_value={'target':'proxmox','status':'UP','http_status':200})))
        client=NS(complete=AsyncMock(side_effect=[message(calls=[Call('check_service',{'target':'proxmox'})]),message('Proxmox VM 100 sehat.')]))
        answer=await Agent(client,reg,capabilities=lambda:{'proxmox_vm_api_configured':False}).run('Apakah VM Proxmox saya sehat?')
        self.assertNotIn('VM 100',answer)
        self.assertIn('Belum disiapkan',answer)

    async def test_no_cursor_does_not_invent_next_page(self):
        client=NS(complete=AsyncMock())
        context=[{'tool':'get_mikrotik_data','arguments':{'section':'system'},'next_offset':None}]
        answer=await Agent(client,self.registry()).run('lanjut',context=context)
        self.assertIn('Belum ada halaman',answer)
        client.complete.assert_not_awaited()

    async def test_provider_failure_after_tool_keeps_real_data(self):
        client=NS(complete=AsyncMock(side_effect=[message(calls=[Call('get_mikrotik_data',{'section':'dhcp_leases'})]),AIError('timeout')]))
        answer=await Agent(client,self.registry()).run('Cek DHCP MikroTik')
        self.assertIn('Ringkasan AI belum',answer)
        self.assertIn('`client-0`',answer)

    async def test_deadline_after_tool_keeps_real_data(self):
        calls=0
        async def complete(*args):
            nonlocal calls
            calls+=1
            if calls==1:return message(calls=[Call('get_mikrotik_data',{'section':'dhcp_leases'})])
            await asyncio.sleep(2)
        client=NS(complete=complete)
        with patch('app.ai.agent.REQUEST_TIMEOUT',.03):
            answer=await Agent(client,self.registry()).run('Cek DHCP MikroTik')
        self.assertIn('batas waktu',answer)
        self.assertIn('`client-0`',answer)

class TelegramContextTests(unittest.IsolatedAsyncioTestCase):
    def handler(self,agent):return Handlers(Settings('t',frozenset({1,2}),'k',('m',)),None,agent,None,None)
    def update(self,user=1):return NS(effective_user=NS(id=user),effective_chat=NS(type='private'),effective_message=NS(reply_text=AsyncMock()))

    async def test_handler_uses_context_and_reset(self):
        received=[]
        async def run(question,context,trace):
            received.append(context)
            trace.append(reference('get_mikrotik_data',{'section':'system'},{'status':'UNKNOWN','error':'readonly_account_required'}))
            return 'Data belum tersedia.'
        h=self.handler(NS(run=AsyncMock(side_effect=run)))
        h.guard=AsyncMock(return_value=True)
        await h.question(self.update(),'Cek CPU MikroTik')
        await h.question(self.update(),'RAMnya?')
        self.assertEqual(received[0],[])
        self.assertEqual(received[1][0]['arguments']['section'],'system')
        await h.question(self.update(2),'RAMnya?')
        self.assertEqual(received[2],[])
        await h.reset(self.update(),NS(args=[]))
        self.assertEqual(h.contexts.get(1),[])

    async def test_reset_during_request_prevents_context_restore(self):
        started=asyncio.Event();resume=asyncio.Event()
        async def run(question,context,trace):
            started.set();await resume.wait()
            trace.append(reference('check_service',{'target':'docker'},{'status':'UP'}))
            return 'Data.'
        h=self.handler(NS(run=AsyncMock(side_effect=run)));h.guard=AsyncMock(return_value=True)
        task=asyncio.create_task(h.question(self.update(),'Cek Docker'))
        await started.wait();await h.reset(self.update(),NS(args=[]));resume.set();await task
        self.assertEqual(h.contexts.get(1),[])

    async def test_general_explanation_preserves_routing_reference(self):
        async def run(question,context,trace):return 'RAM adalah memori.'
        h=self.handler(NS(run=AsyncMock(side_effect=run)));h.guard=AsyncMock(return_value=True)
        h.contexts.set(1,[reference('check_service',{'target':'debian'},{'status':'UP'})])
        await h.question(self.update(),'Apa itu RAM?')
        self.assertEqual(h.contexts.get(1)[0]['arguments']['target'],'debian')
