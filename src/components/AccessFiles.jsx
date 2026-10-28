import { useState } from 'react'
import { accessErrors, accessRequest } from '../data/accessClient'

export function AccessFiles({ session }) {
  const [files, setFiles] = useState([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const upload = async (event) => {
    const input = event.currentTarget
    const file = input.files?.[0]
    if (!file) return
    if (file.size > 15 * 1024 * 1024) { setMessage('Ukuran berkas maksimum 15 MiB.'); input.value = ''; return }
    setBusy(true)
    try {
      const body = new FormData(); body.append('file', file)
      const response = await fetch('/access-api/sessions/' + session.id + '/upload', { method: 'POST', body, credentials: 'same-origin', redirect: 'error' })
      if (!response.ok) throw new Error('unavailable')
      const value = await response.json()
      setMessage('Berkas tersedia di ' + value.remote_path + '. Pilih lokasi ini dari dialog unggah GUI asli.')
    } catch (e) { setMessage(accessErrors[e.message] || accessErrors.unavailable) } finally { setBusy(false); input.value = '' }
  }
  return <details className="border rounded p-3 mt-3"><summary>Berkas sesi GUI</summary>
    <p className="small text-muted mt-2">Berkas berada di sesi privat dan dihapus saat sesi ditutup. Maksimum 15 MiB per berkas.</p>
    <div className="d-flex flex-wrap gap-2 align-items-center"><label className="btn btn-sm btn-outline-secondary mb-0">Unggah ke sesi<input className="visually-hidden" type="file" disabled={busy} onChange={upload} /></label>
      <button className="btn btn-sm btn-outline-secondary" onClick={() => accessRequest('/sessions/' + session.id + '/downloads').then((v) => setFiles(v.items)).catch((e) => setMessage(accessErrors[e.message] || accessErrors.unavailable))}>Lihat hasil unduhan GUI</button></div>
    {message && <p className="small mt-2 mb-0" role="status">{message}</p>}
    {!!files.length && <ul className="mt-3 mb-0">{files.map((file) => <li key={file.name}><a href={'/access-api/sessions/' + session.id + '/downloads/' + encodeURIComponent(file.name)} download>{file.name}</a> <span className="small text-muted">({file.bytes} byte)</span></li>)}</ul>}
  </details>
}
