import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { portObservation, connectedTopologyDevices, linkedLegacyServices } from '../data/topologyModel'
import { usePlatform } from '../data/platformContext'
import { useMonitoring } from '../data/useMonitoring'
import { Badge, EmptyState, Panel, formatTime, percentage } from '../components/ui'
import { Modal, Confirmation } from '../components/Modal'
import { AccessNote, Feedback, Loading, Launcher } from '../components/PlatformUI'
import { topologySignature, verifiedLink } from '../data/topologyVerification'
import { TopologyContextMenu } from '../components/TopologyContextMenu'

import { useTopologyWorkspace } from '../data/topologyWorkspaceContext'
import { networkIcons, iconURL } from '../data/networkIcons'
import { exportDrawio, importDrawio } from '../data/drawio'
const TopologyCanvas = lazy(() => import('../components/TopologyCanvas'))
const id = (prefix) => prefix + crypto.randomUUID().replaceAll('-', '').slice(0, 12)
const deviceKinds = [...new Set(networkIcons.map((item) => item.kind)), 'application', 'other']

export function TopologyEditor() {
  const p = usePlatform()
  const canManage = !p.error && (p.canManage || p.capabilities.permissions?.includes('topology.manage'))
  const { snapshot, observedDevices } = useMonitoring()
  const [management, setManagement] = useState(null)
  const [managementError, setManagementError] = useState(null)
  const [managementLoading, setManagementLoading] = useState(true)
  const { workspace, document: doc, selected, documents, storageError, limitError } = useTopologyWorkspace()
  const graph = doc?.graph
  const dirty = doc?.dirty
  const view = doc?.view || { x: 0, y: 0, zoom: 1 }
  const setView = workspace.setView
  const fileInput = useRef(null)
  const [nodeId, setNodeId] = useState('')
  const [query, setQuery] = useState('')
  const [modal, setModal] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [message, setMessage] = useState('')
  const [importError, setImportError] = useState('')
  const [verification,setVerification]=useState(null)
  const [verifying,setVerifying]=useState(false)
  const [context,setContext]=useState(null)
  const [clock,setClock]=useState(()=>Date.now()/1000)
  const verificationFlight=useRef(false)
  const display=doc?.display||{}
  useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()/1000),1000);return()=>clearInterval(timer)},[])
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

  const saved = p.topologies.find((item) => item.id === doc?.serverId)
  const inventoryStates = management?.inventory || []
  const resources = snapshot.core.hosts.filter((host) => host.sourceId === 'proxmox_resources')
  const connectedDevices = connectedTopologyDevices({ inventory: p.inventory, inventoryStates, observedDevices, now: p.now })
  const visibleGraph = { nodes: graph?.nodes || [], links: graph?.links || [] }
  const selectedNode = visibleGraph.nodes.find((node) => node.id === nodeId)
  const signature=topologySignature(graph)
  const verificationCurrent=verification?.document===selected&&verification.signature===signature
  const report=verificationCurrent?verification.report:null
  const verify=async()=>{
    if(!graph||verificationFlight.current)return
    verificationFlight.current=true;setVerifying(true);setError(null)
    try {
      const value=await p.client.platform('topology-verify',{body:{value:graph}})
      setVerification({document:selected,signature,report:value})
    } catch(e){setError(e.code||'unavailable');setVerification(null)}
    finally{verificationFlight.current=false;setVerifying(false)}
  }
  const linkReport=(edge)=>verifiedLink(edge,report,signature,graph,Math.max(p.now,clock))

  const change = (next) => { workspace.change(next); setError(null); setMessage('') }
  const switchTo = (value) => { workspace.select(value); setNodeId('');setContext(null) }
  const status = (node) => {
    if (node.device_id) {
      const item = p.inventory.find((device) => device.id === node.device_id)
      if (item) {
        if (!item.enabled) return 'UNKNOWN'
        const state = inventoryStates.find((row) => row.id === item.id)
        if (state?.health?.stale || state?.health?.sample_epoch+Math.max(120,item.interval*3)<p.now) return 'UNKNOWN'
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
    const result = await workspace.save()
    if (result) setMessage('Topologi tersimpan di server.')
  }
  const removeGraph = async () => {
    if (!doc?.serverId) { workspace.forget(); setModal(null); return }
    setBusy(true)
    try {
      await p.mutate('topologies/' + doc.serverId + '/delete', { revision: doc.revision })
      workspace.forget(); setModal(null); setMessage('Topologi dihapus.'); setError(null)
    } catch (e) { setError(e.code) } finally { setBusy(false) }
  }
  const insertSymbol = (symbol, position) => {
    const item = networkIcons.find((entry) => entry.id === symbol)
    if (!item || !graph || graph.nodes.length >= 100) return
    const node = { id: id('n_'), name: item.name, kind: item.kind, icon: item.id, x: position?.x ?? 160 + graph.nodes.length % 4 * 200, y: position?.y ?? 100 + Math.floor(graph.nodes.length / 4) * 120, width: 72, height: 64, group: '', collector: '', resource_id: '', service_id: '', device_id: '' }
    change({ ...graph, nodes: [...graph.nodes, node] }); setNodeId(node.id)
  }
  const importFile = async (event) => {
    const file = event.target.files[0]; event.target.value = ''
    if (!file) return
    setImportError(''); setMessage('')
    try {
      if (file.size > 2 * 1024 * 1024) throw new Error('Berkas melebihi 2 MB.')
      const value = importDrawio(await file.text())
      // Bind imported references only when they are known in this workspace.
      for (const node of value.nodes) {
        if (!p.inventory.some((item) => item.id === node.device_id) && !observedDevices.some((item) => item.id === node.device_id)) node.device_id = ''
        if (node.collector && !snapshot.checks.some((item) => item.id === node.collector)) node.collector = ''
      }
      if (workspace.create(value.name) === false) throw new Error('Maksimal 20 draf di browser. Hapus draf yang tidak diperlukan.'); workspace.change(value); setMessage('Diagram diimpor sebagai draf baru. Simpan untuk menyinkronkan ke server.')
    } catch (e) { setError(null); setImportError(e.message) }
  }
  const exportFile = () => {
    const url = URL.createObjectURL(new Blob([exportDrawio(graph)], { type: 'application/xml' }))
    const anchor = window.document.createElement('a'); anchor.href = url; anchor.download = graph.name.replace(/[^a-zA-Z0-9_-]/g, '_') + '.drawio'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  const insert = (device) => {
    if (!graph || graph.nodes.length >= 100) return
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

  const contextNode=context?.kind==='node'?graph?.nodes.find((node)=>node.id===context.id):null
  const contextEdge=context?.kind==='edge'?graph?.links.find((edge)=>edge.id===context.id):null
  const contextDevice=p.inventory.find((device)=>device.id===contextNode?.device_id)
  const contextState=inventoryStates.find((row)=>row.id===contextDevice?.id)
  const contextCheck=snapshot.checks.find((row)=>row.id===(contextState?.monitor_target||contextNode?.collector))
  const contextObserved=observedDevices.find((device)=>device.host===contextDevice?.host||device.id===contextNode?.device_id)
  const contextCollectors=new Set([contextNode?.collector,contextState?.monitor_target,...(contextObserved?.collectors||[])])
  const contextResource=snapshot.checks.find((row)=>contextCollectors.has(row.id)&&!row.stale&&(row.cpu!=null||row.memory!=null))
  const contextSample=contextState?.health?.sample_epoch||contextCheck?.sampled
  const contextMetrics={cpu_percent:contextResource?.cpu,memory_percent:contextResource?.memory,...contextState?.telemetry}
  const contextInterfaces=contextMetrics.interfaces?.length?contextMetrics.interfaces:snapshot.core.interfaces.filter((port)=>contextCollectors.has(port.sourceId)&&!port.stale).map((port)=>({...port,rx_bps:snapshot.core.traffic.find((traffic)=>traffic.id===port.id&&!traffic.stale)?.rx,tx_bps:snapshot.core.traffic.find((traffic)=>traffic.id===port.id&&!traffic.stale)?.tx}))
  const contextServices=p.integrations.filter((service)=>{try{return service.enabled&&new URL(service.url).hostname===contextDevice?.host}catch{return false}})
  const contextLink=contextEdge?report?.links.find((row)=>row.id===contextEdge.id):null
  return <div className={`nms-topology-editor ${display.expanded?'nms-topology-expanded':''}`}>
    <AccessNote canManage={canManage} />
    <Feedback error={error || doc?.error || p.error || managementError} message={message} />
    {importError && <div className="alert alert-danger" role="alert">{importError}</div>}
    {storageError && <div className="alert alert-warning">Penyimpanan draf di browser tidak tersedia. Simpan ke server sebelum meninggalkan halaman.</div>}
    {limitError && <div className="alert alert-warning">Maksimal 20 draf di browser. Hapus draf yang tidak diperlukan sebelum membuat topologi baru.</div>}
    <Loading loading={p.loading || managementLoading} />
    {doc?.error === 'revision_conflict' && <div className="alert alert-warning">Topologi di server berubah. Ekspor draf untuk menyimpan salinan, lalu <button className="btn btn-sm btn-outline-secondary" onClick={workspace.discard}>Muat versi server</button>.</div>}
    <Panel title="Editor Topologi Jaringan" subtitle="Susun perangkat dan layanan dengan maxGraph. Impor dan ekspor format draw.io tersedia." action={<div className="d-flex gap-2"><button className="btn btn-sm btn-outline-primary" disabled={!canManage} onClick={() => setModal({ kind: 'new' })}>Topologi baru</button><button className="btn btn-sm btn-primary" disabled={!canManage || !graph || (!dirty && !doc?.pending) || doc?.saving} onClick={save}>{doc?.saving ? 'Menyimpan…' : doc?.pending ? 'Coba simpan lagi' : 'Simpan topologi'}</button></div>}>
      <div className="d-flex flex-wrap gap-2 align-items-center mb-3">
        <select className="form-select nms-topology-picker" aria-label="Pilih topologi" value={selected} onChange={(event) => switchTo(event.target.value)}>
          {!selected && <option value="">Pilih topologi</option>}
          {Object.entries(documents).map(([key, value]) => <option key={key} value={key}>{value.graph.name}{value.dirty ? ' · draf' : ''}</option>)}
          {p.topologies.filter((item) => !Object.values(documents).some((value) => value.serverId === item.id)).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
        {graph && <Badge status={dirty ? 'DEGRADED' : 'UP'}>{doc.saving ? 'Menyimpan ke server' : dirty ? 'Draf tersimpan di browser' : 'Tersimpan di server'}</Badge>}
        <button className="btn btn-sm btn-outline-secondary ms-md-auto" disabled={!canManage} onClick={() => fileInput.current.click()}>Impor .drawio</button>
        <input ref={fileInput} type="file" accept=".drawio,.xml" className="d-none" aria-label="Berkas draw.io" onChange={importFile}/>
        <button className="btn btn-sm btn-outline-secondary" disabled={!graph} onClick={exportFile}>Ekspor .drawio</button>
        <button className="btn btn-sm btn-outline-secondary" aria-pressed={Boolean(display.expanded)} onClick={()=>workspace.setDisplay({expanded:!display.expanded})}>{display.expanded?'Kembali ke halaman':'Perluas editor'}</button>
      </div>
      {!graph ? <EmptyState action={false} icon="diagram-3" title="Belum ada topologi" description="Buat diagram baru atau impor berkas draw.io. Draf dipulihkan saat navigasi dan refresh."/> : <>
        <div className="d-flex flex-wrap gap-2 mb-3">
          <button className="btn btn-sm btn-primary" disabled={verifying||!graph.nodes.length} onClick={verify}>{verifying?'Memverifikasi…':'Verify Topology'}</button>
          <button className="btn btn-sm btn-outline-secondary" aria-pressed={!display.paletteHidden} onClick={()=>workspace.setDisplay({paletteHidden:!display.paletteHidden})}>{display.paletteHidden?'Tampilkan pustaka':'Sembunyikan pustaka'}</button>
          <button className="btn btn-sm btn-outline-secondary" disabled={!canManage || !connectedDevices.length || graph.nodes.length >= 100} onClick={() => setModal({ kind: 'observed' })}>Tambah dari monitoring</button>
          <button className="btn btn-sm btn-outline-secondary" disabled={!canManage || graph.nodes.length < 2 || graph.links.length >= 200} onClick={() => setModal({ kind: 'edge' })}>Hubungkan node</button>
          <Link className="btn btn-sm btn-outline-secondary" to="/management">Kelola perangkat</Link>
          <button className="btn btn-sm btn-outline-secondary" disabled={!canManage} onClick={() => setModal({ kind: 'rename' })}>Ubah nama</button>
          <button className="btn btn-sm btn-outline-danger" disabled={!canManage || doc.saving} onClick={() => setModal({ kind: 'delete' })}>Hapus topologi</button>
          <div className="btn-group ms-md-auto">
            <button className="btn btn-sm btn-outline-secondary" aria-label="Perkecil canvas" onClick={() => setView((current) => ({ ...current, zoom: Math.max(.1, current.zoom / 1.25) }))}>−</button>
            <button className="btn btn-sm btn-outline-secondary" onClick={() => setView({ x: 0, y: 0, zoom: 1 })}>{Math.round(view.zoom * 100)}% · Atur ulang</button>
            <button className="btn btn-sm btn-outline-secondary" aria-label="Perbesar canvas" onClick={() => setView((current) => ({ ...current, zoom: Math.min(4, current.zoom * 1.25) }))}>+</button>
          </div>
        </div>
        <div className={`nms-topology-workspace ${display.paletteHidden?'nms-topology-no-palette':''}`}>
          {!display.paletteHidden&&
          <aside className="nms-topology-palette" aria-label="Pustaka ikon perangkat">
            <label htmlFor="topology-symbol-search" className="form-label small fw-semibold">Pustaka perangkat</label>
            <input id="topology-symbol-search" className="form-control form-control-sm mb-2" placeholder="Cari ikon…" value={query} onChange={(event) => setQuery(event.target.value)}/>
            <div className="nms-topology-symbols">{networkIcons.filter((item) => (item.name + ' ' + item.kind).toLowerCase().includes(query.toLowerCase())).map((item) => <button key={item.id} draggable={canManage} disabled={!canManage || graph.nodes.length >= 100} className="btn btn-sm btn-light border text-start" onDragStart={(event) => event.dataTransfer.setData('application/theaz-device', item.id)} onClick={() => insertSymbol(item.id)}><img src={iconURL(item.id)} alt="" width="28" height="28"/><span>{item.name}</span></button>)}</div>
          </aside>}
          <Suspense fallback={<p>Memuat canvas…</p>}><TopologyCanvas key={selected} graph={graph} view={view} canManage={canManage} onChange={change} onUndo={workspace.undo} onRedo={workspace.redo} onView={setView} onSelect={setNodeId} onDrop={insertSymbol} onContext={setContext} status={status} animateEdge={(edge)=>Boolean(linkReport(edge))&&[edge.source,edge.target].every((id)=>status(graph.nodes.find((node)=>node.id===id))==='UP')&&portObservation(edge,graph.nodes,snapshot.core.interfaces,p.capabilities.inventory_targets).status!=='DOWN'} edgeStatus={(edge) => linkReport(edge)?'UP':portObservation(edge, graph.nodes, snapshot.core.interfaces, p.capabilities.inventory_targets).status} tooltip={(node) => node.name + ' · ' + status(node) + '\n' + (node.group ? 'Grup: ' + node.group + '\n' : '') + nodeServices(node).map((item) => item.kind + ': ' + item.name + ' · ' + item.status).join('\n')} edgeTooltip={(edge) => (edge.label || edge.type || '') + ' · ' + (report?.links.find((row)=>row.id===edge.id)?.message||'Relasi belum diverifikasi')} onEdit={(kind, value) => { const item = (kind === 'node' ? graph.nodes : graph.links).find((entry) => entry.id === value); if (item) setModal({ kind, [kind]: item }) }}/></Suspense>
        </div>
        <p className="small text-muted mt-2 mb-0">Seret ikon ke canvas atau klik untuk menambah. Seret pegangan koneksi antarnode; klik ganda untuk detail. Seret area kosong untuk pan, Ctrl + roda mouse untuk zoom. Maksimal 100 node dan 200 koneksi. Ikon manual tidak memicu konfigurasi atau pemeriksaan jaringan.</p>
        {verification&&!verificationCurrent&&<div className="alert alert-warning mt-3">Relasi atau perangkat berubah. Jalankan Verify Topology kembali sebelum animasi ditampilkan.</div>}
        {report&&<TopologyVerificationResults report={report} now={Math.max(p.now,clock)}/>}
        {selectedNode && <div className="border rounded p-3 mt-3"><div className="d-flex flex-wrap gap-2 align-items-center"><strong>{selectedNode.name}</strong><Badge status={status(selectedNode)}>{status(selectedNode)}</Badge><button className="btn btn-sm btn-outline-primary ms-auto" onClick={() => setModal({ kind: 'node', node: selectedNode })}>Detail node</button>{canManage && <button className="btn btn-sm btn-outline-danger" onClick={() => setModal({ kind: 'delete-node' })}>Hapus node</button>}</div><p className="small text-muted mb-0 mt-2">{nodeServices(selectedNode).map((item) => item.kind + ': ' + item.name + ' · ' + item.status).join(' / ') || 'Belum ada layanan terpantau yang terkait.'}</p></div>}
      </>}
    </Panel>

    {['new', 'rename'].includes(modal?.kind) && <NameForm initial={modal.kind === 'rename' ? graph.name : ''} title={modal.kind === 'new' ? 'Topologi baru' : 'Ubah nama topologi'} onClose={() => setModal(null)} onSave={(name) => {
      if (modal.kind === 'new') {
        workspace.create(name)
      } else change({ ...graph, name })
      setModal(null)
    }}/>}
    {modal?.kind === 'observed' && <ConnectedDeviceModal devices={connectedDevices.filter((device) => !visibleGraph.nodes.some((node) => node.device_id === device.device_id))} onClose={() => setModal(null)} onSelect={insert}/>}
    {modal?.kind === 'node' && <NodeForm node={modal.node} inventory={p.inventory} inventoryTargets={p.capabilities.inventory_targets} canManage={canManage} onClose={() => setModal(null)} onSave={(updated) => {
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

    {context&&(contextNode||contextEdge)&&<TopologyContextMenu position={context} onClose={()=>setContext(null)}>
      {contextNode?<><strong className="d-block mb-2">{contextNode.name}</strong><Badge status={status(contextNode)}/><dl className="nms-topology-details mt-2"><dt>IP manajemen</dt><dd>{contextDevice?.host||'Belum ditautkan'}</dd><dt>Vendor / model</dt><dd>{[contextDevice?.vendor,contextDevice?.model].filter(Boolean).join(' / ')||'Belum diketahui'}</dd><dt>Integrasi</dt><dd>{contextDevice?.monitor_method||contextNode.collector||'Inventaris manual'}</dd><dt>Pembaruan</dt><dd>{formatTime(contextSample)}</dd>{status(contextNode)==='UP'&&<>{contextMetrics.cpu_percent!=null&&<><dt>CPU</dt><dd>{percentage(contextMetrics.cpu_percent)}</dd></>}{contextMetrics.memory_percent!=null&&<><dt>RAM</dt><dd>{percentage(contextMetrics.memory_percent)}</dd></>}</>}</dl>
      {contextInterfaces.length>0&&status(contextNode)==='UP'&&<details><summary>{contextInterfaces.length} interface terpantau</summary>{contextInterfaces.map((port)=><div className="small border-bottom py-1" key={port.name}>{port.name} · {port.status||(port.running===true||port.running==='true'?'UP':'Belum diketahui')}{(port.rx_bps??port.rx_bits_per_second)!=null&&<div>RX {port.rx_bps??port.rx_bits_per_second} bit/s · TX {port.tx_bps??port.tx_bits_per_second??'—'} bit/s</div>}</div>)}</details>}
      <div className="d-grid gap-2 mt-3"><button className="btn btn-sm btn-outline-primary" onClick={()=>{setModal({kind:'node',node:contextNode});setContext(null)}}>Detail / tautkan perangkat</button>{contextDevice&&<Link className="btn btn-sm btn-outline-secondary" to="/management">Kelola monitoring perangkat</Link>}{contextServices.map((service)=><Launcher small key={service.id} service={service}/>)}{canManage&&<button className="btn btn-sm btn-outline-danger" onClick={()=>{setNodeId(contextNode.id);setModal({kind:'delete-node'});setContext(null)}}>Hapus node</button>}</div></>:<><strong>{contextEdge.label||contextEdge.type}</strong><p className="small mt-2">{contextLink?.message||'Koneksi belum diverifikasi. Jalankan Verify Topology.'}</p><Badge status={linkReport(contextEdge)?'UP':'UNKNOWN'}>{linkReport(contextEdge)?'Terverifikasi':'Belum terbukti / kedaluwarsa'}</Badge>{contextLink?.evidence?.map((item)=><p className="small mt-2" key={item.collector}>{item.protocol} · {item.host} / {item.port} → {item.remote_host}<br/>{formatTime(item.sampled)}</p>)}{linkReport(contextEdge)&&contextLink.traffic&&Object.keys(contextLink.traffic).length>0&&<dl className="nms-topology-details mt-2">{Object.entries(contextLink.traffic).map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>}<p className="small text-muted">Counter/rate berasal dari interface lokal; bukan pengukuran trafik khusus pasangan perangkat ini.</p><button className="btn btn-sm btn-outline-primary" onClick={()=>{setModal({kind:'edge',edge:contextEdge});setContext(null)}}>Detail koneksi</button></>}
    </TopologyContextMenu>}
  </div>
}

function TopologyVerificationResults({report,now}) {
  const expired=report.links.some((row)=>row.verified&&row.expires_at<=now)
  return <details className="nms-topology-verification border rounded p-3 mt-3" open><summary className="fw-semibold">{report.valid&&!expired?'Topologi terverifikasi':'Topologi perlu pemeriksaan'} · {report.summary.recognized}/{report.summary.nodes} node dikenali · {report.summary.verified} koneksi terbukti · {report.summary.unproven} belum terbukti</summary><p className="small text-muted my-2">Pemeriksaan {formatTime(report.checked_at)}. Animasi hanya ilustrasi hubungan LLDP/CDP yang masih berlaku, bukan paket hasil packet capture. Bukti kedaluwarsa otomatis menghentikan animasi; jalankan verifikasi kembali.</p><div className="table-responsive"><table className="table table-sm small"><thead><tr><th>Node / koneksi</th><th>Hasil</th><th>Informasi / data yang diperlukan</th></tr></thead><tbody>{report.nodes.map((row)=><tr key={'n'+row.id}><td>{row.name}<br/>{row.host}</td><td>{row.ready?'Dikenali dan siap':row.recognized?'Dikenali':'Belum dikenali'}</td><td>{row.issues.join(' ')||`${row.method} · ${formatTime(row.sampled)}`}</td></tr>)}{report.links.map((row)=><tr key={'e'+row.id}><td>{row.id}</td><td>{row.verified?(row.expires_at>now?'Terverifikasi':'Bukti kedaluwarsa'):row.status==='MISMATCH'?'Tidak sesuai':'Belum terbukti'}</td><td>{row.message}</td></tr>)}</tbody></table></div></details>
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
    <p className="small text-muted">Hanya perangkat yang mempunyai sampel collector terbaru berstatus UP dapat ditambahkan. Gunakan pustaka perangkat untuk menambahkan node manual, termasuk VM dan container.</p>
    {!devices.length
      ? <EmptyState action={false} icon="router" title="Tidak ada perangkat baru yang siap" description="Perangkat mungkin sudah ada pada topologi atau belum memiliki sampel UP. Daftarkan dan uji lebih dahulu melalui Manajemen Perangkat."/>
      : <div className="list-group">{devices.map((device) => <button key={device.id} className="list-group-item list-group-item-action d-flex align-items-center gap-3 text-start" onClick={() => onSelect(device)}>
        <Badge status="UP">UP</Badge><span><strong>{device.name}</strong><small className="d-block text-muted">{device.kind} · {device.host} · {device.collector}</small></span>
      </button>)}</div>}
  </Modal>
}

function NodeForm({ node, inventory, inventoryTargets, canManage, onSave, onClose }) {
  const [form, setForm] = useState(node)
  const set = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  return <Modal title="Detail perangkat" onClose={onClose} footer={<><button className="btn btn-secondary" onClick={onClose}>Tutup</button>{canManage && <button className="btn btn-primary" form="node-form">Simpan detail</button>}</>}>
    <form id="node-form" onSubmit={(event) => {
      event.preventDefault()
      onSave(form)
    }}>
      <fieldset disabled={!canManage}><div className="row g-3">
        <div className="col-12"><label className="form-label" htmlFor="node-device">Perangkat inventaris</label><select id="node-device" className="form-select" value={form.device_id||''} onChange={(event)=>setForm((current)=>({...current,device_id:event.target.value,collector:inventoryTargets?.[event.target.value]||'',resource_id:''}))}><option value="">Simbol manual — belum terverifikasi</option>{inventory.map((item)=><option key={item.id} value={item.id}>{item.name} · {item.host}</option>)}</select></div>
        <div className="col-md-6"><label className="form-label" htmlFor="node-name">Label pada topologi</label><input id="node-name" className="form-control" required maxLength={80} value={form.name} onChange={(event) => set('name', event.target.value)}/></div>
        <div className="col-md-6"><label className="form-label" htmlFor="node-kind">Jenis perangkat</label><select id="node-kind" className="form-select" value={form.kind} disabled={Boolean(form.device_id || form.resource_id)} onChange={(event) => set('kind', event.target.value)}>{deviceKinds.map((kind) => <option key={kind}>{kind}</option>)}</select></div>
        <div className="col-md-6"><label className="form-label" htmlFor="node-icon">Ikon perangkat</label><select id="node-icon" className="form-select" value={form.icon || form.kind} onChange={(event) => set('icon', event.target.value)}>{networkIcons.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
        {['group', 'x', 'y'].map((key) => <div className="col-md-6" key={key}><label className="form-label" htmlFor={'node-' + key}>{({ group: 'Grup', x: 'Posisi X', y: 'Posisi Y' })[key]}</label><input id={'node-' + key} className="form-control" type={key === 'group' ? 'text' : 'number'} min={-5000} max={5000} maxLength={80} value={form[key] ?? ''} onChange={(event) => set(key, key === 'group' ? event.target.value : Number(event.target.value))}/></div>)}
      </div></fieldset>
    </form>
    <div className="alert alert-info small mt-3 mb-0">Status koneksi dibaca dari cache monitoring bersama. Perubahan hanya berlaku pada diagram. Node manual tetap UNKNOWN sampai dihubungkan dengan data monitoring.</div>
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
