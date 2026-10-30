"""Authenticated application control plane; infrastructure remains read-only."""
import asyncio
from collections import deque
import concurrent.futures
from contextlib import closing
import json
import hashlib
import re
import secrets
import sqlite3
import threading
import time
from app.dashboard import models
from app.dashboard.platform import Platform,Forbidden,Missing
from app.dashboard.credentials import CredentialVault,CredentialVaultUnavailable
from app.monitoring.service_probe import probe
from app.logging_config import redact,request_id

class PlatformAPI:
    def __init__(self, owner, monitor=None, agent=None, loop=None):
        self.owner,self.monitor,self.agent,self.loop=owner,monitor,agent,loop
        self.store=Platform(owner.settings.data_dir,owner.settings)
        self.credentials=CredentialVault(self.store)
        self.device_backups=getattr(monitor,'device_backups',None)
        self.jobs={};self.job_lock=threading.Lock();self.questions=deque();self.probes=deque()
        from app.dashboard.assistant_history import AssistantHistory
        self.assistant_history=AssistantHistory(self.store)

    @staticmethod
    def permitted(session, roles):
        if 'Administrator' in roles:roles=tuple(roles)+('Super Administrator',)
        if not session or session['user']['role'] not in roles:raise Forbidden()
        return session['user']['username']

    def get(self,path,query,session):
        if path=='/api/platform/assistant-history':
            if set(query)-{'before'} or any(len(v)!=1 for v in query.values()):raise ValueError('invalid_query')
            before=query.get('before',[None])[0]
            if before and not re.fullmatch(r'job_[a-f0-9]{24}',before):raise ValueError('invalid_query')
            actor=self.permitted(session,models.ROLES)
            return self.assistant_history.page(actor,before)
        if path=='/api/platform/access':
            from app.dashboard.access import authorize
            return authorize(self.store,session,query)
        credential_match=re.fullmatch(r'/api/platform/credentials/(integration|inventory|device)/([a-z0-9_]{1,80})',path)
        if credential_match:
            if query:raise ValueError('invalid_query')
            from app.dashboard.permissions import require
            actor=require(session,'credentials.read')
            target_type,identity=credential_match.groups()
            self.require_credential_target(target_type,identity)
            return self.credentials.read(target_type,identity,actor)
        if path=='/api/platform/monitoring/enrollment':
            actor=self.permitted(session,models.ROLES)
            if query:raise ValueError('invalid_query')
            from app.dashboard.permissions import permissions
            import os
            return {'permissions':sorted(permissions(session)),
                'routeros_sections':[{'id':key,'label':spec.title} for key,spec in __import__('app.monitoring.mikrotik_catalog',fromlist=['SECTIONS']).SECTIONS.items()],
                'credential_profiles':[{'id':'routeros-default','kind':'routeros','host':os.getenv('MIKROTIK_HOST','192.168.20.1'),'configured':bool(os.getenv('MIKROTIK_USER') and os.getenv('MIKROTIK_PASSWORD'))},
                    {'id':'proxmox-default','kind':'proxmox','host':os.getenv('PROXMOX_HOST','192.168.20.200'),'configured':bool(os.getenv('PROXMOX_TOKEN_ID') and os.getenv('PROXMOX_TOKEN_SECRET'))}],
                'inventory':[{**r,**self.inventory_status(r)} for r in self.store.list('inventory')]}
        if path=='/api/platform/application-logs':
            from app.dashboard.permissions import require
            require(session,'incidents.manage')
            from app.storage.application_logs import page
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:return page(db,query)
        if path=='/api/platform/report':
            from app.dashboard.reports import report
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                return report(db,query,self.store.targets(),self.owner.settings.poll_interval)
        if path=='/api/platform/audit':
            from app.dashboard.permissions import require
            require(session,'audit.read');return self.store.audit_page(query)
        if path=='/api/platform/device-backups':
            if query:raise ValueError('invalid_query')
            from app.dashboard.permissions import require
            require(session,'backup.read')
            if not self.device_backups:raise ValueError('backup_unavailable')
            return self.device_backups.catalog()
        if path.startswith('/api/platform/device-backups/'):
            from app.dashboard.permissions import require
            actor=require(session,'backup.read')
            if not self.device_backups:raise ValueError('backup_unavailable')
            parts=path.removeprefix('/api/platform/device-backups/').split('/')
            if len(parts)==2 and parts[0]=='runs' and re.fullmatch(r'run_[a-f0-9]{24}',parts[1]):
                if query:raise ValueError('invalid_query')
                return self.device_backups.run_status(parts[1])
            if len(parts)==2 and parts[0]=='compare':
                if set(query)-{'left','right'} or any(len(v)!=1 for v in query.values()):raise ValueError('invalid_query')
                return self.device_backups.compare(query.get('left',[''])[0],query.get('right',[''])[0],actor)
            if len(parts)==1 and re.fullmatch(r'backup_[a-f0-9]{24}',parts[0]):
                if query:raise ValueError('invalid_query')
                return self.device_backups.download(parts[0],actor)
            raise Missing()
        if query:raise ValueError('invalid_query')
        if path=='/api/platform':
            from app.dashboard.permissions import permissions
            return {'capabilities':{'manage':bool(session and session['user']['role'] in {'Administrator','Super Administrator'}),
                'acknowledge':'incidents.manage' in permissions(session),'assistant':bool(self.agent and self.loop),
                'device_enrollment':True,'discovery':'cached-observations','embedding':'header-checked-sandbox','device_actions':'native-gui-only','permissions':sorted(permissions(session)),
                'inventory_targets':{r['id']:self.store.inventory_target(r) for r in self.store.list('inventory')}},
                'settings':self.store.get_settings(),'integrations':self.catalog(),'topologies':self.store.list('topologies'),
                'inventory':self.store.list('inventory'),'maintenance':self.store.list('maintenance'),'server_time':time.time()}
        if path=='/api/platform/settings':return self.store.get_settings()
        if path=='/api/platform/export':
            self.permitted(session,('Administrator',));return self.store.export_config()
        if path=='/api/platform/users':
            self.permitted(session,('Administrator',));return {'users':[{'username':'nms','name':'NMS Operator','role':'Read-only operator','enabled':True,'revision':0}]+self.store.users()}
        if path.startswith('/api/platform/jobs/'):
            identity=path.rsplit('/',1)[-1]
            actor=self.permitted(session,models.ROLES)
            with self.job_lock:
                job=self.jobs.get(identity)
                if not job:return self.assistant_history.get(actor,identity)
                if job['owner']!=actor:raise Missing()
                return {k:v for k,v in job.items() if k!='owner'}
        for collection in models.COLLECTIONS:
            base='/api/platform/'+collection
            if path==base:return {'items':self.catalog() if collection=='integrations' else self.store.list(collection)}
            if path.startswith(base+'/'):
                item=self.store.get(collection,path.removeprefix(base+'/'))
                if not item:raise Missing()
                return {'item':item}
        raise Missing()

    def catalog(self):
        # Link the configured launcher to an existing collector. No network I/O here.
        items=self.store.list('integrations')
        with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
            for item in items:
                target=item['collector'] or ('service_'+item['id'] if item['monitor_enabled'] else '')
                row=db.execute('SELECT ts,payload FROM checks WHERE target=? ORDER BY id DESC LIMIT 1',(target,)).fetchone() if target else None
                item['monitor_target']=target
                item['health']=None
                if row:
                    from app.dashboard.projection import check
                    clean=check(json.loads(row[1]),row[0],time.time(),max(self.owner.settings.poll_interval,item['poll_interval']))
                    item['health']={k:clean.get(k) for k in ('status','reported_status','error','sample_epoch','stale','stale_after_seconds','read_state','embedding_supported')}
                    if item['monitor_enabled'] and clean.get('configuration_hash')!=hashlib.sha256(item['url'].encode()).hexdigest():item['health'].update(status='UNKNOWN',error='configuration_changed',stale=True)
                item['capabilities']=['launcher']+(['shared-collector'] if item['collector'] else ['http-observation'] if item['monitor_enabled'] else [])
        return items

    def post(self,path,body,session):
        if path=='/api/platform/topology-verify':
            from app.dashboard.permissions import require
            from app.dashboard.projection import check
            from app.dashboard.topology_verification import verify
            actor=require(session,'monitor.read')
            models.fields(body,('value',),('value',))
            graph=self.store.validate('topologies',body['value'])
            now=time.time()
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                rows=db.execute('SELECT target,ts,payload FROM checks WHERE id IN (SELECT MAX(id) FROM checks GROUP BY target)').fetchall()
            intervals={self.store.inventory_target(i):i['interval'] for i in self.store.list('inventory')}
            samples={target:check(json.loads(payload),ts,now,intervals.get(target,self.owner.settings.poll_interval)) for target,ts,payload in rows}
            value=verify(graph,self.store,samples,now)
            self.store.log(actor,'topology.verify','draft',f"nodes:{len(graph['nodes'])};links:{len(graph['links'])};verified:{value['summary']['verified']}")
            return value
        credential_match=re.fullmatch(r'/api/platform/credentials/(integration|inventory|device)/([a-z0-9_]{1,80})',path)
        if credential_match:
            from app.dashboard.permissions import require
            actor=require(session,'credentials.manage')
            target_type,identity=credential_match.groups()
            self.require_credential_target(target_type,identity)
            models.fields(body,('credentials',),('credentials',))
            return self.credentials.save(target_type,identity,body['credentials'],actor)
        if path=='/api/platform/monitoring/routeros/read':return self.read_router(body,session)
        backup_match=re.fullmatch(r'/api/platform/device-backups/(inv_[a-f0-9]{24})/(run|policy)',path)
        if backup_match:
            from app.dashboard.permissions import require
            actor=require(session,'backup.manage')
            if not self.device_backups:raise ValueError('backup_unavailable')
            identity,action=backup_match.groups()
            if action=='run':
                if body:raise ValueError('invalid_fields')
                return self.device_backups.start_manual(identity,actor,self.loop)
            return self.device_backups.save_policy(identity,body,actor)
        restore_match=re.fullmatch(r'/api/platform/device-backups/(backup_[a-f0-9]{24})/restore',path)
        if restore_match:
            from app.dashboard.permissions import require
            actor=require(session,'backup.manage')
            models.fields(body,('confirmation',),('confirmation',))
            if not self.device_backups:raise ValueError('backup_unavailable')
            return self.device_backups.prepare_restore(restore_match.group(1),body['confirmation'],actor)
        if re.fullmatch(r'/api/platform/inventory/inv_[a-f0-9]{24}/test',path):return self.test_inventory(path.split('/')[-2],body,session)
        if body.get('detach_topology'):
            from app.dashboard.permissions import require
            require(session,'topology.manage')
        if body.get('authorize_host'):
            from app.dashboard.permissions import require
            require(session,'config.manage')
        if path.startswith('/api/platform/inventory') or path.startswith('/api/platform/topologies'):
            from app.dashboard.permissions import require
            require(session,'inventory.manage' if path.startswith('/api/platform/inventory') else 'topology.manage')
            session={'user':{**session['user'],'role':'Administrator'}}
        if path=='/api/platform/ask':
            self.permitted(session,models.ROLES)
            models.fields(body,('question','request_id'),('question',))
            key=body.get('request_id')
            if key is not None and (not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{32}',key)):raise ValueError('invalid_request_id')
            return self.ask(models.text(body['question'],1,2000),session['user']['username'],key)
        if path.startswith('/api/platform/acknowledge/'):
            from app.dashboard.permissions import require
            actor=require(session,'incidents.manage')
            models.fields(body,('note',),('note',));identity=path.rsplit('/',1)[-1]
            if not re.fullmatch(r'inc_(event_[1-9]\d{0,14}|state_[a-f0-9]{20})',identity):raise ValueError('invalid_incident')
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                if not db.execute('SELECT 1 FROM incidents WHERE id=?',(identity,)).fetchone():raise Missing()
            return self.store.acknowledge(identity,body['note'],actor)
        actor=self.permitted(session,('Administrator',))
        if path=='/api/platform/settings':return self.store.save_settings(body,actor)
        if path=='/api/platform/restore':return self.store.restore(body,actor)
        if path=='/api/platform/users':return self.store.save_user(body,actor)
        if path=='/api/platform/inventory/import':
            models.fields(body,('devices',),('devices',))
            if not isinstance(body['devices'],list) or not 1<=len(body['devices'])<=200 or any(not isinstance(v,dict) for v in body['devices']):raise ValueError('invalid_import')
            # Validate the entire batch before the atomic insert.
            values=[self.store.validate('inventory',{k:v for k,v in r.items() if k!='id'}) for r in body['devices']]
            with self.store.db() as db:
                hosts={r['host'] for r in self.store.list('inventory')}
                for value in values:
                    if value['host'] in hosts:raise ValueError('duplicate_host')
                    hosts.add(value['host'])
                if len(hosts)>200:raise ValueError('collection_full')
                now=time.time()
                for value in values:db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)',('inventory','inv_'+secrets.token_hex(12),1,json.dumps(value),now,now))
                self.store.audit(db,actor,'inventory.import','inventory',f'count:{len(values)}')
            return {'ok':True,'count':len(values)}
        for collection in models.COLLECTIONS:
            base='/api/platform/'+collection
            if path==base:
                if collection=='inventory':self.validate_monitor_categories(body.get('value'))
                return self.store.save(collection,body,actor)
            if path.startswith(base+'/'):
                parts=path.removeprefix(base+'/').split('/')
                identity=parts[0]
                if not re.fullmatch(r'[a-z0-9_]{1,80}',identity):raise ValueError('invalid_id')
                if len(parts)==1:
                    if collection=='inventory':self.validate_monitor_categories(body.get('value'),identity)
                    return self.store.save(collection,body,actor,identity)
                if len(parts)==2 and parts[1]=='delete':
                    models.fields(body,('revision','detach_topology'),('revision',));return self.store.remove(collection,identity,body['revision'],actor,detach=models.boolean(body.get('detach_topology',False)))
                if len(parts)==2 and parts[1]=='test' and collection=='integrations':
                    if body:raise ValueError('invalid_fields')
                    return self.test_service(identity,actor)
        raise Missing()

    def require_credential_target(self,target_type,identity):
        if target_type=='integration':
            valid=bool(re.fullmatch(r'(?:int_[a-f0-9]{24}|svc_[a-f0-9]{20})',identity))
            exists=valid and self.store.get('integrations',identity) is not None
        elif target_type=='inventory':
            valid=bool(re.fullmatch(r'inv_[a-f0-9]{24}',identity))
            exists=valid and self.store.get('inventory',identity) is not None
        else:
            valid=bool(re.fullmatch(r'device_[a-f0-9]{12}',identity))
            exists=False
            if valid:
                try:
                    with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                        checks=self.owner.snapshot(db)['checks']
                    exists=identity in {device['id'] for device in self.owner.devices(checks)}
                except sqlite3.Error:
                    raise CredentialVaultUnavailable('credential_vault_unavailable') from None
        if not exists:raise Missing()

    def read_router(self,body,session):
        from app.dashboard.permissions import require
        from app.monitoring.mikrotik_catalog import SECTIONS
        actor=require(session,'monitor.read');models.fields(body,('section','offset'),('section',))
        section=body['section'];offset=models.integer(body.get('offset',0),0,499)
        if not isinstance(section,str) or section not in SECTIONS or not self.monitor or not self.loop:raise ValueError('section_unavailable')
        now=time.time()
        with self.job_lock:
            self.jobs={k:v for k,v in self.jobs.items() if now-v['created_at']<600}
            if any(j['state']=='running' and j['owner']==actor for j in self.jobs.values()):raise ValueError('assistant_busy')
            while self.probes and now-self.probes[0]>60:self.probes.popleft()
            if len(self.probes)>=5:raise ValueError('probe_rate_limit')
            self.probes.append(now);identity='job_'+secrets.token_hex(12)
            self.jobs[identity]={'id':identity,'owner':actor,'state':'running','created_at':now}
        self.store.log(actor,'device.read',section)
        future=asyncio.run_coroutine_threadsafe(self.monitor.router.query(section,offset=offset,limit=10),self.loop)
        def done(f):
            try:value={'state':'complete','result':f.result()}
            except BaseException:value={'state':'failed','error':'collector_failed'}
            with self.job_lock:
                if identity in self.jobs:self.jobs[identity].update(value)
        future.add_done_callback(done)
        return {'id':identity,'state':'running'}

    def inventory_status(self,item):
        from app.dashboard.device_summary import summarize
        from app.dashboard.projection import check
        target=self.store.inventory_target(item)
        targets=[target] if target else []
        source=self.store.source(identity=item['id'])
        if source and source[0]==item['host']:
            import os
            from urllib.parse import urlsplit
            for key in json.loads(source[3]):
                spec=self.owner.settings.targets.get(key,{})
                host=spec.get('host') or urlsplit(spec.get('url','')).hostname
                if key.startswith('mikrotik_') or key in {'wireguard','network_traffic'}:host=os.getenv('MIKROTIK_HOST','192.168.20.1')
                elif key=='proxmox_resources':host=os.getenv('PROXMOX_HOST','192.168.20.200')
                elif key in {'debian','docker'}:host=self.owner.settings.targets.get('debian_ssh',{}).get('host')
                if host==item['host']:targets.append(key)
        targets=list(dict.fromkeys(targets))
        samples={}
        if targets and item['enabled']:
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                by_target={}
                for key in targets:
                    row=db.execute('SELECT ts,payload FROM checks WHERE target=? ORDER BY id DESC LIMIT 1',(key,)).fetchone()
                    if row:by_target[key]=row
            for key in targets:
                if key in by_target:
                    ts,payload=by_target[key]
                    samples[key]=check(json.loads(payload),ts,time.time(),item['interval'] if key==target else self.owner.settings.poll_interval)
        return summarize(item,target,samples)

    def validate_monitor_categories(self,value,identity=None):
        if not isinstance(value,dict) or 'monitor_categories' not in value or not identity:return
        existing=self.store.get('inventory',identity)
        if not existing:return
        if value.get('monitor_method')!=existing.get('monitor_method') or value.get('host')!=existing['host']:return
        if value.get('monitor_categories')==existing.get('monitor_categories'):return
        state=self.inventory_status(existing)
        if not state['collectors']:return
        available=set(state['supported_categories'])
        if any(category not in available for category in value['monitor_categories']):raise ValueError('unsupported_monitor_category')

    def test_inventory(self,identity,body,session):
        from app.dashboard.permissions import require
        actor=require(session,'inventory.manage')
        if body:raise ValueError('invalid_fields')
        item=self.store.get('inventory',identity)
        if not item:raise Missing()
        target=self.store.inventory_target(item)
        if not target:return {'status':'UNKNOWN','error':'adapter_not_configured','source':'inventory'}
        if not self.monitor or not self.loop:raise ValueError('monitor_unavailable')
        with self.job_lock:
            now=time.time()
            while self.probes and now-self.probes[0]>60:self.probes.popleft()
            if len(self.probes)>=5:raise ValueError('probe_rate_limit')
            self.probes.append(now)
        self.store.log(actor,'inventory.test',identity)
        async def test():
            if target.startswith('inventory_') and not item['enabled']:
                from app.monitoring.inventory import collect
                try:creds=self.credentials.collector_credentials('inventory',item['id']) if item.get('monitor_method') in {'snmp','ssh'} else None
                except CredentialVaultUnavailable:return {'target':target,'status':'UNKNOWN','error':'credential_vault_unavailable'}
                previous=self.monitor.database.history(target,1)
                return await collect(item,self.store.get_settings()['value']['allowed_hosts'],creds,previous[0] if previous else None)
            return await self.monitor.check(target,force=True)
        future=asyncio.run_coroutine_threadsafe(test(),self.loop)
        try:value=future.result(timeout=35 if item.get('follow_dhcp') or item.get('monitor_method') in {'snmp','ssh'} else 6)
        except concurrent.futures.TimeoutError:
            future.cancel();return {'status':'UNKNOWN','error':'test_timeout'}
        from app.dashboard.projection import check
        clean=check(value,time.time(),time.time(),item['interval'])
        from app.monitoring.device_capabilities import detect,telemetry
        return {**clean,'supported_categories':detect(clean),'telemetry':telemetry({**clean,'sample_epoch':clean.get('sample_epoch')})}

    def test_service(self,identity,actor):
        item=self.store.get('integrations',identity)
        if not item:raise Missing()
        if not item['enabled']:raise ValueError('integration_disabled')
        with self.job_lock:
            now=time.time()
            while self.probes and now-self.probes[0]>60:self.probes.popleft()
            if len(self.probes)>=5:raise ValueError('probe_rate_limit')
            self.probes.append(now)
        self.store.log(actor,'integration.test',identity)
        if item['collector']:
            with closing(sqlite3.connect(self.store.path.parent/'nms.sqlite3',timeout=3)) as db:
                row=db.execute('SELECT ts,payload FROM checks WHERE target=? ORDER BY id DESC LIMIT 1',(item['collector'],)).fetchone()
            if not row:return {'status':'UNKNOWN','error':'no_sample','source':'shared-monitoring-cache'}
            from app.dashboard.projection import check
            value=check(json.loads(row[1]),row[0],time.time(),self.owner.settings.poll_interval)
            return {'status':value['status'],'error':value.get('error'),'sample_epoch':value['sample_epoch'],'stale':value['stale'],'source':'shared-monitoring-cache','scope':'Existing collector sample; not a new device request'}
        value=asyncio.run(probe('service_'+identity,item['url'],self.store.get_settings()['value']['allowed_hosts']))
        return {k:value[k] for k in ('status','timestamp','method','error','http_status','latency_ms','scope') if k in value}

    def ask(self,question,actor,request_key=None):
        now=time.time()
        with self.job_lock:
            if request_key:
                existing=self.assistant_history.find(actor,request_key,question)
                if existing:return existing
            if not self.agent or not self.loop:raise ValueError('assistant_unavailable')
            self.jobs={k:v for k,v in self.jobs.items() if now-v['created_at']<600}
            while self.questions and now-self.questions[0]>60:self.questions.popleft()
            if len(self.questions)>=3 or any(j['state']=='running' for j in self.jobs.values()):raise ValueError('assistant_busy')
            self.questions.append(now);identity='job_'+secrets.token_hex(12)
            self.assistant_history.start(actor,identity,request_key or identity,question,now)
            self.jobs[identity]={'id':identity,'owner':actor,'state':'running','created_at':now}
        self.store.log(actor,'assistant.ask',identity)  # Audit stores metadata; private conversation history is owner-scoped.
        async def answer():
            token=request_id.set(identity)
            try:return await self.agent.run(question)
            finally:request_id.reset(token)
        future=asyncio.run_coroutine_threadsafe(answer(),self.loop)
        def persist_result(f):
            try:answer=redact(str(f.result())).encode('utf-8')[:30000].decode('utf-8','ignore');update={'state':'complete','answer':answer}
            except BaseException:update={'state':'failed','error':'ai_unavailable'}
            self.assistant_history.finish(identity,update)
            with self.job_lock:
                if identity in self.jobs:self.jobs[identity].update(update,finished_at=time.time())
        future.add_done_callback(lambda f:threading.Thread(target=persist_result,args=(f,),daemon=True,name='nms-assistant-history').start())
        return {'id':identity,'state':'running','created_at':now}
