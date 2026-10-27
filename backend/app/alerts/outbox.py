"""Durable delivery independent of AI; no blind resend after an ambiguous timeout."""
import json
import hashlib
import time
from app.alerts.presentation import metadata

class Outbox:
    def __init__(self,database,cooldown=600,ignored_prefixes=(),ignored_keys=(),silenced=None):
        self.database=database
        self.silenced=silenced or (lambda key:False)
        self.cooldown=cooldown
        self.ignored_prefixes,self.ignored_keys=tuple(ignored_prefixes),frozenset(ignored_keys)
        if database.metadata('notification_cursor') is None:
            highest=database.db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
            database.metadata('notification_cursor',highest)
            # Preserve pending notifications from the previous delivery implementation.
            for key,state in database.states().items():
                if state.get('pending'):
                    event={**state['pending'],'restored_pending':True}
                    database.event(key,event['kind'],event)
        self.cancel_ignored()

    def ignored(self,key):
        return key in self.ignored_keys or bool(self.ignored_prefixes and key.startswith(self.ignored_prefixes))

    def cancel_ignored(self):
        db=self.database.db
        for identity,payload in db.execute("SELECT event_id,payload FROM notifications WHERE status='pending'").fetchall():
            if self.ignored(json.loads(payload).get('key','')):
                db.execute("UPDATE notifications SET status='suppressed',error='notification_policy_disabled' WHERE event_id=?",(identity,))
        db.commit()

    def statistical_gate(self,event,previous,identity):
        """Keep cooldown across recovery; do not announce recovery for a muted cycle."""
        kind,stamp=event['kind'],event['time']
        incident=event.get('first_seen',stamp)
        state=dict(previous)
        if kind=='ALERT':
            last=previous.get('last_alert_at')
            duplicate=last is not None and 0<=stamp-last<self.cooldown
            if event.get('severity')=='CRITICAL' and previous.get('severity')!='CRITICAL':duplicate=False
            state.update(incident=incident,announced=not duplicate,alert_event_id=None if duplicate else identity,
                severity=event.get('severity','WARNING'))
            if not duplicate:state['last_alert_at']=stamp
            return duplicate,'cooldown_duplicate' if duplicate else None,state
        duplicate=not (previous.get('announced') and previous.get('incident')==incident)
        if not duplicate:event['_alert_event_id']=previous.get('alert_event_id')
        state['announced']=False
        return duplicate,'unannounced_recovery' if duplicate else None,state

    def maintenance_gate(self,event):
        key=event.get('key','')
        if not self.silenced(key):return False
        self.database.db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('maintenance_muted:'+key,json.dumps(event)))
        return True

    def release_maintenance(self):
        db=self.database.db
        rows=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'maintenance_muted:%' LIMIT 500").fetchall()
        for meta,payload in rows:
            key=meta.removeprefix('maintenance_muted:')
            if self.silenced(key):continue
            event=json.loads(payload);state=self.database.states().get(key,{})
            # Still active after maintenance: one fresh notification, same incident identity.
            # Recovery inside maintenance stays in history and is not announced alone.
            if state.get('active') and event.get('kind')=='ALERT':
                event.update(time=time.time(),maintenance_ended=True)
                self.database.event(key,'ALERT',event)
            db.execute('DELETE FROM metadata WHERE key=?',(meta,))
        db.commit()

    def stage(self,enabled=True):
        db=self.database.db
        self.cancel_ignored()
        self.release_maintenance()
        cursor=int(self.database.metadata('notification_cursor') or 0)
        rows=db.execute('SELECT id,payload,kind FROM events WHERE id>? ORDER BY id LIMIT 256',(cursor,)).fetchall()
        for identity,payload,kind in rows:
            if enabled and kind in {'ALERT','RECOVERY','CHANGE'}:
                event=json.loads(payload)
                if self.maintenance_gate(event):
                    db.execute('INSERT OR IGNORE INTO notifications(event_id,payload,queued_at,status,error) VALUES(?,?,?,?,?)',
                        (identity,payload,time.time(),'suppressed','maintenance_window'))
                    continue
                if self.ignored(event.get('key','')):
                    db.execute('INSERT OR IGNORE INTO notifications(event_id,payload,queued_at,status,error) VALUES(?,?,?,?,?)',
                        (identity,payload,time.time(),'suppressed','notification_policy_disabled'))
                    continue
                gate_key='notification_gate:'+event.get('key','unknown')
                stored=db.execute('SELECT value FROM metadata WHERE key=?',(gate_key,)).fetchone()
                previous=json.loads(stored[0]) if stored else {}
                if event.get('key','').startswith(('network:idle:','network:traffic:')) and kind in {'ALERT','RECOVERY'}:
                    duplicate,reason,state=self.statistical_gate(event,previous,identity)
                    db.execute('INSERT OR IGNORE INTO notifications(event_id,payload,queued_at,status,error) VALUES(?,?,?,?,?)',
                        (identity,json.dumps(event),time.time(),'suppressed' if duplicate else 'pending',reason))
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',(gate_key,json.dumps(state)))
                    continue
                severity=metadata(event,event.get('key',''),kind).get('severity','WARNING')
                # Same condition is deduplicated, but recovery, a new incident after
                # recovery, another device, and severity escalation bypass the gate.
                signature=hashlib.sha256(json.dumps({'kind':kind,'severity':severity,
                    'value':event.get('value') if kind=='CHANGE' else None},sort_keys=True).encode()).hexdigest()
                stamp=event.get('time',time.time())
                duplicate=(previous.get('signature')==signature and 0<=stamp-previous.get('at',0)<self.cooldown)
                db.execute('INSERT OR IGNORE INTO notifications(event_id,payload,queued_at,status,error) VALUES(?,?,?,?,?)',
                    (identity,payload,time.time(),'suppressed' if duplicate else 'pending','cooldown_duplicate' if duplicate else None))
                if not duplicate:
                    db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',
                        (gate_key,json.dumps({'signature':signature,'at':stamp,'kind':kind,'severity':severity})))
        if rows:db.execute('INSERT OR REPLACE INTO metadata VALUES(?,?)',('notification_cursor',str(rows[-1][0])))
        db.commit()

    def pending(self,now=None):
        now=time.time() if now is None else now
        rows=self.database.db.execute("SELECT event_id,payload,attempts,last_attempt FROM notifications WHERE status='pending' ORDER BY event_id LIMIT 100").fetchall()
        ready=[]
        for identity,payload,attempts,last in rows:
            if last and now-last<min(300,5*2**attempts):continue
            event=json.loads(payload)
            if self.maintenance_gate(event):
                self.database.db.execute("UPDATE notifications SET status='suppressed',error='maintenance_window' WHERE event_id=?",(identity,))
                continue
            related=event.get('_alert_event_id')
            if related:
                status=self.database.db.execute('SELECT status FROM notifications WHERE event_id=?',(related,)).fetchone()
                if not status or status[0] in {'failed','suppressed'}:
                    self.database.db.execute("UPDATE notifications SET status='suppressed',error='alert_not_delivered' WHERE event_id=?",(identity,))
                    continue
                if status[0]=='pending' and related not in {i for i,e in ready}:continue
            ready.append((identity,event))
            if len(ready)==6:break
        self.database.db.commit()
        return ready

    def mark(self,identities,status,error=None,retry_after=0):
        if status not in {'sent','retry','uncertain'}:raise ValueError('invalid delivery state')
        for identity in identities:
            row=self.database.db.execute('SELECT payload,attempts FROM notifications WHERE event_id=?',(identity,)).fetchone()
            if not row:continue
            attempts=row[1]+1
            final=('failed' if attempts>=5 else 'pending') if status=='retry' else status
            self.database.db.execute('UPDATE notifications SET status=?,attempts=?,last_attempt=?,error=? WHERE event_id=?',
                (final,attempts,time.time()+max(0,retry_after),error,identity))
            event=json.loads(row[0]);state=self.database.states().get(event.get('key'),{})
            if status in {'sent','uncertain'} and state.get('pending',{}).get('time')==event.get('time'):
                state.pop('pending',None)
                if status=='sent':state['last_sent']=time.time()
                else:state['delivery_uncertain']=True
                self.database.set_state(event['key'],state)
        self.database.db.commit()
