import { createMemoryDeviceService } from '../../devices/service.js'

// Synthetic documentation-range addresses. This module is dynamically imported only in DEV.
export function createDemoSession() {
  const time = Math.floor(Date.now() / 1000)
  const device = (id, name, host, type, methods, profile, group) => ({ id, name, host, type, methods, profile, group, interval: 30, vendor: 'Example vendor', model: 'Generic', tags: ['demo'], enabled: true })
  const inventory = [
    device('demo-router', 'DEMO-CORE-ROUTER', '192.0.2.1', 'router', ['snmp', 'icmp'], 'network', 'Network'),
    device('demo-switch', 'DEMO-ACCESS-SWITCH', '192.0.2.2', 'switch', ['snmp'], 'network', 'Network'),
    device('demo-host', 'DEMO-APPLICATION-HOST', '192.0.2.10', 'server', ['agent'], 'host', 'Compute'),
    device('demo-pve', 'DEMO-HYPERVISOR', '192.0.2.30', 'hypervisor', ['api'], 'virtualization', 'Compute'),
    device('demo-dns', 'DEMO-DNS', '192.0.2.53', 'dns', ['dns'], 'services', 'Services'),
    device('demo-web', 'DEMO-WEB', 'web.example.test', 'service', ['http'], 'services', 'Services'),
  ]
  const candidates = [{ id: 'demo-found-40', device: device('demo-found-40', 'DEMO-DISCOVERED-SERVER', '192.0.2.40', 'server', ['icmp'], 'connectivity', 'Discovered'), approved: false }, { id: 'demo-found-41', device: device('demo-found-41', 'DEMO-DISCOVERED-SWITCH', '192.0.2.41', 'switch', ['snmp'], 'network', 'Discovered'), approved: false }]
  const deviceService = createMemoryDeviceService(inventory, candidates)
  const sample = (target, method, status, values = {}) => ({ target, method, status, sample_epoch: time, ...values })
  const checks = [
    sample('demo-router', 'SNMP read-only · DEMO', 'UP', { host: '192.0.2.1', interfaces: [
      { name: 'uplink-1', type: 'ethernet', status: 'UP', mtu: 1500, rx_bps: 150000000, tx_bps: 42000000, capacity_bps: 1000000000, utilization_percent: 15, rx_bytes: 1980000000, tx_bytes: 800000000, sample_seconds: 30, rx_errors: 0, rx_drops: 0 },
      { name: 'lan-2', type: 'ethernet', status: 'DOWN', mtu: 1500, rx_bps: 0, tx_bps: 0, capacity_bps: 1000000000, utilization_percent: 0, rx_bytes: 450000, tx_bytes: 320000, sample_seconds: 30, rx_errors: 4, rx_drops: 1 },
    ] }),
    sample('demo-switch', 'SNMP read-only · DEMO', 'UP', { host: '192.0.2.2', interfaces: [{ name: 'port-1', type: 'ethernet', status: 'UP', rx_bps: 38000000, tx_bps: 11000000, capacity_bps: 1000000000, utilization_percent: 3.8, sample_seconds: 30 }] }),
    sample('debian', 'host /proc snapshot · DEMO', 'UP', { host: '192.0.2.10', cpu_percent: 27, memory_percent: 61, uptime_seconds: 456000, disks: [{ path: '/', used_percent: 48, total: 100000000000, used: 48000000000 }, { path: '/data', used_percent: 76, total: 500000000000, used: 380000000000 }] }),
    sample('docker', 'restricted collector · DEMO', 'DEGRADED', { containers: [
      { name: 'demo-nms', state: 'running', health: 'healthy', image: 'example/nms:demo', restart_count: 0, cpu_percent: 2.8, memory_bytes: 90000000, memory_limit_bytes: 512000000 },
      { name: 'demo-worker', state: 'running', health: 'unhealthy', image: 'example/worker:demo', restart_count: 4, cpu_percent: 104, memory_bytes: 200000000, memory_limit_bytes: 512000000 },
    ] }),
    sample('proxmox_resources', 'PVE API · DEMO', 'UP', { host: '192.0.2.30', nodes: [{ id: 'node/demo-node', node: 'demo-node', status: 'online', cpu: .34, mem: 6000000000, maxmem: 16000000000, disk: 25000000000, maxdisk: 100000000000, uptime: 900000 }], guests: [
      { id: 'qemu/101', vmid: 101, name: 'demo-app-vm', type: 'qemu', node: 'demo-node', status: 'running', cpu: .18, mem: 1000000000, maxmem: 2000000000, disk: 4000000000, maxdisk: 20000000000, uptime: 350000 },
      { id: 'lxc/201', vmid: 201, name: 'demo-tools-lxc', type: 'lxc', node: 'demo-node', status: 'stopped', cpu: 0, mem: 0, maxmem: 1000000000, disk: 1000000000, maxdisk: 10000000000, uptime: 0 },
    ] }),
    sample('demo-dns', 'DNS A · DEMO', 'UP', { host: '192.0.2.53', latency_ms: 3.2, query: 'example.test', answers: ['192.0.2.80'] }),
    sample('demo-web', 'HTTP GET · DEMO', 'UP', { host: 'web.example.test', latency_ms: 42, http_status: 200 }),
    sample('demo-connectivity', 'ICMP echo · DEMO', 'UP', { host: '192.0.2.1', latency_ms: 1.8, packet_loss_percent: 0.5 }),
  ]
  const alerts = [
    { key: 'demo:interface:lan-2', active: true, first_seen: time - 900, pending: { title: 'Interface lan-2 DOWN (demo)', device: 'DEMO-CORE-ROUTER', severity: 'CRITICAL' } },
    { key: 'demo:container:worker', active: true, first_seen: time - 300, pending: { title: 'Container worker unhealthy (demo)', device: 'DEMO-APPLICATION-HOST', severity: 'WARNING' } },
  ]
  const points = Array.from({ length: 24 }, (_, i) => ({ time: time - (23 - i) * 30, cpu_percent: Math.round(25 + Math.sin(i / 3) * 9), memory_percent: Math.round(57 + i / 6), latency_ms: 2 + i % 3 }))
  const trafficHistory = {
    'demo-router:uplink-1': points.map((p, i) => ({ time: p.time, rx: Math.round(100000000 + Math.sin(i / 4) * 35000000 + i * 2000000), tx: Math.round(33000000 + Math.sin(i / 3) * 7000000) })),
    'demo-router:lan-2': points.map((p) => ({ time: p.time, rx: 0, tx: 0 })),
    'demo-switch:port-1': points.map((p, i) => ({ time: p.time, rx: 30000000 + i * 350000, tx: 10000000 + i * 90000 })),
  }
  const events = { events: [
    ...alerts.map((a) => ({ key: a.key, time: a.first_seen, kind: 'alert', detail: a.pending })),
    { key: 'demo:web:availability', time: time - 1800, kind: 'recovery', detail: { title: 'HTTP service pulih (demo)', device: 'DEMO-WEB', severity: 'INFO' } },
  ] }
  const topology = {
    nodes: inventory.map((d) => ({ id: d.id, name: d.name, type: d.type, status: 'UP' })),
    links: [['demo-router', 'demo-switch', 'uplink-1'], ['demo-switch', 'demo-host', 'port-2'], ['demo-switch', 'demo-pve', 'port-3'], ['demo-switch', 'demo-dns', 'port-4'], ['demo-host', 'demo-web', 'HTTP']].map(([source, target, label], i) => ({ id: `demo-link-${i}`, source, target, label, evidence: 'Relasi ilustrasi DEMO', sampled: time, status: 'UNKNOWN' })),
  }
  return { deviceService, status: { checks, alerts, interval: 30, server_time: time }, events, history: (target) => ({ target, points: ['debian', 'mikrotik_system'].includes(target) ? points : [] }), trafficHistory, topology }
}
