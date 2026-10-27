import { ApiError } from './apiClient.js'
import { adaptCore, ageCore, emptyCore } from './coreAdapter.js'

export const finite = (v) => (typeof v === 'number' || (typeof v === 'string' && v.trim() !== '')) && Number.isFinite(Number(v)) ? Number(v) : null
const percentage = (v) => { const n = finite(v); return n !== null && n >= 0 && n <= 100 ? n : null }
// eslint-disable-next-line no-control-regex -- Remove control characters from untrusted collector text.
const text = (value, fallback = '—') => typeof value === 'string' && value.trim() ? value.replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 180) : fallback
const record = (v) => v && typeof v === 'object' && !Array.isArray(v)
const list = (v) => Array.isArray(v) ? v.slice(0, 500) : []
const statusOf = (v) => ['UP', 'DOWN', 'DEGRADED', 'UNKNOWN'].includes(v) ? v : 'UNKNOWN'
const epoch = (v) => { const n = finite(v); return n !== null && n >= 0 && n <= 4102444800 ? n : null }

export function adaptStatus(payload, now = Date.now() / 1000) {
  if (!record(payload) || !Array.isArray(payload.checks) || !Array.isArray(payload.alerts)) throw new ApiError('invalid_response')
  const interval = finite(payload.interval)
  const staleAfter = Math.max(120, Math.min(3600, (interval && interval > 0 ? interval : 30) * 3))
  const checks = list(payload.checks).filter(record).map((row, index) => {
    const sampled = epoch(row.sample_epoch)
    const freshness=finite(row.stale_after_seconds);const staleWindow=freshness>=120&&freshness<=10800?freshness:staleAfter
    const stale = sampled === null || now - sampled > staleWindow || sampled > now + 60
    const resource = row.data?.['/system/resource']?.[0] || {}
    const total = finite(resource['total-memory']); const free = finite(resource['free-memory'])
    return {
      id: text(row.target, `collector-${index}`), method: text(row.method), sampled,
      status: stale ? 'UNKNOWN' : statusOf(row.status), reportedStatus: statusOf(row.status), stale, staleAfter:staleWindow,
      cpu: percentage(row.cpu_percent ?? resource['cpu-load']),
      memory: percentage(row.memory_percent ?? (total > 0 && free !== null ? (1 - free / total) * 100 : null)),
      latency: finite(row.latency_ms), error: text(row.error, ''),
    }
  })
  const interfaces = []; const containers = []
  for (const row of list(payload.checks).filter(record)) {
    if (row.target === 'mikrotik_interfaces') {
      const source = checks.find((c) => c.id === row.target)
      for (const item of list(row.data?.['/interface']).filter(record)) {
        const running = item.running === true || item.running === 'true'
        const disabled = item.disabled === true || item.disabled === 'true'
        const known = [true, false, 'true', 'false'].includes(item.running)
        interfaces.push({ name: text(item.name), type: text(item.type), status: source?.stale || !known ? 'UNKNOWN' : disabled ? 'DISABLED' : running ? 'UP' : 'DOWN', rxBytes: finite(item['rx-byte']), txBytes: finite(item['tx-byte']) })
      }
    }
    if (row.target === 'docker') {
      const source = checks.find((c) => c.id === row.target)
      for (const item of list(row.containers).filter(record)) containers.push({ name: text(item.name), state: source?.stale ? 'Sampel lama' : text(item.state), health: source?.stale ? 'UNKNOWN' : text(item.health, 'Tidak tersedia'), restarts: finite(item.restart_count) })
    }
  }
  const alerts = list(payload.alerts).filter(record).filter((a) => a.active === true).map((a, i) => {
    const detail = record(a.pending) && Object.keys(a.pending).length ? a.pending : record(a.last_event) ? a.last_event : {}
    return { key: text(a.key, `alert-${i}`), title: text(detail.title, text(a.key)), severity: ['WARNING', 'CRITICAL', 'INFO'].includes(detail.severity) ? detail.severity : 'UNKNOWN', since: epoch(a.first_seen ?? detail.first_seen), device: text(detail.device, 'Collector') }
  })
  return { checks, interfaces, containers, alerts, interval, serverTime: epoch(payload.server_time), receivedAt: now, core: adaptCore(payload, checks) }
}
export function adaptEvents(payload) {
  if (!record(payload) || !Array.isArray(payload.events)) throw new ApiError('invalid_response')
  return list(payload.events).filter(record).map((e, i) => ({
    id: `${text(e.key, 'event')}-${e.time}-${i}`, key: text(e.key), time: epoch(e.time), kind: text(e.kind),
    title: text(e.detail?.title, text(e.key)), device: text(e.detail?.device, 'Collector'),
    severity: ['WARNING', 'CRITICAL', 'INFO'].includes(e.detail?.severity) ? e.detail.severity : 'UNKNOWN',
  }))
}
export function adaptDevices(payload) {
  if (!record(payload) || !Array.isArray(payload.devices) || payload.read_only !== true) throw new ApiError('invalid_response')
  return list(payload.devices).filter(record).map((d) => ({ id: text(d.id), name: text(d.name), host: text(d.host),
    status: statusOf(d.status), staleAfter:finite(d.stale_after_seconds), readState: text(d.read_state), sampled: epoch(d.sample_epoch),
    collectors: list(d.collectors).filter((x) => typeof x === 'string').map((x) => text(x)),
    methods: list(d.methods).filter((x) => typeof x === 'string').map((x) => text(x)), source: text(d.source) }))
}
export function adaptHistory(payload, target) {
  if (!record(payload) || payload.target !== target || !Array.isArray(payload.points)) throw new ApiError('invalid_response')
  return list(payload.points).filter(record).map((p) => ({ time: epoch(p.time), cpu: percentage(p.cpu_percent), memory: percentage(p.memory_percent), latency: finite(p.latency_ms) })).filter((p) => p.time !== null).sort((a, b) => a.time - b.time)
}
export function isSnapshotStale(snapshot, now = Date.now() / 1000) {
  return !snapshot || now - snapshot.receivedAt > Math.max(120, (snapshot.interval || 30) * 3)
}
export const emptySnapshot = () => ({ checks: [], interfaces: [], containers: [], alerts: [], interval: null, serverTime: null, receivedAt: 0, core: emptyCore() })
export function ageSnapshot(snapshot, now = Date.now() / 1000) {
  const staleAfter = Math.max(120, Math.min(3600, (snapshot.interval || 30) * 3))
  const checks = snapshot.checks.map((c) => {
    const stale = c.stale || c.sampled === null || now - c.sampled > (c.staleAfter || staleAfter)
    return { ...c, stale, status: stale ? 'UNKNOWN' : c.reportedStatus }
  })
  return { ...snapshot, checks,
    core: ageCore(snapshot.core, checks),
    interfaces: checks.find((c) => c.id === 'mikrotik_interfaces')?.stale ? snapshot.interfaces.map((i) => ({ ...i, status: 'UNKNOWN' })) : snapshot.interfaces,
    containers: checks.find((c) => c.id === 'docker')?.stale ? snapshot.containers.map((c) => ({ ...c, state: 'Sampel lama', health: 'UNKNOWN' })) : snapshot.containers,
  }
}
