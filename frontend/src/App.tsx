/**
 * Application shell.
 *
 * Full-viewport three-column layout:
 *   LEFT   navigation (collapsible, slides over on small screens)
 *   CENTER chat surface
 *   RIGHT  document preview (toggleable, driven by citation clicks)
 */

import { useEffect, useState } from 'react'
import { useApp } from './lib/AppContext'
import { AuthScreen } from './components/layout/AuthScreen'
import { Sidebar } from './components/layout/Sidebar'
import { ChatPanel } from './components/chat/ChatPanel'
import { PreviewPanel } from './components/documents/PreviewPanel'
import { CollectionsView, DocumentsView, ModelsView, SettingsView } from './components/views'
import { cn } from './lib/utils'

type View = 'chat' | 'documents' | 'collections' | 'models' | 'settings'

export function App() {
  const { state } = useApp()
  const [view, setView] = useState<View>('chat')

  // Mobile: the sidebar and preview are overlays rather than columns.
  const [mobileNav, setMobileNav] = useState(false)

  useEffect(() => {
    if (state.user) setView('chat')
  }, [state.user])

  if (state.booting) {
    return (
      <div className="flex h-full items-center justify-center bg-surface-0">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-line border-t-accent" />
          <p className="text-sm text-ink-faint">Loading DocMind…</p>
        </div>
      </div>
    )
  }

  if (!state.user) {
    return <AuthScreen />
  }

  return (
    <div className="flex h-full w-full overflow-hidden bg-surface-0">
      {/* ---------------- Left sidebar ---------------- */}
      <aside
        className={cn(
          'z-30 flex h-full shrink-0 flex-col border-r border-line bg-surface-1',
          'transition-[width] duration-200 ease-out',
          state.sidebarOpen ? 'w-[268px]' : 'w-[68px]',
        )}
      >
        <Sidebar
          view={view}
          onViewChange={(v) => {
            setView(v)
            setMobileNav(false)
          }}
        />
      </aside>

      {/* Mobile nav overlay */}
      {mobileNav && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/40 backdrop-blur-sm"
            onClick={() => setMobileNav(false)}
          />
          <div className="absolute inset-y-0 left-0 w-[268px] border-r border-line bg-surface-1 shadow-pop">
            <Sidebar
              view={view}
              onViewChange={(v) => {
                setView(v)
                setMobileNav(false)
              }}
            />
          </div>
        </div>
      )}

      {/* ---------------- Center column ---------------- */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {/* Floating mobile nav button */}
        <button
          onClick={() => setMobileNav(true)}
          className="btn-secondary absolute left-3 top-3 z-20 px-2.5 py-2 lg:hidden"
          aria-label="Open navigation"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            <path d="M3 6h18M3 12h18M3 18h18" />
          </svg>
        </button>

        {view === 'chat' && <ChatPanel />}
        {view === 'documents' && (
          <DocumentsView onOpenChat={() => setView('chat')} />
        )}
        {view === 'collections' && <CollectionsView />}
        {view === 'models' && <ModelsView />}
        {view === 'settings' && <SettingsView />}
      </main>

      {/* ---------------- Right preview ---------------- */}
      <PreviewPanel />

    </div>
  )
}
