import asyncio
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from app.config import Settings
from app.dashboard.platform import Platform, Conflict, Missing
from app.dashboard.platform_api import PlatformAPI
from app.dashboard.assistant_history import AssistantHistory


class WorkspacePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Settings('dummy', frozenset({1}), '', ('m',), data_dir=self.tmp.name)
        self.store = Platform(self.tmp.name, self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_topology_receipt_is_atomic_for_create_retry_and_update_retry(self):
        value = {'name': 'LAN', 'nodes': [{'id': 'vm', 'name': 'Virtual', 'kind': 'vm', 'icon': 'vm', 'x': 200, 'y': 100, 'width': 160, 'height': 80}], 'links': []}
        body = {'request_id': 'a' * 32, 'value': value}
        before = len(self.store.list('topologies'))
        item = self.store.save('topologies', body, 'admin')
        self.assertEqual(self.store.save('topologies', body, 'admin'), item)
        self.assertEqual(len(self.store.list('topologies')), before + 1)
        updated = dict(value, name='LAN updated')
        update = dict(request_id='b' * 32, revision=1, value=updated)
        saved = self.store.save('topologies', update, 'admin', item['id'])
        self.assertEqual(self.store.save('topologies', update, 'admin', item['id']), saved)
        self.assertEqual(saved['revision'], 2)
        with self.assertRaises(Conflict):
            self.store.save('topologies', dict(body, value=updated), 'admin')
        with self.assertRaises(Conflict):
            self.store.save('topologies', dict(value=updated, revision=1), 'admin', item['id'])
        with self.assertRaises(ValueError):
            self.store.save('topologies', dict(value=value, request_id=None), 'admin')

    def test_private_history_is_owner_scoped_persistent_and_restart_does_not_rerun(self):
        history = AssistantHistory(self.store)
        now = time.time()
        history.start('one', 'job_' + 'a' * 24, 'a' * 32, 'Status router?', now)
        history.finish('job_' + 'a' * 24, {'state': 'complete', 'answer': 'Router UP'})
        history.start('two', 'job_' + 'b' * 24, 'b' * 32, 'Private question', now + .1)
        self.assertEqual(history.page('one')['items'][0]['answer'], 'Router UP')
        with self.assertRaises(Missing): history.get('two', 'job_' + 'a' * 24)
        with self.assertRaises(Conflict): history.find('one', 'a' * 32, 'Different question')
        restarted = AssistantHistory(Platform(self.tmp.name))
        self.assertEqual(restarted.get('one', 'job_' + 'a' * 24)['answer'], 'Router UP')
        self.assertEqual(restarted.page('two')['items'][0]['error'], 'job_interrupted')
        self.assertNotIn('Private question', str(self.store.audit_page({})))

    def test_async_job_completes_without_ui_polling_and_duplicate_question_runs_once(self):
        loop = asyncio.new_event_loop()
        thread = threading.Thread(target=loop.run_forever); thread.start()
        calls = []
        class Agent:
            async def run(self, question):
                calls.append(question)
                await asyncio.sleep(.03)
                return 'Selesai'
        dashboard = type('Dashboard', (), {'settings': self.cfg})()
        try:
            with patch('app.dashboard.platform_api.Platform', return_value=self.store):
                api = PlatformAPI(dashboard, None, Agent(), loop)
            first = api.ask('Status?', 'one', 'c' * 32)
            second = api.ask('Status?', 'one', 'c' * 32)
            self.assertEqual(first['id'], second['id'])
            for _ in range(100):
                result = api.assistant_history.get('one', first['id'])
                if result['state'] == 'complete': break
                time.sleep(.01)
            self.assertEqual(result['answer'], 'Selesai')
            self.assertEqual(calls, ['Status?'])
            api.jobs.clear()
            session = {'user': {'username': 'one', 'role': 'Operator'}}
            self.assertEqual(api.get('/api/platform/jobs/' + first['id'], {}, session)['answer'], 'Selesai')
        finally:
            loop.call_soon_threadsafe(loop.stop); thread.join(); loop.close()

    def test_history_pagination_and_retention_do_not_mix_owners(self):
        history = AssistantHistory(self.store)
        now = time.time()
        for i in range(105):
            identity = 'job_' + format(i, '024x')
            history.start('one', identity, format(i, '032x'), 'Question ' + str(i), now - 105 + i)
            history.finish(identity, {'state': 'complete', 'answer': 'ok'})
        page = history.page('one')
        self.assertEqual(len(page['items']), 30)
        next_page = history.page('one', page['next_cursor'])
        self.assertFalse({r['id'] for r in page['items']} & {r['id'] for r in next_page['items']})
        with self.store.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM assistant_history').fetchone()[0], 100)
        self.assertEqual(history.page('other')['items'], [])
