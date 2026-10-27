import json
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock
import httpx
from openai import AuthenticationError,RateLimitError,APITimeoutError,APIConnectionError,InternalServerError
from app.config import Settings
from app.ai.agent import Agent,needs_current_data
from app.ai.client import AIClient,AIError
from app.ai.tool_registry import Registry,Tool

def settings():
    return Settings('fake-token',frozenset({123}),'fake-key',('primary','fallback'))

def msg(text=None,calls=None):
    return NS(content=text,tool_calls=calls)

class Call:
    def __init__(self,name='read',args='{}',identity='call-1'):
        self.id,self.type=identity,'function'
        self.function=NS(name=name,arguments=args)
    def model_dump(self,**kwargs):
        return {'id':self.id,'type':self.type,'function':{'name':self.function.name,'arguments':self.function.arguments}}

def response(text='Siap',calls=None,finish='stop'):
    return NS(model='actual',choices=[NS(message=msg(text,calls),finish_reason=finish)])

class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_key_absent_does_not_disable_monitoring_client_startup(self):
        client=AIClient(Settings('t',frozenset({1}),'',('model',)))
        self.assertIsNone(client.sdk)
        with self.assertRaises(AIError) as exc:await client.complete([])
        self.assertEqual(exc.exception.category,'not_configured')
        self.assertEqual((await client.diagnostics())['status'],'UNKNOWN')
        await client.close()
    def client(self,side_effect):
        sdk=NS(chat=NS(completions=NS(create=AsyncMock(side_effect=side_effect))),close=AsyncMock())
        return AIClient(settings(),sdk),sdk

    async def test_general_answer(self):
        client,sdk=self.client([response()])
        self.assertEqual((await client.complete([])).content,'Siap')
        self.assertEqual(client.last['status'],'UP')

    async def test_router_moderation_model_is_not_accepted_as_general_answer(self):
        classifier=response('safe');classifier.model='nvidia/nemotron-3.5-content-safety:free'
        client,sdk=self.client([classifier,response('NMS memantau jaringan.')])
        result=await client.complete([])
        self.assertEqual(result.content,'NMS memantau jaringan.')
        self.assertEqual(client.last['configured_model'],'fallback')
        self.assertEqual(sdk.chat.completions.create.call_count,2)

    async def test_only_classifier_responses_are_a_bounded_model_error(self):
        classifier=response('safe');classifier.model='meta-llama/llama-guard-4'
        client,sdk=self.client([classifier,classifier])
        with self.assertRaises(AIError) as error:await client.complete([])
        self.assertEqual(error.exception.category,'model')
        self.assertEqual(sdk.chat.completions.create.call_count,2)

    async def test_empty_falls_back(self):
        client,sdk=self.client([NS(choices=[]),response()])
        await client.complete([])
        self.assertEqual(sdk.chat.completions.create.call_args.kwargs['model'],'fallback')

    async def test_whitespace_rejected(self):
        client,_=self.client([response(' '),response(' ')])
        with self.assertRaises(AIError) as e: await client.complete([])
        self.assertEqual(e.exception.category,'empty')

    async def test_truncated_rejected(self):
        client,_=self.client([response('truncated',finish='length')]*2)
        with self.assertRaises(AIError):await client.complete([])

    async def test_required_tool_ignored_uses_explicit_fallback(self):
        client,sdk=self.client([response('Semua sehat'),response(calls=[Call()])])
        result=await client.complete([],tools=[{'type':'function','function':{'name':'read'}}],tool_choice='required')
        self.assertTrue(result.tool_calls)
        self.assertEqual(sdk.chat.completions.create.call_count,2)
        self.assertEqual(client.last['configured_model'],'fallback')

    async def test_required_tool_ignored_by_all_models_is_protocol_failure(self):
        client,sdk=self.client([response('Semua sehat')]*2)
        with self.assertRaises(AIError) as error:
            await client.complete([],tools=[{'type':'function','function':{'name':'read'}}],tool_choice='required')
        self.assertEqual(error.exception.category,'protocol')
        self.assertEqual(sdk.chat.completions.create.call_count,2)

    async def test_auth_no_retry_or_fallback(self):
        http=httpx.Response(401,request=httpx.Request('POST','https://example.invalid'))
        client,sdk=self.client([AuthenticationError('denied',response=http,body=None)])
        with self.assertRaises(AIError) as e:await client.complete([])
        self.assertEqual(e.exception.category,'auth')
        self.assertEqual(sdk.chat.completions.create.call_count,1)

    async def test_rate_limit_fallback(self):
        http=httpx.Response(429,request=httpx.Request('POST','https://example.invalid'))
        client,sdk=self.client([RateLimitError('slow',response=http,body=None),response()])
        await client.complete([])
        self.assertEqual(sdk.chat.completions.create.call_count,2)

    async def test_daily_free_quota_does_not_retry_same_account_free_models(self):
        http=httpx.Response(429,request=httpx.Request('POST','https://example.invalid'))
        error=RateLimitError('limited',response=http,body={'message':'free-models-per-day'})
        sdk=NS(chat=NS(completions=NS(create=AsyncMock(side_effect=error))),close=AsyncMock())
        cfg=Settings('t',frozenset({1}),'dummy',('openrouter/free','configured:free'))
        client=AIClient(cfg,sdk)
        with self.assertRaises(AIError) as exc:await client.complete([])
        self.assertEqual(exc.exception.category,'daily_limit')
        self.assertEqual(sdk.chat.completions.create.call_count,1)

    async def test_timeout_bounded(self):
        error=APITimeoutError(request=httpx.Request('POST','https://example.invalid'))
        client,sdk=self.client([error]*4)
        with self.assertRaises(AIError) as e:await client.complete([])
        self.assertEqual(e.exception.category,'timeout')
        self.assertEqual(sdk.chat.completions.create.call_count,4)

    async def test_network_bounded(self):
        error=APIConnectionError(request=httpx.Request('POST','https://example.invalid'))
        client,sdk=self.client([error]*4)
        with self.assertRaises(AIError) as e:await client.complete([])
        self.assertEqual(e.exception.category,'network')

    async def test_server_fallback(self):
        http=httpx.Response(503,request=httpx.Request('POST','https://example.invalid'))
        error=InternalServerError('offline',response=http,body=None)
        client,sdk=self.client([error,error,response()])
        await client.complete([])
        self.assertEqual(client.last['configured_model'],'fallback')

class AgentTests(unittest.IsolatedAsyncioTestCase):
    def setup_registry(self,handler=None):
        reg=Registry()
        reg.add(Tool('read','read',{'type':'object','properties':{},'additionalProperties':False},handler or AsyncMock(return_value={'status':'UP','value':42})))
        return reg

    async def test_no_tool(self):
        client=NS(complete=AsyncMock(return_value=msg('DNS adalah...')))
        self.assertEqual(await Agent(client,self.setup_registry()).run('Apa itu DNS?'),'DNS adalah...')

    async def test_existing_proxmox_prefetch_preserved_when_provider_times_out(self):
        handler=AsyncMock(return_value={'target':'proxmox_resources','status':'UNKNOWN','error':'missing_readonly_token'})
        reg=Registry();reg.add(Tool('check_service','read',{'type':'object','properties':{'target':{'enum':['proxmox_resources']}},'required':['target']},handler))
        client=NS(complete=AsyncMock(side_effect=AIError('timeout')))
        trace=[]
        answer=await Agent(client,reg,capabilities=lambda:{'proxmox_vm_api_configured':False}).run('Cek VM Proxmox saya',trace=trace)
        handler.assert_awaited_once_with(target='proxmox_resources')
        self.assertEqual(trace[0]['arguments']['target'],'proxmox_resources')
        self.assertIn('Belum disiapkan',answer)

    async def test_tool_call_and_matching_id(self):
        client=NS(complete=AsyncMock(side_effect=[msg(calls=[Call()]),msg('Hasil UP')]))
        await Agent(client,self.setup_registry()).run('Cek homelab')
        messages=client.complete.call_args.args[0]
        self.assertEqual(messages[-1]['tool_call_id'],'call-1')
        self.assertEqual(json.loads(messages[-1]['content'])['value'],42)

    async def test_actual_claim_without_tool_rejected(self):
        client=NS(complete=AsyncMock(return_value=msg('CPU 4%')))
        with self.assertRaises(AIError):await Agent(client,self.setup_registry()).run('Cek CPU')

    async def test_failed_tool_does_not_crash_agent(self):
        client=NS(complete=AsyncMock(side_effect=[msg(calls=[Call()]),msg('Data tidak tersedia')]))
        reg=self.setup_registry(AsyncMock(side_effect=OSError('broken')))
        self.assertIn('Data monitoring belum cukup',await Agent(client,reg).run('Cek homelab'))

    async def test_loop_bounded(self):
        client=NS(complete=AsyncMock(return_value=msg(calls=[Call()])))
        with self.assertRaises(AIError) as e:await Agent(client,self.setup_registry()).run('Cek homelab')
        self.assertEqual(e.exception.category,'tool_limit')
        self.assertEqual(client.complete.call_count,4)

    async def test_bad_json_unknown_tool(self):
        reg=self.setup_registry()
        self.assertEqual((await reg.execute('read','{'))['error'],'invalid_arguments')
        self.assertEqual((await reg.execute('shell','{}'))['error'],'unknown_tool')

    async def test_extra_arguments_rejected(self):
        reg=self.setup_registry()
        for raw in ['[]','null','{"url":"http://169.254.169.254"}','{"target":"8.8.8.8"}']:
            self.assertEqual((await reg.execute('read',raw))['error'],'invalid_arguments')

    async def test_tool_timeout(self):
        import asyncio
        async def slow():await asyncio.sleep(2)
        reg=self.setup_registry(slow); reg.tools['read'].timeout=.01
        self.assertEqual((await reg.execute('read','{}'))['error'],'timeout')

    async def test_duplicate_call_id_rejected(self):
        client=NS(complete=AsyncMock(return_value=msg(calls=[Call(),Call()])))
        with self.assertRaises(AIError):await Agent(client,self.setup_registry()).run('Cek homelab')
