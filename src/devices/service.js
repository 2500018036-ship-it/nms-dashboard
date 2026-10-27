import { DeviceError, validatedDevice, parseInventory, validateScope } from './model.js'
export const unavailableDeviceService = {
  canWrite: false,
  list: () => [], candidates: () => [], acknowledgments: () => ({}),
  create: async () => { throw new DeviceError('backend_not_integrated') },
  update: async () => { throw new DeviceError('backend_not_integrated') },
  setEnabled: async () => { throw new DeviceError('backend_not_integrated') },
  remove: async () => { throw new DeviceError('backend_not_integrated') },
  testConnection: async () => { throw new DeviceError('backend_not_integrated') },
  discover: async () => { throw new DeviceError('backend_not_integrated') },
  approve: async () => { throw new DeviceError('backend_not_integrated') },
  import: async () => { throw new DeviceError('backend_not_integrated') },
  acknowledge: async () => { throw new DeviceError('backend_not_integrated') },
}
// In-memory adapter used only by the explicitly enabled development demonstration.
export function createMemoryDeviceService(seed = [], discovered = []) {
  let devices = seed.map((d) => validatedDevice(d)); let candidates = structuredClone(discovered); const acknowledgments = Object.create(null); const discoveredIds = new Set()
  const find = (id) => { const d = devices.find((item) => item.id === id); if (!d) throw new DeviceError('not_found'); return d }
  const add = (input) => ({ ...validatedDevice(input, devices), id: input.id || crypto.randomUUID() })
  return {
    canWrite: true, list: () => structuredClone(devices), candidates: () => structuredClone(candidates), acknowledgments: () => structuredClone(acknowledgments),
    async create(input) { const value = add(input); if (devices.some((d) => d.id === value.id)) throw new DeviceError('duplicate_id'); devices.push(value); return structuredClone(value) },
    async update(id, input) { find(id); const value = { ...validatedDevice({ ...input, id }, devices, id), id }; devices = devices.map((d) => d.id === id ? value : d); return structuredClone(value) },
    async setEnabled(id, enabled) { const d = find(id); if (typeof enabled !== 'boolean') throw new DeviceError('validation_failed'); d.enabled = enabled },
    async remove(id) { find(id); devices = devices.filter((d) => d.id !== id) },
    async testConnection(id) { const d = find(id); return { simulated: true, device: d.name, message: 'Simulasi alur uji koneksi selesai. Tidak ada request ICMP/SNMP/API ke perangkat.' } },
    async discover(scope) {
      if (!validateScope(scope)) throw new DeviceError('invalid_scope')
      const [address, prefix] = scope.split('/'); const mask = (0xffffffff << (32 - Number(prefix))) >>> 0
      const integer = (host) => host.split('.').reduce((sum, n) => (sum * 256 + Number(n)) >>> 0, 0)
      const found = candidates.filter((c) => !c.approved && /^\d+\.\d+\.\d+\.\d+$/.test(c.device.host) && ((integer(c.device.host) & mask) >>> 0) === ((integer(address) & mask) >>> 0))
      found.forEach((c) => discoveredIds.add(c.id)); return structuredClone(found)
    },
    async approve(ids) {
      if (!Array.isArray(ids) || !ids.length) throw new DeviceError('validation_failed')
      const selected = candidates.filter((c) => ids.includes(c.id) && !c.approved && discoveredIds.has(c.id))
      if (selected.length !== new Set(ids).size) throw new DeviceError('not_found')
      const values = selected.map((c) => ({ ...c.device, id: c.id }))
      const parsed = parseInventory(JSON.stringify({ schemaVersion: 1, devices: values }), devices)
      devices.push(...parsed); candidates = candidates.map((c) => ids.includes(c.id) ? { ...c, approved: true } : c)
      return parsed.length
    },
    async import(text) { const parsed = parseInventory(text, devices).map((d) => ({ ...d, id: d.id || crypto.randomUUID() })); devices.push(...parsed); return parsed.length },
    async acknowledge(key, note = '') { if (!key || typeof note !== 'string' || note.length > 300) throw new DeviceError('invalid_note'); acknowledgments[key] = { status: 'ACKNOWLEDGED', note: note.trim(), time: Date.now() / 1000 } },
  }
}
