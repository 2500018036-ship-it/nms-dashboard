import { useState } from 'react'
import { usePlatform } from '../data/platformContext'
import { Panel } from './ui'
import { Feedback } from './PlatformUI'

export function OperationalResetPlan(){
  const p=usePlatform();const [plan,setPlan]=useState(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false)
  if(!p.canManage)return null
  const load=async()=>{setBusy(true);try{setPlan(await p.client.platform('reset-plan'));setError('')}catch(e){setError(e.code)}finally{setBusy(false)}}
  return <Panel title="Persiapan reset operasional" subtitle="Pratinjau baca-saja; tidak ada penghapusan dari halaman ini" action={<button className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={load}>Muat daftar data</button>}><Feedback error={error}/><p className="small">Reset memerlukan backup lengkap yang lolos pemeriksaan integritas dan persetujuan eksplisit dalam jendela pemeliharaan. Akun, keamanan, pengaturan inti, arsip lama dan versi backup konfigurasi perangkat dipertahankan.</p>{plan&&<><div className="table-responsive"><table className="table table-sm"><thead><tr><th>Penyimpanan</th><th>Data operasional</th><th>Jumlah saat ini</th></tr></thead><tbody>{Object.entries(plan.databases).flatMap(([database,tables])=>Object.entries(tables).map(([table,count])=><tr key={database+table}><td>{database}</td><td>{table}</td><td>{count.toLocaleString('id-ID')}</td></tr>))}</tbody></table></div><div className="alert alert-warning mb-0">Reset belum dijalankan. Jumlah berubah selama monitoring aktif; backup terbaru akan dibuat dan diperiksa kembali sebelum reset yang disetujui.</div></>}</Panel>
}
