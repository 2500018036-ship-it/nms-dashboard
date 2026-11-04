"""Local Unix-only, fixed-image Docker launcher. No caller-controlled Docker args."""
import asyncio
from contextlib import closing
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import time
from aiohttp import web
from .policy import check_sid, load, origin, target


class Broker:
    def __init__(self, config, root, image, seccomp, inventory):
        self.config, self.root, self.image, self.seccomp, self.inventory = config, Path(root).resolve(), image, seccomp, inventory
        self.workers = {}
        self.lock = asyncio.Lock()

    async def docker(self, *args):
        process = await asyncio.create_subprocess_exec('docker', *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 35)
        except BaseException:
            process.kill()
            await process.wait()
            raise
        if process.returncode:
            raise RuntimeError('browser_runtime_failed')
        return stdout.decode().strip()

    def selected(self, identity):
        if re.fullmatch(r'(?:inv_|int_)[a-f0-9]{24}|svc_[a-f0-9]{20}',identity or ''):
            with closing(sqlite3.connect('file:'+self.inventory+'?mode=ro',uri=True,timeout=3)) as db:
                row=db.execute("SELECT collection,payload FROM objects WHERE id=? AND collection IN ('inventory','integrations')",(identity,)).fetchone()
                check=db.execute('SELECT url,checked,payload FROM portal_checks WHERE target_id=?',(identity,)).fetchone()
                policy=db.execute('SELECT payload FROM platform_settings WHERE id=1').fetchone()
            if not row or not check or not policy:raise ValueError('portal_not_verified')
            value=json.loads(row[1]);url=value.get('dashboard_url') if row[0]=='inventory' else value.get('url')
            probe=json.loads(check[2])
            if not value.get('enabled') or not url or url!=check[0] or time.time()-check[1]>=900 or not probe.get('reachable'):raise ValueError('portal_not_verified')
            from urllib.parse import urlsplit
            if urlsplit(url).hostname not in json.loads(policy[0]).get('allowed_hosts',[]):raise ValueError('host_not_allowed')
            # Origins are fixed by the verified server record, never by browser request parameters.
            reviewed=next((v for v in self.config['targets'] if v['url'].rstrip('/')==url.rstrip('/')), {})
            selected={'id':identity,'name':value['name'],'url':url,'roles':['Administrator','Super Administrator','Network Administrator','Server Administrator']}
            ip=probe['connect_ip']
            import ipaddress
            address=ipaddress.IPv4Address(ip)
            if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:raise ValueError('invalid_connect_address')
            try:ipaddress.IPv4Address(urlsplit(url).hostname)
            except ValueError:selected['connect_ip']=ip
            else:
                if urlsplit(url).hostname!=ip:raise ValueError('invalid_connect_address')
            for field in ('tls_spki','asset_origins'):
                if field in reviewed:selected[field]=reviewed[field]
            origin(url,selected.get('connect_ip'))
            return selected
        selected = dict(target(self.config, identity))
        mac = selected.get('inventory_mac')
        if mac:
            with closing(sqlite3.connect('file:' + self.inventory + '?mode=ro', uri=True, timeout=3)) as db:
                rows = db.execute("SELECT payload FROM objects WHERE collection='inventory' AND upper(json_extract(payload,'$.mac_address'))=?", (mac.upper(),)).fetchall()
            matches = [json.loads(row[0]) for row in rows if json.loads(row[0]).get('enabled')]
            if len(matches) != 1:
                raise ValueError('device_address_unavailable')
            # Only the verified registry address can replace this audited HTTP origin.
            scheme, _, port = origin(selected['url'])
            selected['url'] = f'{scheme}://{matches[0]["host"]}:{port}/'
            origin(selected['url'])
        return selected

    async def create(self, identity, target_id):
        check_sid(identity)
        async with self.lock:
            if len(self.workers) >= self.config['max_sessions'] or identity in self.workers:
                raise web.HTTPConflict(text='access_capacity_reached')
            selected = self.selected(target_id)
            directory = self.root / identity
            directory.mkdir(mode=0o700)
            os.chown(directory, 31000, 31000)
            start = directory / 'start.json'
            start.write_text(json.dumps({'url': selected['url'], 'tls_spki': selected.get('tls_spki', [])}))
            start.chmod(0o644)
            try:
                image = self.image
                if os.getenv('ACCESS_WORKER_IMAGE_FILE'):
                    image = Path(os.environ['ACCESS_WORKER_IMAGE_FILE']).read_text().strip()
                    if not re.fullmatch(r'theaz-access-worker:[a-f0-9]{40}', image):
                        raise ValueError('invalid_worker_image')
                await self.docker('run', '-d', '--name', 'theaz-access-' + identity,
                    '--label', 'theaz.access.managed=true', '--network', 'none', '--user', '31000:31000',
                    '--read-only', '--init', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                    '--security-opt', 'seccomp=' + self.seccomp, '--memory', '1g', '--cpus', '0.75',
                    '--pids-limit', '256', '--shm-size', '128m', '--tmpfs', '/tmp:rw,nosuid,nodev,size=128m,mode=1777',
                    '--mount', f'type=bind,src={directory},dst=/run/session', image)
            except BaseException:
                self.erase(identity)
                raise
            now = time.time()
            self.workers[identity] = {'id': identity, 'target': target_id, 'created': now,
                'expires': now + self.config['lifetime_seconds'], 'lease': now}
            return {**self.workers[identity], 'url': selected['url'], **({'connect_ip':selected['connect_ip']} if selected.get('connect_ip') else {}), **({'asset_origins':selected['asset_origins']} if selected.get('asset_origins') else {})}

    def erase(self, identity):
        check_sid(identity)
        path = self.root / identity
        if path.parent.resolve() != self.root or path.is_symlink():
            raise ValueError('invalid_session_path')
        if path.exists():
            shutil.rmtree(path)

    async def stop(self, identity):
        check_sid(identity)
        if identity in self.workers:
            name='theaz-access-'+identity
            try:
                await self.docker('rm', '-f', name)
            except (RuntimeError, OSError):
                # The daemon can finish removal after the CLI times out. Confirm
                # absence before releasing capacity; retain real workers on failure.
                remaining=await self.docker('ps','-a','--filter','name=^/'+name+'$','--filter','label=theaz.access.managed=true','--format','{{.ID}}')
                if remaining:raise
            self.workers.pop(identity,None)
            self.erase(identity)

    async def recover(self):
        # Reap only containers owned by this runtime, never unrelated containers.
        names = await self.docker('ps', '-a', '--filter', 'label=theaz.access.managed=true', '--format', '{{.Names}}')
        for name in names.splitlines():
            identity = name.removeprefix('theaz-access-')
            if name == 'theaz-access-' + identity:
                check_sid(identity)
                await self.docker('rm', '-f', name)
                self.erase(identity)

    async def reap(self):
        while True:
            await asyncio.sleep(10)
            for identity, item in list(self.workers.items()):
                if time.time() > min(item['expires'], item['lease'] + 90):
                    try:
                        await self.stop(identity)
                    except (RuntimeError, OSError):
                        pass


def app(broker):
    async def create(request):
        body = await request.json()
        if set(body) != {'id', 'target'}:
            raise web.HTTPBadRequest()
        try:
            return web.json_response(await broker.create(body['id'], body['target']))
        except (ValueError, KeyError, StopIteration):
            raise web.HTTPBadRequest(text='invalid_target')

    async def lease(request):
        identity = check_sid(request.match_info['id'])
        if identity not in broker.workers:
            raise web.HTTPNotFound()
        broker.workers[identity]['lease'] = time.time()
        return web.json_response({'ok': True})

    async def stop(request):
        await broker.stop(check_sid(request.match_info['id']))
        return web.json_response({'ok': True})

    async def lifecycle(application):
        await broker.recover()
        task = asyncio.create_task(broker.reap())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        for identity in list(broker.workers):
            await broker.stop(identity)

    application = web.Application(client_max_size=4096)
    application.router.add_post('/workers', create)
    application.router.add_post('/workers/{id}/lease', lease)
    application.router.add_delete('/workers/{id}', stop)
    application.cleanup_ctx.append(lifecycle)
    return application


def main():
    config = load(os.environ['ACCESS_CONFIG'])
    broker = Broker(config, os.environ['ACCESS_SESSIONS'], os.environ['ACCESS_WORKER_IMAGE'],
        os.environ['ACCESS_SECCOMP'], os.environ['ACCESS_INVENTORY_DB'])
    path = Path(os.environ['ACCESS_BROKER_SOCKET'])
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    # The group must exist before startup. Socket permissions are enforced by umask.
    os.umask(0o007)
    os.chown(path.parent, 0, 31000)
    web.run_app(app(broker), path=str(path), print=None, access_log=None)


if __name__ == '__main__':
    main()
