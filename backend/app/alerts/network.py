"""State transitions and traffic evidence. Device output is data, never instructions."""
import hashlib
import json
import math
import re
from statistics import median
import time
from app.alerts.traffic_idle import IdleTraffic

def duration(value):
    if value is None:return None
    text=str(value)
    if text in {'','never'}:return None
    if text.isdecimal():return float(text)
    units={'w':604800,'d':86400,'h':3600,'m':60,'s':1,'ms':.001}
    parts=re.findall(r'(\d+(?:\.\d+)?)(ms|[wdhms])',text)
    if parts and ''.join(n+u for n,u in parts)==text:return sum(float(n)*units[u] for n,u in parts)
    return None

class NetworkEvents:
    def __init__(self,settings,database):
        self.settings,self.database=settings,database
        self.idle=IdleTraffic(settings,database,lambda *args,**kwargs:self.emit(*args,**kwargs))
        for key,state in database.states().items():
            disabled=(key.startswith('network:traffic:') and not settings.traffic_baseline_alerts) or (
                key.startswith('network:device:') and not settings.targets.get(key.removeprefix('network:device:'),{}).get('alert_on_unreachable',False))
            if disabled and (state.get('active') or state.get('pending')):
                state.update(active=False,current='POLICY_DISABLED',first_seen=None,candidate=None,count=0)
                state.pop('pending',None);database.set_state(key,state)
                database.event(key,'RETIRED',{'kind':'RETIRED','time':time.time(),'reason':'notification_policy_changed',
                    'detail':'Aturan dinonaktifkan; bukan konfirmasi perangkat/layanan pulih.'})

    def emit(self,key,kind,title,device,value,now=None,severity='WARNING',first_seen=None):
        now=time.time() if now is None else now
        event={'key':key,'kind':kind,'title':title,'device':device,'severity':severity,
            'time':now,'first_seen':now if first_seen is None else first_seen,'value':value}
        if kind=='RECOVERY':event['recovered_at']=now
        self.database.event(key,kind,event)
        return event

    def change(self,key,current,value,title,device,*,now=None,bad=None,severity='WARNING',required=1):
        now=time.time() if now is None else now
        state=self.database.states().get(key)
        if state is None:
            self.database.set_state(key,{'current':current,'active':False,'updated_at':now})
            return None
        if now<state.get('updated_at',0):return None
        if current==state.get('current'):
            state.pop('candidate',None);state['count']=0
            state['updated_at']=now;self.database.set_state(key,state);return None
        if state.get('candidate')!=current:state['candidate_since']=now
        count=state.get('count',0)+1 if state.get('candidate')==current else 1
        state.update(candidate=current,count=count,updated_at=now)
        if count<required:self.database.set_state(key,state);return None
        previous=state['current'];was_active=state.get('active',False)
        kind='RECOVERY' if bad is False and was_active else ('ALERT' if bad is True else 'CHANGE')
        first=state.get('first_seen') if state.get('first_seen') is not None else state.get('candidate_since',now)
        event=self.emit(key,kind,title,device,{'previous':previous,'current':current,**value},now,
            'INFO' if kind=='RECOVERY' or bad is False else severity,first)
        state.update(current=current,active=bool(bad),count=0,first_seen=first if bad else None)
        state.pop('candidate',None);self.database.set_state(key,state)
        return event

    def interfaces(self,rows,observed_at=None,source='polling',link_observed_at=None):
        now=time.time() if observed_at is None else observed_at
        previous=self.database.states().get('network:interface_sample',{})
        elapsed=now-previous.get('at',now)
        samples={};rates=[]
        for row in rows:
            name=row.get('name','')
            if not name:continue
            samples[name]=row
            physical=bool(re.fullmatch(r'ether\d+',name)) and row.get('type')=='ether'
            if self.settings.mikrotik_interfaces:physical=name in self.settings.mikrotik_interfaces
            if physical:self.link(row,now if link_observed_at is None else link_observed_at,source)
            if not physical and row.get('type') not in {'ether','bond','vlan','wg'}:continue
            old=previous.get('rows',{}).get(name)
            valid=bool(old and 0<elapsed<=max(120,self.settings.network_interval*4) and row.get('running')=='true' and old.get('running')=='true')
            point={'name':name,'sample_seconds':round(elapsed,3),'rx_bps':None,'tx_bps':None}
            for direction in ('rx','tx'):
                try:
                    delta=int(row[direction+'-byte'])-int(old[direction+'-byte']) if valid else -1
                    rate=delta*8/elapsed if delta>=0 else None
                    if rate is not None and (not math.isfinite(rate) or rate>1e12):rate=None
                except (KeyError,ValueError,TypeError,ZeroDivisionError):rate=None
                point[direction+'_bps']=round(rate,2) if rate is not None else None
                if (physical or row.get('type')=='wg') and self.settings.traffic_baseline_alerts:self.traffic(name,direction,rate,now)
            if physical or row.get('type')=='wg':
                idle=self.idle.observe(name,point['rx_bps'],point['tx_bps'],now,row.get('running')=='true')
                point['idle_observation']=idle.get('observed','UNKNOWN')
                point['idle_alert_active']=idle.get('active',False)
            capacity=row.get('capacity_bps')
            duplex=row.get('link_monitor',{}).get('full-duplex')
            valid_capacity=(physical and isinstance(capacity,(int,float)) and capacity>0
                and row.get('capacity_age_seconds',999)<=90 and duplex in {'true','false','yes','no'})
            point.update(capacity_bps=capacity if valid_capacity else None,utilization_percent=None,
                rx_percent=None,tx_percent=None,duplex='full' if duplex in {'true','yes'} else ('half' if duplex in {'false','no'} else None))
            if valid_capacity and all(point[d+'_bps'] is not None for d in ('rx','tx')):
                point['rx_percent']=round(100*point['rx_bps']/capacity,3)
                point['tx_percent']=round(100*point['tx_bps']/capacity,3)
                point['utilization_percent']=round((max(point['rx_bps'],point['tx_bps']) if point['duplex']=='full'
                    else point['rx_bps']+point['tx_bps'])*100/capacity,3)
            if physical:self.bandwidth(name,point,now)
            rates.append(point)
            if physical and old and row.get('running')==old.get('running')=='true':
                try:downs=int(row.get('link-downs',0))-int(old.get('link-downs',0))
                except ValueError:downs=0
                if downs>0 and not self.database.states().get('network:link:'+name,{}).get('native_since_sample'):
                    self.emit('network:flap:'+name,'CHANGE','Gangguan link singkat terdeteksi','MikroTik',
                        {'interface':name,'link_downs_delta':downs,'current':'UP','source':'counter link-downs; waktu kejadian persis belum diketahui'},now)
            if physical:
                link=self.database.states().get('network:link:'+name,{})
                link.pop('native_since_sample',None);self.database.set_state('network:link:'+name,link)
        self.database.set_state('network:interface_sample',{'at':now,'rows':samples})
        return rates

    def link(self,row,now=None,source='polling'):
        if row.get('running') not in {'true','false'}:return None
        name=row.get('name','')
        if not name:return None
        state='DISABLED' if row.get('disabled')=='true' else ('UP' if row['running']=='true' else 'DOWN')
        event=self.change('network:link:'+name,state,{'interface':name,'source':source,
            'running':row.get('running'),'disabled':row.get('disabled'),
            'certainty':'Link DOWN tidak membuktikan penyebabnya kabel; dapat berasal dari port/perangkat lain.'},
            'Interface '+state,'MikroTik',now=now,bad=state!='UP',severity='CRITICAL' if name=='ether1' else 'WARNING')
        if source!='polling':
            saved=self.database.states().get('network:link:'+name,{})
            saved['native_since_sample']=True;self.database.set_state('network:link:'+name,saved)
        return event

    def traffic(self,name,direction,rate,now):
        key='network:traffic:'+name+':'+direction
        state=self.database.states().get(key,{'points':[],'active':False,'current':'normal'})
        points=state.get('points',[])
        if rate is None:
            # A counter reset, link down or observation gap is not zero traffic/recovery.
            state.update(points=[],candidate=None,count=0,candidate_since=None,last_valid=None)
            self.database.set_state(key,state);return
        gap=now-state.get('last_valid',now) if state.get('last_valid') is not None else 0
        if gap>max(30,self.settings.network_interval*2.5):
            state.update(points=[],candidate=None,count=0,candidate_since=None)
            points=[]
        state['last_valid']=now
        baseline=state.get('baseline') if state.get('active') else (median(points) if points else None)
        warm=len(points)>=self.settings.traffic_warmup
        current='normal'
        if (warm or state.get('active')) and baseline is not None and baseline>=self.settings.traffic_min_bps:
            spike=1.5 if state.get('current')=='spike' else self.settings.traffic_spike_factor
            drop=.25 if state.get('current')=='drop' else self.settings.traffic_drop_factor
            minimum=0 if state.get('current')=='spike' else self.settings.traffic_spike_min_bps
            if rate>max(minimum,baseline*spike):current='spike'
            elif rate<=baseline*drop:current='drop'
        count=state.get('count',0)+1 if current==state.get('candidate') else 1
        if current!=state.get('candidate') or state.get('candidate_since') is None:state['candidate_since']=now
        state.update(candidate=current,count=count)
        sustained=now-state['candidate_since']
        ready=sustained>=self.settings.traffic_spike_seconds if current=='spike' else count>=2
        if current!=state.get('current') and ready:
            recovering=current=='normal'
            self.emit(key,'RECOVERY' if recovering else 'ALERT',
                'Trafik kembali normal' if recovering else ('Lonjakan trafik' if current=='spike' else 'Penurunan trafik'),
                'MikroTik',{'interface':name,'direction':direction.upper(),'bits_per_second':round(rate,2),
                    'baseline_bps':round(baseline,2),'source':'delta counter byte / selang sampel aktual',
                    'sustained_seconds':round(sustained,1),'certainty':'Anomali statistik; penyebab belum dipastikan.'},now,
                'INFO' if recovering else 'WARNING',state.get('first_seen') if recovering else state['candidate_since'])
            state.update(current=current,active=not recovering,baseline=None if recovering else baseline,
                first_seen=None if recovering else state['candidate_since'])
        if current=='normal' and not state.get('active'):points=(points+[rate])[-20:]
        state['points']=points
        self.database.set_state(key,state)

    def bandwidth(self,name,point,now):
        key='network:bandwidth:'+name
        state=self.database.states().get(key,{'active':False,'current':'NORMAL'})
        value=point.get('utilization_percent')
        if value is None:
            state.update(candidate=None,candidate_since=None,last_valid=None,observed_percent=None)
            self.database.set_state(key,state);return
        previous=state.get('current','NORMAL')
        cfg=self.settings
        if value>cfg.bandwidth_critical or (previous=='CRITICAL' and value>cfg.bandwidth_critical-cfg.bandwidth_hysteresis):current='CRITICAL'
        elif value>cfg.bandwidth_warning or (previous in {'WARNING','CRITICAL'} and value>cfg.bandwidth_warning-cfg.bandwidth_hysteresis):current='WARNING'
        else:current='NORMAL'
        gap=now-state.get('last_valid',now) if state.get('last_valid') is not None else 0
        if current!=state.get('candidate') or state.get('candidate_since') is None or gap>max(30,cfg.network_interval*2.5):
            state['candidate_since']=now
        state.update(candidate=current,last_valid=now,observed_percent=value,updated_at=now)
        sustained=now-state['candidate_since']
        if current!=previous and sustained>=cfg.bandwidth_seconds:
            recovery=current=='NORMAL'
            first=state.get('first_seen') if state.get('active') else state['candidate_since']
            self.emit(key,'RECOVERY' if recovery else 'ALERT',
                'Utilisasi bandwidth kembali normal' if recovery else 'Utilisasi bandwidth '+current,'MikroTik',
                {'interface':name,'utilization_percent':value,'capacity_bps':point.get('capacity_bps'),
                    'rx_percent':point.get('rx_percent'),'tx_percent':point.get('tx_percent'),'duplex':point.get('duplex'),
                    'previous':previous,'current':current,'sustained_seconds':round(sustained,1),
                    'source':'rate Ethernet ternegosiasi; delta counter pada selang aktual',
                    'scope':'Full duplex memakai maksimum RX/TX; half duplex memakai jumlah RX+TX. Bukan utilisasi paket ISP.'},
                now,'INFO' if recovery else current,first)
            state.update(current=current,active=not recovery,first_seen=None if recovery else first)
        self.database.set_state(key,state)

    def missing_sample(self):
        self.idle.invalidate()
        # An explicit collector failure breaks a sustained interval. Preserve active
        # incidents until real good samples confirm recovery.
        for key,state in self.database.states().items():
            if key.startswith(('network:traffic:','network:bandwidth:')):
                state.update(candidate=None,candidate_since=None,count=0,last_valid=None)
                if key.startswith('network:traffic:'):state['points']=[]
                else:state['observed_percent']=None
                self.database.set_state(key,state)

    def routes(self,value,now=None):
        if value.get('status')!='UP':return
        if any(m.get('scan_truncated') or m.get('has_more') for m in value.get('resources',{}).values()):return
        rows=[{k:r.get(k,'') for k in ('dst-address','gateway','routing-table','distance','active')}
            for r in value.get('data',{}).get('/ip/route',[]) if r.get('disabled')!='true']
        rows=sorted(rows,key=lambda r:json.dumps(r,sort_keys=True))
        fingerprint=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
        old=self.database.states().get('network:route_details',{}).get('rows',[])
        removed=[r for r in old if r not in rows];added=[r for r in rows if r not in old]
        self.change('network:mikrotik:routes',fingerprint,{'removed':removed[:6],'added':added[:6],
            'total_removed':len(removed),'total_added':len(added),'details_limit':6,
            'scope':'Route yang berhasil dibaca; bukan bukti forwarding end-to-end.'},'Perubahan routing','MikroTik',now=now)
        self.database.set_state('network:route_details',{'rows':rows})

    def wireguard(self,value,now=None):
        if value.get('status') not in {'UP','DEGRADED'}:return
        for peer in value.get('peers',[]):
            if peer.get('disabled')=='true':continue
            if not duration(peer.get('persistent-keepalive')):continue  # Idle, on-demand peers are not presumed always online.
            identity=peer.get('id') or peer.get('name')
            if not identity:continue
            age=peer.get('handshake_age_seconds')
            if age is None:continue
            bad=age>self.settings.wireguard_stale
            self.change('network:wireguard:'+identity,'STALE' if bad else 'RECENT',
                {'peer':peer.get('name',identity),'interface':peer.get('interface'),'handshake_age_seconds':age,
                    'threshold_seconds':self.settings.wireguard_stale,'certainty':'Handshake lama tidak membuktikan peer mati; tunnel idle juga mungkin.'},
                'WireGuard handshake '+('terlambat' if bad else 'kembali baru'),'WireGuard',now=now,bad=bad,required=2)
