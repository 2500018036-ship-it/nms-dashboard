"""Authorize the private GUI runtime against current NMS sessions and device ACLs."""
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from app.dashboard.permissions import require
from app.dashboard.platform import Forbidden, Missing


def authorize(store, session, query):
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
    for value in config['targets']:
        url = value['url']
        available = True
        if value.get('inventory_mac'):
            matches = [d for d in store.list('inventory') if d.get('mac_address', '').upper() == value['inventory_mac'].upper() and d['enabled']]
            if len(matches) != 1:
                available = False
            else:
                parsed = urlsplit(url)
                authority = matches[0]['host'] + (':' + str(parsed.port) if parsed.port else '')
                url = urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
        allowed = role in value['roles'] and available
        targets.append({'id': value['id'], 'name': value['name'], 'url': url,
            'allowed': allowed, 'available': available, 'reason': '' if allowed else 'device_address_unavailable' if not available else 'access_denied'})
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
