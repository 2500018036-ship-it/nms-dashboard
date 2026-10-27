import { createContext, useContext } from 'react'
export const PlatformContext = createContext(null)
export function usePlatform() { return useContext(PlatformContext) }
export const recordValue = (row) => Object.fromEntries(Object.entries(row).filter(([k]) => !['id','revision','created_at','updated_at','health','capabilities','monitor_target'].includes(k)))
