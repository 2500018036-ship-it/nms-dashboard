import { useEffect, useRef } from 'react'
import { Graph, getDefaultPlugins, RubberBandHandler, InternalEvent, UndoManager, Point } from '@maxgraph/core'
import '@maxgraph/core/css/common.css'
import { iconURL } from '../data/networkIcons'

const colors = { UP: '#198754', DOWN: '#dc3545', DEGRADED: '#b77900', UNKNOWN: '#64748b', DISABLED: '#64748b' }
const clamp = (value, min = -5000, max = 5000) => Math.max(min, Math.min(max, Math.round(value)))
const uid = (prefix) => prefix + crypto.randomUUID().replaceAll('-', '').slice(0, 16)

export default function TopologyCanvas(props) {
  const container = useRef(null); const engine = useRef(null); const latest = useRef(props)
  useEffect(() => { latest.current = props })
  useEffect(() => {
    const host = container.current
    const graph = new Graph(host, undefined, getDefaultPlugins().concat([RubberBandHandler]))
    const model = graph.getDataModel(); const parent = graph.getDefaultParent(); const undo = new UndoManager(100)
    const nodes = new Map(); const edges = new Map()
    let updating = false; let fingerprint = ''; let viewKey = ''
    graph.setConnectable(true); graph.setPanning(true); graph.setHtmlLabels(false)
    graph.setAllowDanglingEdges(false); graph.setAllowLoops(false); graph.setCellsEditable(false); graph.setCellsCloneable(false); graph.setTooltips(true)
    const validateEdge = graph.getEdgeValidationError.bind(graph)
    graph.getEdgeValidationError = (edge, source, target) => graph.getChildEdges(parent).length >= 200 && !graph.getChildEdges(parent).includes(edge) ? 'Maksimal 200 koneksi.' : validateEdge(edge, source, target)
    graph.getPlugin('PanningHandler').useLeftButtonForPanning = true
    graph.getPlugin('PanningHandler').ignoreCell = false
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
        const node = { ...saved, id: cell.id, name: String(cell.value || saved.name || 'Perangkat').slice(0, 80), kind: saved.kind || 'generic', x: clamp(geometry.x + geometry.width / 2), y: clamp(geometry.y + geometry.height / 2), width: clamp(geometry.width, 40, 400), height: clamp(geometry.height, 40, 400) }
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
      fingerprint = constrained ? '' : JSON.stringify(next)
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
    const wheel = (event) => {
      if (!event.ctrlKey && !event.metaKey) return
      event.preventDefault(); graph.view.setScale(Math.max(.25, Math.min(3, graph.view.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15))))
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
    host.addEventListener('wheel', wheel, { passive: false }); host.addEventListener('keydown', keydown)
    host.addEventListener('drop', drop); host.addEventListener('dragover', dragover)
    host.addEventListener('pointerdown', focusCanvas)
    engine.current = {
      sync(value) {
        updating = true
        try {
          graph.setCellsMovable(value.canManage); graph.setCellsResizable(value.canManage)
          graph.setCellsDeletable(value.canManage); graph.setConnectable(value.canManage)
          const serialized = JSON.stringify(value.graph)
          if (serialized !== fingerprint) {
            model.beginUpdate()
            try {
              graph.removeCells(graph.getChildCells(parent), true)
              const cells = new Map()
              for (const node of value.graph.nodes) {
                nodes.set(node.id, node)
                const width = node.width || 160; const height = node.height || 80
                cells.set(node.id, graph.insertVertex({ parent, id: node.id, value: node.name, position: [node.x - width / 2, node.y - height / 2], size: [width, height], style: { shape: 'label', rounded: true, image: iconURL(node.icon || node.kind), imageWidth: 32, imageHeight: 32, spacingLeft: 42, align: 'left', verticalAlign: 'middle', whiteSpace: 'wrap', fillColor: '#ffffff', fontColor: '#172033', strokeWidth: 2 } }))
              }
              for (const edge of value.graph.links) {
                if (!cells.has(edge.source) || !cells.has(edge.target)) continue
                edges.set(edge.id, edge)
                const cell = graph.insertEdge({ parent, id: edge.id, value: edge.label || edge.type, source: cells.get(edge.source), target: cells.get(edge.target) })
                if (edge.points) cell.geometry.points = edge.points.map((point) => new Point(point.x, point.y))
              }
            } finally { model.endUpdate() }
            fingerprint = serialized; undo.clear()
          }
          // Live health changes affect styling, never create edits or topology saves.
          model.beginUpdate()
          try {
            for (const cell of graph.getChildVertices(parent)) graph.setCellStyles('strokeColor', colors[value.status(nodes.get(cell.id))] || colors.UNKNOWN, [cell])
            for (const cell of graph.getChildEdges(parent)) graph.setCellStyles('strokeColor', colors[value.edgeStatus(edges.get(cell.id))] || colors.UNKNOWN, [cell])
          } finally { model.endUpdate() }
          if (JSON.stringify(value.view) !== viewKey) {
            graph.view.scaleAndTranslate(value.view.zoom, value.view.x, value.view.y); viewKey = JSON.stringify(value.view)
          }
        } finally { updating = false }
      },
      undo: () => undo.undo(), redo: () => undo.redo(), delete: () => graph.removeCells(),
    }
    // maxGraph generates edge IDs, independent of inventory identifiers.
    const createEdge = graph.createEdge.bind(graph)
    graph.createEdge = (...args) => { const cell = createEdge(...args); if (!cell.id) cell.setId(uid('e_')); return cell }
    return () => {
      host.removeEventListener('wheel', wheel); host.removeEventListener('keydown', keydown); host.removeEventListener('drop', drop); host.removeEventListener('dragover', dragover)
      host.removeEventListener('pointerdown', focusCanvas)
      graph.destroy(); engine.current = null
    }
  }, [])
  useEffect(() => { engine.current?.sync(props) })
  return <div className="nms-topology-canvas-wrap"><div className="d-flex gap-2 p-2 border-bottom">
    <button className="btn btn-sm btn-outline-secondary" disabled={!props.canManage} onClick={props.onUndo}>Urungkan</button>
    <button className="btn btn-sm btn-outline-secondary" disabled={!props.canManage} onClick={props.onRedo}>Ulangi</button>
    <button className="btn btn-sm btn-outline-danger" disabled={!props.canManage} onClick={() => engine.current?.delete()}>Hapus pilihan</button>
    <small className="text-muted ms-auto align-self-center">maxGraph · Ctrl+Z / Ctrl+Y</small>
  </div><div ref={container} className="nms-topology-canvas" tabIndex={0} role="application" aria-label="Canvas topologi interaktif"/></div>
}
