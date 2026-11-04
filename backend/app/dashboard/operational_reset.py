"""Prepare verified backups; offline reset requires a separately supplied approval.

No reset route is exposed by the web API. CLI apply is for a later, explicitly
approved maintenance window with the NMS backend stopped.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
import time

WIPE={
    'platform.sqlite3':('objects','inventory_sources','credential_records','device_discoveries','portal_checks','annotations','platform_requests','assistant_history','change_plans','device_backup_policies'),
    'nms.sqlite3':('checks','alert_state','events','notifications','incidents','incident_events','metadata','application_logs'),
    'dashboard-auth.sqlite3':('sessions',),
}
PRESERVE=['source code and database schema','all accounts, roles and permissions','platform_settings and allowed-host security policy',
    'Telegram token/settings/account bindings','audit and authentication metadata','device_backups and device_backup_runs',
    'device-config-backups files','previous archives and database/configuration backups','core application environment and secrets']

def checksum(path):
    digest=hashlib.sha256()
    with open(path,'rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def plan(directory):
    root=Path(directory).resolve();files={}
    for filename,tables in WIPE.items():
        path=root/filename
        if not path.is_file():continue
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as db:
            known={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            files[filename]={table:db.execute('SELECT COUNT(*) FROM "'+table+'"').fetchone()[0] for table in tables if table in known}
    return {'databases':files,'preserved':PRESERVE,'reset_executed':False,'requires_explicit_approval':True}

def prepare(directory,destination):
    root=Path(directory).resolve();backup=Path(destination).resolve()
    if backup==root or backup.exists():raise ValueError('backup_destination_must_be_new')
    backup.mkdir(parents=True,mode=0o700)
    manifest={'schema':1,'created_at':time.time(),'source':str(root),'plan':plan(root),'files':{},'id':secrets.token_hex(16)}
    for path in sorted(root.glob('*.sqlite3')):
        if path.is_symlink():raise ValueError('database_symlink_refused')
        output=backup/path.name
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=10)) as source,closing(sqlite3.connect(output)) as target:
            # Pin a WAL read snapshot: continuous polling must not restart a
            # multi-step backup on every committed monitoring sample.
            source.execute('BEGIN')
            source.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
            source.backup(target,pages=512,sleep=.01)
            source.rollback()
            integrity=target.execute('PRAGMA integrity_check').fetchall()
            if integrity!=[('ok',)]:raise ValueError('backup_integrity_failed')
        output.chmod(0o600);manifest['files'][path.name]={'sha256':checksum(output),'bytes':output.stat().st_size,'sqlite_integrity':'ok'}
    # Copy every supporting operational file, including encrypted device backups,
    # while deliberately excluding prior backup trees from recursive inclusion.
    excluded={'operational-reset','backups','instance.lock','health.json'}
    for path in root.iterdir():
        if path.name in excluded or path.name.endswith(('.sqlite3','-wal','-shm')):continue
        if path.is_symlink():raise ValueError('backup_symlink_refused')
        output=backup/'support'/path.name
        if path.is_dir():shutil.copytree(path,output)
        elif path.is_file():output.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,output)
    for path in sorted((backup/'support').rglob('*')) if (backup/'support').exists() else []:
        if path.is_file():path.chmod(0o600);manifest['files'][path.relative_to(backup).as_posix()]={'sha256':checksum(path),'bytes':path.stat().st_size}
    encoded=json.dumps(manifest,sort_keys=True,ensure_ascii=False,indent=2)
    (backup/'manifest.json').write_text(encoded,encoding='utf-8');(backup/'manifest.json').chmod(0o600)
    verify(backup)
    return manifest

def verify(backup):
    backup=Path(backup).resolve();manifest=json.loads((backup/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['files'].items():
        path=(backup/name).resolve()
        if not path.is_relative_to(backup) or not path.is_file() or checksum(path)!=expected['sha256']:raise ValueError('backup_integrity_failed')
        if name.endswith('.sqlite3'):
            with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('backup_integrity_failed')
    return manifest

def apply(directory,backup,confirmation):
    root=Path(directory).resolve();manifest=verify(backup)
    if confirmation!='RESET THEAZ NMS '+manifest['id']:raise ValueError('explicit_reset_confirmation_required')
    if str(root)!=manifest['source']:raise ValueError('reset_source_mismatch')
    if time.time()-manifest['created_at']>3600:raise ValueError('fresh_backup_required')
    # Exclusive singleton lock proves that the live scheduler cannot recreate data.
    import fcntl
    with open(root/'instance.lock','a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('stop_nms_backend_first') from None
        if plan(root)['databases']!=manifest['plan']['databases']:raise ValueError('fresh_backup_required')
        try:
            for filename,tables in manifest['plan']['databases'].items():
                with closing(sqlite3.connect(root/filename)) as db:
                    with db:
                        if filename=='platform.sqlite3' and db.execute("SELECT 1 FROM sqlite_master WHERE name='device_backups'").fetchone():
                            db.execute('CREATE TABLE IF NOT EXISTS device_backup_inventory(id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
                            for identity,payload in db.execute("SELECT id,payload FROM objects WHERE collection='inventory' AND id IN (SELECT inventory_id FROM device_backups)").fetchall():
                                value=json.loads(payload);safe={k:value[k] for k in ('name','host','type','vendor','model') if k in value};safe['id']=identity
                                db.execute('INSERT OR REPLACE INTO device_backup_inventory VALUES(?,?)',(identity,json.dumps(safe)))
                        for table in tables:db.execute('DELETE FROM "'+table+'"')
                        if filename=='platform.sqlite3':
                            db.execute("DELETE FROM platform_metadata WHERE key LIKE 'optional_api:%'")
                            db.execute("INSERT OR REPLACE INTO platform_metadata VALUES('inventory_authoritative','1')")
                            db.execute("INSERT OR REPLACE INTO platform_metadata VALUES('seeded','1')")
                            db.execute("INSERT OR REPLACE INTO platform_metadata VALUES('operational_generation',?)",(manifest['id'],))
                            db.execute("INSERT INTO audit(ts,actor,action,resource,detail) VALUES(?,?,?,?,?)",(time.time(),'admin:offline-reset','operational.reset','NMS',manifest['id']))
                        if db.execute('PRAGMA integrity_check').fetchall()!=[('ok',)]:raise ValueError('reset_integrity_failed')
            remaining=plan(root)
            if any(count for tables in remaining['databases'].values() for count in tables.values()):raise ValueError('reset_incomplete')
        except BaseException:
            for filename in manifest['plan']['databases']:
                with closing(sqlite3.connect(Path(backup)/filename)) as saved,closing(sqlite3.connect(root/filename)) as live:saved.backup(live)
            raise
    return {'reset_executed':True,'generation':manifest['id'],'remaining':remaining}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('plan','prepare','verify','apply'))
    parser.add_argument('--data',default=os.getenv('DATA_DIR','/data'));parser.add_argument('--backup');parser.add_argument('--confirmation')
    args=parser.parse_args()
    if args.action=='plan':value=plan(args.data)
    elif args.action=='prepare':value=prepare(args.data,args.backup)
    elif args.action=='verify':value=verify(args.backup)
    else:value=apply(args.data,args.backup,args.confirmation)
    print(json.dumps(value,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
