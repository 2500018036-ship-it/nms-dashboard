import { Link } from 'react-router'
import { useEffect, useState } from 'react'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, CollectorTable, EmptyState, Panel, formatTime } from '../components/ui'
import { SearchField } from '../components/monitoring'
import { Modal } from '../components/Modal'
import { adaptStatus } from '../data/adapters'
import { errorMessages } from '../data/apiClient'

export function ObservedDevices() {
  const { observedDevices, connection, client } = useMonitoring()
  const [query, setQuery] = useState(''); const [status, setStatus] = useState('all'); const [selected, setSelected] = useState(null)
  const [detail, setDetail] = useState({ loading: false, checks: [], error: null })
  useEffect(() => {
    if (!selected) return
    const controller = new AbortController()
    client.device(selected.id, controller.signal).then((data) => {
      const checks = adaptStatus({ checks: data.checks, alerts: [] }).checks
      if (!controller.signal.aborted) setDetail({ loading: false, checks, error: null })
    }).catch((e) => { if (!controller.signal.aborted) setDetail({ loading: false, checks: [], error: e.code }) })
    return () => controller.abort()
  }, [selected, client])
  const rows = observedDevices.filter((d) => `${d.name} ${d.host} ${d.collectors.join(' ')}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || d.status === status))
  return <><Panel title="Perangkat terpantau" subtitle="Data aktual dari konfigurasi collector backend · akses baca saja" action={<Badge>{observedDevices.length} perangkat</Badge>}>
    <div className="d-flex flex-wrap gap-2 mb-3"><SearchField value={query} onChange={setQuery} label="Cari perangkat terpantau" placeholder="Nama, alamat, collector…" /><select className="form-select w-auto" aria-label="Filter kondisi perangkat" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">Semua kondisi</option>{['UP', 'DEGRADED', 'UNKNOWN'].map((s) => <option key={s}>{s}</option>)}</select></div>
    {connection.devicesError && <div className="alert alert-warning" role="status">Daftar perangkat belum diperbarui: {errorMessages[connection.devicesError]}. Data sebelumnya dapat kedaluwarsa.</div>}
    {!observedDevices.length ? <EmptyState action={false} title={connection.status === 'loading' ? 'Membaca daftar perangkat…' : 'Perangkat belum tersedia'} description="Daftar ini berasal dari backend; browser tidak memindai jaringan." /> : !rows.length ? <p className="text-muted text-center py-4">Tidak ada perangkat yang sesuai filter.</p> : <div className="table-responsive"><table className="table table-hover align-middle mb-0 nms-table"><thead><tr><th>Perangkat / alamat</th><th>Kondisi collector</th><th>Metode teramati</th><th>Pemeriksaan terakhir</th><th>Detail</th></tr></thead><tbody>{rows.map((d) => <tr key={d.id}><td><strong><Link to={`/devices/${d.id}`}>{d.name}</Link></strong><small className="d-block text-muted">{d.host}</small></td><td><Badge status={d.status} /><small className="d-block text-muted">{d.readState === 'partial_failure' || d.status === 'DEGRADED' ? 'Host merespons; sebagian collector belum tersedia' : d.status === 'UNKNOWN' ? 'Data belum lengkap / kedaluwarsa' : 'Collector merespons'}</small></td><td>{d.methods.join(', ')}<small className="d-block text-muted">{d.collectors.length} collector</small></td><td>{formatTime(d.sampled)}</td><td><button className="btn btn-sm btn-outline-primary" onClick={() => { setDetail({ loading: true, checks: [], error: null }); setSelected(d) }} aria-label={`Detail ${d.name}`}>Lihat detail</button></td></tr>)}</tbody></table></div>}
  </Panel>{selected && <Modal title={`Kondisi perangkat · ${selected.name}`} onClose={() => setSelected(null)} footer={<button className="btn btn-secondary" onClick={() => setSelected(null)}>Tutup</button>}><p>{selected.host}</p><div className="alert alert-info small">Membaca cache bersama bot. Tidak ada probe tambahan atau perubahan perangkat.</div>{detail.loading ? <p role="status">Membaca detail…</p> : detail.error ? <div className="alert alert-warning">{errorMessages[detail.error]}</div> : <CollectorTable rows={detail.checks} compact />}</Modal>}</>
}
