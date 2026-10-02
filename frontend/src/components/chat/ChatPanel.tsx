/** Center chat surface: header, message list, composer, empty state. */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import * as api from '../../lib/api'
import type { Citation, RetrievedChunk } from '../../lib/types'
import { copyToClipboard, downloadText } from '../../lib/utils'
import { MessageBubble } from './MessageBubble'
import { EmptyState } from './EmptyState'
import { Composer } from './Composer'
import { ChatHeader } from './ChatHeader'
import { useToast } from '../ui/Toasts'
import { IconCopy, IconDownload, IconSpinner, IconTrash } from '../ui/Icons'

/** Mirrors the server's refusal message so streamed sentinels never show. */
const REFUSAL_FALLBACK =
  "I couldn't find enough information in the uploaded documents to answer that confidently."

/**
 * Hide the model's internal sentinel while it streams. The server still
 * decides whether the turn is grounded; this only stops the raw token from
 * flashing on screen.
 */
function scrubDelta(text: string): string {
  return text.replace(/\bnot[_\s-]*in[_\s-]*docs\b/gi, '')
}

/** Optimistic message used while a streamed answer is in flight. */
interface StreamingState {
  text: string
  citations: Citation[]
  retrieved: RetrievedChunk[]
  confidence: number
  sources: string[]
}

export function ChatPanel() {
  const { state, derived, dispatch, newChat, reloadConversations, openConversation } = useApp()
  const toast = useToast()

  const [streaming, setStreaming] = useState<StreamingState | null>(null)
  const abortRef = useRef<(() => void) | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastQuestion = useRef<string>('')

  const messages = state.messages
  const conversation = state.conversations.find((c) => c.id === state.activeConversationId)

  // ---- Auto-scroll while streaming -------------------------------------
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 180
    if (nearBottom || streaming) el.scrollTop = el.scrollHeight
  }, [messages.length, streaming?.text, streaming])

  const send = useCallback(
    async (question: string, opts: { regenerate?: boolean } = {}) => {
      if (!question.trim() || streaming) return

      lastQuestion.current = question

      // On regenerate, drop the trailing assistant turn and re-ask.
      let baseMessages = messages
      if (opts.regenerate && messages.length >= 2) {
        baseMessages = messages.slice(0, -2)
      }

      const tempId = `pending-${Date.now()}`
      if (!opts.regenerate) {
        dispatch({
          type: 'messages/set',
          messages: [
            ...baseMessages,
            {
              id: tempId,
              role: 'user',
              content: question,
              model: null,
              grounded: false,
              confidence: null,
              latency_ms: null,
              created_at: new Date().toISOString(),
              citations: [],
            },
          ],
        })
      }

      setStreaming({ text: '', citations: [], retrieved: [], confidence: 0, sources: [] })

      const stop = api.chat.stream(
        {
          question,
          conversation_id: opts.regenerate ? state.activeConversationId : state.activeConversationId,
          collection_id: state.activeCollectionId,
          document_ids: null,
        },
        (event, data) => {
          if (event === 'sources') {
            setStreaming((s) =>
              s
                ? {
                    ...s,
                    sources: (data.sources as string[]) ?? [],
                    retrieved: (data.chunks as RetrievedChunk[]) ?? [],
                    confidence: (data.confidence as number) ?? 0,
                  }
                : s,
            )
          } else if (event === 'delta') {
            setStreaming((s) => (s ? { ...s, text: s.text + scrubDelta(data.text as string) } : s))
          } else if (event === 'done') {
            // The server is authoritative: a refusal arrives here with the
            // user-facing message and grounded=false, replacing any raw
            // sentinel the model may have streamed before it was caught.
            const convId = data.conversation_id as string
            setStreaming((s) =>
              s && data.grounded === false
                ? { ...s, text: (data.answer as string) || REFUSAL_FALLBACK }
                : s,
            )
            dispatch({ type: 'conversation/active', id: convId })
            void reloadConversations()
            void openConversation(convId)
            setStreaming(null)
          } else if (event === 'error') {
            toast.push((data.message as string) ?? 'Generation failed', 'error')
            setStreaming(null)
          }
        },
        (message) => {
          toast.push(message, 'error')
          setStreaming(null)
        },
      )
      abortRef.current = stop
    },
    [messages, streaming, state.activeCollectionId, state.activeConversationId, dispatch, openConversation, reloadConversations, toast],
  )

  const stopGeneration = () => {
    abortRef.current?.()
    abortRef.current = null
    setStreaming(null)
  }

  async function clearConversation() {
    stopGeneration()
    if (state.activeConversationId) {
      await api.conversations.remove(state.activeConversationId).catch(() => undefined)
    }
    newChat()
    await reloadConversations()
    toast.push('Conversation cleared', 'success')
  }

  async function exportConversation() {
    const lines = messages.map((m) =>
      m.role === 'user' ? `## You\n\n${m.content}` : `## DocMind\n\n${m.content}`,
    )
    downloadText(`${conversation?.title ?? 'conversation'}.md`, `# ${conversation?.title ?? 'Conversation'}\n\n${lines.join('\n\n---\n\n')}`)
  }

  const hasMessages = messages.length > 0 || Boolean(streaming)

  const transcript = useMemo(
    () =>
      messages
        .map((m) => `${m.role === 'user' ? 'You' : 'DocMind'}: ${m.content}`)
        .join('\n\n'),
    [messages],
  )

  return (
    <div className="flex h-full min-w-0 flex-1 flex-col">
      <ChatHeader />

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
          {!hasMessages ? (
            <EmptyState onAsk={(q) => send(q)} />
          ) : (
            <div className="space-y-6">
              {messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  message={m}
                  citations={m.citations}
                  onCitationClick={(c) => {
                    dispatch({ type: 'preview', open: true })
                    window.dispatchEvent(
                      new CustomEvent('docmind:preview-chunk', {
                        detail: c.chunk_id,
                      }),
                    )
                  }}
                  onRegenerate={
                    m.role === 'assistant' ? () => send(lastQuestion.current, { regenerate: true }) : undefined
                  }
                />
              ))}

              {streaming && (
                <div className="group flex w-full animate-fade-in gap-3.5">
                  <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-accent text-white shadow-card">
                    D
                  </div>
                  <div className="min-w-0 flex-1">
                    {streaming.text ? (
                      <MessageBubble
                        message={{
                          id: 'streaming',
                          role: 'assistant',
                          content: streaming.text,
                          model: null,
                          grounded: false,
                          confidence: streaming.confidence,
                          latency_ms: null,
                          created_at: new Date().toISOString(),
                          citations: streaming.citations,
                        }}
                        streaming
                        citations={streaming.citations}
                        retrieved={streaming.retrieved}
                      />
                    ) : (
                      <ThinkingIndicator sources={streaming.sources} />
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Transcript actions */}
      {hasMessages && (
        <div className="border-t border-line bg-surface-0/80 px-4 py-1.5 backdrop-blur sm:px-6">
          <div className="mx-auto flex max-w-3xl items-center justify-end gap-1">
            <button
              onClick={async () => {
                const ok = await copyToClipboard(transcript)
                toast.push(ok ? 'Conversation copied' : 'Copy failed', ok ? 'success' : 'error')
              }}
              className="btn-ghost px-2 py-1 text-[11px]"
            >
              <IconCopy className="text-xs" /> Copy all
            </button>
            <button onClick={exportConversation} className="btn-ghost px-2 py-1 text-[11px]">
              <IconDownload className="text-xs" /> Export
            </button>
            <button onClick={clearConversation} className="btn-ghost px-2 py-1 text-[11px]">
              <IconTrash className="text-xs" /> Clear
            </button>
          </div>
        </div>
      )}

      <Composer
        onSend={send}
        onStop={stopGeneration}
        streaming={Boolean(streaming)}
        disabled={!derived.hasIndexed}
      />
    </div>
  )
}

function ThinkingIndicator({ sources }: { sources: string[] }) {
  const [dots, setDots] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setDots((d) => (d + 1) % 4), 400)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="rounded-2xl border border-line bg-surface-1 px-4 py-3 shadow-card">
      <div className="flex items-center gap-2 text-[13px] text-ink-muted">
        <IconSpinner className="text-sm text-accent" />
        <span>
          Searching your documents
          <span className="inline-block w-4 text-left">{'.'.repeat(dots)}</span>
        </span>
      </div>
      {sources.length > 0 && (
        <p className="mt-1.5 text-[11px] text-ink-faint">Found passages in {sources.join(', ')}</p>
      )}
    </div>
  )
}
