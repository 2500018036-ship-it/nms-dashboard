"""Authorize the private GUI runtime against current NMS sessions and device ACLs."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from app.dashboard.permissions import require
from app.dashboard.platform import Forbidden, Missing


def authorize(store, session, query):
    if not session:raise Forbidden()
    if set(query) - {'target'} or any(len(v) != 1 for v in query.values()):
        raise ValueError('invalid_query')
    identity = query.get('target', [''])[0]
    if identity and not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', identity):
        raise ValueError('invalid_target')
    enabled = os.getenv('NMS_ACCESS_ENABLED', 'false').lower() == 'true'
    config = {'targets': []}
    if enabled:
        path = Path(os.environ['NMS_ACCESS_TARGETS_FILE'])
        if path.stat().st_size > 65536:
            raise OSError('access_config_invalid')
        config = json.loads(path.read_text())
    role = session['user']['role']
    targets = []
    from app.dashboard.portal import public
    dynamic=public(store) if enabled else []
    for value in dynamic:
        allowed=role in value['roles'] and value['available']
        targets.append({k:v for k,v in value.items() if k!='roles'}|{'allowed':allowed,'reason':value['reason'] if role in value['roles'] else 'access_denied'})
    if identity:
        try:require(session, 'gui.access')
        except Forbidden:
            store.log(session['user']['username'],'access.denied',identity,'role_denied')
            raise
        selected = next((t for t in targets if t['id'] == identity), None)
        if not selected:
            raise Missing()
        if not selected['allowed']:
            store.log(session['user']['username'], 'access.denied', identity, selected['reason'])
            raise Forbidden()
    return {'enabled': enabled, 'user': session['user'], 'expires_at': session['expires_at'],
        'binding': session.get('_access_binding', ''), 'targets': targets}
