import test from 'node:test'
import assert from 'node:assert/strict'
import { DOMParser } from '@xmldom/xmldom'
import { deflateSync, strToU8 } from 'fflate'
import { importDrawio, exportDrawio } from '../src/data/drawio.js'
import { portalTarget } from '../src/data/accessTargets.js'

test('draw.io roundtrip preserves labels, icon, positions, size, bindings and edge waypoints', () => {
  const value = { name: 'LAN & lab', nodes: [{ id: 'r', name: 'MikroTik <lab>', kind: 'router', icon: 'mikrotik', x: 300, y: 180, width: 180, height: 80, collector: 'mikrotik_system', device_id: 'inv_1', group: 'LAN' }, { id: 's', name: 'VM', kind: 'vm', x: 600, y: 280 }], links: [{ id: 'e', source: 'r', target: 's', type: 'VLAN', label: 'Trunk', source_port: 'ether1', vlan: 20, points: [{ x: 420, y: 180 }] }] }
  const xml = exportDrawio(value); const result = importDrawio(xml, DOMParser)
  assert.match(xml, /<mxGraphModel>/); assert.equal(result.name, value.name); assert.equal(result.nodes[0].icon, 'mikrotik'); assert.equal(result.nodes[0].x, 300); assert.equal(result.nodes[0].width, 180); assert.equal(result.nodes[0].device_id, 'inv_1'); assert.deepEqual(result.links[0].points, value.links[0].points); assert.equal(result.links[0].vlan, 20)
  const compressed = Buffer.from(deflateSync(strToU8(encodeURIComponent(xml.match(/<mxGraphModel>.*<\/mxGraphModel>/s)[0])))).toString('base64')
  assert.equal(importDrawio(`<mxfile><diagram name="Compressed">${compressed}</diagram></mxfile>`, DOMParser).nodes.length, 2)
})

test('draw.io importer rejects external entities and bounds decompression; external styles never survive', () => {
  assert.throws(() => importDrawio('<!DOCTYPE x [<!ENTITY a SYSTEM "file:///secret">]><mxGraphModel/>', DOMParser))
  const compressed = Buffer.from(deflateSync(strToU8('a'.repeat(3 * 1024 * 1024)))).toString('base64')
  assert.throws(() => importDrawio(`<mxfile><diagram>${compressed}</diagram></mxfile>`, DOMParser), /besar/)
  const result = importDrawio('<mxGraphModel><root><mxCell id="x" vertex="1" value="&lt;img src=x onerror=alert(1)&gt;Router" style="image=https://evil.invalid/a;html=1"><mxGeometry x="99999" y="1" width="100" height="60"/></mxCell></root></mxGraphModel>', DOMParser)
  assert.equal(result.nodes[0].name, 'Router'); assert.equal(result.nodes[0].x, 5000); assert.equal(JSON.stringify(result).includes('evil.invalid'), false)
})

test('known native services navigate through NMS and arbitrary destinations are not promoted', () => {
  for (const [url, target] of [['http://192.168.20.1/', 'mikrotik'], ['http://192.168.10.26/', 'cisco'], ['http://192.168.10.194/', 'tplink'], ['https://192.168.20.200:8006/', 'proxmox'], ['http://192.168.20.199:5380/', 'technitium'], ['https://192.168.20.195:9443/', 'portainer'], ['http://192.168.20.195:81/', 'npm']]) assert.equal(portalTarget({ url }), target)
  assert.equal(portalTarget({ url: 'https://example.org/' }), null)
})
