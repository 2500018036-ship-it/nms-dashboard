import { Link } from 'react-router'
import { useState } from 'react'
import { useMonitoring } from '../data/useMonitoring'import { topologyHostSummary } from '../data/topologyModel'
import { CapabilityNotice, MetricCard, Panel, Tabs } from '../components/ui'
import { HostTable, GuestTable, ContainerTable, ServiceTable, SearchField } from '../components/monitoring'

export function ServersPage() {
  const { snapshot, observedDevices } = useMonitoring(); const { core } = snapshot
  const [tab, setTab] = useState('hosts'); const [query, setQuery] = useState(''); const [status, setStatus] = useState('all')
  const filter = (rows) => rows.filter((r) => `${r.name} ${r.id} ${r.node || ''} ${r.image || ''} ${r.method || ''}`.toLowerCase().includes(query.toLowerCase()) && (status === 'all' || r.status === status))
  const groups = { hosts: core.hosts, guests: core.guests, containers: core.containers, services: core.services }; const current = filter(groups[tab])
  const ready = snapshot.checks.length > 0
  return <><div className="d-flex justify-content-end mb-3"><Link className="btn btn-outline-primary" to="/virtualization">Proxmox VE · nodes, VM, LXC, storage</Link></div>
    <div className="row g-3 mb-4"><MetricCard label="Host & node" value={ready ? core.hosts.length : '—'} icon="hdd-stack" note={ready ? topologyHostSummary(core.hosts) : 'Menunggu data collector host'} /><MetricCard label="VM / LXC" value={core.guests.length || '—'} icon="pc-display" note="Hanya guest yang dikembalikan API Proxmox" /><MetricCard label="Container" value={core.containers.length || '—'} icon="box-seam" note="Snapshot restricted collector pada Debian server" /><MetricCard label="Service checks" value={ready ? core.services.length : '—'} icon="globe" note="HTTP / DNS / TCP / ICMP sesuai metode" /></div>
    <Tabs value={tab} onChange={(value) => { setTab(value); setQuery(''); setStatus('all') }} items={[{ value: 'hosts', label: 'Hosts' }, { value: 'guests', label: 'VM / LXC' }, { value: 'containers', label: 'Docker' }, { value: 'services', label: 'Services' }]} />
    <Panel title={{ hosts: 'Host Resources', guests: 'Virtual Machines & LXC', containers: 'Docker Containers', services: 'Service Availability' }[tab]} subtitle={tab === 'hosts' ? 'Debian menampilkan metrik OS/Docker; Proxmox menampilkan node hypervisor. Collector belum memetakan Debian ke VMID.' : 'CPU, RAM, disk, health, dan uptime ditampilkan hanya jika tersedia'}>
      <div className="d-flex flex-wrap gap-2 mb-3"><SearchField value={query} onChange={setQuery} label="Cari host atau layanan" placeholder="Nama, ID, node, image…" /><select className="form-select w-auto" aria-label="Filter status resource" value={status} onChange={(e) => setStatus(e.target.value)}><option value="all">Semua status</option>{['UP', 'DOWN', 'DEGRADED', 'UNKNOWN'].map((s) => <option key={s}>{s}</option>)}</select></div>
      {groups[tab].length && !current.length ? <p className="text-muted py-4 text-center">Tidak ada hasil pada filter ini.</p> : tab === 'hosts' ? <HostTable rows={current} devices={observedDevices} /> : tab === 'guests' ? <GuestTable rows={current} /> : tab === 'containers' ? <ContainerTable rows={current} /> : <ServiceTable rows={current} />}
    </Panel>
    <CapabilityNotice title="Akses observasi">Tidak tersedia aksi start/stop VM, restart container, atau perubahan layanan. CPU Docker dapat melewati 100% pada host multicore. Health yang tidak dikonfigurasi tidak disamakan dengan aplikasi sehat.</CapabilityNotice>
  </>
}
