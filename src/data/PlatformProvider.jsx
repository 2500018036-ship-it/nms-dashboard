import { useCallback, useEffect, useRef, useState } from 'react'
import { client } from './monitoringContext'
import { setDisplayPreferences } from './displayPreferences'
import { PlatformContext } from './platformContext'

const empty = { integrations: [], topologies: [], inventory: [], maintenance: [], capabilities: {}, settings: null }
export function PlatformProvider({ children }) {
  const [data, setData] = useState(empty); const [error, setError] = useState(null); const [loading, setLoading] = useState(true)
  const active = useRef(null)
  const [now,setNow]=useState(()=>Date.now()/1000)
  useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()/1000),15000);return ()=>clearInterval(timer)},[])
  const refresh = useCallback(async () => {
    active.current?.abort(); const controller = new AbortController(); active.current = controller
    try {
      const value = await client.platform('', { signal: controller.signal })
      if (!Array.isArray(value.integrations) || !Array.isArray(value.topologies) || !value.capabilities || !value.settings) throw new Error('invalid_response')
      if (!controller.signal.aborted) { setDisplayPreferences(value.settings.value); setData(value); setError(null) }
    } catch (e) { if (!controller.signal.aborted) setError(e.code || 'invalid_response') }
    finally { if (!controller.signal.aborted) setLoading(false) }
  }, [])
  useEffect(() => { const start = setTimeout(refresh, 0); const timer = setInterval(refresh, 60000)
    return () => { clearTimeout(start); clearInterval(timer); active.current?.abort() } }, [refresh])
  const mutate = useCallback(async (path, body) => { const result = await client.platform(path, { body }); await refresh(); return result }, [refresh])
  const granted = data.capabilities?.permissions || []
  return <PlatformContext.Provider value={{ ...data, now, integrations:data.integrations.map((s)=>s.health && (error || s.health.stale || now-s.health.sample_epoch>(s.health.stale_after_seconds||Math.max(120,s.poll_interval*3))) ? {...s,health:{...s.health,status:'UNKNOWN',stale:true}}:s), error, loading, refresh, mutate, client, canManage: !error && data.capabilities.manage === true, canAcknowledge: !error && data.capabilities.acknowledge === true, canReadCredentials: !error && granted.includes('credentials.read'), canManageCredentials: !error && granted.includes('credentials.manage') }}>{children}</PlatformContext.Provider>
}
