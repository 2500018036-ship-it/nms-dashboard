import test from 'node:test'
import assert from 'node:assert/strict'
import { newDevice, validateDevice, validHost, parseInventory, exportInventory, validateScope } from '../src/devices/model.js'
import { createMemoryDeviceService, unavailableDeviceService } from '../src/devices/service.js'
import { adaptStatus, ageSnapshot } from '../src/data/adapters.js'
import { appendTrafficHistory } from '../src/data/coreAdapter.js'
import { createDemoSession } from '../src/data/demo/session.js'
import { formatBps, formatUptime } from '../src/data/format.js'

const device = (changes = {}) => ({ ...newDevice(), id: 'device-1', name: 'Example device', host: '192.0.2.10', ...changes })
const time = 1792560000
const payload = (checks) => ({ checks, alerts: [], server_time: time, interval: 30 })
const check = (target, extra = {}) => ({ target, status: 'UP', method: 'test', sample_epoch: time, ...extra })

test('device validation accepts IPv4, IPv6 and hostnames without locking vendor', () => {
  for (const host of ['192.0.2.10', '2001:db8::1', 'server.example.test', 'local-server']) assert.equal(validHost(host), true)
  for (const host of ['https://host', 'user:pass@host', 'host:8006', '999.1.2.3', 'host/path', '-bad.example', '']) assert.equal(validHost(host), false)
  for (const type of ['router', 'switch', 'server', 'dns', 'hypervisor', 'other']) assert.ok(validateDevice(device({ type })).value)
})
test('form rejects invalid interval, empty methods, unsupported profile and duplicate addresses', () => {
  assert.ok(validateDevice(device({ interval: 0 })).errors.interval)
  assert.ok(validateDevice(device({ interval: '15.5' })).errors.interval)
  assert.ok(validateDevice(device({ methods: [] })).errors.methods)
  assert.ok(validateDevice(device({ profile: 'unsupported' })).errors.profile)
  assert.ok(validateDevice(device({ id: 'device-2' }), [device()]).errors.host)
  assert.ok(validateDevice(device(), [device()], 'device-1').value)
})
test('credential and unknown fields are rejected on configuration import', () => {
  const parsed = (d) => parseInventory(JSON.stringify({ schemaVersion: 1, devices: [d] }))
  for (const field of ['password', 'token', 'community', 'private_key', '__proto__']) {
    const d = JSON.parse(JSON.stringify(device())); Object.defineProperty(d, field, { value: 'test-only-secret', enumerable: true })
    assert.throws(() => parsed(d), { code: 'validation_failed' })
  }
})
test('inventory import validates schema, size and duplicate IDs atomically', () => {
  assert.throws(() => parseInventory('{bad'), { code: 'invalid_json' })
  assert.throws(() => parseInventory('x'.repeat(262145)), { code: 'import_too_large' })
  assert.throws(() => parseInventory(JSON.stringify({ schemaVersion: 1, devices: [device(), device({ host: '192.0.2.11' })] })), { code: 'duplicate_id' })
  assert.throws(() => parseInventory(JSON.stringify({ devices: [device()] })), { code: 'invalid_inventory' })
})
test('export/import round trip preserves configuration and strips credentials/metrics', () => {
  const output = exportInventory([{ ...device(), password: 'test-only-secret', cpu_percent: 12 }], 'development-demonstration')
  assert.equal(output.includes('test-only-secret'), false); assert.equal(output.includes('cpu_percent'), false)
  assert.equal(parseInventory(output)[0].host, '192.0.2.10')
})
test('unavailable live service rejects every mutation or probe', async () => {
  assert.equal(unavailableDeviceService.canWrite, false)
  for (const name of ['create', 'update', 'remove', 'setEnabled', 'testConnection', 'discover', 'approve', 'import', 'acknowledge']) await assert.rejects(unavailableDeviceService[name](), { code: 'backend_not_integrated' })
})
test('memory device adapter supports create/edit/disable/delete without mutating callers', async () => {
  const original = device(); const service = createMemoryDeviceService([original])
  const created = await service.create(device({ id: '', name: 'Other vendor', host: '192.0.2.20', vendor: 'Vendor-neutral' }))
  assert.ok(created.id)
  await service.update(created.id, { ...created, name: 'Updated name' })
  await service.setEnabled(created.id, false)
  assert.equal(service.list().find((d) => d.id === created.id).enabled, false)
  const read = service.list(); read[0].name = 'not persisted'; assert.equal(service.list()[0].name, original.name)
  await service.remove(created.id); assert.equal(service.list().length, 1)
  await assert.rejects(service.update('missing', device()), { code: 'not_found' })
})
test('failed import does not partially write memory inventory', async () => {
  const service = createMemoryDeviceService([device()])
  const input = JSON.stringify({ schemaVersion: 1, devices: [device({ id: 'new-1', host: '192.0.2.20' }), device({ id: 'new-2' })] })
  await assert.rejects(service.import(input), { code: 'validation_failed' })
  assert.equal(service.list().length, 1)
})
test('discovery simulation respects scope and requires approval of discovered candidates', async () => {
  assert.equal(validateScope('192.0.2.0/24'), true); assert.equal(validateScope('0.0.0.0/0'), false)
  const service = createMemoryDeviceService([], [{ id: 'candidate', approved: false, device: device({ id: 'candidate' }) }])
  await assert.rejects(service.approve(['candidate']), { code: 'not_found' })
  assert.equal((await service.discover('198.51.100.0/24')).length, 0)
  assert.equal((await service.discover('192.0.2.0/24')).length, 1)
  assert.equal(service.list().length, 0)
  await service.approve(['candidate']); assert.equal(service.list().length, 1)
  await assert.rejects(service.approve(['candidate']), { code: 'not_found' })
})
test('simulated connection and acknowledgment never imply a network probe', async () => {
  const service = createMemoryDeviceService([device()])
  assert.equal((await service.testConnection('device-1')).simulated, true)
  await service.acknowledge('demo:alert', 'Reviewed in demo')
  assert.equal(service.acknowledgments()['demo:alert'].status, 'ACKNOWLEDGED')
  await assert.rejects(service.acknowledge('demo:alert', 'x'.repeat(301)), { code: 'invalid_note' })
})
test('traffic normalization joins real RouterOS rate data without summing interfaces', () => {
  const data = adaptStatus(payload([
    check('mikrotik_interfaces', { data: { '/interface': [{ name: 'ether1', running: 'true', 'rx-byte': '9000' }] } }),
    check('network_traffic', { interfaces: [{ name: 'ether1', rx_bps: 8000, tx_bps: 2000, capacity_bps: 100000000, utilization_percent: .008, sample_seconds: 15 }] }),
  ]), time)
  assert.equal(data.core.traffic[0].id, data.core.interfaces[0].id)
  assert.equal(data.core.traffic[0].rx, 8000); assert.equal(data.core.interfaces[0].rxBytes, 9000)
  assert.equal(data.core.traffic.length, 1)
})
test('missing packet loss and capacity stay unknown; ICMP UP is not zero loss', () => {
  const data = adaptStatus(payload([check('ping', { host: '192.0.2.1', method: 'ICMP echo', latency_ms: 1 })]), time)
  assert.equal(data.core.services[0].packetLoss, null); assert.equal(data.core.devices.length, 1)
})
test('Proxmox and Docker metrics use their actual units, including multicore CPU', () => {
  const data = adaptStatus(payload([
    check('proxmox_resources', { nodes: [{ id: 'node/a', node: 'a', status: 'online', cpu: .25, mem: 50, maxmem: 100 }], guests: [{ id: 'qemu/101', vmid: 101, name: 'example', type: 'qemu', status: 'running', cpu: .4, mem: 25, maxmem: 100 }] }),
    check('docker', { containers: [{ name: 'worker', state: 'running', health: 'not_configured', cpu_percent: 250, memory_bytes: 25, memory_limit_bytes: 100 }] }),
  ]), time)
  assert.equal(data.core.hosts[0].cpu, 25); assert.equal(data.core.guests[0].cpu, 40)
  assert.equal(data.core.containers[0].cpu, 250); assert.equal(data.core.containers[0].memory, 25)
  assert.equal(data.core.containers[0].health, 'not_configured')
})
test('resource, traffic and guest status age to UNKNOWN without false zeroes', () => {
  const data = adaptStatus(payload([check('debian', { cpu_percent: 10, memory_percent: 20, disks: [{ path: '/', used_percent: 30 }] }), check('router', { interfaces: [{ name: 'port1', status: 'UP', rx_bps: 20, tx_bps: 30 }] })]), time)
  const aged = ageSnapshot(data, time + 121)
  assert.equal(aged.core.hosts[0].cpu, null); assert.equal(aged.core.hosts[0].disks[0].percent, null)
  assert.equal(aged.core.traffic[0].rx, null); assert.equal(aged.core.interfaces[0].status, 'UNKNOWN')
})
test('traffic history deduplicates API snapshots and bounds memory', () => {
  let history = {}
  for (let i = 1; i <= 140; i++) history = appendTrafficHistory(history, [{ id: 'a:port', sampled: i, stale: false, rx: i, tx: 0 }])
  history = appendTrafficHistory(history, [{ id: 'a:port', sampled: 140, stale: false, rx: 999, tx: 999 }])
  assert.equal(history['a:port'].length, 120); assert.equal(history['a:port'].at(-1).rx, 140)
})
test('topology uses observed neighbor evidence and never fabricates link health', () => {
  const empty = adaptStatus(payload([check('router')]), time); assert.equal(empty.core.topology.links.length, 0)
  const data = adaptStatus(payload([check('router', { data: { '/ip/neighbor': [{ identity: 'neighbor', address: '192.0.2.2', interface: 'ether2' }] } })]), time)
  assert.equal(data.core.topology.links[0].evidence, 'Neighbor advertisement')
  assert.equal(data.core.topology.links[0].status, 'UNKNOWN')
})
test('development fixture is explicit, includes all monitoring categories, and uses documentation hosts', () => {
  const demo = createDemoSession(); const data = adaptStatus(demo.status, demo.status.server_time)
  assert.ok(data.core.hosts.length && data.core.guests.length && data.core.containers.length && data.core.services.length && data.core.interfaces.length)
  assert.ok(demo.deviceService.list().every((d) => d.host.startsWith('192.0.2.') || d.host.endsWith('.example.test')))
  assert.equal(demo.trafficHistory['demo-router:uplink-1'].length, 24)
})
test('formatters preserve zero and never label missing data as zero', () => {
  assert.equal(formatBps(null), '—'); assert.equal(formatBps(0), '0 bit/s'); assert.equal(formatBps(1000000), '1.0 Mbit/s')
  assert.equal(formatUptime(null), '—'); assert.equal(formatUptime(0), '0h 0j 0m')
})
test('explicit 100 percent loss on a fresh failed probe is retained', () => {
  const data = adaptStatus(payload([check('ping', { status: 'DOWN', method: 'ICMP batch', packet_loss_percent: 100 })]), time)
  assert.equal(data.core.services[0].packetLoss, 100)
})
test('traffic gaps and topology age preserve uncertainty', () => {
  const history = appendTrafficHistory({}, [{ id: 'p', sampled: time, stale: false, rx: null, tx: null }])
  assert.equal(history.p[0].rx, null)
  const data = adaptStatus(payload([check('router', { data: { '/ip/neighbor': [{ identity: 'switch', interface: 'port1' }] } })]), time)
  assert.equal(ageSnapshot(data, time + 121).core.topology.nodes.find((n) => n.id === 'router').status, 'UNKNOWN')
})
test('malformed field types are rejected without coercion or exceptions', () => {
  assert.ok(validateDevice(device({ profile: { toString: 'not a function' }, interval: { toString: 'invalid' }, tags: [42], enabled: null })).errors.profile)
  assert.ok(validateDevice(device({ vendor: {} })).errors.vendor)
})
test('stale absolute container memory and guest uptime are not displayed as current', () => {
  const data = adaptStatus(payload([check('docker', { containers: [{ name: 'example', state: 'running', memory_bytes: 100 }] }), check('pve', { guests: [{ id: 'qemu/1', status: 'running', uptime: 100 }] })]), time)
  const aged = ageSnapshot(data, time + 121)
  assert.equal(aged.core.containers[0].memoryBytes, null)
  assert.equal(aged.core.guests[0].uptime, null)
})
