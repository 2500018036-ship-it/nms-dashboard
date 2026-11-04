"""Physical server counts and explicitly linked hosted components."""
def hierarchy(store,status):
    inventory=store.list('inventory')
    physical=[d for d in inventory if d.get('component_kind')=='physical' and d['type'] in {'server','hypervisor','container-host'}]
    result=[]
    for server in physical:
        state=status(server)
        children=[{'device':d,'monitoring':status(d)} for d in inventory if d.get('parent_id')==server['id']]
        # Live guests/containers are observed components, not additional physical machines.
        observed=[]
        for kind,key in (('vm','guests'),('container','containers'),('storage','storage')):
            for component in state.get('telemetry',{}).get(key,[]):observed.append({'kind':kind,'value':component,'source':'owned-collector'})
        result.append({'device':server,'monitoring':state,'children':children,'observed_components':observed})
    assigned={d['id'] for s in result for d in [s['device'],*(c['device'] for c in s['children'])]}
    return {'physical_count':len(physical),'servers':result,'unassigned':[d for d in inventory if d['id'] not in assigned and d['type'] in {'server','hypervisor','container-host','service','dns'}],
        'scope':'Physical count uses inventory parent links only. An unknown host/VM relation is never guessed.'}
