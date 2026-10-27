"""Owner-authenticated, bounded transfer area; never expose browser profiles."""
import os
from pathlib import Path
import re
import secrets
import stat
from aiohttp import web

MAX_FILE = 15 * 1024 * 1024


def folder(gateway, item, kind):
    base = gateway.directory(item.id)
    path = base / kind
    if kind not in {'uploads', 'downloads'} or path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
        raise web.HTTPForbidden()
    path.mkdir(mode=0o700, exist_ok=True)
    return path


def routes(application, gateway):
    async def upload(request):
        item, _ = await gateway.owned(request)
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != 'file' or not part.filename:
            raise web.HTTPBadRequest(text='invalid_file')
        name = re.sub(r'[^A-Za-z0-9._-]', '_', Path(part.filename).name)[:100].lstrip('.')
        if not name:
            raise web.HTTPBadRequest(text='invalid_file')
        path = folder(gateway, item, 'uploads') / (secrets.token_hex(4) + '-' + name)
        size = 0
        try:
            with path.open('xb') as stream:
                path.chmod(0o600)
                while chunk := await part.read_chunk(65536):
                    size += len(chunk)
                    if size > MAX_FILE:
                        raise web.HTTPRequestEntityTooLarge(max_size=MAX_FILE, actual_size=size)
                    stream.write(chunk)
            if await reader.next() is not None:
                raise web.HTTPBadRequest(text='one_file_required')
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        gateway.record(item.actor, item.target, item.id, 'access.file_uploaded', 'bytes:' + str(size))
        return web.json_response({'ok': True, 'remote_path': '/run/session/uploads/' + path.name})

    async def listing(request):
        item, _ = await gateway.owned(request)
        directory = folder(gateway, item, 'downloads')
        values = [{'name': p.name, 'bytes': p.stat().st_size} for p in directory.iterdir()
            if p.is_file() and not p.is_symlink() and re.fullmatch(r'[A-Za-z0-9._ -]{1,150}', p.name)
            and not p.name.endswith('.crdownload') and p.stat().st_size <= MAX_FILE][:100]
        return web.json_response({'items': values})

    async def download(request):
        item, _ = await gateway.owned(request)
        name = request.match_info['name']
        if not re.fullmatch(r'[A-Za-z0-9._ -]{1,150}', name) or name in {'.', '..'}:
            raise web.HTTPBadRequest(text='invalid_file')
        path = folder(gateway, item, 'downloads') / name
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        except OSError:
            raise web.HTTPNotFound()
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise web.HTTPForbidden()
            response = web.StreamResponse(headers={'Content-Type': 'application/octet-stream',
                'Content-Disposition': 'attachment; filename="' + name + '"', 'Content-Length': str(info.st_size),
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
            await response.prepare(request)
            while chunk := stream.read(65536):
                await response.write(chunk)
        gateway.record(item.actor, item.target, item.id, 'access.file_downloaded', 'bytes:' + str(info.st_size))
        return response

    prefix = '/access-api/sessions/{id}'
    application.router.add_post(prefix + '/upload', upload)
    application.router.add_get(prefix + '/downloads', listing)
    application.router.add_get(prefix + '/downloads/{name}', download)
