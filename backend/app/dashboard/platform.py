"""NMS-owned configuration, revisions and audit. Never administers infrastructure."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from app.dashboard import models

class Conflict(Exception): pass
class Forbidden(Exception): pass
class Missing(Exception): pass

class Platform:
    def __init__(self, directory, config=None):
        self.path = Path(directory) / 'platform.sqlite3'
        self.config = config
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS objects(
                collection TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,
                created REAL NOT NULL,updated REAL NOT NULL,PRIMARY KEY(collection,id));
                CREATE TABLE IF NOT EXISTS platform_settings(id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,payload TEXT NOT NULL,applied_at REAL);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,ts REAL NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,resource TEXT NOT NULL,detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(username TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,enabled INTEGER NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS annotations(incident TEXT PRIMARY KEY,actor TEXT NOT NULL,at REAL NOT NULL,note TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS platform_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inventory_sources(host TEXT PRIMARY KEY,inventory_id TEXT NOT NULL,primary_target TEXT NOT NULL,targets TEXT NOT NULL);''')
            db.execute('''CREATE TABLE IF NOT EXISTS platform_requests(actor TEXT NOT NULL,request_key TEXT NOT NULL,
                payload_hash TEXT NOT NULL,response TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(actor,request_key))''')
            if config and not db.execute('SELECT 1 FROM platform_settings').fetchone():
                value={key:getattr(config,key) for key in ('poll_interval','network_interval','cpu_threshold','memory_threshold','storage_threshold','cooldown','retention_days','alerts')}
                value.update(identity='THEAZ NMS',timezone='Asia/Jakarta',date_format='id-ID',allowed_hosts=self.configured_hosts())
                db.execute('INSERT INTO platform_settings VALUES(1,1,?,NULL)',(json.dumps(value),))
            if config and not db.execute("SELECT 1 FROM platform_metadata WHERE key='seeded'").fetchone():
                now=time.time()
                for name,t in config.targets.items():
                    if t.get('kind')!='web':continue
                    address=t['url']
                    if name=='proxmox':address='https://'+os.getenv('PROXMOX_HOST','192.168.20.200')+':'+os.getenv('PROXMOX_PORT','8006')+'/'
                    value={'name':t['name'],'url':address,'kind':'proxmox' if name=='proxmox' else 'application','group':'Homelab','enabled':True,'monitor_enabled':False,'poll_interval':60,'collector':'proxmox_resources' if name=='proxmox' else name,'authentication':'server-configured' if name=='proxmox' else 'external'}
                    identity='svc_'+hashlib.sha256(name.encode()).hexdigest()[:20]
                    db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)',('integrations',identity,1,json.dumps(value),now,now))
                db.execute("INSERT INTO platform_metadata VALUES('seeded','1')")
        os.chmod(self.path,0o600)

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=3)
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            with connection:yield connection
        finally:connection.close()

    def sync_inventory(self):
        from app.dashboard.device_registry import sync
        sync(self)

    def source(self, **kwargs):
        from app.dashboard.device_registry import source
        return source(self, **kwargs)

    def configured_hosts(self):
        hosts={os.getenv('PROXMOX_HOST','192.168.20.200'),os.getenv('MIKROTIK_HOST','192.168.20.1')}
        for t in self.config.targets.values():
            value=t.get('host') or urlsplit(t.get('url','')).hostname
            if value:hosts.add(value)
        return sorted(hosts)

    @staticmethod
    def audit(db,actor,action,resource,detail=''):
        # Only explicit identifiers/revision summaries, never request bodies or credentials.
        db.execute('INSERT INTO audit(ts,actor,action,resource,detail) VALUES(?,?,?,?,?)',(time.time(),actor,action,resource,detail))

    def log(self,actor,action,resource,detail=''):
        with self.db() as db:self.audit(db,actor,action,resource,detail)

    def get_settings(self):
        with self.db() as db:
            row=db.execute('SELECT revision,payload,applied_at FROM platform_settings WHERE id=1').fetchone()
        return {'revision':row[0],'value':json.loads(row[1]),'applied_at':row[2]} if row else None

    def apply(self, config, mark=True):
        row=self.get_settings()
        if row:
            for key in ('poll_interval','network_interval','cpu_threshold','memory_threshold','storage_threshold','cooldown','retention_days','alerts'):setattr(config,key,row['value'][key])
            if mark:
                with self.db() as db:db.execute('UPDATE platform_settings SET applied_at=? WHERE id=1 AND revision=?',(time.time(),row['revision']))

    def save_settings(self,body,actor):
        models.fields(body,('revision','value'),('revision','value'))
        value=models.settings(body['value']);revision=models.integer(body['revision'],1,10**9)
        # Hosts referenced by existing services cannot silently disappear from policy.
        for service in self.list('integrations'):
            if urlsplit(service['url']).hostname not in value['allowed_hosts']:raise ValueError('host_in_use')
        for device in self.list('inventory'):
            if device.get('monitor_method') and device['host'] not in value['allowed_hosts']:raise ValueError('host_in_use')
        with self.db() as db:
            result=db.execute('UPDATE platform_settings SET revision=revision+1,payload=?,applied_at=NULL WHERE id=1 AND revision=?',(json.dumps(value),revision))
            if result.rowcount!=1:raise Conflict()
            self.audit(db,actor,'settings.update','settings',f'revision:{revision+1}')
        return self.get_settings()

    @staticmethod
    def item(row):
        return dict(json.loads(row[3]),id=row[1],revision=row[2],created_at=row[4],updated_at=row[5])

    def list(self,collection):
        if collection not in models.COLLECTIONS:raise ValueError('invalid_collection')
        with self.db() as db:rows=db.execute('SELECT * FROM objects WHERE collection=? ORDER BY created,id LIMIT 250',(collection,)).fetchall()
        return [self.item(r) for r in rows]

    def get(self,collection,identity):
        return next((r for r in self.list(collection) if r['id']==identity),None)

    def targets(self):
        return set(self.config.targets if self.config else ())|{'mikrotik_system','mikrotik_interfaces','mikrotik_network','mikrotik_vlan','mikrotik_routes','mikrotik_neighbors','wireguard','cisco_sf200','network_traffic','debian','docker','proxmox_resources'}|{'service_'+s['id'] for s in self.list('integrations')}|{'inventory_'+s['id'] for s in self.list('inventory')}

    def inventory_target(self,item):
        from app.monitoring.inventory import binding
        linked=binding(item)
        if linked:return linked
        method=item.get('monitor_method','')
        source=self.source(identity=item['id']) if item.get('id') else None
        if source and source[2] and self.config and method=='icmp' and self.config.targets.get(source[2],{}).get('kind')=='icmp':
            return source[2]
        if method=='http':
            for service in self.list('integrations'):
                if service['enabled'] and service['monitor_enabled'] and service['url']==item.get('monitor_url'):return 'service_'+service['id']
        for key,target in (self.config.targets.items() if self.config else ()):
            if method=='http' and target.get('kind')=='web' and target.get('url')==item.get('monitor_url'):return key
            if target.get('host')==item['host'] and target.get('kind')==method and (method=='icmp' or target.get('port')==item.get('monitor_port')):
                if method!='dns' or target.get('query')==item.get('dns_query'):return key
        return 'inventory_'+item['id'] if method in {'icmp','tcp','http','dns','snmp','ssh'} else ''

    def validate(self,collection,body,extra_hosts=()):
        cfg=self.get_settings()
        allowed=list(cfg['value']['allowed_hosts'] if cfg else ())+list(extra_hosts)
        value=models.record(collection,body,allowed,self.targets())
        if collection=='inventory':
            from app.monitoring.inventory import binding
            binding(value)  # Existing credential references must match their configured host.
        if collection=='topologies':
            valid={r['id'] for r in self.list('inventory')}
            for node in value['nodes']:
                if node['device_id'].startswith('inv_') and node['device_id'] not in valid:raise ValueError('inventory_not_found')
        return value

    def save(self,collection,body,actor,identity=None):
        models.fields(body,('revision','value','authorize_host','request_id'),('value',))
        request_key=body.get('request_id')
        if 'request_id' in body and (collection!='topologies' or not isinstance(request_key,str) or not __import__('re').fullmatch(r'[a-f0-9]{32}',request_key)):raise ValueError('invalid_request_id')
        authorize=models.boolean(body.get('authorize_host',False))
        if authorize and collection!='inventory':raise ValueError('invalid_fields')
        address=models.host(body['value'].get('host','')) if authorize else None
        value=self.validate(collection,body['value'],[address] if address else []);now=time.time()
        request_hash=hashlib.sha256(json.dumps({'id':identity,'revision':body.get('revision'),'value':value},sort_keys=True).encode()).hexdigest()
        if collection=='integrations' and value['monitor_enabled'] and value['enabled'] and sum(1 for r in self.list(collection) if r['id']!=identity and r['monitor_enabled'] and r['enabled'])>=40:raise ValueError('monitor_limit')
        if collection=='inventory':
            from app.monitoring.inventory import scheduled
            if scheduled(value) and sum(1 for r in self.list(collection) if r['id']!=identity and scheduled(r))>=20:raise ValueError('monitor_limit')
        if identity:
            revision=models.integer(body.get('revision'),1,10**9)
        else:identity=collection[:3]+'_'+secrets.token_hex(12);revision=0
        with self.db() as db:
            if request_key:
                db.execute('BEGIN IMMEDIATE')
                previous=db.execute('SELECT payload_hash,response FROM platform_requests WHERE actor=? AND request_key=?',(actor,request_key)).fetchone()
                if previous:
                    if previous[0]!=request_hash:raise Conflict()
                    return json.loads(previous[1])
            if collection=='inventory' and db.execute("SELECT 1 FROM objects WHERE collection='inventory' AND json_extract(payload,'$.host')=? AND id<>?",(value['host'],identity)).fetchone():raise Conflict()
            if revision:
                result=db.execute('UPDATE objects SET revision=revision+1,payload=?,updated=? WHERE collection=? AND id=? AND revision=?',(json.dumps(value),now,collection,identity,revision))
                if result.rowcount!=1:raise Conflict()
            else:
                if db.execute('SELECT COUNT(*) FROM objects WHERE collection=?',(collection,)).fetchone()[0]>={'topologies':20,'integrations':100,'inventory':200,'maintenance':100}[collection]:raise ValueError('collection_full')
                db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)',(collection,identity,1,json.dumps(value),now,now))
            if authorize:
                row=db.execute('SELECT payload FROM platform_settings WHERE id=1').fetchone();cfg=json.loads(row[0])
                if address not in cfg['allowed_hosts']:
                    if len(cfg['allowed_hosts'])>=100:raise ValueError('invalid_hosts')
                    cfg['allowed_hosts'].append(address)
                    db.execute('UPDATE platform_settings SET payload=?,revision=revision+1 WHERE id=1',(json.dumps(cfg),))
                    self.audit(db,actor,'settings.authorize_host',identity,address)
            self.audit(db,actor,collection+'.'+('update' if revision else 'create'),identity,f'revision:{revision+1}')
            if request_key:
                result=self.item(db.execute('SELECT * FROM objects WHERE collection=? AND id=?',(collection,identity)).fetchone())
                db.execute('INSERT INTO platform_requests VALUES(?,?,?,?,?)',(actor,request_key,request_hash,json.dumps(result),now))
                db.execute('DELETE FROM platform_requests WHERE created<?',(now-7*86400,))
                db.execute('DELETE FROM platform_requests WHERE actor=? AND request_key NOT IN (SELECT request_key FROM platform_requests WHERE actor=? ORDER BY created DESC LIMIT 1000)',(actor,actor))
        return self.get(collection,identity)

    def remove(self,collection,identity,revision,actor,detach=False):
        models.integer(revision,1,10**9)
        if collection in {'inventory','integrations'}:
            field='device_id' if collection=='inventory' else 'service_id'
            if not detach and any(n.get(field)==identity for g in self.list('topologies') for n in g['nodes']):raise ValueError('referenced_by_topology')
        with self.db() as db:
            result=db.execute('DELETE FROM objects WHERE collection=? AND id=? AND revision=?',(collection,identity,revision))
            if result.rowcount!=1:raise Conflict()
            target_type={'integrations':'integration','inventory':'inventory'}.get(collection)
            if target_type and db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credential_records'").fetchone():
                db.execute('DELETE FROM credential_records WHERE target_type=? AND target_id=?',(target_type,identity))
            if detach and collection in {'inventory','integrations'}:
                for graph in db.execute("SELECT id,payload FROM objects WHERE collection='topologies'").fetchall():
                    value=json.loads(graph[1]);removed={n['id'] for n in value['nodes'] if n.get(field)==identity}
                    if removed:
                        value['nodes']=[n for n in value['nodes'] if n['id'] not in removed]
                        value['links']=[e for e in value['links'] if e['source'] not in removed and e['target'] not in removed]
                        db.execute("UPDATE objects SET payload=?,revision=revision+1,updated=? WHERE collection='topologies' AND id=?",(json.dumps(value),time.time(),graph[0]))
                        self.audit(db,actor,'topologies.detach_device',graph[0],identity)
            self.audit(db,actor,collection+'.delete',identity)
        return {'ok':True}

    def maintenance(self,key,now=None):
        now=time.time() if now is None else now
        return any(w['enabled'] and w['start']<=now<w['end'] and (w['scope']=='*' or key==w['scope'] or key.startswith(w['scope']+':')) for w in self.list('maintenance'))

    @staticmethod
    def password(password,salt):
        return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()

    def bootstrap(self,password):
        if not password:return
        if len(password)<24:raise ValueError('admin_password_too_short')
        fingerprint=hashlib.sha256(password.encode()).hexdigest()
        with self.db() as db:
            previous=db.execute("SELECT value FROM platform_metadata WHERE key='admin_credential'").fetchone()
            if previous and hmac.compare_digest(previous[0],fingerprint):return
            salt=secrets.token_hex(16)
            db.execute("INSERT INTO accounts VALUES('admin','NMS Administrator','Administrator',1,?,?,1) ON CONFLICT(username) DO UPDATE SET salt=excluded.salt,hash=excluded.hash,enabled=1,role='Administrator',revision=accounts.revision+1",(salt,self.password(password,salt)))
            db.execute("INSERT OR REPLACE INTO platform_metadata VALUES('admin_credential',?)",(fingerprint,))
            self.audit(db,'system','user.bootstrap','admin')

    def user(self,username):
        with self.db() as db:row=db.execute('SELECT username,name,role,enabled,revision FROM accounts WHERE username=?',(username,)).fetchone()
        return dict(zip(('username','name','role','enabled','revision'),row)) if row and row[3] else None

    def authenticate(self,username,password):
        with self.db() as db:row=db.execute('SELECT salt,hash,enabled FROM accounts WHERE username=?',(username,)).fetchone()
        salt=row[0] if row else '0'*32
        valid=hmac.compare_digest(self.password(password,salt),row[1] if row else '0'*64)
        return self.user(username) if valid and row and row[2] else None

    def users(self):
        with self.db() as db:rows=db.execute('SELECT username,name,role,enabled,revision FROM accounts ORDER BY username').fetchall()
        return [dict(zip(('username','name','role','enabled','revision'),r)) for r in rows]

    def save_user(self,body,actor):
        models.fields(body,('username','name','role','enabled','password','revision'),('username','name','role','enabled'))
        username=models.text(body['username'],3,40)
        if not __import__('re').fullmatch(r'[a-z][a-z0-9_-]+',username) or username in {'nms','admin'}:raise ValueError('reserved_or_invalid_username')
        name=models.text(body['name'],1,80);role=body['role'];enabled=models.boolean(body['enabled'])
        if role not in models.ROLES:raise ValueError('invalid_role')
        password=body.get('password','')
        if not isinstance(password,str) or password and not 16<=len(password)<=128:raise ValueError('weak_password')
        with self.db() as db:
            previous=db.execute('SELECT revision FROM accounts WHERE username=?',(username,)).fetchone()
            if previous:
                if body.get('revision')!=previous[0]:raise Conflict()
                db.execute('UPDATE accounts SET name=?,role=?,enabled=?,revision=revision+1 WHERE username=?',(name,role,enabled,username))
            elif not password:raise ValueError('password_required')
            else:
                if db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]>=50:raise ValueError('users_full')
                db.execute('INSERT INTO accounts VALUES(?,?,?,?,?,?,1)',(username,name,role,enabled,'',''))
            if password:
                salt=secrets.token_hex(16);db.execute('UPDATE accounts SET salt=?,hash=? WHERE username=?',(salt,self.password(password,salt),username))
            self.audit(db,actor,'user.update' if previous else 'user.create',username)
        return {'ok':True}

    def audit_page(self,query):
        models.fields(query,('page','q'))
        if any(len(v)!=1 for v in query.values()):raise ValueError('invalid_query')
        page=models.integer(int(query.get('page',['1'])[0]),1,10000);q=models.text(query.get('q',[''])[0],0,120)
        where='WHERE instr(lower(actor||action||resource||detail),lower(?))>0'
        with self.db() as db:
            total=db.execute('SELECT COUNT(*) FROM audit '+where,(q,)).fetchone()[0]
            rows=db.execute('SELECT id,ts,actor,action,resource,detail FROM audit '+where+' ORDER BY id DESC LIMIT 25 OFFSET ?',(q,(page-1)*25)).fetchall()
        return {'items':[dict(zip(('id','time','actor','action','resource','detail'),r)) for r in rows],'total':total,'page':page,'page_size':25}

    def acknowledge(self,incident,note,actor):
        note=models.text(note,0,300)
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO annotations VALUES(?,?,?,?)',(incident,actor,time.time(),note))
            self.audit(db,actor,'incident.acknowledge',incident)
        return self.annotations().get(incident)

    def annotations(self):
        with self.db() as db:rows=db.execute('SELECT incident,actor,at,note FROM annotations ORDER BY at DESC LIMIT 1000').fetchall()
        return {r[0]:dict(actor=r[1],at=r[2],note=r[3]) for r in rows}

    def export_config(self):
        return {'schema_version':1,'settings':self.get_settings()['value'],'collections':{c:self.list(c) for c in models.COLLECTIONS},'scope':'NMS configuration only; no users, credentials or monitoring history'}

    def restore(self,body,actor):
        models.fields(body,('schema_version','settings','collections','scope'),('schema_version','settings','collections'))
        if body['schema_version']!=1:raise ValueError('unsupported_schema')
        cfg=models.settings(body['settings']);collections=body['collections']
        models.fields(collections,models.COLLECTIONS,models.COLLECTIONS)
        pending=[];seen=set();now=time.time()
        imported=collections['integrations']
        if not isinstance(imported,list) or any(not isinstance(r,dict) for r in imported):raise ValueError('invalid_records')
        targets=self.targets()|{'service_'+models.text(r.get('id'),1,80) for r in imported}
        if sum(r.get('monitor_enabled') is True and r.get('enabled') is True for r in imported)>40:raise ValueError('monitor_limit')
        old={r['id']:r['revision'] for c in models.COLLECTIONS for r in self.list(c)}
        for c,values in collections.items():
            if not isinstance(values,list) or len(values)>{'topologies':20,'integrations':100,'inventory':200,'maintenance':100}[c]:raise ValueError('too_many_records')
            for item in values:
                if not isinstance(item,dict):raise ValueError('invalid_record')
                identity=models.text(item.get('id'),1,80)
                if not __import__('re').fullmatch(r'[a-z0-9_]+',identity) or identity in seen:raise ValueError('invalid_id')
                seen.add(identity);clean={k:v for k,v in item.items() if k not in {'id','revision','created_at','updated_at'}}
                value=models.record(c,clean,cfg['allowed_hosts'],targets)
                if c=='inventory':
                    from app.monitoring.inventory import binding
                    binding(value)
                pending.append((c,identity,old.get(identity,0)+1,json.dumps(value),now,now))
        imported_ids={r[1] for r in pending if r[0]=='inventory'}
        from app.monitoring.inventory import scheduled
        if sum(scheduled(json.loads(r[3])) for r in pending if r[0]=='inventory')>20:raise ValueError('monitor_limit')
        for c,identity,revision,payload,created,updated in pending:
            if c=='topologies' and any(n['device_id'].startswith('inv_') and n['device_id'] not in imported_ids for n in json.loads(payload)['nodes']):raise ValueError('inventory_not_found')
        with self.db() as db:
            db.execute('DELETE FROM objects');db.executemany('INSERT INTO objects VALUES(?,?,?,?,?,?)',pending)
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='credential_records'").fetchone():db.execute('DELETE FROM credential_records')
            db.execute('UPDATE platform_settings SET revision=revision+1,payload=?,applied_at=NULL WHERE id=1',(json.dumps(cfg),))
            self.audit(db,actor,'config.restore','platform',f'records:{len(pending)}')
        return {'ok':True,'records':len(pending)}
