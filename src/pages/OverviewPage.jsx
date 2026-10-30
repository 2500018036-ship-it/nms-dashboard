import { useState } from 'react'
import { Link } from 'react-router'
import { useHistory, useMonitoring } from '../data/useMonitoring'
import { Badge, CollectorTable, EventList, MetricCard, Panel, percentage } from '../components/ui'
import { HostTable } from '../components/monitoring'
import { HistoryChart, TrafficChart } from '../components/HistoryChart'
import { formatBps } from '../data/format'
import { DeviceMonitoringOverview } from '../components/DeviceMonitoringOverview'

export function OverviewPage() {
  const { snapshot, events, connection, trafficHistory, observedDevices } = useMonitoring()
  const { core } = snapshot
  const history = useHistory('debian'); const [interfaceId, setInterfaceId] = useState('')
  const selected = core.traffic.find((t) => t.id === interfaceId) || core.traffic.find((t) => t.rx !== null || t.tx !== null) || core.traffic[0]
  const ready = connection.status === 'connected'
  const stale = snapshot.checks.filter((c) => c.stale).length
  const attention = snapshot.checks.filter((c) => ['DOWN', 'DEGRADED'].includes(c.status)).length
  const host = core.hosts[0]
  const virtualizationReady=core.virtualization && !core.virtualization.stale && ['UP','DEGRADED'].includes(core.virtualization.status)
  const dockerReady=snapshot.checks.some((c)=>c.id==='docker' && !c.stale && ['UP','DEGRADED'].includes(c.status))
  return <>
    <div className="row g-3 g-lg-4 mb-4">
      <MetricCard label="Perangkat terpantau" value={ready && !connection.devicesError ? observedDevices.length : '—'} icon="router" note="Daftar baca dari konfigurasi collector backend" />
      <MetricCard label="Perlu perhatian" value={ready ? attention : '—'} icon="exclamation-triangle" note="Check DOWN / DEGRADED" tone={attention ? 'warning' : ''} />
      <MetricCard label="Alert aktif" value={ready ? snapshot.alerts.length : '—'} icon="bell" note="State alert, tidak diturunkan dari trafik" />
      <MetricCard label="Kesegaran monitoring" value={ready ? `${snapshot.checks.length - stale}/${snapshot.checks.length}` : '—'} icon="heart-pulse" note="Sampel belum kedaluwarsa; bukan jumlah sehat" />
    </div>
    <div className="mb-4"><DeviceMonitoringOverview /></div>
    <div className="row g-3 g-lg-4 mb-4"><MetricCard label="RX terpilih" value={formatBps(selected?.rx)} icon="arrow-down" note={selected?.name || 'Menunggu rate interface'} /><MetricCard label="TX terpilih" value={formatBps(selected?.tx)} icon="arrow-up" note={selected?.name || 'Tidak menganggap data hilang sebagai nol'} /><MetricCard label="CPU host" value={percentage(host?.cpu)} icon="cpu" note={host?.name || 'Menunggu host collector'} /><MetricCard label="RAM host" value={percentage(host?.memory)} icon="memory" note={host?.name || 'Menunggu host collector'} /></div>
    <div className="row g-4"><div className="col-lg-8"><Panel title="Trafik Jaringan" subtitle="RX / TX · snapshot rate API sejak dashboard dibuka" action={<select className="form-select form-select-sm w-auto" aria-label="Interface ringkasan trafik" disabled={!core.traffic.length} value={selected?.id || ''} onChange={(e) => setInterfaceId(e.target.value)}>{!core.traffic.length && <option value="">Belum ada interface</option>}{core.traffic.map((t) => <option key={t.id} value={t.id}>{t.sourceId} / {t.name}</option>)}</select>}><TrafficChart points={selected ? trafficHistory[selected.id] || [] : []} /></Panel></div><div className="col-lg-4"><Panel title="Kesehatan Monitoring" subtitle="Sumber dan kesegaran data"><ul className="list-group list-group-flush"><li className="list-group-item d-flex justify-content-between gap-2">Sumber data <Badge>{connection.status === 'connected' ? 'API langsung' : 'Belum terintegrasi'}</Badge></li><li className="list-group-item d-flex justify-content-between gap-2">Collector snapshot <span>{ready ? snapshot.checks.length : '—'}</span></li><li className="list-group-item d-flex justify-content-between gap-2">Sampel lama / hilang <span>{ready ? stale : '—'}</span></li><li className="list-group-item d-flex justify-content-between gap-2">Status UNKNOWN <span>{ready ? snapshot.checks.filter((c) => c.status === 'UNKNOWN').length : '—'}</span></li></ul><Link className="btn btn-sm btn-outline-primary mt-3" to="/system-health">Detail kesehatan monitoring</Link></Panel><Panel title="Aktivitas Terbaru"><EventList events={events.slice(0, 3)} unavailable={!!connection.eventsError} /></Panel></div></div>
    <div className="row g-3 mb-4"><MetricCard label="Perangkat UP" value={ready ? observedDevices.filter((d)=>d.status==='UP').length : '—'} icon="router" note="Seluruh collector perangkat merespons"/><MetricCard label="Perangkat perlu perhatian" value={ready ? observedDevices.filter((d)=>d.status==='DEGRADED').length : '—'} icon="exclamation-triangle" note="Kegagalan layanan; bukan bukti host offline"/><MetricCard label="VM / LXC berjalan" value={virtualizationReady ? `${core.guests.filter((g)=>g.status==='UP').length}/${core.guests.length}` : '—'} icon="layers" note="Data API Proxmox terverifikasi"/><MetricCard label="Container berjalan" value={dockerReady ? `${core.containers.filter((c)=>c.state==='running').length}/${core.containers.length}` : '—'} icon="box-seam" note="Status Docker restricted collector"/></div><div className="d-flex flex-wrap gap-2 mb-4"><Link className="btn btn-outline-primary" to="/virtualization">Sumber daya Proxmox & storage</Link><Link className="btn btn-outline-secondary" to="/integrations">Portal layanan</Link><Link className="btn btn-outline-secondary" to="/topology">Peta jaringan</Link><Link className="btn btn-outline-secondary" to="/reports">Ketersediaan dan tren</Link></div>
    <div className="row g-4"><div className="col-lg-8"><Panel title="Host dan Node Proxmox" subtitle="Debian menunjukkan metrik OS/Docker; Proxmox menunjukkan node hypervisor. Collector belum memetakan Debian ke VMID." action={<Link className="btn btn-sm btn-outline-primary" to="/servers">Server dan Layanan</Link>}><HostTable rows={core.hosts.slice(0, 4)} devices={observedDevices} /></Panel></div><div className="col-lg-4"><Panel title="Peringatan Aktif" action={<Link className="btn btn-sm btn-outline-primary" to="/alerts">Lihat semua</Link>}>{snapshot.alerts.length ? <ul className="list-group list-group-flush">{snapshot.alerts.slice(0, 4).map((a) => <li className="list-group-item" key={a.key}><Badge status={a.severity} /><p className="mb-1 mt-2">{a.title}</p><small className="text-muted">{a.device}</small></li>)}</ul> : <p className="text-muted mb-0">{ready ? 'Tidak ada alert aktif pada snapshot ini.' : 'State alert belum dapat dibaca.'}</p>}</Panel></div></div>
    <div className="row g-4"><div className="col-lg-8"><Panel title="Riwayat Sumber Daya" subtitle="CPU & RAM · Debian host"><HistoryChart points={history.points} /></Panel></div><div className="col-lg-4"><Panel title="Status Collector"><CollectorTable rows={snapshot.checks} compact /></Panel></div></div>
  </>
}
