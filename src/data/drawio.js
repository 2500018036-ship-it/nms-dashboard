import { Inflate, strFromU8 } from 'fflate'
import { iconURL, networkIcons } from './networkIcons.js'

const limit = 2 * 1024 * 1024
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[char])
const bound = (value, min = -5000, max = 5000) => Math.max(min, Math.min(max, Math.round(Number(value) || 0)))
const kinds = new Set([...networkIcons.map((item) => item.kind), 'application', 'other'])
const clean = (value, max = 80) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, max)

export function exportDrawio(graph) {
  const nodes = graph.nodes.map((node) => {
    const width = node.width || 160; const height = node.height || 80
    const metadata = Object.entries({ label: node.name, nms_kind: node.kind, nms_icon: node.icon || node.kind, nms_group: node.group, nms_collector: node.collector, nms_device_id: node.device_id, nms_resource_id: node.resource_id, nms_service_id: node.service_id }).map(([key, value]) => `${key}="${escape(value)}"`).join(' ')
    return `<object id="${escape(node.id)}" ${metadata}><mxCell vertex="1" parent="1" style="shape=image;image=${escape(iconURL(node.icon || node.kind).replaceAll(';', '%3B'))};imageAspect=1;fillColor=none;strokeColor=none;verticalLabelPosition=bottom;verticalAlign=top;align=center;whiteSpace=wrap;html=0;"><mxGeometry x="${node.x - width / 2}" y="${node.y - height / 2}" width="${width}" height="${height}" as="geometry"/></mxCell></object>`
  })
  const links = graph.links.map((edge) => `<object id="${escape(edge.id)}" label="${escape(edge.label)}" nms_type="${escape(edge.type)}" nms_source_port="${escape(edge.source_port)}" nms_target_port="${escape(edge.target_port)}" nms_vlan="${edge.vlan || 0}" nms_speed_mbps="${edge.speed_mbps || 0}" nms_evidence="${escape(edge.evidence || 'manual')}"><mxCell edge="1" source="${escape(edge.source)}" target="${escape(edge.target)}" parent="1" style="edgeStyle=orthogonalEdgeStyle;endArrow=none;html=0;"><mxGeometry relative="1" as="geometry">${edge.points?.length ? `<Array as="points">${edge.points.map((point) => `<mxPoint x="${point.x}" y="${point.y}"/>`).join('')}</Array>` : ''}</mxGeometry></mxCell></object>`)
  return `<?xml version="1.0" encoding="UTF-8"?><mxfile host="THEAZ NMS"><diagram name="${escape(graph.name)}"><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>${nodes.join('')}${links.join('')}</root></mxGraphModel></diagram></mxfile>`
}

// Normalize imported diagrams to the bounded NMS model. No styles, scripts, URLs or stencils execute.
export function importDrawio(input, Parser = globalThis.DOMParser) {
  const parse = (text) => {
    if (text.length > limit || /<!DOCTYPE|<!ENTITY/i.test(text)) throw new Error('Berkas diagram tidak aman atau melebihi 2 MB.')
    const doc = new Parser().parseFromString(text, 'text/xml')
    if (!doc.documentElement || doc.getElementsByTagName('parsererror').length) throw new Error('XML diagram tidak valid.')
    return doc
  }
  let doc = parse(input)
  const diagram = doc.getElementsByTagName('diagram')[0]
  const name = clean(diagram?.getAttribute('name')) || 'Topologi impor'
  if (diagram && !diagram.getElementsByTagName('mxGraphModel').length) {
    const value = diagram.textContent.trim()
    if (value.startsWith('<')) doc = parse(value)
    else {
      let length = 0; const chunks = []
      const inflater = new Inflate((chunk) => { length += chunk.length; if (length > limit) throw new Error('Diagram terkompresi melebihi 2 MB.'); chunks.push(chunk) })
      try {
        const compressed = Uint8Array.from(atob(value), (char) => char.charCodeAt(0))
        for (let offset = 0; offset < compressed.length; offset += 1024) inflater.push(compressed.subarray(offset, offset + 1024), offset + 1024 >= compressed.length)
        const data = new Uint8Array(length); let offset = 0
        for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length }
        doc = parse(decodeURIComponent(strFromU8(data)))
      } catch { throw new Error('Diagram terkompresi tidak valid atau terlalu besar.') }
    }
  }
  if (!doc.getElementsByTagName('mxGraphModel').length) throw new Error('Gunakan berkas .drawio atau XML mxGraphModel.')
  const cells = [...doc.getElementsByTagName('mxGraphModel')[0].getElementsByTagName('mxCell')]
  if (cells.length > 302) throw new Error('Maksimal 100 node dan 200 koneksi.')
  const attr = (cell, key) => cell.parentNode?.nodeName === 'object' || cell.parentNode?.nodeName === 'UserObject' ? cell.parentNode.getAttribute(key) || cell.getAttribute(key) : cell.getAttribute(key)
  const label = (cell) => clean(/(?:^|;)html=1(?:;|$)/.test(cell.getAttribute('style') || '') ? (attr(cell, 'label') || attr(cell, 'value') || '').replace(/<[^>]*>/g, ' ') : attr(cell, 'label') || attr(cell, 'value'))
  const ids = new Map(); const nodes = []
  for (const cell of cells.filter((cell) => cell.getAttribute('vertex') === '1')) {
    const geometry = cell.getElementsByTagName('mxGeometry')[0]
    if (!geometry) continue
    if (nodes.length >= 100) throw new Error('Maksimal 100 node.')
    const original = attr(cell, 'id'); const id = 'n_' + nodes.length
    ids.set(original, id)
    const kind = kinds.has(attr(cell, 'nms_kind')) ? attr(cell, 'nms_kind') : 'generic'
    const width = bound(geometry.getAttribute('width'), 40, 400); const height = bound(geometry.getAttribute('height'), 40, 400)
    const node = { id, name: label(cell) || 'Perangkat ' + (nodes.length + 1), kind, icon: networkIcons.some((item) => item.id === attr(cell, 'nms_icon')) ? attr(cell, 'nms_icon') : kind, x: bound(Number(geometry.getAttribute('x')) + width / 2), y: bound(Number(geometry.getAttribute('y')) + height / 2), width, height }
    for (const key of ['group', 'collector', 'resource_id', 'service_id', 'device_id']) node[key] = clean(attr(cell, 'nms_' + key), 100)
    nodes.push(node)
  }
  const links = []
  for (const cell of cells.filter((cell) => cell.getAttribute('edge') === '1')) {
    const source = ids.get(cell.getAttribute('source')); const target = ids.get(cell.getAttribute('target'))
    if (!source || !target || source === target) continue
    if (links.length >= 200) throw new Error('Maksimal 200 koneksi.')
    links.push({ id: 'e_' + links.length, source, target, label: clean(attr(cell, 'label') || attr(cell, 'value')), type: clean(attr(cell, 'nms_type')) || 'Ethernet', source_port: clean(attr(cell, 'nms_source_port')), target_port: clean(attr(cell, 'nms_target_port')), vlan: bound(attr(cell, 'nms_vlan'), 0, 4094), speed_mbps: bound(attr(cell, 'nms_speed_mbps'), 0, 1000000), evidence: clean(attr(cell, 'nms_evidence')) || 'manual', points: [...cell.getElementsByTagName('mxPoint')].slice(0, 32).map((point) => ({ x: bound(point.getAttribute('x')), y: bound(point.getAttribute('y')) })) })
  }
  return { name, nodes, links }
}
