import { useState } from 'react'
import { usePlatform } from '../data/platformContext'
import { networkDeviceView } from '../data/networkDeviceView'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, CapabilityNotice, CollectorTable, MetricCard, Panel, Tabs, percentage } from '../components/ui'
import { InterfaceTable, SearchField, ServiceTable } from '../components/monitoring'
import { TrafficChart } from '../components/HistoryChart'
import { formatBps } from '../data/format'

export function NetworkPage() {
  const { snapshot, trafficHistory, observedDevices } = useMonitoring(); const p = usePlatform(); const [deviceId,setDeviceId]=useState(''); const view=networkDeviceView(snapshot.core,p.inventory,observedDevices,deviceId,p.capabilities.inventory_targets); const core={...snapshot.core,...view}
  const [tab, setTab] = useState('interfaces'); const [query, setQuery] = useState(''); const [status, setStatus] = useState('all'); const [selectedId, setSelectedId] = useState('')
  const selected = core.traffic.find((t) => t.id === selectedId) || core.traffic.find(t=>t.name!=='lo'&&(t.rx>0||t.tx>0)) || core.traffic.find(t=>t.name!=='lo') || core.traffic[0]
  const interfaces = core.interfaces.filter((i) => `${i.name} ${i.sourceName} ${i.type}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || status === i.status))
  const points = selected ? trafficHistory[selected.id] || [] : []
  return <>
    <Panel title="Pilih perangkat jaringan"><label className="form-label" htmlFor="network-device">Perangkat terintegrasi</label><select id="network-device" className="form-select" value={view.device?.id||''} onChange={e=>{setDeviceId(e.target.value);setSelectedId('')}} disabled={!view.devices.length}>{!view.devices.length&&<option value="">Belum ada perangkat terintegrasi</option>}{view.devices.map(d=><option key={d.id} value={d.id}>{d.name}  /  {d.host}</option>)}</select></Panel>
    <div className="row g-3 mb-4"><MetricCard label="Interface teramati" value={core.interfaces.length || '—'} icon="ethernet" note="Snapshot collector, bukan seluruh jaringan" /><MetricCard label="RX interface terpilih" value={formatBps(selected?.rx)} icon="arrow-down" note={selected ? `${selected.sourceName} / ${selected.name}` : 'Menunggu sampel'} /><MetricCard label="TX interface terpilih" value={formatBps(selected?.tx)} icon="arrow-up" note={selected ? `${selected.sourceName} / ${selected.name}` : 'Menunggu sampel'} /><MetricCard label="Utilisasi interface" value={percentage(selected?.utilization)} icon="speedometer2" note={selected?.capacity ? `Kapasitas ${formatBps(selected.capacity)}` : 'Kapasitas belum tersedia'} /></div>
    <Panel title="Trafik Interface" subtitle="RX/TX dari sampel collector · memori sesi, maks. 120 sampel per interface" action={<select className="form-select form-select-sm w-auto" aria-label="Pilih interface grafik" value={selected?.id || ''} disabled={!core.traffic.length} onChange={(e) => setSelectedId(e.target.value)}>{!core.traffic.length && <option value="">Belum ada interface</option>}{core.traffic.map((t) => <option key={t.id} value={t.id}>{t.sourceName} / {t.name}</option>)}</select>} footer="Tidak menjumlahkan interface virtual dan fisik. Nilai yang tidak tersedia tidak dianggap nol."><TrafficChart points={points} /></Panel>
    <Tabs value={tab} onChange={setTab} items={[{ value: 'interfaces', label: 'Interface' }, { value: 'connectivity', label: 'Konektivitas dan latensi' }, { value: 'collectors', label: 'Collector jaringan' }]} />
    {tab === 'interfaces' && <Panel title="Status dan Counter Interface" action={<Badge>Collector terhubung</Badge>}><div className="d-flex flex-wrap gap-2 mb-3"><SearchField value={query} onChange={setQuery} label="Cari interface" placeholder="Interface, tipe, sumber…" /><select className="form-select w-auto" aria-label="Filter status interface" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">Semua status</option>{['UP', 'DOWN', 'DISABLED', 'UNKNOWN'].map((s) => <option key={s}>{s}</option>)}</select></div>{core.interfaces.length && !interfaces.length ? <p className="text-muted py-4 text-center">Tidak ada interface yang sesuai filter.</p> : <InterfaceTable interfaces={interfaces} traffic={core.traffic} />}</Panel>}
    {tab === 'connectivity' && <><Panel title="Konektivitas, Latensi, dan Packet Loss"><ServiceTable rows={core.services} /></Panel><CapabilityNotice title="Batas diagnosis">Packet loss memerlukan sampel pengujian yang memadai dari backend. Satu balasan ICMP tidak diasumsikan sebagai packet loss 0%. Port TCP terbuka tidak membuktikan aplikasi atau VLAN sehat.</CapabilityNotice></>}
    {tab === 'collectors' && <Panel title="Status Collector Jaringan" subtitle="Routing, VPN, SNMP, API, dan pemeriksaan konektivitas"><CollectorTable rows={snapshot.checks.filter(c=>view.sources.includes(c.id)).map(c=>({...c,id:view.device?.name||c.id}))} /></Panel>}
  </>
}
