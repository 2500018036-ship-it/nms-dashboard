import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from theaz_access.broker import Broker

class DynamicTargetTests(unittest.TestCase):
    def test_broker_uses_current_verified_inventory_and_rejects_changed_url_or_expired_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'platform.sqlite3';identity='inv_'+'a'*24;url='http://192.168.20.199:5380/'
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE objects(collection TEXT,id TEXT,payload TEXT);CREATE TABLE portal_checks(target_id TEXT,url TEXT,checked REAL,payload TEXT);CREATE TABLE platform_settings(id INTEGER,payload TEXT);')
                db.execute('INSERT INTO objects VALUES(?,?,?)',('inventory',identity,json.dumps({'name':'DNS GUI','enabled':True,'dashboard_url':url})))
                db.execute('INSERT INTO portal_checks VALUES(?,?,?,?)',(identity,url,time.time(),json.dumps({'reachable':True,'connect_ip':'192.168.20.199'})))
                db.execute('INSERT INTO platform_settings VALUES(1,?)',(json.dumps({'allowed_hosts':['192.168.20.199']}),))
            broker=Broker({'targets':[]},directory,'fixed-image','/unused',str(path))
            self.assertEqual(broker.selected(identity)['url'],url)
            with sqlite3.connect(path) as db:db.execute('UPDATE portal_checks SET url=?',('http://192.168.20.199:5381/',))
            with self.assertRaisesRegex(ValueError,'portal_not_verified'):broker.selected(identity)
            with sqlite3.connect(path) as db:db.execute('UPDATE portal_checks SET url=?,checked=?',(url,time.time()-901))
            with self.assertRaisesRegex(ValueError,'portal_not_verified'):broker.selected(identity)
            with sqlite3.connect(path) as db:db.execute('UPDATE portal_checks SET checked=?,payload=?',(time.time(),json.dumps({'reachable':True,'connect_ip':'127.0.0.1'})))
            with self.assertRaisesRegex(ValueError,'invalid_connect_address'):broker.selected(identity)
