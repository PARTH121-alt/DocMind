/** Sign-in / registration screen. */

import { useState, type FormEvent } from 'react'
import { useApp } from '../../lib/AppContext'
import { IconAlert, IconSparkle } from '../ui/Icons'
import { cn } from '../../lib/utils'

export function AuthScreen() {
  const { login, register, state } = useApp()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [identifier, setIdentifier] = useState('')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const health = state.health

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (mode === 'login') {
        await login(identifier.trim(), password)
      } else {
        if (password.length < 8) {
          throw new Error('Password must be at least 8 characters.')
        }
        await register(email.trim(), username.trim(), password)
      }
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex h-full w-full items-center justify-center overflow-hidden bg-surface-0 px-5">
      {/* Subtle ambient wash - two soft radial tints, no heavy gradient. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-[0.55]"
        style={{
          background:
            'radial-gradient(60rem 40rem at 15% -10%, rgb(var(--accent) / 0.10), transparent 60%), radial-gradient(50rem 34rem at 95% 110%, rgb(var(--accent) / 0.07), transparent 60%)',
        }}
      />

      <div className="relative grid w-full max-w-5xl gap-12 lg:grid-cols-[1.05fr_minmax(0,26rem)] lg:gap-16">
        {/* Brand / value panel */}
        <div className="hidden flex-col justify-center lg:flex">
          <div className="mb-7 flex items-center gap-2.5">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-white shadow-card">
              <IconSparkle className="text-xl" />
            </div>
            <div>
              <p className="text-[15px] font-semibold tracking-tight">DocMind</p>
              <p className="text-xs text-ink-faint">Document Intelligence</p>
            </div>
          </div>

          <h1 className="text-balance text-[2.6rem] font-semibold leading-[1.1] tracking-tight">
            Chat with your documents.
          </h1>
          <p className="mt-4 max-w-lg text-[15px] leading-relaxed text-ink-muted">
            Upload files and ask questions. Answers are grounded in your own documents and
            every claim links back to the exact page it came from.
          </p>

          <ul className="mt-9 space-y-3.5">
            {[
              ['Grounded answers', 'Refuses questions your documents cannot support'],
              ['Source citations', 'Jump straight to the supporting passage and page'],
              ['Private by default', 'Your documents are never used by anyone else'],
            ].map(([title, desc]) => (
              <li key={title} className="flex gap-3">
                <span className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="text-sm text-ink-faint">{desc}</p>
                </div>
              </li>
            ))}
          </ul>

          {health && (
            <div className="mt-10 flex flex-wrap gap-2 text-[11px]">
              <span className="chip">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {health.vector_db.toUpperCase()} · {health.vector_count} vectors
              </span>
              <span className="chip">{health.embedding_model}</span>
              <span className="chip">
                {health.generation_backend === 'local' ? 'On-device model' : 'Hugging Face API'}
              </span>
            </div>
          )}
        </div>

        {/* Form panel */}
        <div className="card w-full p-7">
          <div className="mb-6 flex items-center gap-2.5 lg:hidden">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-white">
              <IconSparkle className="text-lg" />
            </div>
            <p className="font-semibold tracking-tight">DocMind</p>
          </div>

          <div className="mb-6 inline-flex rounded-xl bg-surface-2 p-1 text-sm">
            {(['login', 'register'] as const).map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m)
                  setError(null)
                }}
                className={cn(
                  'rounded-lg px-4 py-1.5 font-medium capitalize transition-colors',
                  mode === m ? 'bg-surface-1 text-ink shadow-card' : 'text-ink-muted hover:text-ink',
                )}
              >
                {m === 'login' ? 'Sign in' : 'Create account'}
              </button>
            ))}
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            {mode === 'login' ? (
              <Field label="Email or username" id="identifier">
                <input
                  id="identifier"
                  className="input"
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  autoComplete="username"
                  placeholder="you@example.com"
                  required
                />
              </Field>
            ) : (
              <>
                <Field label="Email" id="email">
                  <input
                    id="email"
                    type="email"
                    className="input"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                    placeholder="you@example.com"
                    required
                  />
                </Field>
                <Field label="Username" id="username">
                  <input
                    id="username"
                    className="input"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    autoComplete="username"
                    placeholder="your name"
                    minLength={2}
                    required
                  />
                </Field>
              </>
            )}

            <Field label="Password" id="password">
              <input
                id="password"
                type="password"
                className="input"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••'}
                required
              />
            </Field>

            {error && (
              <div className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2.5 text-sm text-red-600 dark:text-red-400">
                <IconAlert className="mt-0.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <button type="submit" disabled={busy} className="btn-primary w-full py-2.5">
              {busy ? (
                <>
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                  Please wait…
                </>
              ) : mode === 'login' ? (
                'Sign in'
              ) : (
                'Create account'
              )}
            </button>
          </form>

          <p className="mt-5 text-center text-xs leading-relaxed text-ink-faint">
            Documents are scoped to your account and are never used to train or answer for
            another user.
          </p>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  id,
  children,
}: {
  label: string
  id: string
  children: React.ReactNode
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-ink-muted">
        {label}
      </label>
      {children}
    </div>
  )
}
