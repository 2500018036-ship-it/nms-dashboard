export const modules = [
  { id: 'overview', path: '/', title: 'Ringkasan', icon: 'grid-1x2', group: 'Workspace', description: 'Satu tempat untuk memahami kondisi infrastruktur homelab.' },
  { id: 'access', path: '/access', title: 'Portal Akses Terpusat', navTitle: 'Portal Akses', icon: 'window-stack', group: 'Workspace', description: 'GUI asli perangkat dan layanan di area NMS melalui sesi akses privat.' },
  { id: 'network', path: '/network', title: 'Pemantauan Jaringan', icon: 'activity', group: 'Workspace', description: 'Interface, trafik, routing, dan konektivitas VPN.' },
  { id: 'servers', path: '/servers', title: 'Server dan Layanan', icon: 'hdd-stack', group: 'Workspace', description: 'Resource host, container, virtual machine, dan layanan.' },
  { id: 'topology', path: '/topology', title: 'Topologi', icon: 'diagram-3', group: 'Workspace', description: 'Hubungan antarperangkat berdasarkan data topologi yang terverifikasi.' },
  { id: 'devices', path: '/devices', title: 'Manajemen Perangkat dan Penemuan Otomatis', navTitle: 'Perangkat dan Penemuan', icon: 'router', group: 'Workspace', description: 'Inventaris hasil collector dan kesiapan penemuan perangkat.' },
  { id: 'alerts', path: '/alerts', title: 'Peringatan dan Insiden', icon: 'bell', group: 'Workspace', description: 'Alert aktif dan kronologi kejadian dari sistem monitoring.' },
  { id: 'assistant', path: '/assistant', title: 'Asisten AI NMS', icon: 'stars', group: 'Workspace', description: 'Ruang analisis berbasis bukti monitoring, saat API asisten tersedia.' },
  { id: 'logs', path: '/logs', title: 'Log dan Pemantauan', icon: 'terminal', group: 'Observability', description: 'Fondasi penelusuran log aplikasi, perangkat, dan collector.' },
  { id: 'reports', path: '/reports', title: 'Laporan dan Riwayat', icon: 'bar-chart-line', group: 'Observability', description: 'Riwayat resource dan kejadian untuk evaluasi operasional.' },
  { id: 'health', path: '/system-health', title: 'Kesehatan Sistem NMS', icon: 'heart-pulse', group: 'Observability', description: 'Koneksi data, kesegaran sampel, dan kesiapan collector NMS.' },
  { id: 'settings', path: '/settings', title: 'Pengaturan Sistem', icon: 'sliders2', group: 'Administration', description: 'Konfigurasi sistem dan kebijakan operasional.' },
  { id: 'management', path: '/management', title: 'Perangkat dan Inventaris', navTitle: 'Perangkat', icon: 'router', group: 'Administration', description: 'Wizard onboarding, monitoring, dan akses GUI asli perangkat.' },
  { id: 'backups', path: '/backups', title: 'Backup & Restore Perangkat', navTitle: 'Backup perangkat', icon: 'archive', group: 'Administration', description: 'Arsip konfigurasi terenkripsi untuk adapter perangkat yang mendukung export baca-saja.' },
  { id: 'integrations', path: '/integrations', title: 'Integrasi dan Kredensial', navTitle: 'Integrasi', icon: 'plug', group: 'Administration', description: 'Status integrasi API dan batas akses frontend.' },
  { id: 'users', path: '/users', title: 'Pengguna dan Log Audit', icon: 'people', group: 'Administration', description: 'Fondasi pengelolaan akses dan jejak audit administratif.' },
]

export const moduleById = (id) => modules.find((item) => item.id === id)
export const searchModules = (query) => modules.filter((item) =>
  `${item.title} ${item.description}`.toLocaleLowerCase('id').includes(query.trim().toLocaleLowerCase('id')))
