import { useState } from 'react'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, CapabilityNotice, CollectorTable, MetricCard, Panel, Tabs, percentage } from '../components/ui'
import { InterfaceTable, SearchField, ServiceTable } from '../components/monitoring'
import { TrafficChart } from '../components/HistoryChart'
import { formatBps } from '../data/format'

export function NetworkPage() {
  const { snapshot, trafficHistory } = useMonitoring(); const { core } = snapshot
  const [tab, setTab] = useState('interfaces'); const [query, setQuery] = useState(''); const [status, setStatus] = useState('all'); const [selectedId, setSelectedId] = useState('')
  const selected = core.traffic.find((t) => t.id === selectedId) || core.traffic.find((t) => t.rx !== null || t.tx !== null) || core.traffic[0]
  const interfaces = core.interfaces.filter((i) => `${i.name} ${i.sourceId} ${i.type}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || status === i.status))
  const points = selected ? trafficHistory[selected.id] || [] : []
  return <>
    <div className="row g-3 mb-4"><MetricCard label="Interface teramati" value={core.interfaces.length || '—'} icon="ethernet" note="Snapshot collector, bukan seluruh jaringan" /><MetricCard label="RX interface terpilih" value={formatBps(selected?.rx)} icon="arrow-down" note={selected ? `${selected.sourceId} / ${selected.name}` : 'Menunggu sampel'} /><MetricCard label="TX interface terpilih" value={formatBps(selected?.tx)} icon="arrow-up" note={selected ? `${selected.sourceId} / ${selected.name}` : 'Menunggu sampel'} /><MetricCard label="Utilisasi interface" value={percentage(selected?.utilization)} icon="speedometer2" note={selected?.capacity ? `Kapasitas ${formatBps(selected.capacity)}` : 'Kapasitas belum tersedia'} /></div>
    <Panel title="Interface Traffic" subtitle="RX/TX dari rate API · memori sesi, maks. 120 sampel per interface" action={<select className="form-select form-select-sm w-auto" aria-label="Pilih interface grafik" value={selected?.id || ''} disabled={!core.traffic.length} onChange={(e) => setSelectedId(e.target.value)}>{!core.traffic.length && <option value="">Belum ada interface</option>}{core.traffic.map((t) => <option key={t.id} value={t.id}>{t.sourceId} / {t.name}</option>)}</select>} footer="Tidak menjumlahkan interface virtual dan fisik. Nilai yang tidak tersedia tidak dianggap nol."><TrafficChart points={points} /></Panel>
    <Tabs value={tab} onChange={setTab} items={[{ value: 'interfaces', label: 'Interfaces' }, { value: 'connectivity', label: 'Connectivity & latency' }, { value: 'collectors', label: 'Network collectors' }]} />
    {tab === 'interfaces' && <Panel title="Interface Status & Counters" action={<Badge>Live API</Badge>}><div className="d-flex flex-wrap gap-2 mb-3"><SearchField value={query} onChange={setQuery} label="Cari interface" placeholder="Interface, tipe, sumber…" /><select className="form-select w-auto" aria-label="Filter status interface" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">Semua status</option>{['UP', 'DOWN', 'DISABLED', 'UNKNOWN'].map((s) => <option key={s}>{s}</option>)}</select></div>{core.interfaces.length && !interfaces.length ? <p className="text-muted py-4 text-center">Tidak ada interface yang sesuai filter.</p> : <InterfaceTable interfaces={interfaces} traffic={core.traffic} />}</Panel>}
    {tab === 'connectivity' && <><Panel title="Connectivity, Latency & Packet Loss"><ServiceTable rows={core.services} /></Panel><CapabilityNotice title="Batas diagnosis">Packet loss memerlukan sampel pengujian yang memadai dari backend. Satu balasan ICMP tidak diasumsikan sebagai packet loss 0%. Port TCP terbuka tidak membuktikan aplikasi atau VLAN sehat.</CapabilityNotice></>}
    {tab === 'collectors' && <Panel title="Network Collector Status" subtitle="Routing, VPN, SNMP, API, dan pemeriksaan konektivitas"><CollectorTable rows={snapshot.checks.filter((c) => !/host|proc|docker|PVE/i.test(c.method))} /></Panel>}
  </>
}
