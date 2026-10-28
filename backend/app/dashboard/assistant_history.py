"""Private, durable assistant jobs. Audit logs contain metadata only."""
import time
from app.dashboard.platform import Conflict, Missing
from app.logging_config import redact


class AssistantHistory:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS assistant_history(
                id TEXT PRIMARY KEY,owner TEXT NOT NULL,request_key TEXT NOT NULL,
                question TEXT NOT NULL,state TEXT NOT NULL,created_at REAL NOT NULL,
                finished_at REAL,answer TEXT,error TEXT,UNIQUE(owner,request_key))''')
            db.execute('CREATE INDEX IF NOT EXISTS assistant_owner_created ON assistant_history(owner,created_at)')
            db.execute('DELETE FROM assistant_history WHERE created_at<?', (time.time()-90*86400,))
            db.execute("UPDATE assistant_history SET state='failed',error='job_interrupted',finished_at=? WHERE state='running'", (time.time(),))

    @staticmethod
    def public(row):
        return {key: row[index] for index, key in enumerate(('id','request_id','question','state','created_at','finished_at','answer','error')) if row[index] is not None}

    def find(self, actor, request_key, question):
        with self.store.db() as db:
            row = db.execute('SELECT id,request_key,question,state,created_at,finished_at,answer,error FROM assistant_history WHERE owner=? AND request_key=?', (actor, request_key)).fetchone()
        if row and row[2] != redact(question):
            raise Conflict()
        return self.public(row) if row else None

    def get(self, actor, identity):
        with self.store.db() as db:
            row = db.execute('SELECT id,request_key,question,state,created_at,finished_at,answer,error FROM assistant_history WHERE owner=? AND id=?', (actor, identity)).fetchone()
        if not row:raise Missing()
        return self.public(row)

    def page(self, actor, before=None):
        with self.store.db() as db:
            db.execute('DELETE FROM assistant_history WHERE created_at<?', (time.time()-90*86400,))
            boundary=time.time()+1
            if before:
                cursor=db.execute('SELECT created_at FROM assistant_history WHERE owner=? AND id=?',(actor,before)).fetchone()
                if not cursor:raise Missing()
                boundary=cursor[0]
            rows = db.execute('SELECT id,request_key,question,state,created_at,finished_at,answer,error FROM assistant_history WHERE owner=? AND created_at<? ORDER BY created_at DESC LIMIT 31', (actor,boundary)).fetchall()
        return {'items': [self.public(row) for row in reversed(rows[:30])], 'next_cursor':rows[29][0] if len(rows)>30 else None}

    def start(self, actor, identity, request_key, question, now):
        with self.store.db() as db:
            db.execute("DELETE FROM assistant_history WHERE created_at<? AND state<>'running'", (now-90*86400,))
            db.execute("INSERT INTO assistant_history(id,owner,request_key,question,state,created_at) VALUES(?,?,?,?,'running',?)", (identity, actor, request_key, redact(question), now))
            db.execute("DELETE FROM assistant_history WHERE owner=? AND state<>'running' AND id NOT IN (SELECT id FROM assistant_history WHERE owner=? ORDER BY created_at DESC LIMIT 100)", (actor, actor))

    def finish(self, identity, update):
        with self.store.db() as db:
            db.execute('UPDATE assistant_history SET state=?,answer=?,error=?,finished_at=? WHERE id=?', (update['state'], update.get('answer'), update.get('error'), time.time(), identity))
