import { Badge, EmptyState, Icon, percentage, formatTime } from './ui'
import { formatBps, formatUptime, formatBytes } from '../data/format'

export function SearchField({ value, onChange, label = 'Cari', placeholder = 'Cari…' }) {
  return <div className="input-group w-auto"><span className="input-group-text"><Icon name="search" /></span><input className="form-control" type="search" value={value} onChange={(e) => onChange(e.target.value)} aria-label={label} placeholder={placeholder} /></div>
}
export function ResourceBar({ value, label }) {
  return <div className="nms-resource"><div className="d-flex justify-content-between gap-2 small mb-1"><span>{label}</span><span className="tabular-nums">{percentage(value)}</span></div><div className="progress" role="progressbar" aria-label={label} aria-valuenow={value ?? undefined} aria-valuemin={0} aria-valuemax={100} aria-valuetext={value === null ? 'Belum ada data' : percentage(value)}><div className={`progress-bar ${value >= 95 ? 'bg-danger' : value >= 85 ? 'bg-warning' : ''}`} style={{ width: `${value ?? 0}%` }} /></div></div>
}
export function InterfaceTable({ interfaces, traffic }) {
  if (!interfaces.length) return <EmptyState icon="ethernet" title="Data interface belum tersedia" description="Status, kapasitas, dan statistik mengikuti kemampuan collector perangkat." />
  return <div className="table-responsive"><table className="table table-hover align-middle nms-table mb-0"><thead><tr><th>Interface / sumber</th><th>Status</th><th>RX</th><th>TX</th><th>Utilisasi</th><th>Kapasitas</th><th>Error RX / drop RX</th></tr></thead><tbody>{interfaces.map((i) => { const t = traffic.find((r) => r.id === i.id); return <tr key={i.id}><td><strong>{i.name}</strong><div className="text-muted small">{i.sourceId} · {i.type}</div></td><td><Badge status={i.status} /></td><td>{formatBps(t?.rx)}</td><td>{formatBps(t?.tx)}</td><td>{percentage(t?.utilization)}</td><td>{formatBps(t?.capacity)}</td><td>{i.stale ? '—' : `${i.errors ?? '—'} / ${i.drops ?? '—'}`}</td></tr> })}</tbody></table></div>
}
export function HostTable({ rows, devices = [] }) {
  if (!rows.length) return <EmptyState icon="hdd-stack" title="Resource host belum tersedia" description="CPU, RAM, disk dan uptime memerlukan collector yang sesuai." />
  return <div className="table-responsive"><table className="table table-hover align-middle nms-table mb-0"><thead><tr><th>Host / node</th><th>Status</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Uptime</th></tr></thead><tbody>{rows.map((r) => {
    const observed = devices.find((d) => d.collectors?.includes(r.sourceId))
    const address = r.host || observed?.host
    const sourceLabel = r.sourceId === 'debian' ? 'Debian server · Docker & NMS collector' : r.sourceId === 'proxmox_resources' ? 'Node Proxmox VE' : r.sourceId
    return <tr key={r.id}><td><strong>{r.name}</strong><small className="d-block text-muted">{sourceLabel}{address ? ` · ${address}` : ''}</small></td><td><Badge status={r.status} /></td><td><ResourceBar label="CPU" value={r.cpu} /></td><td><ResourceBar label="RAM" value={r.memory} /></td><td>{r.disks.length ? r.disks.map((d) => <div key={d.name} className="mb-2"><ResourceBar label={d.name} value={d.percent} /></div>) : '—'}</td><td>{r.stale ? '—' : formatUptime(r.uptime)}</td></tr>
  })}</tbody></table></div>
}
export function GuestTable({ rows }) {
  if (!rows.length) return <EmptyState icon="pc-display" title="Data VM/LXC belum tersedia" description="Memerlukan API hypervisor read-only yang telah disiapkan di backend." />
  return <div className="table-responsive"><table className="table table-hover align-middle nms-table mb-0"><thead><tr><th>ID / nama</th><th>Node / tipe</th><th>Status</th><th>CPU</th><th>RAM</th><th>Disk</th><th>Uptime</th></tr></thead><tbody>{rows.map((g) => <tr key={g.id}><td><strong>{g.name}</strong><div className="text-muted small">{g.vmid ?? g.id}</div></td><td>{g.node}<small className="d-block text-muted">{g.type}</small></td><td><Badge status={g.status} /> <span className="small text-muted">{g.stale ? '' : g.state}</span></td><td>{percentage(g.cpu)}</td><td>{percentage(g.memory)}</td><td>{percentage(g.disk)}</td><td>{formatUptime(g.uptime)}</td></tr>)}</tbody></table></div>
}
export function ContainerTable({ rows }) {
  if (!rows.length) return <EmptyState icon="box-seam" title="Snapshot container belum tersedia" description="Browser tidak mengakses Docker socket; data berasal dari collector backend." />
  return <div className="table-responsive"><table className="table table-hover align-middle nms-table mb-0"><thead><tr><th>Container / image</th><th>State</th><th>Health</th><th>CPU</th><th>Memori</th><th>Restart</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td><strong>{r.name}</strong><small className="d-block text-muted nms-word-break">{r.image}</small></td><td><Badge status={r.status} /> {r.stale ? 'Sampel lama' : r.state}</td><td>{r.stale ? 'UNKNOWN' : r.health}</td><td>{r.cpu === null ? '—' : `${r.cpu.toFixed(1)}%`}</td><td>{formatBytes(r.memoryBytes)}<small className="d-block text-muted">{percentage(r.memory)} dari limit</small></td><td>{r.restarts ?? '—'}</td></tr>)}</tbody></table></div>
}
export function ServiceTable({ rows }) {
  if (!rows.length) return <EmptyState icon="globe" title="Hasil pemeriksaan layanan belum tersedia" description="Keterjangkauan TCP tidak otomatis membuktikan aplikasi sehat. Packet loss hanya ditampilkan jika disediakan collector." />
  return <div className="table-responsive"><table className="table table-hover align-middle nms-table mb-0"><thead><tr><th>Target / metode</th><th>Status</th><th>Latensi</th><th>Packet loss</th><th>Bukti tambahan</th><th>Waktu</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td><strong>{r.name}</strong><small className="d-block text-muted">{r.method}{r.host ? ` · ${r.host}` : ''}</small></td><td><Badge status={r.status} /></td><td>{r.latency === null ? '—' : `${r.latency.toFixed(1)} ms`}</td><td>{percentage(r.packetLoss)}</td><td>{r.httpCode ? `HTTP ${r.httpCode}` : r.query ? `${r.query}: ${r.answers.join(', ') || '—'}` : '—'}</td><td className="small">{formatTime(r.sampled)}</td></tr>)}</tbody></table></div>
}
