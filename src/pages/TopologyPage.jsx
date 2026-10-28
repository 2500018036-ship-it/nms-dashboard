import { useState } from 'react'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, CapabilityNotice, EmptyState, Panel, formatTime } from '../components/ui'
import { SearchField } from '../components/monitoring'

export function TopologyPage() {
  const { snapshot } = useMonitoring(); const topology = snapshot.core.topology
  const [selectedId, setSelectedId] = useState(''); const [query, setQuery] = useState(''); const [view, setView] = useState('graph')
  const nodes = topology.nodes.filter((n) => `${n.name} ${n.type}`.toLowerCase().includes(query.toLowerCase()))
  const visible = new Set(nodes.map((n) => n.id)); const links = topology.links.filter((l) => visible.has(l.source) && visible.has(l.target))
  const selected = topology.nodes.find((n) => n.id === selectedId)
  const width = 1000; const height = 410
  const positioned = new Map(nodes.map((n, i) => [n.id, { x: nodes.length === 1 ? 500 : 130 + (i % 4) * 240, y: 70 + Math.floor(i / 4) * 140 }]))
  const graphHeight = Math.max(height, Math.ceil(nodes.length / 4) * 140 + 20)
  return <>
    <CapabilityNotice title="Topologi berbasis bukti telemetri">Relasi antarperangkat hanya dibentuk dari data observasi neighbor dan routing yang benar-benar disediakan backend. Tanpa data relasi yang terverifikasi, sistem tidak menebak link fisik atau konektivitas.</CapabilityNotice>
    <Panel title="Relasi Perangkat" subtitle={`${topology.nodes.length} node · ${topology.links.length} relasi pada sumber aktif`} action={<div className="btn-group btn-group-sm" role="group" aria-label="Tampilan topologi"><button className={`btn btn-outline-primary ${view === 'graph' ? 'active' : ''}`} aria-pressed={view === 'graph'} onClick={() => setView('graph')}>Grafik</button><button className={`btn btn-outline-primary ${view === 'table' ? 'active' : ''}`} aria-pressed={view === 'table'} onClick={() => setView('table')}>Tabel koneksi</button></div>}>
      <div className="mb-3"><SearchField value={query} onChange={setQuery} label="Cari node topologi" placeholder="Nama atau tipe node…" /></div>
      {!topology.nodes.length ? <EmptyState icon="diagram-3" title="Data hubungan perangkat belum tersedia" description="Belum ada endpoint topology atau observasi neighbor yang bisa digunakan pada sumber aktif." /> : !nodes.length ? <p className="text-muted text-center py-5">Tidak ada node yang sesuai.</p> : view === 'graph' ? <div className="table-responsive"><svg viewBox={`0 0 ${width} ${graphHeight}`} className="nms-topology" style={{ height: graphHeight }} role="group" aria-label="Grafik relasi perangkat dari API">
        {links.map((link) => { const a = positioned.get(link.source); const b = positioned.get(link.target); return <g key={link.id}><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} className="link-line" strokeDasharray="5 4" /><text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 8} textAnchor="middle" fontSize="10">{link.label}</text></g> })}
        {nodes.map((n) => { const p = positioned.get(n.id); return <g key={n.id} role="button" tabIndex={0} aria-label={`Detail node ${n.name}`} aria-pressed={selectedId === n.id} onClick={() => setSelectedId(n.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(n.id) } }}><title>{n.name}</title><rect className="node-box" x={p.x - 102} y={p.y - 30} width="204" height="60" rx="8" strokeWidth={selectedId === n.id ? 3 : 1} /><text x={p.x} y={p.y - 3} fontSize="11" textAnchor="middle">{n.name.length > 25 ? `${n.name.slice(0, 23)}…` : n.name}</text><text x={p.x} y={p.y + 17} fontSize="10" textAnchor="middle">{n.type} · {n.status}</text></g> })}
      </svg></div> : <div className="table-responsive"><table className="table align-middle nms-table"><thead><tr><th>Sumber</th><th>Tujuan</th><th>Interface / label</th><th>Bukti</th><th>Waktu</th></tr></thead><tbody>{links.map((l) => <tr key={l.id}><td>{topology.nodes.find((n) => n.id === l.source)?.name}</td><td>{topology.nodes.find((n) => n.id === l.target)?.name}</td><td>{l.label}</td><td>{l.evidence}</td><td>{formatTime(l.sampled)}</td></tr>)}</tbody></table></div>}
    </Panel>
    <Panel title="Node Terpilih">{selected ? <><h3 className="h6">{selected.name}</h3><p className="text-muted">ID: {selected.id} · Tipe: {selected.type}</p><Badge status={selected.status} /><div className="small text-muted mt-3">Relasi teramati: {topology.links.filter((l) => l.source === selected.id || l.target === selected.id).length}. Status node mengikuti sumber data aktif; status link belum diverifikasi melalui pengujian jalur.</div></> : <p className="text-muted mb-0">Pilih node pada grafik untuk melihat detail. Pemilihan tidak menjalankan probe perangkat.</p>}</Panel>
  </>
}
