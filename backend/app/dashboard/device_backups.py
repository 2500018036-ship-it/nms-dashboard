"""Encrypted, versioned, read-only configuration exports for supported devices."""
import asyncio
import base64
import difflib
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.dashboard.credentials import CredentialVault
from app.dashboard.platform import Missing


class DeviceConfigBackups:
    # API responses are capped at 2 MiB; base64 JSON adds about one third.
    MAX_BYTES = 1_300_000
    SAFE_ERRORS = {'readonly_account_required','verified_api_ssl_required','permission_denied','authentication_failed',
        'timeout','connection_failed','collector_busy','empty_backup','backup_too_large','sensitive_data_detected',
        'credential_vault_unavailable','backup_unsupported','device_not_found'}

    def __init__(self, store, monitor):
        self.store, self.monitor = store, monitor
        self.root = Path(store.path).parent / 'device-config-backups'
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS device_backup_policies(
                inventory_id TEXT PRIMARY KEY,enabled INTEGER NOT NULL,interval_seconds INTEGER NOT NULL,
                retention_versions INTEGER NOT NULL,next_due REAL NOT NULL,updated REAL NOT NULL,actor TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS device_backups(
                id TEXT PRIMARY KEY,inventory_id TEXT NOT NULL,created REAL NOT NULL,sha256 TEXT NOT NULL,
                size INTEGER NOT NULL,file_name TEXT NOT NULL,format TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS device_backups_inventory_created ON device_backups(inventory_id,created DESC);
                CREATE TABLE IF NOT EXISTS device_backup_runs(
                id TEXT PRIMARY KEY,inventory_id TEXT NOT NULL,actor TEXT NOT NULL,trigger TEXT NOT NULL,
                started REAL NOT NULL,finished REAL,status TEXT NOT NULL,error TEXT,backup_id TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_backup_per_device ON device_backup_runs(inventory_id) WHERE status='RUNNING';
                CREATE INDEX IF NOT EXISTS device_backup_runs_started ON device_backup_runs(started DESC);''')
            db.execute("UPDATE device_backup_runs SET status='FAILED',finished=?,error='interrupted' WHERE status='RUNNING'", (time.time(),))
        self._futures = {}

    @staticmethod
    def _key():
        # Domain-separated key: rotating NMS_CREDENTIALS_KEY also invalidates encrypted backups.
        return hmac.new(CredentialVault._key(), b'theaz-nms:device-config-backups:v1', hashlib.sha256).digest()

    def _item(self, identity):
        if not re.fullmatch(r'inv_[a-f0-9]{24}', identity):
            raise Missing()
        item = self.store.get('inventory', identity)
        if not item:
            raise Missing()
        return item

    @staticmethod
    def _support(item):
        host = os.getenv('MIKROTIK_HOST', '192.168.20.1').strip().lower()
        if item.get('monitor_method') == 'routeros' and item.get('credential_ref') == 'routeros-default' and item.get('host','').lower() == host:
            return {'supported': True, 'adapter': 'routeros-export', 'format': 'rsc', 'reason': None}
        return {'supported': False, 'adapter': None, 'format': None,
            'reason': 'Akun/API ekspor aman belum dikonfigurasi untuk perangkat ini.'}

    def _policy(self, db, identity):
        row = db.execute('SELECT enabled,interval_seconds,retention_versions,next_due,updated,actor FROM device_backup_policies WHERE inventory_id=?',(identity,)).fetchone()
        return dict(zip(('enabled','interval_seconds','retention_versions','next_due','updated','actor'),row)) if row else {
            'enabled': False, 'interval_seconds': 86400, 'retention_versions': 30, 'next_due': None, 'updated': None, 'actor': None}

    def _versions(self, db, identity):
        rows=db.execute('SELECT id,created,sha256,size,format FROM device_backups WHERE inventory_id=? ORDER BY created DESC LIMIT 100',(identity,)).fetchall()
        return [dict(zip(('id','created_at','sha256','size_bytes','format'),row)) for row in rows]

    def catalog(self):
        devices=[]
        with self.store.db() as db:
            for item in self.store.list('inventory'):
                devices.append({'device':{k:item[k] for k in ('id','name','host','type','vendor','model') if k in item},
                    **self._support(item),'policy':self._policy(db,item['id']),'versions':self._versions(db,item['id'])})
            runs=[dict(zip(('id','inventory_id','actor','trigger','started_at','finished_at','status','error','backup_id'),row))
                for row in db.execute('SELECT id,inventory_id,actor,trigger,started,finished,status,error,backup_id FROM device_backup_runs ORDER BY started DESC LIMIT 100')]
        return {'devices':devices,'runs':runs,'restore_mode':'manual-native-gui'}

    def save_policy(self, identity, body, actor):
        item=self._item(identity)
        if not self._support(item)['supported']:
            raise ValueError('backup_unsupported')
        if not isinstance(body,dict) or set(body)!={'enabled','interval_seconds','retention_versions'} or type(body['enabled']) is not bool:
            raise ValueError('invalid_fields')
        interval=body['interval_seconds'];retention=body['retention_versions']
        if type(interval) is not int or not 3600<=interval<=30*86400 or type(retention) is not int or not 2<=retention<=100:
            raise ValueError('invalid_number')
        now=time.time();next_due=now+interval if body['enabled'] else 0
        with self.store.db() as db:
            db.execute('''INSERT INTO device_backup_policies VALUES(?,?,?,?,?,?,?) ON CONFLICT(inventory_id) DO UPDATE SET
                enabled=excluded.enabled,interval_seconds=excluded.interval_seconds,retention_versions=excluded.retention_versions,
                next_due=excluded.next_due,updated=excluded.updated,actor=excluded.actor''',
                (identity,int(body['enabled']),interval,retention,next_due,now,actor))
            self.store.audit(db,actor,'device_backup.policy',identity,f"enabled:{str(body['enabled']).lower()};interval:{interval};retention:{retention}")
            return self._policy(db,identity)

    def _new_run(self, identity, actor, trigger):
        run_id='run_'+secrets.token_hex(12);now=time.time()
        with self.store.db() as db:
            try:
                db.execute('INSERT INTO device_backup_runs(id,inventory_id,actor,trigger,started,status) VALUES(?,?,?,?,? ,\'RUNNING\')',(run_id,identity,actor,trigger,now))
            except Exception as exc:
                if 'UNIQUE' not in str(exc):raise
                row=db.execute("SELECT id FROM device_backup_runs WHERE inventory_id=? AND status='RUNNING'",(identity,)).fetchone()
                return row[0] if row else None
            return run_id

    def start_manual(self, identity, actor, loop):
        item=self._item(identity)
        if not self._support(item)['supported']:
            raise ValueError('backup_unsupported')
        if loop is None or not loop.is_running():
            raise ValueError('monitor_unavailable')
        run_id=self._new_run(identity,actor,'manual')
        if not run_id:raise ValueError('backup_busy')
        if run_id not in self._futures:
            future=asyncio.run_coroutine_threadsafe(self._execute(run_id,identity,actor),loop)
            self._futures[run_id]=future
            future.add_done_callback(lambda _:self._futures.pop(run_id,None))
        return {'id':run_id,'state':'RUNNING'}

    async def run_due(self):
        now=time.time()
        with self.store.db() as db:
            due=db.execute('SELECT inventory_id,interval_seconds FROM device_backup_policies WHERE enabled=1 AND next_due<=? ORDER BY next_due LIMIT 20',(now,)).fetchall()
            for identity,interval in due:
                db.execute('UPDATE device_backup_policies SET next_due=? WHERE inventory_id=?',(now+interval,identity))
        for identity,_ in due:
            item=self.store.get('inventory',identity)
            if not item or not self._support(item)['supported']:
                continue
            run_id=self._new_run(identity,'scheduler','scheduled')
            if run_id:
                await self._execute(run_id,identity,'scheduler')

    async def _execute(self, run_id, identity, actor):
        try:
            item=self._item(identity)
            if not self._support(item)['supported']:
                raise ValueError('backup_unsupported')
            text=await self.monitor.router.export_configuration()
            if not isinstance(text,str) or not text.strip():raise ValueError('empty_backup')
            plaintext=text.encode('utf-8')
            if len(plaintext)>self.MAX_BYTES:raise ValueError('backup_too_large')
            digest=hashlib.sha256(plaintext).hexdigest();backup_id='backup_'+secrets.token_hex(12)
            nonce=secrets.token_bytes(12);ciphertext=nonce+AESGCM(self._key()).encrypt(nonce,plaintext,(backup_id+'\0'+identity).encode())
            file_name=backup_id+'.enc';final=self.root/file_name;temporary=self.root/(file_name+'.tmp')
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(ciphertext);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,final);os.chmod(final,0o600)
            except Exception:
                temporary.unlink(missing_ok=True);raise
            now=time.time()
            try:
                with self.store.db() as db:
                    db.execute('INSERT INTO device_backups VALUES(?,?,?,?,?,?,?)',(backup_id,identity,now,digest,len(plaintext),file_name,'rsc'))
                    db.execute("UPDATE device_backup_runs SET finished=?,status='COMPLETE',backup_id=? WHERE id=?",(now,backup_id,run_id))
                    policy=self._policy(db,identity)
                    old=db.execute('SELECT id,file_name FROM device_backups WHERE inventory_id=? ORDER BY created DESC LIMIT -1 OFFSET ?',(identity,policy['retention_versions'])).fetchall()
                    if old:
                        db.executemany('DELETE FROM device_backups WHERE id=?',[(row[0],) for row in old])
                    self.store.audit(db,actor,'device_backup.created',identity,f'backup:{backup_id};bytes:{len(plaintext)};sha256:{digest}')
                for _,old_name in old:
                    (self.root/old_name).unlink(missing_ok=True)
            except Exception:
                final.unlink(missing_ok=True)
                raise
            return {'id':run_id,'state':'COMPLETE','backup_id':backup_id,'sha256':digest,'size_bytes':len(plaintext)}
        except Exception as exc:
            raw=str(exc)
            error=raw if raw in self.SAFE_ERRORS else 'backup_failed'
            now=time.time()
            with self.store.db() as db:
                db.execute("UPDATE device_backup_runs SET finished=?,status='FAILED',error=? WHERE id=?",(now,error,run_id))
                self.store.audit(db,actor,'device_backup.failed',identity,error)
            return {'id':run_id,'state':'FAILED','error':error}

    def run_status(self, identity):
        with self.store.db() as db:
            row=db.execute('SELECT id,inventory_id,actor,trigger,started,finished,status,error,backup_id FROM device_backup_runs WHERE id=?',(identity,)).fetchone()
        if not row:raise Missing()
        return dict(zip(('id','inventory_id','actor','trigger','started_at','finished_at','state','error','backup_id'),row))

    def _metadata(self, backup_id):
        if not re.fullmatch(r'backup_[a-f0-9]{24}',backup_id):raise Missing()
        with self.store.db() as db:
            row=db.execute('SELECT id,inventory_id,created,sha256,size,file_name,format FROM device_backups WHERE id=?',(backup_id,)).fetchone()
        if not row:raise Missing()
        return dict(zip(('id','inventory_id','created_at','sha256','size_bytes','file_name','format'),row))

    def _read(self, backup_id):
        item=self._metadata(backup_id);path=self.root/item['file_name']
        if path.parent!=self.root or path.suffix!='.enc':raise Missing()
        try:
            blob=path.read_bytes()
            if len(blob)<28 or len(blob)>self.MAX_BYTES+28:raise ValueError()
            plaintext=AESGCM(self._key()).decrypt(blob[:12],blob[12:],(backup_id+'\0'+item['inventory_id']).encode())
        except Exception:
            raise ValueError('backup_unavailable') from None
        if len(plaintext)!=item['size_bytes'] or hashlib.sha256(plaintext).hexdigest()!=item['sha256']:
            raise ValueError('backup_integrity_failed')
        return item,plaintext.decode('utf-8')

    def download(self, backup_id, actor):
        item,text=self._read(backup_id);device=self.store.get('inventory',item['inventory_id'])
        if not device:raise Missing()
        self.store.log(actor,'device_backup.download',backup_id,f'sha256:{item["sha256"]}')
        safe_name=re.sub(r'[^A-Za-z0-9_-]','_',device['name'])
        return {'id':backup_id,'filename':f'{safe_name}-{int(item["created_at"])}.rsc',
            'content_b64':base64.b64encode(text.encode()).decode(),'sha256':item['sha256'],'size_bytes':item['size_bytes']}

    def compare(self, left, right, actor):
        left_meta,a=self._read(left);right_meta,b=self._read(right)
        if left_meta['inventory_id']!=right_meta['inventory_id']:raise ValueError('backup_device_mismatch')
        diff='\n'.join(difflib.unified_diff(a.splitlines(),b.splitlines(),fromfile=left,tofile=right,lineterm=''))
        if len(diff)>100000:diff=diff[:100000]+'\n… perbandingan dipotong pada 100.000 karakter'
        self.store.log(actor,'device_backup.compare',right,f'left:{left};right:{right}')
        return {'device_id':left_meta['inventory_id'],'left':left,'right':right,'diff':diff,'same':left_meta['sha256']==right_meta['sha256']}

    def prepare_restore(self, backup_id, confirmation, actor):
        item,text=self._read(backup_id)
        if confirmation!='RESTORE '+backup_id:
            raise ValueError('restore_confirmation_required')
        device=self.store.get('inventory',item['inventory_id'])
        if not device:raise Missing()
        self.store.log(actor,'device_backup.restore_prepared',backup_id,f'device:{item["inventory_id"]};sha256:{item["sha256"]}')
        safe_name=re.sub(r'[^A-Za-z0-9_-]','_',device['name'])
        return {'id':backup_id,'filename':f'{safe_name}-{int(item["created_at"])}.rsc',
            'content_b64':base64.b64encode(text.encode()).decode(),'sha256':item['sha256'],'size_bytes':item['size_bytes'],
            'device':{'name':device['name'],'host':device['host']},'mode':'manual-native-gui'}
