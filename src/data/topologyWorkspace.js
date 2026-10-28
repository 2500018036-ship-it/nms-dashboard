const graphValue = (record) => ({ name: record.name, nodes: record.nodes, links: record.links })
export function createTopologyWorkspace({ client, username, storage = globalThis.localStorage, makeId = () => crypto.randomUUID().replaceAll('-', ''), onSaved = () => {} }) {
  const key = 'theaz.topology.v1.' + username
  let restored = {}
  try { const raw = storage.getItem(key) || '{}'; if (raw.length <= 3 * 1024 * 1024) restored = JSON.parse(raw) } catch { /* Server records remain available. */ }
  const documents = Object.fromEntries(Object.entries(restored.documents || {}).filter(([, doc]) => doc?.graph && typeof doc.graph.name === 'string' && Array.isArray(doc.graph.nodes) && doc.graph.nodes.length <= 100 && Array.isArray(doc.graph.links) && doc.graph.links.length <= 200).slice(-20))
  let state = { selected: typeof restored.selected === 'string' ? restored.selected : '', documents, records: [], storageError: false, limitError: false }
  const listeners = new Set(); const flights = new Map()
  let active = false
  const update = (patch) => {
    state = { ...state, ...patch }
    try { storage.setItem(key, JSON.stringify({ selected: state.selected, documents: state.documents })); state.storageError = false } catch { state.storageError = true }
    listeners.forEach((listener) => listener())
  }
  const patchDocument = (id, patch) => update({ documents: { ...state.documents, [id]: { ...state.documents[id], ...patch } } })
  const documentFrom = (record) => ({ graph: graphValue(record), serverId: record.id, revision: record.revision, dirty: false, version: 0, view: { x: 0, y: 0, zoom: 1 }, pending: null, error: null })
  const select = (id) => {
    let selected = Object.keys(state.documents).find((key) => key === id || state.documents[key].serverId === id)
    if (!selected) {
      const record = state.records.find((value) => value.id === id)
      if (!record) return
      selected = id; state = { ...state, documents: { ...state.documents, [id]: documentFrom(record) } }
    }
    update({ selected })
  }
  const save = (id = state.selected) => {
    if (flights.has(id)) return flights.get(id)
    const doc = state.documents[id]
    if (!doc || !doc.dirty && !doc.pending) return Promise.resolve()
    const pending = doc.pending || { request_id: makeId(), version: doc.version, serverId: doc.serverId, revision: doc.revision, value: structuredClone(doc.graph) }
    patchDocument(id, { pending, saving: true, error: null })
    const flight = (async () => {
      try {
        const result = await client.platform('topologies' + (pending.serverId ? '/' + pending.serverId : ''), { body: { value: pending.value, request_id: pending.request_id, ...(pending.serverId ? { revision: pending.revision } : {}) } })
        if (!active || !state.documents[id]) return result
        const current = state.documents[id]
        patchDocument(id, { serverId: result.id, revision: result.revision, pending: null, dirty: current.version !== pending.version, ...(current.version === pending.version ? { graph: graphValue(result) } : {}), savedAt: Date.now(), error: null })
        update({ records: [...state.records.filter((record) => record.id !== result.id), result] })
        onSaved()
        return result
      } catch (error) { if (active) patchDocument(id, { error: error.code || 'unavailable', ...(['validation_failed', 'revision_conflict', 'permission_denied', 'invalid_fields', 'invalid_number', 'invalid_text'].includes(error.code) ? { pending: null } : {}) }); return null }
      finally { flights.delete(id); if (active && state.documents[id]) patchDocument(id, { saving: false }) }
    })()
    flights.set(id, flight)
    return flight
  }
  return {
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    getSnapshot() { return state },
    sync(records) {
      const docs = { ...state.documents }
      for (const [id, doc] of Object.entries(docs)) {
        const record = records.find((value) => value.id === doc.serverId)
        if (record && !doc.dirty && !doc.pending && record.revision !== doc.revision) docs[id] = { ...documentFrom(record), view: doc.view }
      }
      update({ records, documents: docs })
      if (!state.selected && records.length) select(records[0].id)
    },
    select,
    create(name) {
      if (Object.keys(state.documents).length >= 20) { update({ limitError: true }); return false }
      const id = 'draft_' + makeId()
      update({ selected: id, documents: { ...state.documents, [id]: { graph: { name, nodes: [], links: [] }, serverId: null, revision: null, version: 1, dirty: true, pending: null, view: { x: 0, y: 0, zoom: 1 }, error: null } } })
    },
    change(graph) {
      const doc = state.documents[state.selected]
      if (doc) patchDocument(state.selected, { graph, dirty: true, version: doc.version + 1, error: null })
    },
    setView(value) {
      const doc = state.documents[state.selected]
      if (doc) patchDocument(state.selected, { view: typeof value === 'function' ? value(doc.view) : value })
    },
    discard() {
      const doc = state.documents[state.selected]
      if (!doc || doc.saving) return
      const record = state.records.find((value) => value.id === doc.serverId)
      if (record) patchDocument(state.selected, documentFrom(record))
    },
    forget() {
      const docs = { ...state.documents }; delete docs[state.selected]
      update({ selected: '', documents: docs })
    },
    save,
    start() {
      active = true
      for (const [id, doc] of Object.entries(state.documents)) if (doc.pending) save(id)
      return () => { active = false }
    },
  }
}
