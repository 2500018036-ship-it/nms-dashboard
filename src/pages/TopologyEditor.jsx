import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { portObservation, connectedTopologyDevices, knownTopologyDeviceIds, topologyDeviceNodes, linkedLegacyServices } from '../data/topologyModel'
import { usePlatform } from '../data/platformContext'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, EmptyState, Panel } from '../components/ui'
import { Modal, Confirmation } from '../components/Modal'
import { AccessNote, Feedback, Loading } from '../components/PlatformUI'

const colors = { UP: 'var(--bs-success)', DOWN: 'var(--bs-danger)', DEGRADED: 'var(--bs-warning)', UNKNOWN: 'var(--bs-secondary)' }
const id = (prefix) => prefix + crypto.randomUUID().replaceAll('-', '').slice(0, 12)
const deviceKinds = ['router', 'switch', 'firewall', 'server', 'access-point', 'proxmox', 'dns', 'vpn', 'iot', 'generic', 'other']

export function TopologyEditor() {
  const p = usePlatform()
  const canManage = !p.error && (p.canManage || p.capabilities.permissions?.includes('topology.manage'))
  const { snapshot, observedDevices } = useMonitoring()
  const [management, setManagement] = useState(null)
  const [managementError, setManagementError] = useState(null)
  const [managementLoading, setManagementLoading] = useState(true)
  const [selected, setSelected] = useState('')
  const [draft, setDraft] = useState(null)
  const [dirty, setDirty] = useState(false)
  const [baseRevision, setBaseRevision] = useState(null)
  const [nodeId, setNodeId] = useState('')
  const [query, setQuery] = useState('')
  const [modal, setModal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState('')
  const [view, setView] = useState({ x: 0, y: 0, zoom: 1 })
  const svg = useRef(null)
  const drag = useRef(null)

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const value = await p.client.platform('management')
        if (active) {
          setManagement(value)
          setManagementError(null)
        }
      } catch (e) {
        if (active) setManagementError(e.code || 'unavailable')
      } finally {
        if (active) setManagementLoading(false)
      }
    }
    refresh()
    const timer = setInterval(refresh, 30000)
    return () => {
      active = false
      clearInterval(timer)
    }
  }, [p.client])

  const saved = p.topologies.find((g) => g.id === selected) || (!selected ? p.topologies[0] : null)
  const graph = draft || (saved ? Object.fromEntries(Object.entries(saved).filter(([key]) => !['id', 'revision', 'created_at', 'updated_at'].includes(key))) : null)
  const inventoryStates = management?.inventory || []
  const resources = snapshot.core.hosts.filter((host) => host.sourceId === 'proxmox_resources')
  const knownDeviceIds = knownTopologyDeviceIds(p.inventory, observedDevices)
  const knownNodeResources = new Set(resources.map((host) => host.id).filter((value) => value.startsWith('node/')))
  const connectedDevices = connectedTopologyDevices({ inventory: p.inventory, inventoryStates, observedDevices, now: p.now })
  const visibleGraph = topologyDeviceNodes(graph, knownDeviceIds, knownNodeResources)
  const visibleNodes = visibleGraph.nodes.filter((node) => !query || (node.name + ' ' + node.kind + ' ' + (node.group || '')).toLowerCase().includes(query.toLowerCase()))
  const selectedNode = visibleGraph.nodes.find((node) => node.id === nodeId)

  const change = (next) => {
    if (!dirty) setBaseRevision(saved?.revision ?? null)
    setDraft(next)
    setDirty(true)
    setError(null)
    setMessage('')
  }
  const switchTo = (idValue) => {
    if (dirty) {
      setModal({ kind: 'switch', id: idValue })
      return
    }
    setSelected(idValue)
    setDraft(null)
    setNodeId('')
  }
  const point = (event) => {
    const value = svg.current.createSVGPoint()
    value.x = event.clientX
    value.y = event.clientY
    return value.matrixTransform(svg.current.getScreenCTM().inverse())
  }
  const status = (node) => {
    if (node.device_id) {
      const item = p.inventory.find((device) => device.id === node.device_id)
      if (item) {
        if (!item.enabled) return 'UNKNOWN'
        const state = inventoryStates.find((row) => row.id === item.id)
        if (state?.health?.stale) return 'UNKNOWN'
        if (state?.health?.status) return state.health.status
        const observed = observedDevices.find((device) => device.host === item.host)
        return observed?.status || 'UNKNOWN'
      }
      const observed = observedDevices.find((device) => device.id === node.device_id)
      if (observed) return observed.status
    }
    if (node.resource_id) return resources.find((resource) => resource.id === node.resource_id)?.status || 'UNKNOWN'
    const check = snapshot.checks.find((row) => row.id === node.collector)
    return check && !check.stale ? check.status : 'UNKNOWN'
  }
  const nodeServices = (node) => {
    const inventoryItem = p.inventory.find((item) => item.id === node.device_id)
    const observed = observedDevices.find((device) => device.id === node.device_id)
      || observedDevices.find((device) => device.host === inventoryItem?.host)
    const host = inventoryItem?.host || observed?.host
    const entries = []
    const add = (name, kind, serviceStatus = 'UNKNOWN', info = '') => {
      if (!name || entries.some((item) => item.name === name && item.kind === kind)) return
      entries.push({ name, kind, status: serviceStatus, info })
    }
    if (host) {
      for (const service of p.integrations) {
        if (!service.enabled || service.kind === 'proxmox') continue
        try {
          if (new URL(service.url).hostname.toLowerCase() === host.toLowerCase()) add(service.name, 'Integrasi', service.health?.status || 'UNKNOWN')
        } catch { /* Ignore malformed catalog entries. */ }
      }
      for (const service of snapshot.core.services) {
        if (service.host?.toLowerCase() === host.toLowerCase()) add(service.name, service.method, service.status)
      }
    }
    const collectors = new Set([node.collector, ...(observed?.collectors || [])])
    if (collectors.has('proxmox_resources')) {
      for (const guest of snapshot.core.guests) {
        add(guest.name, guest.type === 'lxc' ? 'LXC' : 'VM', guest.status, guest.vmid == null ? '' : 'ID ' + guest.vmid)
      }
    }
    if (collectors.has('docker') || inventoryItem?.type === 'container-host') {
      for (const container of snapshot.core.containers) add(container.name, 'Container', container.status, container.image)
    }
    for (const service of linkedLegacyServices(node, graph)) add(service.name, service.kind, 'UNKNOWN', 'Relasi topologi lama')
    return entries
  }
  const save = async () => {
    if (!graph) return
    setBusy(true)
    setError(null)
    try {
      const value = await p.mutate('topologies' + (saved ? '/' + saved.id : ''), {
        value: graph,
        ...(saved ? { revision: baseRevision ?? saved.revision } : {}),
      })
      setSelected(value.id)
      setDraft(null)
      setDirty(false)
      setMessage('Topologi tersimpan. Canvas hanya menampilkan perangkat; integrasi, VM, dan container terkait muncul saat perangkat di-hover.')
    } catch (e) {
      setError(e.code)
    } finally {
      setBusy(false)
    }
  }
  const removeGraph = async () => {
    setBusy(true)
    try {
      await p.mutate('topologies/' + saved.id + '/delete', { revision: saved.revision })
      setSelected('')
      setDraft(null)
      setDirty(false)
      setModal(null)
      setMessage('Topologi dihapus.')
      setError(null)
    } catch (e) {
      setError(e.code)
    } finally {
      setBusy(false)
    }
  }
  const move = (event) => {
    const activeDrag = drag.current
    if (!activeDrag || !graph) return
    if (activeDrag.type === 'pan') {
      setView((current) => ({
        ...current,
        x: activeDrag.view.x + (activeDrag.clientX - event.clientX) * activeDrag.factor,
        y: activeDrag.view.y + (activeDrag.clientY - event.clientY) * activeDrag.factor,
      }))
      return
    }
    const currentPoint = point(event)
    const x = Math.max(-5000, Math.min(5000, Math.round(currentPoint.x - activeDrag.dx)))
    const y = Math.max(-5000, Math.min(5000, Math.round(currentPoint.y - activeDrag.dy)))
    change({ ...graph, nodes: graph.nodes.map((node) => node.id === activeDrag.id ? { ...node, x, y } : node) })
  }
  const insert = (device) => {
    const newNode = {
      id: id('n_'),
      name: device.name,
      kind: device.kind,
      x: 140 + (visibleGraph.nodes.length % 4) * 235,
      y: 100 + Math.floor(visibleGraph.nodes.length / 4) * 125,
      group: device.group || '',
      collector: device.collector,
      resource_id: '',
      service_id: '',
      device_id: device.device_id,
    }
    change({ ...graph, nodes: [...graph.nodes, newNode] })
    setNodeId(newNode.id)
    setModal(null)
  }
  const deleteNode = () => {
    change({
      ...graph,
      nodes: graph.nodes.filter((node) => node.id !== nodeId),
      links: graph.links.filter((link) => link.source !== nodeId && link.target !== nodeId),
    })
    setNodeId('')
    setModal(null)
  }

  return <>
    <AccessNote canManage={canManage} />
    <Feedback error={error || p.error || managementError} message={message} />
    <Loading loading={p.loading || managementLoading} />
    <Panel title="Topology & Network Map" subtitle="Canvas berisi perangkat terdaftar/terpantau. Layanan dan workload ditampilkan pada hover perangkat." action={<div className="d-flex gap-2"><button className="btn btn-sm btn-outline-primary" disabled={!canManage || dirty} onClick={() => setModal({ kind: 'new' })}>Topologi baru</button><button className="btn btn-sm btn-primary" disabled={!canManage || !graph || !dirty || busy} onClick={save}>{busy ? 'Menyimpan…' : 'Simpan topologi'}</button></div>}>
      <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
        <select className="form-select w-auto" aria-label="Pilih topologi" value={saved?.id || ''} onChange={(event) => switchTo(event.target.value)}>
          {!saved && <option value="">Belum tersimpan</option>}
          {p.topologies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {graph && <>
          <strong>{graph.name}</strong>
          <Badge status={dirty ? 'DEGRADED' : 'UP'}>{dirty ? 'Belum disimpan' : 'Tersimpan'}</Badge>
          <input className="form-control nms-filter-search ms-md-auto" aria-label="Cari perangkat pada topologi" placeholder="Cari perangkat atau grup…" value={query} onChange={(event) => setQuery(event.target.value)} />
        </>}
      </div>

      {!graph
        ? <EmptyState action={false} icon="diagram-3" title="Belum ada topologi manual" description="Buat topologi, pilih perangkat yang collector-nya sedang UP, lalu susun relasinya. Data layanan tidak dibuat sebagai node." />
        : <>
          <div className="d-flex flex-wrap gap-2 mb-3">
            <button className="btn btn-sm btn-outline-secondary" disabled={!canManage || !connectedDevices.length || managementLoading} onClick={() => setModal({ kind: 'observed' })}>Tambah perangkat terhubung</button>
            <button className="btn btn-sm btn-outline-secondary" disabled={!canManage || visibleGraph.nodes.length < 2} onClick={() => setModal({ kind: 'edge' })}>Hubungkan perangkat</button>
            <Link className="btn btn-sm btn-outline-secondary" to="/management">Daftarkan / uji perangkat</Link>
            <button className="btn btn-sm btn-outline-secondary" disabled={!canManage} onClick={() => setModal({ kind: 'rename' })}>Ubah nama</button>
            <button className="btn btn-sm btn-outline-danger" disabled={!canManage || !saved} onClick={() => setModal({ kind: 'delete' })}>Hapus topologi</button>
            <div className="btn-group ms-md-auto">
              <button className="btn btn-sm btn-outline-secondary" aria-label="Zoom out" onClick={() => setView((current) => ({ ...current, zoom: Math.max(.35, current.zoom / 1.25) }))}>−</button>
              <button className="btn btn-sm btn-outline-secondary" onClick={() => setView({ x: 0, y: 0, zoom: 1 })}>{Math.round(view.zoom * 100)}% · Reset</button>
              <button className="btn btn-sm btn-outline-secondary" aria-label="Zoom in" onClick={() => setView((current) => ({ ...current, zoom: Math.min(3, current.zoom * 1.25) }))}>+</button>
            </div>
          </div>
          {visibleGraph.hiddenCount > 0 && <div className="alert alert-info small" role="status">{visibleGraph.hiddenCount} node lama bertipe service/VM/container atau tidak lagi terhubung ke inventaris disembunyikan dari canvas. Layanan lama yang mempunyai relasi tetap terlihat pada hover perangkat induk.</div>}
          {!connectedDevices.length && <div className="alert alert-warning small" role="status">Belum ada perangkat dengan sampel koneksi terbaru berstatus UP. Daftarkan perangkat dan tunggu hasil collector UP sebelum menambahkannya ke topologi.</div>}
          <div className="border rounded overflow-hidden">
            <svg ref={svg} className="w-100" style={{ height: 520, touchAction: 'none', background: 'var(--bs-tertiary-bg)' }} viewBox={view.x + ' ' + view.y + ' ' + 1100 / view.zoom + ' ' + 550 / view.zoom} aria-label="Editor topologi perangkat" role="img" onPointerMove={move} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }} onPointerDown={(event) => {
              if (event.target !== svg.current) return
              drag.current = { type: 'pan', view, clientX: event.clientX, clientY: event.clientY, factor: (1100 / view.zoom) / svg.current.getBoundingClientRect().width }
              svg.current.setPointerCapture(event.pointerId)
              setNodeId('')
            }}>
              {[...new Set(visibleNodes.map((node) => node.group).filter(Boolean))].map((group) => {
                const grouped = visibleNodes.filter((node) => node.group === group)
                const x = Math.min(...grouped.map((node) => node.x)) - 115
                const y = Math.min(...grouped.map((node) => node.y)) - 55
                return <g key={group} pointerEvents="none"><rect x={x} y={y} width={Math.max(...grouped.map((node) => node.x)) - x + 110} height={Math.max(...grouped.map((node) => node.y)) - y + 58} rx="14" fill="var(--bs-primary-bg-subtle)" opacity=".35"/><text x={x + 12} y={y + 18} fill="var(--bs-body-color)" fontSize="12">{group}</text></g>
              })}
              {visibleGraph.links.map((edge) => {
                const source = visibleGraph.nodes.find((node) => node.id === edge.source)
                const target = visibleGraph.nodes.find((node) => node.id === edge.target)
                if (!source || !target) return null
                const observed = portObservation(edge, visibleGraph.nodes, snapshot.core.interfaces, p.capabilities.inventory_targets)
                return <g key={edge.id} onClick={() => setModal({ kind: 'edge', edge })} style={{ cursor: 'pointer' }}>
                  <title>{edge.type + ' · ' + (edge.label || 'Relasi manual') + ' · ' + observed.status + ' · ' + observed.scope}</title>
                  <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={colors[observed.status] || colors.UNKNOWN} strokeWidth="3"/>
                  <text x={(source.x + target.x) / 2} y={(source.y + target.y) / 2 - 10} textAnchor="middle" fill="var(--bs-body-color)" fontSize="12">{edge.label || edge.type}{observed.status !== 'UNKNOWN' ? ' · port ' + observed.status : ''}</text>
                </g>
              })}
              {visibleNodes.map((node) => {
                const dim = query && !((node.name + ' ' + node.kind + ' ' + (node.group || '')).toLowerCase().includes(query.toLowerCase()))
                const nodeStatus = status(node)
                const services = nodeServices(node)
                const serviceText = services.length ? services.map((item) => '• ' + item.kind + ': ' + item.name + (item.info ? ' (' + item.info + ')' : '')).join('\n') : 'Belum ada layanan/workload yang terhubung di monitoring.'
                const tooltip = node.name + ' · ' + node.kind + ' · ' + nodeStatus + '\nLayanan & workload:\n' + serviceText
                return <g key={node.id} transform={'translate(' + node.x + ',' + node.y + ')'} opacity={dim ? 0.25 : 1} role="button" tabIndex={0} aria-label={'Perangkat ' + node.name + '. Arahkan kursor untuk layanan dan workload.'} style={{ cursor: canManage ? 'grab' : 'pointer' }} onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    setNodeId(node.id)
                    setModal({ kind: 'node', node })
                  }
                }} onPointerDown={(event) => {
                  event.stopPropagation()
                  setNodeId(node.id)
                  if (!canManage) return
                  const currentPoint = point(event)
                  drag.current = { id: node.id, type: 'node', dx: currentPoint.x - node.x, dy: currentPoint.y - node.y }
                  event.currentTarget.setPointerCapture(event.pointerId)
                }} onDoubleClick={() => setModal({ kind: 'node', node })}>
                  <title>{tooltip}</title>
                  <rect x="-100" y="-34" width="200" height="68" rx="10" fill="var(--bs-body-bg)" stroke={nodeId === node.id ? 'var(--bs-primary)' : colors[nodeStatus] || colors.UNKNOWN} strokeWidth={nodeId === node.id ? 3 : 2}/>
                  <circle cx="-79" cy="-9" r="5" fill={colors[nodeStatus] || colors.UNKNOWN}/>
                  <text x="-64" y="-5" fill="var(--bs-emphasis-color)" fontSize="13" fontWeight="600">{node.name.length > 22 ? node.name.slice(0, 21) + '…' : node.name}</text>
                  <text x="-80" y="18" fill="var(--bs-secondary-color)" fontSize="11">{node.kind + ' · ' + nodeStatus}</text>
                </g>
              })}
            </svg>
          </div>
          <p className="text-muted small mt-2">Geser node untuk mengatur posisi; geser area kosong untuk pan. Hover menampilkan service, VM/LXC, dan container yang terhubung ke collector. Klik ganda/Enter untuk detail. Warna mengikuti status collector; garis manual bukan bukti jalur fisik.</p>
          {selectedNode && <div className="border rounded p-3">
            <div className="d-flex flex-wrap align-items-center gap-2"><strong>{selectedNode.name}</strong><Badge status={status(selectedNode)}/><small>{selectedNode.collector || 'Collector tidak tersedia'}</small><button className="btn btn-sm btn-outline-secondary ms-md-auto" onClick={() => setModal({ kind: 'node', node: selectedNode })}>Detail / Edit label</button>
              {selectedNode.device_id && <Link className="btn btn-sm btn-outline-primary" to={selectedNode.device_id.startsWith('inv_') ? '/management?device=' + selectedNode.device_id : '/devices/' + selectedNode.device_id}>Detail perangkat</Link>}
              {selectedNode.resource_id && <Link className="btn btn-sm btn-outline-primary" to={'/virtualization?resource=' + encodeURIComponent(selectedNode.resource_id)}>Detail node</Link>}
              {canManage && <button className="btn btn-sm btn-outline-danger" onClick={() => setModal({ kind: 'delete-node' })}>Hapus node</button>}
            </div>
            <div className="small mt-3"><strong>Layanan & workload</strong>
              {nodeServices(selectedNode).length
                ? <ul className="mb-0 mt-1">{nodeServices(selectedNode).map((item) => <li key={item.kind + '-' + item.name}>{item.kind}: {item.name}{item.info ? ' · ' + item.info : ''} · {item.status}</li>)}</ul>
                : <p className="text-muted mb-0 mt-1">Belum ada service/workload yang dapat dikaitkan dari monitoring aktual.</p>}
            </div>
          </div>}
        </>}
    </Panel>

    {['new', 'rename'].includes(modal?.kind) && <NameForm initial={modal.kind === 'rename' ? graph.name : ''} title={modal.kind === 'new' ? 'Topologi baru' : 'Ubah nama topologi'} onClose={() => setModal(null)} onSave={(name) => {
      if (modal.kind === 'new') {
        setSelected('__new__')
        setDraft({ name, nodes: [], links: [] })
        setDirty(true)
      } else change({ ...graph, name })
      setModal(null)
    }}/>}
    {modal?.kind === 'observed' && <ConnectedDeviceModal devices={connectedDevices.filter((device) => !visibleGraph.nodes.some((node) => node.device_id === device.device_id))} onClose={() => setModal(null)} onSelect={insert}/>}
    {modal?.kind === 'node' && <NodeForm node={modal.node} canManage={canManage} onClose={() => setModal(null)} onSave={(updated) => {
      change({ ...graph, nodes: graph.nodes.map((node) => node.id === updated.id ? updated : node) })
      setModal(null)
    }}/>}
    {modal?.kind === 'edge' && <EdgeForm edge={modal.edge} nodes={visibleGraph.nodes} canManage={canManage} onClose={() => setModal(null)} onSave={(edge) => {
      change({ ...graph, links: modal.edge ? graph.links.map((link) => link.id === edge.id ? edge : link) : [...graph.links, edge] })
      setModal(null)
    }} onDelete={() => {
      change({ ...graph, links: graph.links.filter((link) => link.id !== modal.edge.id) })
      setModal(null)
    }}/>}
    {modal?.kind === 'delete' && <Confirmation title="Hapus topologi?" danger onClose={() => setModal(null)} onConfirm={removeGraph} busy={busy}><p>{saved?.name} akan dihapus dari penyimpanan NMS.</p><Feedback error={error}/></Confirmation>}
    {modal?.kind === 'delete-node' && <Confirmation title="Hapus perangkat dan relasinya?" danger onClose={() => setModal(null)} onConfirm={deleteNode}><p>{selectedNode?.name}. Simpan topologi setelah perubahan.</p></Confirmation>}
    {modal?.kind === 'switch' && <Confirmation title="Buang perubahan yang belum disimpan?" onClose={() => setModal(null)} onConfirm={() => {
      setSelected(modal.id)
      setDraft(null)
      setDirty(false)
      setNodeId('')
      setModal(null)
    }}><p>Topologi saat ini memiliki perubahan yang belum disimpan ke server.</p></Confirmation>}
  </>
}

function NameForm({ title, initial, onSave, onClose }) {
  const [name, setName] = useState(initial)
  return <Modal title={title} onClose={onClose} footer={<button className="btn btn-primary" form="topology-name">Lanjut</button>}>
    <form id="topology-name" onSubmit={(event) => {
      event.preventDefault()
      if (name.trim()) onSave(name.trim())
    }}>
      <label className="form-label" htmlFor="topology-name-input">Nama topologi</label>
      <input id="topology-name-input" className="form-control" required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} autoFocus/>
    </form>
  </Modal>
}

function ConnectedDeviceModal({ devices, onClose, onSelect }) {
  return <Modal title="Tambah perangkat terhubung" onClose={onClose} footer={<button className="btn btn-secondary" onClick={onClose}>Tutup</button>}>
    <p className="small text-muted">Hanya perangkat yang mempunyai sampel collector terbaru berstatus UP dapat ditambahkan. Layanan, VM, LXC, dan container tidak menjadi node.</p>
    {!devices.length
      ? <EmptyState action={false} icon="router" title="Tidak ada perangkat baru yang siap" description="Perangkat mungkin sudah ada pada topologi atau belum memiliki sampel UP. Daftarkan dan uji lebih dahulu melalui Device Connections & Management."/>
      : <div className="list-group">{devices.map((device) => <button key={device.id} className="list-group-item list-group-item-action d-flex align-items-center gap-3 text-start" onClick={() => onSelect(device)}>
        <Badge status="UP">UP</Badge><span><strong>{device.name}</strong><small className="d-block text-muted">{device.kind} · {device.host} · {device.collector}</small></span>
      </button>)}</div>}
  </Modal>
}

function NodeForm({ node, canManage, onSave, onClose }) {
  const [form, setForm] = useState(node)
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  return <Modal title="Detail perangkat" onClose={onClose} footer={<><button className="btn btn-secondary" onClick={onClose}>Tutup</button>{canManage && <button className="btn btn-primary" form="node-form">Simpan detail</button>}</>}>
    <form id="node-form" onSubmit={(event) => {
      event.preventDefault()
      onSave(form)
    }}>
      <fieldset disabled={!canManage}><div className="row g-3">
        <div className="col-md-6"><label className="form-label" htmlFor="node-name">Label pada topologi</label><input id="node-name" className="form-control" required maxLength={80} value={form.name} onChange={(event) => set('name', event.target.value)}/></div>
        <div className="col-md-6"><label className="form-label" htmlFor="node-kind">Jenis perangkat</label><select id="node-kind" className="form-select" value={form.kind} disabled>{deviceKinds.map((kind) => <option key={kind}>{kind}</option>)}</select></div>
        {['group', 'x', 'y'].map((key) => <div className="col-md-6" key={key}><label className="form-label" htmlFor={'node-' + key}>{({ group: 'Grup', x: 'Posisi X', y: 'Posisi Y' })[key]}</label><input id={'node-' + key} className="form-control" type={key === 'group' ? 'text' : 'number'} min={-5000} max={5000} maxLength={80} value={form[key] ?? ''} onChange={(event) => set(key, key === 'group' ? event.target.value : Number(event.target.value))}/></div>)}
      </div></fieldset>
    </form>
    <div className="alert alert-info small mt-3 mb-0">Status koneksi dibaca dari cache monitoring bersama. Form ini hanya mengubah label, grup, dan posisi perangkat di topologi.</div>
  </Modal>
}

function EdgeForm({ edge, nodes, canManage, onSave, onDelete, onClose }) {
  const [form, setForm] = useState(() => edge || { id: id('e_'), source: nodes[0]?.id || '', target: nodes[1]?.id || '', type: 'Ethernet', label: '', source_port: '', target_port: '', vlan: 0, speed_mbps: 0, evidence: 'manual' })
  const [error, setError] = useState('')
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  return <Modal title="Relasi perangkat" onClose={onClose} footer={<><button className="btn btn-secondary" onClick={onClose}>Tutup</button>{canManage && edge && <button className="btn btn-outline-danger" onClick={onDelete}>Hapus relasi</button>}{canManage && <button form="edge-form" className="btn btn-primary">Terapkan relasi</button>}</>}>
    <form id="edge-form" onSubmit={(event) => {
      event.preventDefault()
      if (form.source === form.target) {
        setError('Pilih dua perangkat berbeda.')
        return
      }
      onSave(form)
    }}>
      <fieldset disabled={!canManage}>{['source', 'target'].map((key) => <div className="mb-3" key={key}>
        <label className="form-label" htmlFor={'edge-' + key}>{key === 'source' ? 'Perangkat asal' : 'Perangkat tujuan'}</label>
        <select id={'edge-' + key} className="form-select" value={form[key]} onChange={(event) => set(key, event.target.value)}>{nodes.map((node) => <option value={node.id} key={node.id}>{node.name}</option>)}</select>
      </div>)}
        <label className="form-label" htmlFor="edge-type">Jenis koneksi / relasi</label>
        <select id="edge-type" className="form-select mb-3" value={form.type} onChange={(event) => set('type', event.target.value)}>{['Ethernet', 'Fiber', 'Wi-Fi', 'VLAN', 'VPN', 'Physical', 'Logical', 'Trunk', 'Access', 'LAG/LACP', 'Routing', 'Other'].map((value) => <option key={value}>{value}</option>)}</select>
        <label className="form-label" htmlFor="edge-label">Label koneksi</label>
        <input id="edge-label" maxLength={80} className="form-control" value={form.label} onChange={(event) => set('label', event.target.value)}/>
        <div className="row g-3 mt-1">{[['source_port', 'Port sumber'], ['target_port', 'Port tujuan'], ['vlan', 'VLAN (0 = belum diketahui)'], ['speed_mbps', 'Kecepatan Mbps (0 = belum diketahui)']].map(([key, label]) => <div className="col-md-6" key={key}>
          <label className="form-label" htmlFor={'edge-' + key}>{label}</label>
          <input id={'edge-' + key} className="form-control" type={['vlan', 'speed_mbps'].includes(key) ? 'number' : 'text'} min={0} max={key === 'vlan' ? 4094 : 1000000} maxLength={80} value={form[key] ?? (['vlan', 'speed_mbps'].includes(key) ? 0 : '')} onChange={(event) => set(key, ['vlan', 'speed_mbps'].includes(key) ? Number(event.target.value) : event.target.value)}/>
        </div>)}</div>
        <p className="small text-muted mt-3">Relasi manual. Status fisik hanya dapat dipastikan dari collector port yang sesuai; ping tidak membuktikan kabel.</p>
      </fieldset>
      {error && <div className="text-danger mt-2" role="alert">{error}</div>}
    </form>
  </Modal>
}
