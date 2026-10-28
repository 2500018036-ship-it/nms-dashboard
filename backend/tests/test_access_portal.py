import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.config import Settings
from app.dashboard.platform import Platform, Forbidden
from app.dashboard.access import authorize


class AccessPortalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Platform(self.tmp.name,Settings('test',frozenset({1}),'',('m',),data_dir=self.tmp.name))
        self.session={'user':{'username':'admin','role':'Administrator'},'expires_at':9999999999,'_access_binding':'bound-session'}
        import json
        self.config=Path(self.tmp.name)/'targets.json'
        self.config.write_text(json.dumps({'targets':[
            {'id':'router','name':'Router','url':'http://192.168.20.1/','roles':['Administrator','Network Administrator']},
            {'id':'server','name':'Server','url':'https://192.168.20.200:8006/','roles':['Administrator','Server Administrator']}]}))
        self.env=patch.dict(os.environ,{'NMS_ACCESS_ENABLED':'true','NMS_ACCESS_TARGETS_FILE':str(self.config)});self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def test_disabled_by_default_does_not_authorize_a_runtime(self):
        with patch.dict(os.environ,{'NMS_ACCESS_ENABLED':'false'}):
            value=authorize(self.store,self.session,{})
            self.assertFalse(value['enabled']);self.assertEqual(value['targets'],[])
    def test_acl_and_current_session_binding_are_authoritative(self):
        value=authorize(self.store,self.session,{'target':['server']})
        self.assertEqual(value['binding'],'bound-session')
        self.session['user']['role']='Network Administrator'
        with self.assertRaises(Forbidden):authorize(self.store,self.session,{'target':['server']})
        self.assertTrue(authorize(self.store,self.session,{'target':['router']})['targets'][0]['allowed'])
        self.session['user']['role']='Viewer'
        with self.assertRaises(Forbidden):authorize(self.store,self.session,{'target':['router']})
