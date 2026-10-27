"""Allowlisted HTTP observation. DNS is resolved once and the connection is pinned."""
import asyncio
import ipaddress
import hashlib
import os
import socket
import ssl
import time
from urllib.parse import urlsplit,quote
from app.dashboard.models import url
from app.monitoring.common import result

async def probe(target,address,allowed_hosts):
    start=time.monotonic();writer=None
    try:
        url(address,allowed_hosts)
        u=urlsplit(address);port=u.port or (443 if u.scheme=='https' else 80)
        async with asyncio.timeout(7):
            answers=await asyncio.get_running_loop().getaddrinfo(u.hostname,port,type=socket.SOCK_STREAM)
            ips=[]
            for family,_,_,_,sockaddr in answers:
                ip=ipaddress.ip_address(sockaddr[0])
                if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:raise ValueError('unsafe_resolved_address')
                ips.append((family,str(ip)))
            if not ips:raise ValueError('dns_empty')
            family,address_ip=ips[0];ctx=None
            if u.scheme=='https':ctx=ssl.create_default_context(cafile=os.getenv('PROXMOX_CA_FILE') if u.hostname==os.getenv('PROXMOX_HOST','192.168.20.200') else None)
            reader,writer=await asyncio.open_connection(address_ip,port,family=family,ssl=ctx,server_hostname=u.hostname if ctx else None,limit=16384)
            path=quote(u.path or '/',safe='/%:@!$&()*+,;=-._~')
            host=u.hostname+(':'+str(port) if u.port else '')
            writer.write(f'GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: NMS-Service-Observer/1\r\nConnection: close\r\n\r\n'.encode('ascii'))
            await writer.drain()
            header=await reader.readuntil(b'\r\n\r\n')
            code=int(header.split(b'\r\n',1)[0].split()[1])
            if not 100<=code<=599:raise ValueError('invalid_http_status')
            headers={line.partition(b':')[0].lower():line.partition(b':')[2].strip().lower() for line in header.split(b'\r\n')[1:] if b':' in line}
            embedding=200<=code<300 and not headers.get(b'x-frame-options') and b'frame-ancestors' not in headers.get(b'content-security-policy',b'')
            status='UP' if 200<=code<400 else 'DEGRADED' if code in {401,403} else 'DOWN'
            return result(target,'HTTP observation (TLS verified)',status,http_status=code,host=u.hostname,
                latency_ms=round((time.monotonic()-start)*1000,2),embedding_supported=bool(embedding),configuration_hash=hashlib.sha256(address.encode()).hexdigest(),scope='HTTP response only; redirects not followed; no application login or credentials sent')
    except (TimeoutError,OSError,ValueError,asyncio.IncompleteReadError,asyncio.LimitOverrunError) as exc:
        error='tls_verification_failed' if isinstance(exc,ssl.SSLError) else 'timeout' if isinstance(exc,TimeoutError) else 'probe_failed'
        return result(target,'HTTP observation','UNKNOWN' if error=='tls_verification_failed' else 'DOWN',error=error)
    finally:
        if writer:
            writer.close()
            try:
                async with asyncio.timeout(1):await writer.wait_closed()
            except (OSError,TimeoutError):pass
