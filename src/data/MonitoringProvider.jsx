import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { adaptStatus, adaptEvents, ageSnapshot, emptySnapshot, adaptDevices } from './adapters'
import { appendTrafficHistory } from './coreAdapter'
import { unavailableDeviceService } from '../devices/service'
import { MonitoringContext, config, client } from './monitoringContext'

export function MonitoringProvider({ children }) {
  const [snapshot, setSnapshot] = useState(emptySnapshot); const [events, setEvents] = useState([])
  const [observedDevices, setObservedDevices] = useState([]); const [health, setHealth] = useState(null)
  const [trafficHistory, setTrafficHistory] = useState({}); const [now, setNow] = useState(() => Date.now() / 1000)
  const [connection, setConnection] = useState({ status: config.enabled ? 'loading' : 'not_configured', error: config.invalid ? 'invalid_config' : 'not_configured', eventsError: null })
  const active = useRef(null)
  const refresh = useCallback(async () => {
    if (!config.enabled || active.current) return
    const controller = new AbortController(); active.current = controller
    setConnection((c) => ({ ...c, status: 'loading' }))
    const results = await Promise.allSettled([
      client.status(controller.signal).then(adaptStatus), client.events(controller.signal).then(adaptEvents),
      client.devices(controller.signal).then(adaptDevices), client.health(controller.signal),
    ])
    if (controller.signal.aborted) return
    const [s, e, d, h] = results
    if (s.status === 'fulfilled') { setSnapshot(s.value); setTrafficHistory((history) => appendTrafficHistory(history, s.value.core.traffic)) }
    if (e.status === 'fulfilled') setEvents(e.value)
    if (d.status === 'fulfilled') setObservedDevices(d.value)
    if (h.status === 'fulfilled') setHealth(h.value)
    setConnection({ status: s.status === 'fulfilled' ? 'connected' : 'error', error: s.status === 'rejected' ? s.reason.code || 'invalid_response' : null,
      eventsError: e.status === 'rejected' ? e.reason.code || 'invalid_response' : null,
      devicesError: d.status === 'rejected' ? d.reason.code || 'invalid_response' : null,
      healthError: h.status === 'rejected' ? h.reason.code || 'invalid_response' : null })
    active.current = null
  }, [])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now() / 1000), 15000); const startup = setTimeout(refresh, 0)
    return () => { clearInterval(timer); clearTimeout(startup); active.current?.abort(); active.current = null } }, [refresh])
  useEffect(() => {
    if (!config.enabled || connection.status === 'loading' || connection.error === 'auth_required' || connection.eventsError === 'auth_required') return
    const timer = setTimeout(refresh, connection.status === 'error' ? 60000 : Math.max(30000, Math.min(300000, (snapshot.interval || 30) * 1000)))
    return () => clearTimeout(timer)
  }, [connection, snapshot.interval, refresh])
  const agedSnapshot = useMemo(() => ageSnapshot(snapshot, now), [snapshot, now])
  const healthFresh = typeof health?.at === 'number' && now - health.at <= 120 && !connection.healthError && connection.status !== 'error'
  const agedHealth = health ? { ...health, status: healthFresh ? health.status : 'UNKNOWN', poller_ready: healthFresh && health.poller_ready } : null
  const agedDevices = observedDevices.map((d) => ({ ...d, status: now - d.sampled > (d.staleAfter || Math.max(120, Math.min(3600, (snapshot.interval || 30) * 3))) ? 'UNKNOWN' : d.status }))
  return <MonitoringContext.Provider value={{ snapshot: agedSnapshot, events, observedDevices: agedDevices, health: agedHealth, connection, config, refresh, client,
    mode: 'live', canDemo: false, deviceService: unavailableDeviceService, inventory: [], acknowledgments: {}, trafficHistory }}>{children}</MonitoringContext.Provider>
}
