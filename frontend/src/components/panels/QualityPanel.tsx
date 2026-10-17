import { useState } from 'react'
import { AlertTriangle, CheckCircle2 } from 'lucide-react'
import { AiSection } from '../AiPanel'
import type { Manifest, QualityReport } from '../../lib/types'

/** Data-quality workspace: missingness, duplicates, invalid data, outliers. */
export default function QualityPanel({ manifest, runId }: { manifest: Manifest; runId?: string }) {
  const q: QualityReport | null = manifest.quality
  const [view, setView] = useState<'missing' | 'duplicates' | 'invalid' | 'outliers'>('missing')

  if (!q) {
    return (
      <div className="panel p-5 text-[15px] text-ink-soft">
        Data-quality stage did not produce a report for this run.
      </div>
    )
  }

  const missing = q.missing.columns_with_missing ?? []
  const outliers = (q.outliers.columns ?? []) as {
    column: string
    outlier_count: number
    outlier_pct: number
    method: string
    upper_fence: number
    lower_fence: number
  }[]
  const dups = q.duplicates as Record<string, unknown>
  const invalid = q.invalid as Record<string, unknown>

  return (
    <div className="space-y-6">
      {runId && <AiSection runId={runId} section="quality" />}

      {/* ------------------------------------------------------ score card */}
      <div className="panel grid gap-6 p-6 sm:grid-cols-[220px_1fr]">
        <div className="flex flex-col items-center justify-center rounded-[24px] border border-line bg-lime/40 px-5 py-7 text-center">
          <p className="text-[52px] leading-none font-semibold tabular-nums">{q.score}</p>
          <p className="mt-1 text-[14px] text-ink-soft">out of 100 · grade {q.grade}</p>
          <span className="mt-3 chip bg-paper">
            {q.score >= 75 ? 'healthy' : q.score >= 50 ? 'needs attention' : 'clean before analysis'}
          </span>
        </div>
        <div>
          <ul className="space-y-2 text-[15px]">
            {q.summary.map((s, i) => (
              <li key={i} className="flex gap-2.5">
                <CheckCircle2 size={16} className="mt-1 shrink-0 text-teal" aria-hidden />
                {s}
              </li>
            ))}
          </ul>
          <p className="mt-4 border-t border-line/20 pt-3 text-[13px] leading-relaxed text-ink-soft">
            <span className="font-medium text-ink">Formula: </span>
            {q.formula}
          </p>
        </div>
      </div>

      {/* ------------------------------------------------- recommendations */}
      {q.recommendations.length > 0 && (
        <div className="panel p-5">
          <h3 className="text-[19px] font-medium">Recommended treatments</h3>
          <p className="mt-1 text-[14px] text-ink-soft">
            Nothing is applied automatically — the original upload stays immutable.
          </p>
          <ul className="mt-4 space-y-3">
            {q.recommendations.map((r, i) => (
              <li key={i} className="rounded-[14px] border border-line/30 bg-mist px-4 py-3">
                <p className="text-[15px] font-medium">{r.action}</p>
                <p className="mt-1 text-[14px] text-ink-soft">{r.reason}</p>
                {r.targets?.length > 0 && (
                  <p className="mt-2 flex flex-wrap gap-1.5">
                    {r.targets.slice(0, 8).map((t) => (
                      <span key={t} className="rounded-md bg-paper px-2 py-0.5 text-[12.5px] border border-line/25">
                        {t}
                      </span>
                    ))}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* -------------------------------------------------------- tabular */}
      <div className="panel p-5">
        <div className="flex flex-wrap gap-2" role="tablist">
          {(['missing', 'duplicates', 'invalid', 'outliers'] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={`rounded-[14px] border border-line px-4 py-2 text-[14.5px] font-medium capitalize ${
                view === v ? 'bg-ink text-paper' : 'bg-paper hover:bg-mist'
              }`}
            >
              {v}
            </button>
          ))}
        </div>

        <div className="mt-5">
          {view === 'missing' && (
            missing.length === 0 ? (
              <p className="text-[15px] text-ink-soft">No column contains missing values.</p>
            ) : (
              <>
                <p className="mb-3 text-[14.5px] text-ink-soft">
                  {missing.length} column(s) with missing values · total{' '}
                  {q.missing.total_missing_pct}% of cells
                  {q.missing.empty_rows > 0 && ` · ${q.missing.empty_rows} fully empty rows`}
                </p>
                <div className="scroll-ink overflow-x-auto">
                  <table className="table-grid">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Missing</th>
                        <th>Share</th>
                        <th>Distribution</th>
                      </tr>
                    </thead>
                    <tbody>
                      {missing.slice(0, 30).map((m) => (
                        <tr key={m.column}>
                          <td className="font-medium">{m.column}</td>
                          <td className="tabular-nums">{m.missing_count.toLocaleString()}</td>
                          <td className="tabular-nums">{m.missing_pct}%</td>
                          <td className="w-1/2">
                            <span className="block h-2.5 w-full overflow-hidden rounded-full border border-line/40 bg-mist">
                              <span
                                className="block h-full bg-ink"
                                style={{ width: `${Math.min(100, m.missing_pct)}%` }}
                              />
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )
          )}

          {view === 'duplicates' && (
            <dl className="grid gap-4 sm:grid-cols-2">
              <Card label="Exact duplicate rows" value={String(dups.exact_duplicate_rows ?? 0)}
                sub={`${dups.duplicate_pct ?? 0}% of rows`} />
              <div className="rounded-[14px] border border-line/30 p-4">
                <p className="text-[14.5px] font-medium">Duplicate identifiers</p>
                {Object.keys((dups.duplicate_identifiers ?? {}) as object).length === 0 ? (
                  <p className="mt-2 text-[14px] text-ink-soft">
                    No repeated identifier columns detected.
                  </p>
                ) : (
                  <ul className="mt-2 space-y-2 text-[14px]">
                    {Object.entries(dups.duplicate_identifiers as Record<string, {
                      duplicate_id_count: number
                      conflicting_payloads: number
                    }>).map(([col, info]) => (
                      <li key={col} className="border-b border-line/15 pb-2">
                        <span className="font-medium">{col}</span> — {info.duplicate_id_count}{' '}
                        repeated id(s), {info.conflicting_payloads} with conflicting payloads
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </dl>
          )}

          {view === 'invalid' && (
            <div className="space-y-4">
              <TextMap title="Unparseable timestamps" data={invalid.date_issues as Record<string, number>} />
              <TextMap title="Non-numeric values in numeric columns" data={invalid.numeric_issues as Record<string, number>} />
              {(invalid.lifecycle_conflicts as string[] | undefined)?.length ? (
                <div className="rounded-[14px] border border-danger bg-danger/8 px-4 py-3">
                  <p className="flex items-center gap-2 font-medium text-danger">
                    <AlertTriangle size={15} aria-hidden />
                    Lifecycle contradictions
                  </p>
                  <ul className="mt-2 list-disc pl-5 text-[14.5px] text-ink-soft">
                    {(invalid.lifecycle_conflicts as string[]).map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-[15px] text-ink-soft">No contradictory lifecycle records found.</p>
              )}
              {(invalid.invalid_columns as unknown[] | undefined)?.length ? (
                <div className="rounded-[14px] border border-line/30 px-4 py-3 text-[14.5px]">
                  <p className="font-medium">Format issues</p>
                  <ul className="mt-2 list-disc pl-5 text-ink-soft">
                    {(invalid.invalid_columns as { column: string; issue: string; count: number }[]).map(
                      (c) => (
                        <li key={c.column}>
                          {c.column}: {c.issue.replace(/_/g, ' ')} ({c.count} values)
                        </li>
                      ),
                    )}
                  </ul>
                </div>
              ) : null}
            </div>
          )}

          {view === 'outliers' && (
            <>
              <p className="mb-3 text-[14.5px] text-ink-soft">{String(q.outliers.note ?? '')}</p>
              {outliers.length === 0 ? (
                <p className="text-[15px] text-ink-soft">No statistical outliers at 3×IQR.</p>
              ) : (
                <div className="scroll-ink overflow-x-auto">
                  <table className="table-grid">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Flagged</th>
                        <th>Share</th>
                        <th>Lower fence</th>
                        <th>Upper fence</th>
                        <th>Method</th>
                      </tr>
                    </thead>
                    <tbody>
                      {outliers.map((o) => (
                        <tr key={o.column}>
                          <td className="font-medium">{o.column}</td>
                          <td className="tabular-nums">{o.outlier_count.toLocaleString()}</td>
                          <td className="tabular-nums">{o.outlier_pct}%</td>
                          <td className="tabular-nums">{o.lower_fence}</td>
                          <td className="tabular-nums">{o.upper_fence}</td>
                          <td className="text-[12.5px] text-ink-soft">{o.method}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-[14px] border border-line/30 p-4">
      <p className="text-[14.5px]">{label}</p>
      <p className="mt-1 text-[32px] leading-none font-medium tabular-nums">{value}</p>
      {sub && <p className="mt-1.5 text-[13px] text-ink-soft">{sub}</p>}
    </div>
  )
}

function TextMap({ title, data }: { title: string; data?: Record<string, number> }) {
  const entries = Object.entries(data ?? {})
  if (!entries.length) return null
  return (
    <div className="rounded-[14px] border border-line/30 px-4 py-3">
      <p className="font-medium">{title}</p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {entries.map(([k, v]) => (
          <li key={k} className="rounded-md border border-line/25 bg-mist px-2.5 py-1 text-[13.5px]">
            {k} <span className="tabular-nums text-ink-soft">({v})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
