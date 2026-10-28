import { useState } from 'react'
import { usePlatform } from '../data/platformContext'
import { Feedback } from '../components/PlatformUI'
import { useSearchParams } from 'react-router'
import { Badge, CapabilityNotice, MetricCard, Panel, formatTime } from '../components/ui'
import { Modal } from '../components/Modal'
import { Evidence, IncidentBadge, JournalControls, JournalFeedback, JournalPagination } from '../components/JournalControls'
import { useIncident, useJournal } from '../data/useJournal'
import { errorMessages } from '../data/apiClient'

const deliveryLabels = { sent: 'Terkirim', pending: 'Dalam antrean', failed: 'Gagal terkirim', suppressed: 'Ditahan kebijakan / deduplikasi', uncertain: 'Hasil pengiriman belum pasti', not_queued: 'Belum ada catatan pengiriman' }
function IncidentDetail({ id, onClose }) {
  const p=usePlatform();const [ack,setAck]=useState(null);const [note,setNote]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState(null)
  const result = useIncident(id)
  const a = result.data
  return <Modal title="Detail insiden" onClose={onClose} footer={<button className="btn btn-secondary" onClick={onClose}>Tutup</button>}>
    {result.error ? <div className="alert alert-warning" role="alert">{errorMessages[result.error] || 'Insiden tidak dapat dibaca'}</div> : !a ? <p role="status">Membaca insiden…</p> : <>
      <h3 className="h6">{a.title}</h3><div className="d-flex gap-2 mb-3"><Badge status={a.severity} /><IncidentBadge status={a.status} /></div>
      <dl className="row small"><dt className="col-sm-4">ID Insiden</dt><dd className="col-sm-8 nms-word-break">{a.id}</dd><dt className="col-sm-4">Identitas kondisi</dt><dd className="col-sm-8 nms-word-break">{a.key}</dd><dt className="col-sm-4">Perangkat</dt><dd className="col-sm-8">{a.device}</dd><dt className="col-sm-4">Mulai teramati</dt><dd className="col-sm-8">{formatTime(a.firstSeen)}</dd><dt className="col-sm-4">Transisi terakhir</dt><dd className="col-sm-8">{formatTime(a.updatedAt)}</dd><dt className="col-sm-4">Observasi terakhir</dt><dd className="col-sm-8">{formatTime(a.lastObservedAt)}</dd><dt className="col-sm-4">Waktu penutupan</dt><dd className="col-sm-8">{formatTime(a.resolvedAt)}</dd><dt className="col-sm-4">Notifikasi Telegram</dt><dd className="col-sm-8">{deliveryLabels[a.delivery.status] || a.delivery.status}<small className="d-block text-muted">Percobaan: {a.delivery.attempts ?? '—'} · status event terakhir</small></dd></dl>
      {a.status === 'RETIRED' && <div className="alert alert-info small">Insiden dihentikan karena kebijakan atau perubahan inventaris. Status ini bukan bukti layanan pulih.</div>}
      {a.partialHistory && <div className="alert alert-warning small">Sebagian riwayat awal tidak tersedia atau sudah melewati retensi. Waktu/status yang tidak diketahui tidak diisi dengan perkiraan.</div>}
      <div className="alert alert-secondary small">Acknowledgment mencatat penanggung jawab tanpa mengubah status gangguan. Pemulihan tetap ditetapkan oleh monitoring.</div>
      {(ack||a.acknowledgment)?<div className="alert alert-success small">Diakui oleh {(ack||a.acknowledgment).actor} · {formatTime((ack||a.acknowledgment).at)}<div>{(ack||a.acknowledgment).note}</div></div>:a.acknowledgmentSupported&&<form className="mb-3" onSubmit={async(e)=>{e.preventDefault();setBusy(true);try{const value=await p.mutate('acknowledge/'+id,{note});setAck(value);result.refresh();setError(null)}catch(e){setError(e.code)}finally{setBusy(false)}}}><label htmlFor="incident-note" className="form-label">Catatan acknowledgment</label><input id="incident-note" className="form-control mb-2" maxLength={300} disabled={!p.canAcknowledge||busy} value={note} onChange={(e)=>setNote(e.target.value)}/><button className="btn btn-sm btn-primary" disabled={!p.canAcknowledge||busy}>Acknowledge insiden</button>{!p.canAcknowledge&&<small className="text-muted ms-2">Memerlukan peran Operator / Administrator</small>}</form>}<Feedback error={error}/><h4 className="h6">Bukti yang tersedia</h4><Evidence value={a.evidence} />
      <h4 className="h6 mt-4">Kronologi insiden</h4>{!a.timeline.length ? <p className="text-muted small">Event kronologi tidak tersedia dalam retensi saat ini.</p> : <ol className="list-group list-group-numbered">{a.timeline.map((e) => <li className="list-group-item nms-word-break" key={e.id}><strong>{e.kind}</strong> · {formatTime(e.time)}<div>{e.title}</div><small className="text-muted">{e.id} · {deliveryLabels[e.delivery] || e.delivery}</small><details className="mt-2"><summary className="small">Informasi pendukung</summary><Evidence value={e.evidence} /></details></li>)}</ol>}{a.timelineTruncated && <p className="text-muted small">Menampilkan maksimum 100 event terbaru.</p>}
    </>}
  </Modal>
}
export function AlertsPage() {
  const journal = useJournal('incidents')
  const [params, setParams] = useSearchParams()
  const id = params.get('incident')
  const rows = journal.data?.items || []
  const summary = journal.data?.summary
  return <>
    <div className="row g-3 mb-4"><MetricCard label="Insiden aktif" value={summary?.ACTIVE ?? '—'} icon="bell" note="Jumlah tersimpan, di luar filter daftar" /><MetricCard label="Pulih tercatat" value={summary?.RECOVERED ?? '—'} icon="arrow-counterclockwise" note="Dikonfirmasi oleh monitoring" /><MetricCard label="Dihentikan" value={summary?.RETIRED ?? '—'} icon="archive" note="Kebijakan / inventaris; bukan recovery" /><MetricCard label="Acknowledgment" value="Tercatat server" icon="check2-circle" note="Operator / Administrator · tanpa resolusi semu" /></div>
    <Panel title="Peringatan dan Insiden" subtitle="Satu identitas untuk satu siklus gangguan; severity insiden mempertahankan tingkat tertinggi yang tercatat">
      <JournalControls journal={journal} kind="incidents" />
      <JournalFeedback journal={journal} emptyMessage="Tidak ada insiden pada filter ini. Status hanya mengikuti data backend." />
      {!!rows.length && <div className="table-responsive"><table className="table table-hover align-middle nms-table"><thead><tr><th>Tingkat keparahan</th><th>Insiden / perangkat</th><th>Status</th><th>Mulai (WIB)</th><th>Transisi terakhir</th><th>ACK</th><th>Detail</th></tr></thead><tbody>{rows.map((a) => <tr key={a.id}><td><Badge status={a.severity} /></td><td className="nms-word-break"><strong>{a.title}</strong><small className="d-block text-muted">{a.device} · {a.key}</small><small className="d-block text-muted">{a.id}</small></td><td><IncidentBadge status={a.status} /></td><td className="text-nowrap">{formatTime(a.firstSeen)}</td><td className="text-nowrap">{formatTime(a.updatedAt)}</td><td><Badge status={a.acknowledgment?'UP':'UNKNOWN'}>{a.acknowledgment? a.acknowledgment.actor : 'Belum ACK'}</Badge></td><td><button className="btn btn-sm btn-outline-primary" aria-label={`Detail insiden ${a.id}`} onClick={() => setParams({ incident: a.id })}>Detail</button></td></tr>)}</tbody></table></div>}
      <JournalPagination journal={journal} label="incidents" />
    </Panel>
    <CapabilityNotice title="Keputusan alert tetap di backend">Deduplikasi, cooldown, hysteresis dan pemulihan dijalankan oleh engine monitoring dan outbox Telegram yang sama. Filter atau pembaruan halaman tidak mengirim ulang notifikasi.</CapabilityNotice>
    {id && <IncidentDetail id={id} onClose={() => setParams({})} />}
  </>
}
