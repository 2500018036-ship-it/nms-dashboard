"""Persistent opaque dashboard sessions; no monitoring or device operations."""
from contextlib import closing
from app.dashboard.platform import Platform
import hashlib
import hmac
from http.cookies import SimpleCookie
import os
from pathlib import Path
import secrets
import sqlite3
import time

COOKIE = 'nms_session'

class Sessions:
    def __init__(self, directory, password):
        self.path = Path(directory) / 'dashboard-auth.sqlite3'
        self.password = password
        self.accounts = Platform(directory)
        self.accounts.bootstrap(os.getenv('DASHBOARD_ADMIN_PASSWORD',''))
        with closing(self.connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sessions(
                digest TEXT PRIMARY KEY, created REAL NOT NULL, seen REAL NOT NULL,
                expires REAL NOT NULL, idle INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS auth_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);''')
            columns={r[1] for r in db.execute('PRAGMA table_info(sessions)')}
            for key,definition in [('username',"TEXT NOT NULL DEFAULT 'nms'"),('user_revision','INTEGER NOT NULL DEFAULT 0')]:
                if key not in columns:db.execute('ALTER TABLE sessions ADD COLUMN '+key+' '+definition)
            fingerprint = hashlib.sha256(password.encode()).hexdigest()
            old = db.execute("SELECT value FROM auth_metadata WHERE key='credential'").fetchone()
            if not old or not hmac.compare_digest(old[0], fingerprint):
                db.execute('DELETE FROM sessions')
                db.execute("INSERT OR REPLACE INTO auth_metadata VALUES('credential',?)", (fingerprint,))
            db.commit()
        os.chmod(self.path, 0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=3)

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def token(header):
        if not header or len(header) > 2048: return ''
        try:
            cookies = SimpleCookie(); cookies.load(header)
            value = cookies[COOKIE].value
            return value if len(value) == 43 and all(c.isalnum() or c in '-_' for c in value) else ''
        except (KeyError, ValueError): return ''

    def login(self, username, password, remember=False):
        if username=='nms':
            if not hmac.compare_digest(password.encode(),self.password.encode()):return None
            user={'username':'nms','name':'NMS Operator','role':'Read-only operator'};revision=0
        else:
            user=self.accounts.authenticate(username,password)
            if not user:return None
            revision=user.pop('revision');user.pop('enabled')
        now = time.time(); duration = 7 * 86400 if remember else 8 * 3600
        idle = 86400 if remember else 1800
        token = secrets.token_urlsafe(32)
        with closing(self.connect()) as db:
            db.execute('DELETE FROM sessions WHERE expires<=? OR seen+idle<=?', (now, now))
            db.execute('INSERT INTO sessions(digest,created,seen,expires,idle,username,user_revision) VALUES(?,?,?,?,?,?,?)', (self.digest(token), now, now, now + duration, idle,username,revision))
            db.execute('DELETE FROM sessions WHERE digest IN (SELECT digest FROM sessions ORDER BY created DESC LIMIT -1 OFFSET 1000)')
            db.commit()
        self.accounts.log(username,'session.login','session')
        return token, {'user': user,
                       'expires_at': now + duration, 'idle_timeout_seconds': idle}, duration

    def read(self, token):
        if not token: return None
        now = time.time(); digest = self.digest(token)
        with closing(self.connect()) as db:
            row = db.execute('SELECT expires,seen,idle,username,user_revision FROM sessions WHERE digest=?', (digest,)).fetchone()
            if not row: return None
            expires, seen, idle, username, revision = row
            user={'username':'nms','name':'NMS Operator','role':'Read-only operator'} if username=='nms' else self.accounts.user(username)
            if not user or username!='nms' and user.get('revision')!=revision:
                db.execute('DELETE FROM sessions WHERE digest=?',(digest,));db.commit();return None
            user={k:user[k] for k in ('username','name','role')}
            if now >= expires or now >= seen + idle:
                db.execute('DELETE FROM sessions WHERE digest=?', (digest,)); db.commit(); return None
            if now - seen >= 30:
                db.execute('UPDATE sessions SET seen=? WHERE digest=?', (now, digest)); db.commit()
        return {'user': user,
                'expires_at': expires, 'idle_timeout_seconds': idle}

    def revoke(self, token):
        if token:
            with closing(self.connect()) as db:
                row=db.execute('SELECT username FROM sessions WHERE digest=?',(self.digest(token),)).fetchone()
                db.execute('DELETE FROM sessions WHERE digest=?', (self.digest(token),)); db.commit()
                if row:self.accounts.log(row[0],'session.logout','session')

    @staticmethod
    def cookie(token='', duration=None):
        value = f'{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict'
        if not token: value += '; Max-Age=0'
        elif duration is not None: value += f'; Max-Age={duration}'
        # This deployment is loopback HTTP transported through SSH. Public deployment requires HTTPS + Secure.
        return value
