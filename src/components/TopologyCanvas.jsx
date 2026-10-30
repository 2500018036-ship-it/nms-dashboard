import { useEffect, useRef } from 'react'
import { Graph, getDefaultPlugins, RubberBandHandler, InternalEvent, UndoManager, Point } from '@maxgraph/core'
import '@maxgraph/core/css/common.css'
import { iconURL } from '../data/networkIcons'

const colors = { UP: '#198754', DOWN: '#dc3545', DEGRADED: '#b77900', UNKNOWN: '#64748b', DISABLED: '#64748b' }
const clamp = (value, min = -5000, max = 5000) => Math.max(min, Math.min(max, Math.round(value)))
const uid = (prefix) => prefix + crypto.randomUUID().replaceAll('-', '').slice(0, 16)
const contentKey = ({name,nodes,links}) => JSON.stringify({name,nodes,links})

export default function TopologyCanvas(props) {
  const container = useRef(null); const engine = useRef(null); const latest = useRef(props)
  useEffect(() => { latest.current = props })
  useEffect(() => {
    const host = container.current
    const graph = new Graph(host, undefined, getDefaultPlugins().concat([RubberBandHandler]))
    const model = graph.getDataModel(); const parent = graph.getDefaultParent(); const undo = new UndoManager(100)
    const nodes = new Map(); const edges = new Map()
    let updating = false; let fingerprint = ''; let viewKey = ''; let frame = 0
    const overlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    overlay.setAttribute('class','nms-topology-packets'); overlay.setAttribute('aria-hidden','true'); host.appendChild(overlay)
    const packets = new Map()
    const drawPackets = () => {
      frame = 0
      const keep = new Set()
      for (const cell of graph.getChildEdges(parent)) {
        if (!latest.current.animateEdge?.(edges.get(cell.id))) continue
        const points = graph.view.getState(cell)?.absolutePoints?.filter(Boolean)
        if (!points || points.length < 2) continue
        const d = points.map((p,i)=>`${i?'L':'M'}${p.x},${p.y}`).join(' ')
        keep.add(cell.id)
        let item = packets.get(cell.id)
        if (!item) {
          const group = document.createElementNS(overlay.namespaceURI,'g'); const motions = []
          for (let i=0;i<2;i++) {
            const dot = document.createElementNS(overlay.namespaceURI,'circle'); dot.setAttribute('r','3'); dot.setAttribute('fill','#16a34a')
            const motion = document.createElementNS(overlay.namespaceURI,'animateMotion'); motion.setAttribute('dur','3s'); motion.setAttribute('repeatCount','indefinite'); motion.setAttribute('begin',`${-i*1.5}s`)
            dot.appendChild(motion); group.appendChild(dot); motions.push(motion)
          }
          overlay.appendChild(group); item={group,motions,d:''}; packets.set(cell.id,item)
        }
        if (item.d!==d) { item.motions.forEach((motion)=>motion.setAttribute('path',d)); item.d=d }
      }
      for (const [key,item] of packets) if(!keep.has(key)) { item.group.remove(); packets.delete(key) }
    }
    const queuePackets = () => { if (!frame) frame=requestAnimationFrame(drawPackets) }
    const visibility = () => { overlay.style.display=document.hidden?'none':''; queuePackets() }
    document.addEventListener('visibilitychange',visibility)
    const expiryTimer=setInterval(queuePackets,1000)
    graph.setConnectable(true); graph.setPanning(true); graph.setHtmlLabels(false)
    graph.setAllowDanglingEdges(false); graph.setAllowLoops(false); graph.setCellsEditable(false); graph.setCellsCloneable(false); graph.setTooltips(true)
    const validateEdge = graph.getEdgeValidationError.bind(graph)
    graph.getEdgeValidationError = (edge, source, target) => graph.getChildEdges(parent).length >= 200 && !graph.getChildEdges(parent).includes(edge) ? 'Maksimal 200 koneksi.' : validateEdge(edge, source, target)
    graph.getPlugin('PanningHandler').useLeftButtonForPanning = true
    graph.getPlugin('PanningHandler').ignoreCell = false
    graph.getPlugin('PopupMenuHandler')?.setEnabled(false)
    const edgeStyle = graph.getStylesheet().getDefaultEdgeStyle()
    Object.assign(edgeStyle, { edgeStyle: 'orthogonalEdgeStyle', endArrow: 'none', rounded: true, strokeWidth: 2, strokeColor: colors.UNKNOWN, fontColor: '#334155', labelBackgroundColor: '#ffffff' })
    graph.getTooltipForCell = (cell) => cell.isVertex() ? latest.current.tooltip(nodes.get(cell.id) || {}) : latest.current.edgeTooltip(edges.get(cell.id) || {})
    const emit = () => {
      if (updating) return
      const previous = latest.current.graph
      const vertices = graph.getChildVertices(parent)
      let constrained = false
      const nextNodes = vertices.map((cell) => {
        const geometry = cell.getGeometry(); const saved = nodes.get(cell.id) || {}
        const node = { ...saved, id: cell.id, name: String(saved.name || cell.value || 'Perangkat').slice(0, 80), kind: saved.kind || 'generic', x: clamp(geometry.x + geometry.width / 2), y: clamp(geometry.y + geometry.height / 2), width: clamp(geometry.width, 40, 400), height: clamp(geometry.height, 40, 400) }
        if (geometry.width !== node.width || geometry.height !== node.height || geometry.x !== node.x - node.width / 2 || geometry.y !== node.y - node.height / 2) constrained = true
        nodes.set(cell.id, node); return node
      })
      const ids = new Set(nextNodes.map((node) => node.id))
      const nextEdges = graph.getChildEdges(parent).filter((cell) => ids.has(cell.source?.id) && ids.has(cell.target?.id) && cell.source !== cell.target).map((cell) => {
        const saved = edges.get(cell.id) || { type: 'Ethernet', label: '', source_port: '', target_port: '', vlan: 0, speed_mbps: 0, evidence: 'manual' }
        const edge = { ...saved, id: cell.id, source: cell.source.id, target: cell.target.id, points: (cell.geometry.points || []).slice(0, 32).map((point) => ({ x: clamp(point.x), y: clamp(point.y) })) }
        edges.set(cell.id, edge); return edge
      })
      const next = { ...previous, nodes: nextNodes, links: nextEdges }
      if (next.nodes.length > 100 || next.links.length > 200) { undo.undo(); return }
      fingerprint = constrained ? '' : contentKey(next)
      latest.current.onChange(next)
    }
    model.addListener(InternalEvent.UNDO, (_sender, event) => { if (!updating) undo.undoableEditHappened(event.getProperty('edit')) })
    model.addListener(InternalEvent.CHANGE, emit)
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => latest.current.onSelect(graph.getSelectionCell()?.id || ''))
    graph.addListener(InternalEvent.DOUBLE_CLICK, (_sender, event) => {
      const cell = event.getProperty('cell'); if (!cell) return
      latest.current.onEdit(cell.isVertex() ? 'node' : 'edge', cell.id); event.consume()
    })
    const viewChanged = () => {
      if (updating) return
      const value = { x: graph.view.translate.x, y: graph.view.translate.y, zoom: graph.view.scale }
      viewKey = JSON.stringify(value); latest.current.onView(value)
    }
    graph.view.addListener(InternalEvent.SCALE_AND_TRANSLATE, viewChanged)
    graph.view.addListener(InternalEvent.TRANSLATE, viewChanged)
    graph.view.addListener(InternalEvent.SCALE, viewChanged)
    graph.view.addListener(InternalEvent.SCALE_AND_TRANSLATE, queuePackets)
    graph.view.addListener(InternalEvent.TRANSLATE, queuePackets)
    graph.view.addListener(InternalEvent.SCALE, queuePackets)
    model.addListener(InternalEvent.CHANGE, queuePackets)
    const wheel = (event) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault(); graph.view.setScale(Math.max(.1, Math.min(4, graph.view.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15))))
    }
    const keydown = (event) => {
      if (!latest.current.canManage || event.target.closest('input,textarea,select')) return
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); if (event.shiftKey) latest.current.onRedo(); else latest.current.onUndo() }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') { event.preventDefault(); latest.current.onRedo() }
      if (event.key === 'Delete' || event.key === 'Backspace') { event.preventDefault(); graph.removeCells() }
    }
    const drop = (event) => {
      event.preventDefault()
      if (!latest.current.canManage) return
      const symbol = event.dataTransfer.getData('application/theaz-device')
      if (!symbol) return
      const point = graph.getPointForEvent(event)
      latest.current.onDrop(symbol, { x: clamp(point.x), y: clamp(point.y) })
    }
    const dragover = (event) => event.preventDefault()
    const focusCanvas = () => host.focus({ preventScroll: true })
    const contextmenu = (event) => {
      event.preventDefault()
      const rect=host.getBoundingClientRect(); const cell=graph.getCellAt(event.clientX-rect.left+host.scrollLeft,event.clientY-rect.top+host.scrollTop)
      latest.current.onContext?.(cell ? {kind:cell.isVertex()?'node':'edge',id:cell.id,x:event.clientX,y:event.clientY} : null)
    }
    host.addEventListener('contextmenu',contextmenu)
    const resize = new ResizeObserver(()=>{ graph.sizeDidChange(); queuePackets() }); resize.observe(host)
    host.addEventListener('wheel', wheel, { passive: false }); host.addEventListener('keydown', keydown)
    host.addEventListener('drop', drop); host.addEventListener('dragover', dragover)
    host.addEventListener('pointerdown', focusCanvas)
    engine.current = {
      sync(value) {
        updating = true
        try {
          graph.setCellsMovable(value.canManage); graph.setCellsResizable(value.canManage)
          graph.setCellsDeletable(value.canManage); graph.setConnectable(value.canManage)
          const serialized = contentKey(value.graph)
          if (serialized !== fingerprint) {
            model.beginUpdate()
            try {
              const nodeIds = new Set(value.graph.nodes.map((n)=>n.id)); const edgeIds = new Set(value.graph.links.map((e)=>e.id))
              graph.removeCells(graph.getChildEdges(parent).filter((cell)=>!edgeIds.has(cell.id)))
              graph.removeCells(graph.getChildVertices(parent).filter((cell)=>!nodeIds.has(cell.id)))
              for(const key of nodes.keys()) if(!nodeIds.has(key)) nodes.delete(key)
              for(const key of edges.keys()) if(!edgeIds.has(key)) edges.delete(key)
              const cells = new Map()
              for (const node of value.graph.nodes) {
                nodes.set(node.id, node)
                const width = node.width || 72; const height = node.height || 64
                const style = {shape:'image',image:iconURL(node.icon||node.kind),imageAspect:true,fillColor:'none',strokeColor:'none',imageBackground:'none',imageBorder:'none',verticalLabelPosition:'bottom',verticalAlign:'top',align:'center',whiteSpace:'wrap',spacingTop:8,fontColor:'#172033',fontSize:12}
                let cell=model.getCell(node.id)
                if(!cell) cell=graph.insertVertex({parent,id:node.id,value:node.name,position:[node.x-width/2,node.y-height/2],size:[width,height],style})
                else { const geometry=cell.geometry.clone(); Object.assign(geometry,{x:node.x-width/2,y:node.y-height/2,width,height}); model.setGeometry(cell,geometry); model.setStyle(cell,style); model.setValue(cell,node.name) }
                cells.set(node.id,cell)
              }
              for (const edge of value.graph.links) {
                if (!cells.has(edge.source) || !cells.has(edge.target)) continue
                edges.set(edge.id, edge)
                let cell=model.getCell(edge.id)
                if(!cell) cell=graph.insertEdge({ parent, id: edge.id, value: edge.label || edge.type, source: cells.get(edge.source), target: cells.get(edge.target) })
                else { model.setValue(cell,edge.label||edge.type); model.setTerminal(cell,cells.get(edge.source),true); model.setTerminal(cell,cells.get(edge.target),false) }
                const geometry=cell.geometry.clone(); geometry.points=(edge.points||[]).map((point)=>new Point(point.x,point.y)); model.setGeometry(cell,geometry)
              }
            } finally { model.endUpdate() }
            fingerprint = serialized; undo.clear()
          }
          // Live health changes affect styling, never create edits or topology saves.
          model.beginUpdate()
          try {
            for (const cell of graph.getChildVertices(parent)) {
              const color=colors[value.status(nodes.get(cell.id))]||colors.UNKNOWN
              if(cell.getStyle().fontColor!==color) graph.setCellStyles('fontColor',color,[cell])
            }
            for (const cell of graph.getChildEdges(parent)) {
              const color=colors[value.edgeStatus(edges.get(cell.id))]||colors.UNKNOWN
              if(cell.getStyle().strokeColor!==color) graph.setCellStyles('strokeColor',color,[cell])
            }
          } finally { model.endUpdate() }
          if (JSON.stringify(value.view) !== viewKey) {
            graph.view.scaleAndTranslate(value.view.zoom, value.view.x, value.view.y); viewKey = JSON.stringify(value.view)
          }
          queuePackets()
        } finally { updating = false }
      },
      undo: () => undo.undo(), redo: () => undo.redo(), delete: () => graph.removeCells(),
      fit: () => { const fit=graph.getPlugin('fit');fit.maxFitScale=4;fit.fitCenter({border:40}); viewChanged() },
    }
    // maxGraph generates edge IDs, independent of inventory identifiers.
    const createEdge = graph.createEdge.bind(graph)
    graph.createEdge = (...args) => { const cell = createEdge(...args); if (!cell.id) cell.setId(uid('e_')); return cell }
    return () => {
      host.removeEventListener('wheel', wheel); host.removeEventListener('keydown', keydown); host.removeEventListener('drop', drop); host.removeEventListener('dragover', dragover)
      host.removeEventListener('pointerdown', focusCanvas)
      host.removeEventListener('contextmenu',contextmenu); document.removeEventListener('visibilitychange',visibility); resize.disconnect(); clearInterval(expiryTimer); cancelAnimationFrame(frame); overlay.remove()
      graph.destroy(); engine.current = null
    }
  }, [])
  useEffect(() => { engine.current?.sync(props) })
  return <div className="nms-topology-canvas-wrap"><div className="d-flex gap-2 p-2 border-bottom">
    <button className="btn btn-sm btn-outline-secondary" disabled={!props.canManage} onClick={props.onUndo}>Urungkan</button>
    <button className="btn btn-sm btn-outline-secondary" disabled={!props.canManage} onClick={props.onRedo}>Ulangi</button>
    <button className="btn btn-sm btn-outline-danger" disabled={!props.canManage} onClick={() => engine.current?.delete()}>Hapus pilihan</button>
    <button className="btn btn-sm btn-outline-secondary" onClick={()=>engine.current?.fit()}>Muat seluruh diagram</button>
    <small className="text-muted ms-auto align-self-center">Ctrl + roda: zoom · Seret area kosong: pan · Klik kanan: detail</small>
  </div><div ref={container} className="nms-topology-canvas" tabIndex={0} role="application" aria-label="Canvas topologi interaktif"/></div>
}
