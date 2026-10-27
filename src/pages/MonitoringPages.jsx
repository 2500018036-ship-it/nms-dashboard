import { useState } from 'react'
import { useMonitoring } from '../data/useMonitoring'
import { ReportView } from './ReportView'
export { HealthPage } from './HealthPage'
export function ReportsPage() { const { snapshot } = useMonitoring(); const [target,setTarget] = useState('debian'); return <><label className="form-label" htmlFor="report-target">Collector laporan</label><select id="report-target" className="form-select mb-4" value={target} onChange={(e)=>setTarget(e.target.value)}>{[...new Set(['debian','mikrotik_system','proxmox_resources',...snapshot.checks.map((c)=>c.id)])].map((id)=><option key={id}>{id}</option>)}</select><ReportView key={target} target={target}/></> }
