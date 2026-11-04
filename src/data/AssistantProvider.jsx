import { useEffect, useMemo } from 'react'
import { useAuth } from './authSessionContext'
import { usePlatform } from './platformContext'
import { AssistantContext } from './assistantContext'
import { createAssistantWorkspace } from './assistantWorkspace'

export function AssistantProvider({ children }) {
  const { user } = useAuth()
  const { client,capabilities } = usePlatform()
  const generation=capabilities.operational_generation
  const owner=user.username+(generation&&generation!=='initial'?'.'+generation:'')
  const workspace = useMemo(() => createAssistantWorkspace({ client, username: owner }), [client, owner])
  useEffect(() => {if(generation!==undefined)return workspace.start()}, [workspace,generation])
  return <AssistantContext.Provider value={workspace}>{children}</AssistantContext.Provider>
}
