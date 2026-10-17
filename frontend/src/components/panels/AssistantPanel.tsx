import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Bot, CornerDownLeft, Loader2, Sparkles, User } from 'lucide-react'
import { api, ApiError, ASSISTANT_SUGGESTIONS } from '../../lib/api'
import type { AssistantResponse } from '../../lib/types'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  payload?: AssistantResponse
  error?: string
}

/**
 * Conversational panel. Every answer is produced server-side by the
 * allowlisted query planner over persisted results — the client renders it and
 * never computes its own numbers (spec #15).
 */
export default function AssistantPanel({ runId }: { runId: string }) {
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([
    {
      role: 'assistant',
      text: 'Ask me anything about this dataset. I answer from the persisted analysis — findings, quality, top senders, anomalies, cycles, currency, model features.',
    },
  ])
  const bottomRef = useRef<HTMLDivElement>(null)

  const ask = useMutation<AssistantResponse, ApiError, string>({
    mutationFn: (question) =>
      api.post<AssistantResponse>(`/api/runs/${runId}/ask`, { question }),
    onSuccess: (payload) => {
      setTurns((t) => [
        ...t.filter((x) => !(x.role === 'user' && x.error)),
        { role: 'assistant', text: payload.answer, payload },
      ])
    },
    onError: (err) => {
      setTurns((t) => [
        ...t,
        { role: 'assistant', text: 'I could not answer that.', error: err.message },
      ])
    },
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [turns.length, ask.isPending])

  function submit(text: string) {
    const q = text.trim()
    if (!q || ask.isPending) return
    setTurns((t) => [...t, { role: 'user', text: q }])
    setInput('')
    ask.mutate(q)
  }

  const lastPayload = [...turns].reverse().find((t) => t.payload)?.payload

  return (
    <div className="space-y-5">
      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-[26px] font-medium tracking-[-0.03em]">
              Ask your <span className="marker">dataset</span>
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              Answers come from the allowlisted query planner over persisted results.
            </p>
          </div>
          <span className="chip bg-lime">
            <Sparkles size={13} aria-hidden />
            {lastPayload?.llm_note ? 'LLM-assisted' : 'rule-based planner'}
          </span>
        </div>

        {/* ------------------------------------------------------ transcript */}
        <ol className="mt-6 max-h-[460px] space-y-4 overflow-y-auto scroll-ink pr-2">
          {turns.map((t, i) => (
            <li key={i} className={`flex gap-3 ${t.role === 'user' ? 'justify-end' : ''}`}>
              {t.role === 'assistant' && (
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-lime">
                  <Bot size={16} aria-hidden />
                </span>
              )}
              <div
                className={`max-w-[86%] rounded-[18px] px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap ${
                  t.role === 'user'
                    ? 'bg-ink text-paper'
                    : t.error
                      ? 'border border-danger bg-danger/8'
                      : 'border border-line/30 bg-mist'
                }`}
              >
                {t.error ? `${t.text} — ${t.error}` : t.text}

                {t.payload?.chart_hint && t.payload.chart_hint.rows.length > 0 && (
                  <div className="mt-3 rounded-[12px] border border-line/30 bg-paper p-3">
                    <p className="text-[12.5px] text-ink-soft">
                      {t.payload.chart_hint.rows.length} rows · {t.payload.chart_hint.type}
                    </p>
                    <table className="mt-2 w-full text-[13px]">
                      <thead>
                        <tr>
                          <th className="text-left">{t.payload.chart_hint.x}</th>
                          <th className="text-right">{t.payload.chart_hint.y}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {t.payload.chart_hint.rows.slice(0, 8).map((row, j) => (
                          <tr key={j} className="border-t border-line/15">
                            <td className="py-1 truncate">
                              {String(row[t.payload!.chart_hint!.x] ?? '')}
                            </td>
                            <td className="py-1 text-right tabular-nums">
                              {format(row[t.payload!.chart_hint!.y])}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {t.payload && (
                  <p className="mt-3 border-t border-line/25 pt-2 text-[12.5px] opacity-80">
                    {t.payload.scope} · confidence {Math.round(t.payload.confidence * 100)}%
                  </p>
                )}
              </div>
              {t.role === 'user' && (
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-lime ring-1 ring-line">
                  <User size={15} aria-hidden />
                </span>
              )}
            </li>
          ))}
          {ask.isPending && (
            <li className="flex gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-lime">
                <Bot size={16} aria-hidden />
              </span>
              <span className="flex items-center gap-2 rounded-[18px] border border-line/30 bg-mist px-4 py-3 text-[15px] text-ink-soft">
                <Loader2 size={15} className="animate-spin" aria-hidden />
                Running the query…
              </span>
            </li>
          )}
          <div ref={bottomRef} />
        </ol>

        {/* --------------------------------------------------------- input */}
        <form
          className="mt-5 flex gap-3"
          onSubmit={(e) => {
            e.preventDefault()
            submit(input)
          }}
        >
          <input
            className="field flex-1"
            placeholder="e.g. Which accounts have the highest outgoing transfers?"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            aria-label="Ask a question about this dataset"
          />
          <button type="submit" className="btn" disabled={ask.isPending || !input.trim()}>
            Ask
            <CornerDownLeft size={15} aria-hidden />
          </button>
        </form>

        <div className="mt-4 flex flex-wrap gap-2">
          {ASSISTANT_SUGGESTIONS.slice(0, 6).map((s) => (
            <button
              key={s}
              type="button"
              className="chip hover:bg-lime"
              onClick={() => submit(s)}
              disabled={ask.isPending}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* -------------------------------------------------- scope + limits */}
      <div className="panel p-5">
        <p className="text-[14.5px] font-medium">How this assistant works</p>
        <ul className="mt-2.5 list-disc space-y-1.5 pl-5 text-[14px] text-ink-soft">
          <li>
            Your question is matched to an allowlisted operation; the backend executes it and
            returns real numbers.
          </li>
          <li>No unrestricted database or code execution is exposed to the model.</li>
          <li>Uploaded rows are never sent to an external provider in this deployment.</li>
          {lastPayload?.limitations?.map((l) => <li key={l}>{l}</li>)}
        </ul>
      </div>
    </div>
  )
}

function format(v: unknown): string {
  if (typeof v === 'number') {
    return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2)
  }
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
