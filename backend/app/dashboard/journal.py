"""Bounded read-only queries over real monitoring records and incident projection."""
import json
import re
import time
from app.alerts.presentation import clean, metadata, evidence

SOURCES = [
    {'id':'monitoring-events','category':'monitoring','available':True,'label':'Event monitoring'},
    {'id':'monitoring-checks','category':'monitoring','available':True,'label':'Hasil pemeriksaan collector'},
    {'id':'application','category':'application','available':False,'label':'Log aplikasi','reason':'gunakan tab Aplikasi NMS; log container lain belum dikumpulkan'},
    {'id':'audit','category':'audit','available':False,'label':'Audit administratif','reason':'gunakan tab Audit / Users; API audit dibatasi Administrator'},
    {'id':'syslog','category':'syslog','available':False,'label':'Syslog perangkat','reason':'penerimaan remote syslog tidak diaktifkan'},
]

def load(value):
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError): return {}

def params(query, kind):
    allowed = {'page','page_size','q','severity','device','from','to','status'} if kind == 'incidents' else {'page','page_size','q','severity','device','from','to','category','source'}
    if set(query) - allowed or any(len(v) != 1 for v in query.values()): raise ValueError('invalid_query')
    value = {k:v[0] for k,v in query.items()}
    def integer(name, default, maximum):
        raw = value.get(name, str(default))
        if not re.fullmatch(r'[1-9]\d{0,5}', raw) or int(raw) > maximum: raise ValueError('invalid_page')
        return int(raw)
    page, size = integer('page',1,10000), integer('page_size',25,100)
    q, device = value.get('q',''), value.get('device','')
    if len(q) > 120 or len(device) > 180 or any(ord(c)<32 for c in q+device): raise ValueError('invalid_filter')
    severity = value.get('severity','all')
    if severity not in {'all','INFO','WARNING','CRITICAL','UNKNOWN'}: raise ValueError('invalid_severity')
    now = time.time()
    def epoch(name, default):
        raw = value.get(name)
        if raw is None: return default
        if not re.fullmatch(r'\d{1,10}(\.\d{1,6})?', raw): raise ValueError('invalid_time')
        result = float(raw)
        if result > now + 60: raise ValueError('future_time')
        return result
    until = epoch('to', now)
    since = epoch('from', 0 if kind == 'incidents' else until-86400)
    if since > until or kind == 'logs' and until-since > 31*86400: raise ValueError('invalid_window')
    result = dict(page=page,page_size=size,q=q,device=device,severity=severity,since=since,until=until)
    if kind == 'incidents':
        result['status'] = value.get('status','all')
        if result['status'] not in {'all','ACTIVE','RECOVERED','RETIRED','UNKNOWN'}: raise ValueError('invalid_status')
    else:
        result.update(category=value.get('category','all'),source=value.get('source','all'))
        if result['category'] not in {'all','monitoring','application','audit','syslog'} or result['source'] not in {'all',*(s['id'] for s in SOURCES)}: raise ValueError('invalid_source')
    return result

def escaped(value): return value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')

class Journal:
    def __init__(self, db):
        self.db = db
        db.create_function('event_field',4,self.event_field,deterministic=True)
        db.create_function('check_message',1,self.check_message,deterministic=True)
        db.create_function('check_device',2,self.check_device,deterministic=True)

    @staticmethod
    def event_field(payload,key,kind,field):
        return metadata(load(payload),key,kind).get(field) or ('INFO' if kind in {'RETIRED','SUPPRESSED'} and field=='severity' else 'UNKNOWN' if field=='severity' else clean(key))

    @staticmethod
    def check_device(payload,target):
        row=load(payload)
        return clean(row.get('host')) or clean(target)

    @staticmethod
    def check_message(payload):
        row=load(payload)
        status=row.get('status') if row.get('status') in {'UP','DOWN','DEGRADED','UNKNOWN'} else 'UNKNOWN'
        return clean('Hasil pemeriksaan '+str(row.get('target',''))+' · '+str(row.get('method',''))+' · '+status)

    def logs(self, query):
        p=params(query,'logs')
        base='''WITH records AS (
          SELECT 'event_'||e.id id,e.ts time,e.key target,'monitoring-events' source,
            event_field(e.payload,e.key,e.kind,'device') device,event_field(e.payload,e.key,e.kind,'severity') severity,
            event_field(e.payload,e.key,e.kind,'title') message,'event' record_type,e.kind kind,e.id raw_id,ie.incident_id incident_id
            FROM events e LEFT JOIN incident_events ie ON ie.event_id=e.id WHERE e.ts>=? AND e.ts<=?
          UNION ALL SELECT 'check_'||c.id,c.ts,c.target,'monitoring-checks',COALESCE(NULLIF(json_extract(c.payload,'$.host'),''),c.target),
            CASE c.status WHEN 'UP' THEN 'INFO' WHEN 'DOWN' THEN 'WARNING' WHEN 'DEGRADED' THEN 'WARNING' ELSE 'UNKNOWN' END,
            'Hasil pemeriksaan '||c.target||' · '||COALESCE(json_extract(c.payload,'$.method'),'')||' · '||c.status,
            'check',c.status,c.id,NULL FROM checks c WHERE c.ts>=? AND c.ts<=?) '''
        args=[p['since'],p['until'],p['since'],p['until']]; where=['1=1']
        if p['category'] not in {'all','monitoring'}: where.append('0=1')
        for field in ('source','severity','device'):
            if p[field] not in {'all',''}: where.append(field+'=? COLLATE NOCASE');args.append(p[field])
        if p['q']:
            where.append("(message LIKE ? ESCAPE '\\' OR target LIKE ? ESCAPE '\\' OR device LIKE ? ESCAPE '\\')")
            args.extend(['%'+escaped(p['q'])+'%']*3)
        suffix=' WHERE '+' AND '.join(where)
        total=self.db.execute(base+'SELECT COUNT(*) FROM records'+suffix,args).fetchone()[0]
        devices=[clean(r[0]) for r in self.db.execute('''SELECT DISTINCT device FROM (
          SELECT event_field(payload,key,kind,'device') device FROM events WHERE ts>=? AND ts<=?
          UNION SELECT COALESCE(NULLIF(json_extract(payload,'$.host'),''),target) FROM checks WHERE id IN (
            SELECT MAX(id) FROM checks WHERE ts>=? AND ts<=? GROUP BY target))
          ORDER BY device LIMIT 200''',args[:4])]
        # Sort compact identities only. Hydrate the selected page after LIMIT/OFFSET,
        # rather than spilling tens of thousands of messages/payloads to constrained /tmp.
        rows=self.db.execute(base+'SELECT id,time,record_type,raw_id FROM records'+suffix+' ORDER BY time DESC,raw_id DESC,record_type DESC LIMIT ? OFFSET ?',args+[p['page_size'],(p['page']-1)*p['page_size']]).fetchall()
        items=[]
        for identity, at, record_type, raw_id in rows:
            if record_type=='event':
                key,kind,payload=self.db.execute('SELECT key,kind,payload FROM events WHERE id=?',(raw_id,)).fetchone()
                info=metadata(load(payload),key,kind)
                relation=self.db.execute('SELECT incident_id FROM incident_events WHERE event_id=?',(raw_id,)).fetchone()
                device=info.get('device') or key
                severity=info.get('severity') or ('INFO' if kind in {'RETIRED','SUPPRESSED'} else 'UNKNOWN')
                message=info.get('title') or key
                incident_id=relation[0] if relation else None
            else:
                key,kind,payload=self.db.execute('SELECT target,status,payload FROM checks WHERE id=?',(raw_id,)).fetchone()
                device=self.check_device(payload,key);message=self.check_message(payload)
                severity='INFO' if kind=='UP' else 'WARNING' if kind in {'DOWN','DEGRADED'} else 'UNKNOWN'
                incident_id=None
            item={'id':identity,'time':at,'target':clean(key),'source':'monitoring-events' if record_type=='event' else 'monitoring-checks',
                'device':clean(device),'severity':severity,'message':clean(message),'record_type':record_type,'kind':clean(kind),
                'incident_id':incident_id,'category':'monitoring'}
            raw=load(payload)
            item['evidence']=evidence((raw.get('value') or raw) if item['record_type']=='event' else raw)
            item['level_source']='monitoring_event' if item['record_type']=='event' else 'check_result_label'
            items.append(item)
        return {'items':items,'total':total,'page':p['page'],'page_size':p['page_size'],'sources':SOURCES,'devices':devices,
            'from':p['since'],'to':p['until'],'generated_at':time.time(),'read_only':True}

    def incident(self, row):
        item=dict(zip(('id','key','status','first_seen','updated_at','resolved_at','severity','opening_event_id','latest_event_id','device','title','partial_history'),row))
        for key in ('key','device','title'):item[key]=clean(item[key])
        state=self.db.execute('SELECT payload FROM alert_state WHERE key=?',(row[1],)).fetchone()
        state=load(state[0]) if state else {}
        item['last_observed_at']=state.get('updated_at') if item['status']=='ACTIVE' else None
        item['evidence']=evidence(state.get('last_value',{})) if item['status']=='ACTIVE' else {}
        latest=self.db.execute('SELECT payload FROM events WHERE id=?',(item['latest_event_id'],)).fetchone()
        if latest and not item['evidence']:item['evidence']=evidence(load(latest[0]).get('value',{}))
        delivery=self.db.execute('SELECT status,attempts,last_attempt FROM notifications WHERE event_id=?',(item['latest_event_id'],)).fetchone()
        item['delivery']={'status':delivery[0],'attempts':delivery[1],'last_attempt':delivery[2]} if delivery else {'status':'not_queued','attempts':0,'last_attempt':None}
        item['acknowledgment']={'supported':False,'status':'UNAVAILABLE'}
        item['resolution_source']='monitoring_recovery' if item['status']=='RECOVERED' else 'policy_or_inventory' if item['status']=='RETIRED' else None
        item['partial_history']=bool(item['partial_history'] or item['opening_event_id'] is not None and not self.db.execute('SELECT 1 FROM events WHERE id=?',(item['opening_event_id'],)).fetchone())
        return item

    def incidents(self, query):
        p=params(query,'incidents'); where=['updated_at>=?','updated_at<=?'];args=[p['since'],p['until']]
        for field in ('status','severity','device'):
            if p[field] not in {'all',''}:where.append(field+'=? COLLATE NOCASE');args.append(p[field])
        if p['q']:
            where.append("(key LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' OR device LIKE ? ESCAPE '\\')")
            args.extend(['%'+escaped(p['q'])+'%']*3)
        suffix=' WHERE '+' AND '.join(where)
        total=self.db.execute('SELECT COUNT(*) FROM incidents'+suffix,args).fetchone()[0]
        rows=self.db.execute('SELECT * FROM incidents'+suffix+' ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',args+[p['page_size'],(p['page']-1)*p['page_size']]).fetchall()
        summary=dict(self.db.execute('SELECT status,COUNT(*) FROM incidents GROUP BY status'))
        devices=[clean(r[0]) for r in self.db.execute('SELECT DISTINCT device FROM incidents ORDER BY device LIMIT 200')]
        return {'items':[self.incident(r) for r in rows],'total':total,'page':p['page'],'page_size':p['page_size'],'summary':summary,
            'devices':devices,'acknowledgment_supported':False,'resolution_mode':'monitoring_only','generated_at':time.time(),'read_only':True}

    def detail(self, identity):
        if not re.fullmatch(r'inc_(event_[1-9]\d{0,14}|state_[a-f0-9]{20})',identity):raise ValueError('invalid_incident_id')
        row=self.db.execute('SELECT * FROM incidents WHERE id=?',(identity,)).fetchone()
        if not row:return None
        result=self.incident(row)
        rows=self.db.execute('SELECT e.id,e.ts,e.kind,e.payload,n.status FROM incident_events ie JOIN events e ON e.id=ie.event_id LEFT JOIN notifications n ON n.event_id=e.id WHERE ie.incident_id=? ORDER BY e.id DESC LIMIT 101',(identity,)).fetchall()
        result['timeline_truncated']=len(rows)>100
        result['timeline']=[{'id':'event_'+str(i),'time':ts,'kind':kind,'detail':metadata(load(payload),result['key'],kind),
            'evidence':evidence(load(payload).get('value') or load(payload)),'delivery':delivery or 'not_queued'} for i,ts,kind,payload,delivery in rows[:100]]
        return {'incident':result,'read_only':True}
