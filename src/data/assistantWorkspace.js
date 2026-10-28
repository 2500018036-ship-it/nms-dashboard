// The owner is the authenticated workspace, not the assistant page component.
export function createAssistantWorkspace({ client, username, storage = globalThis.localStorage, interval = 2500, makeId = () => crypto.randomUUID().replaceAll('-', '') }) {
  const key = 'theaz.assistant.v1.' + username
  let restored = {}
  try { restored = JSON.parse(storage.getItem(key) || '{}') } catch { /* Restore server history even if browser storage is unavailable. */ }
  const validPending = restored.pending && /^[a-f0-9]{32}$/.test(restored.pending.request_id) && typeof restored.pending.question === 'string' && restored.pending.question.length <= 2000
  let state = { draft: typeof restored.draft === 'string' ? restored.draft.slice(0, 2000) : '', pending: validPending ? restored.pending : null, items: [], error: null, loading: true, submitting: false, nextCursor: null }
  const listeners = new Set()
  let active = false; let generation = 0; let timer; let flight; let olderLoaded = false; let refreshing = null
  const update = (patch) => {
    state = { ...state, ...patch }
    try { storage.setItem(key, JSON.stringify({ draft: state.draft, pending: state.pending })) } catch { /* Server history remains authoritative. */ }
    listeners.forEach((listener) => listener())
  }
  const merge = (items) => [...new Map([...state.items, ...items].map((item) => [item.id, item])).values()].sort((a, b) => a.created_at - b.created_at).slice(-100)
  const refresh = async () => {
    if (!active || refreshing === generation) return
    const version = generation; refreshing = version
    try {
      const result = await client.platform('assistant-history')
      if (!active || version !== generation) return
      if (!Array.isArray(result.items)) throw new Error('invalid_response')
      const items = merge(result.items)
      const found = state.pending && items.some((item) => item.request_id === state.pending.request_id)
      update({ items, ...(found ? { pending: null, draft: '', error: null } : {}), loading: false, error: null, ...(!olderLoaded ? { nextCursor: result.next_cursor } : {}) })
    } catch (error) { if (active && version === generation) update({ error: error.code || 'unavailable', loading: false }) }
    finally { if (refreshing === version) refreshing = null }
  }
  const send = async (pending) => {
    if (flight) return flight
    const version = generation
    update({ pending, submitting: true, error: null })
    flight = (async () => {
      try {
        const result = await client.platform('ask', { body: pending })
        if (active && version === generation) update({ items: merge([{ ...result, question: pending.question, request_id: pending.request_id }]), pending: null, draft: '', error: null })
      } catch (error) { if (active && version === generation) update({ error: error.code || 'unavailable' }) }
      finally { flight = null; if (active && version === generation) update({ submitting: false }) }
    })()
    return flight
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    getSnapshot() { return state },
    setDraft(draft) { update({ draft: draft.slice(0, 2000) }) },
    async submit() {
      if (state.submitting || state.pending || state.items.some((item) => item.state === 'running') || !state.draft.trim()) return
      return send({ question: state.draft.trim(), request_id: makeId() })
    },
    async retry() { await refresh(); if (state.pending) return send(state.pending) },
    async loadOlder() {
      if (!state.nextCursor) return
      const version = generation
      try {
        const result = await client.platform('assistant-history', { params: { before: state.nextCursor } })
        if (active && version === generation) { olderLoaded = true; update({ items: merge(result.items), nextCursor: result.next_cursor }) }
      } catch (error) { if (active && version === generation) update({ error: error.code || 'unavailable' }) }
    },
    start() {
      active = true; generation++
      refresh().then(() => { if (active && state.pending && !state.error) send(state.pending) })
      timer = setInterval(() => { if (state.pending || state.items.some((item) => item.state === 'running')) refresh() }, interval)
      return () => { active = false; generation++; clearInterval(timer) }
    },
  }
}
