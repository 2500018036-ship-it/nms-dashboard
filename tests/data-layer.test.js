import test from 'node:test'
import assert from 'node:assert/strict'
import { readConfig } from '../src/data/capabilities.js'
import { createApiClient } from '../src/data/apiClient.js'
import { adaptStatus, adaptEvents, adaptHistory, ageSnapshot, finite } from '../src/data/adapters.js'
import { modules, searchModules } from '../src/app/modules.js'
import { validateProxyTarget, isReadOnlyRequest } from '../config/devProxy.js'

const response = (data) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
const enabled = readConfig({ VITE_NMS_API_ENABLED: 'true' })
const now = 1792558800
const status = (checks = []) => ({ checks, alerts: [], server_time: now, interval: 15 })

test('default client does not send requests before integration is enabled', async () => {
  let calls = 0
  const client = createApiClient(readConfig(), () => { calls++; return response({}) })
  await assert.rejects(client.status(), { code: 'not_configured' })
  assert.equal(calls, 0)
})
test('API base rejects external origins, credentials and URL query injection', () => {
  for (const base of ['https://example.test', '//example.test', '/api?token=x', '/api#x', '/api\\x']) assert.equal(readConfig({ VITE_NMS_API_BASE: base }).invalid, true)
})
test('API client sends only GET and preserves same-origin policy', async () => {
  let seen
  const client = createApiClient(enabled, async (url, options) => { seen = { url, options }; return response({ checks: [], alerts: [] }) })
  await client.status()
  assert.equal(seen.url, '/nms-api/api/status'); assert.equal(seen.options.method, 'GET')
  assert.equal(seen.options.credentials, 'same-origin'); assert.equal(seen.options.redirect, 'error')
  assert.equal('Authorization' in seen.options.headers, false)
})
test('history rejects target outside allowlist before sending', async () => {
  let calls = 0
  const client = createApiClient(enabled, () => { calls++; return response({}) })
  await assert.rejects(client.history('../private'), { code: 'target_not_allowed' }); assert.equal(calls, 0)
})
test('auth and rate-limit responses are classified without retry or body disclosure', async () => {
  for (const [code, expected] of [[401, 'auth_required'], [403, 'permission_denied'], [429, 'rate_limited'], [503, 'unavailable']]) {
    let calls = 0
    const client = createApiClient(enabled, async () => { calls++; return new Response('private detail', { status: code }) })
    await assert.rejects(client.status(), { code: expected, message: expected }); assert.equal(calls, 1)
  }
})
test('HTML fallback and malformed JSON never count as a successful API response', async () => {
  await assert.rejects(createApiClient(enabled, async () => new Response('<html></html>')).status(), { code: 'invalid_response' })
  await assert.rejects(createApiClient(enabled, async () => new Response('{bad', { headers: { 'Content-Type': 'application/json' } })).status(), { code: 'invalid_response' })
})
test('response body limit is enforced even without content-length', async () => {
  const client = createApiClient(enabled, async () => new Response('x'.repeat(2 * 1024 * 1024 + 1), { headers: { 'Content-Type': 'application/json' } }))
  await assert.rejects(client.status(), { code: 'response_too_large' })
})
test('request timeout and explicit cancellation are classified', async () => {
  const hanging = (_url, options) => new Promise((_resolve, reject) => {
    if (options.signal.aborted) reject(new Error('abort'))
    else options.signal.addEventListener('abort', () => reject(new Error('abort')), { once: true })
  })
  await assert.rejects(createApiClient(enabled, hanging, 15).status(), { code: 'timeout' })
  const controller = new AbortController(); controller.abort()
  await assert.rejects(createApiClient(enabled, hanging).status(controller.signal), { code: 'cancelled' })
})
test('empty or incompatible payload is rejected, not treated as healthy', () => {
  for (const value of [null, {}, { checks: [] }, { checks: 'up', alerts: [] }]) assert.throws(() => adaptStatus(value), { code: 'invalid_response' })
})
test('missing metrics stay null; zero is a real observation', () => {
  assert.equal(finite(null), null); assert.equal(finite(''), null); assert.equal(finite(false), null); assert.equal(finite('NaN'), null)
  const out = adaptStatus(status([{ target: 'debian', status: 'UP', sample_epoch: now, cpu_percent: 0, memory_percent: 101 }]), now)
  assert.equal(out.checks[0].cpu, 0); assert.equal(out.checks[0].memory, null)
})
test('stale, missing, and impossible timestamps cannot produce UP', () => {
  const out = adaptStatus(status([
    { target: 'old', status: 'UP', sample_epoch: now - 121 },
    { target: 'missing', status: 'UP' }, { target: 'future', status: 'UP', sample_epoch: 1e300 },
  ]), now)
  assert.ok(out.checks.every((c) => c.status === 'UNKNOWN' && c.stale))
})
test('snapshot ages to UNKNOWN while API is unavailable', () => {
  const out = adaptStatus(status([{ target: 'debian', status: 'UP', sample_epoch: now }]), now)
  assert.equal(out.checks[0].status, 'UP')
  assert.equal(ageSnapshot(out, now + 121).checks[0].status, 'UNKNOWN')
})
test('RouterOS resource and interface fields are normalized without inference', () => {
  const out = adaptStatus(status([
    { target: 'mikrotik_system', status: 'UP', sample_epoch: now, data: { '/system/resource': [{ 'cpu-load': '12', 'free-memory': '25', 'total-memory': '100' }] } },
    { target: 'mikrotik_interfaces', status: 'UP', sample_epoch: now, data: { '/interface': [{ name: 'ether1', running: 'true', 'rx-byte': '123' }, { name: 'ether2' }] } },
  ]), now)
  assert.equal(out.checks[0].cpu, 12); assert.equal(out.checks[0].memory, 75)
  assert.equal(out.interfaces[0].status, 'UP'); assert.equal(out.interfaces[0].rxBytes, 123)
  assert.equal(out.interfaces[1].status, 'UNKNOWN'); assert.equal(out.interfaces[0].txBytes, null)
})
test('adapter projects known fields instead of forwarding secrets or arbitrary log text', () => {
  const out = adaptStatus(status([{ target: 'debian', status: 'UP', sample_epoch: now, password: 'test-private-value', headers: { Authorization: 'test-private-value' }, raw_logs: 'test-private-value' }]), now)
  assert.equal(JSON.stringify(out).includes('test-private-value'), false)
})
test('events and history reject incompatible contracts and preserve gaps', () => {
  assert.throws(() => adaptEvents({ events: null }), { code: 'invalid_response' })
  assert.throws(() => adaptHistory({ target: 'docker', points: [] }, 'debian'), { code: 'invalid_response' })
  const points = adaptHistory({ target: 'debian', points: [{ time: now, cpu_percent: null, memory_percent: '42' }, { time: 1e300 }] }, 'debian')
  assert.equal(points.length, 1); assert.equal(points[0].cpu, null); assert.equal(points[0].memory, 42)
})
test('development proxy target is limited to loopback origins without credentials', () => {
  assert.equal(validateProxyTarget('http://127.0.0.1:18765'), 'http://127.0.0.1:18765')
  for (const value of ['http://192.168.20.195:8765', 'https://example.test', 'http://user:pass@localhost:80', 'http://localhost/api', 'ftp://localhost']) assert.throws(() => validateProxyTarget(value))
})
test('development gateway disallows administrative methods and endpoints', () => {
  assert.equal(isReadOnlyRequest('GET', '/nms-api/api/status', '/nms-api'), true)
  assert.equal(isReadOnlyRequest('GET', '/nms-api/api/history?target=debian', '/nms-api'), true)
  assert.equal(isReadOnlyRequest('POST', '/nms-api/api/status', '/nms-api'), false)
  assert.equal(isReadOnlyRequest('GET', '/nms-api/api/exec', '/nms-api'), false)
})
test('all 16 modules have unique routes and can be found by title', () => {
  assert.equal(modules.length, 16); assert.equal(new Set(modules.map((m) => m.path)).size, 16)
  for (const module of modules) assert.ok(searchModules(module.title).some((m) => m.id === module.id))
})
