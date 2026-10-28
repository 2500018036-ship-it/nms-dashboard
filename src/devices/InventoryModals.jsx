import { useState } from 'react'
import { Modal } from '../components/Modal'
import { Badge, EmptyState } from '../components/ui'
import { parseInventory, exportInventory, newDevice, validateScope, deviceErrorMessage } from './model'

export function downloadJson(text, filename) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
export function InventoryImport({ service, inventory, onClose, onDone }) {
  const [text, setText] = useState(''); const [preview, setPreview] = useState(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const validate = () => { try { const rows = parseInventory(text, inventory); setPreview(rows); setError('') } catch (e) { setPreview(null); setError(`${deviceErrorMessage(e)} ${Object.values(e.errors || {}).join(' ')}`) } }
  const sample = () => downloadJson(exportInventory([{ ...newDevice(), name: 'EXAMPLE-IMPORT-SERVER', host: '198.51.100.10', type: 'server', profile: 'host', methods: ['agent'] }], 'example-format-only'), 'nms-inventory-format.json')
  const run = async () => { setBusy(true); try { const count = await service.import(text); onDone(`${count} konfigurasi berhasil diimpor ke inventaris server.`) } catch (e) { setError(deviceErrorMessage(e)) } finally { setBusy(false) } }
  return <Modal title="Impor inventaris" onClose={onClose} footer={<><button className="btn btn-secondary" onClick={onClose}>Tutup</button><button className="btn btn-outline-primary" onClick={validate}>Validasi & pratinjau</button><button className="btn btn-primary" disabled={!preview || !service.canWrite || busy} onClick={run}>Impor konfigurasi</button></>}>
    <div className="alert alert-info small">JSON schemaVersion 1 · maksimum 200 perangkat / 256 KiB. Impor bersifat tambah saja; ID dan alamat duplikat ditolak. Credential dan field di luar skema ditolak. {!service.canWrite && 'Penyimpanan backend belum terintegrasi.'}</div>
    <button className="btn btn-sm btn-outline-secondary mb-3" onClick={sample}>Unduh format contoh</button>
    <label className="form-label" htmlFor="inventory-file">Pilih berkas JSON</label><input id="inventory-file" type="file" accept=".json,application/json" className="form-control mb-3" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; if (f.size > 262144) { setError('Ukuran impor maksimum 256 KiB.'); setPreview(null); return } try { setText(await f.text()); setPreview(null); setError('') } catch { setError('Berkas belum dapat dibaca.') } }} />
    <label className="form-label" htmlFor="inventory-json">Atau tempel JSON inventaris</label><textarea id="inventory-json" className="form-control font-monospace" rows={8} maxLength={262144} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); setError('') }} placeholder={'{"schemaVersion":1,"devices":[…]}'} />
    {error && <div className="alert alert-danger mt-3" role="alert">{error}</div>}
    {preview && <div className="mt-3"><div className="alert alert-success" role="status">{preview.length} konfigurasi valid. Belum ada perangkat yang ditambahkan.</div><div className="table-responsive"><table className="table table-sm"><thead><tr><th>Nama</th><th>Alamat</th><th>Tipe</th></tr></thead><tbody>{preview.map((d, i) => <tr key={i}><td>{d.name}</td><td>{d.host}</td><td>{d.type}</td></tr>)}</tbody></table></div></div>}
  </Modal>
}
export function DiscoveryModal({ service, onClose, onDone }) {
  const [scope, setScope] = useState('192.168.20.0/24'); const [ran, setRan] = useState(false); const [selected, setSelected] = useState([]); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const [foundIds, setFoundIds] = useState([])
  const candidates = ran ? service.candidates().filter((c) => !c.approved && foundIds.includes(c.id)) : []
  const run = async () => {
    if (!validateScope(scope)) { setError('Gunakan subnet IPv4 /24–/32.'); return }
    setBusy(true); setError('')
    try { const found = await service.discover(scope); setRan(true); setFoundIds(found.map((c) => c.id)); setSelected(found.map((c) => c.id)) } catch (e) { setError(deviceErrorMessage(e)) } finally { setBusy(false) }
  }
  const approve = async () => { setBusy(true); try { const count = await service.approve(selected); onDone(`${count} kandidat disetujui pada inventaris server.`) } catch (e) { setError(deviceErrorMessage(e)) } finally { setBusy(false) } }
  return <Modal title="Penemuan otomatis dan persetujuan" onClose={onClose} footer={<><button className="btn btn-secondary" onClick={onClose}>Tutup</button><button className="btn btn-primary" disabled={!service.canWrite || !selected.length || busy} onClick={approve}>Setujui kandidat terpilih</button></>}>
    <div className="alert alert-info small">Discovery pasif dari daftar observasi collector yang sudah berjalan. Tidak melakukan scan subnet baru. Approval menyimpan metadata inventaris; tidak otomatis mengaktifkan collector.</div>
    <label className="form-label" htmlFor="discovery-scope">Filter scope observasi</label><div className="input-group mb-3"><input id="discovery-scope" className="form-control" value={scope} onChange={(e) => { setScope(e.target.value); setRan(false); setSelected([]) }} /><button className="btn btn-outline-primary" onClick={run} disabled={!service.canWrite || busy}>{busy ? 'Memproses…' : 'Cari observasi'}</button></div>
    {error && <div className="alert alert-danger" role="alert">{error}</div>}
    {!ran ? <EmptyState compact action={false} icon="radar" title="Belum ada hasil discovery" description="Pilih scope untuk menyaring perangkat yang sudah teramati backend." /> : <div className="table-responsive"><table className="table align-middle"><thead><tr><th>Pilih</th><th>Kandidat</th><th>Alamat</th><th>Status</th></tr></thead><tbody>{candidates.map((c) => <tr key={c.id}><td><input className="form-check-input" type="checkbox" aria-label={`Pilih ${c.device.name}`} checked={selected.includes(c.id)} onChange={(e) => setSelected(e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id))} /></td><td>{c.device.name}</td><td>{c.device.host}</td><td><Badge>Menunggu persetujuan</Badge></td></tr>)}</tbody></table>{!candidates.length && <p className="text-muted">Tidak ada kandidat pada scope ini.</p>}</div>}
  </Modal>
}
