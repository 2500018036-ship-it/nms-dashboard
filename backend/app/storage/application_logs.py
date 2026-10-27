"""Bounded, non-blocking NMS log collection. No tracebacks or device logs in API."""
import logging
from pathlib import Path
import queue
import re
import sqlite3
import threading
import time
from app.logging_config import redact,request_id
from app.dashboard import models

def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS application_logs(
        id INTEGER PRIMARY KEY,ts REAL NOT NULL,source TEXT NOT NULL,level TEXT NOT NULL,
        message TEXT NOT NULL,request_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS application_logs_ts ON application_logs(ts);''')

class LogSink(logging.Handler):
    def __init__(self,directory):
        super().__init__(logging.INFO)
        self.path=Path(directory)/'nms.sqlite3'
        self.queue=queue.Queue(maxsize=1000);self.dropped=0;self.stopping=threading.Event()
        self.worker=threading.Thread(target=self.run,daemon=True,name='nms-log-writer');self.worker.start()

    def emit(self,record):
        if self.stopping.is_set() or not (record.name=='root' or record.name.startswith('app.')):return
        try:
            message=re.sub(r'[\x00-\x1f\x7f]',' ',redact(record.getMessage()))[:1200]
            item=(record.created,record.name[:120],record.levelname[:20],message,request_id.get()[:80])
            self.queue.put_nowait(item)
        except (queue.Full,ValueError,TypeError):self.dropped+=1

    def run(self):
        db=sqlite3.connect(self.path,timeout=.25)
        try:
            while not self.stopping.is_set() or not self.queue.empty():
                try:item=self.queue.get(timeout=.2)
                except queue.Empty:continue
                try:
                    db.execute('INSERT INTO application_logs(ts,source,level,message,request_id) VALUES(?,?,?,?,?)',item);db.commit()
                except sqlite3.Error:self.dropped+=1
                finally:self.queue.task_done()
        finally:db.close()

    def close(self):
        self.stopping.set();self.worker.join(timeout=2);super().close()

def page(db,query):
    models.fields(query,('page','q','level','from','to'))
    if any(len(v)!=1 for v in query.values()):raise ValueError('invalid_query')
    number=models.integer(int(query.get('page',['1'])[0]),1,10000);q=models.text(query.get('q',[''])[0],0,120)
    level=query.get('level',['all'])[0]
    if level not in {'all','INFO','WARNING','ERROR','CRITICAL'}:raise ValueError('invalid_level')
    end=float(query.get('to',[time.time()])[0]);start=float(query.get('from',[end-86400])[0])
    if not 0<start<end<=time.time()+60 or end-start>31*86400:raise ValueError('invalid_window')
    where='ts>=? AND ts<=? AND instr(lower(source||message||request_id),lower(?))>0';args=[start,end,q]
    if level!='all':where+=' AND level=?';args.append(level)
    total=db.execute('SELECT COUNT(*) FROM application_logs WHERE '+where,args).fetchone()[0]
    rows=db.execute('SELECT id,ts,source,level,message,request_id FROM application_logs WHERE '+where+' ORDER BY id DESC LIMIT 25 OFFSET ?',args+[(number-1)*25]).fetchall()
    return {'items':[dict(zip(('id','time','source','level','message','request_id'),r)) for r in rows],'total':total,'page':number,'page_size':25,
        'from':start,'to':end,'generated_at':time.time(),'scope':'Sanitized NMS application logs since collector activation; no tracebacks, conversation text, external Docker logs or remote syslog'}
