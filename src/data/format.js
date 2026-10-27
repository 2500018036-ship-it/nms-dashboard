export function formatBps(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—'
  const units = ['bit/s', 'kbit/s', 'Mbit/s', 'Gbit/s', 'Tbit/s']; let i = 0
  while (value >= 1000 && i < units.length - 1) { value /= 1000; i++ }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`
}
export function formatUptime(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—'
  return `${Math.floor(seconds / 86400)}h ${Math.floor(seconds % 86400 / 3600)}j ${Math.floor(seconds % 3600 / 60)}m`
}
export function formatBytes(value) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '—'
  return `${(value / 1024 ** 2).toFixed(1)} MiB`
}
