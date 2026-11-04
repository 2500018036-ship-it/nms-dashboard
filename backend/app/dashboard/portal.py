"""Inventoried GUI targets, verified before the private browser can launch them."""
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit, urljoin
from app.dashboard import models

ROLES=['Administrator','Super Administrator','Network Administrator','Server Administrator']

def initialize(store):
    with store.db() as db:db.execute('''CREATE TABLE IF NOT EXISTS portal_checks(
        target_id TEXT PRIMARY KEY,url TEXT NOT NULL,checked REAL NOT NULL,payload TEXT NOT NULL)''')

def entries(store):
    devices=[{'id':d['id'],'name':d['name'],'url':d['dashboard_url'],'inventory_id':d['id'],'enabled':d['enabled']} for d in store.list('inventory') if d.get('dashboard_url')]
    services=[{'id':s['id'],'name':s['name'],'url':s['url'],'enabled':s['enabled']} for s in store.list('integrations')]
    dynamic=devices+services
    for item in dynamic:item['roles']=reviewed(item['url']).get('roles',ROLES)
    legacy=[]
    if not store.inventory_authoritative():
        try:
            config=json.loads(Path(os.environ['NMS_ACCESS_TARGETS_FILE']).read_text())
            for target in config.get('targets',[]):
                if any(item['url'].rstrip('/')==target['url'].rstrip('/') for item in dynamic):continue
                value={k:target[k] for k in ('id','name','url','roles')}
                value['enabled']=True
                if target.get('inventory_mac'):
                    matches=[d for d in store.list('inventory') if d.get('mac_address','').upper()==target['inventory_mac'].upper() and d['enabled']]
                    if len(matches)!=1:value['enabled']=False
                    else:
                        from urllib.parse import urlunsplit
                        u=urlsplit(value['url']);value['url']=urlunsplit((u.scheme,matches[0]['host']+(':'+str(u.port) if u.port else ''),u.path,'',''))
                legacy.append(value)
        except (OSError,ValueError,KeyError):pass
    return legacy+dynamic

def reviewed(url):
    path=os.getenv('NMS_ACCESS_TARGETS_FILE','')
    if not path:return {}
    try:
        raw=Path(path).read_text()
        if len(raw)>65536:return {}
        return next((v for v in json.loads(raw).get('targets',[]) if v['url'].rstrip('/')==url.rstrip('/')), {})
    except (OSError,ValueError,KeyError):return {}

def public(store):
    initialize(store)
    with store.db() as db:checks={r[0]:(r[1],r[2],json.loads(r[3])) for r in db.execute('SELECT * FROM portal_checks')}
    result=[]
    for item in entries(store):
        row=checks.get(item['id']); current=row and row[0]==item['url']
        sample=row[2] if current else {}
        recent=bool(current and time.time()-row[1]<900)
        available=bool(item['enabled'] and recent and sample.get('reachable'))
        reason='disabled' if not item['enabled'] else sample.get('error','') if current else 'portal_not_verified'
        if current and not recent:reason='portal_verification_expired'
        result.append({**item,'available':available,'reason':reason,
            'verified_at':row[1] if current else None,'verification':{k:sample[k] for k in ('http_status','authentication_required','iframe_blocked','x_frame_options','frame_ancestors','redirect','error') if k in sample}})
    return result

def safe_ip(value):
    ip=ipaddress.ip_address(value)
    if ip.version!=4 or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:raise ValueError('unsafe_resolved_address')
    return str(ip)

async def verify(store,item):
    initialize(store); writer=None; payload={'reachable':False};address=item['url']
    try:
        models.url(address,store.get_settings()['value']['allowed_hosts'])
        u=urlsplit(address);port=u.port or (443 if u.scheme=='https' else 80);pins=reviewed(address)
        async with asyncio.timeout(8):
            answers=await asyncio.get_running_loop().getaddrinfo(u.hostname,port,type=socket.SOCK_STREAM,family=socket.AF_INET)
            ips=[safe_ip(a[4][0]) for a in answers]
            if not ips:raise ValueError('dns_empty')
            connect_ip=safe_ip(pins.get('connect_ip') or ips[0])
            context=ssl.create_default_context(cafile=os.getenv('PROXMOX_CA_FILE') if u.hostname==os.getenv('PROXMOX_HOST') else None) if u.scheme=='https' else None
            # A root-reviewed certificate pin is an explicit trust decision, never a user checkbox bypass.
            if context and pins.get('tls_spki'):
                context.check_hostname=False;context.verify_mode=ssl.CERT_NONE
            reader,writer=await asyncio.open_connection(connect_ip,port,ssl=context,server_hostname=u.hostname if context else None,limit=16384)
            if context and pins.get('tls_spki'):
                import base64,hashlib
                from cryptography import x509
                from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
                cert=x509.load_der_x509_certificate(writer.get_extra_info('ssl_object').getpeercert(binary_form=True))
                pin=base64.b64encode(hashlib.sha256(cert.public_key().public_bytes(Encoding.DER,PublicFormat.SubjectPublicKeyInfo)).digest()).decode()
                if pin not in pins['tls_spki']:raise ValueError('certificate_pin_mismatch')
            authority=u.hostname+(':'+str(port) if u.port else '')
            path=u.path or '/'
            writer.write(f'GET {path} HTTP/1.1\r\nHost: {authority}\r\nUser-Agent: THEAZ-Portal-Verify/1\r\nConnection: close\r\n\r\n'.encode('ascii'));await writer.drain()
            block=await reader.readuntil(b'\r\n\r\n')
            lines=block.decode('latin-1').split('\r\n');code=int(lines[0].split()[1])
            headers={k.lower():v.strip() for line in lines[1:] for k,sep,v in [line.partition(':')] if sep}
            if not 100<=code<=599:raise ValueError('invalid_http_response')
            error='' if 200<=code<400 or code in {401,403} else 'dashboard_http_error'
            redirect=headers.get('location','')
            if 300<=code<400 and redirect:
                target=urlsplit(urljoin(address,redirect))
                if (target.scheme,target.hostname,target.port or (443 if target.scheme=='https' else 80))!=(u.scheme,u.hostname,port):error='redirect_origin_not_approved'
            frame=headers.get('x-frame-options','')[:160];csp=headers.get('content-security-policy','')
            frame_ancestors=next((s.strip()[:240] for s in csp.split(';') if s.strip().lower().startswith('frame-ancestors')),'')
            payload={'reachable':not error,'http_status':code,'connect_ip':connect_ip,'error':error,
                'authentication_required':code in {401,403},'iframe_blocked':bool(frame or frame_ancestors),
                'x_frame_options':frame,'frame_ancestors':frame_ancestors,'redirect':bool(redirect)}
    except ssl.SSLError:payload['error']='tls_verification_failed'
    except (TimeoutError,socket.timeout):payload['error']='timeout'
    except socket.gaierror:payload['error']='dns_resolution_failed'
    except (OSError,ValueError,asyncio.IncompleteReadError,asyncio.LimitOverrunError) as exc:
        known={'host_not_allowed','unsafe_resolved_address','certificate_pin_mismatch'}
        payload['error']=str(exc) if str(exc) in known else 'dashboard_connection_failed'
    finally:
        if writer:
            writer.close()
            try:await asyncio.wait_for(writer.wait_closed(),1)
            except (OSError,TimeoutError):pass
    with store.db() as db:db.execute('INSERT OR REPLACE INTO portal_checks VALUES(?,?,?,?)',(item['id'],address,time.time(),json.dumps(payload)))
    return {k:v for k,v in payload.items() if k!='connect_ip'}
