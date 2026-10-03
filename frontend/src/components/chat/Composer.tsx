/** Message composer with auto-growing textarea and keyboard shortcuts. */

import { useEffect, useRef, useState } from 'react'
import { cn } from '../../lib/utils'
import { IconSend, IconStop } from '../ui/Icons'

interface Props {
  onSend: (text: string) => void
  onStop: () => void
  streaming: boolean
  disabled?: boolean
  disabledReason?: string
  suggestions?: string[]
}

export function Composer({ onSend, onStop, streaming, disabled, disabledReason, suggestions = [] }: Props) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-grow up to a sane maximum, then scroll.
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  function submit() {
    const text = value.trim()
    if (!text || streaming || disabled) return
    onSend(text)
    setValue('')
  }

  return (
    <div className="shrink-0 border-t border-line bg-surface-0/85 px-4 py-3.5 backdrop-blur-xl sm:px-6">
      <div className="mx-auto w-full max-w-3xl">
        {suggestions.length > 0 && (
          <div className="mb-2.5 flex flex-wrap gap-1.5">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onSend(s)}
                className="chip transition-colors hover:border-accent/45 hover:text-ink"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        <div
          className={cn(
            'flex items-end gap-2 rounded-2xl border border-line bg-surface-1 p-2 shadow-card',
            'transition-colors focus-within:border-accent/50',
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter inserts a newline.
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                submit()
              }
            }}
            rows={1}
            disabled={disabled}
            placeholder={
              disabled
                ? (disabledReason ?? 'Upload a document to start asking questions')
                : 'Ask about your documents, paste a URL, or just say hi…'
            }
            className={cn(
              'max-h-[200px] min-h-[2.5rem] flex-1 resize-none bg-transparent px-2 py-2',
              'text-[14.5px] leading-relaxed text-ink placeholder:text-ink-faint',
              'focus:outline-none disabled:cursor-not-allowed',
            )}
          />

          {streaming ? (
            <button
              onClick={onStop}
              className="btn-secondary shrink-0 px-3 py-2"
              title="Stop generating"
              aria-label="Stop generating"
            >
              <IconStop className="text-sm" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!value.trim() || disabled}
              className="btn-primary shrink-0 px-3 py-2"
              title="Send message"
              aria-label="Send message"
            >
              <IconSend className="text-sm" />
            </button>
          )}
        </div>

        <p className="mt-2 text-center text-[11px] text-ink-faint">
          Paste a URL to analyse it · ask about your documents or the live web
          <span className="mx-1.5 hidden sm:inline">
            <kbd className="kbd">Enter</kbd> to send · <kbd className="kbd">Shift</kbd>+
            <kbd className="kbd">Enter</kbd> for a new line
          </span>
        </p>
      </div>
    </div>
  )
}