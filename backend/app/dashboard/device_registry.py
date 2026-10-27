"""Register configured endpoints once and retain deletions across restarts."""
import hashlib
import ipaddress
import json
import time
from urllib.parse import urlsplit


def sync(store):
    if not store.config:
        return
    grouped = {}
    for target, spec in store.config.targets.items():
        host = spec.get('host') or urlsplit(spec.get('url', '')).hostname
        if host:
            grouped.setdefault(host, []).append((target, spec))
    switch = getattr(store.config, 'switch', {})
    if switch.get('management_host'):
        grouped.setdefault(switch['management_host'], []).append(('', {
            'name': switch.get('name', 'Switch'), 'kind': 'icmp', 'type': 'switch'}))
    now = time.time()
    with store.db() as db:
        settings_row=db.execute('SELECT payload FROM platform_settings WHERE id=1').fetchone()
        policy=json.loads(settings_row[0]) if settings_row else None
        policy_changed=False
        for host, sources in grouped.items():
            if db.execute('SELECT 1 FROM inventory_sources WHERE host=?', (host,)).fetchone():
                continue
            if policy is not None and host not in policy['allowed_hosts'] and len(policy['allowed_hosts'])<100:
                policy['allowed_hosts'].append(host);policy_changed=True
            existing = db.execute("SELECT * FROM objects WHERE collection='inventory' AND json_extract(payload,'$.host')=?", (host,)).fetchone()
            primary, spec = min(sources, key=lambda s: {'icmp': 0, 'tcp': 1, 'dns': 2, 'web': 3}.get(s[1]['kind'], 4))
            method = 'http' if spec['kind'] == 'web' else spec['kind']
            identity = existing[1] if existing else 'inv_' + hashlib.sha256(('configured:' + host).encode()).hexdigest()[:24]
            if not existing:
                value = dict(name=spec['name'], host=host, type=spec.get('type', 'generic'), vendor='', model='',
                    methods=[method], interval=60, group='Perangkat terpantau', tags=[], profile='connectivity', enabled=True,
                    location='', role='', hostname='', credential_ref='', monitor_method=method,
                    monitor_port=spec.get('port', 443), monitor_url=spec.get('url', '') if method == 'http' else '',
                    dns_query=spec.get('query', 'example.com'), mac_address=spec.get('mac_address', ''),
                    follow_dhcp=spec.get('follow_dhcp', False))
                db.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)', ('inventory', identity, 1, json.dumps(value), now, now))
            elif spec.get('mac_address'):
                value = json.loads(existing[3])
                if not value.get('mac_address'):
                    value.update(mac_address=spec['mac_address'], follow_dhcp=spec.get('follow_dhcp', False))
                    db.execute("UPDATE objects SET payload=?,revision=revision+1,updated=? WHERE collection='inventory' AND id=?", (json.dumps(value), now, identity))
            targets=[key for key,_ in sources if key]
            if any(key=='debian_ssh' for key in targets):targets+=['debian','docker']
            if any(key=='mikrotik' for key in targets):targets+=['mikrotik_system','mikrotik_interfaces','mikrotik_network','mikrotik_vlan','mikrotik_routes','wireguard','network_traffic']
            if any(key=='proxmox' for key in targets):targets+=['proxmox_resources']
            db.execute('INSERT INTO inventory_sources VALUES(?,?,?,?)', (host, identity, primary, json.dumps(targets)))
        if policy_changed:
            db.execute('UPDATE platform_settings SET payload=?,revision=revision+1 WHERE id=1',(json.dumps(policy),))
            store.audit(db,'system:registry','settings.sync_configured_hosts','inventory')


def source(store, *, target=None, identity=None):
    with store.db() as db:
        rows = db.execute('SELECT host,inventory_id,primary_target,targets FROM inventory_sources').fetchall()
    return next((r for r in rows if r[1] == identity or target is not None and target in json.loads(r[3])), None)


def dhcp_address(item, leases, configured_hosts):
    if not item.get('follow_dhcp') or not item.get('mac_address'):
        return None
    networks = set()
    for host in configured_hosts:
        try:
            ip = ipaddress.IPv4Address(host)
            if ip.is_private and not (ip.is_loopback or ip.is_link_local):
                networks.add(ipaddress.ip_network(str(ip) + '/24', strict=False))
        except ValueError:
            pass
    matches = set()
    for row in leases:
        if row.get('status') != 'bound' or row.get('disabled') == 'true':
            continue
        mac = row.get('active-mac-address') or row.get('mac-address', '')
        if mac.upper() != item['mac_address'].upper():
            continue
        try:
            ip = ipaddress.IPv4Address(row.get('active-address') or row.get('address', ''))
            if any(ip in subnet for subnet in networks):
                matches.add(str(ip))
        except ValueError:
            pass
    return next(iter(matches)) if len(matches) == 1 else None


def move(store, identity, previous_host, new_host):
    """Persist a verified MAC lease move without overwriting a concurrent edit."""
    with store.db() as db:
        row = db.execute("SELECT payload FROM objects WHERE collection='inventory' AND id=?", (identity,)).fetchone()
        if not row:
            return False
        value = json.loads(row[0])
        if value['host'] != previous_host or not value.get('follow_dhcp') or not value['enabled']:
            return False
        if db.execute("SELECT 1 FROM objects WHERE collection='inventory' AND id<>? AND json_extract(payload,'$.host')=?", (identity, new_host)).fetchone():
            return False
        value['host'] = new_host
        cfg = db.execute('SELECT payload FROM platform_settings WHERE id=1').fetchone()
        settings = json.loads(cfg[0])
        if new_host not in settings['allowed_hosts']:
            if len(settings['allowed_hosts'])>=100:return False
            settings['allowed_hosts'].append(new_host)
            db.execute('UPDATE platform_settings SET payload=?,revision=revision+1 WHERE id=1', (json.dumps(settings),))
        db.execute("UPDATE objects SET payload=?,revision=revision+1,updated=? WHERE collection='inventory' AND id=?", (json.dumps(value), time.time(), identity))
        store.audit(db, 'system:dhcp', 'inventory.address_followed', identity, previous_host + ' -> ' + new_host)
        return True
