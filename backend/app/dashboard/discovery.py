"""Persist discovered capabilities independently from enabled polling categories."""
import hashlib
import json
import time
from app.monitoring.device_capabilities import detect

def initialize(store):
    with store.db() as db:db.execute('''CREATE TABLE IF NOT EXISTS device_discoveries(
        inventory_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,categories TEXT NOT NULL,observed REAL NOT NULL)''')

def fingerprint(item):
    return hashlib.sha256(json.dumps({k:item.get(k) for k in ('host','monitor_port','monitor_method','vendor','model','firmware')},sort_keys=True).encode()).hexdigest()

def read(store,item):
    initialize(store)
    with store.db() as db:row=db.execute('SELECT fingerprint,categories,observed FROM device_discoveries WHERE inventory_id=?',(item['id'],)).fetchone()
    return {'categories':json.loads(row[1]),'observed_at':row[2]} if row and row[0]==fingerprint(item) else None

def save(store,item,sample,complete=False):
    if sample.get('status') not in {'UP','DEGRADED'} or sample.get('error'):return
    previous=read(store,item); found=set(detect(sample))
    if previous and not complete:found.update(previous['categories'])
    # Counter based bandwidth is supported only after a measured delta exists.
    with store.db() as db:db.execute('INSERT OR REPLACE INTO device_discoveries VALUES(?,?,?,?)',
        (item['id'],fingerprint(item),json.dumps(sorted(found)),time.time()))
