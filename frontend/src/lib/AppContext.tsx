/** React context wrapper around the application store. */

import { createContext, useContext, type ReactNode } from 'react'
import { useAppState, type AppStore } from './store'

const AppContext = createContext<AppStore | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const store = useAppState()
  return <AppContext.Provider value={store}>{children}</AppContext.Provider>
}

export function useApp(): AppStore {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used inside <AppProvider>')
  return ctx
}
