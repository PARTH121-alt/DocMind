/** Documents library: upload, list, search, filter, and smart actions. */

import { useEffect, useMemo, useState } from 'react'
import { eventName } from '../../lib/storage'
import { useApp } from '../../lib/AppContext'
import * as api from '../../lib/api'
import type { DocumentItem, EmotionResponse, RetrievedChunk, SmartResponse } from '../../lib/types'
import { EmotionPanel } from './EmotionPanel'
import {
  cn,
  debounce,
  fileExtension,
  formatBytes,
  formatRelative,
  isProcessing,
  STATUS_META,
} from '../../lib/utils'
import { UploadDropzone, ProcessingQueue } from '../documents/UploadDropzone'
import { useToast } from '../ui/Toasts'
import {
  IconEye,
  IconFile,
  IconLayers,
  IconList,
  IconQuote,
  IconRefresh,
  IconSearch,
  IconSparkle,
  IconSpinner,
  IconTrash,
  IconHeart,
} from '../ui/Icons'

type ToolResult =
  | { kind: 'text'; title: string; content: string }
  | { kind: 'emotion'; title: string; data: EmotionResponse }
  | null

export function DocumentsView({ onOpenChat }: { onOpenChat: () => void }) {
  const { state, derived, reloadDocuments, dispatch } = useApp()
  const toast = useToast()
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busyTool, setBusyTool] = useState<string | null>(null)
  const [result, setResult] = useState<ToolResult>(null)

  const docs = state.documents

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return docs.filter((d) => {
      if (statusFilter !== 'all' && d.status !== statusFilter) return false
      if (q && !d.filename.toLowerCase().includes(q)) return false
      return true
    })
  }, [docs, query, statusFilter])

  // Server-side search when the query looks like a content query.
  const [searchHits, setSearchHits] = useState<RetrievedChunk[] | null>(null)
  const runContentSearch = useMemo(
    () =>
      debounce(async (q: string) => {
        if (q.trim().length < 3) {
          setSearchHits(null)
          return
        }
        try {
          const res = await api.search.query(q, 12, state.activeCollectionId)
          setSearchHits(res.results)
        } catch {
          setSearchHits(null)
        }
      }, 400),
    [state.activeCollectionId],
  )

  useEffect(() => {
    runContentSearch(query)
  }, [query, runContentSearch])

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function removeDoc(doc: DocumentItem) {
    if (!confirm(`Delete "${doc.filename}"? Its chunks and vectors will be removed.`)) return
    try {
      await api.documents.remove(doc.id)
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(doc.id)
        return next
      })
      await reloadDocuments()
      toast.push('Document deleted', 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  async function reprocess(doc: DocumentItem) {
    try {
      await api.documents.reprocess(doc.id)
      await reloadDocuments()
      toast.push(`Re-processing ${doc.filename}`, 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  function previewDoc(doc: DocumentItem) {
    dispatch({ type: 'preview', open: true })
    window.dispatchEvent(new CustomEvent(eventName('preview-doc'), { detail: doc.id }))
  }

  async function runTool(
    name: string,
    fn: () => Promise<SmartResponse | EmotionResponse>,
  ) {
    const ids = Array.from(selected)
    if (!ids.length) {
      toast.push('Select at least one indexed document first', 'error')
      return
    }
    setBusyTool(name)
    setResult(null)
    try {
      const res = await fn.call(null)
      if ('summary' in res && !('result' in res)) {
        setResult({ kind: 'emotion', title: 'Emotion analysis', data: res as EmotionResponse })
      } else {
        setResult({ kind: 'text', title: `${name} result`, content: (res as SmartResponse).result })
      }
      toast.push(`${name} finished in ${(res.processing_time_ms / 1000).toFixed(1)}s`, 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusyTool(null)
    }
  }

  const selectedCount = selected.size

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-line bg-surface-1/60 px-4 py-3 backdrop-blur-xl sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <h1 className="text-sm font-semibold tracking-tight">Documents</h1>
            <p className="text-[11px] text-ink-faint">
              {docs.length} document{docs.length === 1 ? '' : 's'} ·{' '}
              {derived.indexedDocuments.length} indexed in{' '}
              {derived.activeCollection?.name ?? 'all collections'}
            </p>
          </div>

          <div className="relative w-full sm:w-64">
            <IconSearch className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-xs text-ink-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search filenames or content…"
              className="input py-1.5 pl-8 text-[13px]"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="input w-auto py-1.5 text-[13px]"
          >
            <option value="all">All statuses</option>
            <option value="indexed">Indexed</option>
            <option value="failed">Failed</option>
            <option value="queued">Queued</option>
            <option value="embedding">Embedding</option>
          </select>
        </div>

        {/* Bulk actions */}
        {selectedCount > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 animate-fade-in">
            <span className="chip">{selectedCount} selected</span>
            <ToolButton icon={<IconHeart className="text-xs" />} label="Emotions" busy={busyTool === 'Emotions'}
              onClick={() =>
                runTool('Emotions', () =>
                  api.smart.emotions(Array.from(selected), state.activeCollectionId),
                )
              }
            />
            <ToolButton icon={<IconQuote className="text-xs" />} label="Summarize" busy={busyTool === 'Summarize'}
              onClick={() =>
                runTool('Summarize', () =>
                  api.smart.summarize(Array.from(selected), 'detailed', state.activeCollectionId),
                )
              }
            />
            <ToolButton icon={<IconLayers className="text-xs" />} label="Compare" busy={busyTool === 'Compare'}
              disabled={selectedCount < 2}
              onClick={() =>
                runTool('Compare', () =>
                  api.smart.compare(Array.from(selected), undefined, state.activeCollectionId),
                )
              }
            />
            <ToolButton icon={<IconList className="text-xs" />} label="Extract info" busy={busyTool === 'Extract info'}
              onClick={() =>
                runTool('Extract info', () =>
                  api.smart.extractInfo(
                    Array.from(selected),
                    ['names', 'dates', 'organizations', 'locations', 'technologies', 'financial figures'],
                    state.activeCollectionId,
                  ),
                )
              }
            />
            <ToolButton icon={<IconSparkle className="text-xs" />} label="Quiz" busy={busyTool === 'Quiz'}
              onClick={() =>
                runTool('Quiz', () =>
                  api.smart.quiz(Array.from(selected), 5, state.activeCollectionId),
                )
              }
            />
            <ToolButton icon={<IconFile className="text-xs" />} label="Study notes" busy={busyTool === 'Study notes'}
              onClick={() =>
                runTool('Study notes', () =>
                  api.smart.studyNotes(Array.from(selected), state.activeCollectionId),
                )
              }
            />
            <button
              onClick={() => setSelected(new Set())}
              className="btn-ghost ml-auto px-2 py-1 text-[11px]"
            >
              Clear
            </button>
          </div>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-5xl space-y-5">
          <ProcessingQueue />

          {/* Content search results */}
          {searchHits && searchHits.length > 0 && (
            <div className="card p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                <IconSearch className="text-xs" />
                Content matches ({searchHits.length})
              </p>
              <div className="space-y-1.5">
                {searchHits.slice(0, 8).map((hit) => (
                  <div
                    key={hit.chunk_id}
                    className="rounded-lg border border-line/70 bg-surface-2/40 p-2.5"
                  >
                    <div className="mb-1 flex items-center gap-2 text-[10px] text-ink-faint">
                      <span className="font-mono text-accent">{hit.score.toFixed(3)}</span>
                      <span className="truncate">{hit.filename}</span>
                      {hit.page_number != null && <span>page {hit.page_number}</span>}
                    </div>
                    <p className="line-clamp-2 text-[12.5px] leading-snug text-ink-muted">{hit.text}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Smart tool output */}
          {result && result.kind === 'emotion' && (
            <div className="card p-5" data-testid="emotion-result">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold">{result.title}</h2>
                <button onClick={() => setResult(null)} className="btn-ghost px-2 py-1 text-[11px]">
                  Close
                </button>
              </div>
              <EmotionPanel
                overall={result.data.overall}
                documents={result.data.documents}
                passages={result.data.charged_passages}
                summary={result.data.summary}
                latencyMs={result.data.processing_time_ms}
              />
            </div>
          )}

          {result && result.kind === 'text' && (
            <div className="card p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">{result.title}</h2>
                <button onClick={() => setResult(null)} className="btn-ghost px-2 py-1 text-[11px]">
                  Close
                </button>
              </div>
              <div className="markdown">
                <pre className="whitespace-pre-wrap font-sans text-[14px] leading-relaxed text-ink">
                  {result.content}
                </pre>
              </div>
              <button
                onClick={() => {
                  void navigator.clipboard?.writeText(result.content)
                  toast.push('Copied', 'success')
                  onOpenChat()
                }}
                className="btn-secondary mt-3"
              >
                Ask a follow-up question
              </button>
            </div>
          )}

          {/* Document grid */}
          {filtered.length === 0 ? (
            docs.length === 0 ? (
              <div className="card p-6">
                <UploadDropzone onUploaded={reloadDocuments} />
              </div>
            ) : (
              <p className="py-10 text-center text-sm text-ink-faint">No documents match</p>
            )
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {filtered.map((doc) => (
                <DocumentCard
                  key={doc.id}
                  doc={doc}
                  selected={selected.has(doc.id)}
                  onToggle={() => toggleSelect(doc.id)}
                  onPreview={() => previewDoc(doc)}
                  onReprocess={() => reprocess(doc)}
                  onDelete={() => removeDoc(doc)}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ToolButton({
  icon,
  label,
  onClick,
  busy,
  disabled,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
  busy?: boolean
  disabled?: boolean
}) {
  return (
    <button onClick={onClick} disabled={busy || disabled} className="btn-secondary px-2.5 py-1 text-[11px]">
      {busy ? <IconSpinner className="text-xs" /> : icon}
      {label}
    </button>
  )
}

function DocumentCard({
  doc,
  selected,
  onToggle,
  onPreview,
  onReprocess,
  onDelete,
}: {
  doc: DocumentItem
  selected: boolean
  onToggle: () => void
  onPreview: () => void
  onReprocess: () => void
  onDelete: () => void
}) {
  const meta = STATUS_META[doc.status]
  const processing = isProcessing(doc.status)

  return (
    <div
      className={cn(
        'card group relative flex flex-col p-3.5 transition-all hover:shadow-lift',
        selected && 'ring-2 ring-accent/50',
      )}
    >
      <div className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          disabled={doc.status !== 'indexed'}
          className="mt-1 h-3.5 w-3.5 shrink-0 accent-[rgb(var(--accent))]"
          aria-label={`Select ${doc.filename}`}
        />
        <span className="text-lg leading-none">{emojiFor(doc.filename)}</span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium" title={doc.filename}>
            {doc.filename}
          </p>
          <p className="truncate text-[10px] text-ink-faint">
            {fileExtension(doc.filename).toUpperCase()} · {formatBytes(doc.file_size)} ·{' '}
            {formatRelative(doc.created_at)}
          </p>
        </div>
      </div>

      {/* Status line */}
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[10px]">
          <span className={cn('font-medium', meta.tone)}>{meta.label}</span>
          {processing && (
            <span className="text-ink-faint">{Math.round(doc.progress * 100)}%</span>
          )}
        </div>
        <div className="h-1 overflow-hidden rounded-full bg-surface-2">
          <div
            className={cn(
              'h-full rounded-full transition-all duration-500',
              doc.status === 'failed'
                ? 'bg-red-500'
                : doc.status === 'indexed'
                  ? 'bg-emerald-500'
                  : 'bg-accent',
            )}
            style={{ width: `${doc.status === 'indexed' ? 100 : Math.max(3, doc.progress * 100)}%` }}
          />
        </div>
        {doc.status_detail && processing && (
          <p className="mt-1 truncate text-[10px] text-ink-faint">{doc.status_detail}</p>
        )}
      </div>

      {/* Stats */}
      <div className="mt-3 grid grid-cols-3 gap-1.5 text-center">
        <Stat label="Pages" value={doc.page_count || '—'} />
        <Stat label="Chunks" value={doc.chunk_count || '—'} />
        <Stat label="Words" value={doc.word_count ? doc.word_count.toLocaleString() : '—'} />
      </div>

      {doc.used_ocr && (
        <span className="chip mt-2 self-start !py-0.5 text-[9px]">OCR applied</span>
      )}

      {doc.status === 'failed' && doc.error && (
        <p className="mt-2 line-clamp-2 rounded-lg bg-red-500/10 px-2 py-1.5 text-[10px] text-red-600 dark:text-red-400">
          {doc.error}
        </p>
      )}

      {/* Actions - dimmed until hover so the card does not reserve dead space */}
      <div className="mt-3 flex items-center gap-1 border-t border-line pt-2.5 opacity-60 transition-opacity group-hover:opacity-100">
        <button onClick={onPreview} className="btn-ghost flex-1 px-2 py-1 text-[11px]" title="Preview">
          <IconEye className="text-xs" /> Open
        </button>
        <button
          onClick={onReprocess}
          className="btn-ghost px-2 py-1"
          title="Re-process"
          aria-label="Re-process"
        >
          <IconRefresh className="text-xs" />
        </button>
        <button
          onClick={onDelete}
          className="btn-ghost px-2 py-1 hover:text-red-500"
          title="Delete"
          aria-label="Delete"
        >
          <IconTrash className="text-xs" />
        </button>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-surface-2 py-1.5">
      <p className="text-[13px] font-semibold leading-none">{value}</p>
      <p className="mt-0.5 text-[9px] text-ink-faint">{label}</p>
    </div>
  )
}

function emojiFor(filename: string): string {
  const map: Record<string, string> = {
    pdf: '📕', docx: '📘', doc: '📘', xlsx: '📗', xls: '📗', csv: '📗',
    pptx: '📙', ppt: '📙', png: '🖼️', jpg: '🖼️', jpeg: '🖼️', webp: '🖼️',
    json: '🧾', md: '📄', markdown: '📄', txt: '📄',
  }
  return map[fileExtension(filename)] ?? '📄'
}