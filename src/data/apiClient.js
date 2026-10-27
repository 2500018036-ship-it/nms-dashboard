import { historyTargets } from './capabilities.js'

export class ApiError extends Error {
  constructor(code) { super(code); this.name = 'ApiError'; this.code = code }
}
export function createApiClient(config, fetcher = globalThis.fetch, timeoutMs = 8000) {
  async function request(path, signal, body) {
    if (!config.enabled) throw new ApiError(config.invalid ? 'invalid_config' : 'not_configured')
    const controller = new AbortController()
    let timedOut = false
    const abort = () => controller.abort()
    if (signal?.aborted) abort()
    signal?.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(() => { timedOut = true; controller.abort() }, timeoutMs)
    try {
      const response = await fetcher(`${config.base}${path}`, {
        method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }), cache: 'no-store', redirect: 'error',
      })
      if (response.status === 401) {
        if (!path.startsWith('/api/auth/') && typeof window !== 'undefined') window.dispatchEvent(new Event('nms:auth-expired'))
        throw new ApiError(path === '/api/auth/login' ? 'invalid_credentials' : 'auth_required')
      }
      if (response.status === 403) throw new ApiError('permission_denied')
      if (response.status === 400) throw new ApiError('validation_failed')
      if (response.status === 409) throw new ApiError('revision_conflict')
      if (response.status === 429) throw new ApiError('rate_limited')
      if (response.status === 404) throw new ApiError('not_found')
      if (!response.ok) throw new ApiError('unavailable')
      if (!response.headers.get('content-type')?.includes('application/json')) throw new ApiError('invalid_response')
      const maxBytes = 2 * 1024 * 1024
      if (Number(response.headers.get('content-length')) > maxBytes) throw new ApiError('response_too_large')
      const reader = response.body?.getReader()
      if (!reader) throw new ApiError('invalid_response')
      const chunks = []; let length = 0
      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          length += value.byteLength
          if (length > maxBytes) { await reader.cancel(); throw new ApiError('response_too_large') }
          chunks.push(value)
        }
      } finally { reader.releaseLock() }
      const bytes = new Uint8Array(length); let offset = 0
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
      try { return JSON.parse(new TextDecoder().decode(bytes)) }
      catch { throw new ApiError('invalid_response') }
    } catch (error) {
      if (error instanceof ApiError) throw error
      throw new ApiError(timedOut ? 'timeout' : controller.signal.aborted ? 'cancelled' : 'unavailable')
    } finally {
      clearTimeout(timer); signal?.removeEventListener('abort', abort)
    }
  }
  const get = (path, signal) => request(path, signal)
  return {
    platform: (path = '', { body, params = {}, signal } = {}) => {
      const valid = /^(?:|settings|export|restore|users|audit|report|application-logs|ask|management(?:\/read|\/preview|\/plan_[a-f0-9]{24}\/confirm)?|inventory\/import|(?:integrations|topologies|inventory|maintenance)(?:\/[a-z0-9_]{1,80}(?:\/(?:delete|test))?)?|jobs\/job_[a-f0-9]{24}|acknowledge\/inc_(?:event_[1-9]\d{0,14}|state_[a-f0-9]{20}))$/.test(path)
      const allowed = path === 'report' ? ['target','from','to','resource'] : path === 'audit' ? ['page','q'] : path === 'application-logs' ? ['page','q','level','from','to'] : []
      if (!valid || Object.keys(params).some((key) => !allowed.includes(key))) return Promise.reject(new ApiError('target_not_allowed'))
      const query = new URLSearchParams(params)
      return request(`/api/platform${path ? '/' + path : ''}${query.size ? '?' + query : ''}`, signal, body)
    },
    status: (signal) => get('/api/status', signal), events: (signal) => get('/api/events', signal),
    session: (signal) => get('/api/auth/session', signal),
    login: ({ username, password, remember = false }, signal) => request('/api/auth/login', signal, { username, password, remember }),
    logout: (signal) => request('/api/auth/logout', signal, {}),
    credentials: (targetType, id, { credentials, signal } = {}) => {
      const validType = ['integration', 'inventory', 'device'].includes(targetType)
      const validId = targetType === 'integration' ? /^(?:int_[a-f0-9]{24}|svc_[a-f0-9]{20})$/.test(id || '')
        : targetType === 'inventory' ? /^inv_[a-f0-9]{24}$/.test(id || '')
          : targetType === 'device' ? /^device_[a-f0-9]{12}$/.test(id || '') : false
      if (!validType || !validId) return Promise.reject(new ApiError('target_not_allowed'))
      return request(`/api/platform/credentials/${targetType}/${id}`, signal, credentials === undefined ? undefined : { credentials })
    },
    devices: (signal) => get('/api/devices', signal),
    health: (signal) => get('/api/health', signal),
    services: (signal) => get('/api/services', signal),
    journal: (kind, params, signal) => {
      if (!['logs', 'incidents'].includes(kind)) return Promise.reject(new ApiError('target_not_allowed'))
      const allowed = new Set(['page','page_size','q','severity','device','from','to', ...(kind === 'logs' ? ['category','source'] : ['status'])])
      if (Object.keys(params).some((k) => !allowed.has(k))) return Promise.reject(new ApiError('invalid_filter'))
      const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== '' && value !== undefined))
      return get(`/api/${kind}?${query}`, signal)
    },
    incident: (id, signal) => typeof id === 'string' && /^inc_(event_[1-9]\d{0,14}|state_[a-f0-9]{20})$/.test(id) ? get(`/api/incidents/${id}`, signal) : Promise.reject(new ApiError('target_not_allowed')),
    device: (id, signal) => /^[a-z0-9_]{1,80}$/.test(id) ? get(`/api/devices/${id}`, signal) : Promise.reject(new ApiError('target_not_allowed')),
    history: (target, signal) => {
      if (!historyTargets.includes(target)) return Promise.reject(new ApiError('target_not_allowed'))
      return get(`/api/history?target=${encodeURIComponent(target)}`, signal)
    },
  }
}
export const errorMessages = {
  not_configured: 'API belum dihubungkan', invalid_config: 'Konfigurasi API tidak valid',
  auth_required: 'Autentikasi gateway diperlukan', rate_limited: 'API membatasi permintaan',
  unavailable: 'API belum dapat dijangkau', timeout: 'Waktu tunggu API habis',
  invalid_response: 'Format respons API belum sesuai', response_too_large: 'Respons API melewati batas aman',
  invalid_credentials: 'Username atau password tidak sesuai.',
  target_not_allowed: 'Target riwayat tidak diizinkan', cancelled: 'Permintaan dibatalkan',
  invalid_filter: 'Filter waktu tidak valid. Gunakan waktu WIB, urutan awal–akhir yang benar, dan rentang log maksimum 31 hari.',
  ai_unavailable: 'Provider AI belum dapat menyelesaikan jawaban. Monitoring dan notifikasi tetap berjalan.',
  permission_denied: 'Role akun ini tidak mengizinkan tindakan tersebut.',
  credential_vault_unavailable: 'Vault kredensial belum siap atau kunci server tidak valid. Kredensial tidak dibaca atau disimpan.',
  validation_failed: 'Konfigurasi ditolak server. Periksa field wajib, host yang diizinkan, format, dan batas nilai.',
  revision_conflict: 'Data sudah berubah di server atau alamat duplikat. Muat ulang sebelum menyimpan kembali.',
  not_found: 'Data atau endpoint tidak ditemukan',
}
