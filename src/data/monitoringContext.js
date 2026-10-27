import { createContext } from 'react'
import { createApiClient } from './apiClient'
import { readConfig } from './capabilities'
export const config = readConfig(import.meta.env)
export const client = createApiClient(config)
export const MonitoringContext = createContext(null)
