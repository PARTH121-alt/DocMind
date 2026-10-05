/**
 * Typed API client.
 *
 * The access token lives in localStorage and is attached as a Bearer header.
 * The HF token is never present here - it stays on the server and the frontend
 * only ever sees `hf_token_configured: boolean`.
 */

import type {
  WebResponse,
  AppSettings,
  AuthResponse,
  ChatResponse,
  ChunkContext,
  Collection,
  DocumentChunk,
  Conversation,
  ConversationDetail,
  DocumentItem,
  DocumentList,
  Health,
  ModelsResponse,
  SmartResponse,
  EmotionResponse,
} from './types'

const BASE = '/api'
const TOKEN_KEY = 'docmind.token'

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(
  path: string,
  init: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const { auth = true, ...rest } = init
  const headers = new Headers(rest.headers)
  if (auth) {
    const token = getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  if (rest.body && !(rest.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${BASE}${path}`, { ...rest, headers })

  if (res.status === 401 && auth) {
    setToken(null)
    // Let the app shell render the login screen.
    window.dispatchEvent(new CustomEvent('docmind:unauthorized'))
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (typeof body?.detail === 'string') detail = body.detail
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
export const auth = {
  register: (email: string, username: string, password: string) =>
    request<AuthResponse>('/auth/register', {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ email, username, password }),
    }),
  login: (identifier: string, password: string) =>
    request<AuthResponse>('/auth/login', {
      method: 'POST',
      auth: false,
      body: JSON.stringify({ identifier, password }),
    }),
  me: () => request<AuthResponse['user']>('/auth/me'),
}

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------
export const documents = {
  list: (params: { collection_id?: string; status?: string; search?: string; page?: number } = {}) => {
    const qs = new URLSearchParams()
    if (params.collection_id) qs.set('collection_id', params.collection_id)
    if (params.status) qs.set('status', params.status)
    if (params.search) qs.set('search', params.search)
    if (params.page) qs.set('page', String(params.page))
    return request<DocumentList>(`/documents?${qs}`)
  },
  get: (id: string) => request<DocumentItem>(`/documents/${id}`),
  chunks: (id: string, limit = 200) =>
    request<{ total: number; chunks: DocumentChunk[] }>(`/documents/${id}/chunks?limit=${limit}`),
  reprocess: (id: string) => request<DocumentItem>(`/documents/${id}/process`, { method: 'POST' }),
  remove: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  upload: (files: File[], collectionId?: string | null) => {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    if (collectionId) form.append('collection_id', collectionId)
    return request<DocumentItem[]>('/documents/upload', { method: 'POST', body: form })
  },
  rawUrl: (id: string) => `${BASE}/documents/${id}/raw`,
}

// ---------------------------------------------------------------------------
// Collections
// ---------------------------------------------------------------------------
export const collections = {
  list: () => request<Collection[]>('/collections'),
  create: (name: string, description = '') => request<Collection>('/collections', {
    method: 'POST',
    body: JSON.stringify({ name, description }),
  }),
  update: (id: string, patch: Partial<Pick<Collection, 'name' | 'description' | 'color'>>) =>
    request<Collection>(`/collections/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => request<void>(`/collections/${id}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Conversations
// ---------------------------------------------------------------------------
export const conversations = {
  list: (search?: string) =>
    request<Conversation[]>(`/conversations${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  get: (id: string) => request<ConversationDetail>(`/conversations/${id}`),
  create: (title = 'New Chat', collectionId?: string | null) =>
    request<Conversation>('/conversations', {
      method: 'POST',
      body: JSON.stringify({ title, collection_id: collectionId ?? null }),
    }),
  update: (id: string, patch: { title?: string; collection_id?: string | null; model?: string }) =>
    request<Conversation>(`/conversations/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => request<void>(`/conversations/${id}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
export interface ChatParams {
  question: string
  conversation_id?: string | null
  collection_id?: string | null
  model?: string | null
  temperature?: number | null
  top_p?: number | null
  max_tokens?: number | null
  top_k?: number | null
  document_ids?: string[] | null
  allow_general?: boolean | null
  allow_web?: boolean | null
  search_web?: boolean | null
}

export const chat = {
  send: (params: ChatParams) =>
    request<ChatResponse>('/chat', { method: 'POST', body: JSON.stringify(params) }),

  /**
   * Stream an answer over SSE.
   *
   * `onEvent` receives every server event. Returns an abort function so the
   * UI can implement "stop generating" with a real network cancellation.
   */
  stream(
    params: ChatParams,
    onEvent: (event: string, data: Record<string, unknown>) => void,
    onError?: (message: string) => void,
  ): () => void {
    const controller = new AbortController()

    ;(async () => {
      try {
        const headers: HeadersInit = { 'Content-Type': 'application/json' }
        const token = getToken()
        if (token) (headers as Record<string, string>).Authorization = `Bearer ${token}`

        const res = await fetch(`${BASE}/chat/stream`, {
          method: 'POST',
          headers,
          body: JSON.stringify(params),
          signal: controller.signal,
        })

        if (!res.ok || !res.body) {
          onError?.(`Stream failed (${res.status})`)
          return
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // SSE frames are separated by a blank line.
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''

          for (const frame of frames) {
            let event = 'message'
            const dataLines: string[] = []
            for (const line of frame.split('\n')) {
              if (line.startsWith('event: ')) event = line.slice(7).trim()
              else if (line.startsWith('data: ')) dataLines.push(line.slice(6))
            }
            if (!dataLines.length) continue
            try {
              onEvent(event, JSON.parse(dataLines.join('\n')))
            } catch {
              /* ignore malformed frame */
            }
          }
        }
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          onError?.((err as Error).message)
        }
      }
    })()

    return () => controller.abort()
  },
}

// ---------------------------------------------------------------------------
// Search + smart features
// ---------------------------------------------------------------------------
export const search = {
  query: (q: string, topK = 8, collectionId?: string | null) =>
    request<{ query: string; results: import('./types').RetrievedChunk[]; count: number }>('/search', {
      method: 'POST',
      body: JSON.stringify({ query: q, top_k: topK, collection_id: collectionId ?? null }),
    }),
}

export const smart = {
  emotions: (documentIds: string[], collectionId?: string | null) =>
    request<EmotionResponse>('/documents/emotions', {
      method: 'POST',
      body: JSON.stringify({
        document_ids: documentIds,
        collection_id: collectionId ?? null,
        top_passages: 6,
      }),
    }),
  summarize: (documentIds: string[], style: string, collectionId?: string | null) =>
    request<SmartResponse>('/documents/summarize', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, style, collection_id: collectionId ?? null }),
    }),
  compare: (documentIds: string[], aspect?: string, collectionId?: string | null) =>
    request<SmartResponse>('/documents/compare', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, aspect: aspect ?? null, collection_id: collectionId ?? null }),
    }),
  extractInfo: (documentIds: string[], fields: string[], collectionId?: string | null) =>
    request<SmartResponse>('/documents/extract-info', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, fields, collection_id: collectionId ?? null }),
    }),
  quiz: (documentIds: string[], numQuestions: number, collectionId?: string | null) =>
    request<SmartResponse>('/documents/quiz', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, num_questions: numQuestions, collection_id: collectionId ?? null }),
    }),
  studyNotes: (documentIds: string[], collectionId?: string | null) =>
    request<SmartResponse>('/documents/study-notes', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, collection_id: collectionId ?? null }),
    }),
  suggestedQuestions: (documentIds: string[], collectionId?: string | null) =>
    request<{ questions: string[]; sources: string[] }>('/documents/suggested-questions', {
      method: 'POST',
      body: JSON.stringify({ document_ids: documentIds, collection_id: collectionId ?? null }),
    }),
}

// ---------------------------------------------------------------------------
// Web search / page ingestion
// ---------------------------------------------------------------------------
export type { WebResponse } from './types'

export const web = {
  providers: () =>
    request<{ active: string; providers: { name: string; configured: boolean; requires_key: boolean; env_var: string | null }[] }>(
      '/web/providers',
    ),

  search: (query: string, maxResults = 5) =>
    request<WebResponse>(`/web/search?query=${encodeURIComponent(query)}&max_results=${maxResults}`),

  fetchPages: (urls: string[], collectionId?: string | null) =>
    request<WebResponse>('/web/fetch', {
      method: 'POST',
      body: JSON.stringify({ urls, collection_id: collectionId ?? null }),
    }),
}

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------
export const meta = {
  models: () => request<ModelsResponse>('/models'),
  health: () => request<Health>('/health', { auth: false }),
  settings: () => request<AppSettings>('/settings'),
  updateSettings: (preferences: Record<string, unknown>) =>
    request<{ preferences: Record<string, unknown> }>('/settings', {
      method: 'PUT',
      body: JSON.stringify({ preferences }),
    }),
  chunkContext: (chunkId: string) => request<ChunkContext>(`/chunks/${chunkId}/context`),
  evaluationDatasets: () =>
    request<{ available: boolean; datasets: { key: string; hf_id: string; name: string; task: string }[] }>(
      '/evaluation/datasets',
    ),
}
