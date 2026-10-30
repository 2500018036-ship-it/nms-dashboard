"""Read-only SNMPv2c/v3 polling for system identity and standard IF-MIB."""
from datetime import datetime, timezone
import time

from app.monitoring.common import result

SYS_OIDS = {
    'description': '1.3.6.1.2.1.1.1.0',
    'object_id': '1.3.6.1.2.1.1.2.0',
    'uptime_ticks': '1.3.6.1.2.1.1.3.0',
    'name': '1.3.6.1.2.1.1.5.0',
    'interface_count': '1.3.6.1.2.1.2.1.0',
}
IF_OIDS = {
    'name': '1.3.6.1.2.1.31.1.1.1.1',
    'oper_status': '1.3.6.1.2.1.2.2.1.8',
    'speed_mbps': '1.3.6.1.2.1.31.1.1.1.15',
    'rx_bytes': '1.3.6.1.2.1.31.1.1.1.6',
    'tx_bytes': '1.3.6.1.2.1.31.1.1.1.10',
}


def _value(varbind):
    from pysnmp.proto.rfc1905 import NoSuchObject,NoSuchInstance,EndOfMibView
    if isinstance(varbind[1],(NoSuchObject,NoSuchInstance,EndOfMibView)):return None
    try:
        return varbind[1].prettyPrint()
    except (AttributeError, IndexError, TypeError):
        return str(varbind[1])


def _number(value):
    try:
        parsed=int(value)
        return parsed if parsed>=0 else None
    except (TypeError, ValueError):
        return None


def _previous_interfaces(previous):
    if not isinstance(previous,dict):return {}
    return {str(row.get('index')):row for row in previous.get('interfaces',[]) if isinstance(row,dict) and row.get('index') is not None}


async def _interface_names(engine,auth,address,limit):
    from pysnmp.hlapi.v3arch.asyncio import walk_cmd,ContextData,ObjectType,ObjectIdentity
    # ifIndex values can have gaps and are never derived from ifNumber.
    for base in (IF_OIDS['name'],'1.3.6.1.2.1.2.2.1.2'):
        found={};prefix=base+'.'
        async for error,status,_,values in walk_cmd(engine,auth,address,ContextData(),ObjectType(ObjectIdentity(base)),lookupMib=False,lexicographicMode=False,maxRows=limit,maxCalls=limit+1):
            if error or status:break
            for oid,value in values:
                oid_text=oid.prettyPrint()
                if not oid_text.startswith(prefix):continue
                index=_number(oid_text[len(prefix):]);name=_value((oid,value))
                if index and name:found[index]=name[:128]
                if len(found)>=limit:break
            if len(found)>=limit:break
        if found:return found
    return {}


async def probe(target, host, port, config, categories, previous=None):
    if not isinstance(config,dict) or config.get('version') not in {'v2c','v3'}:
        return result(target,'SNMP',error='missing_snmp_credentials',host=host)
    try:
        from pysnmp.hlapi.v3arch.asyncio import (
            CommunityData, ContextData, ObjectIdentity, ObjectType, SnmpEngine,
            UsmUserData, UdpTransportTarget, get_cmd,
            usmAesCfb128Protocol, usmHMACSHAAuthProtocol,
        )
        if config.get('version')=='v2c':
            auth=CommunityData(config['community'],mpModel=1)
        else:
            auth_protocol=usmHMACSHAAuthProtocol
            if config.get('auth_protocol')=='sha256':
                try:
                    from pysnmp.hlapi.v3arch.asyncio import usmHMAC192SHA256AuthProtocol
                    auth_protocol=usmHMAC192SHA256AuthProtocol
                except ImportError:
                    return result(target,'SNMPv3',error='unsupported_auth_protocol',host=host)
            auth=UsmUserData(config['username'],authKey=config['auth_secret'],privKey=config['privacy_secret'],
                authProtocol=auth_protocol,privProtocol=usmAesCfb128Protocol)
    except ImportError:
        return result(target,'SNMP',error='adapter_unavailable',host=host)

    engine=SnmpEngine()
    try:
        started=time.monotonic()
        address=await UdpTransportTarget.create((host,port),timeout=1.5,retries=0)
        wanted=[ObjectType(ObjectIdentity(oid)) for oid in SYS_OIDS.values()]
        indication,status,index,varbinds=await get_cmd(engine,auth,address,ContextData(),*wanted,lookupMib=False)
        if indication:
            message=str(indication).lower()
            error='timeout' if 'timeout' in message or 'no snmp response' in message else 'snmp_request_failed'
            return result(target,'SNMPv3' if config['version']=='v3' else 'SNMPv2c',error=error,host=host)
        if status:
            return result(target,'SNMP',error='snmp_agent_error',host=host)
        raw={key:_value(value) for key,value in zip(SYS_OIDS,varbinds)}
        if not raw.get('description') or 'no such' in raw['description'].lower():
            return result(target,'SNMP',error='snmp_identity_unavailable',host=host)
        telemetry={'system_info':{
            'name':(raw.get('name') or '')[:128], 'description':raw['description'][:240],
            'object_id':(raw.get('object_id') or '')[:128]},
            'uptime_seconds':round(_number(raw['uptime_ticks'])/100,2) if _number(raw.get('uptime_ticks')) is not None else None}
        reported=_number(raw.get('interface_count'))
        count=min(reported or 128,128)
        interfaces=[]
        requested=set(categories or ())
        if requested.intersection({'interfaces','traffic','bandwidth'}):
            names=await _interface_names(engine,auth,address,count)
            discovered=sorted(names)
            previous_rows=_previous_interfaces(previous)
            old_epoch=None
            if isinstance(previous,dict) and isinstance(previous.get('timestamp'),str):
                try:old_epoch=datetime.fromisoformat(previous['timestamp'].replace('Z','+00:00')).timestamp()
                except ValueError:pass
            now=datetime.now(timezone.utc).timestamp()
            elapsed=now-old_epoch if old_epoch else None
            fields=tuple(IF_OIDS.items())
            # Bound the request size: four interfaces (20 varbinds) per datagram.
            for start in range(0,len(discovered),4):
                indices=discovered[start:start+4]
                requested_oids=[(key,f'{base}.{number}') for number in indices for key,base in fields]
                objects=[ObjectType(ObjectIdentity(oid)) for _,oid in requested_oids]
                err,pdu_error,pdu_index,values=await get_cmd(engine,auth,address,ContextData(),*objects,lookupMib=False)
                if err or pdu_error:continue
                for offset,number in enumerate(indices):
                    row={}
                    for field_index,(key,_) in enumerate(fields):
                        pos=offset*len(fields)+field_index
                        if pos<len(values):row[key]=_value(values[pos])
                    rx=_number(row.get('rx_bytes'));tx=_number(row.get('tx_bytes'))
                    speed=_number(row.get('speed_mbps'))
                    interface={'index':number,'name':(row.get('name') or names[number])[:128],
                        'status':'UP' if row.get('oper_status')=='1' else 'DOWN' if row.get('oper_status')=='2' else 'UNKNOWN',
                        'capacity_bps':speed*1_000_000 if speed is not None else None,
                        'rx_bytes':rx,'tx_bytes':tx}
                    old=previous_rows.get(str(number),{})
                    uptime_ok=not previous or previous.get('uptime_seconds') is None or telemetry['uptime_seconds'] is None or telemetry['uptime_seconds']>=previous['uptime_seconds']
                    if elapsed and elapsed>=1 and rx is not None and tx is not None and uptime_ok and old.get('name',interface['name'])==interface['name']:
                        old_rx=_number(old.get('rx_bytes'));old_tx=_number(old.get('tx_bytes'))
                        if old_rx is not None and old_tx is not None and rx>=old_rx and tx>=old_tx:
                            interface['rx_bps']=round((rx-old_rx)*8/elapsed,2)
                            interface['tx_bps']=round((tx-old_tx)*8/elapsed,2)
                            interface['sample_seconds']=round(elapsed,2)
                    interfaces.append(interface)
            if interfaces:telemetry['interfaces']=interfaces
        return result(target,'SNMPv3' if config['version']=='v3' else 'SNMPv2c','UP',host=host,
            latency_ms=round((time.monotonic()-started)*1000,2),system_info=telemetry['system_info'],uptime_seconds=telemetry['uptime_seconds'],
            interfaces=interfaces,interface_count=reported,collected_interface_count=len(interfaces),scan_truncated=bool(reported and reported>len(interfaces) and requested.intersection({'interfaces','traffic','bandwidth'})),detected_oids=['SNMPv2-MIB::sysDescr.0','SNMPv2-MIB::sysName.0']+(['IF-MIB'] if interfaces else []))
    except Exception:
        return result(target,'SNMP',error='snmp_request_failed',host=host)
    finally:
        try:engine.close_dispatcher()
        except Exception:pass
