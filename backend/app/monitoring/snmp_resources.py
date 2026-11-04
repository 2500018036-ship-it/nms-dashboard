"""Bounded standard MIB reads; absent/denied OIDs never become invented metrics."""
import asyncio
from app.monitoring.snmp import _value, _number


async def walk(engine, auth, address, base, limit=64):
    from pysnmp.hlapi.v3arch.asyncio import walk_cmd, ContextData, ObjectType, ObjectIdentity
    found={}; prefix=base+'.'
    async for error,status,_,values in walk_cmd(engine,auth,address,ContextData(),ObjectType(ObjectIdentity(base)),
            lookupMib=False,lexicographicMode=False,maxRows=limit,maxCalls=limit+1):
        if error or status:break
        for oid,value in values:
            identity=oid.prettyPrint(); measurement=_value((oid,value))
            if identity.startswith(prefix) and measurement is not None:found[identity[len(prefix):]]=measurement
        if len(found)>=limit:break
    return found


async def table(engine,auth,address,base,fields,limit=64):
    rows={}
    for name,column in fields.items():
        for identity,value in (await walk(engine,auth,address,base+'.'+str(column),limit)).items():
            rows.setdefault(identity,{'index':identity})[name]=value
    return list(rows.values())


def storage_metrics(rows):
    disks=[]; memory={}
    for row in rows:
        units=_number(row.get('units'));size=_number(row.get('size'));used=_number(row.get('used'))
        if not units or not size or used is None or used>size:continue
        total=size*units; amount=used*units
        if row.get('type')=='1.3.6.1.2.1.25.2.1.2':
            memory={'memory_total':total,'memory_available':total-amount,'memory_percent':round(amount*100/total,2)}
        elif row.get('type') in {'1.3.6.1.2.1.25.2.1.4','1.3.6.1.2.1.25.2.1.5','1.3.6.1.2.1.25.2.1.10'}:
            disks.append({'path':str(row.get('name',row['index']))[:128],'total':total,'used':amount,'free':total-amount,'used_percent':round(amount*100/total,2)})
    return {**memory,**({'disks':disks} if disks else {})}


async def collect(engine,auth,address,categories):
    wanted=set(categories); out={}; warnings=[]
    async def group(label,work):
        try:
            async with asyncio.timeout(4):return await work()
        except Exception:
            warnings.append(label+'_not_available');return None
    if 'cpu' in wanted:
        async def cpu():
            values=await walk(engine,auth,address,'1.3.6.1.2.1.25.3.3.1.2',64)
            numbers=[_number(v) for v in values.values()]; numbers=[v for v in numbers if v is not None and v<=100]
            return {'cpu_percent':round(sum(numbers)/len(numbers),2)} if numbers else {}
        out.update(await group('cpu',cpu) or {})
    if wanted.intersection({'memory','storage'}):
        async def storage():return storage_metrics(await table(engine,auth,address,'1.3.6.1.2.1.25.2.3.1',{'type':2,'name':3,'units':4,'size':5,'used':6},32))
        out.update(await group('storage',storage) or {})
    if 'vlan' in wanted:
        async def vlans():
            values=await walk(engine,auth,address,'1.3.6.1.2.1.17.7.1.4.3.1.1',128)
            return [{'name':name[:128],'vlan-id':_number(identity)} for identity,name in values.items() if _number(identity) is not None]
        values=await group('vlan',vlans)
        if values:out['vlans']=values
    if 'routing' in wanted:
        async def routes():
            values=await table(engine,auth,address,'1.3.6.1.2.1.4.21.1',{'destination':1,'gateway':7,'type':8,'mask':11},64)
            return [{'dst-address':r['destination']+'/'+r['mask'],'gateway':r.get('gateway'),'active':r['type']!='2'} for r in values if all(k in r for k in ('destination','mask','type'))]
        values=await group('routing',routes)
        if values:out['routes']=values
    if wanted.intersection({'temperature','sensors'}):
        async def sensors():
            values=await table(engine,auth,address,'1.3.6.1.2.1.99.1.1.1',{'type':1,'scale':2,'precision':3,'raw':4,'status':5},32)
            result=[]
            for row in values:
                try:
                    scale=int(row['scale']);precision=int(row['precision']);raw=int(row['raw'])
                    if row.get('status')!='1' or not 1<=scale<=17 or not -12<=precision<=12:continue
                    value=raw*(10.0**((scale-9)*3-precision))
                    result.append({'name':'Sensor '+row['index'],'value':round(value,6),'unit':'°C' if row['type']=='8' else 'ENTITY-SENSOR type '+row['type']})
                except (KeyError,ValueError,OverflowError):continue
            return result
        values=await group('sensors',sensors)
        if values:
            out['sensors']=values
            temperatures=[v['value'] for v in values if v['unit']=='°C']
            if temperatures:out['temperature']=temperatures[0]
    if warnings:out['collection_notes']=warnings
    return out
