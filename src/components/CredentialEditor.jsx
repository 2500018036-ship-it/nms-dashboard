import { useEffect, useState } from 'react'
import { usePlatform } from '../data/platformContext'
import { errorMessages } from '../data/apiClient'
import { Icon } from './ui'

const emptyCredentials = () => ({ gui: { username: '', password: '', fields: [] }, wifi_networks: [], custom_fields: [] })
const newId = (prefix) => `${prefix}_${Math.random().toString(36).slice(2, 11)}`
const fieldTypes = ['text', 'username', 'password', 'ssid', 'secret', 'url', 'email', 'number', 'boolean', 'textarea', 'token', 'api_key']

function Input({ label, type = 'text', value, onChange, readOnly = false, reveal, onReveal, maxLength = 4096 }) {
  const hidden = ['password', 'secret', 'token', 'api_key'].includes(type) && !reveal
  const htmlType = hidden ? 'password' : ['username', 'ssid', 'text', 'secret', 'token', 'api_key'].includes(type) ? 'text' : type
  const props = { className: 'form-control', value: value ?? '', readOnly, maxLength, autoComplete: hidden ? 'new-password' : 'off', spellCheck: false, onChange: (event) => onChange(event.target.value) }
  return <div><label className="form-label">{label}</label><div className="input-group">{type === 'textarea' ? <textarea {...props} rows="2" /> : type === 'boolean' ? <select {...props} disabled={readOnly}><option value="">Pilih</option><option value="true">Ya</option><option value="false">Tidak</option></select> : <input {...props} type={htmlType} />}{['password', 'secret', 'token', 'api_key'].includes(type) && <button className="btn btn-outline-secondary" type="button" aria-label={reveal ? `Sembunyikan ${label}` : `Tampilkan ${label}`} onClick={onReveal}><Icon name={reveal ? 'eye-slash' : 'eye'} /></button>}</div></div>
}

function FieldList({ title, fields, onChange, disabled, reveal, toggleReveal }) {
  const set = (index, key, value) => onChange(fields.map((field, i) => i === index ? { ...field, [key]: value } : field))
  return <div className="mt-3"><div className="d-flex justify-content-between align-items-center gap-2 mb-2"><h4 className="h6 mb-0">{title}</h4>{!disabled && <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => onChange([...fields, { id: newId('field'), label: '', type: 'text', value: '' }])}><Icon name="plus-lg" className="me-1" />Tambah field</button>}</div>
    {!fields.length && <p className="small text-muted mb-2">Belum ada field tambahan.</p>}
    {fields.map((field, index) => <div className="row g-2 align-items-end mb-2" key={field.id}><div className="col-md-3"><label className="form-label">Nama field</label><input className="form-control" maxLength="64" value={field.label} readOnly={disabled} onChange={(e) => set(index, 'label', e.target.value)} /></div><div className="col-md-3"><label className="form-label">Tipe</label><select className="form-select" value={field.type} disabled={disabled} onChange={(e) => set(index, 'type', e.target.value)}>{fieldTypes.map((type) => <option value={type} key={type}>{type}</option>)}</select></div><div className="col"><Input label="Nilai" type={field.type} value={field.value} readOnly={disabled} reveal={reveal[`field:${field.id}`]} onReveal={() => toggleReveal(`field:${field.id}`)} onChange={(value) => set(index, 'value', value)} /></div>{!disabled && <div className="col-auto"><button type="button" className="btn btn-outline-danger" aria-label={`Hapus field ${field.label || 'baru'}`} onClick={() => onChange(fields.filter((_, i) => i !== index))}><Icon name="trash" /></button></div>}</div>)}
  </div>
}

/** Values are fetched only when opened and are never placed in platform snapshots or browser storage. */
export function CredentialEditor({ targetType, targetId, title = 'Vault kredensial', initialOpen = false, onDraftChange }) {
  const p = usePlatform(); const [open, setOpen] = useState(initialOpen); const [data, setData] = useState(emptyCredentials); const [busy, setBusy] = useState(false); const [error, setError] = useState(null); const [message, setMessage] = useState(''); const [updatedAt, setUpdatedAt] = useState(null); const [revealed, setRevealed] = useState({}); const [dirty, setDirty] = useState(false); const [dataTarget, setDataTarget] = useState(null);
  const canRead = p.canReadCredentials; const canManage = p.canManageCredentials
  useEffect(() => {
    if (!open || !targetId || !canRead || dirty) return undefined
    const controller = new AbortController()
    Promise.resolve().then(() => p.client.credentials(targetType, targetId, { signal: controller.signal })).then((result) => {
      if (!controller.signal.aborted) { setData(result.credentials); setUpdatedAt(result.updated_at); setRevealed({}); setDirty(false); setDataTarget(targetId) }
    }).catch((reason) => { if (!controller.signal.aborted) setError(reason.code || 'unavailable') })
    return () => controller.abort()
  }, [open, targetType, targetId, canRead, p.client, dirty])
  const close = () => { setOpen(false); setData(emptyCredentials()); setRevealed({}); setError(null); setMessage(''); setUpdatedAt(null); setDirty(false); setDataTarget(null) }
  const toggleReveal = (key) => setRevealed((old) => ({ ...old, [key]: !old[key] }))
  const save = async () => {
    setBusy(true); setError(null); setMessage('')
    try { const result = await p.client.credentials(targetType, targetId, { credentials: data }); setUpdatedAt(result.updated_at); setDirty(false); setDataTarget(targetId); setMessage('Kredensial tersimpan terenkripsi di server.') }
    catch (reason) { setError(reason.code || 'unavailable') }
    finally { setBusy(false) }
  }
  const changeData = (next) => { setData(next); setDirty(true); setMessage(''); onDraftChange?.(next) }
  const updateGui = (key, value) => changeData({ ...data, gui: { ...data.gui, [key]: value } })
  const updateList = (key, value) => changeData({ ...data, [key]: value })
  const loading = Boolean(open && targetId && canRead && !dirty && dataTarget !== targetId && !error)
  const disabled = !canManage || loading || busy || !targetId
  return <section className="card mb-3">
    <div className="card-header d-flex justify-content-between align-items-center gap-2"><div><h3 className="h6 mb-0">{title}</h3><small className="text-muted">Login GUI, Wi-Fi, dan field khusus tersimpan terpisah dari konfigurasi perangkat.</small></div><button type="button" className="btn btn-sm btn-outline-primary" disabled={!canRead && !canManage} onClick={() => { if (open) close(); else { setError(null); setMessage(''); setOpen(true) } }}>{open ? 'Tutup vault' : 'Buka vault'}</button></div>
    {open && <div className="card-body">
      {!targetId && <div className="alert alert-info">Field ini sementara di form. Simpan integrasi terlebih dahulu agar kredensial dapat dienkripsi dan dikaitkan dengan target.</div>}
      {!canRead && <div className="alert alert-warning">Akun ini tidak memiliki izin untuk membaca kredensial.</div>}
      {loading && <p className="small text-muted" role="status">Membuka vault terenkripsi…</p>}
      {error && <div className="alert alert-danger" role="alert">{errorMessages[error] || 'Vault kredensial tidak dapat diakses.'}</div>}
      {canRead && !loading && !error && <>
        <div className="border rounded p-3 mb-3"><h4 className="h6">Login GUI / administrasi perangkat</h4><p className="small text-muted">Dipisahkan dari kata sandi jaringan Wi-Fi.</p><div className="row g-3"><div className="col-md-6"><Input label="Nama pengguna" type="username" value={data.gui.username} readOnly={!canManage} onChange={(value) => updateGui('username', value)} /></div><div className="col-md-6"><Input label="Kata sandi" type="password" value={data.gui.password} readOnly={!canManage} reveal={revealed['gui:password']} onReveal={() => toggleReveal('gui:password')} onChange={(value) => updateGui('password', value)} /></div></div><FieldList title="Field login tambahan" fields={data.gui.fields} onChange={(fields) => updateGui('fields', fields)} disabled={!canManage} reveal={revealed} toggleReveal={toggleReveal}/></div>
        <div className="border rounded p-3 mb-3"><div className="d-flex justify-content-between align-items-center gap-2"><div><h4 className="h6 mb-0">Jaringan Wi-Fi</h4><small className="text-muted">Setiap SSID menyimpan password sendiri.</small></div>{canManage && <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => updateList('wifi_networks', [...data.wifi_networks, { id: newId('wifi'), ssid: '', password: '' }])}><Icon name="plus-lg" className="me-1"/>Tambah SSID</button>}</div>
          {!data.wifi_networks.length && <p className="small text-muted mt-3 mb-0">Belum ada SSID tersimpan.</p>}
          {data.wifi_networks.map((network, index) => <div className="row g-2 align-items-end border-top mt-3 pt-3" key={network.id}><div className="col-md-5"><Input label={`SSID ${index + 1}`} type="ssid" value={network.ssid} readOnly={!canManage} onChange={(value) => updateList('wifi_networks', data.wifi_networks.map((item, i) => i === index ? { ...item, ssid: value } : item))} maxLength={32}/></div><div className="col"><Input label="Kata sandi Wi-Fi" type="password" value={network.password} readOnly={!canManage} reveal={revealed[`wifi:${network.id}`]} onReveal={() => toggleReveal(`wifi:${network.id}`)} onChange={(value) => updateList('wifi_networks', data.wifi_networks.map((item, i) => i === index ? { ...item, password: value } : item))}/></div>{canManage && <div className="col-auto"><button type="button" className="btn btn-outline-danger" aria-label={`Hapus SSID ${index + 1}`} onClick={() => updateList('wifi_networks', data.wifi_networks.filter((_, i) => i !== index))}><Icon name="trash"/></button></div>}</div>)}
        </div>
        <div className="border rounded p-3 mb-3"><FieldList title="Field khusus perangkat" fields={data.custom_fields} onChange={(fields) => updateList('custom_fields', fields)} disabled={!canManage} reveal={revealed} toggleReveal={toggleReveal}/></div>
        <div className="d-flex justify-content-between flex-wrap gap-2 align-items-center"><small className="text-muted">Terakhir diperbarui: {updatedAt ? new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Jakarta' }).format(new Date(updatedAt * 1000)) + ' WIB' : 'Belum tersimpan'}</small>{canManage && <button type="button" className="btn btn-primary" disabled={disabled} onClick={save}>{busy ? 'Menyimpan…' : 'Simpan kredensial terenkripsi'}</button>}</div>
        {message && <div className="alert alert-success mt-3 mb-0" role="status">{message}</div>}
        <div className="small text-muted mt-3">Nilai hanya dimuat setelah vault dibuka, memakai API yang memerlukan sesi dan permission, dan tidak masuk ke API monitoring, log, audit, atau penyimpanan browser.</div>
      </>}
    </div>}
  </section>
}
