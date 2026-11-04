import { useEffect, useMemo } from 'react'
import { useAuth } from './authSessionContext'
import { usePlatform } from './platformContext'
import { createTopologyWorkspace } from './topologyWorkspace'
import { TopologyWorkspaceContext } from './topologyWorkspaceContext'
export function TopologyWorkspaceProvider({ children }) {
  const { user } = useAuth()
  const { client, topologies, refresh, capabilities, canManage } = usePlatform()
  const generation=capabilities.operational_generation
  const owner=user.username+(generation&&generation!=='initial'?'.'+generation:'')
  const autoSave = Boolean(canManage || capabilities.permissions?.includes('topology.manage'))
  const workspace = useMemo(() => createTopologyWorkspace({ client, username: owner, onSaved: refresh, autoSave }), [client, owner, refresh, autoSave])
  useEffect(() => {if(generation!==undefined)return workspace.start()}, [workspace,generation])
  useEffect(() => workspace.sync(topologies), [workspace, topologies])
  return <TopologyWorkspaceContext.Provider value={workspace}>{children}</TopologyWorkspaceContext.Provider>
}
