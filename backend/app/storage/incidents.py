"""Transactional projection of recorded monitoring transitions; never sends alerts."""
import hashlib
import json
import math
from app.alerts.presentation import metadata

RANK = {'UNKNOWN': 0, 'INFO': 1, 'WARNING': 2, 'CRITICAL': 3}

def stamp(value, fallback):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else fallback

def apply(db, event_id, key, kind, value, recorded):
    if kind not in {'ALERT', 'RECOVERY', 'RETIRED', 'SUPPRESSED'}: return
    if db.execute('SELECT 1 FROM incident_events WHERE event_id=?',(event_id,)).fetchone(): return
    current = db.execute("SELECT id,severity FROM incidents WHERE key=? AND status='ACTIVE'", (key,)).fetchone()
    info = metadata(value, key, kind)
    at = stamp(value.get('time'), recorded)
    first = stamp(value.get('first_seen'), at if kind == 'ALERT' else None)
    status = 'ACTIVE' if kind == 'ALERT' else 'RECOVERED' if kind == 'RECOVERY' else 'RETIRED'
    if not current:
        if kind not in {'ALERT', 'RECOVERY'}: return
        identity = 'inc_event_' + str(event_id)
        severity = info.get('severity', 'UNKNOWN') if kind == 'ALERT' else 'UNKNOWN'
        db.execute('INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (identity, key, status, first, at, at if status != 'ACTIVE' else None, severity,
             event_id if kind == 'ALERT' else None, event_id, info.get('device') or key.split(':', 1)[0],
             info.get('title') or key, int(kind != 'ALERT')))
    else:
        identity, severity = current
        if kind == 'ALERT' and RANK.get(info.get('severity'), 0) > RANK.get(severity, 0): severity = info['severity']
        db.execute('UPDATE incidents SET status=?,updated_at=?,resolved_at=?,severity=?,latest_event_id=? WHERE id=?',
            (status, at, at if status != 'ACTIVE' else None, severity, event_id, identity))
    db.execute('INSERT OR IGNORE INTO incident_events VALUES(?,?)', (event_id, identity))

def initialize(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY,key TEXT NOT NULL,status TEXT NOT NULL,
          first_seen REAL,updated_at REAL NOT NULL,resolved_at REAL,severity TEXT NOT NULL,
          opening_event_id INTEGER,latest_event_id INTEGER,device TEXT NOT NULL,title TEXT NOT NULL,partial_history INTEGER NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS incident_one_active ON incidents(key) WHERE status='ACTIVE';
        CREATE INDEX IF NOT EXISTS incidents_updated ON incidents(updated_at DESC,id);
        CREATE TABLE IF NOT EXISTS incident_events(event_id INTEGER PRIMARY KEY,incident_id TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS incident_event_identity ON incident_events(incident_id,event_id);
        CREATE INDEX IF NOT EXISTS events_key_id ON events(key,id);
        CREATE INDEX IF NOT EXISTS events_ts_id ON events(ts,id);
        CREATE INDEX IF NOT EXISTS checks_ts_id ON checks(ts,id);
    ''')
    initialized = db.execute("SELECT 1 FROM metadata WHERE key='incident_projection_v1'").fetchone()
    stored = db.execute("SELECT value FROM metadata WHERE key='incident_projection_cursor'").fetchone()
    cursor = int(stored[0]) if initialized and stored else 0
    # Replay existing history without adding events or touching the delivery cursor/outbox.
    for identity, recorded, key, kind, payload in db.execute('SELECT id,ts,key,kind,payload FROM events WHERE id>? ORDER BY id',(cursor,)).fetchall():
        apply(db, identity, key, kind, json.loads(payload), recorded)
        cursor = identity
    for key, payload in db.execute('SELECT key,payload FROM alert_state').fetchall():
        state = json.loads(payload)
        current = db.execute("SELECT id FROM incidents WHERE key=? AND status='ACTIVE'", (key,)).fetchone()
        if state.get('active') and not current:
            first = stamp(state.get('first_seen'), None)
            identity = 'inc_state_' + hashlib.sha256((key + ':' + str(first)).encode()).hexdigest()[:20]
            info = metadata({'value': state.get('last_value', {})}, key, 'ALERT')
            db.execute('INSERT OR IGNORE INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,key,'ACTIVE',first,stamp(state.get('updated_at'), first or 0),None,info['severity'],
                 None,None,info['device'],info['title'],1))
        elif not state.get('active') and current:
            # Missing transition evidence is not proof of recovery.
            db.execute("UPDATE incidents SET status='UNKNOWN',partial_history=1 WHERE id=?", current)
    db.execute("INSERT OR REPLACE INTO metadata VALUES('incident_projection_v1','1')")
    db.execute("INSERT OR REPLACE INTO metadata VALUES('incident_projection_cursor',?)",(str(cursor),))
    db.commit()
