import { modules } from '../app/modules.js'
import { ApiError } from './apiClient.js'

export function safeReturnPath(path) {
  return typeof path === 'string' && (modules.some((m) => m.path === path) || /^\/(devices\/device_[a-f0-9]{12}|integrations\/[a-z0-9_]{1,80}|virtualization)$/.test(path)) ? path : '/'
}
export function validateLogin({ username, password }) {
  const errors = {}
  if (typeof username !== 'string' || !username.trim() || username.length > 80) errors.username = 'Masukkan username, maksimum 80 karakter.'
  if (typeof password !== 'string' || !password || password.length > 512) errors.password = 'Masukkan password, maksimum 512 karakter.'
  return errors
}
export function adaptSession(payload) {
  if (!payload || typeof payload.user?.username !== 'string' || !/^[a-z][a-z0-9_-]{1,79}$/.test(payload.user.username) || !['Administrator','Super Administrator','Network Administrator','Server Administrator','Operator','Read-only operator','Viewer'].includes(payload.user?.role) ||
      typeof payload.expires_at !== 'number' || !Number.isFinite(payload.expires_at) || payload.expires_at <= Date.now() / 1000 ||
      !Number.isInteger(payload.idle_timeout_seconds) || payload.idle_timeout_seconds <= 0) throw new ApiError('invalid_response')
  return { user: { username: payload.user.username, name: typeof payload.user.name === 'string' ? payload.user.name.slice(0,80) : payload.user.username, role: payload.user.role }, expiresAt: payload.expires_at }
}
