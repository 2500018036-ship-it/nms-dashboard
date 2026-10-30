import asyncio
import time
import os
import json
import hashlib
from collections import Counter
from app.ai.tool_registry import Tool
from app.monitoring import tcp, dns, web, proxmox,icmp
from app.dashboard.platform import Platform
from app.monitoring.service_probe import probe as service_probe
from app.alerts.network import duration
from app.monitoring.docker_monitor import read_snapshot
from app.monitoring.mikrotik import MikroTik
from app.monitoring.mikrotik_catalog import SECTIONS, FILTER_FIELDS
from app.monitoring.common import result

EMPTY = {'type':'object','properties':{},'additionalProperties':False}

class Monitoring:
    def __init__(self, settings, database):
        self.settings, self.database = settings, database
        self.platform=Platform(str(__import__('pathlib').Path(database.db.execute('PRAGMA database_list').fetchone()[2]).parent),settings)
        self.platform.apply(settings)
        from app.dashboard.credentials import CredentialVault
        self.credentials=CredentialVault(self.platform)
        self.router = MikroTik(settings)
        from app.dashboard.device_backups import DeviceConfigBackups
        self.device_backups = DeviceConfigBackups(self.platform, self)
        self.cache, self.locks, self.metrics = {}, {}, Counter()
        self.semaphore = asyncio.Semaphore(3)
        self.extra_targets=['wireguard','cisco_sf200','mikrotik_routes','network_traffic'] if settings.continuous_enabled else []

    def capabilities(self):
        return {'configured_inventory':[{'id':d['id'],'name':d['name'],'host':d['host'],'enabled':d['enabled'],'method':d.get('monitor_method',''),'collector':self.platform.inventory_target(d)} for d in self.platform.list('inventory')],'service_integrations':[{'id':r['id'],'name':r['name'],'collector':r['collector'],'scheduled_http':r['monitor_enabled'],'enabled':r['enabled']} for r in self.platform.list('integrations')], 'continuous_monitoring':{'configured':self.settings.continuous_enabled,'interface_interval_seconds':self.settings.network_interval,
            'alerts_enabled':self.settings.alerts,
            'event_history_tool':'get_incidents','switch_scope':'LLDP/uplink MikroTik; 24 port Cisco belum tersedia tanpa akses manajemen',
            'alerts_independent_of_ai':True},'proxmox_vm_api_configured':bool(os.getenv('PROXMOX_TOKEN_ID') and os.getenv('PROXMOX_TOKEN_SECRET')),
            'proxmox_vm_api':('Konfigurasi token tersedia; status aktual tetap perlu tool.'
            if os.getenv('PROXMOX_TOKEN_ID') and os.getenv('PROXMOX_TOKEN_SECRET') else
            'Belum disiapkan: token API read-only belum ada. Jangan mengklaim status/resource node, VM atau LXC.'),
            'mikrotik':'Izin akun diperiksa saat query. Kredensial terisi belum berarti API siap; ikuti status/error tool.',
            'scope':'Collector yang belum disiapkan dipisahkan dari gangguan layanan. HTTP/TCP Proxmox tidak membuktikan VM sehat.'}

    async def check(self, target, force=False):
        if target in self.settings.targets:
            source=self.platform.source(target=target)
            item=self.platform.get('inventory',source[1]) if source else None
            if source and (not item or not item['enabled']):return result(target,'registry',error='monitoring_disabled')
        if target.startswith('inventory_'):
            item=self.platform.get('inventory',target.removeprefix('inventory_'))
            if item and item['enabled']:
                canonical=self.platform.inventory_target(item)
                if canonical and canonical!=target:return await self.check(canonical,force=force)
        async with self.locks.setdefault(target, asyncio.Lock()):
            service=self.platform.get('integrations',target.removeprefix('service_')) if target.startswith('service_') else None
            device=self.platform.get('inventory',target.removeprefix('inventory_')) if target.startswith('inventory_') else None
            source=self.platform.source(target=target)
            source_item=self.platform.get('inventory',source[1]) if source else None
            if source_item and target in self.settings.targets and self.settings.targets[target].get('kind')=='icmp':device=source_item
            ttl=service['poll_interval'] if service else device['interval'] if device else 60
            configuration=hashlib.sha256(json.dumps(device,sort_keys=True).encode()).hexdigest() if device else hashlib.sha256(service['url'].encode()).hexdigest() if service else None
            if not force and target in self.cache and time.monotonic()-self.cache[target][0] < ttl and (configuration is None or self.cache[target][1].get('configuration_hash')==configuration):
                return self.cache[target][1]
            async with self.semaphore:
                try:
                    # RouterOS has its own 19-second request budget including lock
                    # wait; leave room for thread scheduling and SQLite bookkeeping.
                    router_target=target.startswith('mikrotik_') or target in {'wireguard','cisco_sf200'}
                    async with asyncio.timeout(35 if device and device.get('follow_dhcp') else 25 if router_target else 20):
                        value = await self._collect(target)
                except Exception as exc:
                    value = result(target,'collector',error=type(exc).__name__)
            if device:value['configuration_hash']=configuration
            self.metrics[value['status']] += 1
            self.cache[target] = (time.monotonic(), value)
            self.database.save(value)
            return value

    async def _collect(self, target):
        if target.startswith('inventory_'):
            from app.monitoring.inventory import collect,scheduled
            item=self.platform.get('inventory',target.removeprefix('inventory_'))
            if not item or not scheduled(item):return result(target,'inventory',error='target_not_allowed')
            canonical=self.platform.inventory_target(item)
            if canonical!=target:return result(target,'inventory',error='use_shared_collector')
            previous=self.database.history(target,1)
            try:credentials=self.credentials.collector_credentials('inventory',item['id']) if item.get('monitor_method') in {'snmp','ssh'} else None
            except Exception as exc:
                from app.dashboard.credentials import CredentialVaultUnavailable
                if isinstance(exc,CredentialVaultUnavailable):return result(target,item.get('monitor_method','SNMP').upper(),error='credential_vault_unavailable')
                raise
            value=await self.icmp_device(target,item) if item.get('monitor_method')=='icmp' else await collect(item,self.platform.get_settings()['value']['allowed_hosts'],credentials,previous[0] if previous else None)
            return {**value,'configuration_hash':hashlib.sha256(json.dumps(item,sort_keys=True).encode()).hexdigest()}
        if target.startswith('service_'):
            service=self.platform.get('integrations',target.removeprefix('service_'))
            if not service or not service['enabled'] or not service['monitor_enabled']:return result(target,'allowlist',error='target_not_allowed')
            value=await service_probe(target,service['url'],self.platform.get_settings()['value']['allowed_hosts'])
            return {**value,'display_name':service['name']}
        if target=='wireguard' and self.settings.continuous_enabled:
            value=await self.router.collect('wireguard_peers')
            value['target']=target
            if value['status'] in {'UP','DEGRADED'}:
                value['peers']=[{**row,'handshake_age_seconds':duration(row.get('last-handshake'))}
                    for row in value.get('data',{}).get('/interface/wireguard/peers',[])]
                value['scope']='Handshake aktual, bukan jaminan aplikasi melewati VPN. Key tidak dibaca.'
            return value
        if target=='mikrotik_routes' and self.settings.continuous_enabled:
            return {**await self.router.collect('routes'),'target':target}
        if target=='cisco_sf200' and self.settings.continuous_enabled:
            neighbors=await self.router.collect('neighbors')
            management_host=self.settings.switch.get('management_host')
            return result(target,'LLDP dari MikroTik',error='missing_switch_management',
                host=management_host,
                neighbors=[r for r in neighbors.get('data',{}).get('/ip/neighbor',[]) if 'cisco' in r.get('platform','').lower()],
                uplinks=self.settings.switch.get('uplinks',[]),management_configured=False,
                neighbor_read_status=neighbors['status'],detail=('IP manajemen sudah dicatat; SNMP/SSH belum terintegrasi dan keterjangkauan harus diverifikasi. Status port internal, VLAN, CPU/RAM belum diketahui.' if management_host else 'Cisco teridentifikasi saat audit. IP manajemen/kredensial belum diketahui; port internal, CPU dan SNMP/traps switch belum dapat dipastikan.'))
        if target=='network_traffic' and self.settings.continuous_enabled:
            history=self.database.history(target,1)
            return history[0] if history and time.time()-self.database.db.execute('SELECT ts FROM checks WHERE target=? ORDER BY id DESC LIMIT 1',(target,)).fetchone()[0]<120 else result(target,'delta counter',error='waiting_for_samples')
        if target.startswith('mikrotik_') and target.split('_',1)[1] in {'system','interfaces','network','vlan'}:
            value = await self.router.collect(target.split('_',1)[1])
            value['target'] = target
            return value
        if target == 'proxmox_resources':
            return {**await proxmox.collect(),'target':target}
        if target in {'docker','debian'}:
            value=read_snapshot(self.settings.snapshot_dir,target)
            if target=='docker':
                for container in value.get('containers',[]):
                    container['expected_running']=container['name'] not in self.settings.docker_ignored_containers
            return value
        if target not in self.settings.targets:
            return result(target,'allowlist',error='target_not_allowed')
        t = self.settings.targets[target]
        if t['kind']=='icmp':
            source=self.platform.source(target=target)
            item=self.platform.get('inventory',source[1]) if source else None
            if item and item['enabled']:
                value=await self.icmp_device(target,item)
            else:value=await icmp.probe(target,t['host'])
            return {**value,'display_name':item['name'] if item else t['name'],'alert_on_unreachable':t.get('alert_on_unreachable',False)}
        if t['kind']=='tcp':
            return await tcp.probe(target,t['host'],t['port'])
        if t['kind']=='dns':
            return await dns.probe(target,t['host'],t['port'],t['query'])
        return await web.probe(target,t['url'])

    async def icmp_device(self,target,item):
        if item['host'] not in self.platform.get_settings()['value']['allowed_hosts']:
            return result(target,'inventory',error='host_not_allowed',host=item['host'])
        value=await icmp.probe(target,item['host'])
        if value['status']=='DOWN' and item.get('follow_dhcp'):
            from app.dashboard.device_registry import dhcp_address,move
            lease=await self.router.collect('dhcp_leases',limit=100)
            metadata=lease.get('resources',{}).get('/ip/dhcp-server/lease',{})
            if lease['status']=='UP' and not metadata.get('has_more') and not metadata.get('scan_truncated'):
                address=dhcp_address(item,lease.get('data',{}).get('/ip/dhcp-server/lease',[]),self.platform.configured_hosts())
                if address and address!=item['host']:
                    updated=await icmp.probe(target,address)
                    if updated['status']=='UP' and move(self.platform,item['id'],item['host'],address):
                        value={**updated,'address_source':'dhcp_mac','previous_host':item['host']}
        return {**value,'display_name':item['name']}

    async def all(self):
        services=['service_'+s['id'] for s in self.platform.list('integrations') if s['enabled'] and s['monitor_enabled']]
        from app.monitoring.inventory import scheduled
        inventory=[self.platform.inventory_target(d) for d in self.platform.list('inventory') if scheduled(d)]
        inventory=[t for t in inventory if t.startswith('inventory_')]
        configured=[]
        for key in self.settings.targets:
            source=self.platform.source(target=key)
            item=self.platform.get('inventory',source[1]) if source else None
            if not source or item and item['enabled']:configured.append(key)
        retired=set(self.settings.targets)-set(configured)
        for key,state in self.database.states().items():
            if state.get('active') and (key.startswith(('service_','inventory_')) and key.split(':',1)[0] not in services+inventory or key.split(':',1)[0] in retired or any(key=='network:device:'+target for target in retired)):
                state.update(active=False,retired=True);state.pop('pending',None);self.database.set_state(key,state)
                self.database.event(key,'RETIRED',{'reason':'integration_disabled_or_removed'})
        targets = list(dict.fromkeys(inventory+services+configured+['mikrotik_system','mikrotik_interfaces','proxmox_resources','docker','debian']+self.extra_targets))
        router_targets = ['mikrotik_system','mikrotik_interfaces']+[t for t in self.extra_targets if t!='network_traffic']
        other_targets = [t for t in targets if t not in router_targets]
        async def router_sequence():
            # Each check gets its own timeout after the previous router check.
            # Otherwise the interface timeout is spent waiting for system login.
            return [await self.check(t) for t in router_targets]
        others, router = await asyncio.gather(
            asyncio.gather(*(self.check(t) for t in other_targets)), router_sequence())
        by_target = dict(zip(other_targets, others)) | dict(zip(router_targets, router))
        results = [by_target[t] for t in targets]
        return {'results': results,'counts': dict(Counter(r['status'] for r in results))}

    async def compare(self, target):
        current = await self.check(target)
        history = self.database.history(target,2)
        return {'target':target,'current':current,'previous':history[1] if len(history)>1 else None,'note':'Data sebelumnya belum tersedia' if len(history)<2 else 'Bandingkan timestamp; hasil cache bisa berumur sampai 60 detik'}

    async def overview(self):
        """All target statuses, bounded detail. Full collectors remain available separately."""
        value=await self.all()
        output=[]
        scalar=('target','status','method','timestamp','error','detail','display_name','latency_ms','http_status','host',
            'cpu_percent','memory_percent','memory_total','memory_available','uptime_seconds','age_seconds')
        groups={'containers':('name','state','health','expected_running','cpu_percent','memory_bytes','restart_count'),
            'peers':('name','interface','disabled','handshake_age_seconds','rx','tx'),
            'guests':('vmid','name','node','type','status','cpu','mem'),
            'nodes':('node','status','cpu','mem','maxmem'),'disks':('path','used_percent'),
            'interfaces':('name','rx_bps','tx_bps','sample_seconds','capacity_bps','utilization_percent','rx_percent','tx_percent','duplex')}
        for row in value['results']:
            small={key:(item[:240] if isinstance(item,str) else item) for key,item in row.items() if key in scalar}
            small['summary_only']=True
            for group,fields in groups.items():
                if isinstance(row.get(group),list):
                    items=row[group]
                    small[group]=[{k:v for k,v in item.items() if k in fields} for item in items[:20]]
                    small[group+'_available']=len(items)
            data=row.get('data',{})
            if row['target']=='mikrotik_system':small['resource']=data.get('/system/resource',[{}])[0] if data.get('/system/resource') else {}
            if row['target']=='mikrotik_interfaces':
                interfaces=data.get('/interface',[])
                small['interfaces']=[{k:v for k,v in r.items() if k in {'name','type','running','disabled','rx-error','tx-error'}} for r in interfaces[:20]]
                small['interfaces_available']=len(interfaces)
            if row['target']=='mikrotik_routes':
                routes=data.get('/ip/route',[]);small['routes_available']=len(routes)
                small['default_routes']=[r for r in routes if r.get('dst-address')=='0.0.0.0/0'][:5]
            if row['target']=='cisco_sf200':small['management_configured']=False
            output.append(small)
        summary={'results':output,'counts':value['counts'],'summary_only':True,
            'scope':'Status semua target yang diperiksa; field/detail dibatasi. Gunakan check_service atau get_mikrotik_data untuk data rinci; available menghitung baris dalam hasil collector, bukan menjamin seluruh infrastruktur.'}
        # Keep every status even when an administrator configures many guests/ports.
        while len(json.dumps(summary,ensure_ascii=False))>20000:
            reduced=False
            for row in output:
                for key,items in row.items():
                    if isinstance(items,list) and len(items)>1:items.pop();reduced=True
            if not reduced:break
        return summary

    def register(self, registry):
        router_schema={'type':'object','properties':{
            'section':{'type':'string','enum':list(SECTIONS)},
            'offset':{'type':'integer','minimum':0,'maximum':499},
            'limit':{'type':'integer','minimum':1,'maximum':10},
            'filter_field':{'type':'string','enum':FILTER_FIELDS},
            'filter_value':{'type':'string','minLength':1,'maxLength':80,'pattern':r'^[^\x00-\x1f\x7f]+$'}},
            'required':['section'],'additionalProperties':False,
            'dependentRequired':{'filter_field':['filter_value'],'filter_value':['filter_field']}}
        sections='; '.join(f'{name}: {spec.title}' for name,spec in SECTIONS.items())
        registry.add(Tool('get_mikrotik_data',
            'Baca data MikroTik terperinci sesuai permintaan. '+sections+'. '
            'Filter exact opsional, hanya field yang sesuai section: name untuk interface/queue, '
            'address atau host-name/status/server untuk dhcp_leases, interface untuk VLAN/ARP, '
            'dst-address/gateway/active untuk routes, chain/action untuk firewall. '
            'Maksimal 10 baris; lanjut dengan next_offset jika has_more. Jangan klaim lengkap jika masih ada halaman. '
            'Data tambahan tidak berarti fitur itu tersedia; UNKNOWN/unsupported harus dijelaskan. '
            'Tidak tersedia password, config export, script, shell atau perubahan router.',router_schema,self.router.query))
        targets=list(self.settings.targets)+['mikrotik_system','mikrotik_interfaces','mikrotik_network','mikrotik_vlan','proxmox_resources','docker','debian']+self.extra_targets
        schema={'type':'object','properties':{'target':{'type':'string','enum':targets}},'required':['target'],'additionalProperties':False}
        registry.add(Tool('check_service','Periksa layanan aktual: DNS query, HTTP TLS, MikroTik CPU/RAM/interface, VM Proxmox, container Docker atau resource Debian. Pilih ID sesuai pertanyaan.',schema,self.check))
        async def check_integration(integration_id):
            item=self.platform.get('integrations',integration_id)
            if not item or not item['enabled']:return result('integration','allowlist',error='target_not_allowed')
            target=item['collector'] or ('service_'+item['id'] if item['monitor_enabled'] else '')
            if not target:return result(item['name'],'launcher only',error='monitoring_not_configured')
            return await self.check(target)
        registry.add(Tool('check_integration','Read a configured service integration using its id from service_integrations capabilities. Uses the shared collector cache; never performs configuration changes.',
            {'type':'object','properties':{'integration_id':{'type':'string','pattern':'^[a-z0-9_]{1,80}$'}},'required':['integration_id'],'additionalProperties':False},check_integration))
        async def check_inventory_device(device_id):
            item=self.platform.get('inventory',device_id)
            if not item or not item['enabled']:return result('inventory','allowlist',error='target_not_allowed')
            target=self.platform.inventory_target(item)
            if not target:return result(item['name'],'inventory',error='adapter_not_configured')
            return await self.check(target)
        registry.add(Tool('check_inventory_device','Read an enrolled inventory device by its id in configured_inventory capabilities. Uses the same monitoring cache; never applies changes.',
            {'type':'object','properties':{'device_id':{'type':'string','pattern':'^inv_[a-f0-9]{24}$'}},'required':['device_id'],'additionalProperties':False},check_inventory_device))
        registry.add(Tool('check_all_endpoints','Ringkasan kesehatan semua target. Detail field/baris dibatasi; gunakan check_service/get_mikrotik_data untuk permintaan rinci. UNKNOWN dipertahankan jika akses belum tersedia.',EMPTY,self.overview if self.settings.continuous_enabled else self.all,90))
        registry.add(Tool('compare_previous','Bandingkan hasil pemeriksaan saat ini dengan sampel sebelumnya yang tersimpan.',schema,self.compare))
        async def get_incidents(component='all',limit=10):
            return result('incidents','SQLite event history','UP',events=self.database.events(limit,component),
                delivery=dict(self.database.db.execute('SELECT status,count(*) FROM notifications GROUP BY status')),
                scope='Catatan observasi; pisahkan fakta, analisis kemungkinan dan tindakan yang belum dijalankan. uncertain bukan bukti terkirim/gagal.')
        registry.add(Tool('get_incidents','Ambil riwayat perubahan, gangguan dan recovery untuk menjelaskan notifikasi/gangguan berdasarkan bukti. Tidak membutuhkan perubahan jaringan.',
            {'type':'object','properties':{'component':{'type':'string','enum':['all','mikrotik','wireguard','cisco','docker','debian','proxmox','devices']},
                'limit':{'type':'integer','minimum':1,'maximum':30}},'additionalProperties':False},get_incidents))
        legacy={'mikrotik':('192.168.20.1',8291),'technitium_dns':('192.168.20.199',53),'proxmox':('192.168.20.200',8006),'debian_ssh':('192.168.20.195',22),'web_http':('192.168.20.195',80),'web_https':('192.168.20.195',443)}
        async def check_tcp_endpoint(target):
            return await tcp.probe(target,*legacy[target])
        registry.add(Tool('check_tcp_endpoint','Uji keterjangkauan TCP endpoint lama. Hasil bukan kesehatan aplikasi.',{'type':'object','properties':{'target':{'type':'string','enum':list(legacy)}},'required':['target'],'additionalProperties':False},check_tcp_endpoint))
