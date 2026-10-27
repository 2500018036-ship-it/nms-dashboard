"""Temporary routing references, never conversation text or monitoring readings."""
from collections import OrderedDict
from copy import deepcopy
import json
import re
import time

ALLOWED_ARGUMENTS = {'section','target','offset','limit','filter_field','filter_value'}

def metric_followup(question,references):
    q=question.lower().strip()
    if not references or len(q)>80:return None
    if re.search(r'\b(mikrotik|routeros|router|docker|debian|proxmox|pve|dns|technitium|cloud|website)\b',q):return None
    if re.match(r'^(apa itu|apa fungsi|apa yang dimaksud|bagaimana cara|cara |jelaskan)',q):return None
    if re.search(r'\b(kenapa|mengapa|penyebab|analisis|saran)\b',q):return None
    metric='memory' if re.search(r'ram|memori',q) else 'cpu' if 'cpu' in q else 'traffic' if re.search(r'trafik|bandwidth|rx|tx',q) else None
    if not metric:return None
    domains=set()
    for item in references:
        args=item['arguments'];target=args.get('target','')
        if item['tool']=='get_mikrotik_data' or target.startswith('mikrotik'):domains.add('mikrotik')
        elif target in {'docker','debian','proxmox_resources'}:domains.add(target)
        else:return {'clarify':True}
    if len(domains)!=1:return {'clarify':True}
    domain=next(iter(domains))
    if domain=='mikrotik':
        args={'section':'traffic' if metric=='traffic' else 'system'}
        previous=references[-1]['arguments']
        if metric=='traffic' and previous.get('filter_field')=='name':
            args.update(filter_field='name',filter_value=previous['filter_value'])
        return {'tool':'get_mikrotik_data','arguments':args,'metric':metric}
    if metric=='traffic':return {'clarify':True}
    return {'tool':'check_service','arguments':{'target':domain},'metric':metric}

def focus_metric(value,metric):
    value=deepcopy(value)
    if value.get('status')=='UNKNOWN':return value
    if value.get('target')=='docker':
        fields={'name','state','health'}|({'cpu_percent','cpu_limit_nano'} if metric=='cpu' else {'memory_bytes','memory_limit_bytes'})
        value['containers']=[{k:v for k,v in row.items() if k in fields} for row in value.get('containers',[])]
    elif value.get('target')=='debian':
        fields={'target','status','method','timestamp'}|({'cpu_percent'} if metric=='cpu' else {'memory_total','memory_available','memory_percent'})
        value={k:v for k,v in value.items() if k in fields}
    elif value.get('section')=='system':
        fields={'cpu','cpu-load','cpu-count','cpu-frequency'} if metric=='cpu' else {'total-memory','free-memory'}
        value['data']={path:[{k:v for k,v in row.items() if path=='/system/identity' or k in fields} for row in entries]
            for path,entries in value.get('data',{}).items() if path in {'/system/resource','/system/identity'}}
        value['resources']={path:meta for path,meta in value.get('resources',{}).items() if path in value['data']}
    return value

def reference(name, arguments, result):
    if name not in {'get_mikrotik_data','check_service','check_all_endpoints','compare_previous','check_tcp_endpoint'}:
        return None
    if result.get('error') in {'invalid_arguments','unknown_tool'}:
        return None
    args={k:v for k,v in arguments.items() if k in ALLOWED_ARGUMENTS}
    cursor=None
    if name=='get_mikrotik_data':
        for meta in result.get('resources',{}).values():
            if meta.get('has_more') and type(meta.get('next_offset')) is int:
                cursor=meta['next_offset']
                break
        if result.get('status')=='UNKNOWN' and type(args.get('offset')) is int and args['offset']>0:
            cursor=args['offset']
    return {'tool':name,'arguments':args,'next_offset':cursor}


class ContextStore:
    def __init__(self, ttl=600, max_users=64, clock=None):
        self.ttl,self.max_users,self.clock=ttl,max_users,clock or time.monotonic
        self.entries=OrderedDict()
        self.versions={}

    def version(self,user):return self.versions.get(user,0)

    def get(self,user):
        now=self.clock()
        for key,(stamp,_) in list(self.entries.items()):
            if now-stamp>=self.ttl:self.entries.pop(key,None)
        item=self.entries.get(user)
        return deepcopy(item[1]) if item else []

    def set(self,user,references,expected_version=None):
        if expected_version is not None and expected_version!=self.version(user):return
        latest=OrderedDict()
        for item in references:
            if item:
                key=(item['tool'],json.dumps({k:v for k,v in item['arguments'].items() if k not in {'offset','limit'}},sort_keys=True))
                previous=latest.get(key)
                if previous and previous['arguments'].get('offset',0)>item['arguments'].get('offset',0):continue
                latest[key]=item
                latest.move_to_end(key)
        safe=list(latest.values())[-4:]
        if safe:
            self.versions[user]=self.version(user)+1
            self.entries[user]=(self.clock(),deepcopy(safe))
            self.entries.move_to_end(user)
            while len(self.entries)>self.max_users:self.entries.popitem(last=False)
        else:self.clear(user)

    def clear(self,user):
        self.versions[user]=self.version(user)+1
        self.entries.pop(user,None)
