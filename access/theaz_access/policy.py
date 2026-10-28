import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

SID = re.compile(r'^[a-f0-9]{32}$')
TARGET = re.compile(r'^[a-z][a-z0-9_-]{0,39}$')


def origin(value, connect_ip=None):
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or url.username or url.password or not url.hostname or url.fragment:
        raise ValueError('invalid_target_origin')
    if connect_ip is not None:
        # Root-owned virtual-host mapping: preserve browser Host/SNI and TLS checks,
        # while dialing a fixed audited address without resolving caller-controlled DNS.
        ip = ipaddress.IPv4Address(connect_ip)
        private = any(ip in ipaddress.ip_network(net) for net in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
        if not (ip.is_global or private) or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError('invalid_connect_address')
        hostname=url.hostname
        if len(hostname)>253 or '.' not in hostname or not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',hostname) or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in hostname.split('.')):
            raise ValueError('invalid_target_hostname')
        try:ipaddress.IPv4Address(hostname)
        except ValueError:pass
        else:raise ValueError('invalid_target_hostname')
        return url.scheme,hostname,url.port or (443 if url.scheme=='https' else 80)
    ip = ipaddress.IPv4Address(url.hostname)
    if not ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise ValueError('invalid_target_origin')
    return url.scheme, str(ip), url.port or (443 if url.scheme == 'https' else 80)


def load(path):
    data = json.loads(Path(path).read_text())
    public = urlsplit(data['public_origin'])
    if public.scheme != 'https' or public.username or public.password or public.path not in {'', '/'} or public.query or public.fragment:
        raise ValueError('invalid_public_origin')
    if type(data['max_sessions']) is not int or not 1 <= data['max_sessions'] <= 2:
        raise ValueError('invalid_capacity')
    if not 60 <= data['idle_seconds'] <= 1800 or not 300 <= data['lifetime_seconds'] <= 3600:
        raise ValueError('invalid_timeout')
    targets = data['targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
        raise ValueError('invalid_targets')
    ids = set()
    for target in targets:
        if not TARGET.fullmatch(target['id']) or target['id'] in ids:
            raise ValueError('invalid_target_id')
        ids.add(target['id'])
        origin(target['url'],target.get('connect_ip'))
        if target.get('connect_ip') and target.get('inventory_mac'):raise ValueError('invalid_target_mapping')
        assets=target.get('asset_origins',[])
        if not isinstance(assets,list) or len(assets)>8:raise ValueError('invalid_asset_origins')
        for asset in assets:
            if set(asset)!={'url','connect_ip'}:raise ValueError('invalid_asset_origin')
            scheme,_,port=origin(asset['url'],asset['connect_ip'])
            if scheme!='https' or port!=443 or urlsplit(asset['url']).path not in ('','/') or urlsplit(asset['url']).query:raise ValueError('invalid_asset_origin')
        if not target['roles'] or any(role not in {'Administrator', 'Super Administrator', 'Network Administrator', 'Server Administrator'} for role in target['roles']):
            raise ValueError('invalid_roles')
        for pin in target.get('tls_spki', []):
            if not re.fullmatch(r'[A-Za-z0-9+/]{43}=', pin):
                raise ValueError('invalid_certificate_pin')
    return data


def target(config, identity):
    if not isinstance(identity, str) or not TARGET.fullmatch(identity):
        raise KeyError('target_not_found')
    value=next((t for t in config['targets'] if t['id']==identity),None)
    if value is None:raise KeyError('target_not_found')
    return value


def check_sid(value):
    if not isinstance(value, str) or not SID.fullmatch(value):
        raise ValueError('invalid_session_id')
    return value
