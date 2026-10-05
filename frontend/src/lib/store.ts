/**
 * Application state.
 *
 * A single reducer-backed store holds auth, the active collection, the active
 * conversation, documents and server capabilities. Keeping this in one place
 * avoids prop drilling across the three-column layout.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'
import * as api from './api'
import type {
  Collection,
  Conversation,
  DocumentItem,
  Health,
  Message,
  ModelsResponse,
  User,
} from './types'

export interface State {
  user: User | null
  booting: boolean
  health: Health | null
  models: ModelsResponse | null
  collections: Collection[]
  activeCollectionId: string | null
  documents: DocumentItem[]
  conversations: Conversation[]
  activeConversationId: string | null
  messages: Message[]
  loadingMessages: boolean
  sidebarOpen: boolean
  previewOpen: boolean
  theme: 'light' | 'dark' | 'system'
  error: string | null
}

type Action =
  | { type: 'boot/done'; user: User | null }
  | { type: 'boot/start' }
  | { type: 'health/set'; health: Health | null }
  | { type: 'models/set'; models: ModelsResponse | null }
  | { type: 'collections/set'; collections: Collection[] }
  | { type: 'collection/active'; id: string | null }
  | { type: 'documents/set'; documents: DocumentItem[] }
  | { type: 'conversations/set'; conversations: Conversation[] }
  | { type: 'conversation/active'; id: string | null }
  | { type: 'messages/set'; messages: Message[] }
  | { type: 'messages/loading'; value: boolean }
  | { type: 'message/append'; message: Message }
  | { type: 'message/patch'; id: string; patch: Partial<Message> }
  | { type: 'message/removeLast' }
  | { type: 'sidebar'; open: boolean }
  | { type: 'preview'; open: boolean }
  | { type: 'theme'; theme: State['theme'] }
  | { type: 'error'; message: string | null }
  | { type: 'reset' }

const initial: State = {
  user: null,
  booting: true,
  health: null,
  models: null,
  collections: [],
  activeCollectionId: null,
  documents: [],
  conversations: [],
  activeConversationId: null,
  messages: [],
  loadingMessages: false,
  // Expanded by default; the user can collapse to icon-only mode.
  sidebarOpen: true,
  previewOpen: false,
  theme: 'system',
  error: null,
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'boot/start':
      return { ...state, booting: true }
    case 'boot/done':
      return { ...state, booting: false, user: action.user }
    case 'health/set':
      return { ...state, health: action.health }
    case 'models/set':
      return { ...state, models: action.models }
    case 'collections/set':
      return { ...state, collections: action.collections }
    case 'collection/active':
      return { ...state, activeCollectionId: action.id }
    case 'documents/set':
      return { ...state, documents: action.documents }
    case 'conversations/set':
      return { ...state, conversations: action.conversations }
    case 'conversation/active':
      return {
        ...state,
        activeConversationId: action.id,
        messages: action.id ? state.messages : [],
      }
    case 'messages/set':
      return { ...state, messages: action.messages }
    case 'messages/loading':
      return { ...state, loadingMessages: action.value }
    case 'message/append':
      return { ...state, messages: [...state.messages, action.message] }
    case 'message/patch':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.id ? { ...m, ...action.patch } : m,
        ),
      }
    case 'message/removeLast':
      return { ...state, messages: state.messages.slice(0, -1) }
    case 'sidebar':
      return { ...state, sidebarOpen: action.open }
    case 'preview':
      return { ...state, previewOpen: action.open }
    case 'theme':
      return { ...state, theme: action.theme }
    case 'error':
      return { ...state, error: action.message }
    case 'reset':
      return { ...initial, booting: false, theme: state.theme }
    default:
      return state
  }
}

const COLLECTION_KEY = 'docmind.collection'

export function useAppState() {
  const [state, dispatch] = useReducer(reducer, initial)
  // Guards against polling overlapping a slow in-flight request.
  const pollRef = useRef<number | null>(null)

  // ---- Theme ------------------------------------------------------------
  // `theme` is the user's preference; `resolvedTheme` is what is actually
  // applied. Toggling must be based on the resolved value, otherwise a
  // "system" preference whose resolved appearance is dark would render a
  // "Dark" button that sets dark again instead of switching to light.
  const prefersDark = useMemo(
    () =>
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches,
    // Recompute when the OS preference changes.
    [state.theme],
  )

  const resolvedTheme: 'light' | 'dark' = useMemo(() => {
    if (state.theme === 'system') return prefersDark ? 'dark' : 'light'
    return state.theme
  }, [state.theme, prefersDark])

  useEffect(() => {
    const saved = (localStorage.getItem('docmind.theme') as State['theme']) || 'system'
    // Persist the default immediately so storage and state never disagree.
    if (!localStorage.getItem('docmind.theme')) {
      localStorage.setItem('docmind.theme', saved)
    }
    dispatch({ type: 'theme', theme: saved })
  }, [])

  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolvedTheme === 'dark')
  }, [resolvedTheme])

  // Follow the OS while the preference is "system".
  useEffect(() => {
    if (state.theme !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => dispatch({ type: 'theme', theme: 'system' })
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [state.theme])

  const setTheme = useCallback((theme: State['theme']) => {
    localStorage.setItem('docmind.theme', theme)
    dispatch({ type: 'theme', theme })
  }, [])

  /** Flip between explicit light and dark, resolving "system" first. */
  const toggleTheme = useCallback(() => {
    setTheme(resolvedTheme === 'dark' ? 'light' : 'dark')
  }, [resolvedTheme, setTheme])

  // ---- Boot -------------------------------------------------------------
  const refreshAll = useCallback(async () => {
    const [collections, conversations, docs, models] = await Promise.allSettled([
      api.collections.list(),
      api.conversations.list(),
      api.documents.list({ collection_id: state.activeCollectionId ?? undefined }),
      // Fetched here as well as at boot: signing in or registering does not
      // reload the page, so boot's copy never runs and the model selector
      // would otherwise render empty for the whole session.
      api.meta.models(),
    ])

    if (models.status === 'fulfilled') {
      dispatch({ type: 'models/set', models: models.value })
    }

    if (collections.status === 'fulfilled') {
      dispatch({ type: 'collections/set', collections: collections.value })
      // Default to the first collection so the user always has a scope.
      setTimeout(() => {
        const stored = localStorage.getItem(COLLECTION_KEY)
        if (stored && collections.value.some((c) => c.id === stored)) {
          dispatch({ type: 'collection/active', id: stored })
        } else if (collections.value.length) {
          const def = collections.value.find((c) => c.is_default) ?? collections.value[0]
          dispatch({ type: 'collection/active', id: def.id })
        }
      }, 0)
    }
    if (conversations.status === 'fulfilled') {
      dispatch({ type: 'conversations/set', conversations: conversations.value })
    }
    if (docs.status === 'fulfilled') {
      dispatch({ type: 'documents/set', documents: docs.value.items })
    }
  }, [state.activeCollectionId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      dispatch({ type: 'boot/start' })
      api.meta
        .health()
        .then((h) => !cancelled && dispatch({ type: 'health/set', health: h }))
        .catch(() => undefined)

      if (!api.getToken()) {
        if (!cancelled) dispatch({ type: 'boot/done', user: null })
        return
      }
      try {
        const user = await api.auth.me()
        if (cancelled) return
        dispatch({ type: 'boot/done', user })
        await refreshAll()
      } catch {
        if (!cancelled) dispatch({ type: 'boot/done', user: null })
      }
    })()
    return () => {
      cancelled = true
    }
    // Boot once; refreshAll is stable enough for this purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The 401 interceptor resets the session; mirror that into the store.
  useEffect(() => {
    const onUnauthorized = () => {
      api.setToken(null)
      dispatch({ type: 'reset' })
    }
    window.addEventListener('docmind:unauthorized', onUnauthorized)
    return () => window.removeEventListener('docmind:unauthorized', onUnauthorized)
  }, [])

  // ---- Document polling -------------------------------------------------
  // Keeps progress bars live while background indexing runs.
  useEffect(() => {
    if (!state.user) return
    const hasActive = state.documents.some(
      (d) => d.status !== 'indexed' && d.status !== 'failed',
    )
    if (!hasActive) return

    const tick = async () => {
      try {
        const res = await api.documents.list({
          collection_id: state.activeCollectionId ?? undefined,
        })
        dispatch({ type: 'documents/set', documents: res.items })
      } catch {
        /* transient; the next tick retries */
      }
    }
    pollRef.current = window.setInterval(tick, 1500)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [state.user, state.activeCollectionId, state.documents])

  // ---- Collection changes ----------------------------------------------
  const setActiveCollection = useCallback((id: string | null) => {
    dispatch({ type: 'collection/active', id })
    if (id) localStorage.setItem(COLLECTION_KEY, id)
    else localStorage.removeItem(COLLECTION_KEY)
  }, [])

  // ---- Actions ----------------------------------------------------------
  const login = useCallback(async (identifier: string, password: string) => {
    const res = await api.auth.login(identifier, password)
    api.setToken(res.access_token)
    dispatch({ type: 'boot/done', user: res.user })
    await refreshAll()
    return res.user
  }, [refreshAll])

  const register = useCallback(async (email: string, username: string, password: string) => {
    const res = await api.auth.register(email, username, password)
    api.setToken(res.access_token)
    dispatch({ type: 'boot/done', user: res.user })
    await refreshAll()
    return res.user
  }, [refreshAll])

  const logout = useCallback(() => {
    api.setToken(null)
    dispatch({ type: 'reset' })
  }, [])

  const reloadDocuments = useCallback(async () => {
    const res = await api.documents.list({
      collection_id: state.activeCollectionId ?? undefined,
    })
    dispatch({ type: 'documents/set', documents: res.items })
  }, [state.activeCollectionId])

  const reloadConversations = useCallback(async () => {
    const res = await api.conversations.list()
    dispatch({ type: 'conversations/set', conversations: res })
  }, [])

  const openConversation = useCallback(async (id: string) => {
    dispatch({ type: 'conversation/active', id })
    dispatch({ type: 'messages/loading', value: true })
    try {
      const detail = await api.conversations.get(id)
      dispatch({ type: 'messages/set', messages: detail.messages })
    } catch (e) {
      dispatch({ type: 'error', message: (e as Error).message })
    } finally {
      dispatch({ type: 'messages/loading', value: false })
    }
  }, [])

  const newChat = useCallback(() => {
    dispatch({ type: 'conversation/active', id: null })
    dispatch({ type: 'messages/set', messages: [] })
    dispatch({ type: 'preview', open: false })
  }, [])

  const derived = useMemo(
    () => ({
      indexedDocuments: state.documents.filter((d) => d.status === 'indexed'),
      hasDocuments: state.documents.length > 0,
      hasIndexed: state.documents.some((d) => d.status === 'indexed'),
      activeCollection: state.collections.find((c) => c.id === state.activeCollectionId) ?? null,
    }),
    [state.documents, state.collections, state.activeCollectionId],
  )

  return {
    state,
    derived,
    dispatch,
    resolvedTheme,
    toggleTheme,
    setTheme,
    setActiveCollection,
    login,
    register,
    logout,
    reloadDocuments,
    reloadConversations,
    openConversation,
    newChat,
    refreshAll,
  }
}

export type AppStore = ReturnType<typeof useAppState>
