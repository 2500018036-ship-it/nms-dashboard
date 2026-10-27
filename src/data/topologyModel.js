export function portObservation(edge,nodes,interfaces,inventoryTargets={}) {
  for (const [id,port] of [[edge.source,edge.source_port],[edge.target,edge.target_port]]) {
    const node=nodes.find((n)=>n.id===id);const collector=inventoryTargets[node?.device_id]||node?.collector
    if(!port||!collector?.startsWith('mikrotik'))continue
    const found=interfaces.find((i)=>i.sourceId==='mikrotik_interfaces'&&i.name===port)
    if(found&&!found.stale&&['UP','DOWN','DISABLED'].includes(found.status))return {status:found.status,scope:`Status port ${node.name} / ${port}; bukan verifikasi relasi fisik atau konektivitas end-to-end`}
  }
  return {status:'UNKNOWN',scope:'Relasi manual; port belum terverifikasi collector'}
}

const serviceKinds = new Set(['service', 'application', 'proxy', 'vm', 'lxc', 'docker'])
const deviceCollectors = new Set(['mikrotik_system', 'mikrotik_interfaces', 'mikrotik_network', 'mikrotik_vlan', 'mikrotik_routes', 'proxmox_resources', 'cisco_sf200', 'debian', 'docker', 'wireguard'])

export function isDeviceTopologyKind(kind) {
  return typeof kind === 'string' && !serviceKinds.has(kind.toLowerCase())
}

export function deviceTopologyKind(type) {
  if (type === 'hypervisor') return 'proxmox'
  if (type === 'container-host') return 'server'
  if (type === 'vpn') return 'other'
  return isDeviceTopologyKind(type) ? type : 'other'
}

function isFreshUp(status, sampled, stale, staleAfter, now) {
  const ageLimit = Math.max(120, Number.isFinite(staleAfter) ? staleAfter : 120)
  return status === 'UP' && stale !== true && Number.isFinite(sampled) && sampled <= now + 60 && now - sampled <= ageLimit
}

function preferredCollector(collectors = []) {
  const priority = ['mikrotik_interfaces', 'mikrotik_system', 'proxmox_resources', 'cisco_sf200', 'debian', 'docker', 'wireguard', 'mikrotik_network', 'mikrotik_vlan', 'mikrotik_routes']
  return priority.find((id) => collectors.includes(id)) || ''
}

export function connectedTopologyDevices({ inventory = [], inventoryStates = [], observedDevices = [], now = Date.now() / 1000 }) {
  const connectedByHost = new Map()
  for (const device of observedDevices) {
    const collector = preferredCollector(device.collectors)
    if (!collector || !deviceCollectors.has(collector) || !isFreshUp(device.status, device.sampled, device.stale, device.staleAfter, now)) continue
    connectedByHost.set(device.host, {
      id: device.id,
      name: device.name,
      host: device.host,
      kind: collector.startsWith('mikrotik_') ? 'router' : collector === 'proxmox_resources' ? 'proxmox' : collector === 'cisco_sf200' ? 'switch' : 'server',
      collector,
      device_id: device.id,
      status: 'UP',
      sampled: device.sampled,
      source: 'collector',
    })
  }

  const states = new Map(inventoryStates.map((item) => [item.id, item]))
  for (const item of inventory) {
    if (!item.enabled || item.type === 'service' || !isDeviceTopologyKind(item.type)) continue
    const state = states.get(item.id)
    const health = state?.health
    const interval = Number(item.interval)
    const ageLimit = Math.max(120, Number.isFinite(interval) ? interval * 3 : 120)
    if (state?.integration_state !== 'CONNECTED' || !isFreshUp(health?.status, health?.sample_epoch, health?.stale, ageLimit, now)) continue
    const observed = connectedByHost.get(item.host)
    connectedByHost.set(item.host, {
      id: item.id,
      name: item.name,
      host: item.host,
      kind: deviceTopologyKind(item.type),
      collector: state.monitor_target || observed?.collector || '',
      device_id: item.id,
      status: 'UP',
      sampled: health.sample_epoch,
      source: 'inventory',
      group: item.group || '',
    })
  }
  return [...connectedByHost.values()].sort((a, b) => a.name.localeCompare(b.name))
}

export function knownTopologyDeviceIds(inventory = [], observedDevices = []) {
  const ids = new Set(inventory.filter((item) => item.type !== 'service' && isDeviceTopologyKind(item.type)).map((item) => item.id))
  for (const device of observedDevices) {
    if (preferredCollector(device.collectors) && deviceCollectors.has(preferredCollector(device.collectors))) ids.add(device.id)
  }
  return ids
}

export function topologyDeviceNodes(graph, knownDeviceIds, knownNodeResources = new Set()) {
  const nodes = (graph?.nodes || []).filter((node) => isDeviceTopologyKind(node.kind) && (
    knownDeviceIds.has(node.device_id) || (node.resource_id && node.resource_id.startsWith('node/') && knownNodeResources.has(node.resource_id))
  ))
  const ids = new Set(nodes.map((node) => node.id))
  const links = (graph?.links || []).filter((link) => ids.has(link.source) && ids.has(link.target))
  return { nodes, links, hiddenCount: (graph?.nodes || []).length - nodes.length }
}

export function linkedLegacyServices(node, graph) {
  const byId = new Map((graph?.nodes || []).map((item) => [item.id, item]))
  return (graph?.links || []).flatMap((link) => {
    const otherId = link.source === node.id ? link.target : link.target === node.id ? link.source : ''
    if (!otherId) return []
    const target = byId.get(otherId)
    if (!target || isDeviceTopologyKind(target.kind)) return []
    return [{ name: target.name, kind: target.kind, status: 'UNKNOWN', evidence: 'Relasi topologi manual' }]
  })
}

export function topologyHostSummary(hosts = []) {
  const debian = hosts.filter((host) => host.sourceId === 'debian').length
  const proxmox = hosts.filter((host) => host.sourceId === 'proxmox_resources').length
  const other = hosts.length - debian - proxmox
  return [debian && `${debian} server Debian/Docker`, proxmox && `${proxmox} node Proxmox`, other && `${other} host lain`].filter(Boolean).join(' · ') || 'Belum ada host yang menyediakan metrik'
}
