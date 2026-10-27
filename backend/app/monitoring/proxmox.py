import os
import re
import ssl
import httpx
from app.monitoring.common import result

def select(row, keys):
    return {k: row[k] for k in keys.split(',') if k in row}

async def collect():
    token_id, secret = os.getenv('PROXMOX_TOKEN_ID'), os.getenv('PROXMOX_TOKEN_SECRET')
    if not token_id or not secret:
        return result('proxmox', 'PVE API', error='missing_readonly_token', detail='Proxmox VM/LXC belum disiapkan: token API read-only belum tersedia. Status guest belum dapat diperiksa.')
    host=os.getenv('PROXMOX_HOST','192.168.20.200')
    port=os.getenv('PROXMOX_PORT','8006')
    base = os.getenv('PROXMOX_URL', f'https://{host}:{port}').rstrip('/')
    if not base.startswith('https://'):
        return result('proxmox', 'PVE API', error='https_required')
    if os.getenv('PROXMOX_SSL_VERIFY','true').lower()!='true':
        return result('proxmox','PVE API',error='tls_verification_required',detail='Aktifkan validasi TLS dan sediakan CA Proxmox yang dipercaya; bypass sertifikat tidak diizinkan.')
    try:
        async with httpx.AsyncClient(base_url=base+'/api2/json/', timeout=7, verify=ssl.create_default_context(cafile=os.getenv('PROXMOX_CA_FILE')), follow_redirects=False, trust_env=False,
                headers={'Authorization': f'PVEAPIToken={token_id}={secret}'}) as client:
            async def get(path):
                async with client.stream('GET', path) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 512000:
                            raise ValueError('response_too_large')
                    import json
                    return json.loads(body)['data']
            permissions = await get('access/permissions')
            privileges = {p for values in permissions.values() if isinstance(values, dict) for p, enabled in values.items() if enabled} if isinstance(permissions, dict) else set()
            if not privileges or any(not p.endswith('.Audit') for p in privileges):
                return result('proxmox', 'PVE API', error='excessive_or_unverified_permissions')
            if not {'Sys.Audit', 'VM.Audit', 'Datastore.Audit'}.issubset(privileges):
                return result('proxmox', 'PVE API', error='permission_denied')
            version = await get('version')
            resources = await get('cluster/resources')
            nodes = [select(r,'id,node,status,cpu,maxcpu,mem,maxmem,disk,maxdisk,uptime') for r in resources if r.get('type')=='node'][:16]
            guests = [select(r,'id,vmid,name,node,type,status,cpu,maxcpu,mem,maxmem,disk,maxdisk,uptime,netin,netout,diskread,diskwrite') for r in resources if r.get('type') in {'qemu','lxc'}][:100]
            storage = [select(r,'id,node,storage,status,disk,maxdisk') for r in resources if r.get('type')=='storage'][:50]
            tasks = []
            for node in nodes[:4]:
                if re.fullmatch(r'[\w.-]{1,64}', node['node']):
                    try:
                        tasks += [select(t,'type,status,starttime,endtime') for t in await get('nodes/'+node['node']+'/tasks?limit=10')][:10]
                    except httpx.HTTPError:
                        tasks.append({'status':'UNKNOWN','reason':'task_permission_or_request_failed'})
            return result('proxmox','PVE API (TLS verified)','UP',version=select(version,'version,release'),nodes=nodes,guests=guests,storage=storage,tasks=tasks,readonly_verified=True)
    except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
        error=type(exc).__name__
        if 'certificate_verify_failed' in str(exc).lower() or 'certificate verify failed' in str(exc).lower():error='tls_verification_failed'
        elif isinstance(exc,httpx.TimeoutException):error='timeout'
        elif isinstance(exc,httpx.HTTPStatusError):error='authentication_failed' if exc.response.status_code==401 else ('permission_denied' if exc.response.status_code==403 else 'api_http_error')
        return result('proxmox','PVE API',error=error,detail='Data node/VM belum dapat diverifikasi; autentikasi dan TLS tetap diwajibkan.')
