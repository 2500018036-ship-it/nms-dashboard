"""Closed, bounded public projections of already collected telemetry."""
from datetime import datetime
import math
import re

STATUS = {'UP', 'DOWN', 'DEGRADED', 'UNKNOWN'}

def text(value, limit=180):
    return re.sub(r'[\x00-\x1f\x7f]', '', value)[:limit] if isinstance(value, str) else None

def project(row, fields):
    if not isinstance(row, dict): return {}
    result = {}
    for key in fields.split(','):
        value = row.get(key)
        if isinstance(value, str): result[key] = text(value)
        elif value is None or type(value) in (bool, int) or isinstance(value, float) and math.isfinite(value): result[key] = value
    return result

def rows(value, fields, limit=200):
    return [project(r, fields) for r in value[:limit] if isinstance(r, dict)] if isinstance(value, list) else []

def sample_time(row, saved):
    try:
        observed = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).timestamp()
        return min(saved, observed) if observed > 0 else saved
    except (KeyError, ValueError, TypeError, AttributeError): return saved

def check(row, saved, now, interval):
    out = project(row, 'target,method,timestamp,host,display_name,address_source,previous_host,port,latency_ms,packet_loss_percent,http_status,query,cpu_percent,memory_percent,memory_total,memory_available,uptime_seconds,age_seconds,scan_truncated,management_configured,neighbor_read_status,embedding_supported,configuration_hash')
    out['sample_epoch'] = sample_time(row, saved)
    out['reported_status'] = row.get('status') if row.get('status') in STATUS else 'UNKNOWN'
    out['stale_after_seconds'] = max(120,min(10800,interval*3))
    out['stale'] = now - out['sample_epoch'] > out['stale_after_seconds']
    out['status'] = 'UNKNOWN' if out['stale'] else out['reported_status']
    error = row.get('error')
    if isinstance(error, str) and re.fullmatch(r'[\w:.-]{1,80}', error): out['error'] = error
    out['read_state'] = ('stale' if out['stale'] else 'offline' if out['status'] == 'DOWN' else
                         'collection_failed' if error else 'unavailable' if out['status'] == 'UNKNOWN' else out['status'].lower())
    out['answers'] = [text(a) for a in row.get('answers', [])[:8] if isinstance(a, str)] if isinstance(row.get('answers'), list) else []
    out['disks'] = rows(row.get('disks'), 'path,used_percent,total,used,free', 32)
    out['interfaces'] = rows(row.get('interfaces'), 'index,name,type,running,disabled,status,rx_bps,tx_bps,capacity_bps,utilization_percent,sample_seconds,duplex,rx_bytes,tx_bytes,rx_errors,tx_errors,rx_drops,tx_drops,mtu', 200)
    out['nodes'] = rows(row.get('nodes'), 'id,node,status,cpu,maxcpu,mem,maxmem,disk,maxdisk,uptime', 16)
    out['guests'] = rows(row.get('guests'), 'id,vmid,name,node,type,status,cpu,maxcpu,mem,maxmem,disk,maxdisk,uptime,netin,netout,diskread,diskwrite', 100)
    out['storage'] = rows(row.get('storage'), 'id,node,storage,status,disk,maxdisk', 50)
    out['tasks'] = rows(row.get('tasks'), 'node,type,status,starttime,endtime', 40)
    out['version'] = project(row.get('version'), 'version,release')
    out['readonly_verified'] = row.get('readonly_verified') is True
    out['containers'] = rows(row.get('containers'), 'name,state,health,image,restart_count,cpu_percent,memory_bytes,memory_limit_bytes,expected_running', 100)
    out['data'] = {}
    allowed = {
        '/system/resource': 'uptime,version,board-name,architecture-name,cpu-load,cpu-count,cpu-frequency,total-memory,free-memory,total-hdd-space,free-hdd-space',
        '/system/identity': 'name', '/system/routerboard': 'model,routerboard',
        '/interface': 'name,type,running,disabled,mtu,rx-byte,tx-byte,rx-packet,tx-packet,rx-error,tx-error,rx-drop,tx-drop,rx_bits_per_second,tx_bits_per_second,sample_seconds,rate_sample_valid',
        '/interface/vlan': 'name,interface,vlan-id,disabled,running',
        '/interface/wireless': 'name,ssid,mode,band,frequency,channel-width,running,disabled,signal-strength,noise-floor',
        '/system/health': 'name,value,temperature,voltage,current,frequency',
        '/ip/neighbor': 'identity,address,interface,platform,version',
        '/ip/route': 'dst-address,gateway,active,disabled,distance,routing-table',
        '/interface/wireguard/peers': 'name,interface,disabled,last-handshake,rx,tx',
    }
    raw = row.get('data') if isinstance(row.get('data'), dict) else {}
    for path, fields in allowed.items():
        if path in raw: out['data'][path] = rows(raw[path], fields)
    if isinstance(row.get('system_info'),dict):out['system_info']=project(row['system_info'],'name,description,object_id,version,release')
    out['peers'] = rows(row.get('peers'), 'name,interface,disabled,last-handshake,handshake_age_seconds,rx,tx', 100)
    return out

def event(value, key='', kind=''):
    from app.alerts.presentation import metadata
    return metadata(value, key, kind)
