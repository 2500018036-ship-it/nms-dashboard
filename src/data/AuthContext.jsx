import { useState, useEffect, useCallback, useRef } from 'react'
import { AuthContext } from './authSessionContext'
import { client, config } from './monitoringContext'
import { adaptSession, validateLogin } from './authModel'
import { ApiError } from './apiClient'

export function AuthProvider({ children }) {
  const [auth, setAuth] = useState({ status: 'checking', user: null, error: null })
  const sequence = useRef(0)
  const channel = useRef(null)
  const check = useCallback(async () => {
    const id = ++sequence.current
    try {
      const session = adaptSession(await client.session())
      if (id === sequence.current) setAuth({ status: 'authenticated', ...session, error: null })
    } catch (error) {
      if (id === sequence.current) setAuth({ status: error.code === 'auth_required' ? 'anonymous' : 'error', user: null, error: error.code || 'unavailable' })
    }
  }, [])
  useEffect(() => {
    // Never trust the former browser-only identity. Legacy inventory is left untouched but is not used as backend data.
    for (const key of ['nms.auth_session']) {
      try { localStorage.removeItem(key); sessionStorage.removeItem(key) } catch { /* Optional legacy cleanup. */ }
    }
    const startup = setTimeout(check, 0)
    const expired = () => { sequence.current++; setAuth({ status: 'anonymous', user: null, error: 'session_expired' }) }
    const focus = () => check()
    window.addEventListener('nms:auth-expired', expired); window.addEventListener('focus', focus)
    if (typeof BroadcastChannel !== 'undefined') {
      channel.current = new BroadcastChannel('nms-auth')
      channel.current.onmessage = check
    }
    const invalidate = () => { sequence.current++ }
    const cleanup = () => { clearTimeout(startup); invalidate(); channel.current?.close(); window.removeEventListener('nms:auth-expired', expired); window.removeEventListener('focus', focus) }
    return cleanup
  }, [check])
  useEffect(() => {
    if (auth.status !== 'authenticated') return
    const timer = setInterval(check, 60000)
    const expires = setTimeout(() => { sequence.current++; setAuth({ status: 'anonymous', user: null, error: 'session_expired' }) }, Math.max(0, auth.expiresAt * 1000 - Date.now()))
    return () => { clearInterval(timer); clearTimeout(expires) }
  }, [auth.status, auth.expiresAt, check])
  const login = async (input) => {
    if (Object.keys(validateLogin(input)).length) throw new ApiError('invalid_credentials')
    const id = ++sequence.current
    const session = adaptSession(await client.login({ ...input, username: input.username.trim() }))
    if (id === sequence.current) setAuth({ status: 'authenticated', ...session, error: null })
    channel.current?.postMessage('changed')
  }
  const logout = async () => {
    sequence.current++
    await client.logout()
    setAuth({ status: 'anonymous', user: null, error: null })
    channel.current?.postMessage('changed')
  }
  return <AuthContext.Provider value={{ ...auth, config, isAuthenticated: auth.status === 'authenticated', login, logout, check }}>{children}</AuthContext.Provider>
}
