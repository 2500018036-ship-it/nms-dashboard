"""Pinned-host-key SSH metrics for Linux; command surface is fixed and read-only."""
import asyncio
import re
import time
from datetime import datetime, timezone

from app.monitoring.common import result

# This constant contains no user-controlled text and never invokes sudo or a write command.
COMMANDS={
    'system_information':"printf 'NMS_UNAME\\n'; uname -srmo; printf 'NMS_UPTIME\\n'; cat /proc/uptime",
    'cpu':"printf 'NMS_CPU\\n'; head -n 1 /proc/stat",
    'memory':"printf 'NMS_MEM\\n'; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo",
    'storage':"printf 'NMS_DF\\n'; df -B1 -P -x tmpfs -x devtmpfs /",
    'interfaces':"printf 'NMS_NET\\n'; cat /proc/net/dev",
    'traffic':"printf 'NMS_NET\\n'; cat /proc/net/dev",
    'bandwidth':"printf 'NMS_NET\\n'; cat /proc/net/dev",
}
def _command(categories):
    selected=set(categories or ())
    parts=list(dict.fromkeys(COMMANDS[key] for key in COMMANDS if key in selected))
    return '; '.join(parts) if parts else "printf 'NMS_OK\\n'"


def _sections(output):
    sections={};current=None
    for line in output.splitlines():
        match=re.fullmatch(r'NMS_(UNAME|UPTIME|MEM|DF|CPU|NET)',line.strip())
        if match:current=match.group(1);sections[current]=[]
        elif current:sections[current].append(line.strip())
    return sections


def _previous_interfaces(previous):
    if not isinstance(previous,dict):return {}
    return {str(row.get('name')):row for row in previous.get('interfaces',[]) if isinstance(row,dict) and row.get('name')}


def _positive(value):
    try:
        number=int(value)
        return number if number>=0 else None
    except (ValueError,TypeError):return None


def _read_metrics(output,previous):
    sections=_sections(output);now=time.time();parsed={}
    uname=' '.join(sections.get('UNAME',[]))[:160]
    uptime=None
    try:uptime=float(sections.get('UPTIME',[''])[0].split()[0])
    except (IndexError,ValueError):pass
    memory={}
    for line in sections.get('MEM',[]):
        match=re.fullmatch(r'(MemTotal|MemAvailable):\s+(\d+)\s+kB',line)
        if match:memory[match.group(1)]=int(match.group(2))*1024
    if memory.get('MemTotal',0)>0 and 'MemAvailable' in memory:
        total=memory['MemTotal'];available=memory['MemAvailable']
        parsed.update(memory_total=total,memory_available=available,memory_percent=round((total-available)*100/total,2))
    disk=[]
    for line in sections.get('DF',[])[1:]:
        fields=line.split()
        if len(fields)>=6 and fields[1].isdigit() and fields[2].isdigit() and fields[3].isdigit():
            total=int(fields[1]);used=int(fields[2]);disk.append({'path':fields[5][:128],'total':total,'used':used,'free':int(fields[3]),'used_percent':round(used*100/total,2) if total else None})
    if disk:parsed['disks']=disk[:8]
    cpu=sections.get('CPU',[''])
    if cpu and cpu[0].startswith('cpu '):
        counters=[_positive(value) for value in cpu[0].split()[1:]]
        if len(counters)>=4 and all(value is not None for value in counters):
            # Linux guest/guest_nice counters are already included in user/nice.
            current={'total':sum(counters[:8] if len(counters)>8 else counters),'idle':counters[3]+(counters[4] if len(counters)>4 else 0)}
            previous_cpu=previous.get('cpu_counters',{}) if isinstance(previous,dict) else {}
            try:
                elapsed=current['total']-int(previous_cpu['total']);idle=current['idle']-int(previous_cpu['idle'])
                if elapsed>0 and 0<=idle<=elapsed:parsed['cpu_percent']=round((elapsed-idle)*100/elapsed,2)
            except (KeyError,TypeError,ValueError):pass
            parsed['cpu_counters']=current
    old_interfaces=_previous_interfaces(previous);interfaces=[]
    net_lines=sections.get('NET',[])
    for line in net_lines[2:]:
        if ':' not in line:continue
        name,raw=line.split(':',1);name=name.strip()
        if not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,64}',name):continue
        values=raw.split()
        if len(values)<16:continue
        rx=_positive(values[0]);tx=_positive(values[8])
        if rx is None or tx is None:continue
        row={'name':name,'rx_bytes':rx,'tx_bytes':tx}
        old=old_interfaces.get(name,{})
        try:
            old_rx=int(old['rx_bytes']);old_tx=int(old['tx_bytes'])
            old_at=float(previous.get('sample_epoch') or datetime.fromisoformat(previous['timestamp'].replace('Z','+00:00')).timestamp())
            elapsed=now-old_at
            if elapsed>=1 and rx>=old_rx and tx>=old_tx:
                row.update(rx_bps=round((rx-old_rx)*8/elapsed,2),tx_bps=round((tx-old_tx)*8/elapsed,2),sample_seconds=round(elapsed,2))
        except (KeyError,TypeError,ValueError):pass
        interfaces.append(row)
    if interfaces:parsed['interfaces']=interfaces[:32]
    if uname:parsed['system_info']={'name':uname.split()[0], 'description':uname}
    if uptime is not None:parsed['uptime_seconds']=uptime
    return parsed


async def probe(target,host,port,credentials,categories,previous=None,vendor='',model=''):
    if re.search(r'windows|microsoft',f'{vendor} {model}'.lower()):
        return result(target,'SSH',error='ssh_unsupported_os',host=host)
    config=credentials if isinstance(credentials,dict) else {}
    username=config.get('username','');password=config.get('password','');key_type=config.get('host_key_type','');key_data=config.get('host_key_data','')
    if not username or not password or key_type not in {'ssh-ed25519','ecdsa-sha2-nistp256'} or not key_data:
        return result(target,'SSH',error='missing_ssh_credentials',host=host)
    try:
        import asyncssh
    except ImportError:return result(target,'SSH',error='adapter_unavailable',host=host)
    pattern=host if port==22 else f'[{host}]:{port}'
    try:
        try:known_hosts=asyncssh.import_known_hosts(f'{pattern} {key_type} {key_data}')
        except (asyncssh.Error,ValueError):return result(target,'SSH',error='ssh_host_key_invalid',host=host)
        started=time.monotonic()
        async with asyncssh.connect(host,port=port,username=username,password=password,known_hosts=known_hosts,
            config=None,request_pty=False,client_keys=[],agent_path=None,preferred_auth='password',
            password_auth=True,public_key_auth=False,kbdint_auth=False,connect_timeout=4,login_timeout=4,keepalive_interval=0) as connection:
            reply=await connection.run(_command(categories),check=False,timeout=8,encoding='utf-8')
        if getattr(reply,'exit_status',0)!=0:
            return result(target,'SSH pinned host key',error='ssh_command_failed',host=host)
        value=_read_metrics(reply.stdout,previous)
        if not value.get('system_info',{}).get('description') and 'system_information' in set(categories or ()):
            return result(target,'SSH',error='ssh_unsupported_os',host=host)
        return result(target,'SSH pinned host key','UP',host=host,latency_ms=round((time.monotonic()-started)*1000,2),**value)
    except asyncio.TimeoutError:return result(target,'SSH',error='timeout',host=host)
    except asyncssh.HostKeyNotVerifiable:return result(target,'SSH',error='ssh_host_key_mismatch',host=host)
    except asyncssh.PermissionDenied:return result(target,'SSH',error='authentication_failed',host=host)
    except (asyncssh.Error,OSError,ValueError):return result(target,'SSH',error='ssh_connection_failed',host=host)
