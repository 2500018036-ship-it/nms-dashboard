"""Capabilities and small telemetry projections derived only from saved samples."""
CATEGORIES = {
    'network_status':'Status jaringan', 'latency':'Latensi', 'system_information':'Informasi sistem',
    'cpu':'CPU', 'memory':'Memori', 'storage':'Penyimpanan', 'interfaces':'Interface',
    'traffic':'Counter trafik', 'bandwidth':'Bandwidth', 'vlan':'VLAN', 'routing':'Routing', 'wireless':'Nirkabel',
    'temperature':'Suhu', 'sensors':'Sensor', 'virtualization':'Virtualisasi', 'service_health':'Kesehatan layanan',
}


def _has(value):
    return value is not None and value != '' and value != [] and value != {}


def detect(sample):
    if not isinstance(sample,dict):return []
    found=set();data=sample.get('data') if isinstance(sample.get('data'),dict) else {}
    interfaces=sample.get('interfaces') if isinstance(sample.get('interfaces'),list) and sample['interfaces'] else data.get('/interface',[])
    resource=(data.get('/system/resource') or [{}])[0] if isinstance(data.get('/system/resource'),list) and data.get('/system/resource') else {}
    if sample.get('status') in {'UP','DOWN','DEGRADED'}:found.add('network_status')
    if isinstance(sample.get('latency_ms'),(float,int)):found.add('latency')
    if _has(sample.get('system_info')) or _has(sample.get('version')) or _has(resource) or _has(data.get('/system/identity')) or _has(sample.get('nodes')):
        found.add('system_information')
    nodes=sample.get('nodes') if isinstance(sample.get('nodes'),list) else []
    if isinstance(sample.get('cpu_percent'),(float,int)) or _has(sample.get('cpu_counters')) or _has(resource.get('cpu-load')) or any(isinstance(v,dict) and _has(v.get('cpu')) for v in nodes):
        found.add('cpu')
    if isinstance(sample.get('memory_percent'),(float,int)) or _has(resource.get('total-memory')) or any(isinstance(v,dict) and _has(v.get('mem')) for v in nodes):
        found.add('memory')
    if _has(sample.get('disks')) or _has(sample.get('storage')) or _has(resource.get('total-hdd-space')):found.add('storage')
    if isinstance(interfaces,list) and interfaces:found.add('interfaces')
    if isinstance(interfaces,list) and any(isinstance(row,dict) and any(_has(row.get(k)) for k in ('rx_bps','tx_bps','rx-byte','tx-byte','rx_bytes','tx_bytes')) for row in interfaces):found.add('traffic')
    if isinstance(interfaces,list) and any(isinstance(row,dict) and (_has(row.get('rx_bps')) or _has(row.get('tx_bps')) or _has(row.get('rx_bits_per_second')) or _has(row.get('tx_bits_per_second'))) for row in interfaces):found.add('bandwidth')
    if _has(data.get('/interface/vlan')) or _has(sample.get('vlans')):found.add('vlan')
    if _has(data.get('/ip/route')) or _has(sample.get('routes')):found.add('routing')
    if _has(data.get('/interface/wireless')) or _has(data.get('/interface/wifi')) or _has(sample.get('wireless')):found.add('wireless')
    if _has(data.get('/system/health')) or _has(sample.get('temperature')):found.add('temperature')
    if _has(sample.get('sensors')):found.add('sensors')
    if _has(sample.get('nodes')) or _has(sample.get('guests')) or _has(sample.get('storage')):found.add('virtualization')
    if _has(sample.get('http_status')) or _has(sample.get('query')):found.add('service_health')
    return [key for key in CATEGORIES if key in found]


def telemetry(sample):
    if not isinstance(sample,dict):return {}
    data=sample.get('data') if isinstance(sample.get('data'),dict) else {}
    out={}
    for key in ('status','error','method','latency_ms','packet_loss_percent','http_status','uptime_seconds','cpu_percent','memory_percent','memory_total','memory_available','host','sample_epoch'):
        value=sample.get(key)
        if value is None or type(value) in (bool,int,float) or isinstance(value,str):out[key]=value
    info=sample.get('system_info') if isinstance(sample.get('system_info'),dict) else {}
    identity=data.get('/system/identity')
    resource=data.get('/system/resource')
    board=data.get('/system/routerboard')
    if isinstance(resource,list) and resource and isinstance(resource[0],dict):
        row=resource[0]
        try:
            if out.get('cpu_percent') is None and row.get('cpu-load') is not None:out['cpu_percent']=float(row['cpu-load'])
        except (TypeError,ValueError):pass
        try:
            total=int(row.get('total-memory',0));free=int(row.get('free-memory',0))
            if total>0:
                if out.get('memory_percent') is None:out['memory_percent']=round(max(0,min(100,(total-free)*100/total)),2)
                if out.get('memory_total') is None:out['memory_total']=total
                if out.get('memory_available') is None:out['memory_available']=free
        except (TypeError,ValueError):pass
    if info:out['system_info']={k:str(v)[:240] for k,v in info.items() if k in {'name','description','object_id','version','release'} and v is not None}
    if isinstance(identity,list) and identity and isinstance(identity[0],dict):out.setdefault('system_info',{})['name']=str(identity[0].get('name',''))[:128]
    if isinstance(resource,list) and resource and isinstance(resource[0],dict):out['system_info']={**out.get('system_info',{}),**{k:str(resource[0][k])[:80] for k in ('version','board-name','architecture-name','uptime','cpu-load','total-memory','free-memory','total-hdd-space','free-hdd-space') if resource[0].get(k) is not None}}
    if isinstance(board,list) and board and isinstance(board[0],dict):out.setdefault('system_info',{}).update({k:str(board[0][k])[:80] for k in ('model','routerboard') if board[0].get(k) is not None})
    interfaces=sample.get('interfaces') if isinstance(sample.get('interfaces'),list) and sample['interfaces'] else data.get('/interface',[])
    if isinstance(interfaces,list):
        rows=[]
        for row in interfaces[:32]:
            if not isinstance(row,dict):continue
            item={}
            for key in ('index','name','status','running','disabled','rx_bps','tx_bps','rx_bits_per_second','tx_bits_per_second','capacity_bps','sample_seconds','rx_bytes','tx_bytes','rx-byte','tx-byte','rx-error','tx-error','rx-drop','tx-drop'):
                value=row.get(key)
                if value is None or type(value) in (bool,int,float) or isinstance(value,str):item[key]=value
            if item:rows.append(item)
        if rows:out['interfaces']=rows
    for key,source,keys in (
        ('nodes','nodes',('node','status','cpu','mem','maxmem','uptime')),
        ('guests','guests',('vmid','name','node','type','status','cpu','mem','uptime')),
        ('storage','storage',('node','storage','status','disk','maxdisk')),
        ('disks','disks',('path','used_percent','total','used','free')),
        ('vlans','vlans',('name','vlan-id','interface','disabled')),
        ('routes','routes',('dst-address','gateway','active','distance','routing-table')),
    ):
        values=sample.get(source)
        if source=='vlans' and values is None:values=data.get('/interface/vlan')
        if source=='routes' and values is None:values=data.get('/ip/route')
        if isinstance(values,list):out[key]=[{k:(str(row[k])[:128] if isinstance(row[k],str) else row[k]) for k in keys if k in row and (row[k] is None or type(row[k]) in (bool,int,float) or isinstance(row[k],str))} for row in values[:32] if isinstance(row,dict)]
    if isinstance(out.get('nodes'),list) and out['nodes']:
        node=out['nodes'][0]
        try:
            if out.get('cpu_percent') is None and isinstance(node.get('cpu'),(int,float)):out['cpu_percent']=round(max(0,min(100,node['cpu']*100)),2)
            maximum=node.get('maxmem');used=node.get('mem')
            if out.get('memory_percent') is None and isinstance(maximum,(int,float)) and maximum>0 and isinstance(used,(int,float)):
                out['memory_percent']=round(max(0,min(100,used*100/maximum)),2);out['memory_total']=maximum;out['memory_available']=max(0,maximum-used)
        except (TypeError,ValueError):pass
    if isinstance(out.get('interfaces'),list):
        for row in out['interfaces']:
            if row.get('rx_bps') is None and isinstance(row.get('rx_bits_per_second'),(int,float)):row['rx_bps']=row['rx_bits_per_second']
            if row.get('tx_bps') is None and isinstance(row.get('tx_bits_per_second'),(int,float)):row['tx_bps']=row['tx_bits_per_second']
    return out
