import { AlertTriangle, Banknote, Info, Workflow } from 'lucide-react'
import { AiSection } from '../AiPanel'
import { SeverityChip } from './OverviewPanel'
import type { Finding, Manifest, PatternResult } from '../../lib/types'

/**
 * Financial intelligence: transaction summary, explainable pattern findings,
 * currency analytics, payment performance and reconciliation. Every number
 * states its calculation policy; every finding states method + thresholds.
 */
export default function FinancialPanel({
  manifest,
  focus,
  runId,
}: {
  manifest: Manifest
  focus: 'financial' | 'payments' | 'currency' | 'reconciliation'
  runId?: string
}) {
  const fin = manifest.financial
  const mods = fin?.modules ?? {}

  if (!fin?.activated) {
    return (
      <div className="panel p-5">
        <p className="font-medium">Financial module not activated</p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {manifest.capabilities?.transaction_summary?.reason ??
            'No transaction-like columns were detected in this file.'}
        </p>
      </div>
    )
  }

  // every financial sub-tab gets an AI reading of the same computed module
  const body =
    focus === 'payments' ? (
      <PaymentsPanel mods={mods} manifest={manifest} />
    ) : focus === 'currency' ? (
      <CurrencyPanel manifest={manifest} mods={mods} />
    ) : focus === 'reconciliation' ? (
      <ReconciliationPanel mods={mods} />
    ) : (
      <SummaryAndPatterns mods={mods} manifest={manifest} />
    )

  return (
    <div className="space-y-6">
      {runId && <AiSection runId={runId} section="financial" />}
      {body}
    </div>
  )
}

/* ==================================================== summary + patterns == */
function SummaryAndPatterns({
  mods,
  manifest,
}: {
  mods: Manifest['financial']['modules']
  manifest: Manifest
}) {
  const summary = mods.summary as
    | {
        status: string
        reason?: string
        metrics: Record<string, string | number | boolean | null>
        calc_policy: string[]
        warnings: string[]
        status_breakdown: { status: string; count: number; pct: number }[]
        volume_by_channel: { channel: string; count: number; volume: number; completed?: number }[]
        volume_by_time: { t: string; count: number; value: number }[]
      }
    | undefined

  if (!summary || summary.status !== 'completed') {
    return (
      <div className="panel p-5">
        <p className="font-medium">Transaction summary unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {summary?.reason ?? 'No amount column detected.'}
        </p>
      </div>
    )
  }

  const m = summary.metrics
  const patterns: PatternResult | undefined = mods.patterns as PatternResult | undefined

  const kpis: [string, string, string?][] = [
    ['Rows', num(m.row_count).toLocaleString()],
    ['Completed', num(m.completed_count).toLocaleString()],
    ['Failed', num(m.failed_count).toLocaleString()],
    ['Pending', num(m.pending_count).toLocaleString()],
    ['Completed volume*', num(m.total_volume_completed).toLocaleString()],
    ['Median amount', String(m.median_amount_completed ?? '—')],
    ['Largest', String(m.largest_transaction ?? '—')],
    ['Failure rate', `${m.failure_rate_pct}%`],
    ['Reversals', num(m.reversal_count).toLocaleString()],
    ['Refunds', num(m.refund_count).toLocaleString()],
    ['Source accounts', m.distinct_source_accounts ? num(m.distinct_source_accounts).toLocaleString() : '—'],
    ['Destination accounts', m.distinct_destination_accounts ? num(m.distinct_destination_accounts).toLocaleString() : '—'],
  ]

  return (
    <div className="space-y-6">
      <div className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-[26px] font-medium tracking-[-0.03em]">
              Transaction <span className="marker">intelligence</span>
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              amount column <b>{String(m.amount_column)}</b>
              {m.status_column ? (
                <>
                  {' '}· status column <b>{String(m.status_column)}</b>
                </>
              ) : null}
            </p>
          </div>
          <span className="chip bg-lime">
            <Banknote size={13} aria-hidden />
            {summary.warnings?.length ? 'native-currency totals' : 'single currency'}
          </span>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {kpis.map(([label, value]) => (
            <div key={label} className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
              <p className="text-[12.5px] text-ink-soft">{label}</p>
              <p className="text-[20px] font-medium tabular-nums">{value}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[13px] text-ink-soft">
          * Completed volume sums native amounts
          {m.amount_sums_are_native_currency_only ? (
            <b className="text-danger"> across multiple currencies — use the per-currency
              breakdown in the Currency module for real totals</b>
          ) : null}.
        </p>

        {summary.warnings.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {summary.warnings.map((w) => (
              <li key={w} className="flex gap-2 text-[14px] text-amber">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden />
                {w}
              </li>
            ))}
          </ul>
        )}

        <details className="mt-4 rounded-[14px] border border-line/30 px-4 py-3">
          <summary className="cursor-pointer text-[14.5px] font-medium">
            Calculation policy ({summary.calc_policy.length} rules)
          </summary>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-[14px] text-ink-soft">
            {summary.calc_policy.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ol>
        </details>

        {summary.status_breakdown?.length > 0 && (
          <div className="mt-5">
            <h3 className="text-[17px] font-medium">Status distribution</h3>
            <ul className="mt-3 space-y-2">
              {summary.status_breakdown.map((s) => (
                <li key={s.status} className="flex items-center gap-3 text-[14.5px]">
                  <span className="w-28 shrink-0 font-medium">{s.status}</span>
                  <span className="h-3 flex-1 overflow-hidden rounded-full border border-line/30 bg-mist">
                    <span className="block h-full bg-ink" style={{ width: `${Math.min(100, s.pct)}%` }} />
                  </span>
                  <span className="w-32 shrink-0 text-right tabular-nums text-ink-soft">
                    {s.count.toLocaleString()} ({s.pct}%)
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {summary.volume_by_channel?.length > 0 && (
          <div className="mt-6">
            <h3 className="text-[17px] font-medium">Volume by channel</h3>
            <div className="scroll-ink mt-3 overflow-x-auto">
              <table className="table-grid">
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>Transactions</th>
                    <th>Native volume</th>
                    <th>Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.volume_by_channel.map((c) => (
                    <tr key={c.channel}>
                      <td className="font-medium">{c.channel}</td>
                      <td className="tabular-nums">{c.count.toLocaleString()}</td>
                      <td className="tabular-nums">{Number(c.volume).toLocaleString()}</td>
                      <td className="tabular-nums">{c.completed?.toLocaleString?.() ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------ patterns */}
      <div className="panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-[24px] font-medium">
            Potential anomalies <span className="marker">requiring review</span>
          </h2>
          <span className="chip bg-mist">{patterns?.total ?? 0} findings</span>
        </div>

        {patterns && patterns.findings.length > 0 ? (
          <>
            <p className="mt-3 rounded-[14px] border border-amber bg-amber/10 px-4 py-3 text-[14px]">
              {patterns.disclaimer}
            </p>
            <ol className="mt-5 space-y-4">
              {patterns.findings.slice(0, 20).map((f, i) => (
                <li key={`${f.kind}-${f.entity}-${i}`} className="rounded-[16px] border border-line/35 p-4">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="chip bg-mist text-[11.5px]">{f.kind.replace(/_/g, ' ')}</span>
                    <SeverityChip severity={f.severity} />
                    <span className="chip text-[11.5px]">confidence: {f.confidence}</span>
                  </div>
                  <h3 className="mt-2.5 text-[17px] font-medium">{f.title}</h3>
                  <p className="mt-1.5 text-[14.5px] leading-relaxed text-ink-soft">{f.evidence}</p>

                  <div className="mt-3 grid gap-3 text-[13.5px] md:grid-cols-2">
                    <Block label="Method" value={f.method} />
                    <Block
                      label="Thresholds"
                      value={Object.entries(f.thresholds)
                        .map(([k, v]) => `${k} = ${String(v)}`)
                        .join(' · ') || 'data-derived'}
                    />
                    <Block label="Suggested next step" value={f.next_steps} />
                    <Block label="Known false-positive risk" value={f.false_positive_note} />
                  </div>

                  {f.examples?.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {f.examples.slice(0, 5).map((ex, j) => (
                        <span key={j} className="rounded-lg border border-line/25 bg-mist px-2.5 py-1 text-[12.5px]">
                          {Object.entries(ex)
                            .map(([k, v]) => `${k}: ${String(v)}`)
                            .join(' · ')}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ol>

            <details className="mt-5 rounded-[14px] border border-line/30 px-4 py-3">
              <summary className="cursor-pointer text-[14.5px] font-medium">
                Detection methodology ({Object.keys(patterns.methodology).length} detectors)
              </summary>
              <dl className="mt-3 space-y-2.5 text-[14px]">
                {Object.entries(patterns.methodology).map(([k, v]) => (
                  <div key={k}>
                    <dt className="font-medium">{k.replace(/_/g, ' ')}</dt>
                    <dd className="text-ink-soft">{v}</dd>
                  </div>
                ))}
              </dl>
            </details>
          </>
        ) : (
          <p className="mt-4 text-[15px] text-ink-soft">
            No rule or statistical detector crossed its threshold on this dataset. That is a
            result, not an error — thresholds are data-derived.
          </p>
        )}
      </div>

      {/* top flows snapshot */}
      {(mods.network as { status?: string; edges?: unknown[] })?.status === 'completed' && (
        <div className="rounded-[14px] border border-line/30 px-5 py-4 text-[14.5px]">
          <Info size={14} className="mr-1.5 inline" aria-hidden />
          A directed transfer network with {String((mods.network as { node_count: number }).node_count)}{' '}
          entities is available in the <b>Transfer network</b> module.{' '}
          {manifest.modules.find((x) => x.key === 'network')?.state === 'active' ? '' : 'It was skipped for this run.'}
        </div>
      )}
    </div>
  )
}

/* ============================================================= payments == */
function PaymentsPanel({
  mods,
  manifest,
}: {
  mods: Manifest['financial']['modules']
  manifest: Manifest
}) {
  const perf = mods.performance as
    | {
        status: string
        reason?: string
        rates?: Record<string, number | string>
        processing?: Record<string, number | string>
        settlement?: Record<string, number | string>
        by_channel?: { channel: string; total: number; success_pct: number; failure_pct: number }[]
      }
    | undefined
  const cap = manifest.capabilities?.payments

  if (!perf || perf.status !== 'completed') {
    return (
      <div className="panel p-5">
        <p className="flex items-center gap-2 font-medium">
          <Workflow size={17} aria-hidden />
          Payment performance unavailable
        </p>
        <p className="mt-1 text-[15px] text-ink-soft">{perf?.reason ?? cap?.reason}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="panel p-5">
        <h2 className="text-[24px] font-medium">
          Payment <span className="marker">performance</span>
        </h2>
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(perf.rates ?? {}).map(([k, v]) => (
            <div key={k} className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
              <p className="text-[12.5px] text-ink-soft">{k.replace(/_/g, ' ')}</p>
              <p className="text-[20px] font-medium tabular-nums">{String(v)}</p>
            </div>
          ))}
        </div>
        <p className="mt-3 text-[13.5px] text-ink-soft">
          Denominator: {String(perf.rates?.denominator ?? 'all rows')} — failed and pending rows
          are never counted as completed monetary movement.
        </p>

        {['processing', 'settlement'].map((key) => {
          const d = perf[key as 'processing' | 'settlement']
          if (!d) return null
          return (
            <div key={key} className="mt-5 rounded-[14px] border border-line/30 px-4 py-3">
              <p className="text-[15px] font-medium capitalize">{key} duration</p>
              <p className="mt-1 text-[14px] text-ink-soft">column: {String(d.column)}</p>
              <div className="mt-2 grid grid-cols-2 gap-3 text-[14.5px] sm:grid-cols-4">
                <span>mean <b className="tabular-nums">{String(d.mean_seconds)}s</b></span>
                <span>median <b className="tabular-nums">{String(d.median_seconds)}s</b></span>
                <span>p95 <b className="tabular-nums">{String(d.p95_seconds)}s</b></span>
                <span>max <b className="tabular-nums">{String(d.max_seconds)}s</b></span>
              </div>
            </div>
          )
        })}

        {perf.by_channel?.length ? (
          <div className="mt-6">
            <h3 className="text-[17px] font-medium">Channel comparison</h3>
            <div className="scroll-ink mt-3 overflow-x-auto">
              <table className="table-grid">
                <thead>
                  <tr>
                    <th>Channel</th>
                    <th>Transactions</th>
                    <th>Success</th>
                    <th>Failure</th>
                  </tr>
                </thead>
                <tbody>
                  {perf.by_channel.map((c) => (
                    <tr key={c.channel}>
                      <td className="font-medium">{c.channel}</td>
                      <td className="tabular-nums">{c.total.toLocaleString()}</td>
                      <td className="tabular-nums">{c.success_pct}%</td>
                      <td className="tabular-nums text-danger">{c.failure_pct}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}

/* ============================================================= currency == */
function CurrencyPanel({
  manifest,
  mods,
}: {
  manifest: Manifest
  mods: Manifest['financial']['modules']
}) {
  const cur = mods.currency as
    | {
        status: string
        reason?: string
        native_totals: { currency: string; count: number; native_total: number | null }[]
        rate_stats: Record<string, string | number | null>
        conversion_check?: {
          compared_rows: number
          rows_over_1pct_error: number
          error_rate_pct: number
          formula: string
        }
        rate_series?: { t: string; rate: number }[]
        warnings: string[]
        methodology: string[]
      }
    | undefined

  if (!cur || cur.status !== 'completed') {
    return (
      <div className="panel p-5">
        <p className="font-medium">Currency analytics unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {cur?.reason ?? manifest.capabilities?.currency?.reason}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="panel p-5">
        <h2 className="text-[24px] font-medium">
          Currency <span className="marker">analytics</span>
        </h2>
        <p className="mt-4 text-[15px] font-medium">Native-currency totals</p>
        <p className="text-[13.5px] text-ink-soft">
          Amounts are grouped by currency and never summed together.
        </p>
        <div className="scroll-ink mt-3 overflow-x-auto">
          <table className="table-grid">
            <thead>
              <tr>
                <th>Currency</th>
                <th>Rows</th>
                <th>Native total</th>
              </tr>
            </thead>
            <tbody>
              {cur.native_totals.map((t) => (
                <tr key={t.currency}>
                  <td className="font-medium">{t.currency}</td>
                  <td className="tabular-nums">{t.count.toLocaleString()}</td>
                  <td className="tabular-nums">
                    {t.native_total === null ? '—' : Number(t.native_total).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {Object.keys(cur.rate_stats).length > 0 && (
          <div className="mt-6">
            <p className="text-[15px] font-medium">Historical rates embedded in this file</p>
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['Observations', String(cur.rate_stats.observations ?? '—')],
                ['Min', String(cur.rate_stats.min ?? '—')],
                ['Max', String(cur.rate_stats.max ?? '—')],
                ['Volatility', `${cur.rate_stats.volatility_pct ?? '—'}%`],
              ].map(([k, v]) => (
                <div key={k} className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
                  <p className="text-[12.5px] text-ink-soft">{k}</p>
                  <p className="text-[19px] font-medium tabular-nums">{v}</p>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[13.5px] text-ink-soft">
              {String(cur.rate_stats.coverage ?? '')} · bucket {String(cur.rate_stats.bucket ?? '—')}
            </p>
          </div>
        )}

        {cur.conversion_check && (
          <div className="mt-5 rounded-[14px] border border-line/30 px-4 py-3 text-[14.5px]">
            <p className="font-medium">Conversion consistency</p>
            <p className="mt-1 text-ink-soft">{cur.conversion_check.formula}</p>
            <p className="mt-1.5">
              <b className="tabular-nums">{cur.conversion_check.rows_over_1pct_error.toLocaleString()}</b>{' '}
              of {cur.conversion_check.compared_rows.toLocaleString()} rows differ by &gt;1% (
              {cur.conversion_check.error_rate_pct}%).
            </p>
          </div>
        )}

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="rounded-[14px] border border-amber bg-amber/10 px-4 py-3">
            <p className="text-[14.5px] font-medium">Warnings</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[14px] text-ink-soft">
              {cur.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
              <li>No live exchange-rate provider is configured for this deployment.</li>
            </ul>
          </div>
          <div className="rounded-[14px] border border-line/30 px-4 py-3">
            <p className="text-[14.5px] font-medium">Methodology</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-[14px] text-ink-soft">
              {cur.methodology.map((x) => (
                <li key={x}>{x}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ========================================================= reconciliation = */
function ReconciliationPanel({ mods }: { mods: Manifest['financial']['modules'] }) {
  const rec = mods.reconciliation as
    | {
        status: string
        reason?: string
        columns?: string[]
        status_breakdown?: { status: string; count: number; pct: number }[]
        comparison?: Record<string, number>
        difference_stats?: Record<string, number>
      }
    | undefined

  if (!rec || rec.status !== 'completed') {
    return (
      <div className="panel p-5">
        <p className="font-medium">Reconciliation unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {rec?.reason ??
            'This analysis requires additional fields — FinSentry does not manufacture reconciliation results.'}
        </p>
      </div>
    )
  }

  return (
    <div className="panel p-5">
      <h2 className="text-[24px] font-medium">
        Reconciliation <span className="marker">status</span>
      </h2>
      <p className="mt-2 text-[14.5px] text-ink-soft">
        Columns examined: {rec.columns?.join(', ')}
      </p>

      {rec.status_breakdown && (
        <div className="mt-5">
          <h3 className="text-[17px] font-medium">Reconciliation status distribution</h3>
          <ul className="mt-3 space-y-2">
            {rec.status_breakdown.map((s) => (
              <li key={s.status} className="flex items-center gap-3 text-[14.5px]">
                <span className="w-44 shrink-0 font-medium">{s.status}</span>
                <span className="h-3 flex-1 overflow-hidden rounded-full border border-line/30 bg-mist">
                  <span className="block h-full bg-ink" style={{ width: `${Math.min(100, s.pct)}%` }} />
                </span>
                <span className="w-28 shrink-0 text-right tabular-nums text-ink-soft">
                  {s.count.toLocaleString()} ({s.pct}%)
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {rec.comparison && (
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Object.entries(rec.comparison).map(([k, v]) => (
            <div key={k} className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
              <p className="text-[12.5px] text-ink-soft">{k.replace(/_/g, ' ')}</p>
              <p className="text-[19px] font-medium tabular-nums">
                {typeof v === 'number' ? v.toLocaleString() : String(v)}
              </p>
            </div>
          ))}
        </div>
      )}

      {rec.difference_stats && (
        <div className="mt-4 rounded-[14px] border border-line/30 px-4 py-3 text-[14.5px]">
          <p className="font-medium">Reconciliation difference amounts</p>
          <p className="mt-1 text-ink-soft">
            {rec.difference_stats.non_zero.toLocaleString()} non-zero of{' '}
            {rec.difference_stats.count.toLocaleString()} · sum{' '}
            <b className="tabular-nums">{rec.difference_stats.sum.toLocaleString()}</b> · max{' '}
            <b className="tabular-nums">{rec.difference_stats.max.toLocaleString()}</b>
          </p>
        </div>
      )}
    </div>
  )
}

/* -------------------------------------------------------------- helpers -- */
function Block({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div className="rounded-[12px] border border-line/20 bg-mist px-3 py-2">
      <p className="text-[12px] text-ink-soft">{label}</p>
      <p className="mt-0.5 leading-snug">{value}</p>
    </div>
  )
}

function num(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

export type { Finding }
