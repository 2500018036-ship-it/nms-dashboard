import test from 'node:test'
import assert from 'node:assert/strict'
import { createAssistantWorkspace } from '../src/data/assistantWorkspace.js'
import { createTopologyWorkspace } from '../src/data/topologyWorkspace.js'
const storage = () => { const values = new Map(); return { getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value) } }
const tick = () => new Promise((resolve) => setImmediate(resolve))
const deferred = () => { let resolve; const promise = new Promise((done) => { resolve = done }); return { promise, resolve } }

test('assistant continues without page subscribers and restores completed server history after refresh', async () => {
  const store = storage(); const gate = deferred(); const items = []; let calls = 0
  const client = { async platform(path, options) { if (path === 'assistant-history') return { items: structuredClone(items) }; calls++; const pending = options.body; await gate.promise; const job = { id: 'job_1', request_id: pending.request_id, question: pending.question, created_at: 1, state: 'running' }; items.push(job); return job } }
  const a = createAssistantWorkspace({ client, username: 'azril', storage: store, interval: 5, makeId: () => 'a'.repeat(32) }); const stop = a.start(); await tick()
  a.setDraft('Periksa homelab'); const unsubscribe = a.subscribe(() => {}); const first = a.submit(); await a.submit(); unsubscribe()
  gate.resolve(); await first; items[0].state = 'complete'; items[0].answer = 'Selesai'
  await new Promise((resolve) => setTimeout(resolve, 20)); assert.equal(a.getSnapshot().items[0].answer, 'Selesai'); assert.equal(calls, 1); stop()
  const restored = createAssistantWorkspace({ client, username: 'azril', storage: store }); const stop2 = restored.start(); await tick(); assert.equal(restored.getSnapshot().items[0].question, 'Periksa homelab'); assert.equal(restored.getSnapshot().items[0].answer, 'Selesai'); stop2()
})

test('uncertain assistant request is retried using the same persisted idempotency key', async () => {
  const store = storage(); const keys = []; let failed = true
  const client = { async platform(path, options) { if (path === 'assistant-history') return { items: [] }; keys.push(options.body.request_id); if (failed) throw Error('network'); return { id: 'job_2', state: 'complete', answer: 'ok', created_at: 2 } } }
  const a = createAssistantWorkspace({ client, username: 'one', storage: store, makeId: () => 'b'.repeat(32) }); const stop = a.start(); await tick(); a.setDraft('Status'); await a.submit(); stop(); failed = false
  const b = createAssistantWorkspace({ client, username: 'one', storage: store }); const end = b.start(); await tick(); await tick(); assert.deepEqual(keys, ['b'.repeat(32), 'b'.repeat(32)]); assert.equal(b.getSnapshot().items[0].answer, 'ok'); end()
  assert.equal(createAssistantWorkspace({ client, username: 'two', storage: store }).getSnapshot().draft, '')
})

test('topology drafts, geometry, connections and view survive navigation and refresh', async () => {
  const store = storage(); const client = { platform: async () => { throw Error('unused') } }
  const a = createTopologyWorkspace({ client, username: 'one', storage: store, makeId: () => 'a'.repeat(32) }); const stop = a.start(); a.create('LAN')
  a.change({ name: 'LAN', nodes: [{ id: 'r', x: 240, y: 120 }, { id: 's', x: 410, y: 300 }], links: [{ id: 'e', source: 'r', target: 's' }] }); a.setView({ x: 20, y: 40, zoom: 1.5 }); const before = a.getSnapshot(); stop()
  const b = createTopologyWorkspace({ client, username: 'one', storage: store }); assert.deepEqual(b.getSnapshot().documents, before.documents); assert.equal(b.getSnapshot().selected, before.selected)
  assert.equal(Object.keys(createTopologyWorkspace({ client, username: 'other', storage: store }).getSnapshot().documents).length, 0)
})

test('topology single-flight save retains edits made during a request and reuses uncertain save receipts', async () => {
  const store = storage(); const gate = deferred(); const bodies = []; let uncertain = false
  const client = { async platform(_path, { body }) { bodies.push(body); await gate.promise; if (uncertain) throw Error('network'); return { id: 'top_1', revision: bodies.length, ...body.value } } }
  const a = createTopologyWorkspace({ client, username: 'one', storage: store, makeId: () => 'c'.repeat(32) }); const stop = a.start(); a.create('LAN'); const save = a.save(); a.save(); a.change({ name: 'LAN changed', nodes: [], links: [] }); gate.resolve(); await save
  let doc = a.getSnapshot().documents[a.getSnapshot().selected]; assert.equal(bodies.length, 1); assert.equal(doc.dirty, true); assert.equal(doc.graph.name, 'LAN changed')
  uncertain = true; await a.save(); const key = bodies[1].request_id; stop(); uncertain = false
  const b = createTopologyWorkspace({ client, username: 'one', storage: store }); const end = b.start(); await tick(); doc = b.getSnapshot().documents[b.getSnapshot().selected]; assert.equal(bodies[2].request_id, key); assert.equal(doc.dirty, false); assert.equal(doc.pending, null); end()
})

test('topology undo and redo restore palette additions, metadata and deleted connections', () => {
  const a = createTopologyWorkspace({ client: {}, username: 'one', storage: storage(), makeId: () => 'd'.repeat(32) }); a.create('LAN')
  const router = { id: 'r', name: 'Router', kind: 'router', icon: 'mikrotik', x: 200, y: 100 }
  a.change({ name: 'LAN', nodes: [router], links: [] })
  a.undo(); let doc = a.getSnapshot().documents[a.getSnapshot().selected]; assert.equal(doc.graph.nodes.length, 0)
  a.redo(); doc = a.getSnapshot().documents[a.getSnapshot().selected]; assert.equal(doc.graph.nodes[0].icon, 'mikrotik')
  a.change({ name: 'LAN', nodes: [router, { ...router, id: 's', name: 'Switch' }], links: [{ id: 'e', source: 'r', target: 's', label: 'Trunk' }] })
  a.change({ name: 'LAN', nodes: [router], links: [] }); a.undo(); doc = a.getSnapshot().documents[a.getSnapshot().selected]; assert.equal(doc.graph.links[0].label, 'Trunk'); assert.equal(doc.dirty, true)
})
