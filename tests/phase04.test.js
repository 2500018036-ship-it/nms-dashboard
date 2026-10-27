import test from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from '../src/data/apiClient.js'
import { adaptEvidence, adaptIncident, adaptJournal, incidentIdValid, journalParams } from '../src/data/journalModel.js'
import { isGatewayRequest } from '../config/devProxy.js'

const filters = { page: 1, pageSize: 25, q: '', severity: 'all', device: '', period: '24h', source: 'all', category: 'all', status: 'ACTIVE' }
const incident = { id: 'inc_event_12', key: 'dns:availability', status: 'RECOVERED', severity: 'CRITICAL', first_seen: 100, updated_at: 200, resolved_at: 200, acknowledgment: { supported: false }, timeline: [{ id: 'event_12', time: 100, kind: 'ALERT', detail: { title: 'DNS', severity: 'CRITICAL' }, evidence: { status: 'DOWN', password: 'never-forward' } }] }
test('journal client encodes filters and only permits read endpoints and validated IDs', async () => {
  const calls = []
  const client = createApiClient({ enabled: true, base: '/nms-api' }, async (url, options) => { calls.push({ url, options }); return new Response('{}', { headers: { 'Content-Type': 'application/json' } }) })
  await client.journal('logs', { q: 'DNS & error', device: 'MikroTik' })
  assert.equal(calls[0].url, '/nms-api/api/logs?q=DNS+%26+error&device=MikroTik')
  assert.equal(calls[0].options.method, 'GET')
  await assert.rejects(client.journal('exec', {}), { code: 'target_not_allowed' })
  await assert.rejects(client.journal('logs', { url: 'https://evil.example' }), { code: 'invalid_filter' })
  await assert.rejects(client.incident('../../etc/passwd'), { code: 'target_not_allowed' })
  await client.incident('inc_event_12'); assert.equal(calls.length, 2)
})
test('WIB custom time range is explicit and invalid future or inverted range is rejected', () => {
  const now = Date.parse('2026-10-23T15:00:00+07:00') / 1000
  const actual = journalParams({ ...filters, period: 'custom', start: '2026-10-23T12:00', end: '2026-10-23T13:00' }, 'logs', now)
  assert.equal(actual.to - actual.from, 3600)
  assert.equal(actual.from, Date.parse('2026-10-23T05:00:00Z') / 1000)
  for (const patch of [{ start: '', end: '' }, { start: '2026-10-23T14:00', end: '2026-10-23T13:00' }, { start: '2026-10-23T16:00', end: '2026-10-23T17:00' }]) assert.throws(() => journalParams({ ...filters, period: 'custom', ...patch }, 'logs', now), { code: 'invalid_filter' })
})
test('pagination window stays anchored and inactive data is never fabricated', () => {
  const first = journalParams(filters, 'logs', 1000000)
  const second = journalParams({ ...filters, page: 2 }, 'logs', 1000000)
  assert.equal(first.from, second.from); assert.equal(first.to, second.to); assert.equal(second.page, 2)
  const data = adaptJournal({ read_only: true, items: [], total: 0, page: 1, page_size: 25, sources: [{ id: 'syslog', available: false }] }, 'logs')
  assert.equal(data.items.length, 0); assert.equal(data.sources[0].available, false)
})
test('incident identity, peak severity, recovery and incomplete history are preserved', () => {
  const result = adaptIncident(incident)
  assert.equal(result.id, 'inc_event_12'); assert.equal(result.severity, 'CRITICAL'); assert.equal(result.status, 'RECOVERED')
  assert.equal(result.acknowledgmentSupported, false)
  assert.equal(result.firstSeen, 100); assert.equal(result.resolvedAt, 200)
  assert.equal(JSON.stringify(result).includes('never-forward'), false)
  assert.equal(adaptIncident({ ...incident, status: 'made_up', partial_history: true, first_seen: null }).firstSeen, null)
  assert.equal(incidentIdValid('inc_event_12/restart'), false)
})
test('journal rejects malformed contracts, excessive pages and invalid row identity', () => {
  const base = { read_only: true, items: [], total: 0, page: 1, page_size: 25 }
  for (const patch of [{ read_only: false }, { total: -1 }, { page: 0 }, { page_size: 101 }, { items: [{ id: 'fake' }] }]) assert.throws(() => adaptJournal({ ...base, ...patch }, 'logs'), { code: 'invalid_response' })
  assert.deepEqual(adaptEvidence({ cpu_percent: 0, threshold: 90, password: 'hidden', headers: { authorization: 'hidden' } }), { cpu_percent: 0, threshold: 90 })
})
test('journal development proxy exposes no acknowledgment, resolution or syslog mutation', () => {
  for (const url of ['/nms-api/api/logs', '/nms-api/api/incidents', '/nms-api/api/incidents/inc_event_12']) assert.equal(isGatewayRequest('GET', url, '/nms-api'), true)
  for (const method of ['POST', 'DELETE', 'PATCH']) for (const url of ['/nms-api/api/incidents/inc_event_12', '/nms-api/api/incidents/inc_event_12/ack', '/nms-api/api/logs']) assert.equal(isGatewayRequest(method, url, '/nms-api'), false)
})
