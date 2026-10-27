import json
import sqlite3
import time
from pathlib import Path
from app.storage import incidents
from app.storage.application_logs import initialize as initialize_logs

class Database:
    def __init__(self, directory):
        Path(directory).mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(Path(directory)/'nms.sqlite3'))
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('PRAGMA busy_timeout=5000')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, ts REAL NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS checks_target_ts ON checks(target,ts);
          CREATE INDEX IF NOT EXISTS checks_target_id ON checks(target,id DESC);
          CREATE TABLE IF NOT EXISTS alert_state(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts REAL NOT NULL,key TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS notifications(event_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
            last_attempt REAL NOT NULL DEFAULT 0,queued_at REAL NOT NULL,error TEXT);
        ''')
        initialize_logs(self.db)
        self.db.execute("INSERT OR IGNORE INTO metadata(key,value) SELECT 'last_event_id',CAST(COALESCE(MAX(id),0) AS TEXT) FROM events")
        self.db.commit()
        incidents.initialize(self.db)

    def save(self, value):
        self.db.execute('INSERT INTO checks(ts,target,status,payload) VALUES(?,?,?,?)',(time.time(),value['target'],value['status'],json.dumps(value,ensure_ascii=False)))
        self.db.commit()

    def history(self, target, limit=2):
        return [json.loads(row[0]) for row in self.db.execute('SELECT payload FROM checks WHERE target=? ORDER BY id DESC LIMIT ?', (target,limit))]

    def event(self, key, kind, payload):
        # IDs must not reset after retention deletes every historical event:
        # the durable notification cursor depends on monotonically increasing IDs.
        highest=self.db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
        identity=max(highest,int(self.metadata('last_event_id') or 0))+1
        recorded=time.time()
        with self.db:
            cursor=self.db.execute('INSERT INTO events(id,ts,key,kind,payload) VALUES(?,?,?,?,?)',(identity,recorded,key,kind,json.dumps(payload)))
            incidents.apply(self.db,identity,key,kind,payload,recorded)
            self.db.execute("INSERT OR REPLACE INTO metadata VALUES('incident_projection_cursor',?)",(str(identity),))
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('last_event_id',str(identity)))
        return cursor.lastrowid

    def events(self, limit=20, component='all'):
        prefixes={'mikrotik':('%mikrotik%','network:link:%','network:traffic:%','network:idle:%','network:bandwidth:%','network:flap:%','interface:%'),
            'wireguard':('%wireguard%',),'cisco':('%cisco%',),'docker':('%container%','restarts:%'),
            'debian':('%debian%',),'proxmox':('%pve%','guest:%'),'devices':('%device%',)}
        if component!='all' and component not in prefixes:raise ValueError('invalid component')
        if type(limit) is not int or not 1<=limit<=30:raise ValueError('invalid limit')
        sql='SELECT ts,key,kind,payload FROM events'
        args=[]
        if component!='all':
            sql+=' WHERE ('+' OR '.join('key LIKE ?' for _ in prefixes[component])+')';args.extend(prefixes[component])
        sql+=' ORDER BY id DESC LIMIT ?';args.append(limit)
        return [{**json.loads(payload),'recorded_at':ts,'key':key,'kind':kind}
            for ts,key,kind,payload in self.db.execute(sql,args)]

    def states(self):
        return {k:json.loads(v) for k,v in self.db.execute('SELECT key,payload FROM alert_state')}

    def set_state(self, key, state):
        self.db.execute('INSERT OR REPLACE INTO alert_state VALUES(?,?)',(key,json.dumps(state)))
        self.db.commit()

    def metadata(self, key, value=None):
        if value is not None:
            self.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(key,str(value)))
            self.db.commit()
        row=self.db.execute('SELECT value FROM metadata WHERE key=?',(key,)).fetchone()
        return row[0] if row else None

    def cleanup(self, days):
        cutoff=time.time()-days*86400
        self.db.execute('DELETE FROM checks WHERE ts < ?', (cutoff,))
        self.db.execute('DELETE FROM application_logs WHERE ts < ?',(cutoff,))
        self.db.execute('DELETE FROM events WHERE ts < ?', (cutoff,))
        self.db.execute("DELETE FROM notifications WHERE queued_at < ? AND status!='pending'",(cutoff,))
        self.db.execute("DELETE FROM incidents WHERE status!='ACTIVE' AND updated_at<?",(cutoff,))
        self.db.execute('DELETE FROM incident_events WHERE incident_id NOT IN (SELECT id FROM incidents)')
        for key,state in self.states().items():
            if not state.get('active') and not state.get('pending') and state.get('updated_at',time.time()) < cutoff:
                self.db.execute('DELETE FROM alert_state WHERE key=?',(key,))
        self.db.commit()

    def close(self):
        self.db.close()
