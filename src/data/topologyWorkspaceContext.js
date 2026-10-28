import { createContext, useContext, useSyncExternalStore } from 'react'
export const TopologyWorkspaceContext = createContext(null)
export function useTopologyWorkspace() {
  const workspace = useContext(TopologyWorkspaceContext)
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot)
  return { ...state, document: state.documents[state.selected] || null, workspace }
}
