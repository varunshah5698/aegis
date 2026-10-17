import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BadgeHelp,
  Banknote,
  Bot,
  ChartColumn,
  CheckCircle2,
  ClipboardList,
  CloudRain,
  FileBarChart,
  GitBranch,
  Layers,
  ScrollText,
  SearchCheck,
  Table2,
  Workflow,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Manifest, RunStatus } from '../lib/types'
import OverviewPanel from '../components/panels/OverviewPanel'
import QualityPanel from '../components/panels/QualityPanel'
import ChartsPanel from '../components/panels/ChartsPanel'
import RelationshipsPanel from '../components/panels/RelationshipsPanel'
import MLPanel from '../components/panels/MLPanel'
import FinancialPanel from '../components/panels/FinancialPanel'
import NetworkPanel from '../components/panels/NetworkPanel'
import RecordsPanel from '../components/panels/RecordsPanel'
import ReportsPanel from '../components/panels/ReportsPanel'
import { AiChat, AiInsights, AiSection } from '../components/AiPanel'
import SchemaPanel from '../components/panels/SchemaPanel'

const MODULE_ICON: Record<string, React.ComponentType<{ size?: number }>> = {
  overview: Layers,
  quality: SearchCheck,
  exploration: ChartColumn,
  relationships: Activity,
  ml: ClipboardList,
  anomaly: CloudRain,
  financial: Banknote,
  network: GitBranch,
  currency: Banknote,
  payments: Workflow,
  reconciliation: ScrollText,
  forecast: ChartColumn,
  assistant: Bot,
  reports: FileBarChart,
  schema: Table2,
}

/**
 * Results workspace. The tab set is built from the backend manifest: only
 * modules the data actually supports are offered, and inactive ones are listed
 * with their missing prerequisites (spec #5.4, #14).
 */
export default function Workspace() {
  const { runId = '' } = useParams()
  const [tab, setTab] = useState('overview')

  const { data: status } = useQuery<RunStatus>({
    queryKey: ['run-status', runId],
    queryFn: () => api.get<RunStatus>(`/api/runs/${runId}/status`),
    enabled: !!runId,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return s === 'completed' || s === 'partial' || s === 'failed' ? false : 2000
    },
  })

  const running = status ? !['completed', 'partial'].includes(status.status) : false

  const { data: manifest, error, isPending } = useQuery<Manifest>({
    queryKey: ['manifest', runId],
    queryFn: () => api.get<Manifest>(`/api/runs/${runId}/manifest`),
    enabled: !!runId && !running,
    retry: false,
  })

  const activeModules = useMemo(
    () => (manifest?.modules ?? []).filter((m) => m.state === 'active'),
    [manifest],
  )
  const inactiveModules = useMemo(
    () => (manifest?.modules ?? []).filter((m) => m.state !== 'active'),
    [manifest],
  )

  // keep the active tab valid when the module set changes
  useEffect(() => {
    if (!activeModules.length) return
    if (!activeModules.some((m) => m.key === tab)) setTab('overview')
  }, [activeModules, tab])

  if (error instanceof ApiError && error.status === 409) {
    return <NotReady runId={runId} />
  }
  if (isPending || !manifest) {
    return (
      <div className="flex items-center gap-3 py-24">
        <span className="size-4 animate-spin rounded-full border-2 border-line border-t-transparent" />
        <span className="text-[16px] text-ink-soft">Loading workspace…</span>
      </div>
    )
  }

  const brand = manifest.brand

  return (
    <div>
      {/* ---------------------------------------------------------- header */}
      <Link to="/catalog" className="chip">
        <ArrowLeft size={15} aria-hidden />
        Datasets
      </Link>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <h1 className="truncate text-[36px] leading-tight font-medium tracking-[-0.03em] sm:text-[42px]">
            {brand?.name ?? 'Aegis'} <span className="marker">investigation</span>
          </h1>
          <p className="mt-2 text-[16px] break-all text-ink-soft">
            {manifest.filename} · {(manifest.overview.row_count as number)?.toLocaleString()} rows ·{' '}
            {(manifest.overview.column_count as number)} columns · analysis v
            {manifest.analysis_version} · dataset {manifest.dataset_version}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="chip bg-lime">
            quality {manifest.quality ? `${manifest.quality.score}/100` : '—'}
          </span>
          <span className="chip bg-mist">
            {(manifest.overview.missing_pct as number)}% missing
          </span>
          <span className="chip bg-mist">
            {activeModules.length}/{manifest.modules.length} modules
          </span>
        </div>
      </div>

      {/* global warnings (limitations + quality summary) */}
      {manifest.warnings.length > 0 && (
        <details className="mt-5 rounded-[14px] border border-amber bg-amber/10 px-5 py-3">
          <summary className="cursor-pointer text-[15px] font-medium">
            {manifest.warnings.length} warning{manifest.warnings.length === 1 ? '' : 's'} from
            this run
          </summary>
          <ul className="mt-3 list-disc space-y-1.5 pl-5 text-[14.5px] text-ink-soft">
            {manifest.warnings.slice(0, 12).map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}

      <div className="mt-8 grid gap-8 lg:grid-cols-[230px_1fr]">
        {/* --------------------------------------------------------- sidebar */}
        <nav aria-label="Analysis modules" className="lg:sticky lg:top-[104px] lg:self-start">
          <ul className="flex gap-2 overflow-x-auto pb-2 scroll-ink lg:flex-col lg:overflow-visible lg:pb-0">
            {activeModules.map((m) => {
              const Icon = MODULE_ICON[m.key] ?? Layers
              const on = tab === m.key
              return (
                <li key={m.key} className="shrink-0">
                  <button
                    type="button"
                    onClick={() => setTab(m.key)}
                    aria-current={on ? 'page' : undefined}
                    className={`flex w-full items-center gap-2.5 rounded-[14px] border border-line px-4 py-2.5 text-left text-[14.5px] font-medium whitespace-nowrap transition-colors ${
                      on ? 'bg-ink text-paper' : 'bg-paper hover:bg-mist'
                    }`}
                  >
                    <Icon size={16} />
                    {m.label}
                  </button>
                </li>
              )
            })}
          </ul>

          {inactiveModules.length > 0 && (
            <div className="mt-5 hidden rounded-[14px] border border-line/30 bg-mist p-4 lg:block">
              <p className="flex items-center gap-2 text-[13.5px] font-medium">
                <BadgeHelp size={14} aria-hidden />
                Not available for this file
              </p>
              <ul className="mt-3 space-y-3">
                {inactiveModules.map((m) => (
                  <li key={m.key} className="text-[12.5px] leading-relaxed text-ink-soft">
                    <span className="font-medium text-ink">{m.label}</span>
                    <br />
                    {m.reason || 'Prerequisite columns not detected.'}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </nav>

        {/* ---------------------------------------------------------- panels */}
        <section className="min-w-0">
          {/* AI briefing is present on every workspace tab, above the module */}
          <div className="mb-6">
            <AiInsights
              runId={runId}
              title="What this analysis says"
              subtitle="Grounded in the persisted results — the model narrates, it never computes"
            />
          </div>
          {tab === 'overview' && <OverviewPanel manifest={manifest} runId={runId} />}
          {tab === 'quality' && <QualityPanel manifest={manifest} runId={runId} />}
          {tab === 'schema' && <SchemaPanel manifest={manifest} runId={runId} />}
          {tab === 'exploration' && <ChartsPanel manifest={manifest} runId={runId} />}
          {tab === 'relationships' && <RelationshipsPanel manifest={manifest} runId={runId} />}
          {tab === 'ml' && <MLPanel manifest={manifest} runId={runId} />}
          {tab === 'anomaly' && <MLPanel manifest={manifest} focus="anomaly" runId={runId} />}
          {tab === 'forecast' && <ForecastPanel manifest={manifest} runId={runId} />}
          {(tab === 'financial' || tab === 'payments' || tab === 'currency' || tab === 'reconciliation') && (
            <FinancialPanel manifest={manifest} focus={tab} runId={runId} />
          )}
          {tab === 'network' && <NetworkPanel runId={runId} manifest={manifest} />}
          {tab === 'assistant' && <AiChat runId={runId} />}
          {tab === 'reports' && <ReportsPanel runId={runId} />}

          {/* records browser is always reachable */}
          <div className="mt-8">
            <RecordsPanel runId={runId} manifest={manifest} />
          </div>
        </section>
      </div>

      {/* inactive module summary for mobile */}
      {inactiveModules.length > 0 && (
        <div className="mt-8 rounded-[14px] border border-line/30 bg-mist p-5 lg:hidden">
          <p className="flex items-center gap-2 text-[14.5px] font-medium">
            <BadgeHelp size={15} aria-hidden />
            Modules not available for this dataset
          </p>
          <ul className="mt-3 space-y-2.5 text-[13.5px] text-ink-soft">
            {inactiveModules.map((m) => (
              <li key={m.key}>
                <b className="text-ink">{m.label}</b> — {m.reason || 'Prerequisites missing.'}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ForecastPanel({ manifest, runId }: { manifest: Manifest; runId?: string }) {
  const f = manifest.forecast ?? {}
  if (f.status !== 'completed') {
    return (
      <div className="panel p-5">
        <p className="flex items-center gap-2 font-medium">
          <AlertTriangle size={16} className="text-amber" aria-hidden />
          Forecasting unavailable
        </p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {String(f.reason ?? 'This dataset does not support forecasting.')}
        </p>
      </div>
    )
  }
  const history = (f.history as { t: string; actual: number }[]) ?? []
  const future = (f.future as { t: string; forecast: number }[]) ?? []
  const all = [
    ...history.map((h) => ({ t: h.t, value: h.actual, kind: 'actual' })),
    ...future.map((x) => ({ t: x.t, value: x.forecast, kind: 'forecast' })),
  ]
  return (
    <div className="space-y-6">
      {runId && <AiSection runId={runId} section="forecast" />}
    <div className="panel p-5">
      <h2 className="text-[22px] font-medium">
        Forecast: <span className="marker">{String(f.target)}</span>
      </h2>
      <p className="mt-1 text-[14.5px] text-ink-soft">{String(f.method)}</p>
      <dl className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['MAE', String(f.mae)],
          ['RMSE', String(f.rmse)],
          ['MAPE', `${f.mape_pct ?? '—'}%`],
          ['Backtest points', String(f.backtest_points)],
        ].map(([k, v]) => (
          <div key={k} className="rounded-[12px] border border-line/25 bg-mist px-3 py-2">
            <dt className="text-[12px] text-ink-soft">{k}</dt>
            <dd className="font-medium tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-5 space-y-1.5 text-[14.5px]">
        {all.slice(-14).map((p) => (
          <div key={`${p.kind}-${p.t}`} className="flex items-baseline justify-between border-b border-line/15 pb-1">
            <span className="tabular-nums text-ink-soft">{p.t}</span>
            <span className={`font-medium tabular-nums ${p.kind === 'forecast' ? 'text-teal' : ''}`}>
              {p.value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
              {p.kind === 'forecast' && <span className="ml-2 text-[12px] text-ink-soft">forecast</span>}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[13px] text-ink-soft">{String(f.note ?? '')}</p>
    </div>
    </div>
  )
}

function NotReady({ runId }: { runId: string }) {
  return (
    <div className="py-24 text-center">
      <CheckCircle2 size={34} className="mx-auto text-amber" aria-hidden />
      <h1 className="mt-4 text-[30px] font-medium">Analysis still running</h1>
      <p className="mt-2 text-ink-soft">Results appear once the pipeline finishes.</p>
      <Link to={`/run/${runId}/process`} className="btn mt-6">
        Watch progress
      </Link>
    </div>
  )
}
