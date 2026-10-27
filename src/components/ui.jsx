import { displayPreferences } from '../data/displayPreferences'
import { Link } from 'react-router'
export function Icon({ name, className = '' }) { return <i className={`bi bi-${name} ${className}`} aria-hidden="true" /> }
export function Badge({ status = 'UNKNOWN', children }) {
  const tone = ['UP', 'connected'].includes(status) ? 'success' : ['DOWN', 'CRITICAL'].includes(status) ? 'danger' : ['WARNING', 'DEGRADED'].includes(status) ? 'warning' : status === 'ready' ? 'primary' : 'secondary'
  return <span className={`badge bg-${tone}-subtle text-${tone}-emphasis border border-${tone}-subtle`}>{children || status}</span>
}
export function Panel({ title, subtitle, action, children, className = '', footer, bodyClassName = '' }) {
  return <section className={`card mb-4 ${className}`}><div className="card-header d-flex flex-wrap justify-content-between align-items-center gap-2"><div><h2 className="h5 card-title mb-0">{title}</h2>{subtitle && <small className="text-muted fw-normal">{subtitle}</small>}</div>{action}</div><div className={`card-body ${bodyClassName}`}>{children}</div>{footer && <div className="card-footer small text-muted">{footer}</div>}</section>
}
export function EmptyState({ icon = 'database', title = 'Menunggu data monitoring', description = 'Hubungkan API untuk menampilkan data aktual dari collector.', compact = false, action = true }) {
  return <div className={`text-center text-muted ${compact ? 'py-4' : 'py-5'}`}><Icon name={icon} className="fs-2 d-inline-block mb-3" /><h3 className="h6 text-body-secondary">{title}</h3><p className="mb-3 small mx-auto" style={{ maxWidth: 440 }}>{description}</p>{action && <Link className="btn btn-sm btn-outline-primary" to="/integrations">Lihat integrasi <Icon name="arrow-right" className="ms-2" /></Link>}</div>
}
export function MetricCard({ label, value = '—', unit, icon, note = 'Belum ada data', tone, columnClass = 'col-sm-6 col-xl-3' }) {
  return <div className={columnClass}><section className="card stats-card h-100"><div className="card-body"><div className="d-flex align-items-center"><div className="flex-shrink-0"><div className="stats-icon bg-primary bg-opacity-10 text-primary"><Icon name={icon} /></div></div><div className="flex-grow-1 ms-3"><p className="h6 mb-0 text-muted">{label}</p><div className="h3 mb-0 tabular-nums">{value}{unit && <span className="fs-6 ms-1">{unit}</span>}</div><small className={tone === 'good' ? 'text-success-emphasis' : tone === 'warning' ? 'text-warning-emphasis' : 'text-muted'}>{note}</small></div></div></div></section></div>
}
export function CapabilityNotice({ children, title = 'Integrasi belum tersedia', icon = 'info-circle' }) {
  return <div className="alert alert-info d-flex align-items-start gap-3 mb-4"><Icon name={icon} className="mt-1" /><div><strong>{title}</strong><p className="mb-0 small mt-1">{children}</p></div></div>
}
export function Tabs({ items, value, onChange, label = 'Tampilan data' }) {
  return <div className="nav nav-tabs mb-4" role="group" aria-label={label}>{items.map((item) => <button type="button" key={item.value} className={`nav-link ${item.value === value ? 'active' : ''}`} aria-pressed={item.value === value} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>
}
export function formatTime(epoch, short = false) {
  if (typeof epoch !== 'number' || !Number.isFinite(epoch) || epoch < 0 || epoch > 4102444800) return 'Belum tersedia'
  const { timezone,date_format } = displayPreferences()
  return new Intl.DateTimeFormat(date_format, { timeZone: timezone, ...(short ? {} : { day: '2-digit', month: 'short' }), hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(epoch * 1000)) + (timezone === 'Asia/Jakarta' ? ' WIB' : ' '+timezone)
}
export function percentage(value) { return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—' }
export function CollectorTable({ rows = [], query = '', compact = false }) {
  const filtered = rows.filter((r) => `${r.id} ${r.method} ${r.status}`.toLowerCase().includes(query.toLowerCase()))
  if (!rows.length) return <EmptyState compact={compact} icon="router" title="Belum ada snapshot collector" description="Daftar dan status collector akan muncul dari API monitoring." />
  if (!filtered.length) return <EmptyState compact title="Tidak ada hasil" description="Coba kata kunci atau filter lain." action={false} icon="search" />
  return <div className="table-responsive"><table className="table table-hover align-middle mb-0 nms-table"><thead><tr><th>Collector / target</th><th>Status</th><th>Metode</th><th>Pemeriksaan terakhir</th></tr></thead><tbody>{filtered.map((row) => <tr key={row.id}><td className="nms-word-break"><div className="fw-medium">{row.id}</div><small className="text-muted">{row.stale ? 'Sampel kedaluwarsa / belum tersedia' : row.error || 'Snapshot monitoring'}</small></td><td><Badge status={row.status} /></td><td className="text-muted">{row.method}</td><td className="text-muted tabular-nums">{formatTime(row.sampled)}</td></tr>)}</tbody></table></div>
}
export function EventList({ events = [], unavailable = false }) {
  if (unavailable) return <EmptyState compact icon="clock-history" title="Riwayat belum dapat dibaca" description="Endpoint kejadian belum terhubung atau tidak dapat diakses." />
  if (!events.length) return <EmptyState compact icon="clock-history" title="Belum ada data kejadian" description="Kejadian akan muncul setelah riwayat berhasil dibaca dari API." />
  return <div className="activity-feed">{events.map((event) => <article className="activity-item" key={event.id}><div className="activity-icon"><Icon name={event.kind === 'recovery' ? 'arrow-counterclockwise' : 'bell'} /></div><div className="activity-content nms-word-break"><p className="mb-1">{event.title}</p><small className="text-muted">{event.device} · {event.kind} · {formatTime(event.time)}</small><div className="mt-1"><Badge status={event.severity} /></div></div></article>)}</div>
}
