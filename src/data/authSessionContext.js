import { createContext, useContext } from 'react'

// Keep context identity stable while the provider component is refreshed in development.
export const AuthContext = createContext(null)
export function useAuth() { return useContext(AuthContext) }
