#!/usr/bin/env python3
"""Trusted host collector. No network listener, commands, env/labels/mounts or raw logs exported."""
import datetime
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import time

OUT = Path('/var/lib/nms-collector')

class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(4)
        self.sock.connect('/var/run/docker.sock')

def docker_get(path):
    allowed = path == '/containers/json?all=true' or re.fullmatch(r'/containers/[a-f0-9]{64}/(json|stats\?stream=false|logs\?stdout=true&stderr=true&tail=20)',path)
    if not allowed:
        raise ValueError('endpoint_not_allowed')
    connection = UnixConnection('localhost', timeout=4)
    try:
        connection.request('GET',path)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('docker_http_'+str(response.status))
        maximum = 1000000 if path == '/containers/json?all=true' else 262144
        body = response.read(maximum+1)
        if len(body) > maximum:
            raise ValueError('response_too_large')
        return body if '/logs?' in path else json.loads(body)
    finally:
        connection.close()

def atomic(path,value):
    temp=path.with_suffix('.tmp')
    with open(temp,'w') as stream:
        json.dump(value,stream,allow_nan=False)
    os.chmod(temp,0o644)
    os.replace(temp,path)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    daemon='UP'
    scan_truncated=True
    try:
        items=docker_get('/containers/json?all=true')
        scan_truncated=len(items)>100
        for item in items[:100]:
            identity=item['Id']
            try:
                detail=docker_get('/containers/'+identity+'/json')
                state=detail.get('State',{})
                limits=detail.get('HostConfig',{})
                ports=[{'private':p.get('PrivatePort'),'public':p.get('PublicPort'),'bind':p.get('IP'),'type':p.get('Type')} for p in item.get('Ports',[])][:20]
                row={'name':detail.get('Name','').lstrip('/')[:100], 'image':detail.get('Config',{}).get('Image','')[:150],
                    'state':state.get('Status'),'health':state.get('Health',{}).get('Status','not_configured'),
                    'started_at':state.get('StartedAt'), 'restart_count':detail.get('RestartCount',0),
                    'memory_limit_bytes':limits.get('Memory',0),'cpu_limit_nano':limits.get('NanoCpus',0),'ports':ports,
                    'cpu_percent':None,'memory_bytes':None}
                if state.get('Running'):
                    stats=docker_get('/containers/'+identity+'/stats?stream=false')
                    cpu,prev=stats.get('cpu_stats',{}),stats.get('precpu_stats',{})
                    delta=cpu.get('cpu_usage',{}).get('total_usage',0)-prev.get('cpu_usage',{}).get('total_usage',0)
                    total=cpu.get('system_cpu_usage',0)-prev.get('system_cpu_usage',0)
                    if total>0 and prev:
                        row['cpu_percent']=round(delta/total*cpu.get('online_cpus',1)*100,2)
                    memory=stats.get('memory_stats',{})
                    row['memory_bytes']=max(0,memory.get('usage',0)-memory.get('stats',{}).get('inactive_file',0))
                    row['memory_limit_bytes']=memory.get('limit',row['memory_limit_bytes'])
                # Export only aggregate counts, never untrusted raw lines or secrets.
                try:
                    log_body=docker_get('/containers/'+identity+'/logs?stdout=true&stderr=true&tail=20').lower()
                    row['recent_log_summary']={'sample_max_lines':20,'error_markers':len(re.findall(rb'\b(error|fatal|panic|exception)\b',log_body)),'raw_logs_exported':False}
                except Exception:
                    row['recent_log_summary']={'status':'UNKNOWN','raw_logs_exported':False}
                rows.append(row)
            except Exception as exc:
                rows.append({'name':item.get('Names',['unknown'])[0].lstrip('/'),'state':item.get('State'),'collector_error':type(exc).__name__})
                daemon='DEGRADED'
    except Exception as exc:
        daemon='UNKNOWN'
    mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1)
        mem[key]=int(value.strip().split()[0])*1024
    cpus=[int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    total,idle=sum(cpus),cpus[3]+cpus[4]
    cpu_pct=None
    try:
        previous=json.loads((OUT/'cpu.json').read_text())
        delta=total-previous['total']
        if delta>0: cpu_pct=round(100*(1-(idle-previous['idle'])/delta),2)
    except (OSError,ValueError,KeyError):
        pass
    atomic(OUT/'cpu.json',{'total':total,'idle':idle})
    disks=[]
    for path in ('/','/mnt/data'):
        disk=shutil.disk_usage(path)
        disks.append({'path':path,'total':disk.total,'used':disk.used,'used_percent':round(100*disk.used/disk.total,2)})
    atomic(OUT/'snapshot.json',{'collected_at':time.time(),'docker':{'status':daemon,'containers':rows,'scan_truncated':scan_truncated},
        'host':{'cpu_percent':cpu_pct,'memory_total':mem['MemTotal'],'memory_available':mem['MemAvailable'],
            'memory_percent':round((1-mem['MemAvailable']/mem['MemTotal'])*100,2),'disks':disks,
            'uptime_seconds':float(Path('/proc/uptime').read_text().split()[0])}})

if __name__=='__main__':
    main()
