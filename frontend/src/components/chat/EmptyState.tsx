/** Landing / empty state shown before any documents are uploaded. */

import { useEffect, useState } from 'react'
import { useApp } from '../../lib/AppContext'
import { smart, documents as docsApi } from '../../lib/api'
import { UploadDropzone } from '../documents/UploadDropzone'
import { IconFile, IconSparkle, IconUpload } from '../ui/Icons'
import { useToast } from '../ui/Toasts'

const FLOW = ['Upload', 'Process', 'Ask', 'Get cited answers']

export function EmptyState({ onAsk }: { onAsk: (question: string) => void }) {
  const { state, derived, reloadDocuments } = useApp()
  const toast = useToast()
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [loadingSuggestions, setLoadingSuggestions] = useState(false)
  const [loadingDemo, setLoadingDemo] = useState(false)

  // Once documents exist, offer question starters generated from their content.
  useEffect(() => {
    let cancelled = false
    const ids = state.documents
      .filter((d) => d.status === 'indexed')
      .slice(0, 4)
      .map((d) => d.id)

    if (!ids.length) {
      setSuggestions([])
      setLoadingSuggestions(false)
      return
    }

    setLoadingSuggestions(true)
    // Generation can take several seconds on CPU. Fall back to the static
    // prompts if it is slow or fails, so the chips never stay as skeletons.
    const timer = setTimeout(() => {
      if (!cancelled) {
        setLoadingSuggestions(false)
        setSuggestions(FALLBACK_QUESTIONS)
      }
    }, 8000)

    smart
      .suggestedQuestions(ids, state.activeCollectionId)
      .then((res) => {
        if (cancelled) return
        setSuggestions(res.questions.length ? res.questions : FALLBACK_QUESTIONS)
      })
      .catch(() => {
        if (!cancelled) setSuggestions(FALLBACK_QUESTIONS)
      })
      .finally(() => {
        clearTimeout(timer)
        if (!cancelled) setLoadingSuggestions(false)
      })

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [state.documents, state.activeCollectionId])

  const hasIndexed = derived.hasIndexed

  return (
    <div className="flex min-h-full flex-col items-center justify-center py-10">
      <div className="w-full max-w-2xl text-center">
        <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-accent text-white shadow-card">
          <IconSparkle className="text-2xl" />
        </div>

        <h2 className="text-balance text-[1.75rem] font-semibold tracking-tight">
          Chat with your documents.
        </h2>
        <p className="mx-auto mt-2.5 max-w-lg text-balance text-[15px] leading-relaxed text-ink-muted">
          Upload your files and ask questions. Your AI assistant will find the relevant
          information and explain it with sources.
        </p>

        <div className="mt-7 flex flex-wrap items-center justify-center gap-2.5">
          {hasIndexed ? (
            <button
              onClick={() =>
                document.querySelector<HTMLTextAreaElement>('textarea')?.focus()
              }
              className="btn-primary"
            >
              <IconSparkle className="text-base" />
              Ask a question
            </button>
          ) : (
            <button
              onClick={() =>
                document.querySelector<HTMLInputElement>('input[type=file]')?.click()
              }
              className="btn-primary"
            >
              <IconUpload className="text-base" />
              Upload Documents
            </button>
          )}
          <button onClick={loadDemo} disabled={loadingDemo} className="btn-secondary">
            <IconFile className="text-base" />
            {loadingDemo ? 'Loading…' : 'Try Demo Document'}
          </button>
        </div>

        {/* Pipeline explainer */}
        <div className="mt-9 flex flex-wrap items-center justify-center gap-x-2 gap-y-2 text-[12px] text-ink-faint">
          {FLOW.map((step, i) => (
            <span key={step} className="flex items-center gap-2">
              <span className="chip">{step}</span>
              {i < FLOW.length - 1 && <span aria-hidden>→</span>}
            </span>
          ))}
        </div>
      </div>

      {/* Suggested questions */}
      {(hasIndexed || loadingSuggestions) && (
        <div className="mt-9 w-full max-w-2xl">
          <p className="mb-2.5 text-center text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
            Try asking
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            {loadingSuggestions
              ? Array.from({ length: 3 }).map((_, i) => (
                  <span key={i} className="skeleton h-8 w-40" />
                ))
              : (suggestions.length ? suggestions : FALLBACK_QUESTIONS).map((q) => (
                  <button
                    key={q}
                    onClick={() => onAsk(q)}
                    className="chip max-w-full py-1.5 text-left transition-colors hover:border-accent/45 hover:text-ink"
                  >
                    <span className="truncate">{q}</span>
                  </button>
                ))}
          </div>
        </div>
      )}

      {!hasIndexed && (
        <div className="mt-9 w-full max-w-2xl">
          <UploadDropzone />
        </div>
      )}
    </div>
  )

  async function loadDemo() {
    setLoadingDemo(true)
    try {
      const file = new File([DEMO_DOCUMENT], 'Demo-Renewable-Energy.txt', {
        type: 'text/plain',
      })
      await docsApi.upload([file], state.activeCollectionId)
      await reloadDocuments()
      toast.push('Demo document uploaded and indexing', 'success')
    } catch (e) {
      toast.push((e as Error).message, 'error')
    } finally {
      setLoadingDemo(false)
    }
  }
}

const FALLBACK_QUESTIONS = [
  'What is the main topic of this document?',
  'Summarize the key findings',
  'What methodology was used?',
  'What are the limitations?',
]

const DEMO_DOCUMENT = `Renewable Energy: Solar Photovoltaics and Wind Power

Overview
Renewable energy sources replenish naturally and produce far lower greenhouse gas
emissions than fossil fuels. This document describes the two dominant technologies:
solar photovoltaic systems and wind turbines.

Solar Photovoltaics
A photovoltaic cell is built from doped silicon. When photons strike the material
they dislodge electrons, generating direct current. An inverter converts this direct
current into alternating current for grid use.

Standard silicon panels achieve roughly 20 percent conversion efficiency, though
perovskite tandem cells in laboratories have exceeded 30 percent. Efficiency degrades
with temperature and with dust accumulation on the glass surface.

Wind Turbines
Wind turbines capture kinetic energy with three blades mounted on a central hub.
The rotor spins a shaft connected to a generator. Larger rotors extract more energy at
lower wind speeds.

Betz's law limits extraction to roughly 59 percent of the wind's kinetic power, meaning
no turbine can ever capture the full energy in the moving air. Cut-in speed is typically
3 to 4 metres per second and rated output is reached around 12 to 15 metres per second.

Storage and Grid Integration
Intermittency is the central challenge of renewable power. Grid scale battery storage
using lithium iron phosphate cells smooths short term fluctuations.

Pumped hydro storage remains the most deployed form of bulk storage, storing energy by
lifting water into elevated reservoirs during periods of surplus generation.

Economic Considerations
Levelised cost of energy for utility scale solar has fallen by roughly 90 percent since
2010. Wind generation is often the cheapest electricity source in resource rich regions.

Policy instruments such as feed in tariffs and renewable portfolio standards accelerate
deployment. Curtailment, when generation exceeds grid demand, remains an economic loss
for operators.
`