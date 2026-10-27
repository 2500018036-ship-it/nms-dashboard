"""Strict configuration contracts. No device credentials or arbitrary commands."""
import ipaddress
import re
from urllib.parse import urlsplit

KINDS = ('router', 'switch', 'firewall', 'server', 'access-point', 'proxmox', 'vm', 'lxc', 'docker', 'dns', 'proxy', 'application','iot','generic','other')
ROLES = ('Administrator','Super Administrator','Network Administrator','Server Administrator','Operator','Read-only operator','Viewer')
COLLECTIONS = ('integrations', 'topologies', 'inventory', 'maintenance')

def text(value, minimum=0, maximum=180):
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum or re.search(r'[\x00-\x1f\x7f]', value):
        raise ValueError('invalid_text')
    return value.strip()

def fields(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body): raise ValueError('invalid_fields')

def integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ValueError('invalid_number')
    return value

def boolean(value):
    if type(value) is not bool: raise ValueError('invalid_boolean')
    return value

def host(value):
    value = text(value, 1, 253).lower()
    try:
        address = ipaddress.ip_address(value)
        if address.version != 4 or address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ValueError('unsafe_host')
        return value
    except ValueError:
        if not re.fullmatch(r'(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', value) or '.' not in value or '..' in value or value.endswith(('.localhost', '.localdomain')) or re.fullmatch(r'[\d.]+', value):
            raise ValueError('invalid_host')
        return value

def url(value, allowed_hosts):
    value = text(value, 1, 500)
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query or '\\' in value:
        raise ValueError('invalid_service_url')
    if host(parsed.hostname) not in allowed_hosts: raise ValueError('host_not_allowed')
    if parsed.port is not None and not 1 <= parsed.port <= 65535: raise ValueError('invalid_port')
    if any(x in parsed.path.lower() for x in ('/api/auth', '/latest/meta-data', '..')): raise ValueError('unsafe_path')
    return value

def settings(body):
    fields(body, ('identity', 'timezone', 'date_format', 'poll_interval', 'network_interval', 'cpu_threshold', 'memory_threshold', 'storage_threshold', 'cooldown', 'retention_days', 'alerts', 'allowed_hosts'), ('identity', 'timezone', 'date_format', 'allowed_hosts'))
    out = {'identity': text(body['identity'], 1, 80), 'timezone': text(body['timezone'], 1, 80), 'date_format': text(body['date_format'], 1, 20)}
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try: ZoneInfo(out['timezone'])
    except ZoneInfoNotFoundError: raise ValueError('invalid_timezone') from None
    if out['date_format'] not in {'id-ID', 'en-GB', 'en-US'}: raise ValueError('invalid_date_format')
    for key, low, high in (('poll_interval',60,3600),('network_interval',10,120),('cpu_threshold',50,100),('memory_threshold',50,100),('storage_threshold',50,100),('cooldown',300,86400),('retention_days',1,365)):
        out[key] = integer(body.get(key), low, high)
    out['alerts'] = boolean(body.get('alerts'))
    if not isinstance(body['allowed_hosts'], list) or len(body['allowed_hosts']) > 100: raise ValueError('invalid_hosts')
    out['allowed_hosts'] = list(dict.fromkeys(host(v) for v in body['allowed_hosts']))
    return out

def record(collection, body, allowed_hosts=(), targets=()):
    if collection == 'integrations':
        fields(body, ('name','url','kind','group','enabled','monitor_enabled','poll_interval','collector','authentication'), ('name','url','kind','enabled'))
        kind = body['kind']
        if kind not in KINDS: raise ValueError('invalid_kind')
        collector = text(body.get('collector',''), 0, 80)
        if collector and collector not in targets: raise ValueError('invalid_collector')
        auth = body.get('authentication', 'external')
        if auth not in {'none', 'external', 'server-configured'} or auth == 'server-configured' and not collector: raise ValueError('invalid_authentication')
        enabled = boolean(body['enabled']); monitored = boolean(body.get('monitor_enabled', False))
        if monitored and collector: raise ValueError('collector_already_scheduled')
        return {'name':text(body['name'],1,80),'url':url(body['url'],allowed_hosts),'kind':kind,'group':text(body.get('group',''),0,48),'enabled':enabled,
            'monitor_enabled':monitored,'poll_interval':integer(body.get('poll_interval',60),60,3600),'collector':collector,'authentication':auth}
    if collection == 'inventory':
        fields(body, ('name','host','type','vendor','model','methods','interval','group','tags','profile','enabled','location','role','hostname','credential_ref','monitor_method','monitor_port','monitor_url','dns_query','mac_address','follow_dhcp'), ('name','host','type','methods','interval','profile','enabled'))
        methods = body['methods']; tags = body.get('tags', [])
        if not isinstance(methods,list) or not methods or len(methods)>6 or any(v not in {'icmp','tcp','snmp','api','dns','http','agent'} for v in methods): raise ValueError('invalid_methods')
        if body['type'] not in {'router','switch','server','hypervisor','container-host','dns','vpn','service','access-point','firewall','iot','generic','other'}: raise ValueError('invalid_type')
        if body['profile'] not in {'network','host','services','connectivity','virtualization','custom'}: raise ValueError('invalid_profile')
        if not isinstance(tags,list) or len(tags)>12: raise ValueError('invalid_tags')
        method=body.get('monitor_method','')
        if not isinstance(method,str) or method not in {'','icmp','tcp','http','dns','routeros','proxmox','snmp','ssh'}:raise ValueError('invalid_monitor_method')
        reference=text(body.get('credential_ref',''),0,40)
        if reference not in {'','routeros-default','proxmox-default'}:raise ValueError('invalid_credential_reference')
        address=host(body['host'])
        if method and address not in allowed_hosts:raise ValueError('host_not_allowed')
        port=integer(body.get('monitor_port',443),1,65535)
        monitor_url=text(body.get('monitor_url',''),0,500)
        if method=='http':
            monitor_url=url(monitor_url,allowed_hosts)
            if urlsplit(monitor_url).hostname!=address:raise ValueError('url_host_mismatch')
        elif monitor_url:raise ValueError('unexpected_monitor_url')
        query=text(body.get('dns_query','example.com'),1,253)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}',query):raise ValueError('invalid_dns_query')
        mac=text(body.get('mac_address',''),0,17).upper()
        follow=boolean(body.get('follow_dhcp',False))
        if mac and not re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}',mac):raise ValueError('invalid_mac_address')
        if follow and (not mac or method!='icmp'):raise ValueError('invalid_dhcp_tracking')
        return {'name':text(body['name'],1,80),'host':address,'type':body['type'],'vendor':text(body.get('vendor',''),0,80),'model':text(body.get('model',''),0,80),
            'methods':list(dict.fromkeys(methods)),'interval':integer(body['interval'],15,86400),'group':text(body.get('group',''),0,48),
            'tags':list(dict.fromkeys(text(t,1,32) for t in tags)),'profile':body['profile'],'enabled':boolean(body['enabled']),
            'location':text(body.get('location',''),0,80),'role':text(body.get('role',''),0,80),'hostname':text(body.get('hostname',''),0,253),
            'credential_ref':reference,'monitor_method':method,'monitor_port':port,'monitor_url':monitor_url,'dns_query':query,'mac_address':mac,'follow_dhcp':follow}
    if collection == 'maintenance':
        fields(body, ('name','scope','start','end','enabled'), ('name','scope','start','end','enabled'))
        scope=text(body['scope'],1,100)
        if scope != '*' and not re.fullmatch(r'[a-zA-Z0-9_./:-]{1,100}',scope): raise ValueError('invalid_scope')
        start=integer(body['start'],0,4102444800); end=integer(body['end'],0,4102444800)
        if not 0 < end-start <= 7*86400: raise ValueError('invalid_window')
        return {'name':text(body['name'],1,80),'scope':scope,'start':start,'end':end,'enabled':boolean(body['enabled'])}
    if collection == 'topologies':
        fields(body, ('name','nodes','links'), ('name','nodes','links'))
        if not isinstance(body['nodes'],list) or len(body['nodes'])>100 or not isinstance(body['links'],list) or len(body['links'])>200: raise ValueError('topology_too_large')
        nodes=[]; ids=set()
        for n in body['nodes']:
            fields(n, ('id','name','kind','x','y','group','collector','resource_id','service_id','device_id'), ('id','name','kind','x','y'))
            identity=text(n['id'],1,60)
            if not re.fullmatch(r'[a-zA-Z0-9_-]+',identity) or identity in ids or n['kind'] not in KINDS: raise ValueError('invalid_node')
            ids.add(identity)
            item={'id':identity,'name':text(n['name'],1,80),'kind':n['kind'],'x':integer(n['x'],-5000,5000),'y':integer(n['y'],-5000,5000)}
            for k in ('group','collector','resource_id','service_id','device_id'): item[k]=text(n.get(k,''),0,100)
            if item['collector'] and item['collector'] not in targets: raise ValueError('invalid_collector')
            nodes.append(item)
        links=[]; ids_links=set()
        for e in body['links']:
            fields(e, ('id','source','target','type','label','source_port','target_port','vlan','speed_mbps','evidence'), ('id','source','target','type','label'))
            item={k:text(e[k],1 if k!='label' else 0,80) for k in ('id','source','target','type','label')}
            item.update(source_port=text(e.get('source_port',''),0,80),target_port=text(e.get('target_port',''),0,80),
                vlan=integer(e.get('vlan',0),0,4094),speed_mbps=integer(e.get('speed_mbps',0),0,1000000),evidence=text(e.get('evidence','manual'),1,80))
            if item['id'] in ids_links or item['source'] not in ids or item['target'] not in ids or item['source']==item['target']: raise ValueError('invalid_link')
            ids_links.add(item['id']);links.append(item)
        return {'name':text(body['name'],1,80),'nodes':nodes,'links':links}
    raise ValueError('invalid_collection')


def public_validation_code(exc):
    known={'host_not_allowed','invalid_mac_address','invalid_dhcp_tracking','duplicate_host','referenced_by_topology','monitor_limit','invalid_monitor_method','credential_host_mismatch','literal_ipv4_required','invalid_host','invalid_number','invalid_fields','invalid_methods','invalid_profile','invalid_type','invalid_text','url_host_mismatch','invalid_service_url','invalid_dns_query'}
    return str(exc) if str(exc) in known else 'validation_failed'
