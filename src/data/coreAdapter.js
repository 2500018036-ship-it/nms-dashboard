const number = (v) => (typeof v === 'number' || typeof v === 'string' && v.trim()) && Number.isFinite(Number(v)) ? Number(v) : null
const nonnegative = (v) => { const n = number(v); return n !== null && n >= 0 ? n : null }
const percent = (v) => { const n = nonnegative(v); return n !== null && n <= 100 ? n : null }
const ratio = (v, max) => { const a = nonnegative(v); const b = nonnegative(max); return a !== null && b > 0 ? percent(a / b * 100) : null }
// eslint-disable-next-line no-control-regex -- Remove control characters from untrusted collector text.
const text = (v, fallback = '—') => typeof v === 'string' && v.trim() ? v.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 180) : fallback
const rows = (v) => Array.isArray(v) ? v.filter((r) => r && typeof r === 'object').slice(0, 500) : []
const up = (v) => v === true || v === 'true'
const powerStatus = (v) => ['running', 'online', 'active'].includes(v) ? 'UP' : ['stopped', 'offline', 'exited'].includes(v) ? 'DOWN' : 'UNKNOWN'
export const emptyCore = () => ({ devices: [], interfaces: [], traffic: [], hosts: [], guests: [], storage: [], virtualization: null, containers: [], services: [], topology: { nodes: [], links: [] } })

export function adaptCore(payload, checks) {
  const out = emptyCore(); const devices = new Map(); const nodes = new Map()
  for (const row of rows(payload.checks)) {
    const source = checks.find((c) => c.id === row.target)
    if (!source) continue
    const good = !source.stale && ['UP', 'DEGRADED'].includes(source.status)
    const sourceId = source.id; const sampled = source.sampled
    const host = typeof row.host === 'string' && !/[\s/@?#\\]/.test(row.host) ? text(row.host, '') : ''
    if (host) {
      const old = devices.get(host) || { id: host, name: host, host, statuses: [], collectors: [], sampled }
      old.statuses.push(source.status); old.collectors.push(sourceId); devices.set(host, old)
    }
    const base = { sourceId, freshnessId: sourceId, sampled, stale: source.stale, status: source.status }
    const measurement = !source.stale && source.status !== 'UNKNOWN'
    if (/DNS|HTTP|TCP|ICMP/i.test(source.method)) out.services.push({ ...base, id: sourceId, name: sourceId, method: source.method, host, port: nonnegative(row.port), latency: measurement ? nonnegative(row.latency_ms) : null, packetLoss: measurement ? percent(row.packet_loss_percent) : null, httpCode: nonnegative(row.http_status), query: text(row.query, ''), answers: Array.isArray(row.answers) ? row.answers.filter((a) => typeof a === 'string').slice(0, 8).map((a) => text(a)) : [] })
    if (row.target === 'network_traffic') for (const i of rows(row.interfaces)) out.traffic.push({ ...base, id: `mikrotik_interfaces:${text(i.name)}`, sourceId: 'mikrotik_interfaces', name: text(i.name), rx: good ? nonnegative(i.rx_bps) : null, tx: good ? nonnegative(i.tx_bps) : null, capacity: nonnegative(i.capacity_bps), utilization: good ? percent(i.utilization_percent) : null, interval: nonnegative(i.sample_seconds), duplex: text(i.duplex) })
    const legacyInterfaces = rows(row.data?.['/interface'])
    const genericInterfaces = row.target === 'network_traffic' ? [] : rows(row.interfaces)
    for (const i of [...legacyInterfaces, ...genericInterfaces]) {
      const disabled = up(i.disabled); const runningKnown = [true, false, 'true', 'false'].includes(i.running)
      const observed = ['UP', 'DOWN', 'DISABLED'].includes(i.status) ? i.status : disabled ? 'DISABLED' : runningKnown ? up(i.running) ? 'UP' : 'DOWN' : 'UNKNOWN'
      const id = `${sourceId}:${text(i.name)}`
      out.interfaces.push({ ...base, id, name: text(i.name), type: text(i.type), status: good ? observed : 'UNKNOWN', rxBytes: nonnegative(i['rx-byte'] ?? i.rx_bytes), txBytes: nonnegative(i['tx-byte'] ?? i.tx_bytes), errors: nonnegative(i['rx-error'] ?? i.rx_errors), drops: nonnegative(i['rx-drop'] ?? i.rx_drops), mtu: nonnegative(i.mtu) })
      if (genericInterfaces.includes(i)) out.traffic.push({ ...base, id, name: text(i.name), rx: good ? nonnegative(i.rx_bps) : null, tx: good ? nonnegative(i.tx_bps) : null, capacity: nonnegative(i.capacity_bps), utilization: good ? percent(i.utilization_percent) : null, interval: nonnegative(i.sample_seconds), duplex: text(i.duplex) })
    }
    if (row.target !== 'docker' && (nonnegative(row.cpu_percent) !== null || rows(row.disks).length > 0 || row.target === 'debian')) out.hosts.push({ ...base, id: sourceId, name: sourceId === 'debian' ? 'Debian Docker server' : sourceId, host, cpu: good ? source.cpu : null, memory: good ? source.memory : null, uptime: nonnegative(row.uptime_seconds), disks: rows(row.disks).map((d) => ({ name: text(d.path), percent: good ? percent(d.used_percent) : null, total: nonnegative(d.total), used: nonnegative(d.used) })) })
    if (row.target === 'proxmox_resources') {
      out.virtualization = { ...base, version: text(row.version?.version), readonlyVerified: row.readonly_verified === true, tasks: rows(row.tasks) }
      for (const disk of rows(row.storage)) out.storage.push({ ...base, id: text(disk.id), name: text(disk.storage), node: text(disk.node), state: text(disk.status), status: good ? ['available','active'].includes(disk.status) ? 'UP' : 'UNKNOWN' : 'UNKNOWN', percent: good ? ratio(disk.disk,disk.maxdisk) : null, used: good ? nonnegative(disk.disk) : null, total: good ? nonnegative(disk.maxdisk) : null })
    }
    for (const node of rows(row.nodes)) out.hosts.push({ ...base, id: text(node.id), name: text(node.node), host, cpu: good && number(node.cpu) !== null ? percent(number(node.cpu) * 100) : null, memory: good ? ratio(node.mem, node.maxmem) : null, status: good ? powerStatus(node.status) : 'UNKNOWN', uptime: nonnegative(node.uptime), disks: [{ name: 'node storage', percent: good ? ratio(node.disk, node.maxdisk) : null }] })
    for (const guest of rows(row.guests)) out.guests.push({ ...base, id: text(guest.id, String(guest.vmid)), vmid: nonnegative(guest.vmid), name: text(guest.name), node: text(guest.node), type: text(guest.type), cores: nonnegative(guest.maxcpu), memoryBytes: good ? nonnegative(guest.mem) : null, memoryTotal: nonnegative(guest.maxmem), netIn: good ? nonnegative(guest.netin) : null, netOut: good ? nonnegative(guest.netout) : null, state: text(guest.status), status: good ? powerStatus(guest.status) : 'UNKNOWN', cpu: good && number(guest.cpu) !== null ? percent(number(guest.cpu) * 100) : null, memory: good ? ratio(guest.mem, guest.maxmem) : null, disk: good && guest.type==='lxc' ? ratio(guest.disk, guest.maxdisk) : null, uptime: good ? nonnegative(guest.uptime) : null })
    for (const c of rows(row.containers)) out.containers.push({ ...base, id: `${sourceId}:${text(c.name)}`, name: text(c.name), state: text(c.state), health: text(c.health), status: good ? c.health === 'unhealthy' ? 'DEGRADED' : powerStatus(c.state) : 'UNKNOWN', image: text(c.image), restarts: nonnegative(c.restart_count), cpu: good ? nonnegative(c.cpu_percent) : null, memory: good ? ratio(c.memory_bytes, c.memory_limit_bytes) : null, memoryBytes: good ? nonnegative(c.memory_bytes) : null })
    for (const neighbor of rows(row.data?.['/ip/neighbor'])) {
      const id = `neighbor:${text(neighbor.address, text(neighbor.identity))}`
      nodes.set(sourceId, { id: sourceId, name: sourceId, type: 'source', status: source.status })
      nodes.set(id, { id, name: text(neighbor.identity, text(neighbor.address)), type: 'neighbor', status: 'UNKNOWN' })
      out.topology.links.push({ id: `${sourceId}-${id}-${text(neighbor.interface)}`, source: sourceId, target: id, label: text(neighbor.interface), evidence: 'Neighbor advertisement', sampled, status: 'UNKNOWN' })
    }
  }
  out.devices = [...devices.values()].map(({ statuses, ...d }) => ({ ...d, status: statuses.includes('DOWN') ? 'DOWN' : statuses.includes('DEGRADED') ? 'DEGRADED' : statuses.every((s) => s === 'UP') ? 'UP' : 'UNKNOWN' }))
  out.topology.nodes = [...nodes.values()]
  return out
}

export function appendTrafficHistory(history, traffic) {
  const next = { ...history }
  for (const row of traffic) {
    if (row.stale || !row.sampled) continue
    const points = next[row.id] || []
    if (points.length && points.at(-1).time >= row.sampled) continue
    next[row.id] = [...points, { time: row.sampled, rx: row.rx, tx: row.tx }].slice(-120)
  }
  return Object.fromEntries(Object.entries(next).slice(-200))
}
export function ageCore(core, checks) {
  if (!core) return emptyCore()
  const stale = new Set(checks.filter((c) => c.stale).map((c) => c.id))
  const mark = (r) => stale.has(r.freshnessId || r.sourceId) ? { ...r, stale: true, status: 'UNKNOWN', rx: null, tx: null, utilization: null, cpu: null, memory: null, memoryBytes: null, netIn: null, netOut: null, uptime: null, latency: null, packetLoss: null, disk: null, disks: r.disks?.map((d) => ({ ...d, percent: null })) } : r
  return { ...core, interfaces: core.interfaces.map(mark), traffic: core.traffic.map(mark), hosts: core.hosts.map(mark), guests: core.guests.map(mark), containers: core.containers.map(mark), services: core.services.map(mark), devices: core.devices.map((d) => d.collectors.some((id) => stale.has(id)) ? { ...d, status: 'UNKNOWN' } : d),
    storage: (core.storage || []).map((r) => stale.has(r.sourceId) ? { ...r, status: 'UNKNOWN', stale: true, percent: null, used: null } : r), virtualization: core.virtualization ? mark(core.virtualization) : null,
    topology: { nodes: core.topology.nodes.map((n) => stale.has(n.id) ? { ...n, status: 'UNKNOWN' } : n), links: core.topology.links.map((l) => stale.has(l.source) ? { ...l, stale: true } : l) },
  }
}
