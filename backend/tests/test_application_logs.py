import logging
import os
import tempfile
import time
import unittest
from unittest.mock import patch
from app.storage.database import Database
from app.storage.application_logs import LogSink,page
from app.dashboard.platform import Platform
import test_dashboard_sessions as helpers

class ApplicationLogTests(unittest.TestCase):
    def test_real_records_are_redacted_bounded_and_tracebacks_not_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            database=Database(directory);sink=LogSink(directory)
            with patch.dict(os.environ,{'TEST_API_KEY':'private-value-test'}):
                record=logging.LogRecord('app.services.test',logging.WARNING,'',1,'test_event password=abc api_key=private-value-test '+('x'*2000),(),None)
                sink.emit(record)
            sink.queue.join();sink.close()
            value=page(database.db,{})
            self.assertEqual(value['total'],1);message=value['items'][0]['message']
            self.assertNotIn('private-value-test',message);self.assertNotIn('password=abc',message);self.assertLessEqual(len(message),1200)
            self.assertEqual(value['items'][0]['level'],'WARNING')
            self.assertEqual(page(database.db,{'level':['ERROR']})['total'],0)
            self.assertEqual(page(database.db,{'q':['test_event']})['total'],1)
            database.close()

    def test_third_party_loggers_are_excluded_and_retention_is_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            database=Database(directory);sink=LogSink(directory)
            sink.emit(logging.LogRecord('httpx',logging.INFO,'',1,'external body',(),None));sink.close()
            self.assertEqual(page(database.db,{})['total'],0)
            database.db.execute("INSERT INTO application_logs(ts,source,level,message,request_id) VALUES(?,'root','INFO','old','-')",(time.time()-3*86400,));database.db.commit()
            database.cleanup(1);self.assertEqual(database.db.execute('SELECT COUNT(*) FROM application_logs').fetchone()[0],0);database.close()

class ApplicationLogAPITests(unittest.TestCase):
    setUp=helpers.SessionAPITests.setUp;tearDown=helpers.SessionAPITests.tearDown;request=helpers.SessionAPITests.request;login=helpers.SessionAPITests.login
    def test_log_access_and_filter_validation(self):
        self.assertEqual(self.request('/api/platform/application-logs')[0],401)
        self.login();self.assertEqual(self.request('/api/platform/application-logs')[0],403)
        self.server.platform.store.bootstrap('test-admin-'+'X'*30)
        status,_,headers=self.request('/api/auth/login','POST',{'username':'admin','password':'test-admin-'+'X'*30});self.assertEqual(status,200);self.cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('/api/platform/application-logs')[0],200)
        self.assertEqual(self.request('/api/platform/application-logs?level=invalid')[0],400)
        self.assertEqual(self.request('/api/platform/application-logs?page=0')[0],400)

if __name__=='__main__':unittest.main()
