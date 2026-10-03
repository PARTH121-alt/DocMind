/**
 * Add websites to the knowledge base.
 *
 * Fetched pages become documents, so they can be cited and previewed exactly
 * like an uploaded file. Shows which search backend is active.
 */

import { useEffect, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import * as api from '../../lib/api'
import { cn } from '../../lib/utils'
import { useToast } from '../ui/Toasts'
import { IconAlert, IconExternal, IconSpinner } from '../ui/Icons'

const URL_RE = /^https?:\/\/[^\s]+$/i

export function WebPanel({ onDone }: { onDone?: () => void }) {
  const { state, reloadDocuments } = useApp()
  const toast = useToast()
  const [urls, setUrls] = useState<string[]>([''])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<api.WebResponse | null>(null)
  const [active, setActive] = useState<string>('')

  useEffect(() => {
    api.web
      .providers()
      .then((r) => setActive(r.active))
      .catch(() => undefined)
  }, [])

  const valid = urls.filter((u) => u.trim() && URL_RE.test(u.trim()))
  const invalid = urls.filter((u) => u.trim() && !URL_RE.test(u.trim()))

  function addRow() {
    setUrls((u) => [...u, ''])
  }
  function update(i: number, value: string) {
    setUrls((u) => u.map((x, idx) => (idx === i ? value : x)))
  }
  function remove(i: number) {
    setUrls((u) => (u.length === 1 ? [''] : u.filter((_, idx) => idx !== i)))
  }

  async function submit() {
    if (!valid.length || busy) return
    setBusy(true)
    setResult(null)
    try {
      const res = await api.web.fetchPages(valid, state.activeCollectionId)
      setResult(res)
      await reloadDocuments()
      if (res.ingested.length) {
        toast.push(`Indexed ${res.ingested.length} page(s)`, 'success')
      }
      if (res.errors.length) {
        toast.push(`${res.errors.length} page(s) could not be read`, 'error')
      }
      if (res.ingested.length) onDone?.()
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="animate-fade-in px-0.5 pb-1">
      <div className="rounded-xl border border-line bg-surface-1 p-2.5">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            Add websites
          </span>
          {active && (
            <span className="chip !px-1.5 !py-0 text-[9px]">search: {active}</span>
          )}
        </div>

        {urls.map((url, i) => (
          <div key={i} className="mb-1 flex items-center gap-1">
            <input
              value={url}
              onChange={(e) => update(i, e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && valid.length && submit()}
              placeholder="https://example.com/article"
              className={cn(
                'input flex-1 py-1.5 text-[12px]',
                url.trim() && !URL_RE.test(url.trim()) && 'border-red-500/60',
              )}
              aria-label={`URL ${i + 1}`}
            />
            {urls.length > 1 && (
              <button
                onClick={() => remove(i)}
                className="btn-ghost px-1.5 py-1 text-[11px]"
                aria-label="Remove URL"
              >
                ×
              </button>
            )}
          </div>
        ))}

        {invalid.length > 0 && (
          <p className="mb-1 flex items-center gap-1 text-[10.5px] text-red-600 dark:text-red-400">
            <IconAlert className="shrink-0" /> Only full http(s) URLs are supported.
          </p>
        )}

        <div className="flex items-center gap-1.5">
          <button onClick={addRow} className="btn-ghost px-2 py-1 text-[11px]">
            + Another
          </button>
          <button
            onClick={submit}
            disabled={!valid.length || busy}
            className="btn-primary ml-auto px-2.5 py-1 text-[11px]"
          >
            {busy ? <IconSpinner className="text-[11px]" /> : null}
            {busy ? 'Fetching…' : 'Fetch & index'}
          </button>
        </div>

        {result && (
          <div className="mt-2 space-y-1.5">
            {result.results.map((r) => (
              <a
                key={r.url}
                href={r.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-1.5 rounded-lg bg-surface-2/60 px-2 py-1.5 text-[11px] hover:bg-surface-2"
              >
                <IconExternal className="mt-0.5 shrink-0 text-[10px] text-ink-faint" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{r.title || r.domain}</span>
                  <span className="block truncate text-ink-faint">{r.snippet}</span>
                </span>
              </a>
            ))}
            {result.errors.map((e) => (
              <p
                key={e}
                className="rounded-lg bg-red-500/10 px-2 py-1.5 text-[10.5px] text-red-600 dark:text-red-400"
              >
                {e}
              </p>
            ))}
          </div>
        )}

        <p className="mt-2 text-[10px] leading-relaxed text-ink-faint">
          Fetched pages are indexed like uploads. Ask anything and answers can cite them.
        </p>
      </div>
    </div>
  )
}