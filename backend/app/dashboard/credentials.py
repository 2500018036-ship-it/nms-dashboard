"""Encrypted, narrowly scoped storage for device and service credentials."""
import base64
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialVaultUnavailable(OSError):
    """The vault cannot safely encrypt or decrypt data; never fall back to plaintext."""


class CredentialVault:
    VERSION = 1
    MAX_PAYLOAD_BYTES = 65536
    FIELD_TYPES = {'text', 'username', 'password', 'ssid', 'secret', 'url', 'email', 'number', 'boolean', 'textarea', 'token', 'api_key'}
    EMPTY = {'gui': {'username': '', 'password': '', 'fields': []}, 'wifi_networks': [], 'custom_fields': []}

    def __init__(self, store):
        self.store = store
        self.path = Path(store.path)
        with store.db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS credential_records(
                target_type TEXT NOT NULL,target_id TEXT NOT NULL,nonce BLOB NOT NULL,ciphertext BLOB NOT NULL,
                updated REAL NOT NULL,PRIMARY KEY(target_type,target_id))''')
        os.chmod(self.path, 0o600)

    @staticmethod
    def _key():
        value = os.environ.get('NMS_CREDENTIALS_KEY', '')
        if not value:
            raise CredentialVaultUnavailable('credential_vault_unavailable') from None
        try:
            raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
        except (ValueError, TypeError):
            raise CredentialVaultUnavailable('credential_vault_unavailable') from None
        if len(raw) != 32:
            raise CredentialVaultUnavailable('credential_vault_unavailable') from None
        return raw

    @staticmethod
    def _text(value, maximum, *, empty=True):
        if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or re.search(r'[\x00-\x1f\x7f]', value):
            raise ValueError('invalid_credentials')
        return value

    @classmethod
    def _fields(cls, values):
        if not isinstance(values, list) or len(values) > 32:
            raise ValueError('invalid_credentials')
        result, seen = [], set()
        for item in values:
            if not isinstance(item, dict) or set(item) != {'id', 'label', 'type', 'value'}:
                raise ValueError('invalid_credentials')
            identity = item['id']; kind = item['type']
            if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9_-]{1,40}', identity) or identity in seen:
                raise ValueError('invalid_credentials')
            if not isinstance(kind, str) or kind not in cls.FIELD_TYPES:
                raise ValueError('invalid_credentials')
            seen.add(identity)
            result.append({'id': identity, 'label': cls._text(item['label'], 64, empty=False), 'type': kind,
                'value': cls._text(item['value'], 4096)})
        return result

    @classmethod
    def validate(cls, body):
        if not isinstance(body, dict) or set(body) != {'gui', 'wifi_networks', 'custom_fields'}:
            raise ValueError('invalid_credentials')
        gui = body['gui']
        if not isinstance(gui, dict) or set(gui) != {'username', 'password', 'fields'}:
            raise ValueError('invalid_credentials')
        gui_fields = cls._fields(gui['fields'])
        networks = body['wifi_networks']
        if not isinstance(networks, list) or len(networks) > 32:
            raise ValueError('invalid_credentials')
        checked, seen = [], set()
        for network in networks:
            if not isinstance(network, dict) or set(network) != {'id', 'ssid', 'password'}:
                raise ValueError('invalid_credentials')
            identity = network['id']
            if not isinstance(identity, str) or not re.fullmatch(r'[a-z0-9_-]{1,40}', identity) or identity in seen:
                raise ValueError('invalid_credentials')
            seen.add(identity)
            checked.append({'id': identity, 'ssid': cls._text(network['ssid'], 32), 'password': cls._text(network['password'], 4096)})
        clean = {'gui': {'username': cls._text(gui['username'], 256), 'password': cls._text(gui['password'], 4096), 'fields': gui_fields},
            'wifi_networks': checked, 'custom_fields': cls._fields(body['custom_fields'])}
        encoded = json.dumps(clean, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > cls.MAX_PAYLOAD_BYTES:
            raise ValueError('invalid_credentials')
        return clean, encoded

    @staticmethod
    def _aad(target_type, target_id):
        return f'nms-credentials:v{CredentialVault.VERSION}:{target_type}:{target_id}'.encode('ascii')

    def save(self, target_type, target_id, body, actor):
        clean, plaintext = self.validate(body)
        key = self._key()
        nonce = secrets.token_bytes(12)
        try:
            ciphertext = AESGCM(key).encrypt(nonce, plaintext, self._aad(target_type, target_id))
        except Exception:
            raise CredentialVaultUnavailable('credential_vault_unavailable') from None
        count = len(clean['gui']['fields']) + len(clean['custom_fields']) + len(clean['wifi_networks']) + sum(bool(clean['gui'][k]) for k in ('username', 'password'))
        with self.store.db() as db:
            db.execute('''INSERT INTO credential_records(target_type,target_id,nonce,ciphertext,updated) VALUES(?,?,?,?,?)
                ON CONFLICT(target_type,target_id) DO UPDATE SET nonce=excluded.nonce,ciphertext=excluded.ciphertext,updated=excluded.updated''',
                (target_type, target_id, nonce, ciphertext, time.time()))
            self.store.audit(db, actor, 'credentials.update', f'{target_type}:{target_id}', f'fields:{count};wifi:{len(clean["wifi_networks"])}')
        return {'ok': True, 'updated_at': time.time()}

    def read(self, target_type, target_id, actor):
        key = self._key()
        with self.store.db() as db:
            row = db.execute('SELECT nonce,ciphertext,updated FROM credential_records WHERE target_type=? AND target_id=?', (target_type, target_id)).fetchone()
            if row is None:
                clean = self.EMPTY.copy()
                clean = {'gui': dict(self.EMPTY['gui']), 'wifi_networks': [], 'custom_fields': []}
                updated = None
            else:
                try:
                    plaintext = AESGCM(key).decrypt(row[0], row[1], self._aad(target_type, target_id))
                    clean = json.loads(plaintext.decode('utf-8'))
                    clean = self.validate(clean)[0]
                except (InvalidTag, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                    raise CredentialVaultUnavailable('credential_vault_unavailable') from None
                updated = row[2]
            count = len(clean['gui']['fields']) + len(clean['custom_fields']) + len(clean['wifi_networks']) + sum(bool(clean['gui'][k]) for k in ('username', 'password'))
            self.store.audit(db, actor, 'credentials.read', f'{target_type}:{target_id}', f'fields:{count};wifi:{len(clean["wifi_networks"])}')
        return {'credentials': clean, 'updated_at': updated}
