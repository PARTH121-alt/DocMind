/**
 * Badge that states where an answer came from.
 *
 * This is the visible half of the grounding contract: a document answer, a web
 * answer, a server-clock fact and a general-knowledge answer must never look
 * alike, because only the first two carry verifiable sources.
 */

import type { AnswerMode } from '../../lib/types'
import { cn } from '../../lib/utils'

const META: Record<
  AnswerMode,
  { label: string; detail: string; className: string; icon: JSX.Element }
> = {
  document: {
    label: 'From your documents',
    detail: 'Grounded in passages retrieved from your uploaded files',
    className: 'border-emerald-500/35 text-emerald-600 dark:text-emerald-400',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
        <path d="M14 3v5h5" />
      </svg>
    ),
  },
  entity: {
    label: 'Structured data',
    detail: 'Facts from Wikidata, the structured database behind Wikipedia',
    className: 'border-teal-500/35 text-teal-600 dark:text-teal-400',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <ellipse cx="12" cy="6" rx="8" ry="3" />
        <path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" />
        <path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" />
      </svg>
    ),
  },
  web: {
    label: 'From the web',
    detail: 'Answered using pages fetched live from the internet',
    className: 'border-sky-500/35 text-sky-600 dark:text-sky-400',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18" />
      </svg>
    ),
  },
  live: {
    label: 'Live',
    detail: 'Computed on the server from the system clock',
    className: 'border-violet-500/35 text-violet-600 dark:text-violet-400',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
  general: {
    label: 'General knowledge',
    detail: 'Not from your documents or the web - the model’s own knowledge, so verify it',
    className: 'border-amber-500/35 text-amber-600 dark:text-amber-400',
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <path d="M12 3.5 13.6 8 18 9.6 13.6 11.2 12 15.7 10.4 11.2 6 9.6 10.4 8z" />
      </svg>
    ),
  },
}

export function ModeBadge({
  mode,
  grounded,
  compact = false,
}: {
  mode: AnswerMode
  grounded?: boolean
  compact?: boolean
}) {
  const meta = META[mode] ?? META.general
  return (
    <span
      title={meta.detail}
      className={cn(
        'inline-flex select-none items-center gap-1 rounded-full border bg-surface-1/70 px-2 py-[3px]',
        'text-[10.5px] font-medium leading-none',
        meta.className,
      )}
    >
      {meta.icon}
      {meta.label}
      {!compact && grounded && mode !== 'document' && (
        <span className="text-current/60">· verified</span>
      )}
    </span>
  )
}

export function modeDetail(mode: AnswerMode): string {
  return (META[mode] ?? META.general).detail
}