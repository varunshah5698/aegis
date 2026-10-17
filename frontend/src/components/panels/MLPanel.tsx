import { useState } from 'react'
import { Brain, Target, TriangleAlert } from 'lucide-react'
import { AiSection } from '../AiPanel'
import type { Manifest } from '../../lib/types'

/** Supervised / unsupervised / anomaly results with metrics and explanations. */
export default function MLPanel({
  manifest,
  focus,
  runId,
}: {
  manifest: Manifest
  focus?: 'anomaly'
  runId?: string
}) {
  const aiSection = (
    runId ? <AiSection runId={runId} section={focus === 'anomaly' ? 'anomaly' : 'machine_learning'} /> : null
  )
  const ml = manifest.ml ?? {}
  const sup = ml.supervised
  const anomaly = ml.anomaly
  const clustering = ml.clustering as
    | {
        status: string
        reason?: string
        metrics?: Record<string, number | null>
        clusters?: { cluster: number; size: number; share_pct: number; profile: Record<string, { median: number; vs_overall: string }> }[]
        limitations?: string[]
      }
    | undefined

  const [showAllAnomalies, setShowAllAnomalies] = useState(false)

  if (focus === 'anomaly') {
    if (!anomaly || anomaly.status !== 'completed') {
      return (
        <Unavailable
          title="Anomaly detection unavailable"
          reason={anomaly?.reason ?? manifest.capabilities?.ml_anomaly?.reason ?? 'Not run.'}
        />
      )
    }
    const flagged = Number(anomaly.metrics.flagged ?? 0)
    const agree = anomaly.metrics.agreement_with_label as
      | { precision: number; recall: number; support_positive: number; note: string }
      | undefined
    const list = showAllAnomalies ? anomaly.anomalies : anomaly.anomalies.slice(0, 8)

    return (
      <div className="space-y-6">
        {aiSection}
        <div className="panel p-5">
          <h2 className="text-[26px] font-medium tracking-[-0.03em]">
            Unsupervised <span className="marker">anomaly detection</span>
          </h2>
          <p className="mt-1 text-[14.5px] text-ink-soft">
            {anomaly.method} · {anomaly.sample_size.toLocaleString()} rows scored ·{' '}
            {anomaly.duration_s}s
          </p>

          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Kpi label="Flagged rows" value={flagged.toLocaleString()} />
            <Kpi label="Share of rows" value={`${anomaly.metrics.flagged_pct}%`} />
            <Kpi label="Observed contamination" value={String(anomaly.metrics.contamination_observed)} />
            <Kpi label="Score p95" value={String(anomaly.metrics.score_p95)} />
          </div>

          {agree && (
            <div className="mt-5 rounded-[14px] border border-line/30 bg-mist px-4 py-3">
              <p className="text-[15px] font-medium">Agreement with synthetic ground truth</p>
              <div className="mt-2 grid grid-cols-3 gap-3 text-[14.5px]">
                <span>Precision: <b className="tabular-nums">{agree.precision}</b></span>
                <span>Recall: <b className="tabular-nums">{agree.recall}</b></span>
                <span>Positives: <b className="tabular-nums">{agree.support_positive}</b></span>
              </div>
              <p className="mt-1.5 text-[13px] text-ink-soft">{agree.note}</p>
            </div>
          )}

          <ul className="mt-5 space-y-2 border-t border-line/20 pt-4 text-[14px] text-ink-soft">
            {anomaly.limitations.map((l) => (
              <li key={l} className="flex gap-2.5">
                <TriangleAlert size={14} className="mt-1 shrink-0 text-amber" aria-hidden />
                {l}
              </li>
            ))}
          </ul>
        </div>

        <div className="panel p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-3">
            <h3 className="text-[19px] font-medium">Highest-scoring rows and why</h3>
            {anomaly.anomalies.length > 8 && (
              <button
                type="button"
                className="btn btn-ghost px-4 py-2 text-[14px]"
                onClick={() => setShowAllAnomalies((v) => !v)}
              >
                {showAllAnomalies ? 'Show top 8' : `Show all ${anomaly.anomalies.length}`}
              </button>
            )}
          </div>
          <ol className="mt-4 space-y-3">
            {list.map((a, i) => (
              <li key={`${a.row_index}-${i}`} className="rounded-[14px] border border-line/30 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <span className="text-[15px] font-medium">
                    Row {a.row_index}
                    {a.synthetic_label !== undefined && (
                      <span
                        className={`ml-2 rounded px-2 py-0.5 text-[11.5px] ${
                          a.synthetic_label === '1' ? 'bg-lime' : 'bg-mist'
                        }`}
                      >
                        label={a.synthetic_label}
                      </span>
                    )}
                  </span>
                  <span className="chip bg-mist text-[12.5px]">
                    score <b className="tabular-nums">{a.score}</b>
                  </span>
                </div>
                <ul className="mt-2 flex flex-wrap gap-2">
                  {a.reasons.map((r, j) => (
                    <li
                      key={j}
                      className="rounded-lg border border-line/25 bg-mist px-2.5 py-1 text-[13px]"
                    >
                      {r.feature} = <span className="tabular-nums">{String(r.value)}</span>
                      <span className="ml-1.5 text-ink-soft tabular-nums">
                        ({r.deviation_sigma}σ)
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-[12.5px] text-ink-soft">detected by {a.detected_by}</p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    )
  }

  // ---------------------------------------------------------- supervised --
  if (!sup || sup.status !== 'completed') {
    return (
      <div className="space-y-6">
        {aiSection}
        <Unavailable
          title="Supervised learning not run"
          reason={sup?.reason ?? manifest.capabilities?.ml_classification?.reason ?? 'No target column detected.'}
        />
        {clustering && clustering.status === 'completed' && (
          <Clusters card={clustering} />
        )}
        {anomaly && anomaly.status === 'completed' && (
          <div className="panel p-5">
            <p className="text-[15px]">
              Unsupervised anomaly detection did run:{' '}
              <b className="tabular-nums">{Number(anomaly.metrics.flagged ?? 0).toLocaleString()}</b>{' '}
              rows flagged — open the Anomaly module for evidence.
            </p>
          </div>
        )}
      </div>
    )
  }

  const m = sup.metrics
  const isClass = sup.task === 'classification'

  return (
    <div className="space-y-6">
      {aiSection}
      <div className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-[26px] font-medium tracking-[-0.03em]">
              <span className="marker">{sup.best_model}</span>{' '}
              {sup.task === 'classification' ? 'classifier' : 'regressor'}
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              target <b>{sup.target ?? '—'}</b> · {sup.split_strategy} · train{' '}
              {sup.train_size.toLocaleString()} / test {sup.test_size.toLocaleString()} ·{' '}
              {sup.duration_s}s
            </p>
          </div>
          <span className="chip bg-lime">
            <Target size={13} aria-hidden />
            {sup.task}
          </span>
        </div>

        {/* metrics */}
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {Object.entries(m).map(([k, v]) => (
            <div key={k} className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
              <p className="text-[12.5px] text-ink-soft">{k.replace(/_/g, ' ')}</p>
              <p className="text-[21px] font-medium tabular-nums">{formatMetric(v)}</p>
            </div>
          ))}
        </div>

        {/* baseline comparison */}
        <div className="mt-4 rounded-[14px] border border-line/30 px-4 py-3 text-[14.5px]">
          <span className="font-medium">Baseline: </span>
          {Object.entries(sup.baselines)
            .map(([k, v]) => `${k.replace(/_/g, ' ')} = ${v}`)
            .join(' · ')}
        </div>

        {/* confusion + per-class */}
        {isClass && sup.confusion?.length > 0 && (
          <div className="mt-6 grid gap-5 lg:grid-cols-2">
            <div>
              <h3 className="text-[17px] font-medium">Confusion matrix</h3>
              <div className="scroll-ink mt-3 overflow-x-auto">
                <table className="table-grid text-center">
                  <thead>
                    <tr>
                      <th className="text-left">actual ↓ / pred →</th>
                      {sup.confusion.map((_, j) => (
                        <th key={j}>{String(j)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sup.confusion.map((row, i) => (
                      <tr key={i}>
                        <td className="text-left font-medium">{String(i)}</td>
                        {row.map((v, j) => (
                          <td
                            key={j}
                            className={`tabular-nums ${i === j ? 'font-semibold' : ''}`}
                            style={{
                              background:
                                v > 0
                                  ? `rgba(185,255,102,${i === j ? 0.55 : 0.2})`
                                  : undefined,
                            }}
                          >
                            {v.toLocaleString()}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <h3 className="text-[17px] font-medium">Per-class metrics</h3>
              <div className="scroll-ink mt-3 overflow-x-auto">
                <table className="table-grid">
                  <thead>
                    <tr>
                      <th>Class</th>
                      <th>Precision</th>
                      <th>Recall</th>
                      <th>F1</th>
                      <th>Support</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sup.per_class.map((c) => (
                      <tr key={c.class}>
                        <td className="font-medium">{c.class}</td>
                        <td className="tabular-nums">{c.precision}</td>
                        <td className="tabular-nums">{c.recall}</td>
                        <td className="tabular-nums">{c.f1}</td>
                        <td className="tabular-nums">{c.support.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        <ul className="mt-5 space-y-2 border-t border-line/20 pt-4 text-[14px] text-ink-soft">
          {sup.limitations.map((l) => (
            <li key={l} className="flex gap-2.5">
              <TriangleAlert size={14} className="mt-1 shrink-0 text-amber" aria-hidden />
              {l}
            </li>
          ))}
        </ul>
      </div>

      {/* ----------------------------------------------- feature importance */}
      <div className="panel p-5">
        <h3 className="flex items-center gap-2 text-[19px] font-medium">
          <Brain size={17} aria-hidden />
          What the model relies on
        </h3>
        {sup.feature_importance.length === 0 ? (
          <p className="mt-3 text-[14.5px] text-ink-soft">
            This model does not expose native feature importances.
          </p>
        ) : (
          <ul className="mt-4 space-y-2.5">
            {sup.feature_importance.slice(0, 14).map((f, i) => {
              const max = sup.feature_importance[0]?.importance || 1
              return (
                <li key={f.feature}>
                  <div className="flex items-baseline justify-between gap-3 text-[14.5px]">
                    <span className="font-medium">
                      <span className="mr-2 text-ink-soft tabular-nums">{i + 1}.</span>
                      {f.feature}
                    </span>
                    <span className="tabular-nums">{f.importance}</span>
                  </div>
                  <span className="mt-1 block h-2 w-full overflow-hidden rounded-full border border-line/30 bg-mist">
                    <span
                      className="block h-full bg-ink"
                      style={{ width: `${(f.importance / max) * 100}%` }}
                    />
                  </span>
                </li>
              )
            })}
          </ul>
        )}
        <p className="mt-4 text-[13.5px] text-ink-soft">
          Feature importances reflect predictive association, not causation. Label columns were
          excluded from inputs:{' '}
          <b>{sup.excluded_features.join(', ') || 'no label column present'}</b>.
        </p>
      </div>

      {/* ------------------------------------------------------- candidates */}
      <div className="panel p-5">
        <h3 className="text-[19px] font-medium">Models tried</h3>
        <div className="scroll-ink mt-3 overflow-x-auto">
          <table className="table-grid">
            <thead>
              <tr>
                <th>Model</th>
                {Object.keys(sup.models_tried[0] ?? { metric: '' })
                  .filter((k) => k !== 'model' && k !== 'error')
                  .map((k) => (
                    <th key={k}>{k.replace(/_/g, ' ')}</th>
                  ))}
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {sup.models_tried.map((x, i) => (
                <tr key={`${x.model}-${i}`}>
                  <td className="font-medium">{String(x.model)}</td>
                  {Object.entries(x)
                    .filter(([k]) => k !== 'model' && k !== 'error')
                    .map(([, v]) => (
                      <td key={String(v)} className="tabular-nums">
                        {formatMetric(v)}
                      </td>
                    ))}
                  <td>
                    <span className={`chip text-[12px] ${x.error ? 'border-danger text-danger' : 'bg-lime'}`}>
                      {x.error ? 'failed' : x.model === sup.best_model ? 'selected' : 'ok'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {clustering && clustering.status === 'completed' && <Clusters card={clustering} />}
    </div>
  )
}

function Clusters({ card }: { card: NonNullable<Extract<Manifest['ml'], { clustering?: unknown }>['clustering']> }) {
  const c = card as {
    metrics?: Record<string, number | null>
    clusters?: { cluster: number; size: number; share_pct: number; profile: Record<string, { median: number; vs_overall: string }> }[]
    limitations?: string[]
  }
  return (
    <div className="panel p-5">
      <h3 className="text-[19px] font-medium">Segmentation (K-Means)</h3>
      <div className="mt-3 flex flex-wrap gap-2 text-[14px]">
        <span className="chip bg-mist">k = {c.metrics?.k ?? '—'}</span>
        <span className="chip bg-mist">silhouette {c.metrics?.silhouette ?? '—'}</span>
        <span className="chip bg-mist">inertia {c.metrics?.inertia ?? '—'}</span>
      </div>
      <div className="mt-5 grid gap-4 md:grid-cols-2">
        {(c.clusters ?? []).map((cl) => (
          <div key={cl.cluster} className="rounded-[14px] border border-line/30 p-4">
            <div className="flex items-center justify-between">
              <span className="text-[15.5px] font-medium">Cluster {cl.cluster}</span>
              <span className="chip bg-lime text-[12px]">{cl.share_pct}%</span>
            </div>
            <p className="mt-1 text-[13.5px] text-ink-soft">{cl.size.toLocaleString()} rows</p>
            <ul className="mt-3 space-y-1.5 text-[13.5px]">
              {Object.entries(cl.profile).slice(0, 6).map(([feat, s]) => (
                <li key={feat} className="flex justify-between gap-3 border-b border-line/15 pb-1">
                  <span className="truncate">{feat}</span>
                  <span className="tabular-nums">
                    {s.median} <span className="text-ink-soft">({s.vs_overall})</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <ul className="mt-4 space-y-1.5 border-t border-line/20 pt-3 text-[13.5px] text-ink-soft">
        {(c.limitations ?? []).map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[14px] border border-line/30 bg-mist px-3.5 py-3">
      <p className="text-[12.5px] text-ink-soft">{label}</p>
      <p className="text-[21px] font-medium tabular-nums">{value}</p>
    </div>
  )
}

function Unavailable({ title, reason }: { title: string; reason: string }) {
  return (
    <div className="panel p-5">
      <h2 className="flex items-center gap-2 text-[20px] font-medium">
        <Brain size={18} className="text-ink-soft" aria-hidden />
        {title}
      </h2>
      <p className="mt-2 text-[15px] text-ink-soft">{reason}</p>
    </div>
  )
}

function formatMetric(v: unknown): string {
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return v.toLocaleString()
    return v.toFixed(Math.abs(v) < 1 ? 4 : 2)
  }
  return String(v ?? '—')
}
