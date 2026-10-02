/** Small formatting and helper utilities. */

import { clsx, type ClassValue } from 'clsx'
import type { DocumentStatus } from './types'

export function cn(...inputs: ClassValue[]): string {
  return clsx(inputs)
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** i
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function formatRelative(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const diff = Date.now() - then
  const mins = Math.round(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function fileExtension(filename: string): string {
  const idx = filename.lastIndexOf('.')
  return idx > 0 ? filename.slice(idx + 1).toLowerCase() : ''
}

export function fileIcon(filename: string): string {
  switch (fileExtension(filename)) {
    case 'pdf':
      return '📕'
    case 'docx':
    case 'doc':
      return '📘'
    case 'xlsx':
    case 'xls':
    case 'csv':
      return '📗'
    case 'pptx':
    case 'ppt':
      return '📙'
    case 'png':
    case 'jpg':
    case 'jpeg':
    case 'webp':
    case 'gif':
    case 'tif':
    case 'tiff':
      return '🖼️'
    case 'json':
      return '🧾'
    case 'md':
    case 'markdown':
    case 'txt':
      return '📄'
    default:
      return '📄'
  }
}

/** Human label + tone for each processing stage. */
export const STATUS_META: Record<DocumentStatus, { label: string; tone: string }> = {
  uploading: { label: 'Uploading', tone: 'text-ink-muted' },
  queued: { label: 'Queued', tone: 'text-ink-muted' },
  extracting: { label: 'Extracting', tone: 'text-amber-600 dark:text-amber-400' },
  chunking: { label: 'Chunking', tone: 'text-amber-600 dark:text-amber-400' },
  embedding: { label: 'Embedding', tone: 'text-accent' },
  indexing: { label: 'Indexing', tone: 'text-accent' },
  indexed: { label: 'Indexed', tone: 'text-emerald-600 dark:text-emerald-400' },
  failed: { label: 'Failed', tone: 'text-red-600 dark:text-red-400' },
}

export function isProcessing(status: DocumentStatus): boolean {
  return !['indexed', 'failed'].includes(status)
}

/** Debounce for search-as-you-type inputs. */
export function debounce<T extends (...args: never[]) => void>(fn: T, ms: number) {
  let timer: ReturnType<typeof setTimeout> | undefined
  return (...args: Parameters<T>) => {
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => fn(...args), ms)
  }
}

export function downloadText(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/** Confidence band used for the grounding indicator. */
export function confidenceTone(confidence: number | null): {
  label: string
  className: string
} {
  const c = confidence ?? 0
  if (c >= 0.6) return { label: 'Well grounded', className: 'text-emerald-600 dark:text-emerald-400' }
  if (c >= 0.42) return { label: 'Grounded', className: 'text-accent' }
  if (c > 0) return { label: 'Weak match', className: 'text-amber-600 dark:text-amber-400' }
  return { label: 'Not grounded', className: 'text-ink-faint' }
}
