/**
 * Emotion analysis panel.
 *
 * Shows the measurement, not just the verdict: the per-emotion bars, the
 * intensity scale, and the passages that drove the score. A single label
 * ("Joy") would be indistinguishable from a guess, so the panel exposes the
 * distribution and the evidence behind it, and names its own blind spots.
 */

import { useState } from 'react'

import type { EmotionDocument, EmotionOverall, EmotionPassage } from '../../lib/types'
import { cn } from '../../lib/utils'

const EMOTION_COLOR: Record<string, string> = {
  joy: '#f59e0b',
  anger: '#ef4444',
  sadness: '#3b82f6',
  fear: '#8b5cf6',
  disgust: '#84cc16',
  surprise: '#06b6d4',
  trust: '#14b8a6',
  anticipation: '#ec4899',
  neutral: '#94a3b8',
}

const EMOTION_ORDER = [
  'joy',
  'trust',
  'anticipation',
  'surprise',
  'sadness',
  'fear',
  'anger',
  'disgust',
  'neutral',
]

const POLARITY_STYLE: Record<string, string> = {
  positive: 'text-emerald-600 dark:text-emerald-400',
  'mildly positive': 'text-emerald-600/80 dark:text-emerald-400/80',
  negative: 'text-red-600 dark:text-red-400',
  'mildly negative': 'text-red-600/80 dark:text-red-400/80',
  neutral: 'text-ink-faint',
}

function EmotionBars({
  scores,
  only,
}: {
  scores: Record<string, number>
  only?: string[]
}) {
  const keys = EMOTION_ORDER.filter((k) => (only ?? EMOTION_ORDER).includes(k))
  const present = keys.filter((k) => (scores[k] ?? 0) > 0)
  if (present.length === 0) {
    return (
      <p className="text-[12px] text-ink-faint">
        No emotional words detected - the text reads as matter-of-fact.
      </p>
    )
  }
  return (
    <div className="space-y-1.5">
      {present.map((key) => (
        <div key={key} className="flex items-center gap-2">
          <span className="w-24 shrink-0 text-[11px] capitalize text-ink-muted">{key}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-2">
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.max(2, (scores[key] ?? 0) * 100)}%`,
                backgroundColor: EMOTION_COLOR[key],
              }}
            />
          </div>
          <span className="w-9 shrink-0 text-right text-[10.5px] tabular-nums text-ink-faint">
            {Math.round((scores[key] ?? 0) * 100)}%
          </span>
        </div>
      ))}
    </div>
  )
}

function IntensityMeter({ valence, arousal }: { valence: number; arousal: number }) {
  // Valence runs -1..1; map to a 0..100 position on a diverging bar.
  const position = Math.round(((valence + 1) / 2) * 100)
  return (
    <div className="space-y-1.5">
      <div>
        <div className="mb-1 flex items-center justify-between text-[10.5px] text-ink-faint">
          <span>negative</span>
          <span className="tabular-nums">
            valence {valence >= 0 ? '+' : ''}
            {valence.toFixed(2)}
          </span>
          <span>positive</span>
        </div>
        <div className="relative h-2 rounded-full bg-gradient-to-r from-red-500/45 via-surface-2 to-emerald-500/45">
          <div
            className="absolute top-1/2 h-3.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface-1 bg-ink shadow"
            style={{ left: `${position}%` }}
            title={`valence ${valence.toFixed(2)}`}
          />
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-24 shrink-0 text-[11px] text-ink-muted">Arousal</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full bg-violet-500"
            style={{ width: `${Math.max(2, arousal * 100)}%` }}
          />
        </div>
        <span className="w-9 shrink-0 text-right text-[10.5px] tabular-nums text-ink-faint">
          {Math.round(arousal * 100)}%
        </span>
      </div>
      <p className="text-[10.5px] leading-relaxed text-ink-faint">
        Arousal is how activated the language is, independent of whether it is
        positive or negative.
      </p>
    </div>
  )
}

function PassageRow({ passage }: { passage: EmotionPassage }) {
  const [open, setOpen] = useState(false)
  const color = EMOTION_COLOR[passage.emotion] ?? EMOTION_COLOR.neutral
  return (
    <li className="rounded-xl border border-line bg-surface-1 p-3">
      <div className="flex items-start gap-2.5">
        <span
          className="mt-1 h-2 w-2 shrink-0 rounded-full"
          style={{ backgroundColor: color }}
          title={passage.emotion}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium capitalize" style={{ color }}>
              {passage.emotion}
            </span>
            <span className="text-[10.5px] text-ink-faint">
              {Math.round(passage.charge * 100)}% intensity
            </span>
            <span className="text-[10.5px] text-ink-faint">
              {passage.filename}
              {passage.page_number ? ` p${passage.page_number}` : ''}
            </span>
          </div>
          <p
            className={cn(
              'mt-1 text-[12.5px] leading-relaxed text-ink',
              open ? '' : 'line-clamp-2',
            )}
          >
            “{passage.text}”
          </p>
          {passage.text.length > 120 && (
            <button
              onClick={() => setOpen((v) => !v)}
              className="mt-1 text-[10.5px] font-medium text-accent hover:underline"
            >
              {open ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

export function EmotionPanel({
  overall,
  documents,
  passages,
  summary,
  latencyMs,
}: {
  overall: EmotionOverall | null
  documents: EmotionDocument[]
  passages: EmotionPassage[]
  summary: string
  latencyMs: number
}) {
  const [scope, setScope] = useState<'overall' | string>('overall')
  const perDoc = documents.find((d) => d.document_id === scope)
  const showing = scope === 'overall' ? overall : perDoc

  if (!showing) {
    return <p className="text-[12.5px] text-ink-faint">Nothing to analyse yet.</p>
  }

  const scores = showing.scores ?? {}
  const polarityClass = POLARITY_STYLE[showing.polarity] ?? 'text-ink-faint'
  const rows = scope === 'overall' ? passages : perDoc?.charged_passages ?? []

  return (
    <div className="space-y-5" data-testid="emotion-panel">
      {/* Verdict */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-ink-faint">
            {scope === 'overall' ? 'Overall' : showing === perDoc ? perDoc?.filename : ''}
          </p>
          <p className="text-2xl font-semibold tracking-tight">{showing.emotion_label}</p>
        </div>
        <span className={cn('text-[12.5px] font-medium capitalize', polarityClass)}>
          {showing.polarity}
        </span>
        {scope === 'overall' && overall && (
          <span className="chip !px-2 !py-0.5 text-[10px]">
            {overall.signal} signal · {overall.emotional_hits} emotional terms
          </span>
        )}
        {documents.length > 1 && (
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="ml-auto rounded-lg border border-line bg-surface-1 px-2 py-1 text-[12px]"
          >
            <option value="overall">All documents</option>
            {documents.map((d) => (
              <option key={d.document_id} value={d.document_id}>
                {d.filename}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Distribution */}
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          Emotion distribution
        </p>
        <EmotionBars scores={scores} />
      </div>

      {/* Intensity */}
      <IntensityMeter valence={showing.valence} arousal={showing.arousal} />

      {/* Evidence */}
      <div>
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
          Most emotionally charged passages
        </p>
        {rows.length === 0 ? (
          <p className="text-[12px] text-ink-faint">
            No strongly charged sentences found in this text.
          </p>
        ) : (
          <ul className="space-y-2">
            {rows.map((p, i) => (
              <PassageRow key={`${p.document_id}-${i}`} passage={p} />
            ))}
          </ul>
        )}
      </div>

      {/* Honest summary + limits */}
      <div className="rounded-xl border border-line bg-surface-2/60 p-3.5">
        <pre className="whitespace-pre-wrap font-sans text-[12.5px] leading-relaxed text-ink-muted">
          {summary}
        </pre>
      </div>

      <p className="text-[10.5px] text-ink-faint">
        Scored by a deterministic lexicon in {latencyMs} ms - not generated, so it is
        reproducible. It reads word choice only: sarcasm, tone of voice and who is
        speaking are not detected.
      </p>
    </div>
  )
}