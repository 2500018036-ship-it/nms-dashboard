const allowedEndpoints = new Set(['/api/status', '/api/events', '/api/history', '/api/devices', '/api/metrics', '/api/services', '/api/health', '/api/auth/session', '/api/logs', '/api/incidents'])
const credentialsPath = /^\/api\/platform\/credentials\/(?:integration\/(?:int_[a-f0-9]{24}|svc_[a-f0-9]{20})|inventory\/inv_[a-f0-9]{24}|device\/device_[a-f0-9]{12})$/
export function validateProxyTarget(value) {
  if (!value) return null
  const url = new URL(value)
  if (!['http:', 'https:'].includes(url.protocol) || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || url.username || url.password || url.pathname !== '/' || url.search || url.hash) throw new Error('NMS_API_TARGET must be a loopback HTTP(S) origin without credentials or path')
  return url.origin
}
export function isReadOnlyRequest(method, requestUrl, base) {
  if (method !== 'GET') return false
  const path = new URL(requestUrl, 'http://localhost').pathname.slice(base.length)
  return /^\/api\/platform(?:$|\/(?:access|settings|export|users|audit|report|application-logs|assistant-history|device-backups(?:\/runs\/run_[a-f0-9]{24}|\/backup_[a-f0-9]{24}|\/compare)?|monitoring\/enrollment|(?:integrations|topologies|inventory|maintenance)(?:\/[a-z0-9_]{1,80})?|jobs\/job_[a-f0-9]{24})$)/.test(path) || credentialsPath.test(path) || allowedEndpoints.has(path) || /^\/api\/devices\/device_[a-f0-9]{12}$/.test(path) || /^\/api\/incidents\/inc_(event_[1-9]\d{0,14}|state_[a-f0-9]{20})$/.test(path)
}
export function isGatewayRequest(method, requestUrl, base) {
  const path = new URL(requestUrl, 'http://localhost').pathname.slice(base.length)
  return isReadOnlyRequest(method, requestUrl, base) || method === 'POST' && (['/api/auth/login', '/api/auth/logout'].includes(path) || credentialsPath.test(path) || /^\/api\/platform\/(?:settings|restore|users|ask|topology-verify|monitoring\/routeros\/read|device-backups(?:\/inv_[a-f0-9]{24}\/(?:run|policy)|\/backup_[a-f0-9]{24}\/restore)?|inventory\/import|(?:integrations|topologies|inventory|maintenance)(?:\/[a-z0-9_]{1,80}(?:\/(?:delete|test))?)?|acknowledge\/inc_(?:event_[1-9]\d{0,14}|state_[a-f0-9]{20}))$/.test(path))
}
export function sameOriginRequest(headers) {
  try { const origin = new URL(headers.origin); return ['http:', 'https:'].includes(origin.protocol) && origin.host === headers.host && headers['sec-fetch-site'] !== 'cross-site' }
  catch { return false }
}
export function readOnlyGateway(base) {
  return { name: 'nms-read-only-development-gateway', configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (!req.url?.startsWith(`${base}/`)) return next()
      if (req.headers['sec-fetch-site'] === 'cross-site' || req.method === 'POST' && !sameOriginRequest(req.headers)) {
        res.writeHead(403, { 'Content-Type': 'application/json' }); res.end('{"error":"origin_denied"}'); return
      }
      if (!isGatewayRequest(req.method, req.url, base)) {
        res.writeHead(405, { 'Content-Type': 'application/json', Allow: 'GET' })
        res.end('{"error":"read_only_endpoint_required"}'); return
      }
      next()
    })
  } }
}
