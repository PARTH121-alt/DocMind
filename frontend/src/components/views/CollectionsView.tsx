/** Collections management view. */

import { useState } from 'react'
import { useApp } from '../../lib/AppContext'
import * as api from '../../lib/api'
import { cn } from '../../lib/utils'
import { useToast } from '../ui/Toasts'
import { IconCheck, IconFolder, IconPlus, IconTrash } from '../ui/Icons'

export function CollectionsView() {
  const { state, setActiveCollection, refreshAll } = useApp()
  const toast = useToast()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)

  async function create() {
    const trimmed = name.trim()
    if (!trimmed) return
    setBusy(true)
    try {
      await api.collections.create(trimmed)
      setName('')
      await refreshAll()
      toast.push('Collection created', 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    if (!confirm('Delete this collection? Its documents are kept and unassigned.')) return
    try {
      await api.collections.remove(id)
      await refreshAll()
      toast.push('Collection deleted', 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="shrink-0 border-b border-line bg-surface-1/60 px-4 py-3 backdrop-blur-xl sm:px-6">
        <h1 className="text-sm font-semibold tracking-tight">Collections</h1>
        <p className="text-[11px] text-ink-faint">
          Group documents into separate knowledge bases. Chats only retrieve from the active
          collection.
        </p>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-4">
          {/* Create */}
          <div className="card flex gap-2 p-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && create()}
              placeholder="New collection name, e.g. Research Papers"
              className="input flex-1"
              maxLength={200}
            />
            <button onClick={create} disabled={busy || !name.trim()} className="btn-primary">
              <IconPlus className="text-base" />
              Create
            </button>
          </div>

          {/* List */}
          <div className="space-y-2">
            {state.collections.map((c) => {
              const count = state.documents.filter((d) => d.collection_id === c.id).length
              const active = state.activeCollectionId === c.id
              return (
                <div
                  key={c.id}
                  className={cn(
                    'card flex items-center gap-3 p-3.5 transition-all',
                    active && 'ring-2 ring-accent/50',
                  )}
                >
                  <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent">
                    <IconFolder className="text-base" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-medium">{c.name}</p>
                    <p className="truncate text-[11px] text-ink-faint">
                      {count} document{count === 1 ? '' : 's'}
                      {c.is_default && ' · default'}
                      {c.description && ` · ${c.description}`}
                    </p>
                  </div>
                  <button
                    onClick={() => setActiveCollection(active ? null : c.id)}
                    className={cn('btn-ghost px-2.5 py-1 text-[11px]', active && 'text-accent')}
                  >
                    {active ? <IconCheck className="text-xs" /> : null}
                    {active ? 'Active' : 'Use'}
                  </button>
                  <button
                    onClick={() => remove(c.id)}
                    className="btn-ghost px-2 py-1 hover:text-red-500"
                    aria-label={`Delete ${c.name}`}
                  >
                    <IconTrash className="text-xs" />
                  </button>
                </div>
              )
            })}

            {!state.collections.length && (
              <p className="py-8 text-center text-sm text-ink-faint">
                No collections yet. Create one above.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}