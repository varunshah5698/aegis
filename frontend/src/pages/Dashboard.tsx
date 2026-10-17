import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  ArrowUpRight,
  Banknote,
  Bell,
  CalendarCheck,
  ChartPie,
  Database,
  FileSpreadsheet,
  Gauge,
  GitBranch,
  Layers,
  LayoutList,
  MessagesSquare,
  Play,
  ShieldAlert,
  Sparkles,
  Table2,
  TrendingUp,
  UploadCloud,
} from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { api, ApiError } from '../lib/api'
import type {
  DatasetOut,
  Finding,
  Manifest,
  Overview,
  PreviewOut,
  QualityReport,
  SchemaOut,
} from '../lib/types'
import { AiExplain, AiInsights } from '../components/AiPanel'
import {
  Badge,
  CHART_SERIES,
  ChartTooltip,
  Empty,
  MiniStat,
  Panel,
  PageHeader,
  StatCard,
  compactNumber,
  formatWhen,
  prettify,
} from '../components/ui'

const SECTIONS = [
  { id: 'summary', label: 'Summary' },
  { id: 'ai', label: 'AI briefing' },
  { id: 'profile', label: 'Columns' },
  { id: 'quality', label: 'Quality' },
  { id: 'records', label: 'Records' },
  { id: 'detections', label: 'Detections' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'flows', label: 'Flows' },
  { id: 'ml', label: 'ML signals' },
  { id: 'forecast', label: 'Forecast' },
  { id: 'notes', label: 'Messages' },
]

const SEV_TONE: Record<string, 'danger' | 'amber' | 'sky' | 'neutral'> = {
  critical: 'danger',
  high: 'amber',
  medium: 'amber',
  low: 'sky',
  info: 'neutral',
}

/**
 * Dataset analysis report. Pick a dataset (and one of its runs) and every
 * panel below analyzes that selection: profile, quality, records, detections,
 * alerts, flows, ML signals and forecast. Uploading lives on /upload.
 */
export default function Dashboard() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [datasetId, setDatasetId] = useState('')
  const [runId, setRunId] = useState('')
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState('')
  const [sevFilter, setSevFilter] = useState('all')
  const [alertQuery, setAlertQuery] = useState('')
  const [msgDraft, setMsgDraft] = useState('')
  const [msgError, setMsgError] = useState('')

  const { data: datasets, isPending } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })

  const { data: overview } = useQuery<Overview>({
    queryKey: ['overview'],
    queryFn: () => api.get<Overview>('/api/workspaces/overview'),
    staleTime: 15_000,
  })

  const dataset = (datasets ?? []).find((d) => d.id === datasetId) ?? (datasets ?? [])[0]
  const dsid = dataset?.id ?? ''
  const finishedRuns = useMemo(
    () => (dataset?.runs ?? []).filter((r) => r.status === 'completed' || r.status === 'partial'),
    [dataset],
  )
  const activeRun = runId || finishedRuns[0]?.id || ''

  const { data: schema } = useQuery<SchemaOut>({
    queryKey: ['dataset-schema', dsid],
    queryFn: () => api.get<SchemaOut>(`/api/datasets/${dsid}/schema`),
    enabled: !!dsid,
    retry: false,
    staleTime: 60_000,
  })

  const { data: quality } = useQuery<QualityReport>({
    queryKey: ['dataset-quality', dsid],
    queryFn: () => api.get<QualityReport>(`/api/datasets/${dsid}/quality`),
    enabled: !!dsid,
    retry: false,
    staleTime: 60_000,
  })

  const { data: preview } = useQuery<PreviewOut>({
    queryKey: ['dataset-preview', dsid],
    queryFn: () => api.get<PreviewOut>(`/api/datasets/${dsid}/preview?rows=8`),
    enabled: !!dsid,
    retry: false,
    staleTime: 60_000,
  })

  const { data: manifest } = useQuery<Manifest>({
    queryKey: ['manifest', activeRun],
    queryFn: () => api.get<Manifest>(`/api/runs/${activeRun}/manifest`),
    enabled: !!activeRun,
    retry: false,
    staleTime: 60_000,
  })

  const postMessage = useMutation({
    mutationFn: (text: string) => api.post(`/api/datasets/${dsid}/comments`, { text }),
    onSuccess: () => {
      setMsgDraft('')
      setMsgError('')
    },
    onError: (err) => setMsgError(err instanceof ApiError ? err.message : 'Could not send.'),
  })

  async function startAnalysis() {
    if (!dsid) return
    setStarting(true)
    setRunError('')
    try {
      const res = await api.post<{ run_id: string }>('/api/runs/start', {
        dataset_id: dsid,
        column_overrides: {},
        config: {},
      })
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      navigate(`/run/${res.run_id}/process`)
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Could not start the analysis run.')
    } finally {
      setStarting(false)
    }
  }

  /* ------------------------------------------------- derived chart data */
  const typeData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const c of schema?.columns ?? []) {
      const t = c.semantic_type || c.physical_type || 'unknown'
      counts.set(t, (counts.get(t) ?? 0) + 1)
    }
    return [...counts.entries()].map(([name, value], i) => ({
      name: prettify(name),
      value,
      fill: CHART_SERIES[i % CHART_SERIES.length],
    }))
  }, [schema])

  const missingData = useMemo(
    () =>
      (quality?.missing?.columns_with_missing ?? [])
        .slice()
        .sort((a, b) => b.missing_pct - a.missing_pct)
        .slice(0, 10)
        .map((c) => ({
          name: c.column.length > 16 ? `${c.column.slice(0, 15)}…` : c.column,
          pct: c.missing_pct,
        })),
    [quality],
  )

  const numericProfile = useMemo(
    () =>
      (schema?.columns ?? [])
        .filter((c) => c.numeric_mean != null && c.numeric_min != null && c.numeric_max != null)
        .slice(0, 40)
        .map((c) => ({
          name: c.name,
          min: c.numeric_min as number,
          max: c.numeric_max as number,
          mean: c.numeric_mean as number,
        })),
    [schema],
  )

  const patternFindings: Finding[] = useMemo(() => {
    const p = manifest?.financial?.modules?.patterns
    return p && Array.isArray(p.findings) ? (p.findings as Finding[]) : []
  }, [manifest])

  const kindData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of patternFindings) {
      const k = prettify(f.kind || 'other')
      counts.set(k, (counts.get(k) ?? 0) + 1)
    }
    return [...counts.entries()].map(([kind, count], i) => ({
      kind,
      count,
      fill: CHART_SERIES[i % CHART_SERIES.length],
    }))
  }, [patternFindings])

  const sevData = useMemo(() => {
    const counts = new Map<string, number>()
    for (const f of patternFindings) {
      const s = (f.severity || 'info').toLowerCase()
      counts.set(s, (counts.get(s) ?? 0) + 1)
    }
    return [...counts.entries()].map(([name, value], i) => ({
      name,
      value,
      fill: CHART_SERIES[(i + 3) % CHART_SERIES.length],
    }))
  }, [patternFindings])

  const severities = useMemo(
    () => [...new Set(patternFindings.map((f) => (f.severity || 'info').toLowerCase()))],
    [patternFindings],
  )

  const alerts = useMemo(() => {
    const q = alertQuery.trim().toLowerCase()
    return patternFindings
      .filter((f) => {
        if (sevFilter !== 'all' && (f.severity || 'info').toLowerCase() !== sevFilter) return false
        if (q && !`${f.title} ${f.entity} ${f.kind}`.toLowerCase().includes(q)) return false
        return true
      })
      .slice(0, 10)
  }, [patternFindings, sevFilter, alertQuery])

  const flowData = useMemo(() => {
    const nodes = manifest?.financial?.modules?.network?.nodes ?? []
    return nodes
      .map((n) => ({
        name: n.label.length > 14 ? `${n.label.slice(0, 13)}…` : n.label,
        value: n.in_value + n.out_value,
        pagerank: n.pagerank,
      }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 8)
  }, [manifest])

  const mlMetrics = useMemo(() => {
    const m = manifest?.ml?.supervised?.metrics ?? {}
    return Object.entries(m)
      .filter(([, v]) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 1)
      .slice(0, 6)
      .map(([name, value]) => ({ name: prettify(name), value: value as number }))
  }, [manifest])

  const forecastData = useMemo(() => {
    const f = manifest?.forecast as
      | { status?: string; history?: { t: string; actual: number }[]; future?: { t: string; forecast: number }[] }
      | undefined
    if (!f || f.status !== 'completed') return null
    return [
      ...(f.history ?? []).slice(-10).map((h) => ({ t: h.t, actual: h.actual, forecast: null as number | null })),
      ...(f.future ?? []).slice(0, 6).map((x) => ({ t: x.t, actual: null as number | null, forecast: x.forecast })),
    ]
  }, [manifest])

  if (isPending) {
    return (
      <div className="flex items-center gap-3 py-24">
        <span className="size-4 animate-spin rounded-full border-2 border-line border-t-transparent" />
        <span className="text-[15px] text-ink-soft">Loading your datasets…</span>
      </div>
    )
  }

  if (!datasets?.length) {
    return (
      <div className="mx-auto max-w-[640px] py-20 text-center">
        <span className="mx-auto grid size-14 place-items-center rounded-[16px] bg-ink text-lime">
          <Database size={24} aria-hidden />
        </span>
        <h1 className="mt-5 text-[28px] font-semibold tracking-[-0.03em]">No datasets yet</h1>
        <p className="mx-auto mt-2 max-w-[48ch] text-[15px] text-ink-soft">
          Upload a CSV and this dashboard becomes its graphical analysis — profile,
          quality, records, detections, flows and forecast.
        </p>
        <Link to="/upload" className="btn mt-6">
          <UploadCloud size={16} aria-hidden />
          Upload a dataset
        </Link>
      </div>
    )
  }

  return (
    <>
      <PageHeader
        eyebrow="Analysis report"
        title={dataset?.filename ?? 'Dataset'}
        description={
          <>
            {dataset?.row_count.toLocaleString()} rows · {dataset?.column_count} columns ·{' '}
            {finishedRuns.length} finished {finishedRuns.length === 1 ? 'run' : 'runs'} · validation{' '}
            <b className="text-ink">{dataset?.validation_status}</b>
            {runError && <span className="ml-2 text-danger">{runError}</span>}
          </>
        }
        actions={
          <>
            <select
              value={dsid}
              onChange={(e) => {
                setDatasetId(e.target.value)
                setRunId('')
              }}
              className="field w-auto min-w-[220px] py-2.5"
              aria-label="Choose a dataset"
            >
              {(datasets ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename} · {d.row_count.toLocaleString()} rows
                </option>
              ))}
            </select>
            {finishedRuns.length > 1 && (
              <select
                value={activeRun}
                onChange={(e) => setRunId(e.target.value)}
                className="field w-auto py-2.5"
                aria-label="Choose a run"
              >
                {finishedRuns.map((r) => (
                  <option key={r.id} value={r.id}>
                    run {r.id.slice(0, 8)} · {r.status}
                  </option>
                ))}
              </select>
            )}
            <button type="button" className="btn py-2.5" disabled={starting} onClick={startAnalysis}>
              {starting ? 'Starting…' : 'Run analysis'}
              <span className="grid size-6 place-items-center rounded-full bg-lime text-ink">
                <Play size={12} aria-hidden />
              </span>
            </button>
            <Link to={`/datasets/${dsid}`} className="btn btn-ghost py-2.5">
              Detail page
              <ArrowUpRight size={15} aria-hidden />
            </Link>
          </>
        }
      />

      {/* section rail — persistent structure for the whole report */}
      <nav aria-label="Report sections" className="panel sticky top-[76px] z-20 mb-6 flex gap-1 overflow-x-auto px-2.5 py-2">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#sec-${s.id}`}
            className="shrink-0 rounded-[10px] px-3.5 py-1.5 text-[13.5px] font-medium text-ink-soft transition-colors hover:bg-mist hover:text-ink"
          >
            {s.label}
          </a>
        ))}
      </nav>

      <div className="space-y-5">
        {/* ---------------------------------------------------- summary */}
        <section id="sec-summary" className="scroll-mt-32">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard icon={Database} label="Transactions" value={(dataset?.row_count ?? 0).toLocaleString()} hint="Rows in this dataset" />
            <StatCard icon={Table2} label="Columns" value={String(dataset?.column_count ?? 0)} hint="Fields profiled" accent="bg-teal/20 text-ink" />
            <StatCard icon={Bell} label="Detections" value={String(patternFindings.length)} hint={activeRun ? 'Patterns found' : 'No analysis yet'} accent="bg-amber/25 text-ink" />
            <StatCard icon={Gauge} label="Quality score" value={quality ? `${quality.score}` : '—'} hint={quality ? `Grade ${quality.grade}` : 'Scored after analysis'} accent="bg-violet-300/40 text-ink" />
          </div>

          <div id="sec-ai" className="mt-5 scroll-mt-32">
            <AiInsights
              runId={finishedRuns.length ? activeRun : undefined}
              title="AI briefing on every value"
              subtitle="Headline, summary and insight cards over the computed results below"
            />
          </div>
        </section>

        <div className="grid gap-5 xl:grid-cols-2">
          {/* -------------------------------------------------- columns */}
          <Panel
            id="sec-profile"
            icon={ChartPie}
            title="Column profile"
            subtitle="Inferred semantic types across the dataset"
            footer={
              schema
                ? `${schema.columns.length} columns profiled · ${schema.warnings.length} inference warnings`
                : 'Inference runs with the analysis'
            }
          >
            {!typeData.length ? (
              <Empty text="Column inference appears once the schema stage completes." />
            ) : (
              <div className="flex flex-wrap items-center gap-6">
                <ResponsiveContainer width={200} height={200}>
                  <PieChart>
                    <Pie data={typeData} dataKey="value" nameKey="name" innerRadius={52} outerRadius={84} paddingAngle={3}>
                      {typeData.map((d, i) => (
                        <Cell key={i} fill={d.fill} />
                      ))}
                    </Pie>
                    <Tooltip content={<ChartTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
                <ul className="space-y-2 text-[13.5px]">
                  {typeData.map((d) => (
                    <li key={d.name} className="flex items-center gap-2.5">
                      <span className="size-2.5 rounded-full" style={{ background: d.fill }} />
                      <b>{d.name}</b>
                      <span className="tabular-nums text-ink-soft">{d.value}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>

          {/* -------------------------------------------------- quality */}
          <Panel
            id="sec-quality"
            icon={ShieldAlert}
            title="Data quality"
            subtitle="Missing values, duplicates and validity"
            action={quality && <Badge tone={quality.score >= 90 ? 'lime' : quality.score >= 75 ? 'amber' : 'danger'}>{quality.grade}</Badge>}
            footer={quality?.formula}
          >
            {!quality ? (
              <Empty text="Quality scoring appears after an analysis run finishes." />
            ) : (
              <>
                <div className="flex items-baseline gap-2">
                  <span className="text-[34px] leading-none font-semibold tabular-nums">{quality.score}</span>
                  <span className="text-[13.5px] text-ink-soft">/ 100</span>
                </div>
                {missingData.length > 0 && (
                  <div className="mt-4">
                    <p className="mb-2 text-[12.5px] font-medium text-ink-soft">Missing values by column (%)</p>
                    <ResponsiveContainer width="100%" height={170}>
                      <BarChart data={missingData} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" horizontal={false} />
                        <XAxis type="number" tick={{ fontSize: 11 }} />
                        <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={120} />
                        <Tooltip content={<ChartTooltip />} />
                        <Bar dataKey="pct" fill="#e8a33d" radius={[0, 5, 5, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <ul className="mt-3 space-y-1.5 text-[13.5px] text-ink-soft">
                  {quality.summary.slice(0, 3).map((s, i) => (
                    <li key={i}>• {s}</li>
                  ))}
                </ul>
              </>
            )}
          </Panel>
        </div>

        {/* ---------------------------------------------------- records */}
        <Panel
          id="sec-records"
          icon={LayoutList}
          title="Records"
          subtitle="First rows exactly as parsed"
          action={<Badge tone="neutral">preview</Badge>}
          footer={preview ? `${preview.total_rows.toLocaleString()} total rows${preview.truncated ? ' · showing a sample' : ''}` : undefined}
        >
          {!preview ? (
            <Empty text="Record preview is unavailable for this file." />
          ) : (
            <div className="scroll-ink -mx-1 overflow-x-auto">
              <table className="table-grid text-[12.5px]">
                <thead>
                  <tr>
                    {preview.columns.slice(0, 7).map((c) => (
                      <th key={c}>{c}</th>
                    ))}
                    {preview.columns.length > 7 && <th>…</th>}
                  </tr>
                </thead>
                <tbody>
                  {preview.rows.slice(0, 7).map((row, i) => (
                    <tr key={i}>
                      {row.slice(0, 7).map((cell, j) => (
                        <td key={j} className="max-w-[190px] truncate">
                          {String(cell)}
                        </td>
                      ))}
                      {row.length > 7 && <td>…</td>}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <div className="grid gap-5 xl:grid-cols-2">
          {/* ----------------------------------------------- detections */}
          <Panel
            id="sec-detections"
            icon={Layers}
            title="Detections by pattern"
            subtitle="Rule-engine findings in the selected run"
            action={patternFindings.length > 0 && <Badge tone="lime">{patternFindings.length} found</Badge>}
          >
            {!activeRun ? (
              <Empty text="Run an analysis to activate the detection charts." />
            ) : !kindData.length ? (
              <Empty text="No detector triggered on this file — a clean result is still a result." />
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={kindData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="kind" tick={{ fontSize: 11 }} width={140} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="count" radius={[0, 5, 5, 0]}>
                    {kindData.map((d, i) => (
                      <Cell key={i} fill={d.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>

          {/* ------------------------------------------------ severity */}
          <Panel
            id="sec-severity"
            icon={Gauge}
            title="Severity mix"
            subtitle="How the findings split by severity"
          >
            {!sevData.length ? (
              <Empty text="Severity breakdown appears with the first detection run." />
            ) : (
              <div className="flex flex-wrap items-center gap-6">
                <ResponsiveContainer width={190} height={190}>
                  <PieChart>
                    <Pie data={sevData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={80} paddingAngle={3}>
                      {sevData.map((d, i) => (
                        <Cell key={i} fill={d.fill} />
                      ))}
                    </Pie>
                    <Tooltip content={<ChartTooltip />} />
                  </PieChart>
                </ResponsiveContainer>
                <ul className="space-y-2 text-[13.5px]">
                  {sevData.map((d) => (
                    <li key={d.name} className="flex items-center gap-2.5">
                      <span className="size-2.5 rounded-full" style={{ background: d.fill }} />
                      <b className="capitalize">{d.name}</b>
                      <span className="tabular-nums text-ink-soft">{d.value}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </div>

        {/* ----------------------------------------------------- alerts */}
        <Panel
          id="sec-alerts"
          icon={Bell}
          title="Alert queue"
          subtitle="Prioritized findings with the evidence behind each one"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={alertQuery}
                onChange={(e) => setAlertQuery(e.target.value)}
                placeholder="Filter…"
                className="field w-[150px] py-2 text-[13.5px]"
                aria-label="Filter alerts"
              />
              <select
                value={sevFilter}
                onChange={(e) => setSevFilter(e.target.value)}
                className="field w-auto py-2 text-[13.5px]"
                aria-label="Filter by severity"
              >
                <option value="all">All</option>
                {severities.map((s) => (
                  <option key={s} value={s} className="capitalize">
                    {s}
                  </option>
                ))}
              </select>
            </div>
          }
          footer={
            activeRun ? (
              <Link to={`/run/${activeRun}`} className="inline-flex items-center gap-1.5 font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4">
                Open the full investigation workspace
                <ArrowUpRight size={13} aria-hidden />
              </Link>
            ) : (
              'Alerts are statistical patterns for human review — they do not prove wrongdoing.'
            )
          }
        >
          {!alerts.length ? (
            <Empty text={patternFindings.length ? 'No alerts match these filters.' : 'The queue fills once detections run.'} />
          ) : (
            <ul className="divide-y divide-line/10">
              {alerts.map((f, i) => (
                <li key={`${f.kind}-${i}`} className="flex flex-wrap items-start gap-3 py-3 first:pt-0 last:pb-0">
                  <Badge tone={SEV_TONE[(f.severity || 'info').toLowerCase()] ?? 'neutral'}>
                    {f.severity || 'info'}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-[14.5px] font-medium">{f.title}</p>
                    <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">{f.evidence}</p>
                    <p className="mt-1.5 font-mono text-[11.5px] text-ink-soft">
                      {prettify(f.kind)} · entity {f.entity} · {f.method}
                    </p>
                    <AiExplain
                      runId={activeRun}
                      findingIndex={patternFindings.indexOf(f)}
                    />
                  </div>
                  <Badge tone="neutral">{f.row_count} rows</Badge>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="grid gap-5 xl:grid-cols-2">
          {/* ---------------------------------------------------- flows */}
          <Panel
            id="sec-flows"
            icon={GitBranch}
            title="Money flows"
            subtitle="Entities ranked by total flow value"
            action={
              manifest?.financial?.modules?.network && (
                <Badge tone="teal">
                  {manifest.financial.modules.network.node_count} entities
                </Badge>
              )
            }
            footer={
              activeRun && flowData.length ? (
                <Link to={`/run/${activeRun}`} className="font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4">
                  Explore the full transfer graph
                </Link>
              ) : undefined
            }
          >
            {!flowData.length ? (
              <Empty text="The entity network activates for transaction datasets with sender and receiver columns." />
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={flowData} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" horizontal={false} />
                  <XAxis type="number" tickFormatter={compactNumber} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={104} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="value" fill="#FA9D72" radius={[0, 5, 5, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Panel>

          {/* ------------------------------------------------------- ml */}
          <Panel
            id="sec-ml"
            icon={Sparkles}
            title="Machine-learning signals"
            subtitle="Anomaly detection kept separate from the rule score"
            action={manifest?.ml?.anomaly?.status && <Badge tone="violet">{manifest.ml.anomaly.status}</Badge>}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <MiniStat label="Method" value={manifest?.ml?.anomaly?.method ?? '—'} />
              <MiniStat label="Flagged" value={String(manifest?.ml?.anomaly?.anomalies?.length ?? 0)} />
              <MiniStat label="Best model" value={manifest?.ml?.supervised?.best_model ?? '—'} />
            </div>
            {mlMetrics.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-[12.5px] font-medium text-ink-soft">Hold-out metrics (0–1)</p>
                <ResponsiveContainer width="100%" height={165}>
                  <BarChart data={mlMetrics} margin={{ top: 0, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" vertical={false} />
                    <XAxis dataKey="name" tick={{ fontSize: 10.5 }} />
                    <YAxis domain={[0, 1]} tick={{ fontSize: 10.5 }} width={34} />
                    <Tooltip content={<ChartTooltip />} />
                    <Bar dataKey="value" fill="#FA9D72" stroke="#FA9D72" strokeWidth={1} radius={[5, 5, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            {manifest?.ml?.anomaly?.anomalies?.length ? (
              <div className="mt-4">
                <p className="mb-2 text-[12.5px] font-medium text-ink-soft">Flagged rows by anomaly score</p>
                <ResponsiveContainer width="100%" height={150}>
                  <ScatterChart margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" />
                    <XAxis dataKey="row_index" name="row" tick={{ fontSize: 10.5 }} />
                    <YAxis dataKey="score" name="score" tick={{ fontSize: 10.5 }} width={40} />
                    <ZAxis range={[40, 40]} />
                    <Tooltip content={<ChartTooltip />} />
                    <Scatter data={manifest.ml.anomaly.anomalies.slice(0, 200)} fill="#d4453d" />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            ) : null}
          </Panel>
        </div>

        {/* -------------------------------------------------- forecast */}
        <Panel
          id="sec-forecast"
          icon={TrendingUp}
          title="Forecast"
          subtitle="Recent history with projected values"
          action={
            forecastData && (
              <div className="flex items-center gap-3 text-[12.5px] text-ink-soft">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-4 bg-ink" /> actual
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-4 border-t-2 border-dashed border-teal" /> forecast
                </span>
              </div>
            )
          }
          footer={String((manifest?.forecast as { note?: string } | undefined)?.note ?? '')}
        >
          {!forecastData ? (
            <Empty text="Forecasting activates for datasets with a usable time column." />
          ) : (
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={forecastData} margin={{ top: 4, right: 12, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#6f467955" vertical={false} />
                <XAxis dataKey="t" tick={{ fontSize: 11 }} minTickGap={28} />
                <YAxis tickFormatter={compactNumber} tick={{ fontSize: 11 }} width={48} />
                <Tooltip content={<ChartTooltip />} />
                <Line type="monotone" dataKey="actual" stroke="#FA9D72" strokeWidth={2} dot={false} connectNulls />
                <Line type="monotone" dataKey="forecast" stroke="#2f8f83" strokeWidth={2} strokeDasharray="6 3" dot={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Panel>

        {/* ------------------------------------- numeric spread + notes */}
        <div className="grid gap-5 xl:grid-cols-2">
          <Panel
            icon={Banknote}
            title="Numeric spread"
            subtitle="Minimum to maximum per numeric column"
            footer={numericProfile.length ? 'Bars show the observed range; the tick marks the mean.' : undefined}
          >
            {!numericProfile.length ? (
              <Empty text="No numeric columns were detected in this file." />
            ) : (
              <div className="scroll-ink max-h-[300px] space-y-3 overflow-y-auto pr-1">
                {numericProfile.map((c) => {
                  const span = c.max - c.min || 1
                  const meanPct = ((c.mean - c.min) / span) * 100
                  return (
                    <div key={c.name}>
                      <div className="flex items-baseline justify-between gap-3 text-[12.5px]">
                        <span className="truncate font-medium">{c.name}</span>
                        <span className="shrink-0 tabular-nums text-ink-soft">
                          {compactNumber(c.min)} → {compactNumber(c.max)}
                        </span>
                      </div>
                      <div className="relative mt-1.5 h-2.5 overflow-hidden rounded-full bg-mist">
                        <div className="absolute inset-y-0 left-0 w-full bg-teal/30" />
                        <span
                          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-paper bg-ink"
                          style={{ left: `${Math.min(Math.max(meanPct, 0), 100)}%` }}
                          title={`mean ${c.mean}`}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Panel>

          <Panel
            id="sec-notes"
            icon={MessagesSquare}
            title="Messages"
            subtitle="Comment on this dataset without leaving the analysis"
            footer={
              <Link to={`/datasets/${dsid}`} className="font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4">
                See the full thread on the detail page
              </Link>
            }
          >
            <form
              className="flex flex-col gap-2 sm:flex-row"
              onSubmit={(e) => {
                e.preventDefault()
                if (msgDraft.trim()) postMessage.mutate(msgDraft.trim())
              }}
            >
              <input
                value={msgDraft}
                onChange={(e) => setMsgDraft(e.target.value)}
                placeholder="Write a message…"
                maxLength={2000}
                className="field flex-1"
              />
              <button type="submit" className="btn py-2.5 text-[14.5px]" disabled={postMessage.isPending || !msgDraft.trim()}>
                Send
              </button>
            </form>
            {msgError && <p className="mt-2 text-[13.5px] text-danger">{msgError}</p>}

            <div className="mt-5 border-t border-line/10 pt-4">
              <p className="text-[12.5px] font-medium text-ink-soft">Workspace activity</p>
              <ul className="mt-2.5 space-y-2 text-[13.5px]">
                {(overview?.latest_runs ?? []).slice(0, 3).map((r) => (
                  <li key={r.id} className="flex items-center gap-2">
                    <Activity size={13} className="text-ink-soft" aria-hidden />
                    <Link to={r.status === 'completed' ? `/run/${r.id}` : `/run/${r.id}/process`} className="font-mono text-[12px] underline decoration-lime decoration-2 underline-offset-4">
                      {r.id.slice(0, 8)}
                    </Link>
                    <span className="text-ink-soft">{r.status}</span>
                  </li>
                ))}
                {(overview?.upcoming ?? []).slice(0, 2).map((b) => (
                  <li key={b.id} className="flex items-center gap-2">
                    <CalendarCheck size={13} className="text-ink-soft" aria-hidden />
                    <b className="font-medium">{b.topic}</b>
                    <span className="text-ink-soft">· {formatWhen(b.scheduled_at)}</span>
                  </li>
                ))}
                <li className="flex items-center gap-2">
                  <FileSpreadsheet size={13} className="text-ink-soft" aria-hidden />
                  <Link to="/catalog" className="font-medium underline">
                    {datasets.length} datasets in your catalog
                  </Link>
                </li>
              </ul>
            </div>
          </Panel>
        </div>
      </div>
    </>
  )
}
