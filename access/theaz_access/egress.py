"""One selected origin per Unix socket. TLS and native WebSocket stay end-to-end."""
import asyncio
from urllib.parse import urlsplit
from .policy import origin


async def relay(reader, writer):
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    finally:
        writer.close()


async def tunnel(left_reader, left_writer, right_reader, right_writer):
    tasks = [asyncio.create_task(relay(left_reader, right_writer)), asyncio.create_task(relay(right_reader, left_writer))]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        left_writer.close()
        right_writer.close()


def destination(method, raw_url, selected):
    selected = selected if isinstance(selected,dict) else {'url':selected}
    scheme, host, port = origin(selected['url'],selected.get('connect_ip'))
    address=selected.get('connect_ip') or host
    if method == 'CONNECT':
        # Chromium may tunnel a native ws:// connection as well as HTTPS.
        # Only the selected endpoint and explicitly reviewed HTTPS asset origins.
        for endpoint in [selected,*selected.get('asset_origins',[])]:
            _,name,endpoint_port=origin(endpoint['url'],endpoint.get('connect_ip'))
            if raw_url==f'{name}:{endpoint_port}':return endpoint.get('connect_ip') or name,endpoint_port,None
        raise ValueError('origin_denied')
    url = urlsplit(raw_url)
    if scheme != 'http' or url.scheme not in {'http','ws'} or url.hostname != host or (url.port or 80) != port or url.username or url.password or url.fragment:
        raise ValueError('origin_denied')
    return address, port, (url.path or '/') + ('?' + url.query if url.query else '')


async def handle(reader, writer, selected):
    upstream = None
    try:
        block = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
        if len(block) > 32768:
            raise ValueError('request_too_large')
        lines = block.decode('latin-1').split('\r\n')
        method, url, version = lines[0].split(' ')
        if method not in {'CONNECT', 'GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'} or version not in {'HTTP/1.1', 'HTTP/1.0'}:
            raise ValueError('invalid_proxy_request')
        host, port, path = destination(method, url, selected)
        remote, upstream = await asyncio.wait_for(asyncio.open_connection(host, port), 8)
        if method == 'CONNECT':
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        else:
            forwarded = []
            for line in lines[1:]:
                if not line:
                    continue
                key, separator, value = line.partition(':')
                if not separator or key[:1].isspace():
                    raise ValueError('invalid_header')
                if key.lower() in {'host', 'proxy-authorization', 'proxy-connection'}:
                    continue
                forwarded.append(line)
            value=selected if isinstance(selected,dict) else {'url':selected}
            _,hostname,_=origin(value['url'],value.get('connect_ip'))
            authority = hostname + (':' + str(port) if port != 80 else '')
            upstream.write((f'{method} {path} {version}\r\nHost: {authority}\r\n' + '\r\n'.join(forwarded) + '\r\n\r\n').encode('latin-1'))
            await upstream.drain()
        await writer.drain()
        await tunnel(reader, writer, remote, upstream)
    except (ValueError, UnicodeError, asyncio.LimitOverrunError):
        writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        try:
            writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        except OSError:
            pass
    finally:
        try:
            await writer.drain()
        except OSError:
            pass
        writer.close()
        if upstream:
            upstream.close()


async def serve(path, selected):
    return await asyncio.start_unix_server(lambda r, w: handle(r, w, selected), path=str(path), limit=65536)
