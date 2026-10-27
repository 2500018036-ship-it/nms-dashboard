import { ApiError } from './apiClient.js'

const record = (v) => v && typeof v === 'object' && !Array.isArray(v)
const finite = (v) => typeof v === 'number' && Number.isFinite(v) ? v : null
// eslint-disable-next-line no-control-regex -- Sanitize text read from monitoring records.
const text = (v, fallback = '—') => typeof v === 'string' && v.trim() ? v.replace(/[\x00-\x1f\x7f]/g, '').slice(0, 500) : fallback
const severity = (v) => ['CRITICAL', 'WARNING', 'INFO', 'UNKNOWN'].includes(v) ? v : 'UNKNOWN'
const status = (v) => ['ACTIVE', 'RECOVERED', 'RETIRED', 'UNKNOWN'].includes(v) ? v : 'UNKNOWN'
const evidenceKeys = new Set(['status','method','error','value','threshold','hysteresis','state','health','running','disabled','restart_delta_15m','name','node','interface','source','previous','current','bits_per_second','baseline_bps','handshake_age_seconds','scope','certainty','host','direction','utilization_percent','capacity_bps','cpu_percent','memory_percent','latency_ms','http_status','rx_percent','tx_percent','sustained_seconds','duplex','rx_bps','tx_bps','threshold_seconds','reason'])
export const incidentIdValid = (v) => typeof v === 'string' && /^inc_(event_[1-9]\d{0,14}|state_[a-f0-9]{20})$/.test(v)
export function adaptEvidence(v) {
  return record(v) ? Object.fromEntries(Object.entries(v).filter(([k, value]) => evidenceKeys.has(k) && (value === null || typeof value === 'string' || typeof value === 'boolean' || finite(value) !== null)).map(([k, value]) => [k, typeof value === 'string' ? text(value) : value])) : {}
}
export function adaptIncident(v) {
  if (!record(v) || !incidentIdValid(v.id)) throw new ApiError('invalid_response')
  return { id: v.id, key: text(v.key), title: text(v.title), device: text(v.device), status: status(v.status), severity: severity(v.severity),
    firstSeen: finite(v.first_seen), updatedAt: finite(v.updated_at), lastObservedAt: finite(v.last_observed_at), resolvedAt: finite(v.resolved_at),
    partialHistory: v.partial_history === true, evidence: adaptEvidence(v.evidence),
    delivery: { status: text(v.delivery?.status, 'not_queued'), attempts: finite(v.delivery?.attempts), lastAttempt: finite(v.delivery?.last_attempt) },
    acknowledgment: record(v.acknowledgment) && typeof v.acknowledgment.actor === 'string' ? { actor:text(v.acknowledgment.actor), at:finite(v.acknowledgment.at), note:text(v.acknowledgment.note,'') } : null,
    acknowledgmentSupported: v.acknowledgment?.supported === true, resolutionSource: text(v.resolution_source, ''),
    timeline: Array.isArray(v.timeline) ? v.timeline.slice(0, 100).filter(record).map((e) => ({ id: text(e.id), time: finite(e.time), kind: text(e.kind), title: text(e.detail?.title), severity: severity(e.detail?.severity), delivery: text(e.delivery), evidence: adaptEvidence(e.evidence) })) : [],
    timelineTruncated: v.timeline_truncated === true,
  }
}
export function adaptJournal(payload, kind) {
  if (!record(payload) || !Array.isArray(payload.items) || payload.read_only !== true || !Number.isInteger(payload.total) || payload.total < 0 || !Number.isInteger(payload.page) || payload.page < 1 || !Number.isInteger(payload.page_size) || payload.page_size < 1 || payload.page_size > 100 || payload.items.length > payload.page_size) throw new ApiError('invalid_response')
  const items = kind === 'incidents' ? payload.items.map(adaptIncident) : payload.items.map((v) => {
    if (!record(v) || !/^(event|check)_[1-9]\d{0,14}$/.test(v.id)) throw new ApiError('invalid_response')
    return { id: v.id, time: finite(v.time), target: text(v.target), source: text(v.source), category: text(v.category), device: text(v.device), severity: severity(v.severity), message: text(v.message), recordType: text(v.record_type), kind: text(v.kind), evidence: adaptEvidence(v.evidence), incidentId: incidentIdValid(v.incident_id) ? v.incident_id : null }
  })
  return { items, total: payload.total, page: payload.page, pageSize: payload.page_size, generatedAt: finite(payload.generated_at),
    devices: Array.isArray(payload.devices) ? payload.devices.slice(0, 200).filter((v) => typeof v === 'string').map((v) => text(v)) : [],
    sources: Array.isArray(payload.sources) ? payload.sources.slice(0, 10).filter(record).map((s) => ({ id: text(s.id), label: text(s.label), category: text(s.category), available: s.available === true, reason: text(s.reason, '') })) : [],
    summary: Object.fromEntries(['ACTIVE','RECOVERED','RETIRED','UNKNOWN'].map((k) => [k, finite(payload.summary?.[k]) ?? 0])),
  }
}
export function journalParams(filters, kind, now) {
  const p = { page: filters.page, page_size: filters.pageSize, q: filters.q, severity: filters.severity, device: filters.device }
  if (kind === 'incidents') p.status = filters.status
  else { p.category = filters.category; p.source = filters.source }
  if (filters.period === 'custom') {
    const start = Date.parse(filters.start + '+07:00') / 1000; const end = Date.parse(filters.end + '+07:00') / 1000
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || end > now + 60 || kind === 'logs' && end - start > 31 * 86400) throw new ApiError('invalid_filter')
    p.from = start; p.to = end
  } else {
    p.to = Math.floor(now)
    if (filters.period !== 'all') { const seconds = { '24h': 86400, '7d': 7 * 86400, '30d': 30 * 86400 }[filters.period]; if (!seconds) throw new ApiError('invalid_filter'); p.from = Math.floor(now - seconds) }
  }
  return p
}
