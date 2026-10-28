import { createContext, useContext, useSyncExternalStore } from 'react'
export const AssistantContext = createContext(null)
export function useAssistant() {
  const workspace = useContext(AssistantContext)
  const state = useSyncExternalStore(workspace.subscribe, workspace.getSnapshot)
  return { ...state, workspace }
}
