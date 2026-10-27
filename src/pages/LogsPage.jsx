import { useState } from 'react'
import { Link } from 'react-router'
import { Badge, CapabilityNotice, MetricCard, Panel, formatTime } from '../components/ui'
import { Modal } from '../components/Modal'
import { Evidence, JournalControls, JournalFeedback, JournalPagination } from '../components/JournalControls'
import { useJournal } from '../data/useJournal'

export function LogsPage() {
  const journal = useJournal('logs')
  const [selected, setSelected] = useState(null)
  const rows = journal.data?.items || []
  const unsupported = !['all', 'monitoring'].includes(journal.filters.category)
  return <>
    <div className="row g-3 mb-4"><MetricCard label="Log sesuai filter" value={journal.data?.total ?? '—'} icon="journal-text" note="Total record backend, bukan jumlah baris halaman" /><MetricCard label="Sumber tersedia" value={journal.data ? journal.data.sources.filter((s) => s.available).length : '—'} icon="database" note="Event dan hasil pemeriksaan monitoring" /><MetricCard label="Pembaruan daftar" value={journal.paused ? 'Dijeda' : '60 detik'} icon="clock-history" note="Tidak memulai probe perangkat" /><MetricCard label="Kategori aktif" value="Monitoring" icon="activity" note="Event dan hasil collector, tanpa log buatan" /></div>
    <CapabilityNotice title="Sumber data aktual">Event monitoring dan hasil pemeriksaan collector tersimpan dibaca dari SQLite backend. Hasil pemeriksaan diberi label tersendiri; bukan log mentah aplikasi. Log aplikasi NMS tersedia di tab Aplikasi NMS; audit administratif tersedia di tab Audit. Remote syslog dan log mentah aplikasi lain belum dikumpulkan.</CapabilityNotice>
    <Panel title="Logs & Log Monitoring" subtitle="Pencarian, waktu WIB, perangkat, severity dan pagination dijalankan oleh backend">
      <JournalControls journal={journal} kind="logs" />
      {unsupported && <div className="alert alert-info" role="status">Jurnal ini hanya memuat hasil dan event monitoring. Gunakan tab Aplikasi NMS atau Audit administratif untuk sumber tersebut; remote syslog belum dikumpulkan.</div>}
      <JournalFeedback journal={journal} emptyMessage="Tidak ada record pada filter dan rentang waktu ini." />
      {!!rows.length && <div className="table-responsive"><table className="table table-hover align-middle nms-table"><thead><tr><th>Waktu WIB</th><th>Kategori / sumber</th><th>Perangkat / target</th><th>Severity</th><th>Pesan</th><th>Detail</th></tr></thead><tbody>{rows.map((r) => <tr key={r.id}><td className="text-nowrap">{formatTime(r.time)}</td><td><Badge>{r.category}</Badge><small className="d-block text-muted">{r.recordType === 'check' ? 'Hasil pemeriksaan collector' : 'Event monitoring'}</small></td><td className="nms-word-break"><strong>{r.device}</strong><small className="d-block text-muted">{r.target}</small></td><td><Badge status={r.severity} />{r.recordType === 'check' && <small className="d-block text-muted">Label hasil check</small>}</td><td className="nms-word-break">{r.message}</td><td><button className="btn btn-sm btn-outline-primary" aria-label={`Detail log ${r.id}`} onClick={() => setSelected(r)}>Detail</button></td></tr>)}</tbody></table></div>}
      <JournalPagination journal={journal} label="logs" />
    </Panel>
    {selected && <Modal title="Detail record monitoring" onClose={() => setSelected(null)} footer={<button className="btn btn-secondary" onClick={() => setSelected(null)}>Tutup</button>}><h3 className="h6">{selected.message}</h3><dl className="row"><dt className="col-sm-4">Record ID</dt><dd className="col-sm-8 nms-word-break">{selected.id}</dd><dt className="col-sm-4">Waktu</dt><dd className="col-sm-8">{formatTime(selected.time)}</dd><dt className="col-sm-4">Sumber</dt><dd className="col-sm-8">{selected.source}</dd><dt className="col-sm-4">Perangkat</dt><dd className="col-sm-8">{selected.device}</dd><dt className="col-sm-4">Jenis</dt><dd className="col-sm-8">{selected.kind}</dd></dl><Evidence value={selected.evidence} />{selected.incidentId && <Link className="btn btn-outline-primary mt-3" to={`/alerts?incident=${encodeURIComponent(selected.incidentId)}`}>Buka insiden terkait</Link>}</Modal>}
  </>
}
