import asyncio
from contextlib import closing
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from aiohttp import ClientError, ClientSession, ClientTimeout, UnixConnector, WSMsgType, web
from . import egress
from .policy import check_sid, load


@dataclass
class Session:
    id: str
    target: str
    actor: str
    binding: str
    created: float
    expires: float
    activity: float
    cookie: str = field(repr=False)
    proxy: object = field(repr=False)
    sockets: set = field(default_factory=set, repr=False)


class Gateway:
    def __init__(self, config, root, audit, auth_url, broker_socket):
        self.config, self.root = config, Path(root).resolve()
        self.audit_path, self.auth_url, self.broker_socket = Path(audit), auth_url, broker_socket
        self.sessions = {}
        self.lock = asyncio.Lock()
        self.http = self.broker = None
        with closing(sqlite3.connect(self.audit_path)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS access_audit(id INTEGER PRIMARY KEY,at REAL,actor TEXT,target TEXT,session TEXT,event TEXT,reason TEXT)')
            db.commit()
        self.audit_path.chmod(0o600)

    def record(self, actor, target, identity, event, reason=''):
        with closing(sqlite3.connect(self.audit_path)) as db:
            db.execute('INSERT INTO access_audit(at,actor,target,session,event,reason) VALUES(?,?,?,?,?,?)',
                (time.time(), actor, target, identity, event, reason))
            db.execute('DELETE FROM access_audit WHERE at<?', (time.time() - 90*86400,))
            db.execute('DELETE FROM access_audit WHERE id<=(SELECT MAX(id)-100000 FROM access_audit)')
            db.commit()

    async def auth(self, cookie, target=None):
        if not cookie or len(cookie) > 2048:
            raise web.HTTPUnauthorized(text='authentication_required')
        try:
            async with self.http.get(self.auth_url, params={'target': target} if target else {},
                    headers={'Cookie': cookie, 'Host': '127.0.0.1:8765'}, allow_redirects=False) as response:
                if response.status in {401, 403}:
                    raise web.HTTPUnauthorized(text='authentication_required') if response.status == 401 else web.HTTPForbidden(text='access_denied')
                if response.status != 200:
                    raise web.HTTPServiceUnavailable(text='authentication_unavailable')
                raw = await response.content.read(32769)
                if len(raw) > 32768:
                    raise ValueError()
                value = json.loads(raw)
                if not value['enabled']:
                    raise web.HTTPServiceUnavailable(text='access_not_activated')
                if not re.fullmatch(r'[a-f0-9]{64}', value.get('binding', '')) or not value['user']['username'] or value['expires_at'] <= time.time():
                    raise ValueError('invalid_authorization')
                return value
        except web.HTTPException:
            raise
        except Exception:
            raise web.HTTPServiceUnavailable(text='authentication_unavailable') from None

    async def control(self, method, path, body=None):
        async with self.broker.request(method, 'http://broker' + path, json=body) as response:
            if response.status == 409:
                raise web.HTTPConflict(text='access_capacity_reached')
            if response.status != 200:
                raise web.HTTPServiceUnavailable(text='browser_runtime_unavailable')
            return await response.json()

    def directory(self, identity):
        check_sid(identity)
        directory = self.root / identity
        if directory.is_symlink() or directory.parent.resolve() != self.root:
            raise web.HTTPForbidden()
        return directory

    async def owned(self, request):
        identity = check_sid(request.match_info['id'])
        item = self.sessions.get(identity)
        if not item:
            raise web.HTTPNotFound(text='session_not_found')
        user = await self.auth(request.headers.get('Cookie', ''), item.target)
        if user['binding'] != item.binding or user['user']['username'] != item.actor:
            self.record(user['user']['username'], item.target, identity, 'access.denied', 'session_owner_mismatch')
            raise web.HTTPForbidden(text='session_owner_mismatch')
        if time.time() >= item.expires or time.time() - item.activity > self.config['idle_seconds']:
            await self.close(identity, 'expired')
            raise web.HTTPGone(text='session_expired')
        return item, user

    def public(self, item):
        state = 'starting'
        path = self.directory(item.id) / 'state.json'
        if path.is_file() and not path.is_symlink():
            try:
                state = json.loads(path.read_text())['state']
            except (ValueError, KeyError, OSError):
                state = 'failed'
        return {'id': item.id, 'target': item.target, 'state': state if state in {'starting','ready','failed'} else 'failed',
            'expires_at': item.expires, 'idle_seconds': self.config['idle_seconds'],
            'websocket_path': '/access-api/sessions/' + item.id + '/display'}

    async def close(self, identity, reason):
        item = self.sessions.get(identity)
        if item:
            for socket in list(item.sockets):
                await socket.close(code=1008, message=b'session_ended')
            if item.proxy:
                item.proxy.close()
                await item.proxy.wait_closed()
            try:
                await self.control('DELETE', '/workers/' + identity)
            except (ClientError, OSError, web.HTTPException):
                # Revoke display immediately; the broker lease also removes orphaned workers.
                self.record(item.actor, item.target, identity, 'access.cleanup_pending', 'broker_unavailable')
            self.sessions.pop(identity, None)
            self.record(item.actor, item.target, identity, 'access.stopped', reason)

    async def sweep(self):
        while True:
            await asyncio.sleep(10)
            for identity, item in list(self.sessions.items()):
                reason = None
                if time.time() >= item.expires:
                    reason = 'lifetime_expired'
                elif time.time() - item.activity > self.config['idle_seconds']:
                    reason = 'idle_expired'
                else:
                    try:
                        user = await self.auth(item.cookie, item.target)
                        if user['binding'] != item.binding:
                            reason = 'session_revoked'
                    except web.HTTPException:
                        reason = 'authorization_revoked_or_unavailable'
                try:
                    if reason:
                        await self.close(identity, reason)
                    else:
                        await self.control('POST', '/workers/' + identity + '/lease', {})
                except (ClientError, OSError, web.HTTPException):
                    # Broker independently expires orphaned workers after 90 seconds.
                    pass


def app(gateway):
    @web.middleware
    async def guarded(request, handler):
        if request.method != 'GET' or request.headers.get('Upgrade', '').lower() == 'websocket':
            if request.headers.get('Origin') != gateway.config['public_origin']:
                raise web.HTTPForbidden(text='origin_denied')
        if request.headers.get('Sec-Fetch-Site') == 'cross-site':
            raise web.HTTPForbidden(text='origin_denied')
        try:
            response = await handler(request)
            if not isinstance(response, web.WebSocketResponse):
                response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
            return response
        except (ValueError, KeyError):
            raise web.HTTPBadRequest(text='invalid_request') from None

    async def health(request):
        return web.json_response({'status': 'UP'})

    async def catalog(request):
        user = await gateway.auth(request.headers.get('Cookie', ''))
        return web.json_response({'targets': user['targets'], 'max_sessions': gateway.config['max_sessions']})

    async def create(request):
        body = await request.json()
        if set(body) != {'target'}:
            raise web.HTTPBadRequest(text='invalid_request')
        cookie = request.headers.get('Cookie', '')
        user = await gateway.auth(cookie, body['target'])
        async with gateway.lock:
            for item in list(gateway.sessions.values()):
                if item.binding == user['binding']:
                    if item.target == body['target']:
                        return web.json_response(gateway.public(item))
                    await gateway.close(item.id, 'target_switched')
            identity = secrets.token_hex(16)
            worker = await gateway.control('POST', '/workers', {'id': identity, 'target': body['target']})
            try:
                path = gateway.directory(identity) / 'egress.sock'
                proxy = await egress.serve(path, worker['url'])
                os.chmod(path, 0o600)
            except BaseException:
                await gateway.control('DELETE', '/workers/' + identity)
                raise
            now = time.time()
            item = Session(identity, body['target'], user['user']['username'], user['binding'], now,
                min(worker['expires'], user['expires_at']), now, cookie, proxy)
            gateway.sessions[identity] = item
            gateway.record(item.actor, item.target, identity, 'access.started')
            return web.json_response(gateway.public(item))

    async def status(request):
        item, _ = await gateway.owned(request)
        return web.json_response(gateway.public(item))

    async def stop(request):
        item, _ = await gateway.owned(request)
        await gateway.close(item.id, 'user_closed')
        return web.json_response({'ok': True})

    async def activity(request):
        item, _ = await gateway.owned(request)
        if await request.json() != {}:
            raise web.HTTPBadRequest()
        item.activity = time.time()
        return web.json_response({'ok': True})

    async def display(request):
        item, _ = await gateway.owned(request)
        if len(item.sockets) >= 1:
            raise web.HTTPConflict(text='display_already_connected')
        path = gateway.directory(item.id) / 'vnc.sock'
        if path.is_symlink() or not path.is_socket():
            raise web.HTTPServiceUnavailable(text='display_not_ready')
        reader, writer = await asyncio.open_unix_connection(str(path))
        websocket = web.WebSocketResponse(protocols=('binary',), heartbeat=20, max_msg_size=1048576, compress=False)
        await websocket.prepare(request)
        item.sockets.add(websocket)

        async def outbound():
            while chunk := await reader.read(65536):
                await websocket.send_bytes(chunk)

        async def inbound():
            async for message in websocket:
                if message.type == WSMsgType.BINARY:
                    writer.write(message.data)
                    await writer.drain()
                elif message.type in {WSMsgType.ERROR, WSMsgType.TEXT}:
                    break

        tasks = [asyncio.create_task(outbound()), asyncio.create_task(inbound())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            item.sockets.discard(websocket)
            await websocket.close()
        return websocket

    async def audit(request):
        user = await gateway.auth(request.headers.get('Cookie', ''))
        if user['user']['role'] not in {'Administrator', 'Super Administrator'}:
            raise web.HTTPForbidden(text='access_denied')
        with closing(sqlite3.connect(gateway.audit_path)) as db:
            rows = db.execute('SELECT at,actor,target,session,event,reason FROM access_audit ORDER BY id DESC LIMIT 100').fetchall()
        return web.json_response({'items': [dict(zip(('at','actor','target','session','event','reason'), row)) for row in rows]})

    async def lifecycle(application):
        gateway.http = ClientSession(timeout=ClientTimeout(total=8))
        gateway.broker = ClientSession(connector=UnixConnector(path=gateway.broker_socket), timeout=ClientTimeout(total=45))
        task = asyncio.create_task(gateway.sweep())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for identity in list(gateway.sessions):
            await gateway.close(identity, 'gateway_shutdown')
        await gateway.http.close()
        await gateway.broker.close()

    application = web.Application(middlewares=[guarded], client_max_size=16*1024*1024)
    prefix = '/access-api'
    application.router.add_get(prefix + '/healthz', health)
    application.router.add_get(prefix + '/catalog', catalog)
    application.router.add_post(prefix + '/sessions', create)
    application.router.add_get(prefix + '/sessions/{id}', status)
    application.router.add_delete(prefix + '/sessions/{id}', stop)
    application.router.add_post(prefix + '/sessions/{id}/activity', activity)
    application.router.add_get(prefix + '/sessions/{id}/display', display)
    application.router.add_get(prefix + '/audit', audit)
    from .files import routes
    routes(application,gateway)
    application.cleanup_ctx.append(lifecycle)
    return application


def main():
    gateway = Gateway(load(os.environ['ACCESS_CONFIG']), os.environ['ACCESS_SESSIONS'], os.environ['ACCESS_AUDIT_DB'],
        os.environ['ACCESS_AUTH_URL'], os.environ['ACCESS_BROKER_SOCKET'])
    web.run_app(app(gateway), host='0.0.0.0', port=8081, print=None, access_log=None)


if __name__ == '__main__':
    main()
