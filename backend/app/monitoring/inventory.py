"""Inventory enrollment into the existing monitoring engine, no browser polling."""
import os
import ipaddress
from app.monitoring import tcp,dns,icmp
from app.monitoring.common import result
from app.monitoring.service_probe import probe

def binding(item):
    method=item.get('monitor_method','');ref=item.get('credential_ref','')
    if method in {'routeros','proxmox'}:
        expected='routeros-default' if method=='routeros' else 'proxmox-default'
        host=os.getenv('MIKROTIK_HOST','192.168.20.1') if method=='routeros' else os.getenv('PROXMOX_HOST','192.168.20.200')
        if ref!=expected or item['host']!=host:raise ValueError('credential_host_mismatch')
        return 'mikrotik_system' if method=='routeros' else 'proxmox_resources'
    if ref:raise ValueError('unexpected_credential_reference')
    return ''

def scheduled(item):
    return item['enabled'] and item.get('monitor_method') in {'icmp','tcp','http','dns'}

async def collect(item,allowed_hosts):
    target='inventory_'+item['id'];method=item.get('monitor_method')
    if item['host'] not in allowed_hosts:return result(target,'inventory',error='host_not_allowed')
    if method in {'icmp','tcp','dns'}:
        try:ipaddress.IPv4Address(item['host'])
        except ValueError:return result(target,'inventory',error='literal_ipv4_required')
    if method=='icmp':value=await icmp.probe(target,item['host'])
    elif method=='tcp':value=await tcp.probe(target,item['host'],item['monitor_port'])
    elif method=='dns':value=await dns.probe(target,item['host'],item['monitor_port'],item['dns_query'])
    elif method=='http':value=await probe(target,item['monitor_url'],allowed_hosts)
    else:return result(target,'inventory',error='adapter_not_configured')
    return {**value,'host':item['host'],'display_name':item['name']}
