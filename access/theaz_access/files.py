"""Owner-authenticated, bounded transfer area; never expose browser profiles."""
import os
from contextlib import contextmanager
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


@contextmanager
def directory(gateway, item, kind):
    # Linux runtime: pin the directory inode across asynchronous file transfers.
    descriptor = os.open(folder(gateway, item, kind), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


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
        name = secrets.token_hex(4) + '-' + name
        size = 0
        with directory(gateway, item, 'uploads') as descriptor:
            try:
                file = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
                with os.fdopen(file, 'wb') as stream:
                    while chunk := await part.read_chunk(65536):
                        size += len(chunk)
                        if size > MAX_FILE:
                            raise web.HTTPRequestEntityTooLarge(max_size=MAX_FILE, actual_size=size)
                        stream.write(chunk)
                if await reader.next() is not None:
                    raise web.HTTPBadRequest(text='one_file_required')
            except BaseException:
                try:os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:pass
                raise
        gateway.record(item.actor, item.target, item.id, 'access.file_uploaded', 'bytes:' + str(size))
        return web.json_response({'ok': True, 'remote_path': '/run/session/uploads/' + name})

    async def listing(request):
        item, _ = await gateway.owned(request)
        values = []
        with directory(gateway, item, 'downloads') as descriptor:
            for name in os.listdir(descriptor):
                if len(values) >= 100:break
                if not re.fullmatch(r'[A-Za-z0-9._ -]{1,150}', name) or name.endswith('.crdownload'):continue
                try:info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except FileNotFoundError:continue
                if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE:values.append({'name':name, 'bytes':info.st_size})
        return web.json_response({'items': values})

    async def download(request):
        item, _ = await gateway.owned(request)
        name = request.match_info['name']
        if not re.fullmatch(r'[A-Za-z0-9._ -]{1,150}', name) or name in {'.', '..'}:
            raise web.HTTPBadRequest(text='invalid_file')
        try:
            with directory(gateway, item, 'downloads') as parent:
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
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
