"""Combine only explicitly owned, current collector samples for one inventory host."""
from app.monitoring.device_capabilities import CATEGORIES,detect,telemetry


def summarize(item, target, samples):
    collectors=[];available=set();merged={};origins={}
    primary=samples.get(target)
    for identity,sample in sorted(samples.items(),key=lambda pair:pair[1].get('sample_epoch',0),reverse=True):
        if sample.get('host') and sample['host']!=item['host']:continue
        categories=detect(sample)
        if not sample.get('stale'):available.update(c for c in categories if c in {'network_status','latency'})
        collectors.append({**{key:sample.get(key) for key in ('status','method','error','sample_epoch','stale','stale_after_seconds')},'target':identity,'categories':categories})
        if sample.get('stale') or sample.get('status') not in {'UP','DEGRADED'} or sample.get('error'):continue
        available.update(categories)
        values=telemetry(sample)
        for key,value in values.items():
            if key in {'status','error','method','sample_epoch','host'} or value is None or value==[] or value=={}:continue
            source={'collector':identity,'sample_epoch':sample['sample_epoch']}
            if isinstance(value,list):
                rows=merged.setdefault(key,[])
                for row in value:
                    if not isinstance(row,dict):continue
                    marker=next((row.get(k) for k in ('id','name','vmid','path','node') if row.get(k) is not None),None)
                    old=next((r for r in rows if marker is not None and next((r.get(k) for k in ('id','name','vmid','path','node') if r.get(k) is not None),None)==marker),None)
                    if old is None:
                        rows.append({**row,**source})
                    else:
                        # Missing values never erase a measurement from another owned collector.
                        for field,measurement in row.items():
                            if measurement is not None and old.get(field) is None:old[field]=measurement
                        old.setdefault('sources',[{'collector':old['collector'],'sample_epoch':old['sample_epoch']}])
                        if source not in old['sources']:old['sources'].append(source)
            elif isinstance(value,dict):
                origins.setdefault(key,source)
                merged.setdefault(key,{})
                for field,measurement in value.items():
                    if measurement is not None and merged[key].get(field) is None:merged[key][field]=measurement
            elif merged.get(key) is None:
                merged[key]=value;origins[key]=source
    # For a legacy registration without a category selection, expose all real capabilities.
    enabled=item.get('monitor_categories')
    enabled=[category for category in CATEGORIES if category in available and (enabled is None or category in enabled)]
    health={key:primary.get(key) for key in ('status','error','sample_epoch','stale','stale_after_seconds','method')} if primary and primary.get('host') in (None,'',item['host']) else None
    if not item['enabled']:state='DISABLED'
    elif not target:state='NOT_CONFIGURED'
    elif not health:state='WAITING_FOR_SAMPLE'
    elif health.get('stale'):state='STALE'
    elif health['status']=='UP':state='CONNECTED'
    elif any(c['status']=='UP' and not c.get('stale') and not c.get('error') for c in collectors):state='PARTIAL'
    elif health['status']=='DOWN':state='UNREACHABLE'
    else:state='COLLECTION_FAILED' if health.get('error') else 'UNKNOWN'
    return {'id':item['id'],'name':item['name'],'host':item['host'],'monitor_target':target,'enabled':item['enabled'],
            'integration_state':state,'health':health,'supported_categories':[c for c in CATEGORIES if c in available],
            'enabled_categories':enabled,'telemetry':merged,'collectors':collectors,'metric_sources':origins}
