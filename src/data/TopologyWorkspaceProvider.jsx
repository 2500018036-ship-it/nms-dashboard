import { useEffect, useMemo } from 'react'
import { useAuth } from './authSessionContext'
import { usePlatform } from './platformContext'
import { createTopologyWorkspace } from './topologyWorkspace'
import { TopologyWorkspaceContext } from './topologyWorkspaceContext'
export function TopologyWorkspaceProvider({ children }) {
  const { user } = useAuth()
  const { client, topologies, refresh, capabilities, canManage } = usePlatform()
  const autoSave = Boolean(canManage || capabilities.permissions?.includes('topology.manage'))
  const workspace = useMemo(() => createTopologyWorkspace({ client, username: user.username, onSaved: refresh, autoSave }), [client, user.username, refresh, autoSave])
  useEffect(() => workspace.start(), [workspace])
  useEffect(() => workspace.sync(topologies), [workspace, topologies])
  return <TopologyWorkspaceContext.Provider value={workspace}>{children}</TopologyWorkspaceContext.Provider>
}
