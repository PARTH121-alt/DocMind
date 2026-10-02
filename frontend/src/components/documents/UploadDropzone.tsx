/** Drag-and-drop upload area with per-file processing status. */

import { useCallback, useRef, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import { documents as docsApi } from '../../lib/api'
import { cn, isProcessing, STATUS_META } from '../../lib/utils'
import { useToast } from '../ui/Toasts'
import { IconUpload } from '../ui/Icons'

const SUPPORTED = 'PDF, DOCX, TXT, CSV, XLSX, PPTX, MD, JSON, images (PNG, JPG)'

export function UploadDropzone({
  compact = false,
  onUploaded,
}: {
  compact?: boolean
  onUploaded?: () => void
}) {
  const { state, reloadDocuments } = useApp()
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const handleFiles = useCallback(
    async (files: FileList | File[]) => {
      const list = Array.from(files)
      if (!list.length) return

      setUploading(true)
      setErrors([])
      try {
        await docsApi.upload(list, state.activeCollectionId)
        await reloadDocuments()
        toast.push(
          `Uploaded ${list.length} file${list.length > 1 ? 's' : ''} - indexing now`,
          'success',
        )
        onUploaded?.()
      } catch (e) {
        const message = (e as Error).message
        setErrors([message])
        toast.push(message, 'error')
      } finally {
        setUploading(false)
      }
    },
    [state.activeCollectionId, reloadDocuments, toast, onUploaded],
  )

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragging(false)
    void handleFiles(e.dataTransfer.files)
  }

  return (
    <div className={cn('w-full', compact ? '' : 'max-w-2xl')}>
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          'relative rounded-2xl border-2 border-dashed transition-all duration-150',
          compact ? 'p-4' : 'p-10 text-center',
          dragging
            ? 'border-accent bg-accent-soft'
            : 'border-line bg-surface-1 hover:border-accent/50 hover:bg-surface-2/40',
        )}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          accept=".pdf,.docx,.txt,.csv,.xlsx,.pptx,.md,.markdown,.json,.png,.jpg,.jpeg,.webp,.gif,.tif,.tiff"
          onChange={(e) => {
            if (e.target.files) void handleFiles(e.target.files)
            e.target.value = ''
          }}
        />

        <div className={cn('flex gap-3.5', compact ? 'items-center' : 'flex-col items-center')}>
          <div
            className={cn(
              'grid shrink-0 place-items-center rounded-xl bg-accent-soft text-accent transition-transform',
              compact ? 'h-10 w-10' : 'h-14 w-14',
              dragging && 'scale-110',
            )}
          >
            <IconUpload className={compact ? 'text-lg' : 'text-2xl'} />
          </div>

          <div className={cn('min-w-0', compact ? 'text-left' : '')}>
            <p className={cn('font-medium', compact ? 'text-[13px]' : 'text-base')}>
              {dragging ? 'Drop to upload' : 'Drop your documents here'}
            </p>
            {!compact && (
              <p className="mt-1 text-sm text-ink-muted">
                or <span className="font-medium text-accent">browse files</span> from your computer
              </p>
            )}
            <p className="mt-1.5 text-[11px] text-ink-faint">Supported files: {SUPPORTED}</p>
          </div>

          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className={cn(compact ? 'btn-secondary ml-auto' : 'btn-primary mt-2')}
          >
            {uploading ? (
              <>
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current/30 border-t-current" />
                Uploading…
              </>
            ) : (
              'Browse Files'
            )}
          </button>
        </div>
      </div>

      {errors.length > 0 && (
        <div className="mt-2.5 space-y-1">
          {errors.map((e) => (
            <p key={e} className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-400">
              {e}
            </p>
          ))}
        </div>
      )}

      {/* In-flight processing cards */}
      {!compact && <ProcessingQueue />}
    </div>
  )
}

/** Live status cards for documents still being indexed. */
export function ProcessingQueue() {
  const { state } = useApp()
  const active = state.documents.filter((d) => isProcessing(d.status) || d.status === 'failed')

  if (!active.length) return null

  return (
    <div className="mt-4 space-y-2">
      {active.map((doc) => (
        <div key={doc.id} className="card p-3.5">
          <div className="flex items-center gap-3">
            <span className="text-lg">{fileEmoji(doc.filename)}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium">{doc.filename}</p>
              <div className="mt-1.5 flex items-center gap-2">
                <div className="h-1 flex-1 overflow-hidden rounded-full bg-surface-2">
                  <div
                    className={cn(
                      'h-full rounded-full transition-all duration-500',
                      doc.status === 'failed' ? 'bg-red-500' : 'bg-accent',
                    )}
                    style={{ width: `${doc.status === 'failed' ? 100 : Math.max(4, doc.progress * 100)}%` }}
                  />
                </div>
                <span
                  className={cn(
                    'shrink-0 text-[10px] font-medium',
                    STATUS_META[doc.status].tone,
                  )}
                >
                  {doc.status === 'failed'
                    ? 'Failed'
                    : `${STATUS_META[doc.status].label} · ${Math.round(doc.progress * 100)}%`}
                </span>
              </div>
              {doc.status === 'failed' && doc.error && (
                <p className="mt-1.5 line-clamp-2 text-[11px] text-red-600 dark:text-red-400">
                  {doc.error}
                </p>
              )}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function fileEmoji(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    pdf: '📕',
    docx: '📘',
    doc: '📘',
    xlsx: '📗',
    xls: '📗',
    csv: '📗',
    pptx: '📙',
    ppt: '📙',
    png: '🖼️',
    jpg: '🖼️',
    jpeg: '🖼️',
    webp: '🖼️',
    json: '🧾',
    md: '📄',
    markdown: '📄',
    txt: '📄',
  }
  return map[ext] ?? '📄'
}
