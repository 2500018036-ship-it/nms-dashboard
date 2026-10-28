export const endpoints = [
  { path: '/api/status', feature: 'Snapshot collector & alert aktif', state: 'Adapter siap', method: 'GET' },
  { path: '/api/events', feature: 'Riwayat kejadian terbaru', state: 'Adapter siap', method: 'GET' },
  { path: '/api/history?target=debian', feature: 'Riwayat CPU, RAM & latensi', state: 'Adapter siap', method: 'GET' },
  { path: '/api/devices', feature: 'Perangkat dari konfigurasi collector (read-only)', state: 'Adapter siap', method: 'GET' },
  { path: '/api/services', feature: 'Kondisi layanan dari cache bersama', state: 'Adapter siap', method: 'GET' },
  { path: '/api/metrics?target=debian', feature: 'Metrik collector sesuai allowlist', state: 'Adapter siap', method: 'GET' },
  { path: '/api/health', feature: 'Heartbeat bot dan scheduler', state: 'Adapter siap', method: 'GET' },
]
export const pendingCapabilities = [
  ['Konfigurasi & credentials', 'Belum ditemukan endpoint penyimpanan konfigurasi atau secret.'],
  ['Penemuan otomatis & topology', 'Belum ditemukan API discovery, inventaris permanen, atau hubungan antarperangkat.'],
  ['AI assistant web', 'Belum ditemukan endpoint chat AI untuk dashboard.'],
  ['Log monitoring', 'Event monitoring tersedia pada kontrak lama; pengumpulan log mentah belum tersedia.'],
  ['Users & audit administratif', 'Sesi operator read-only tersedia; manajemen multi-user/RBAC dan audit administratif belum tersedia.'],
]
export const historyTargets = ['debian', 'mikrotik_system', 'docker', 'proxmox_resources']
export function readConfig(env = {}) {
  const base = env.VITE_NMS_API_BASE || '/nms-api'
  if (!/^\/[a-zA-Z0-9/_-]*$/.test(base) || base.startsWith('//')) return { enabled: false, base: '/nms-api', invalid: true }
  return { enabled: env.VITE_NMS_API_ENABLED === 'true', base: base.replace(/\/$/, ''), invalid: false }
}
