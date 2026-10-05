/**
 * Badge showing how the user's own message read emotionally.
 *
 * Deliberately understated and shown only when the reading was confident: a
 * badge that appears on every message turns "I noticed how you feel" into
 * noise, and over-confident empathy reads worse than none at all. It reports
 * what the analyser measured, including that it is a measurement.
 */

import type { ToneReading } from '../../lib/types'
import { cn } from '../../lib/utils'

const TONE_STYLE: Record<string, string> = {
  joy: 'border-amber-500/35 text-amber-600 dark:text-amber-400',
  trust: 'border-teal-500/35 text-teal-600 dark:text-teal-400',
  anger: 'border-red-500/35 text-red-600 dark:text-red-400',
  sadness: 'border-blue-500/35 text-blue-600 dark:text-blue-400',
  fear: 'border-violet-500/35 text-violet-600 dark:text-violet-400',
  disgust: 'border-lime-600/35 text-lime-700 dark:text-lime-400',
  surprise: 'border-cyan-500/35 text-cyan-600 dark:text-cyan-400',
  anticipation: 'border-pink-500/35 text-pink-600 dark:text-pink-400',
}

export function ToneBadge({ tone }: { tone: ToneReading }) {
  const style = TONE_STYLE[tone.emotion] ?? TONE_STYLE.trust
  const pct = Math.round(tone.confidence * 100)
  return (
    <span
      title={`Your message reads as ${tone.label.toLowerCase()} (${pct}% confidence). Read from word choice by a lexicon, so sarcasm and context are not detected.`}
      className={cn(
        'inline-flex select-none items-center gap-1 rounded-full border bg-surface-1/70 px-2 py-[3px]',
        'text-[10.5px] font-medium leading-none',
        style,
      )}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" width="11" height="11">
        <circle cx="12" cy="12" r="9" />
        <path d="M8.5 14.5s1.3 1.5 3.5 1.5 3.5-1.5 3.5-1.5" />
        <circle cx="9" cy="10" r="0.9" fill="currentColor" stroke="none" />
        <circle cx="15" cy="10" r="0.9" fill="currentColor" stroke="none" />
      </svg>
      reads as {tone.label.toLowerCase()}
    </span>
  )
}