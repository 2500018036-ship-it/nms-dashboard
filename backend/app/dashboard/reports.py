"""Bounded aggregates from persisted observations, not fabricated SLA or uptime."""
import time
from app.dashboard import models

def report(db,query,targets,interval):
    models.fields(query,('target','from','to','resource'))
    if any(len(v)!=1 for v in query.values()):raise ValueError('invalid_query')
    target=query.get('target',['debian'])[0]
    if target not in targets:raise ValueError('target_not_allowed')
    end=float(query.get('to',[time.time()])[0]);start=float(query.get('from',[end-86400])[0])
    if not 0<start<end<=time.time()+60 or end-start>31*86400:raise ValueError('invalid_window')
    resource=query.get('resource',[''])[0]
    if resource and target!='proxmox_resources':raise ValueError('invalid_resource')
    import re
    if resource and not re.fullmatch(r'(node/[\w.-]+|(?:qemu|lxc)/\d+|storage/[\w.-]+/[\w.-]+)',resource):raise ValueError('invalid_resource')
    group='nodes' if resource.startswith('node/') else 'storage' if resource.startswith('storage/') else 'guests'
    join=" JOIN json_each(c.payload,'$."+group+"') r" if resource else ''
    where='c.target=? AND c.ts>=? AND c.ts<=?'+(" AND json_extract(r.value,'$.id')=?" if resource else '')
    args=[target,start,end]+([resource] if resource else [])
    total,first,last,up,down,degraded,unknown=db.execute('SELECT COUNT(*),MIN(c.ts),MAX(c.ts),'+','.join("SUM(CASE WHEN c.status='"+s+"' THEN 1 ELSE 0 END)" for s in ('UP','DOWN','DEGRADED','UNKNOWN'))+' FROM checks c'+join+' WHERE '+where,args).fetchone()
    counts=dict(zip(('UP','DOWN','DEGRADED','UNKNOWN'),(up or 0,down or 0,degraded or 0,unknown or 0)))
    # Per-resource values are ratios supplied by Proxmox. Invalid/missing values stay NULL.
    if resource:
        cpu="json_extract(r.value,'$.cpu')*100"
        memory="100.0*json_extract(r.value,'$.mem')/NULLIF(json_extract(r.value,'$.maxmem'),0)"
        disk='NULL' if resource.startswith('qemu/') else "100.0*json_extract(r.value,'$.disk')/NULLIF(json_extract(r.value,'$.maxdisk'),0)"
    elif target=='mikrotik_system':
        cpu="json_extract(c.payload,'$.data.\"/system/resource\"[0].\"cpu-load\"')+0.0"
        memory="100.0*(1.0-json_extract(c.payload,'$.data.\"/system/resource\"[0].\"free-memory\"')/NULLIF(1.0*json_extract(c.payload,'$.data.\"/system/resource\"[0].\"total-memory\"'),0))"
        disk='NULL'
    else:
        cpu="json_extract(c.payload,'$.cpu_percent')";memory="json_extract(c.payload,'$.memory_percent')";disk='NULL'
    good="c.status IN ('UP','DEGRADED')"
    expressions=[f'AVG(CASE WHEN {good} THEN {v} END)' for v in (cpu,memory,disk,"json_extract(c.payload,'$.latency_ms')")]
    bucket=max(60,int((end-start)/240))
    sql='SELECT CAST(c.ts/? AS INTEGER)*? time,COUNT(*),'+','.join(expressions)+' FROM checks c'+join+' WHERE '+where+' GROUP BY 1 ORDER BY 1 LIMIT 241'
    rows=db.execute(sql,[bucket,bucket]+args).fetchall()
    points=[dict(zip(('time','samples','cpu_percent','memory_percent','storage_percent','latency_ms'),r)) for r in rows]
    known=total-counts['UNKNOWN']
    # Coverage accounts for observation gaps and only gives each sample a bounded window.
    sample_interval=interval if target!='network_traffic' else min(30,interval)
    coverage=db.execute('SELECT SUM(MIN(?,MAX(0,next-ts))) FROM (SELECT ts,LEAD(ts,1,?) OVER(ORDER BY ts) next FROM checks WHERE target=? AND ts>=? AND ts<=?)',
        (sample_interval,end,target,start,end)).fetchone()[0] or 0
    return {'target':target,'resource':resource or None,'from':start,'to':end,'samples':total,'first_sample':first,'last_sample':last,
        'counts':counts,'sample_availability_percent':round(counts['UP']/known*100,3) if known else None,
        'coverage_percent':round(min(100,coverage/(end-start)*100),2),'points':points,'bucket_seconds':bucket,'generated_at':time.time(),
        'scope':'Availability of recorded collector observations (UP / known samples); not host uptime or an end-to-end SLA. UNKNOWN is excluded. Gaps are not assumed healthy.'}
