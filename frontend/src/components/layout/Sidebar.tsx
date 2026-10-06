/** Left sidebar: navigation, conversations, collections, upload, account. */

import { useMemo, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import { conversations as convApi } from '../../lib/api'
import type { Collection } from '../../lib/types'
import { cn, fileIcon, formatRelative, isProcessing, STATUS_META } from '../../lib/utils'
import { UploadDropzone } from '../documents/UploadDropzone'
import { WebPanel } from '../chat/WebPanel'
import { MadeWithLove } from './MadeWithLove'
import { useToast } from '../ui/Toasts'
import {
  IconChat,
  IconChevronDown,
  IconCog,
  IconCpu,
  IconFolder,
  IconGlobe,
  IconGrid,
  IconLayers,
  IconLogOut,
  IconMoon,
  IconPlus,
  IconSearch,
  IconSun,
  IconTrash,
  IconUpload,
  IconX,
} from '../ui/Icons'

interface Props {
  view: string
  onViewChange: (view: 'chat' | 'documents' | 'collections' | 'models' | 'settings') => void
}

export function Sidebar({ view, onViewChange }: Props) {
  const { state, dispatch, setActiveCollection, newChat, openConversation, logout, toggleTheme, resolvedTheme } =
    useApp()
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [showUpload, setShowUpload] = useState(false)
  const [showWeb, setShowWeb] = useState(false)
  const [showCollections, setShowCollections] = useState(true)

  const collapsed = !state.sidebarOpen

  const filteredConversations = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return state.conversations
    return state.conversations.filter((c) => c.title.toLowerCase().includes(q))
  }, [state.conversations, query])

  const processingDocs = state.documents.filter((d) => isProcessing(d.status))

  async function handleDeleteConversation(id: string) {
    try {
      await convApi.remove(id)
      if (state.activeConversationId === id) newChat()
      toast.push('Conversation deleted', 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  const NAV = [
    { id: 'chat', label: 'Chat', icon: IconChat },
    { id: 'documents', label: 'Documents', icon: IconGrid },
    { id: 'collections', label: 'Collections', icon: IconFolder },
    { id: 'models', label: 'Models', icon: IconCpu },
    { id: 'settings', label: 'Settings', icon: IconCog },
  ] as const

  return (
    <>
      {/* Header */}
      <div className={cn('flex h-14 shrink-0 items-center border-b border-line', collapsed ? 'justify-center px-2' : 'gap-2.5 px-4')}>
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-white">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
            <path d="M12 3.5 13.6 8 18 9.6 13.6 11.2 12 15.7 10.4 11.2 6 9.6 10.4 8z" />
          </svg>
        </div>
        {!collapsed && (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold tracking-tight">DocMind</p>
            <p className="truncate text-[10px] text-ink-faint">{state.user?.username}</p>
          </div>
        )}
        {!collapsed && (
          <button
            onClick={() => dispatch({ type: 'sidebar', open: false })}
            className="hidden rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface-2 hover:text-ink lg:block"
            aria-label="Collapse sidebar"
          >
            <IconLayers className="text-base" />
          </button>
        )}
      </div>

      {/* Scrollable body */}
      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto px-2.5 py-3">
        {/* Primary actions */}
        <button onClick={newChat} className={cn('btn-primary', collapsed && 'px-0')} title="New chat">
          <IconPlus className="text-base" />
          {!collapsed && 'New chat'}
        </button>

        <button
          onClick={() => setShowUpload((v) => !v)}
          className={cn(
            'btn-secondary w-full',
            collapsed && 'px-0',
            showUpload && 'border-accent/50 bg-accent-soft text-accent',
          )}
          title="Upload documents"
        >
          <IconUpload className="text-base" />
          {!collapsed && 'Upload documents'}
        </button>

        {showUpload && !collapsed && (
          <div className="animate-fade-in px-0.5 pb-1">
            <UploadDropzone
              compact
              onUploaded={() => {
                setShowUpload(false)
                onViewChange('documents')
              }}
            />
          </div>
        )}

        {!collapsed && (
          <button
            onClick={() => setShowWeb((v) => !v)}
            className={cn(
              'btn-secondary w-full',
              showWeb && 'border-sky-500/50 bg-sky-500/10 text-sky-600 dark:text-sky-400',
            )}
            title="Analyse websites"
          >
            <IconGlobe className="text-base" />
            Add website
          </button>
        )}

        {showWeb && !collapsed && (
          <WebPanel onDone={() => setShowWeb(false)} />
        )}

        <div className="my-2 h-px bg-line" />

        {/* Navigation */}
        <nav className="space-y-0.5">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onViewChange(id)}
              title={label}
              className={cn(
                'flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm transition-colors',
                collapsed && 'justify-center px-0',
                view === id
                  ? 'bg-accent-soft font-medium text-accent'
                  : 'text-ink-muted hover:bg-surface-2 hover:text-ink',
              )}
            >
              <Icon className="shrink-0 text-base" />
              {!collapsed && label}
            </button>
          ))}
        </nav>

        <div className="my-2 h-px bg-line" />

        {/* Processing indicator */}
        {processingDocs.length > 0 && (
          <div className="mb-1 rounded-xl border border-accent/25 bg-accent-soft/60 p-2.5">
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-accent">
              <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-accent" />
              Processing {processingDocs.length} document{processingDocs.length > 1 ? 's' : ''}
            </p>
            <div className="space-y-1">
              {processingDocs.slice(0, 3).map((d) => (
                <div key={d.id} className="flex items-center gap-2">
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-accent/15">
                    <div
                      className="h-full rounded-full bg-accent transition-all duration-500"
                      style={{ width: `${Math.max(6, d.progress * 100)}%` }}
                    />
                  </div>
                  <span className="shrink-0 text-[9px] text-ink-faint">
                    {STATUS_META[d.status].label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Collection selector */}
        {!collapsed && (
          <div className="mb-1">
            <button
              onClick={() => setShowCollections((v) => !v)}
              className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint transition-colors hover:text-ink-muted"
            >
              <IconFolder className="text-xs" />
              <span className="flex-1 text-left">Collection</span>
              <IconChevronDown
                className={cn('text-xs transition-transform', showCollections && 'rotate-180')}
              />
            </button>

            {showCollections && (
              <div className="mt-1 space-y-0.5">
                <CollectionRow
                  collection={null}
                  active={state.activeCollectionId === null}
                  label="All documents"
                  count={state.documents.length}
                  onSelect={() => setActiveCollection(null)}
                />
                {state.collections.map((c) => {
                  const count = state.documents.filter((d) => d.collection_id === c.id).length
                  return (
                    <CollectionRow
                      key={c.id}
                      collection={c}
                      active={state.activeCollectionId === c.id}
                      label={c.name}
                      count={count}
                      onSelect={() => setActiveCollection(c.id)}
                    />
                  )
                })}
              </div>
            )}
          </div>
        )}

        {/* Conversations */}
        {!collapsed && (
          <div className="mt-2 min-h-0 flex-1">
            <div className="mb-1.5 flex items-center justify-between px-2.5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                Conversations
              </span>
              <button
                onClick={newChat}
                className="rounded p-0.5 text-ink-faint transition-colors hover:text-ink"
                aria-label="New conversation"
              >
                <IconPlus className="text-xs" />
              </button>
            </div>

            <div className="relative mb-2">
              <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-faint" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search chats…"
                className="input py-1.5 pl-8 text-[13px]"
              />
              {query && (
                <button
                  onClick={() => setQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-faint hover:text-ink"
                >
                  <IconX className="text-xs" />
                </button>
              )}
            </div>

            <div className="max-h-[42vh] space-y-0.5 overflow-y-auto lg:max-h-full">
              {filteredConversations.length === 0 && (
                <p className="px-2.5 py-4 text-center text-xs text-ink-faint">
                  {query ? 'No matches' : 'No conversations yet'}
                </p>
              )}
              {filteredConversations.map((c) => (
                <div
                  key={c.id}
                  className={cn(
                    'group flex items-center gap-1 rounded-lg pr-1 transition-colors',
                    state.activeConversationId === c.id
                      ? 'bg-surface-2'
                      : 'hover:bg-surface-2',
                  )}
                >
                  <button
                    onClick={() => {
                      openConversation(c.id)
                      onViewChange('chat')
                    }}
                    className="min-w-0 flex-1 px-2.5 py-1.5 text-left"
                  >
                    <p className="truncate text-[13px] font-medium">{c.title}</p>
                    <p className="truncate text-[10px] text-ink-faint">
                      {c.message_count} msg{c.message_count === 1 ? '' : 's'} ·{' '}
                      {formatRelative(c.updated_at)}
                    </p>
                  </button>
                  <button
                    onClick={() => handleDeleteConversation(c.id)}
                    className="rounded p-1 text-ink-faint opacity-0 transition-all hover:text-red-500 group-hover:opacity-100"
                    aria-label={`Delete ${c.title}`}
                  >
                    <IconTrash className="text-xs" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className={cn('shrink-0 border-t border-line p-2.5', collapsed && 'px-1.5')}>
        <div className={cn('flex items-center gap-1', collapsed && 'flex-col')}>
          <button
            onClick={toggleTheme}
            className="btn-ghost flex-1 px-2 py-1.5"
            title={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
            aria-label={`Switch to ${resolvedTheme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {resolvedTheme === 'dark' ? <IconSun className="text-base" /> : <IconMoon className="text-base" />}
            {!collapsed && (resolvedTheme === 'dark' ? 'Light' : 'Dark')}
          </button>
          <button onClick={logout} className="btn-ghost px-2 py-1.5" title="Sign out">
            <IconLogOut className="text-base" />
            {!collapsed && 'Sign out'}
          </button>
        </div>
        {/* Pinned under the theme toggle and sign out, so it never scrolls away
            and always sits at the very bottom of the rail. */}
        {!collapsed ? (
          <MadeWithLove className="mt-2.5 border-t border-line pt-2.5" />
        ) : (
          <div className="mt-2.5 flex justify-center border-t border-line pt-2.5">
            <span title="Made with love by Parth" aria-label="Made with love by Parth">
              <svg viewBox="0 0 24 24" width="11" height="11" className="text-red-500" aria-hidden>
                <path
                  fill="currentColor"
                  d="M12 21s-7.5-4.7-9.6-9.2C.7 8.2 2.4 4.5 6 4.5c2.1 0 3.6 1.2 4.3 2.4h3.4C14.4 5.7 15.9 4.5 18 4.5c3.6 0 5.3 3.7 3.6 7.3C19.5 16.3 12 21 12 21z"
                />
              </svg>
            </span>
          </div>
        )}
      </div>
    </>
  )
}

function CollectionRow({
  collection,
  active,
  label,
  count,
  onSelect,
}: {
  collection: Collection | null
  active: boolean
  label: string
  count: number
  onSelect: () => void
}) {
  return (
    <button
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px] transition-colors',
        active ? 'bg-surface-2 font-medium text-ink' : 'text-ink-muted hover:bg-surface-2',
      )}
    >
      {collection ? (
        <span className="text-xs">{fileIcon(`${collection.name}.pdf`)}</span>
      ) : (
        <IconLayers className="text-xs" />
      )}
      <span className="min-w-0 flex-1 truncate text-left">{label}</span>
      <span className="shrink-0 text-[10px] text-ink-faint">{count}</span>
    </button>
  )
}
