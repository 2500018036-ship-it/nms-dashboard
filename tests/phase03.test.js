import test from 'node:test'
import assert from 'node:assert/strict'
import { createApiClient } from '../src/data/apiClient.js'
import { adaptSession, safeReturnPath, validateLogin } from '../src/data/authModel.js'
import { adaptDevices, adaptStatus } from '../src/data/adapters.js'
import { isGatewayRequest, sameOriginRequest } from '../config/devProxy.js'

const json = (data) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
test('empty pending alert does not hide recorded last-event metadata', () => {
  const snapshot = adaptStatus({ checks: [], alerts: [{ key: 'mikrotik:storage', active: true, first_seen: 123,
    pending: {}, last_event: { title: 'Peringatan monitoring', severity: 'CRITICAL', device: 'mikrotik' } }] })
  assert.equal(snapshot.alerts[0].severity, 'CRITICAL')
  assert.equal(snapshot.alerts[0].device, 'mikrotik')
})
test('auth client sends only exact login fields via JSON POST without auth headers', async () => {
  let seen
  const client = createApiClient({ enabled: true, base: '/nms-api' }, async (url, options) => { seen = { url, options }; return json({}) })
  await client.login({ username: 'nms', password: ' test password ', remember: false, role: 'admin' })
  assert.equal(seen.url, '/nms-api/api/auth/login'); assert.equal(seen.options.method, 'POST')
  assert.deepEqual(JSON.parse(seen.options.body), { username: 'nms', password: ' test password ', remember: false })
  assert.equal(seen.options.credentials, 'same-origin'); assert.equal('Authorization' in seen.options.headers, false)
  await client.logout(); assert.equal(seen.url, '/nms-api/api/auth/logout'); assert.equal(seen.options.body, '{}')
})
test('login fails on unauthorized response and never accepts a six-character password locally', async () => {
  const client = createApiClient({ enabled: true, base: '/nms-api' }, async () => new Response('{}', { status: 401 }))
  await assert.rejects(client.login({ username: 'admin', password: 'abcdef' }), { code: 'invalid_credentials' })
  await assert.rejects(client.session(), { code: 'auth_required' })
})
test('login validation preserves password whitespace and rejects malformed fields', () => {
  assert.deepEqual(validateLogin({ username: 'nms', password: ' spaces count ' }), {})
  assert.equal(Object.keys(validateLogin({ username: '', password: '' })).length, 2)
  assert.ok(validateLogin({ username: 'a'.repeat(81), password: 'x'.repeat(513) }).password)
})
test('session projection requires server identity, role and future expiry without forwarding secrets', () => {
  const payload = { user: { username: 'nms', role: 'Read-only operator', password: 'do-not-forward' }, expires_at: Date.now() / 1000 + 3600, idle_timeout_seconds: 1800, token: 'do-not-forward' }
  assert.equal(JSON.stringify(adaptSession(payload)).includes('do-not-forward'), false)
  for (const value of [{}, { ...payload, expires_at: 0 }, { ...payload, user: { username: 'admin', role: 'admin' } }]) assert.throws(() => adaptSession(value), { code: 'invalid_response' })
})
test('return routes reject open redirects, login loops and credential URL injection', () => {
  assert.equal(safeReturnPath('/network'), '/network')
  for (const path of ['//evil.example', 'https://evil.example', '/login', '/nms-api/api/status', '/\\evil', null, { path: '/network' }]) assert.equal(safeReturnPath(path), '/')
})
test('gateway allows only authentication POST and read-only monitoring endpoints', () => {
  for (const path of ['/api/auth/login', '/api/auth/logout']) assert.equal(isGatewayRequest('POST', '/nms-api' + path, '/nms-api'), true)
  for (const path of ['/api/devices', '/api/exec', '/api/status', '/api/auth/register']) assert.equal(isGatewayRequest('POST', '/nms-api' + path, '/nms-api'), false)
  assert.equal(isGatewayRequest('GET', '/nms-api/api/devices/device_0123456789ab', '/nms-api'), true)
  assert.equal(isGatewayRequest('GET', '/nms-api/api/devices/../../private', '/nms-api'), false)
})
test('gateway checks incoming browser origin before rewriting to backend origin', () => {
  assert.equal(sameOriginRequest({ host: '127.0.0.1:5173', origin: 'http://127.0.0.1:5173' }), true)
  for (const headers of [{ host: '127.0.0.1:5173' }, { host: '127.0.0.1:5173', origin: 'https://evil.example' }, { host: '127.0.0.1:5173', origin: 'http://127.0.0.1:5173', 'sec-fetch-site': 'cross-site' }]) assert.equal(sameOriginRequest(headers), false)
})
test('observed devices require read-only contract and project known fields', () => {
  assert.throws(() => adaptDevices({ devices: [] }), { code: 'invalid_response' })
  const result = adaptDevices({ read_only: true, devices: [{ id: 'device_0123456789ab', name: 'Router', host: '192.0.2.1', status: 'UNKNOWN', collectors: ['api'], methods: ['API'], sample_epoch: 100, password: 'do-not-forward' }] })
  assert.equal(result[0].status, 'UNKNOWN'); assert.equal(JSON.stringify(result).includes('do-not-forward'), false)
})
test('projected null metrics and empty disk arrays do not classify every device as a server', () => {
  const now = Date.now() / 1000
  const payload = { alerts: [], checks: [
    { target: 'dns', status: 'UP', sample_epoch: now, cpu_percent: null, disks: [] },
    { target: 'debian', status: 'UP', sample_epoch: now, cpu_percent: 12, disks: [] },
  ] }
  const snapshot = adaptStatus(payload, now)
  assert.deepEqual(snapshot.core.hosts.map((h) => h.id), ['debian'])
  assert.equal(snapshot.core.hosts[0].cpu, 12)
})
