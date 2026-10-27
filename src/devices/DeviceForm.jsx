import { useRef, useState } from 'react'
import { Modal } from '../components/Modal'
import { deviceTypes, methods, profiles, newDevice, validateDevice, deviceErrorMessage } from './model'

export function DeviceForm({ device, inventory, service, onClose, onSaved }) {
  const [form, setForm] = useState(() => ({ ...(device || newDevice()), tagsText: device?.tags.join(', ') || '' }))
  const [errors, setErrors] = useState({}); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false)
  const summary = useRef(null)
  const set = (key, value) => { setForm((f) => ({ ...f, [key]: value })); setMessage('') }
  const submit = async (event) => {
    event.preventDefault()
    const { tagsText, ...draft } = form
    const result = validateDevice({ ...draft, tags: tagsText.split(',').map((t) => t.trim()).filter(Boolean) }, inventory, device?.id)
    setErrors(result.errors)
    if (!result.value) { setTimeout(() => summary.current?.focus(), 0); return }
    if (!service.canWrite) { setMessage('Konfigurasi valid. Backend penyimpanan belum terintegrasi; perangkat BELUM ditambahkan atau diubah.'); return }
    setBusy(true)
    try {
      if (device) await service.update(device.id, result.value)
      else await service.create(result.value)
      onSaved(`Konfigurasi ${device ? 'diperbarui' : 'ditambahkan'} pada penyimpanan server.`)
    } catch (error) { setErrors(error.errors || {}); setMessage(deviceErrorMessage(error)) }
    finally { setBusy(false) }
  }
  const field = (key, label, options = {}) => <div className={options.wide ? 'col-12' : 'col-md-6'}><label className="form-label" htmlFor={`device-${key}`}>{label}</label><input id={`device-${key}`} className={`form-control ${errors[key] ? 'is-invalid' : ''}`} value={form[key]} onChange={(e) => set(key, e.target.value)} aria-invalid={!!errors[key]} aria-describedby={errors[key] ? `error-${key}` : undefined} {...options.input} />{errors[key] && <div className="invalid-feedback" id={`error-${key}`}>{errors[key]}</div>}</div>
  return <Modal title={device ? 'Edit konfigurasi perangkat' : 'Tambah konfigurasi perangkat'} onClose={busy ? () => {} : onClose} footer={<><button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Batal</button><button type="submit" form="device-form" className="btn btn-primary" disabled={busy}>{busy ? 'Memproses…' : service.canWrite ? 'Simpan konfigurasi' : 'Validasi konfigurasi'}</button></>}>
    <div className="alert alert-info small">Metadata inventaris disimpan di backend. Profil dan metode yang dipilih tidak otomatis mengaktifkan collector atau protokol perangkat. Credential perangkat tetap berada di server.</div>
    <form id="device-form" onSubmit={submit} noValidate>
      {!!Object.keys(errors).length && <div className="alert alert-danger" role="alert" tabIndex={-1} ref={summary}>Periksa konfigurasi: {errors.form || 'ada field yang belum valid.'}</div>}
      {message && <div className="alert alert-info" role="status">{message}</div>}
      <div className="row g-3">
        {field('name', 'Nama perangkat', { input: { autoFocus: true, maxLength: 80, required: true } })}
        {field('host', 'IP / hostname', { input: { placeholder: '192.0.2.10 atau server.example.test', required: true, autoComplete: 'off' } })}
        <div className="col-md-6"><label className="form-label" htmlFor="device-type">Tipe perangkat</label><select id="device-type" className={`form-select ${errors.type ? 'is-invalid' : ''}`} value={form.type} onChange={(e) => set('type', e.target.value)}>{deviceTypes.map((type) => <option key={type}>{type}</option>)}</select>{errors.type && <div className="invalid-feedback">{errors.type}</div>}</div>
        {field('interval', 'Interval polling (detik)', { input: { type: 'number', min: 15, max: 86400, step: 1 } })}
        {field('vendor', 'Vendor (opsional)', { input: { maxLength: 80 } })}{field('model', 'Model (opsional)', { input: { maxLength: 80 } })}
        {field('group', 'Grup', { input: { maxLength: 48, placeholder: 'Network, Compute, Services…' } })}
        <div className="col-md-6"><label className="form-label" htmlFor="device-profile">Profil monitoring</label><select id="device-profile" className={`form-select ${errors.profile ? 'is-invalid' : ''}`} value={form.profile} onChange={(e) => set('profile', e.target.value)}>{Object.entries(profiles).map(([key, p]) => <option key={key} value={key}>{p.label}</option>)}</select>{errors.profile && <div className="invalid-feedback">{errors.profile}</div>}</div>
        <fieldset className="col-12"><legend className="form-label fs-6">Metode monitoring</legend><div className="d-flex flex-wrap gap-3">{methods.map((method) => <div className="form-check" key={method}><input type="checkbox" className="form-check-input" id={`method-${method}`} checked={form.methods.includes(method)} onChange={(e) => set('methods', e.target.checked ? [...form.methods, method] : form.methods.filter((m) => m !== method))} /><label className="form-check-label text-uppercase" htmlFor={`method-${method}`}>{method}</label></div>)}</div>{errors.methods && <div className="text-danger small mt-1">{errors.methods}</div>}</fieldset>
        {field('tagsText', 'Tag (pisahkan dengan koma)', { wide: true, input: { placeholder: 'critical, lan, rack-a' } })}
        {errors.tags && <div className="col-12 text-danger small">{errors.tags}</div>}
        <div className="col-12"><div className="form-check form-switch"><input id="device-enabled" className="form-check-input" type="checkbox" checked={form.enabled} onChange={(e) => set('enabled', e.target.checked)} /><label className="form-check-label" htmlFor="device-enabled">Konfigurasi monitoring aktif</label></div></div>
        <div className="col-12"><div className="alert alert-secondary small mb-0"><strong>Rancangan metrik: </strong>{profiles[form.profile]?.metrics.join(' · ')}<div className="mt-1">Metrik aktual mengikuti kemampuan perangkat, metode, dan collector. Profil ini tidak mengaktifkan protokol atau mengubah konfigurasi jaringan.</div></div></div>
      </div>
    </form>
  </Modal>
}
