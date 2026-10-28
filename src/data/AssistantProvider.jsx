import { useEffect, useMemo } from 'react'
import { useAuth } from './authSessionContext'
import { usePlatform } from './platformContext'
import { AssistantContext } from './assistantContext'
import { createAssistantWorkspace } from './assistantWorkspace'

export function AssistantProvider({ children }) {
  const { user } = useAuth()
  const { client } = usePlatform()
  const workspace = useMemo(() => createAssistantWorkspace({ client, username: user.username }), [client, user.username])
  useEffect(() => workspace.start(), [workspace])
  return <AssistantContext.Provider value={workspace}>{children}</AssistantContext.Provider>
}
