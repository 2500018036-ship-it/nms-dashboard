import { useContext, useState, useEffect } from 'react'
import { MonitoringContext, config, client } from './monitoringContext'
import { adaptHistory } from './adapters'

export function useMonitoring() { return useContext(MonitoringContext) }
export function useHistory(target) {
  const [result, setResult] = useState({ target, status: config.enabled ? 'loading' : 'not_configured', points: [], error: null })
  useEffect(() => {
    if (!config.enabled) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      client.history(target, controller.signal).then((payload) => {
        const points = adaptHistory(payload, target)
        if (!controller.signal.aborted) setResult({ target, points, status: 'connected', error: null })
      }).catch((error) => {
        if (!controller.signal.aborted) setResult({ target, points: [], status: 'error', error: error.code || 'invalid_response' })
      })
    }, 0)
    return () => { clearTimeout(timer); controller.abort() }
  }, [target])
  return result.target === target ? result : { target, status: config.enabled ? 'loading' : 'not_configured', points: [], error: null }
}
