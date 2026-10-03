/** A single chat message: user bubble or assistant answer with sources. */

import { memo, useState } from 'react'
import type { AnswerMode, Citation, Message, RetrievedChunk } from '../../lib/types'
import {
  cn,
  confidenceTone,
  copyToClipboard,
  downloadText,
  formatTime,
} from '../../lib/utils'
import { Markdown } from './Markdown'
import { ModeBadge } from './ModeBadge'
import {
  IconAlert,
  IconCheck,
  IconCopy,
  IconDownload,
  IconQuote,
  IconRefresh,
} from '../ui/Icons'

interface Props {
  message: Message
  streaming?: boolean
  citations?: Citation[]
  retrieved?: RetrievedChunk[]
  mode?: AnswerMode
  onCitationClick?: (citation: Citation) => void
  onRegenerate?: () => void
}

function MessageBubbleBase({
  message,
  streaming,
  citations = [],
  retrieved = [],
  mode,
  onCitationClick,
  onRegenerate,
}: Props) {
  const answerMode: AnswerMode = mode ?? message.mode ?? 'document'
  const [copied, setCopied] = useState(false)
  const isUser = message.role === 'user'

  async function handleCopy() {
    const ok = await copyToClipboard(message.content)
    if (ok) {
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    }
  }

  return (
    <div className={cn('group flex w-full animate-fade-in gap-3.5', isUser && 'flex-row-reverse')}>
      {/* Avatar */}
      <div
        className={cn(
          'mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[13px] font-semibold',
          isUser
            ? 'bg-surface-3 text-ink-muted'
            : 'bg-accent text-white shadow-card',
        )}
        aria-hidden
      >
        {isUser ? 'You'.slice(0, 1) : 'D'}
      </div>

      <div className={cn('flex min-w-0 flex-1 flex-col', isUser && 'items-end')}>
        {/* Bubble */}
        <div
          className={cn(
            'group/bubble relative w-full rounded-2xl px-4 py-3',
            isUser
              ? 'max-w-[85%] bg-surface-2 text-ink'
              : 'border border-line bg-surface-1 shadow-card',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed">{message.content}</p>
          ) : (
            <div className={cn(streaming && 'stream-caret')}>
              <Markdown
                content={message.content}
                onCitationClick={(index) => {
                  const hit = citations[index - 1]
                  if (hit && onCitationClick) onCitationClick(hit)
                }}
              />
            </div>
          )}

          {!isUser && !streaming && message.content.startsWith("I couldn't find") && (
            <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[12.5px] text-amber-700 dark:text-amber-400">
              <IconAlert className="mt-0.5 shrink-0" />
              <span>
                This answer was <strong>not</strong> grounded in your documents. No passages
                matched closely enough.
              </span>
            </div>
          )}
        </div>

        {/* Meta row */}
        {!streaming && (
          <div
            className={cn(
              'mt-1.5 flex items-center gap-2.5 px-1 text-[11px] text-ink-faint',
              isUser && 'flex-row-reverse',
            )}
          >
            <span>{formatTime(message.created_at)}</span>

            {!isUser && message.model && (
              <>
                <span className="h-2.5 w-px bg-line" />
                <span className="truncate font-mono">{message.model.split('::').pop()}</span>
              </>
            )}

            {!isUser && (
              <>
                <span className="h-2.5 w-px bg-line" />
                <span className={cn('font-medium', confidenceTone(message.confidence).className)}>
                  {message.grounded ? confidenceTone(message.confidence).label : 'Not grounded'}
                </span>
              </>
            )}

            {/* Actions */}
            <div className={cn('flex items-center gap-0.5', isUser && 'flex-row-reverse')}>
              <button
                onClick={handleCopy}
                className="rounded p-1 transition-colors hover:bg-surface-2 hover:text-ink"
                title={copied ? 'Copied' : 'Copy'}
                aria-label="Copy message"
              >
                {copied ? <IconCheck className="text-xs text-emerald-500" /> : <IconCopy className="text-xs" />}
              </button>

              {!isUser && (
                <>
                  <button
                    onClick={() =>
                      downloadText(
                        `docmind-${message.id.slice(0, 8)}.md`,
                        message.content,
                      )
                    }
                    className="rounded p-1 transition-colors hover:bg-surface-2 hover:text-ink"
                    title="Download as Markdown"
                    aria-label="Download answer"
                  >
                    <IconDownload className="text-xs" />
                  </button>
                  {onRegenerate && (
                    <button
                      onClick={onRegenerate}
                      className="rounded p-1 transition-colors hover:bg-surface-2 hover:text-ink"
                      title="Regenerate"
                      aria-label="Regenerate answer"
                    >
                      <IconRefresh className="text-xs" />
                    </button>
                  )}
                </>
              )}
            </div>
          </div>
        )}

        {/* Provenance: always state which subsystem answered */}
        {!isUser && !streaming && (
          <div className="mt-2 flex items-center gap-2">
            <ModeBadge mode={answerMode} grounded={message.grounded} />
            {citations.length > 0 && (
              <span className="text-[11px] text-ink-faint">
                {citations.length} citation{citations.length === 1 ? '' : 's'}
              </span>
            )}
          </div>
        )}

        {/* Sources */}
        {!isUser && !streaming && citations.length > 0 && (
          <Sources citations={citations} onCitationClick={onCitationClick} />
        )}

        {/* Retrieved passages, collapsed by default */}
        {!isUser && !streaming && retrieved.length > 0 && (
          <RetrievedPanel chunks={retrieved} onCitationClick={onCitationClick} />
        )}
      </div>
    </div>
  )
}

export const MessageBubble = memo(MessageBubbleBase)

function Sources({
  citations,
  onCitationClick,
}: {
  citations: Citation[]
  onCitationClick?: (c: Citation) => void
}) {
  const [expanded, setExpanded] = useState(true)
  return (
    <div className="mt-2.5 w-full">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-ink-faint transition-colors hover:text-ink-muted"
      >
        <IconQuote className="text-xs" />
        Sources ({citations.length})
        <span className="text-[10px]">{expanded ? '▾' : '▸'}</span>
      </button>

      {expanded && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {citations.map((c) => (
            <a
              key={`${c.document_id}-${c.rank}`}
              data-testid="citation-card"
              href={c.source_type === 'web' ? (c.source_url ?? undefined) : undefined}
              target={c.source_type === 'web' ? '_blank' : undefined}
              rel={c.source_type === 'web' ? 'noopener noreferrer' : undefined}
              onClick={(e) => {
                if (c.source_type !== 'web') {
                  e.preventDefault()
                  onCitationClick?.(c)
                }
              }}
              className="group/src flex flex-col gap-1 rounded-xl border border-line bg-surface-1 p-2.5 text-left transition-all hover:border-accent/45 hover:bg-accent-soft/30"
            >
              <div className="flex items-center gap-1.5">
                <span className="grid h-4 w-4 shrink-0 place-items-center rounded bg-accent-soft text-[9px] font-bold text-accent">
                  {c.rank}
                </span>
                <span className="min-w-0 flex-1 truncate text-[11.5px] font-medium">
                  {c.source_type === 'web' ? (c.domain ?? c.filename) : c.filename}
                </span>
                {c.source_type === 'web' ? (
                  <span className="chip shrink-0 !border-sky-500/30 !px-1.5 !py-0 text-[9px] !text-sky-600 dark:!text-sky-400">
                    web
                  </span>
                ) : (
                  c.page_number != null && (
                    <span className="chip shrink-0 !px-1.5 !py-0 text-[9px]">p{c.page_number}</span>
                  )
                )}
              </div>
              <p className="line-clamp-2 text-[11px] leading-snug text-ink-faint">{c.excerpt}</p>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function RetrievedPanel({
  chunks,
  onCitationClick,
}: {
  chunks: RetrievedChunk[]
  onCitationClick?: (c: Citation) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mt-2 w-full">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-ink-faint transition-colors hover:text-ink-muted"
      >
        {open ? '▾' : '▸'} {chunks.length} retrieved passage{chunks.length === 1 ? '' : 's'}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1.5">
          {chunks.map((c, i) => (
            <button
              key={c.chunk_id}
              onClick={() =>
                onCitationClick?.({
                  document_id: c.document_id,
                  filename: c.filename,
                  excerpt: c.text,
                  page_number: c.page_number,
                  section: c.section,
                  chunk_id: c.chunk_id,
                  score: c.score,
                  rank: i + 1,
                  source_type: c.source_type,
                  source_url: c.source_url,
                  domain: c.domain,
                })
              }
              className="block w-full rounded-lg border border-line/70 bg-surface-2/50 p-2 text-left text-[11px] transition-colors hover:border-accent/40"
            >
              <div className="mb-1 flex items-center gap-1.5 text-ink-faint">
                <span className="font-mono">{c.score.toFixed(3)}</span>
                <span className="truncate">{c.filename}</span>
                {c.page_number != null && <span>p{c.page_number}</span>}
              </div>
              <p className="line-clamp-3 leading-snug text-ink-muted">{c.text}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}