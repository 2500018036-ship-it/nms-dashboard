"""Persistent one-shot change plans. Client cannot supply arbitrary commands."""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import time
from app.dashboard import models
from app.dashboard.permissions import permissions,require
from app.dashboard.platform import Missing,Conflict
from app.management.adapters import Adapters,OPERATIONS,validate

class Management:
 def __init__(self,store,monitor=None,loop=None):
  self.store,self.loop=store,loop;self.adapters=Adapters(getattr(monitor,'router',None))
  with store.db() as db:
   db.execute('''CREATE TABLE IF NOT EXISTS change_plans(id TEXT PRIMARY KEY,actor TEXT NOT NULL,operation TEXT NOT NULL,params TEXT NOT NULL,
    observation TEXT NOT NULL,nonce_hash TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL,outcome TEXT)''')
   # Interrupted operations must never be resubmitted automatically after restart.
   db.execute("UPDATE change_plans SET state='UNKNOWN',outcome=? WHERE state='APPLYING'",(json.dumps({'error':'interrupted_verify_actual_device'}),))
   db.execute('DELETE FROM change_plans WHERE created<?',(time.time()-365*86400,))
   db.execute("INSERT OR REPLACE INTO platform_metadata(key,value) VALUES('management_schema','2')")

 def enabled(self):return os.getenv('NMS_DEVICE_WRITES_ENABLED','false').lower()=='true'

 def list(self,session):
  actor=session['user']['username'];all_users='audit.read' in permissions(session)
  with self.store.db() as db:
   rows=db.execute('SELECT id,actor,operation,created,expires,state,outcome FROM change_plans '+('' if all_users else 'WHERE actor=? ')+'ORDER BY created DESC LIMIT 100',() if all_users else (actor,)).fetchall()
  return {'items':[dict(id=r[0],actor=r[1],operation=r[2],created_at=r[3],expires_at=r[4],state='EXPIRED' if r[5]=='PREVIEW' and r[4]<time.time() else r[5],outcome=json.loads(r[6]) if r[6] else None) for r in rows],
      'writes_enabled':self.enabled(),'proxmox_monitoring_only':os.getenv('PROXMOX_MANAGEMENT_ENABLED','false').lower()!='true',
      'operations':[{**info,'id':op,'authorized':info['permission'] in permissions(session)} for op,info in OPERATIONS.items()]}

 def preview(self,body,session):
  models.fields(body,('operation','params'),('operation','params'));operation=body['operation']
  if not isinstance(operation,str) or operation not in OPERATIONS:raise ValueError('unsupported_operation')
  actor=require(session,OPERATIONS[operation]['permission']);params=validate(operation,body['params'])
  with self.store.db() as db:
   if db.execute('SELECT COUNT(*) FROM change_plans WHERE actor=? AND created>?',(actor,time.time()-60)).fetchone()[0]>=3:raise ValueError('probe_rate_limit')
  try:observation=asyncio.run(self.adapters.inspect(operation,params))
  except Exception as exc:
   import httpx
   import logging
   logging.getLogger(__name__).warning('management_preview_failed category=%s',type(exc).__name__)
   code=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None
   observation={'before':{},'allowed':False,'blocker':'authentication_failed' if code==401 else 'device_access_denied' if code==403 else 'device_connection_or_tls_failed','target':'configured-device'}
  identity='plan_'+secrets.token_hex(12);nonce=secrets.token_urlsafe(24);now=time.time()
  with self.store.db() as db:
   db.execute('INSERT INTO change_plans VALUES(?,?,?,?,?,?,?,?,?,NULL)',(identity,actor,operation,json.dumps(params),json.dumps(observation),hashlib.sha256(nonce.encode()).hexdigest(),now,now+180,'PREVIEW'))
   self.store.audit(db,actor,'change.preview',identity,operation)
  return {'id':identity,'operation':operation,'params':params,**observation,**OPERATIONS[operation],'expires_at':now+180,'confirmation':nonce,
      'allowed':observation['allowed'] and self.enabled(),'blocker':observation['blocker'] or (None if self.enabled() else 'device_write_policy_disabled')}

 def confirm(self,identity,body,session):
  models.fields(body,('confirmation','phrase'),('confirmation','phrase'))
  nonce=models.text(body['confirmation'],1,100);phrase=models.text(body['phrase'],1,80)
  if not self.loop or not self.enabled():raise ValueError('device_write_policy_disabled')
  with self.store.db() as db:
   row=db.execute('SELECT actor,operation,params,observation,nonce_hash,expires,state FROM change_plans WHERE id=?',(identity,)).fetchone()
   if not row or row[0]!=session['user']['username']:raise Missing()
   actor=require(session,OPERATIONS[row[1]]['permission'])
   if phrase!='APPLY '+identity or not hmac.compare_digest(row[4],hashlib.sha256(nonce.encode()).hexdigest()):raise ValueError('confirmation_mismatch')
   if row[5]<=time.time() or row[6]!='PREVIEW':raise Conflict()
   observation=json.loads(row[3])
   if not observation['allowed']:raise ValueError('device_permission_or_transport_blocked')
   if db.execute("SELECT 1 FROM change_plans WHERE state='APPLYING'").fetchone():raise Conflict()
   db.execute("UPDATE change_plans SET state='APPLYING' WHERE id=? AND state='PREVIEW'",(identity,))
   self.store.audit(db,actor,'change.confirm',identity,row[1])
  async def apply():
   try:outcome=await self.adapters.execute(row[1],json.loads(row[2]),observation['before'])
   except Exception:outcome={'state':'UNKNOWN','error':'operation_outcome_unverified_do_not_retry_automatically'}
   with self.store.db() as db:
    db.execute('UPDATE change_plans SET state=?,outcome=? WHERE id=?',(outcome['state'],json.dumps(outcome),identity))
    self.store.audit(db,actor,'change.result',identity,outcome['state'])
  asyncio.run_coroutine_threadsafe(apply(),self.loop)
  return {'id':identity,'state':'APPLYING'}
