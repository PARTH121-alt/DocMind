/** Model catalogue: every generation backend, grouped by vendor, plus the
 *  active configuration and which provider credentials are present. */

import { useApp } from '../../lib/AppContext'
import { cn } from '../../lib/utils'
import type { ModelDescriptor, ProviderStatus } from '../../lib/types'
import { IconCpu, IconInfo, IconLayers, IconSparkle } from '../ui/Icons'

const TIER_LABELS: Record<string, string> = {
  fast: 'Fast',
  balanced: 'Balanced',
  high_quality: 'High Quality',
}

/** Closed-model vendors, each with the environment variable it needs. */
const PROVIDER_KEYS: {
  backend: keyof ProviderStatus
  label: string
  variable: string
  note: string
}[] = [
  {
    backend: 'openai',
    label: 'OpenAI · ChatGPT',
    variable: 'OPENAI_API_KEY',
    note: 'GPT-4o and GPT-4o mini. The same adapter serves any OpenAI-compatible endpoint.',
  },
  {
    backend: 'anthropic',
    label: 'Anthropic · Claude',
    variable: 'ANTHROPIC_API_KEY',
    note: 'Claude Sonnet and Haiku, via the Messages API.',
  },
  {
    backend: 'gemini',
    label: 'Google · Gemini',
    variable: 'GEMINI_API_KEY',
    note: 'Gemini Flash and Pro, via generateContent.',
  },
]

export function ModelsView() {
  const { state } = useApp()
  const models = state.models
  const health = state.health

  if (!models) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <p className="text-sm text-ink-faint">Loading model catalogue…</p>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-line bg-surface-1/60 px-4 py-3 backdrop-blur-xl sm:px-6">
        <h1 className="text-sm font-semibold tracking-tight">Models</h1>
        <p className="text-[11px] text-ink-faint">
          Every model is resolved from environment variables - nothing is hard-coded to one
          checkpoint.
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-4xl space-y-6">
          {/* Active configuration */}
          <section className="card p-4">
            <h2 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
              <IconInfo className="text-xs" /> Active configuration
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <ConfigItem label="Generation backend" value={models.active.generation_backend} />
              <ConfigItem label="Embedding backend" value={models.active.embedding_backend} />
              <ConfigItem label="Reranker backend" value={models.active.reranker_backend} />
              <ConfigItem label="Embedding model" value={models.active.embedding_model} mono />
              <ConfigItem label="Reranker" value={models.active.reranker_model} mono />
              <ConfigItem
                label="Hugging Face token"
                value={models.active.hf_token_configured ? 'Configured' : 'Not set'}
                tone={models.active.hf_token_configured ? 'good' : 'warn'}
              />
            </div>

            {/* Closed-model vendors each need their own credential; none of
                them are reachable through the Hugging Face hub. */}
            {models.providers && (
              <div className="mt-3 border-t border-line pt-3">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                  Closed-model providers
                </p>
                <div className="grid gap-2 sm:grid-cols-3">
                  {PROVIDER_KEYS.map(({ backend, label, variable, note }) => {
                    const ready = models.providers?.[backend] ?? false
                    return (
                      <div key={backend} className="card p-3">
                        <div className="flex items-center gap-1.5">
                          <span
                            className={cn(
                              'h-1.5 w-1.5 rounded-full',
                              ready ? 'bg-emerald-500' : 'bg-ink-faint/50',
                            )}
                          />
                          <p className="text-[12.5px] font-medium">{label}</p>
                        </div>
                        <p className="mt-1 text-[11px] leading-snug text-ink-faint">{note}</p>
                        <p
                          className={cn(
                            'mt-1.5 font-mono text-[10.5px]',
                            ready ? 'text-emerald-600 dark:text-emerald-400' : 'text-ink-faint',
                          )}
                        >
                          {variable} {ready ? '· set' : '· not set'}
                        </p>
                      </div>
                    )
                  })}
                </div>
                <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-faint">
                  ChatGPT, Claude and Gemini are not distributed on the Hugging Face hub, so they
                  need their own vendor keys. The app runs fully on-device without any of them.
                </p>
              </div>
            )}

            {!models.active.hf_token_configured && (
              <p className="mt-3 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[12.5px] text-amber-700 dark:text-amber-400">
                Without <code className="font-mono">HF_TOKEN</code> the app runs fully on-device:
                local ONNX generation, fastembed embeddings, and the cross-encoder reranker.
                Hosted models, OCR, and evaluation datasets become available once you add one.
              </p>
            )}
          </section>

          {/* Quality tiers */}
          <section>
            <h2 className="mb-2.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
              <IconSparkle className="text-xs" /> Quality presets
            </h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {Object.entries(models.tiers).map(([tier, m]) => (
                <TierCard key={tier} tier={tier} model={m} />
              ))}
            </div>
          </section>

          {/* Generation */}
          <ModelSection
            title="Text generation"
            description="Used to answer questions and produce summaries, comparisons and quizzes."
            models={models.generation}
          />
          <ModelSection
            title="Embeddings"
            description="Convert text into vectors for semantic retrieval."
            models={models.embeddings}
          />
          <ModelSection
            title="Reranking"
            description="Reorders retrieved passages by true question relevance."
            models={models.reranking}
          />
          <ModelSection
            title="Auxiliary"
            description="Specialised tasks: summarization, extractive QA and OCR for scans."
            models={models.auxiliary}
          />

          {/* Retrieval defaults */}
          <section className="card p-4">
            <h2 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
              <IconLayers className="text-xs" /> Retrieval defaults
            </h2>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              <ConfigItem label="Chunk size" value={String(models.retrieval_defaults.chunk_size)} />
              <ConfigItem label="Overlap" value={String(models.retrieval_defaults.chunk_overlap)} />
              <ConfigItem label="Top-K" value={String(models.retrieval_defaults.top_k)} />
              <ConfigItem label="Temperature" value={String(models.retrieval_defaults.temperature)} />
              <ConfigItem label="Top-P" value={String(models.retrieval_defaults.top_p)} />
              <ConfigItem label="Max tokens" value={String(models.retrieval_defaults.max_tokens)} />
              <ConfigItem label="Vector DB" value={health?.vector_db ?? '—'} />
              <ConfigItem
                label="Relevance threshold"
                value={String(models.retrieval_defaults.relevance_threshold)}
              />
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-ink-faint">
              When no passage scores above the relevance threshold the assistant refuses
              instead of answering, rather than guessing.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}

function ModelSection({
  title,
  description,
  models,
}: {
  title: string
  description: string
  models: ModelDescriptor[]
}) {
  return (
    <section>
      <h2 className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        <IconCpu className="text-xs" /> {title}
      </h2>
      <p className="mb-2.5 text-[12px] text-ink-faint">{description}</p>
      <div className="space-y-2">
        {models.map((m) => {
          // Prefer the backend's own verdict over a blanket HF-token check, so
          // a model needing only ANTHROPIC_API_KEY is not reported as blocked
          // because HF_TOKEN happens to be absent.
          const blocked = m.configured === false
          return (
            <div key={m.id} className={cn('card flex items-start gap-3 p-3.5', blocked && 'opacity-60')}>
              <span
                className={cn(
                  'mt-0.5 h-2 w-2 shrink-0 rounded-full',
                  blocked ? 'bg-ink-faint' : m.backend === 'local' ? 'bg-emerald-500' : 'bg-accent',
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="text-[13.5px] font-medium">{m.label}</p>
                  <span className="chip !px-1.5 !py-0 text-[9px]">{m.backend}</span>
                  {blocked && (
                    <span className="chip !px-1.5 !py-0 text-[9px]">
                      needs {m.unavailable_reason?.split(' ')[0] ?? 'key'}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 break-all font-mono text-[11px] text-ink-faint">{m.id}</p>
                <p className="mt-1 text-[12px] leading-snug text-ink-muted">{m.description}</p>
                <div className="mt-1.5 flex gap-3 text-[10px] text-ink-faint">
                  <span>{m.context_length.toLocaleString()} ctx</span>
                  {m.approx_size_mb && <span>~{m.approx_size_mb} MB</span>}
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function ConfigItem({
  label,
  value,
  mono,
  tone,
}: {
  label: string
  value: string
  mono?: boolean
  tone?: 'good' | 'warn'
}) {
  return (
    <div className="rounded-lg bg-surface-2 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-ink-faint">{label}</p>
      <p
        className={cn(
          'mt-0.5 truncate text-[13px] font-medium',
          mono && 'font-mono text-[11.5px]',
          tone === 'good' && 'text-emerald-600 dark:text-emerald-400',
          tone === 'warn' && 'text-amber-600 dark:text-amber-400',
        )}
        title={value}
      >
        {value}
      </p>
    </div>
  )
}

function TierCard({ tier, model }: { tier: string; model: ModelDescriptor }) {
  return (
    <div className="card p-3.5">
      <div className="mb-1.5 flex items-center gap-1.5">
        <span className="rounded-md bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
          {TIER_LABELS[tier] ?? tier}
        </span>
        <span className="h-1.5 w-1.5 rounded-full bg-ink-faint" />
      </div>
      <p className="text-[13px] font-medium">{model.label}</p>
      <p className="mt-1 break-all font-mono text-[10.5px] text-ink-faint">{model.id}</p>
    </div>
  )
}