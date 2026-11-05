export function networkDeviceView(core, inventory, observed, selectedId, targets = {}) {
  const devices = inventory.filter(d => d.enabled && d.monitor_method !== 'none').map(d => ({
    id:d.id, name:d.name, host:d.host,
    sources:[targets[d.id] || `inventory_${d.id}`, ...(observed.find(o=>o.host===d.host)?.collectors || []).filter(id=>!id.startsWith('inventory_'))],
  }))
  const device=devices.find(d=>d.id===selectedId)||devices[0]
  const belongs=row=>!!device&&device.sources.includes(row.sourceId || row.id)
  const label=row=>({...row,sourceName:device?.name||'Perangkat belum dipilih'})
  return {devices,device,interfaces:core.interfaces.filter(belongs).map(label),traffic:core.traffic.filter(belongs).map(label),services:core.services.filter(belongs),sources:device?.sources||[]}
}
