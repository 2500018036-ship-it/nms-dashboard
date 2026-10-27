from datetime import datetime, timezone,timedelta
import time
from app.alerts.presentation import metadata

class Alerts:
    def __init__(self, settings, database):
        self.settings,self.database=settings,database

    def observe(self, key, bad, value, now=None, required=2):
        now=now if now is not None else time.time()
        state=self.database.states().get(key,{'active':False,'bad_count':0,'good_count':0,'first_seen':None,'last_sent':0})
        if bad is None:
            state['good_count']=state['bad_count']=0
            self.database.set_state(key,state)
            return None
        state['bad_count']=state['bad_count']+1 if bad else 0
        state['good_count']=state['good_count']+1 if not bad else 0
        if bad and state['first_seen'] is None:
            state['first_seen']=now
        event=None
        if not state['active'] and state['bad_count']>=required:
            state['active']=True
            event={'kind':'ALERT','first_seen':state['first_seen'],'value':value}
        elif state['active'] and not bad and state['good_count']>=2:
            state['active']=False
            event={'kind':'RECOVERY','first_seen':state['first_seen'],'recovered_at':now,'value':value}
            state['first_seen']=None
        elif not state['active'] and not bad:
            state['first_seen']=None
        if event:
            event.update(key=key,time=now)
            # Durable pending notification is retried only after cooldown on transport failure.
            state['pending']=event
            state['last_attempt']=state['last_sent'] if event['kind']=='ALERT' else 0
            self.database.event(key,event['kind'],event)
        state['last_value']=value
        state['updated_at']=now
        self.database.set_state(key,state)
        return event

    def metric(self,key,value,threshold):
        active=self.database.states().get(key,{}).get('active',False)
        bad=None if value is None else value > (threshold-5 if active else threshold)
        self.observe(key,bad,{'value':value,'threshold':threshold,'hysteresis':5})

    def evaluate(self,results):
        cfg=self.settings
        for row in results:
            target=row['target']; status=row['status']
            if row['method'].startswith('ICMP') and not target.startswith('inventory_'):continue  # Existing device transitions use their own quiet first baseline.
            self.observe(target+':availability',status in {'DOWN','DEGRADED'} if status!='UNKNOWN' else None,{'status':status,'method':row['method']})
            # Credential gaps are not service outages, and are visible in /status instead.
            unavailable=status=='UNKNOWN' and row.get('error') not in {'readonly_account_required','missing_readonly_token','network_details_disabled',
                'excessive_or_unverified_permissions','cannot_verify_account','missing_credentials',
                'plaintext_not_explicitly_allowed','tls_verification_required','missing_switch_management','waiting_for_samples','icmp_not_permitted'}
            self.observe(target+':collector',unavailable,{'status':status,'error':row.get('error')},required=3)
            if target=='debian' and status=='UP':
                self.metric('debian:cpu',row.get('cpu_percent'),cfg.cpu_threshold)
                self.metric('debian:memory',row.get('memory_percent'),cfg.memory_threshold)
                for disk in row.get('disks',[]):
                    self.metric('debian:disk:'+disk['path'],disk.get('used_percent'),cfg.storage_threshold)
            if target=='mikrotik_system' and status=='UP':
                values=row.get('data',{}).get('/system/resource',[{}])[0]
                self.metric('mikrotik:cpu',float(values['cpu-load']) if 'cpu-load' in values else None,cfg.cpu_threshold)
                memory=100*(1-int(values['free-memory'])/int(values['total-memory'])) if int(values.get('total-memory',0)) else None
                self.metric('mikrotik:memory',memory,cfg.memory_threshold)
                disk=100*(1-int(values['free-hdd-space'])/int(values['total-hdd-space'])) if int(values.get('total-hdd-space',0)) else None
                self.metric('mikrotik:storage',disk,cfg.storage_threshold)
            if target=='mikrotik_interfaces' and status=='UP' and not cfg.continuous_enabled:
                for interface in row.get('data',{}).get('/interface',[]):
                    if interface.get('name') in cfg.mikrotik_interfaces:
                        self.observe('interface:'+interface['name'],interface.get('running')!='true',{'running':interface.get('running'),'disabled':interface.get('disabled')})
            if target=='docker' and status in {'UP','DEGRADED'}:
                for c in row.get('containers',[]):
                    name=c['name']
                    if c.get('expected_running') is False:
                        for key in ('container:'+name,'restarts:'+name):
                            state=self.database.states().get(key)
                            if state and (state.get('active') or state.get('pending')):
                                state.update(active=False,suppressed_by_configuration=True)
                                state.pop('pending',None)
                                self.database.set_state(key,state)
                                self.database.event(key,'SUPPRESSED',{'reason':'explicit_container_ignorelist'})
                        continue
                    self.observe('container:'+name,c.get('state') not in {'running'} or c.get('health')=='unhealthy',{'state':c.get('state'),'health':c.get('health')})
                    key='restarts:'+name
                    state=self.database.states().get(key,{})
                    points=state.get('points',[])
                    now=time.time()
                    points=[p for p in points if now-p[0]<900]+[[now,c.get('restart_count',0)]]
                    delta=max(0,points[-1][1]-points[0][1])
                    self.observe(key,delta>=3,{'restart_delta_15m':delta},required=1)
                    state=self.database.states()[key]; state['points']=points[-20:]
                    self.database.set_state(key,state)
                if row.get('scan_truncated') is False:
                    names={c['name'] for c in row.get('containers',[])}
                    previous=self.database.states().get('docker:inventory',{}).get('names',[])
                    for name in sorted(set(previous)-names):
                        now=time.time()
                        self.database.event('container:'+name,'CHANGE',{'kind':'CHANGE','key':'container:'+name,
                            'device':'Docker','title':'Container tidak lagi tercantum','severity':'INFO','time':now,'first_seen':now,
                            'value':{'name':name,'scope':'Hilang dari daftar lengkap Docker; bukan bukti layanan pulih.'}})
                    for key,state in self.database.states().items():
                        if key.startswith(('container:','restarts:')) and key.split(':',1)[1] not in names and state.get('active'):
                            state.update(active=False,retired=True);state.pop('pending',None);self.database.set_state(key,state)
                            self.database.event(key,'RETIRED',{'reason':'absent_from_complete_docker_inventory'})
                    self.database.set_state('docker:inventory',{'names':sorted(names),'updated_at':time.time()})
            if target=='proxmox_resources' and status=='UP':
                for node in row.get('nodes',[]):
                    key='pve:'+node['node']
                    self.observe(key+':node',node.get('status')!='online',{'status':node.get('status')})
                    self.metric(key+':cpu',node.get('cpu',0)*100,cfg.cpu_threshold)
                    self.metric(key+':memory',node.get('mem',0)/node['maxmem']*100 if node.get('maxmem') else None,cfg.memory_threshold)
                for guest in row.get('guests',[]):
                    if str(guest['vmid']) in cfg.expected_guests:
                        self.observe('guest:'+str(guest['vmid']),guest.get('status')!='running',{'name':guest.get('name'),'node':guest.get('node'),'status':guest.get('status')})
                for disk in row.get('storage',[]):
                    self.metric('pve:storage:'+disk['id'],disk.get('disk',0)/disk['maxdisk']*100 if disk.get('maxdisk') else None,cfg.storage_threshold)

    def pending(self):
        now=time.time()
        return [(key,state) for key,state in self.database.states().items() if state.get('pending') and now-state.get('last_attempt',0)>=self.settings.cooldown]

    def attempted(self,key,success):
        state=self.database.states()[key]
        state['last_attempt']=time.time()
        if success:
            state['last_sent']=time.time()
            state.pop('pending',None)
        self.database.set_state(key,state)

    @staticmethod
    def text(event):
        stamp=lambda value:datetime.fromtimestamp(value or event['time'],timezone(timedelta(hours=7),'WIB')).strftime('%d/%m/%Y %H:%M:%S WIB')
        info=metadata(event)
        title=info['title']
        quote=lambda value:'`'+str(value).replace('`','ˋ').replace('\n',' ').replace('\r',' ')[:500]+'`'
        device=info['device']
        severity=info['severity']
        labels={'status':'Status','method':'Metode','error':'Keterangan','value':'Nilai','threshold':'Ambang batas','hysteresis':'Hysteresis','state':'Kondisi','health':'Healthcheck','running':'Running','disabled':'Disabled','restart_delta_15m':'Restart dalam 15 menit','name':'Nama','node':'Node'}
        labels.update(interface='Interface',source='Sumber',previous='Sebelumnya',current='Sekarang',bits_per_second='Kecepatan',
            baseline_bps='Baseline',handshake_age_seconds='Usia handshake (detik)',scope='Cakupan',certainty='Batas diagnosis',
            host='Alamat',direction='Arah',uplinks='Link ke switch',removed='Route sebelumnya',added='Route baru',
            total_removed='Jumlah route berubah/hilang',total_added='Jumlah route berubah/baru')
        labels.update(utilization_percent='Utilisasi (%)',capacity_bps='Kapasitas link',rx_percent='RX (%)',tx_percent='TX (%)',
            sustained_seconds='Durasi terkonfirmasi (detik)',duplex='Duplex',rx_bps='RX',tx_bps='TX',threshold_seconds='Ambang waktu (detik)')
        lines=[f'**{title}**',f'Perangkat: {quote(device)}',f"Kejadian: {quote(event['key'])}",
            f'Keparahan: {severity}',f"Waktu: {stamp(event['time'])}",
            'Pemulihan: '+('PULIH' if event['kind']=='RECOVERY' else ('BELUM PULIH' if event['kind']=='ALERT' else 'perubahan teramati')),
            f"Mulai teramati: {stamp(event.get('first_seen'))}",'','**Bukti pemeriksaan**']
        for key,value in event.get('value',{}).items():
            label=labels.get(key,key)
            if key in {'bits_per_second','baseline_bps','capacity_bps','rx_bps','tx_bps'} and isinstance(value,(int,float)):
                value=(f'{value/1000000:.2f} Mbit/detik' if value>=1000000 else f'{value/1000:.1f} kbit/detik')
            if isinstance(value,dict):
                lines.append(f'• {label}:')
                lines.extend(f'  • {quote(k)}: {quote(v)}' for k,v in list(value.items())[:8])
            elif isinstance(value,list):
                lines.append(f'• {label}: {len(value)} detail')
                for item in value[:6]:
                    text='; '.join(f'{k}: {v}' for k,v in item.items()) if isinstance(item,dict) else str(item)
                    lines.append('  • '+quote(text))
            else:lines.append(f"• {label}: {quote(value) if value is not None else 'belum tersedia'}")
        lines+=['','Observasi saja; tidak ada perubahan infrastruktur.']
        return '\n'.join(lines)
