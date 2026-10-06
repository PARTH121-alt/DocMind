/**
 * Right-hand document preview.
 *
 * Opens when a citation is clicked and highlights the exact retrieved passage
 * inside the document's stored chunks.
 */

import { useCallback, useEffect, useState } from 'react'
import { eventName } from '../../lib/storage'
import { useApp } from '../../lib/AppContext'
import { documents as docsApi, meta } from '../../lib/api'
import type { DocumentChunk, DocumentItem } from '../../lib/types'
import { cn, formatBytes } from '../../lib/utils'
import { IconDownload, IconEye, IconSpinner, IconX } from '../ui/Icons'

export function PreviewPanel() {
  const { state, dispatch } = useApp()
  const [doc, setDoc] = useState<DocumentItem | null>(null)
  const [chunks, setChunks] = useState<DocumentChunk[]>([])
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const open = state.previewOpen

  const load = useCallback(
    async (docId: string, chunkId?: string | null) => {
      setLoading(true)
      setError(null)
      try {
        const fetched = await docsApi.get(docId)
        setDoc(fetched)
        const res = await docsApi.chunks(docId, 300)
        setChunks(res.chunks)
        if (chunkId) {
          setHighlightId(chunkId)
          // Scroll the highlighted passage into view.
          requestAnimationFrame(() => {
            globalThis.document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({
              behavior: 'smooth',
              block: 'center',
            })
          })
        }
      } catch (e) {
        setError((e as Error).message)
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  // Citation clicks arrive as a custom event from the chat surface.
  useEffect(() => {
    const onChunk = async (e: Event) => {
      const chunkId = (e as CustomEvent<string>).detail
      try {
        const ctx = await meta.chunkContext(chunkId)
        dispatch({ type: 'preview', open: true })
        await load(ctx.document_id, ctx.chunk_id)
      } catch {
        /* the citation may have been removed server-side */
      }
    }
    window.addEventListener(eventName('preview-chunk'), onChunk)
    return () => window.removeEventListener(eventName('preview-chunk'), onChunk)
  }, [dispatch, load])

  if (!open) return null

  function close() {
    dispatch({ type: 'preview', open: false })
    setHighlightId(null)
  }

  return (
    <aside className="hidden w-[26rem] shrink-0 flex-col border-l border-line bg-surface-1 xl:flex">
      <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4">
        <button onClick={close} className="btn-ghost px-2 py-1.5" title="Close preview">
          <IconX className="text-base" />
        </button>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-medium">
            {doc?.filename ?? 'Preview'}
          </p>
          {doc && (
            <p className="truncate text-[10px] text-ink-faint">
              {doc.page_count} page{doc.page_count === 1 ? '' : 's'} ·{' '}
              {doc.chunk_count} chunks · {formatBytes(doc.file_size)}
            </p>
          )}
        </div>
        {doc && (
          <a
            href={docsApi.rawUrl(doc.id)}
            target="_blank"
            rel="noreferrer"
            className="btn-ghost px-2 py-1.5"
            title="Open original file"
          >
            <IconDownload className="text-base" />
          </a>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && (
          <div className="space-y-3 p-4">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton h-20" />
            ))}
          </div>
        )}

        {error && (
          <div className="p-4">
            <p className="rounded-xl bg-red-500/10 px-3 py-2.5 text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          </div>
        )}

        {!loading && !error && !chunks.length && (
          <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
            <IconEye className="text-2xl text-ink-faint" />
            <p className="text-sm text-ink-muted">No previewable content</p>
          </div>
        )}

        {!loading &&
          chunks.map((c) => {
            const highlighted = c.id === highlightId
            return (
              <div
                key={c.id}
                id={`chunk-${c.id}`}
                className={cn(
                  'border-b border-line/60 px-4 py-3 transition-colors',
                  highlighted ? 'bg-accent-soft/70' : 'hover:bg-surface-2/40',
                )}
              >
                <div className="mb-1.5 flex items-center gap-2 text-[10px] text-ink-faint">
                  <span className="font-mono">#{c.index + 1}</span>
                  {c.page_number != null && (
                    <span className="chip !px-1.5 !py-0 text-[9px]">page {c.page_number}</span>
                  )}
                  {c.section && <span className="truncate">{c.section}</span>}
                  {highlighted && (
                    <span className="ml-auto font-medium text-accent">
                      ← cited passage
                    </span>
                  )}
                </div>
                <p
                  className={cn(
                    'whitespace-pre-wrap text-[13px] leading-relaxed',
                    highlighted ? 'text-ink' : 'text-ink-muted',
                  )}
                >
                  {c.text}
                </p>
              </div>
            )
          })}
      </div>

      {loading && (
        <div className="flex items-center justify-center gap-2 border-t border-line py-3 text-xs text-ink-faint">
          <IconSpinner /> Loading passages…
        </div>
      )}
    </aside>
  )
}
