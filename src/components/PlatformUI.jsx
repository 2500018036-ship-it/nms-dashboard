import { errorMessages } from '../data/apiClient'
import { Badge } from './ui'
export function Feedback({ error, message }) { return error ? <div className="alert alert-danger" role="alert">{errorMessages[error] || errorMessages.unavailable}</div> : message ? <div className="alert alert-success" role="status">{message}</div> : null }
export function AccessNote({ canManage }) { return !canManage && <div className="alert alert-secondary small"><i className="bi bi-shield-lock me-2" />Akun ini memiliki akses baca. Masuk sebagai Administrator untuk mengubah konfigurasi NMS.</div> }
export function Loading({ loading }) { return loading && <div className="d-flex gap-2 align-items-center py-3" role="status"><span className="spinner-border spinner-border-sm" />Memuat data server…</div> }
export function Launcher({ service, small = false }) {
  let safe = false
  try { const u = new URL(service.url); safe = ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password && !u.hash && !u.search } catch { /* Reject malformed server values. */ }
  return safe && service.enabled ? <a className={`btn btn-outline-primary ${small ? 'btn-sm' : ''}`} href={service.url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer"><i className="bi bi-box-arrow-up-right me-2" />Buka dashboard asli</a> : <Badge>Launcher nonaktif</Badge>
}
