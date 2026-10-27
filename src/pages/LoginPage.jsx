import { useState, useEffect } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from '../data/authSessionContext'
import { safeReturnPath, validateLogin } from '../data/authModel'
import { errorMessages } from '../data/apiClient'
import { Icon } from '../components/ui'

export function LoginPage() {
  const { status, login, error: sessionError } = useAuth(); const location = useLocation()
  const [form, setForm] = useState({ username: '', password: '' }); const [remember, setRemember] = useState(false)
  const [showPassword, setShowPassword] = useState(false); const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(''); const [errors, setErrors] = useState({})
  const [theme, setTheme] = useState(() => { try { return localStorage.getItem('nms.ui.theme') === 'light' ? 'light' : 'dark' } catch { return 'dark' } })
  useEffect(() => { document.title = 'Masuk · NMS Homelab'; document.documentElement.dataset.bsTheme = theme; try { localStorage.setItem('nms.ui.theme', theme) } catch { /* Preference only. */ } }, [theme])
  if (status === 'authenticated') return <Navigate to={safeReturnPath(location.state?.from)} replace />
  const submit = async (event) => {
    event.preventDefault(); if (submitting) return
    const invalid = validateLogin(form); setErrors(invalid); setError('')
    if (Object.keys(invalid).length) { document.getElementById(invalid.username ? 'login-username' : 'login-password')?.focus(); return }
    setSubmitting(true)
    try { await login({ ...form, remember }); setForm((f) => ({ ...f, password: '' })) }
    catch (e) { setError(errorMessages[e.code] || 'Autentikasi belum dapat diselesaikan. Coba lagi.'); setForm((f) => ({ ...f, password: '' })) }
    finally { setSubmitting(false) }
  }
  return <div className="auth-layout"><main className="auth-main">
    <div className="auth-topbar"><a className="auth-brand" href="/login"><img src="/metis/logo.svg" alt="" /><span>NMS Homelab</span></a><button type="button" className="btn btn-sm btn-outline-secondary" aria-label="Ganti tema" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}><Icon name={theme === 'dark' ? 'moon-fill' : 'sun-fill'} /></button></div>
    <div className="auth-body"><div className="auth-heading"><h1>Masuk ke dashboard</h1><p>Masuk untuk memantau homelab dan mengelola konfigurasi NMS sesuai role.</p></div>
      {(sessionError === 'session_expired' || location.state?.expired) && <div className="alert alert-info small" role="status">Sesi berakhir. Silakan masuk kembali.</div>}
      {status === 'error' && <div className="alert alert-warning small" role="status">{errorMessages[sessionError] || 'Sesi belum dapat diperiksa'}. Pastikan koneksi backend tersedia.</div>}
      {error && <div className="alert alert-danger small" role="alert">{error}</div>}
      <form className="auth-form" onSubmit={submit} noValidate aria-busy={submitting}>
        <div className="mb-3"><label className="form-label" htmlFor="login-username">Username</label><input id="login-username" className={`form-control ${errors.username ? 'is-invalid' : ''}`} autoComplete="username" autoCapitalize="none" spellCheck={false} maxLength={80} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="Username dashboard" aria-invalid={!!errors.username} aria-describedby={errors.username ? 'username-error' : undefined} disabled={submitting} required />{errors.username && <div id="username-error" className="invalid-feedback">{errors.username}</div>}</div>
        <div className="mb-3"><label className="form-label" htmlFor="login-password">Password</label><div className="auth-password"><input id="login-password" type={showPassword ? 'text' : 'password'} className={`form-control ${errors.password ? 'is-invalid' : ''}`} autoComplete="current-password" maxLength={512} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Password dashboard" aria-invalid={!!errors.password} aria-describedby={errors.password ? 'password-error' : undefined} disabled={submitting} required /><button className="auth-password-toggle" type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? 'Sembunyikan password' : 'Tampilkan password'}><Icon name={showPassword ? 'eye-slash' : 'eye'} /></button></div>{errors.password && <div id="password-error" className="invalid-feedback d-block">{errors.password}</div>}</div>
        <div className="form-check mb-4"><input id="login-remember" type="checkbox" className="form-check-input" checked={remember} disabled={submitting} onChange={(e) => setRemember(e.target.checked)} /><label className="form-check-label small" htmlFor="login-remember">Tetap masuk hingga 7 hari di perangkat ini</label></div>
        <button className="btn btn-primary w-100" disabled={submitting || status === 'checking'}>{submitting && <span className="spinner-border spinner-border-sm me-2" aria-hidden="true" />}{submitting ? 'Memeriksa akun…' : status === 'checking' ? 'Memeriksa sesi…' : 'Masuk'}</button>
      </form><p className="auth-footnote">Hak akses mengikuti role akun. Hubungi pengelola server jika Anda belum memiliki akun dashboard.</p>
    </div><p className="auth-legal">Sesi diverifikasi oleh server. Password tidak disimpan di browser.</p>
  </main><aside className="auth-aside"><div className="auth-aside-inner"><p className="auth-quote">Kondisi jaringan, berdasarkan data yang terukur.</p><ul className="auth-points"><li><Icon name="check" /><span>Dashboard membaca cache monitoring yang sama dengan bot Telegram.</span></li><li><Icon name="check" /><span>Data belum tersedia dan sampel kedaluwarsa ditampilkan secara jelas.</span></li><li><Icon name="check" /><span>Credential perangkat tetap berada di server.</span></li><li><Icon name="check" /><span>Layout, kontrol, serta tema mengikuti template Metis.</span></li></ul><dl className="auth-stats"><div><dt>14</dt><dd>Modul dashboard</dd></div><div><dt>Read-only</dt><dd>Akses monitoring</dd></div></dl></div></aside></div>
}
