/** Chat header: title, active collection, model + status indicator. */

import { useApp } from '../../lib/AppContext'
import { cn } from '../../lib/utils'
import { IconChevronDown, IconLayers, IconPlus, IconCpu } from '../ui/Icons'
import { useState } from 'react'
import { conversations } from '../../lib/api'
import type { ModelDescriptor } from '../../lib/types'
import { useToast } from '../ui/Toasts'

export function ChatHeader() {
  const { state, derived, newChat } = useApp()
  const toast = useToast()
  const [openPicker, setOpenPicker] = useState(false)

  const conversation = state.conversations.find((c) => c.id === state.activeConversationId)
  const title = conversation?.title ?? (state.messages.length ? 'New Chat' : 'DocMind')

  const generation = state.models?.generation ?? []
  const activeModel = generation[0]
  const backendLabel =
    state.health?.generation_backend === 'local' ? 'On-device' : 'Hugging Face API'
  const ready = Boolean(state.health && state.health.status !== 'degraded')

  async function pickModel(m: ModelDescriptor) {
    setOpenPicker(false)
    if (m.backend === 'hf_api' && !state.health?.hf_token_configured) {
      toast.push('Set HF_TOKEN in the backend .env to use hosted models.', 'error')
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
            <div className="absolute right-0 z-20 mt-2 w-80 overflow-hidden rounded-xl border border-line bg-surface-1 shadow-pop">
              <p className="border-b border-line px-3 py-2 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
                Generation model
              </p>
              <div className="max-h-80 overflow-y-auto">
                {generation.map((m) => (
                  <button
                    key={m.id}
                    onClick={() => pickModel(m)}
                    className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-surface-2"
                  >
                    <span
                      className={cn(
                        'mt-1 h-1.5 w-1.5 shrink-0 rounded-full',
                        m.backend === 'local' ? 'bg-emerald-500' : 'bg-accent',
                      )}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5 text-[13px] font-medium">
                        {m.label}
                        {m.requires_token && !state.health?.hf_token_configured && (
                          <span className="chip !px-1.5 !py-0 text-[9px]">token</span>
                        )}
                      </span>
                      <span className="mt-0.5 block text-[11px] leading-snug text-ink-faint">
                        {m.description}
                      </span>
                    </span>
                  </button>
                ))}
              </div>
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