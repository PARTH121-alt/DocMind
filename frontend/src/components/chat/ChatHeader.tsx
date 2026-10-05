/** Chat header: title, active collection, model + status indicator. */

import { useApp } from '../../lib/AppContext'
import { cn } from '../../lib/utils'
import { IconChevronDown, IconLayers, IconPlus, IconCpu } from '../ui/Icons'
import { useState } from 'react'
import { conversations } from '../../lib/api'
import type { ModelDescriptor } from '../../lib/types'
import { useToast } from '../ui/Toasts'

/** Vendor grouping for the model picker.
 *
 * Order is deliberate: what works right now first, then the popular closed
 * vendors, and the long open-weight list last so it cannot bury them. */
const PROVIDER_GROUPS = [
  { title: 'On this machine', backends: ['local'], dot: 'bg-emerald-500', collapse: 0 },
  { title: 'OpenAI · ChatGPT', backends: ['openai'], dot: 'bg-emerald-400', collapse: 0 },
  { title: 'Anthropic · Claude', backends: ['anthropic'], dot: 'bg-orange-400', collapse: 0 },
  { title: 'Google · Gemini', backends: ['gemini'], dot: 'bg-blue-400', collapse: 0 },
  { title: 'Open weights · Hugging Face', backends: ['hf_api'], dot: 'bg-accent', collapse: 4 },
] as const

const CONTEXT_ENV: Record<string, string> = {
  local: 'Local',
  hf_api: 'HF',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  gemini: 'Gemini',
}

function formatContext(n: number): string {
  if (!n) return 'unknown'
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(n % 1_000_000 ? 1 : 0)}M` : `${Math.round(n / 1000)}K`
}

export function ChatHeader() {
  const { state, derived, newChat } = useApp()
  const toast = useToast()
  const [openPicker, setOpenPicker] = useState(false)
  // Which collapsible vendor groups the user chose to expand.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const conversation = state.conversations.find((c) => c.id === state.activeConversationId)
  const title = conversation?.title ?? (state.messages.length ? 'New Chat' : 'DocMind')

  const generation = state.models?.generation ?? []
  // Configured models sort ahead of unconfigured ones within a group, so the
  // things you can actually use never sit below a wall of greyed-out entries.
  const ordered = [...generation].sort(
    (a, b) => Number(a.configured === false) - Number(b.configured === false),
  )
  const groups = PROVIDER_GROUPS.map((group) => {
    const all = ordered.filter((m) => (group.backends as readonly string[]).includes(m.backend))
    return {
      ...group,
      all,
      shown: group.collapse ? all.slice(0, group.collapse) : all,
      hidden: all.length - (group.collapse ? Math.min(group.collapse, all.length) : all.length),
      ready: all.length > 0 && all.every((m) => m.configured !== false),
    }
  }).filter((group) => group.all.length > 0)

  const selectedId = conversation?.model
  const activeModel =
    generation.find((m) => m.id === selectedId) ??
    generation.find((m) => m.configured !== false) ??
    generation[0]
  const backendLabel = activeModel
    ? CONTEXT_ENV[activeModel.backend] ?? activeModel.backend
    : 'Model'
  const ready = Boolean(state.health && state.health.status !== 'degraded')

  async function pickModel(m: ModelDescriptor) {
    setOpenPicker(false)
    if (m.configured === false) {
      toast.push(
        m.unavailable_reason
          ? `${m.label} is unavailable: ${m.unavailable_reason}.`
          : `${m.label} is not configured.`,
        'error',
      )
      return
    }
    try {
      // Persist the choice on the conversation so follow-up turns reuse it.
      if (state.activeConversationId) {
        await conversations.update(state.activeConversationId, { model: m.id })
      }
      toast.push(`Model set to ${m.label}`, 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface-1/60 px-4 backdrop-blur-xl sm:px-6">
      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-semibold tracking-tight">{title}</h1>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-faint">
          <span className="flex items-center gap-1">
            <IconLayers className="text-[11px]" />
            {derived.activeCollection?.name ?? 'All documents'}
          </span>
          <span className="h-2.5 w-px bg-line" />
          <span className="flex items-center gap-1">
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                ready ? 'bg-emerald-500' : 'bg-amber-500',
              )}
              title={ready ? 'Backend ready' : 'Backend degraded'}
            />
            {activeModel?.label.split('(')[0].trim() ?? 'Model'}
            <span className="text-ink-faint/70">· {backendLabel}</span>
          </span>
        </div>
      </div>

      {/* Model picker */}
      <div className="relative">
        <button
          onClick={() => setOpenPicker((v) => !v)}
          className="chip hover:border-accent/40 hover:text-ink"
          title="Change model"
        >
          <IconCpu className="text-[11px]" />
          <span className="hidden sm:inline">Model</span>
          <IconChevronDown className={cn('text-[10px] transition-transform', openPicker && 'rotate-180')} />
        </button>

        {openPicker && (
          <>
            <button
              className="fixed inset-0 z-10 cursor-default"
              onClick={() => setOpenPicker(false)}
              aria-label="Close model picker"
            />
            <div className="absolute right-0 z-20 mt-2 w-96 overflow-hidden rounded-xl border border-line bg-surface-1 shadow-pop">
              <p className="border-b border-line px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                Generation model
              </p>
              <div className="max-h-[26rem] overflow-y-auto">
                {groups.map((group) => (
                  <section key={group.title}>
                    <p className="sticky top-0 flex items-center gap-1.5 bg-surface-2/95 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink-faint backdrop-blur">
                      <span className={cn('h-1.5 w-1.5 rounded-full', group.dot)} />
                      {group.title}
                      {!group.ready && (
                        <span className="ml-auto font-normal normal-case tracking-normal text-ink-faint/70">
                          not configured
                        </span>
                      )}
                    </p>
                    {(expanded[group.title] ? group.all : group.shown).map((m) => {
                      const ready = m.configured !== false
                      return (
                        <button
                          key={m.id}
                          onClick={() => ready && pickModel(m)}
                          disabled={!ready}
                          title={ready ? m.description : m.unavailable_reason || 'No API key set'}
                          className={cn(
                            'flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors',
                            ready ? 'hover:bg-surface-2' : 'cursor-not-allowed opacity-45',
                          )}
                        >
                          <span
                            className={cn(
                              'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                              ready ? 'bg-accent' : 'bg-ink-faint/40',
                            )}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-1.5 text-[13px] font-medium">
                              {m.label}
                              {!ready && (
                                <span className="chip !px-1.5 !py-0 text-[9px]">
                                  {m.unavailable_reason?.split(' ')[0] ?? 'key'}
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block text-[11px] leading-snug text-ink-faint">
                              {ready ? m.description : m.unavailable_reason}
                            </span>
                            <span className="mt-1 block text-[10px] text-ink-faint/70">
                              {formatContext(m.context_length)} context
                            </span>
                          </span>
                        </button>
                      )
                    })}
                    {group.hidden > 0 && (
                      <button
                        onClick={() =>
                          setExpanded((prev) => ({ ...prev, [group.title]: !prev[group.title] }))
                        }
                        className="w-full px-3 py-1.5 text-left text-[11px] font-medium text-accent transition-colors hover:bg-surface-2"
                      >
                        {expanded[group.title]
                          ? 'Show fewer'
                          : `Show ${group.hidden} more open-weight model${group.hidden === 1 ? '' : 's'}`}
                      </button>
                    )}
                  </section>
                ))}
              </div>
              <p className="border-t border-line bg-surface-2/60 px-3 py-2 text-[10px] leading-relaxed text-ink-faint">
                Closed models run on their vendor's servers, so your documents are sent to
                them for that request. Use a local or open-weight model to keep everything on
                this machine.
              </p>
            </div>
          </>
        )}
      </div>

      <button onClick={newChat} className="btn-secondary px-2.5 py-1.5" title="New chat">
        <IconPlus className="text-base" />
        <span className="hidden md:inline text-sm">New</span>
      </button>
    </header>
  )
}