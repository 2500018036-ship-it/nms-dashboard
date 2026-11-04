"""Telegram transport settings and NMS-account bindings in the platform database."""
import base64
import json
import os
import re
import secrets
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.dashboard import models
from app.dashboard.credentials import CredentialVault
from app.dashboard.platform import Conflict, Missing


class TelegramControl:
    def __init__(self,store,settings=None):
        self.store=store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS telegram_settings(
                id INTEGER PRIMARY KEY CHECK(id=1),revision INTEGER NOT NULL,enabled INTEGER NOT NULL,
                nonce BLOB,ciphertext BLOB,status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_bindings(telegram_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,enabled INTEGER NOT NULL,notify INTEGER NOT NULL,revision INTEGER NOT NULL);''')
            if not db.execute('SELECT 1 FROM telegram_settings').fetchone():
                # Legacy IDs receive the existing read-only NMS identity, never an administrator role.
                db.execute("INSERT INTO telegram_settings VALUES(1,1,?,NULL,NULL,'{}')",(bool(settings and settings.telegram_token),))
                for identity in (settings.allowed_ids if settings else ()):
                    db.execute('INSERT OR IGNORE INTO telegram_bindings VALUES(?,?,1,?,1)',(identity,'nms',identity==settings.alert_chat_id))
                store.audit(db,'system','telegram.migrate','telegram','legacy allowlist linked to read-only NMS identity')

    def token(self):
        with self.store.db() as db:row=db.execute('SELECT nonce,ciphertext FROM telegram_settings WHERE id=1').fetchone()
        if row[1]:return AESGCM(CredentialVault._key()).decrypt(row[0],row[1],b'nms-telegram-token:v1').decode()
        return os.getenv('TELEGRAM_BOT_TOKEN','')

    def user(self,identity):
        with self.store.db() as db:row=db.execute('SELECT username,enabled FROM telegram_bindings WHERE telegram_id=?',(identity,)).fetchone()
        if not row or not row[1]:return None
        return {'username':'nms','name':'NMS Operator','role':'Read-only operator','enabled':True,'revision':0} if row[0]=='nms' else self.store.user(row[0])

    def public(self):
        with self.store.db() as db:
            row=db.execute('SELECT revision,enabled,ciphertext,status FROM telegram_settings WHERE id=1').fetchone()
            bindings=[dict(zip(('telegram_id','username','enabled','notify','revision'),r)) for r in db.execute('SELECT * FROM telegram_bindings ORDER BY telegram_id')]
        for item in bindings:
            user=self.user(item['telegram_id']);item['role']=user['role'] if user else None;item['account_available']=bool(user)
        return {'revision':row[0],'enabled':bool(row[1]),'token_configured':bool(row[2] or os.getenv('TELEGRAM_BOT_TOKEN')),
            'status':json.loads(row[3]),'bindings':bindings}

    def settings(self,body,actor):
        models.fields(body,('revision','enabled','token'),('revision','enabled'))
        enabled=models.boolean(body['enabled']);revision=models.integer(body['revision'],1,10**9)
        token=body.get('token','')
        if not isinstance(token,str) or token and not re.fullmatch(r'[0-9]{6,}:[A-Za-z0-9_-]{20,}',token):raise ValueError('invalid_bot_token')
        nonce=cipher=None
        if token:
            nonce=secrets.token_bytes(12);cipher=AESGCM(CredentialVault._key()).encrypt(nonce,token.encode(),b'nms-telegram-token:v1')
        with self.store.db() as db:
            result=db.execute('UPDATE telegram_settings SET revision=revision+1,enabled=?,nonce=COALESCE(?,nonce),ciphertext=COALESCE(?,ciphertext) WHERE id=1 AND revision=?',(enabled,nonce,cipher,revision))
            if result.rowcount!=1:raise Conflict()
            self.store.audit(db,actor,'telegram.settings','telegram','token_replaced' if token else 'transport updated')
        return self.public()

    def binding(self,body,actor):
        models.fields(body,('telegram_id','username','enabled','notify','revision','confirmation','delete'),('telegram_id','confirmation'))
        identity=models.integer(body['telegram_id'],1,2**53-1)
        if body['confirmation']!=str(identity):raise ValueError('user_confirmation_required')
        remove=models.boolean(body.get('delete',False))
        with self.store.db() as db:
            previous=db.execute('SELECT revision FROM telegram_bindings WHERE telegram_id=?',(identity,)).fetchone()
            if previous and body.get('revision')!=previous[0]:raise Conflict()
            if remove:
                if not previous:raise Missing()
                db.execute('DELETE FROM telegram_bindings WHERE telegram_id=?',(identity,))
            else:
                username=models.text(body.get('username'),3,40)
                if username!='nms' and not self.store.user(username):raise ValueError('account_unavailable')
                enabled=models.boolean(body.get('enabled',True));notify=models.boolean(body.get('notify',False))
                if not previous and db.execute('SELECT count(*) FROM telegram_bindings').fetchone()[0]>=100:raise ValueError('users_full')
                db.execute('INSERT INTO telegram_bindings VALUES(?,?,?,?,1) ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username,enabled=excluded.enabled,notify=excluded.notify,revision=telegram_bindings.revision+1',(identity,username,enabled,notify))
            self.store.audit(db,actor,'telegram.binding.delete' if remove else 'telegram.binding.save',str(identity))
        return self.public()

    def recipients(self):
        with self.store.db() as db:ids=[r[0] for r in db.execute('SELECT telegram_id FROM telegram_bindings WHERE enabled=1 AND notify=1')]
        return [identity for identity in ids if self.user(identity)]

    def status(self,state,**details):
        safe={'state':state,'checked_at':time.time(),**{k:v for k,v in details.items() if k in {'username','error'}}}
        with self.store.db() as db:db.execute('UPDATE telegram_settings SET status=? WHERE id=1',(json.dumps(safe),))

    async def test(self):
        from telegram import Bot
        token=self.token()
        if not token:raise ValueError('telegram_not_configured')
        try:
            async with Bot(token=token) as bot:user=await bot.get_me(read_timeout=8,connect_timeout=5)
            self.status('verified',username=user.username);return self.public()
        except Exception:
            self.status('failed',error='telegram_connection_failed');return self.public()
