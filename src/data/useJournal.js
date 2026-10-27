import { useEffect, useState } from 'react'
import { client } from './monitoringContext'
import { adaptIncident, adaptJournal, journalParams } from './journalModel'

export function useJournal(kind) {
  const [filters, setFilters] = useState({ page: 1, pageSize: 25, q: '', severity: 'all', device: '', period: kind === 'logs' ? '24h' : 'all', start: '', end: '', category: 'all', source: 'all', status: 'ACTIVE' })
  const [anchor, setAnchor] = useState(() => Date.now() / 1000)
  const [paused, setPaused] = useState(false)
  const [result, setResult] = useState({ key: '', data: null, error: null })
  const key = JSON.stringify({ filters, anchor })
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      try {
        const data = adaptJournal(await client.journal(kind, journalParams(filters, kind, anchor), controller.signal), kind)
        if (!controller.signal.aborted) setResult({ key, data, error: null })
      } catch (e) { if (!controller.signal.aborted) setResult({ key, data: null, error: e.code || 'invalid_response' }) }
    }, 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [key, filters, anchor, kind])
  useEffect(() => {
    if (paused || filters.page !== 1 || ['auth_required', 'rate_limited'].includes(result.error)) return
    const timer = setInterval(() => setAnchor(Date.now() / 1000), 60000)
    return () => clearInterval(timer)
  }, [paused, filters.page, result.error])
  const update = (patch) => { setFilters((previous) => ({ ...previous, ...patch, page: 1 })); setAnchor(Date.now() / 1000) }
  const refresh = () => { setFilters((p) => ({ ...p, page: 1 })); setAnchor(Date.now() / 1000) }
  return { filters, update, refresh, paused, setPaused, setPage: (page) => setFilters((p) => ({ ...p, page })),
    loading: result.key !== key, data: result.key === key ? result.data : null, error: result.key === key ? result.error : null }
}
export function useIncident(id) {
  const [result, setResult] = useState({ id: null, data: null, error: null });const [version,setVersion]=useState(0)
  useEffect(() => {
    if (!id) return
    const controller = new AbortController()
    client.incident(id, controller.signal).then((payload) => {
      const data = adaptIncident(payload.incident)
      if (!controller.signal.aborted) setResult({ id, data, error: null })
    }).catch((e) => { if (!controller.signal.aborted) setResult({ id, data: null, error: e.code || 'invalid_response' }) })
    return () => controller.abort()
  }, [id,version])
  return {...(result.id === id ? result : { data:null,error:null }),refresh:()=>setVersion((v)=>v+1)}
}
