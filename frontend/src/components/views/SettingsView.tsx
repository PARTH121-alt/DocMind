/** Settings view: appearance, retrieval, privacy and system status. */

import { useEffect, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import * as api from '../../lib/api'
import type { AppSettings } from '../../lib/types'
import { cn } from '../../lib/utils'
import { IconChart, IconCheck, IconCpu, IconInfo, IconSparkle } from '../ui/Icons'

const THEMES = [
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
  { id: 'system', label: 'System' },
] as const

export function SettingsView() {
  const { state, setTheme } = useApp()
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [datasets, setDatasets] = useState<{ available: boolean; datasets: { key: string; name: string; hf_id: string; task: string }[] } | null>(null)

  useEffect(() => {
    api.meta.settings().then(setSettings).catch(() => undefined)
    api.meta.evaluationDatasets().then(setDatasets).catch(() => undefined)
  }, [])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-line bg-surface-1/60 px-4 py-3 backdrop-blur-xl sm:px-6">
        <h1 className="text-sm font-semibold tracking-tight">Settings</h1>
        <p className="text-[11px] text-ink-faint">
          API keys are configured server-side and are never exposed to the browser.
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {/* Account */}
          <Section title="Account" icon={<IconInfo className="text-xs" />}>
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="Username" value={state.user?.username ?? '—'} />
              <Row label="Email" value={state.user?.email ?? '—'} />
              <Row
                label="Member since"
                value={state.user ? new Date(state.user.created_at).toLocaleDateString() : '—'}
              />
              <Row label="Signed in as" value="Owner" />
            </div>
          </Section>

          {/* Appearance */}
          <Section title="Appearance" icon={<IconSparkle className="text-xs" />}>
            <div className="flex items-center gap-2">
              {THEMES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTheme(t.id)}
                  className={cn(
                    'rounded-xl border px-4 py-2 text-sm font-medium transition-colors',
                    state.theme === t.id
                      ? 'border-accent bg-accent-soft text-accent'
                      : 'border-line text-ink-muted hover:bg-surface-2',
                  )}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </Section>

          {/* AI models */}
          <Section title="AI models" icon={<IconCpu className="text-xs" />}>
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="Generation" value={settings?.ai?.generation_backend as string ?? '—'} />
              <Row label="Embeddings" value={settings?.ai?.embedding_model as string ?? '—'} mono />
              <Row label="Reranker" value={settings?.ai?.reranker_model as string ?? '—'} mono />
              <Row
                label="Hugging Face token"
                value={settings?.ai?.hf_token_configured ? 'Configured' : 'Not set'}
                tone={settings?.ai?.hf_token_configured ? 'good' : 'warn'}
              />
            </div>
            <p className="mt-2.5 text-[11.5px] leading-relaxed text-ink-faint">
              Change models by editing <code className="font-mono">HF_MODEL</code>,{' '}
              <code className="font-mono">HF_EMBEDDING_MODEL</code> and related values in the
              backend <code className="font-mono">.env</code>, then restart the server.
            </p>
          </Section>

          {/* Document processing */}
          <Section title="Document processing" icon={<IconInfo className="text-xs" />}>
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="Chunk size" value={String(settings?.documents?.chunk_size ?? '—')} />
              <Row label="Chunk overlap" value={String(settings?.documents?.chunk_overlap ?? '—')} />
              <Row label="Max upload" value={`${settings?.documents?.max_upload_mb ?? '—'} MB`} />
              <Row
                label="OCR"
                value={settings?.documents?.ocr_enabled ? 'Enabled' : 'Disabled (needs token)'}
                tone={settings?.documents?.ocr_enabled ? 'good' : 'warn'}
              />
            </div>
          </Section>

          {/* Retrieval */}
          <Section title="Retrieval" icon={<IconChart className="text-xs" />}>
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="Vector database" value={settings?.retrieval?.vector_db as string ?? '—'} />
              <Row label="Top-K chunks" value={String(settings?.retrieval?.top_k ?? '—')} />
              <Row label="Rerank to N" value={String(settings?.retrieval?.rerank_top_n ?? '—')} />
              <Row
                label="Relevance threshold"
                value={String(settings?.retrieval?.relevance_threshold ?? '—')}
              />
            </div>
          </Section>

          {/* Privacy & security */}
          <Section title="Privacy & security" icon={<IconInfo className="text-xs" />}>
            <div className="space-y-2">
              <Checklist label="Documents are isolated per account and never shared between users" />
              <Checklist label="Uploaded files are treated as untrusted input, not instructions" />
              <Checklist label="Prompt-injection patterns in documents are detected and neutralised" />
              <Checklist
                label={`Rate limiting active: ${settings?.privacy?.rate_limit_per_minute ?? '—'} requests/minute`}
              />
              <Checklist label="File type and size validated on upload" />
            </div>
          </Section>

          {/* System */}
          <Section title="System status" icon={<IconChart className="text-xs" />}>
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="API version" value={state.health?.version ?? '—'} />
              <Row label="Database" value={state.health?.database ?? '—'} tone="good" />
              <Row label="Vectors indexed" value={String(state.health?.vector_count ?? '—')} />
              <Row label="Documents stored" value={String(state.health?.documents ?? '—')} />
            </div>
          </Section>

          {/* Evaluation datasets */}
          {datasets && (
            <Section title="Evaluation datasets" icon={<IconChart className="text-xs" />}>
              <p className="mb-2.5 text-[12px] leading-relaxed text-ink-muted">
                Public Hugging Face datasets used only for benchmarking retrieval and
                groundedness. They are separate from your uploaded documents, which remain the
                sole knowledge source for answers.
              </p>
              {!datasets.available ? (
                <p className="rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] text-amber-700 dark:text-amber-400">
                  Install the evaluation extras with{' '}
                  <code className="font-mono">pip install datasets</code> to enable benchmarks.
                </p>
              ) : (
                <div className="space-y-1.5">
                  {datasets.datasets.map((d) => (
                    <div
                      key={d.key}
                      className="flex items-center gap-2 rounded-lg bg-surface-2 px-3 py-2 text-[12px]"
                    >
                      <span className="font-medium">{d.name}</span>
                      <span className="chip !px-1.5 !py-0 text-[9px]">{d.task}</span>
                      <span className="ml-auto truncate font-mono text-[10.5px] text-ink-faint">
                        {d.hf_id}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Section>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({
  title,
  icon,
  children,
}: {
  title: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <section className="card p-4">
      <h2 className="mb-3 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
        {icon}
        {title}
      </h2>
      {children}
    </section>
  )
}

function Row({
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

function Checklist({ label }: { label: string }) {
  return (
    <p className="flex items-start gap-2 text-[12.5px] text-ink-muted">
      <IconCheck className="mt-0.5 shrink-0 text-emerald-500" />
      {label}
    </p>
  )
}