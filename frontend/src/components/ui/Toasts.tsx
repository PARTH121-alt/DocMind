/** Lightweight toast notifications. */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { cn } from '../../lib/utils'

type ToastKind = 'info' | 'success' | 'error'

interface Toast {
  id: number
  kind: ToastKind
  message: string
}

const ToastContext = createContext<{ push: (message: string, kind?: ToastKind) => void } | null>(null)

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const push = useCallback((message: string, kind: ToastKind = 'info') => {
    const id = nextId++
    setToasts((prev) => [...prev, { id, kind, message }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 5200)
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <Toaster toasts={toasts} />
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>')
  return ctx
}

function Toaster({ toasts }: { toasts: Toast[] }) {
  if (!toasts.length) return null
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-5 right-5 z-50 flex w-[min(24rem,calc(100vw-2.5rem))] flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={cn(
            'glass pointer-events-auto animate-fade-in rounded-xl px-4 py-3 text-sm shadow-pop',
            t.kind === 'error' && 'border-red-500/40 text-red-600 dark:text-red-400',
            t.kind === 'success' && 'border-emerald-500/40 text-emerald-600 dark:text-emerald-400',
            t.kind === 'info' && 'text-ink',
          )}
        >
          {t.message}
        </div>
      ))}
    </div>
  )
}
