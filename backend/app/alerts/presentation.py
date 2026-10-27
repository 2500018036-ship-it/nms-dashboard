"""Shared event presentation, not a second alert-decision engine."""
import math
import re
from app.logging_config import redact

def clean(value, limit=240):
    return re.sub(r'[\x00-\x1f\x7f]', '', redact(value))[:limit] if isinstance(value, str) else None

def metadata(value, key='', kind=''):
    value = value if isinstance(value, dict) else {}
    key = key or value.get('key', '')
    kind = kind or value.get('kind', '')
    out = {k: clean(value[k]) for k in ('title', 'device', 'severity') if isinstance(value.get(k), str)}
    for field in ('first_seen', 'recovered_at'):
        number = value.get(field)
        if type(number) in (int, float) and math.isfinite(number): out[field] = number
    if kind not in {'ALERT', 'RECOVERY', 'CHANGE'}: return out
    out.setdefault('device', clean(key.split(':', 1)[0]) or 'Collector')
    out.setdefault('title', 'Layanan pulih' if kind == 'RECOVERY' else 'Perubahan monitoring' if kind == 'CHANGE' else 'Peringatan monitoring')
    if out.get('severity') not in {'INFO', 'WARNING', 'CRITICAL'}:
        evidence = value.get('value') if isinstance(value.get('value'), dict) else {}
        number = evidence.get('value')
        critical = kind == 'ALERT' and any(k in key for k in ('storage', 'disk')) and type(number) in (int, float) and number >= 95
        out['severity'] = 'INFO' if kind != 'ALERT' else 'CRITICAL' if critical else 'WARNING'
        out['severity_source'] = 'rule_default'
    return out

def evidence(value):
    allowed = {'status','method','error','value','threshold','hysteresis','state','health','running','disabled',
        'restart_delta_15m','name','node','interface','source','previous','current','bits_per_second','baseline_bps',
        'handshake_age_seconds','scope','certainty','host','direction','utilization_percent','capacity_bps',
        'cpu_percent','memory_percent','latency_ms','http_status','rx_percent','tx_percent','sustained_seconds','duplex','rx_bps','tx_bps','threshold_seconds','reason'}
    out = {}
    if not isinstance(value, dict): return out
    for key in allowed & value.keys():
        item = value[key]
        if isinstance(item, str): out[key] = clean(item, 500)
        elif item is None or type(item) in (bool, int) or type(item) is float and math.isfinite(item): out[key] = item
    return out
