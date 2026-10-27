import asyncio
from contextlib import contextmanager
import os
import re
import ssl
import httpx
import routeros_api
from app.dashboard import models
from app.logging_config import redact

OPERATIONS={
 'routeros.interface.comment':{'permission':'network.change','risk':'LOW','impact':'Mengubah deskripsi satu interface. Tidak mengubah link, VLAN, route atau firewall. Pemulihan melalui preview baru dengan nilai komentar sebelumnya.'},
 **{'proxmox.guest.'+action:{'permission':'server.operate','risk':'HIGH','impact':'Mengubah daya guest. Shutdown/reboot dapat menghentikan aplikasi dan sesi pengguna. Tidak tersedia rollback transaksi; pemulihan membutuhkan operasi daya baru yang disetujui.'} for action in ('start','shutdown','reboot')},
}

def validate(operation,value):
 if not isinstance(operation,str) or operation not in OPERATIONS:raise ValueError('unsupported_operation')
 if operation.startswith('routeros.'):
  models.fields(value,('interface','comment'),('interface','comment'))
  name=models.text(value['interface'],1,80)
  if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}',name):raise ValueError('invalid_interface')
  comment=models.text(value['comment'],0,120)
  if redact(comment)!=comment:raise ValueError('sensitive_comment')
  return {'interface':name,'comment':comment}
 models.fields(value,('node','kind','vmid'),('node','kind','vmid'))
 node=models.text(value['node'],1,64)
 if not re.fullmatch(r'[A-Za-z0-9_.-]+',node) or value['kind'] not in {'qemu','lxc'}:raise ValueError('invalid_guest')
 return {'node':node,'kind':value['kind'],'vmid':models.integer(value['vmid'],100,999999999)}

class Adapters:
 def __init__(self,router=None):self.router=router

 @contextmanager
 def router_api(self):
  if not self.router:raise ValueError('router_unavailable')
  if not self.router.lock.acquire(timeout=3):raise ValueError('collector_busy')
  pool=None
  try:
   port=int(os.getenv('MIKROTIK_PORT','8729'));secure=port==8729
   if not secure and os.getenv('MIKROTIK_ALLOW_PLAINTEXT','false').lower()!='true':raise ValueError('plaintext_not_allowed')
   if secure and os.getenv('MIKROTIK_SSL_VERIFY','true').lower()!='true':raise ValueError('tls_verification_required')
   pool=routeros_api.RouterOsApiPool(os.getenv('MIKROTIK_HOST','192.168.20.1'),username=os.environ['MIKROTIK_USER'],password=os.environ['MIKROTIK_PASSWORD'],port=port,
       use_ssl=secure,ssl_verify=True,ssl_verify_hostname=True,ssl_context=ssl.create_default_context(cafile=os.getenv('MIKROTIK_CA_FILE') or None) if secure else None,plaintext_login=True)
   pool.socket_timeout=3;api=pool.get_api();pool.set_timeout(3)
   users=api.get_resource('/user').call('print',{'.proplist':'name,group'},{'name':os.environ['MIKROTIK_USER']})
   if len(users)!=1:raise ValueError('permission_unverified')
   groups=api.get_resource('/user/group').call('print',{'.proplist':'name,policy'},{'name':users[0]['group']})
   policy=set(groups[0].get('policy','').split(',')) if len(groups)==1 else set()
   if not {'api','read'}<=policy:raise ValueError('permission_denied')
   yield api,policy,secure
  finally:
   try:
    if pool:pool.disconnect()
   finally:self.router.lock.release()

 @staticmethod
 def interface(api,name):
  rows=api.get_resource('/interface').call('print',{'.proplist':'.id,name,comment,disabled,running'},{'name':name})
  if len(rows)!=1:raise ValueError('interface_not_found')
  row=rows[0];identity=row.get('id',row.get('.id',''))
  if not re.fullmatch(r'\*[A-Fa-f0-9]+',identity):raise ValueError('invalid_resource_id')
  comment=row.get('comment','')
  if not isinstance(comment,str) or len(comment)>120 or redact(comment)!=comment:raise ValueError('comment_not_safe_to_preview')
  return {'id':identity,'name':row['name'],'comment':comment,'disabled':row.get('disabled'),'running':row.get('running')}

 async def inspect(self,operation,params):
  if operation.startswith('routeros.'):
   if os.getenv('MIKROTIK_PORT','8729')!='8729':
    # A write plan is blocked before opening an extra plaintext management session.
    # Display only a previously observed interface; execution still rechecks live data.
    snapshot=getattr(self.router,'snapshots',{}).get(('interfaces','',''))
    rows=snapshot[1].get('data',{}).get('/interface',[]) if snapshot else []
    row=next((r for r in rows if r.get('name')==params['interface']),None)
    before={k:redact(str(row[k]))[:120] for k in ('id','name','comment','disabled','running') if row and k in row}
    return {'before':before or {'name':params['interface']},'before_source':'shared_monitoring_cache' if row else 'no_current_interface_sample',
        'allowed':False,'blocker':'verified_api_ssl_required_for_writes','target':os.getenv('MIKROTIK_HOST','192.168.20.1')}
   def read():
    with self.router_api() as (api,policy,secure):
     return {'before':self.interface(api,params['interface']),'allowed':bool(secure and 'write' in policy),
         'blocker':None if secure and 'write' in policy else 'verified_api_ssl_required_for_writes' if not secure else 'write_permission_required',
         'target':os.getenv('MIKROTIK_HOST','192.168.20.1')}
   return await asyncio.to_thread(read)
  async with self.pve_client() as client:
   permission=await self.pve_get(client,'access/permissions',params={'path':'/vms/'+str(params['vmid'])})
   privileges={p for v in permission.values() if isinstance(v,dict) for p,yes in v.items() if yes} if isinstance(permission,dict) else set()
   current=await self.pve_get(client,self.guest_path(params)+'/status/current')
   action=operation.rsplit('.',1)[-1];state=current.get('status')
   enabled=os.getenv('PROXMOX_MANAGEMENT_ENABLED','false').lower()=='true'
   allowed=enabled and 'VM.PowerMgmt' in privileges and (state=='stopped' if action=='start' else state=='running')
   return {'before':{'status':state,'vmid':params['vmid'],'node':params['node'],'kind':params['kind']},'allowed':allowed,
       'blocker':None if allowed else 'proxmox_monitoring_only_policy' if not enabled else 'power_permission_required' if 'VM.PowerMgmt' not in privileges else 'guest_state_conflict',
       'target':os.getenv('PROXMOX_HOST','192.168.20.200')}

 @staticmethod
 def guest_path(p):return f"nodes/{p['node']}/{p['kind']}/{p['vmid']}"

 @staticmethod
 def pve_client():
  from urllib.parse import urlsplit
  base=os.getenv('PROXMOX_URL',f"https://{os.getenv('PROXMOX_HOST','192.168.20.200')}:{os.getenv('PROXMOX_PORT','8006')}").rstrip('/')
  if urlsplit(base).scheme!='https' or os.getenv('PROXMOX_SSL_VERIFY','true').lower()!='true':raise ValueError('tls_required')
  identity=os.getenv('PROXMOX_MANAGEMENT_TOKEN_ID') or os.getenv('PROXMOX_TOKEN_ID')
  secret=os.getenv('PROXMOX_MANAGEMENT_TOKEN_SECRET') or os.getenv('PROXMOX_TOKEN_SECRET')
  if not identity or not secret:raise ValueError('credentials_missing')
  return httpx.AsyncClient(base_url=base+'/api2/json/',verify=ssl.create_default_context(cafile=os.getenv('PROXMOX_CA_FILE') or None),timeout=3,follow_redirects=False,trust_env=False,
      headers={'Authorization':f'PVEAPIToken={identity}={secret}'})

 @staticmethod
 async def pve_get(client,path,params=None):
  async with client.stream('GET',path,params=params) as response:
   response.raise_for_status();data=bytearray()
   async for part in response.aiter_bytes():
    data.extend(part)
    if len(data)>256000:raise ValueError('response_limit')
   import json
   return json.loads(data)['data']

 async def execute(self,operation,params,before):
  # Recheck live state and device permission immediately before the single write.
  inspected=await self.inspect(operation,params)
  if not inspected['allowed']:return {'state':'BLOCKED','error':inspected['blocker']}
  if inspected['before']!=before:return {'state':'CONFLICT','error':'device_changed_since_preview'}
  if operation.startswith('routeros.'):
   def write():
    with self.router_api() as (api,policy,secure):
     if not secure or 'write' not in policy:raise ValueError('write_permission_required')
     if self.interface(api,params['interface'])!=before:return {'state':'CONFLICT','error':'device_changed_since_preview'}
     api.get_resource('/interface').call('set',{'.id':before['id'],'comment':params['comment']})
     after=self.interface(api,params['interface']);self.router.snapshots.clear()
     return {'state':'VERIFIED' if after['comment']==params['comment'] else 'UNKNOWN','after':after}
   return await asyncio.to_thread(write)
  async with self.pve_client() as client:
   # Never retry a mutation after timeout: its outcome might already have occurred.
   response=await client.post(self.guest_path(params)+'/status/'+operation.rsplit('.',1)[-1],data={})
   response.raise_for_status()
   if len(response.content)>4096:raise ValueError('response_limit')
   task=response.json().get('data')
   if not isinstance(task,str) or not task.startswith('UPID:'):return {'state':'UNKNOWN','error':'invalid_task_response'}
   from urllib.parse import quote
   for _ in range(10):
    await asyncio.sleep(3)
    status=await self.pve_get(client,'nodes/'+params['node']+'/tasks/'+quote(task,safe='')+'/status')
    if status.get('status')=='stopped':
     current=await self.pve_get(client,self.guest_path(params)+'/status/current')
     expected='stopped' if operation.endswith('.shutdown') else 'running'
     return {'state':'VERIFIED' if status.get('exitstatus')=='OK' and current.get('status')==expected else 'FAILED','after':{'status':current.get('status')},'task_exit':status.get('exitstatus','UNKNOWN')}
   return {'state':'UNKNOWN','error':'task_not_completed_in_verification_window'}
