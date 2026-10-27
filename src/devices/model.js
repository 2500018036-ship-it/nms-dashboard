export const deviceTypes = ['router', 'switch', 'server', 'hypervisor', 'container-host', 'dns', 'vpn', 'service', 'access-point','firewall','iot','generic','other']
export const methods = ['icmp', 'tcp', 'snmp', 'api', 'agent', 'http', 'dns']
export const profiles = {
  connectivity: { label: 'Connectivity', metrics: ['Availability', 'Latency', 'Packet loss jika tersedia'] },
  network: { label: 'Network interfaces', metrics: ['Interface', 'RX/TX', 'Utilisasi', 'Error/drop jika tersedia'] },
  host: { label: 'Host resources', metrics: ['CPU', 'RAM', 'Disk', 'Uptime'] },
  virtualization: { label: 'Virtualization', metrics: ['Node', 'VM/LXC', 'Storage'] },
  services: { label: 'Service health', metrics: ['HTTP/DNS/API availability', 'Response time'] },
  custom: { label: 'Custom / capability-based', metrics: ['Metrik mengikuti kemampuan collector'] },
}
const allowed = new Set(['id', 'name', 'host', 'type', 'vendor', 'model', 'methods', 'interval', 'group', 'tags', 'profile', 'enabled','location','role','hostname','credential_ref','monitor_method','monitor_port','monitor_url','dns_query','mac_address','follow_dhcp'])
const clean = (v) => typeof v === 'string' ? v.trim() : ''
export class DeviceError extends Error {
  constructor(code, errors = {}) { super(code); this.code = code; this.errors = errors }
}
export function validHost(value) {
  if (typeof value !== 'string' || value.length > 253 || /[\s/@?#%\\]/.test(value)) return false
  if (value.includes(':')) {
    try { return new URL(`http://[${value}]/`).hostname.startsWith('[') } catch { return false }
  }
  if (/^[\d.]+$/.test(value)) return value.split('.').length === 4 && value.split('.').every((n) => /^(0|[1-9]\d{0,2})$/.test(n) && Number(n) <= 255)
  return value.replace(/\.$/, '').split('.').every((part) => /^(?!-)[a-zA-Z0-9-]{1,63}(?<!-)$/.test(part))
}
export function validateDevice(input, existing = [], editingId = null) {
  const errors = {}
  if (!input || typeof input !== 'object' || Array.isArray(input)) return { errors: { form: 'Konfigurasi perangkat harus berupa objek.' }, value: null }
  if (Object.keys(input).some((key) => !allowed.has(key))) errors.form = 'Field tidak dikenal atau credential tidak diperbolehkan.'
  const value = {
    id: clean(input.id), name: clean(input.name), host: clean(input.host).toLowerCase().replace(/\.$/, ''),
    type: input.type, vendor: clean(input.vendor), model: clean(input.model),
    methods: Array.isArray(input.methods) ? [...new Set(input.methods)] : [],
    interval: typeof input.interval === 'number' || typeof input.interval === 'string' && /^\d+$/.test(input.interval) ? Number(input.interval) : NaN,
    group: clean(input.group), tags: Array.isArray(input.tags) ? [...new Set(input.tags.map(clean).filter(Boolean))] : [],
    profile: input.profile, enabled: input.enabled ?? true,
  }
  if (value.id && !/^[\w-]{1,80}$/.test(value.id)) errors.id = 'ID tidak valid.'
  // eslint-disable-next-line no-control-regex -- Reject control characters in inventory names.
  if (!value.name || value.name.length > 80 || /[\u0000-\u001f]/.test(value.name)) errors.name = 'Nama wajib diisi, maksimum 80 karakter.'
  if (!validHost(value.host)) errors.host = 'Gunakan IPv4, IPv6, atau hostname tanpa URL, port, dan credential.'
  if (existing.some((d) => d.id !== editingId && d.host === value.host)) errors.host = 'Alamat sudah digunakan oleh perangkat lain.'
  if (!deviceTypes.includes(value.type)) errors.type = 'Pilih tipe perangkat.'
  if (!value.methods.length || value.methods.some((m) => !methods.includes(m))) errors.methods = 'Pilih minimal satu metode monitoring yang tersedia.'
  if (!Number.isInteger(value.interval) || value.interval < 15 || value.interval > 86400) errors.interval = 'Interval harus bilangan bulat 15â€“86400 detik.'
  if (typeof value.profile !== 'string' || !Object.hasOwn(profiles, value.profile)) errors.profile = 'Pilih profil monitoring.'
  if (value.vendor.length > 80 || value.model.length > 80) errors.vendor = 'Vendor/model maksimum 80 karakter.'
  if (value.group.length > 48) errors.group = 'Grup maksimum 48 karakter.'
  if (value.tags.length > 10 || value.tags.some((t) => !/^[\w-]{1,32}$/.test(t))) errors.tags = 'Maksimum 10 tag, gunakan huruf, angka, _ atau - (32 karakter/tag).'
  if (input.tags !== undefined && !Array.isArray(input.tags)) errors.tags = 'Tag harus berupa array.'
  if (Array.isArray(input.tags) && input.tags.some((v) => typeof v !== 'string')) errors.tags = 'Setiap tag harus berupa teks.'
  for (const key of ['id', 'vendor', 'model', 'group']) if (input[key] !== undefined && typeof input[key] !== 'string') errors[key] = 'Field harus berupa teks.'
  if (input.enabled !== undefined && typeof input.enabled !== 'boolean') errors.enabled = 'Status aktif harus boolean.'
  for(const key of ['location','role','hostname','credential_ref','monitor_method','monitor_port','monitor_url','dns_query','mac_address','follow_dhcp']) if(input[key]!==undefined)value[key]=input[key]
  if (value.mac_address !== undefined && (typeof value.mac_address !== 'string' || value.mac_address && !/^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(value.mac_address))) errors.mac_address = 'Gunakan MAC dengan format AA:BB:CC:DD:EE:FF.'
  if (value.follow_dhcp !== undefined && typeof value.follow_dhcp !== 'boolean') errors.follow_dhcp = 'Pilihan DHCP tidak valid.'
  if (value.follow_dhcp && (!value.mac_address || value.monitor_method !== 'icmp')) errors.mac_address = 'Pelacakan DHCP memerlukan MAC dan metode ICMP.'
  return { errors, value: Object.keys(errors).length ? null : value }
}
export function validatedDevice(input, existing = [], editingId = null) {
  const result = validateDevice(input, existing, editingId)
  if (!result.value) throw new DeviceError('validation_failed', result.errors)
  return result.value
}
export const newDevice = () => ({ name: '', host: '', type: 'other', vendor: '', model: '', methods: ['icmp'], interval: 30, group: '', tags: [], profile: 'connectivity', enabled: true })
export function parseInventory(text, existing = []) {
  if (typeof text !== 'string' || new TextEncoder().encode(text).length > 262144) throw new DeviceError('import_too_large')
  let data
  try { data = JSON.parse(text) } catch { throw new DeviceError('invalid_json') }
  if (!data || data.schemaVersion !== 1 || !Array.isArray(data.devices) || !data.devices.length || data.devices.length > 200 || Object.keys(data).some((k) => !['schemaVersion', 'source', 'devices'].includes(k))) throw new DeviceError('invalid_inventory')
  const result = []; const ids = new Set(existing.map((d) => d.id))
  for (let i = 0; i < data.devices.length; i++) {
    const value = validatedDevice(data.devices[i], [...existing, ...result])
    if (value.id && ids.has(value.id)) throw new DeviceError('duplicate_id', { form: `ID duplikat pada baris ${i + 1}.` })
    if (value.id) ids.add(value.id)
    result.push(value)
  }
  return result
}
export function exportInventory(devices, source) {
  return JSON.stringify({ schemaVersion: 1, source, devices: devices.map((d) => validatedDevice(Object.fromEntries([...allowed].filter((k) => k in d).map((k) => [k, d[k]])))) }, null, 2)
}
export function validateScope(value) {
  const [host, prefix, extra] = clean(value).split('/')
  return !extra && /^\d+$/.test(prefix || '') && /^\d+\.\d+\.\d+\.\d+$/.test(host || '') && validHost(host) && Number(prefix) >= 24 && Number(prefix) <= 32
}
export const deviceErrorMessage = (error) => ({
  backend_not_integrated: 'Operasi belum terintegrasi dengan backend. Tidak ada perubahan perangkat.',
  validation_failed: 'Konfigurasi belum valid. Periksa field yang ditandai.',
  invalid_json: 'JSON tidak valid.', invalid_inventory: 'Gunakan schemaVersion 1 dan 1â€“200 perangkat.',
  import_too_large: 'Ukuran import maksimum 256 KiB.', duplicate_id: 'ID perangkat duplikat.',
  not_found: 'Perangkat tidak ditemukan.', invalid_scope: 'Gunakan subnet IPv4 /24â€“/32 untuk rancangan discovery ini.',
  invalid_note: 'Catatan maksimum 300 karakter.',
}[error.code] || 'Operasi belum dapat diselesaikan.')
