export const modules = [
  { id: 'overview', path: '/', title: 'Overview', icon: 'grid-1x2', group: 'Workspace', description: 'Satu tempat untuk memahami kondisi infrastruktur homelab.' },
  { id: 'network', path: '/network', title: 'Network Monitoring', icon: 'activity', group: 'Workspace', description: 'Interface, trafik, routing, dan konektivitas VPN.' },
  { id: 'servers', path: '/servers', title: 'Servers & Services', icon: 'hdd-stack', group: 'Workspace', description: 'Resource host, container, virtual machine, dan layanan.' },
  { id: 'topology', path: '/topology', title: 'Topology', icon: 'diagram-3', group: 'Workspace', description: 'Hubungan antarperangkat berdasarkan data topologi yang terverifikasi.' },
  { id: 'devices', path: '/devices', title: 'Device Management & Auto-Discovery', navTitle: 'Devices & Discovery', icon: 'router', group: 'Workspace', description: 'Inventaris hasil collector dan kesiapan penemuan perangkat.' },
  { id: 'alerts', path: '/alerts', title: 'Alerts & Incidents', icon: 'bell', group: 'Workspace', description: 'Alert aktif dan kronologi kejadian dari sistem monitoring.' },
  { id: 'assistant', path: '/assistant', title: 'AI NMS Assistant', icon: 'stars', group: 'Workspace', description: 'Ruang analisis berbasis bukti monitoring, saat API asisten tersedia.' },
  { id: 'logs', path: '/logs', title: 'Logs & Log Monitoring', icon: 'terminal', group: 'Observability', description: 'Fondasi penelusuran log aplikasi, perangkat, dan collector.' },
  { id: 'reports', path: '/reports', title: 'Reports & History', icon: 'bar-chart-line', group: 'Observability', description: 'Riwayat resource dan kejadian untuk evaluasi operasional.' },
  { id: 'health', path: '/system-health', title: 'NMS System Health', icon: 'heart-pulse', group: 'Observability', description: 'Koneksi data, kesegaran sampel, dan kesiapan collector NMS.' },
  { id: 'settings', path: '/settings', title: 'System Settings', icon: 'sliders2', group: 'Administration', description: 'Konfigurasi sistem dan kebijakan operasional.' },
  { id: 'management', path: '/management', title: 'Device Connections & Management', navTitle: 'Device Management', icon: 'tools', group: 'Administration', description: 'Pendaftaran collector, koneksi perangkat, preview dan konfirmasi perubahan.' },
  { id: 'integrations', path: '/integrations', title: 'Integrations & Credentials', navTitle: 'Integrations', icon: 'plug', group: 'Administration', description: 'Status integrasi API dan batas akses frontend.' },
  { id: 'users', path: '/users', title: 'Users & Audit Logs', icon: 'people', group: 'Administration', description: 'Fondasi pengelolaan akses dan jejak audit administratif.' },
]

export const moduleById = (id) => modules.find((item) => item.id === id)
export const searchModules = (query) => modules.filter((item) =>
  `${item.title} ${item.description}`.toLocaleLowerCase('id').includes(query.trim().toLocaleLowerCase('id')))
