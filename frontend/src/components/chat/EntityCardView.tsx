/**
 * Structured entity card.
 *
 * Renders Wikidata facts as a definition-style card rather than prose, so
 * "what is the capital of France" produces a scannable fact block instead of a
 * sentence the reader has to parse. Degrades to the Markdown table when no
 * structured payload is present.
 */

import type { EntityCard } from '../../lib/types'
import { IconExternal } from '../ui/Icons'

export function EntityCardView({ entity }: { entity: EntityCard }) {
  const facts = entity.facts ?? []

  return (
    <div
      data-testid="entity-card"
      className="my-3 overflow-hidden rounded-2xl border border-teal-500/30 bg-surface-1 shadow-card"
    >
      {/* Header */}
      <div className="flex items-start gap-3 border-b border-line bg-teal-500/[0.06] px-4 py-3">
        {entity.image ? (
          <img
            src={entity.image}
            alt=""
            loading="lazy"
            className="h-12 w-12 shrink-0 rounded-lg border border-line bg-surface-2 object-cover"
            onError={(e) => {
              // Wikimedia file paths 404 fairly often; drop the image rather
              // than leaving a broken placeholder.
              ;(e.currentTarget as HTMLImageElement).style.display = 'none'
            }}
          />
        ) : null}

        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-semibold tracking-tight">{entity.label}</p>
          {entity.description && (
            <p className="mt-0.5 text-[12.5px] leading-snug text-ink-muted">
              {entity.description}
            </p>
          )}
          {entity.aliases.length > 0 && (
            <p className="mt-1 text-[11px] text-ink-faint">
              also known as {entity.aliases.slice(0, 3).join(', ')}
            </p>
          )}
        </div>

        {entity.wikipedia_url && (
          <a
            href={entity.wikipedia_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-ghost shrink-0 px-2 py-1 text-[11px]"
            title="Open the Wikipedia article"
          >
            <IconExternal className="text-xs" />
            Wiki
          </a>
        )}
      </div>

      {/* Facts */}
      {facts.length > 0 ? (
        <dl className="divide-y divide-line/60">
          {facts.map((fact, i) => (
            <div
              key={`${fact.label}-${i}`}
              className="grid grid-cols-[minmax(0,10rem)_1fr] items-baseline gap-3 px-4 py-2 transition-colors hover:bg-surface-2/40"
            >
              <dt className="text-[11.5px] font-medium text-ink-faint">{fact.label}</dt>
              <dd className="min-w-0 text-[13.5px] text-ink">
                {fact.url ? (
                  <a
                    href={fact.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="font-medium text-accent underline decoration-accent/30 underline-offset-2 hover:decoration-accent"
                  >
                    {fact.value}
                  </a>
                ) : (
                  fact.value
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="px-4 py-3 text-[13px] text-ink-faint">
          Wikidata has this entity but no facts in the configured set.
        </p>
      )}

      {/* Footer */}
      <div className="flex items-center gap-1.5 border-t border-line bg-surface-2/40 px-4 py-2">
        <span className="chip !border-teal-500/30 !px-1.5 !py-0 text-[9px] !text-teal-600 dark:!text-teal-400">
          Wikidata {entity.qid}
        </span>
        <span className="text-[10.5px] text-ink-faint">
          Structured facts, not generated text
        </span>
      </div>
    </div>
  )
}
