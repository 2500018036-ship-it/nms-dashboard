export function ageDeviceSummary(state,now) {
  if(!state?.collectors)return state
  const collectors=state.collectors.map((source)=>({...source,stale:source.stale||now-source.sample_epoch>(source.stale_after_seconds||120)}))
  const active=new Set(collectors.filter((s)=>!s.stale&&!s.error&&['UP','DEGRADED'].includes(s.status)).map((s)=>s.target))
  const telemetry={}
  for(const [key,value] of Object.entries(state.telemetry||{})) {
    if(Array.isArray(value))telemetry[key]=value.filter((row)=>!row.collector||active.has(row.collector))
    else if(!state.metric_sources?.[key]||active.has(state.metric_sources[key].collector))telemetry[key]=value
  }
  const health=state.health?{...state.health,stale:state.health.stale||now-state.health.sample_epoch>(state.health.stale_after_seconds||120)}:null
  if(health?.stale)health.status='UNKNOWN'
  const integration_state=health?.stale?(active.size?'PARTIAL':'STALE'):state.integration_state
  return {...state,collectors,telemetry,health,integration_state}
}
