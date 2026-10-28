// Navigation hints only. The server independently authorizes its exact target allowlist.
export function portalTarget(service) {
  try {
    const url = new URL(service.url)
    const host = url.hostname; const port = url.port || (url.protocol === 'https:' ? '443' : '80')
    if (host === '192.168.20.1' && port === '80') return 'mikrotik'
    if (host === '192.168.10.26' && port === '80') return 'cisco'
    if (['192.168.10.194', '192.168.30.194'].includes(host) && port === '80') return 'tplink'
    if (host === '192.168.20.200' && port === '8006') return 'proxmox'
    if (host === '192.168.20.199' && port === '5380') return 'technitium'
    if (host === '192.168.20.195' && port === '9443') return 'portainer'
    if (host === '192.168.20.195' && port === '81') return 'npm'
  } catch { /* Unknown targets are never forwarded from a client URL. */ }
  return null
}
