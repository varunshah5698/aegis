import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  Bot,
  CornerDownLeft,
  FileText,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  User,
} from 'lucide-react'
import { api, ApiError, ASSISTANT_SUGGESTIONS } from '../lib/api'
import { Badge, Panel } from './ui'

/* ------------------------------------------------------------------ types */

export interface AiInsight {
  title: string
  detail: string
  severity?: string
  evidence?: string
}

export interface AiInsightsResponse {
  headline: string
  summary: string
  insights: AiInsight[]
  limitations?: string[]
  model: string
  latency_ms: number
  provenance: string
  unsupported_numbers: string[]
  truncated?: boolean
}

export interface AiStatus {
  enabled: boolean
  configured: boolean
  provider: string
  model: string | null
  models_available: number
  verified: boolean
  detail: string
  rate_limit_per_minute: number
}

export interface AiAnswer {
  answer: string
  ai_answer: string | null
  llm_note: string
  model: string | null
  latency_ms: number | null
  topic?: string
  confidence?: number
  limitations?: string[]
  unsupported_numbers?: string[]
}

const SEV: Record<string, 'danger' | 'amber' | 'sky' | 'neutral'> = {
  critical: 'danger', high: 'amber', medium: 'amber', low: 'sky', info: 'neutral',
}

/** Provider/model banner. Shows configuration state honestly, never the key. */
export function AiStatusChip({ status }: { status?: AiStatus }) {
  if (!status) return null
  if (!status.configured) {
    return (
      <Badge tone="neutral">
        <AlertTriangle size={12} aria-hidden />
        AI off · {status.detail.slice(0, 46)}
      </Badge>
    )
  }
  return (
    <Badge tone={status.verified ? 'lime' : 'amber'}>
      <Sparkles size={12} aria-hidden />
      {status.provider} · {status.model ?? 'resolving…'}
    </Badge>
  )
}

/**
 * AI insights for one analysis run: headline, summary, and insight cards.
 * Every card carries the computed evidence it rests on, and the response
 * reports any number in the text that was not found in that evidence.
 */
export function AiInsights({
  runId,
  datasetId,
  mode = 'run',
  icon: Icon = Sparkles,
  title,
  subtitle,
}: {
  runId?: string
  datasetId?: string
  mode?: 'run' | 'dataset'
  icon?: typeof Sparkles
  title?: string
  subtitle?: string
}) {
  const endpoint = mode === 'run' ? '/api/ai/insights' : '/api/ai/dataset-insights'
  const id = mode === 'run' ? runId : datasetId
  const [data, setData] = useState<AiInsightsResponse | null>(null)
  const [error, setError] = useState<{ message: string; code?: string } | null>(null)

  const status = useQuery<AiStatus>({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/api/ai/status'),
    staleTime: 120_000,
    retry: false,
  })

  const generate = useMutation<AiInsightsResponse, ApiError, void>({
    mutationFn: () =>
      api.post<AiInsightsResponse>(endpoint, mode === 'run' ? { run_id: id } : { run_id: id }),
    onSuccess: (res) => {
      setData(res)
      setError(null)
    },
    onError: (err) => {
      setData(null)
      setError({ message: err.message, code: (err.payload as { detail?: string })?.detail })
    },
  })

  useEffect(() => {
    // generate on mount when a provider is available and an id exists
    if (!id || status.data?.configured === false || generate.isPending || data) return
    if (status.isSuccess) generate.mutate()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, status.isSuccess, status.data?.configured])

  return (
    <Panel
      icon={Icon}
      title={title ?? 'AI analysis briefing'}
      subtitle={subtitle ?? 'Written by the language model over values computed by the analysis engine'}
      action={
        <div className="flex items-center gap-2">
          <AiStatusChip status={status.data} />
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
            onClick={() => generate.mutate()}
            disabled={generate.isPending || !id || status.data?.configured === false}
          >
            {generate.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw size={13} aria-hidden />
            )}
            {data ? 'Regenerate' : 'Generate'}
          </button>
        </div>
      }
      footer={
        data ? (
          <span>
            {data.provenance}
            {data.unsupported_numbers.length > 0 && (
              <span className="ml-1 font-medium text-amber">
                Unverified numbers: {data.unsupported_numbers.join(', ')}
              </span>
            )}
          </span>
        ) : (
          'Grounded narration: the model may only cite numbers present in the computed evidence.'
        )
      }
    >
      {status.data?.configured === false ? (
        <p className="rounded-[12px] border border-amber/40 bg-amber/10 px-4 py-3 text-[13.5px]">
          {status.data.detail}
        </p>
      ) : generate.isPending ? (
        <div className="space-y-3">
          <div className="h-5 w-2/3 animate-pulse rounded bg-mist" />
          <div className="h-3 w-full animate-pulse rounded bg-mist" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-mist" />
        </div>
      ) : error ? (
        <div className="rounded-[12px] border border-danger/40 bg-danger/8 px-4 py-3">
          <p className="text-[14px] font-medium text-danger">AI narration unavailable</p>
          <p className="mt-1 text-[13.5px] text-ink-soft">{error.message}</p>
          <p className="mt-1 text-[12.5px] text-ink-soft">
            The computed results are unaffected — every chart and number on this page still
            comes from the analysis engine.
          </p>
        </div>
      ) : !data ? (
        <p className="rounded-[12px] border border-dashed border-line/25 bg-mist/60 px-4 py-6 text-center text-[13.5px] text-ink-soft">
          {id ? 'No briefing generated yet.' : 'Analyze a dataset to generate a briefing.'}
        </p>
      ) : (
        <>
          <p className="text-[16.5px] leading-snug font-semibold">{data.headline}</p>
          <p className="mt-2 text-[14.5px] leading-relaxed text-ink-soft">{data.summary}</p>
          <ul className="mt-4 space-y-2.5">
            {data.insights.map((insight, i) => (
              <li key={`${insight.title}-${i}`} className="rounded-[14px] border border-line/12 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  {insight.severity && (
                    <Badge tone={SEV[insight.severity.toLowerCase()] ?? 'neutral'}>
                      {insight.severity}
                    </Badge>
                  )}
                  <b className="text-[14.5px]">{insight.title}</b>
                </div>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">{insight.detail}</p>
                {insight.evidence && (
                  <p className="mt-1.5 font-mono text-[11.5px] text-ink-soft/80">
                    evidence: {insight.evidence.slice(0, 220)}
                  </p>
                )}
              </li>
            ))}
          </ul>
          {data.limitations && data.limitations.length > 0 && (
            <ul className="mt-4 space-y-1 text-[12.5px] text-ink-soft">
              {data.limitations.map((l) => (
                <li key={l}>• {l}</li>
              ))}
            </ul>
          )}
          <p className="mt-4 flex items-center gap-1.5 text-[12px] text-ink-soft">
            <ShieldCheck size={12} aria-hidden />
            {data.model} · {data.latency_ms} ms
            {data.truncated && ' · response truncated by the token limit'}
          </p>
        </>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------- executive summary */

export function AiSummary({ runId }: { runId: string }) {
  const [data, setData] = useState<{
    headline: string
    summary: string
    priorities: string[]
    limitations?: string[]
    model: string
    latency_ms: number
  } | null>(null)
  const [error, setError] = useState('')

  const status = useQuery<AiStatus>({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/api/ai/status'),
    staleTime: 120_000,
    retry: false,
  })

  const run = useMutation({
    mutationFn: () => api.post<NonNullable<typeof data>>('/api/ai/summary', { run_id: runId }),
    onSuccess: (res) => {
      setData(res)
      setError('')
    },
    onError: (err) => {
      setData(null)
      setError(err instanceof ApiError ? err.message : 'Summary failed.')
    },
  })

  const configured = status.data?.configured !== false

  return (
    <Panel
      icon={FileText}
      title="AI executive summary"
      subtitle="Headline, review priorities and caveats over this run's own numbers"
      action={
        <div className="flex items-center gap-2">
          <AiStatusChip status={status.data} />
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
            onClick={() => run.mutate()}
            disabled={run.isPending || !configured}
          >
            {run.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <Sparkles size={13} aria-hidden />
            )}
            {data ? 'Regenerate' : 'Write summary'}
          </button>
        </div>
      }
      footer={data ? `${data.model} · ${data.latency_ms} ms · figures trace to the run manifest` : 'The model writes prose only; every figure comes from the run manifest.'}
    >
      {error && <p className="rounded-[12px] border border-danger/40 bg-danger/8 px-4 py-3 text-[13.5px] text-danger">{error}</p>}
      {!error && !data && !run.isPending && (
        <p className="rounded-[12px] border border-dashed border-line/25 bg-mist/60 px-4 py-5 text-center text-[13.5px] text-ink-soft">
          {configured ? 'Generate a reviewer-ready summary of this analysis.' : 'AI is not configured on the server.'}
        </p>
      )}
      {run.isPending && (
        <div className="space-y-3">
          <div className="h-5 w-2/3 animate-pulse rounded bg-mist" />
          <div className="h-3 w-full animate-pulse rounded bg-mist" />
          <div className="h-3 w-5/6 animate-pulse rounded bg-mist" />
        </div>
      )}
      {data && !run.isPending && (
        <>
          <p className="text-[16px] leading-snug font-semibold">{data.headline}</p>
          <p className="mt-2 text-[14.5px] leading-relaxed text-ink-soft">{data.summary}</p>
          {data.priorities?.length > 0 && (
            <ol className="mt-3 list-decimal space-y-1 pl-5 text-[14px]">
              {data.priorities.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ol>
          )}
          {data.limitations && data.limitations.length > 0 && (
            <ul className="mt-3 space-y-1 text-[12.5px] text-ink-soft">
              {data.limitations.map((l) => (
                <li key={l}>• {l}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------ chart narration ---- */

export function AiChartNarrate({ runId, chartId }: { runId: string; chartId: string }) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<{
    reading: string
    what_to_check: string[]
    limitations?: string[]
    model: string
    latency_ms: number
  } | null>(null)
  const [error, setError] = useState('')

  const run = useMutation({
    mutationFn: () =>
      api.post<NonNullable<typeof data>>('/api/ai/narrate', { run_id: runId, chart_id: chartId }),
    onSuccess: (res) => {
      setData(res)
      setError('')
    },
    onError: (err) => {
      setData(null)
      setError(err instanceof ApiError ? err.message : 'Narration failed.')
    },
  })

  return (
    <div className="mt-3">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
        onClick={() => {
          setOpen((v) => !v)
          if (!data && !run.isPending) run.mutate()
        }}
        disabled={run.isPending}
      >
        {run.isPending ? (
          <Loader2 size={12} className="animate-spin" aria-hidden />
        ) : (
          <Sparkles size={12} aria-hidden />
        )}
        {open ? 'Hide reading' : 'Explain this chart'}
      </button>
      {open && (
        <div className="mt-2 rounded-[12px] border border-line/15 bg-mist/60 px-4 py-3">
          {error && <p className="text-[13px] text-danger">{error}</p>}
          {data && (
            <>
              <p className="text-[13.5px] leading-relaxed">{data.reading}</p>
              {data.what_to_check?.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink-soft">
                  {data.what_to_check.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              )}
              <p className="mt-2 font-mono text-[11px] text-ink-soft/80">
                {data.model} · {data.latency_ms} ms
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ------------------------------------------------------ module narration -- */

/**
 * "Explain these numbers" for one workspace module. Sends only that module's
 * computed values to the model and renders the reading inline, so every tab of
 * the workspace has an AI reading of its own figures.
 */
export function AiSection({
  runId,
  section,
  label = 'Explain these numbers',
}: {
  runId: string
  section:
    | 'overview'
    | 'quality'
    | 'schema'
    | 'exploration'
    | 'relationships'
    | 'machine_learning'
    | 'anomaly'
    | 'forecast'
    | 'financial'
    | 'network'
    | 'records'
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const [data, setData] = useState<{
    headline: string
    reading: string
    watchouts: string[]
    limitations?: string[]
    model: string
    latency_ms: number
    unsupported_numbers?: string[]
  } | null>(null)
  const [error, setError] = useState('')

  const run = useMutation({
    mutationFn: () =>
      api.post<NonNullable<typeof data>>('/api/ai/section', { run_id: runId, section }),
    onSuccess: (res) => {
      setData(res)
      setError('')
    },
    onError: (err) => {
      setData(null)
      setError(err instanceof ApiError ? err.message : 'Narration failed.')
    },
  })

  return (
    <div className="rounded-[14px] border border-line/25 bg-mist/50 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[12.5px] text-ink-soft">
          <Sparkles size={12} aria-hidden />
          AI reading of this module's own computed values
        </span>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 bg-paper px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
          onClick={() => {
            setOpen((v) => !v)
            if (!data && !run.isPending) run.mutate()
          }}
          disabled={run.isPending}
        >
          {run.isPending ? (
            <Loader2 size={12} className="animate-spin" aria-hidden />
          ) : (
            <Sparkles size={12} aria-hidden />
          )}
          {open ? 'Hide' : data ? 'Show' : label}
        </button>
      </div>

      {open && (
        <div className="mt-2.5">
          {error && (
            <p className="rounded-[12px] border border-danger/40 bg-danger/8 px-3 py-2 text-[13px] text-danger">
              {error}
            </p>
          )}
          {data && (
            <>
              <p className="text-[14.5px] leading-snug font-semibold">{data.headline}</p>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-soft">{data.reading}</p>
              {data.watchouts?.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink-soft">
                  {data.watchouts.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              )}
              {data.limitations && data.limitations.length > 0 && (
                <ul className="mt-2 space-y-1 text-[12px] text-ink-soft/90">
                  {data.limitations.map((l) => (
                    <li key={l}>• {l}</li>
                  ))}
                </ul>
              )}
              {data.unsupported_numbers && data.unsupported_numbers.length > 0 && (
                <p className="mt-2 text-[12px] font-medium text-amber">
                  Numbers in the text not found in the computed evidence:{' '}
                  {data.unsupported_numbers.join(', ')}
                </p>
              )}
              <p className="mt-2 font-mono text-[11px] text-ink-soft/80">
                {data.model} · {data.latency_ms} ms · figures computed by the analysis engine
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ---------------------------------------------------------- workspace view */

export function AiWorkspaceSummary() {
  const [data, setData] = useState<{
    headline: string
    summary: string
    focus: string[]
    model: string
    latency_ms: number
  } | null>(null)
  const [error, setError] = useState('')

  const status = useQuery<AiStatus>({
    queryKey: ['ai-status'],
    queryFn: () => api.get<AiStatus>('/api/ai/status'),
    staleTime: 120_000,
    retry: false,
  })

  const run = useMutation({
    mutationFn: () =>
      api.post<NonNullable<typeof data>>('/api/ai/workspace-summary', {}),
    onSuccess: (res) => {
      setData(res)
      setError('')
    },
    onError: (err) => {
      setData(null)
      setError(err instanceof ApiError ? err.message : 'Workspace summary failed.')
    },
  })

  const configured = status.data?.configured !== false

  return (
    <Panel
      icon={Sparkles}
      title="AI workspace read"
      subtitle="Where to look first, from your own catalog counts"
      action={
        <div className="flex items-center gap-2">
          <AiStatusChip status={status.data} />
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
            onClick={() => run.mutate()}
            disabled={run.isPending || !configured}
          >
            {run.isPending ? (
              <Loader2 size={13} className="animate-spin" aria-hidden />
            ) : (
              <RefreshCw size={13} aria-hidden />
            )}
            {data ? 'Refresh' : 'Read my workspace'}
          </button>
        </div>
      }
      footer={data ? `${data.model} · ${data.latency_ms} ms · counts from your database, not the model` : 'The model only phrases counts computed from your database.'}
    >
      {error && <p className="rounded-[12px] border border-danger/40 bg-danger/8 px-4 py-3 text-[13.5px] text-danger">{error}</p>}
      {!error && !data && !run.isPending && (
        <p className="rounded-[12px] border border-dashed border-line/25 bg-mist/60 px-4 py-5 text-center text-[13.5px] text-ink-soft">
          {configured
            ? 'Generate a short briefing over your datasets and runs.'
            : 'AI is not configured on the server.'}
        </p>
      )}
      {run.isPending && (
        <div className="space-y-3">
          <div className="h-5 w-2/3 animate-pulse rounded bg-mist" />
          <div className="h-3 w-full animate-pulse rounded bg-mist" />
        </div>
      )}
      {data && !run.isPending && (
        <>
          <p className="text-[15.5px] leading-snug font-semibold">{data.headline}</p>
          <p className="mt-2 text-[14px] leading-relaxed text-ink-soft">{data.summary}</p>
          {data.focus?.length > 0 && (
            <ul className="mt-3 list-disc space-y-1 pl-5 text-[13.5px]">
              {data.focus.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </Panel>
  )
}

/* --------------------------------------------------------------- one alert */

export function AiExplain({
  runId,
  findingIndex,
  label = 'Explain with AI',
}: {
  runId: string
  findingIndex: number
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const [result, setResult] = useState<{
    explanation: string
    why_it_matters: string
    next_steps: string[]
    false_positive_check?: string
    limitations?: string[]
    model: string
    latency_ms: number
  } | null>(null)
  const [error, setError] = useState('')

  const explain = useMutation({
    mutationFn: () =>
      api.post<NonNullable<typeof result>>('/api/ai/explain', {
        run_id: runId,
        finding_index: findingIndex,
      }),
    onSuccess: (res) => {
      setResult(res)
      setError('')
    },
    onError: (err) => {
      setResult(null)
      setError(err instanceof ApiError ? err.message : 'Explanation failed.')
    },
  })

  return (
    <div className="mt-2">
      <button
        type="button"
        className="inline-flex items-center gap-1.5 rounded-[10px] border border-line/20 px-2.5 py-1.5 text-[12.5px] font-medium transition hover:bg-mist disabled:opacity-50"
        onClick={() => {
          setOpen((v) => !v)
          if (!result && !explain.isPending) explain.mutate()
        }}
        disabled={explain.isPending}
      >
        {explain.isPending ? (
          <Loader2 size={12} className="animate-spin" aria-hidden />
        ) : (
          <Sparkles size={12} aria-hidden />
        )}
        {open ? 'Hide explanation' : label}
      </button>

      {open && (
        <div className="mt-2 rounded-[12px] border border-line/15 bg-mist/60 px-4 py-3">
          {explain.isPending && (
            <p className="flex items-center gap-2 text-[13px] text-ink-soft">
              <Loader2 size={13} className="animate-spin" aria-hidden />
              Asking the model to explain this detection…
            </p>
          )}
          {error && <p className="text-[13px] text-danger">{error}</p>}
          {result && (
            <>
              <p className="text-[13.5px] leading-relaxed">{result.explanation}</p>
              <p className="mt-2 text-[13.5px] leading-relaxed">
                <b>Why it matters:</b> {result.why_it_matters}
              </p>
              {result.next_steps?.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ink-soft">
                  {result.next_steps.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              )}
              {result.false_positive_check && (
                <p className="mt-2 text-[13px] text-ink-soft">
                  <b>Could be legitimate:</b> {result.false_positive_check}
                </p>
              )}
              <p className="mt-2 font-mono text-[11px] text-ink-soft/80">
                {result.model} · {result.latency_ms} ms
              </p>
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------- chat */

interface Turn {
  role: 'user' | 'assistant'
  text: string
  computed?: string
  topic?: string
  confidence?: number
  note?: string
  error?: string
  model?: string | null
  unsupported?: string[]
}

/**
 * Grounded chat. The engine's computed answer is always shown; the model's
 * narration appears alongside it, clearly labelled, with a provenance note.
 */
export function AiChat({ runId, compact = false }: { runId: string; compact?: boolean }) {
  const [input, setInput] = useState('')
  const [turns, setTurns] = useState<Turn[]>([
    {
      role: 'assistant',
      text:
        'Ask about this dataset. The analysis engine computes the answer first; the ' +
        'language model then explains it, and I show both so you can check the wording ' +
        'against the numbers.',
    },
  ])
  const bottomRef = useRef<HTMLDivElement>(null)

  const ask = useMutation<AiAnswer, ApiError, string>({
    mutationFn: (question) =>
      api.post<AiAnswer>('/api/ai/ask', {
        run_id: runId,
        question,
        history: turns.slice(-6).map((t) => ({ role: t.role, text: t.text.slice(0, 400) })),
      }),
    onSuccess: (res) => {
      setTurns((t) => [
        ...t,
        {
          role: 'assistant',
          text: res.ai_answer || res.answer,
          computed: res.answer,
          topic: res.topic,
          confidence: res.confidence,
          note: res.llm_note,
          model: res.model,
          unsupported: res.unsupported_numbers,
        },
      ])
    },
    onError: (err) => {
      setTurns((t) => [...t, { role: 'assistant', text: 'That request failed.', error: err.message }])
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

  return (
    <Panel
      icon={Bot}
      title="Ask Aegis"
      subtitle="Computed answers with model narration over them — never the other way round"
      footer="Every figure comes from the analysis engine. The model only phrases the result."
    >
      <ol className={`space-y-3.5 overflow-y-auto scroll-ink pr-1 ${compact ? 'max-h-[360px]' : 'max-h-[460px]'}`}>
        {turns.map((t, i) => (
          <li key={i} className={`flex gap-2.5 ${t.role === 'user' ? 'justify-end' : ''}`}>
            {t.role === 'assistant' && (
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-ink text-lime">
                <Bot size={14} aria-hidden />
              </span>
            )}
            <div
              className={`max-w-[88%] rounded-[16px] px-3.5 py-2.5 text-[14px] leading-relaxed whitespace-pre-wrap ${
                t.role === 'user'
                  ? 'bg-ink text-paper'
                  : t.error
                    ? 'border border-danger/40 bg-danger/8'
                    : 'border border-line/15 bg-mist/70'
              }`}
            >
              {t.error ? `${t.text} — ${t.error}` : t.text}

              {t.computed && t.computed !== t.text && (
                <details className="mt-2 border-t border-line/20 pt-2">
                  <summary className="cursor-pointer text-[12.5px] font-medium text-ink-soft">
                    Engine-computed answer (authoritative)
                  </summary>
                  <pre className="mt-1.5 text-[12.5px] whitespace-pre-wrap text-ink-soft">
                    {t.computed}
                  </pre>
                </details>
              )}

              {t.unsupported && t.unsupported.length > 0 && (
                <p className="mt-2 text-[12px] font-medium text-amber">
                  Numbers in the narration not found in the evidence: {t.unsupported.join(', ')}
                </p>
              )}

              {(t.note || t.topic) && (
                <p className="mt-2 border-t border-line/20 pt-1.5 text-[11.5px] text-ink-soft">
                  {t.topic && `topic ${t.topic}`}
                  {t.confidence != null && ` · confidence ${Math.round(t.confidence * 100)}%`}
                  {t.model && ` · ${t.model}`}
                  {t.note && ` · ${t.note}`}
                </p>
              )}
            </div>
            {t.role === 'user' && (
              <span className="grid size-7 shrink-0 place-items-center rounded-full bg-lime ring-1 ring-line">
                <User size={13} aria-hidden />
              </span>
            )}
          </li>
        ))}
        {ask.isPending && (
          <li className="flex gap-2.5">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-ink text-lime">
              <Bot size={14} aria-hidden />
            </span>
            <span className="flex items-center gap-2 rounded-[16px] border border-line/15 bg-mist/70 px-3.5 py-2.5 text-[14px] text-ink-soft">
              <Loader2 size={14} className="animate-spin" aria-hidden />
              Computing then narrating…
            </span>
          </li>
        )}
        <div ref={bottomRef} />
      </ol>

      <form
        className="mt-4 flex flex-col gap-2 sm:flex-row"
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
      >
        <input
          className="field flex-1"
          placeholder="e.g. Which accounts sent the most value?"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={600}
          aria-label="Ask a question about this dataset"
        />
        <button type="submit" className="btn py-2.5 text-[14.5px]" disabled={ask.isPending || !input.trim()}>
          Ask
          <CornerDownLeft size={15} aria-hidden />
        </button>
      </form>

      <div className="mt-3 flex flex-wrap gap-2">
        {ASSISTANT_SUGGESTIONS.slice(0, 5).map((s) => (
          <button
            key={s}
            type="button"
            className="chip text-[12.5px] hover:bg-lime"
            onClick={() => submit(s)}
            disabled={ask.isPending}
          >
            {s}
          </button>
        ))}
      </div>
    </Panel>
  )
}
