import { Info } from 'lucide-react'
import { AiSection } from '../AiPanel'
import type { Manifest } from '../../lib/types'

/** Correlation matrix, strongest pairs, categorical association, mutual info. */
export default function RelationshipsPanel({ manifest, runId }: { manifest: Manifest; runId?: string }) {
  const rel = manifest.relationships
  if (!rel || (rel.labels?.length ?? 0) < 2) {
    return (
      <div className="panel p-5">
        <p className="font-medium">Relationship analysis unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">
          {manifest.capabilities?.relationships?.reason ??
            'At least two non-identifier numeric columns are required.'}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {runId && <AiSection runId={runId} section="relationships" />}

      {/* ----------------------------------------------- strongest pairs */}
      <div className="panel p-5">
        <h2 className="text-[24px] font-medium tracking-[-0.03em]">
          Strongest <span className="marker">relationships</span>
        </h2>
        <p className="mt-1 text-[14.5px] text-ink-soft">{rel.note}</p>

        {rel.strong_pairs.length === 0 ? (
          <p className="mt-4 text-[15px] text-ink-soft">
            No pair reached |r| ≥ 0.3 — the numeric columns move independently.
          </p>
        ) : (
          <div className="scroll-ink mt-5 overflow-x-auto">
            <table className="table-grid">
              <thead>
                <tr>
                  <th>Column A</th>
                  <th>Column B</th>
                  <th>Pearson</th>
                  <th>Spearman</th>
                  <th>Strength</th>
                </tr>
              </thead>
              <tbody>
                {rel.strong_pairs.map((p, i) => (
                  <tr key={`${p.a}-${p.b}-${i}`}>
                    <td className="font-medium">{p.a}</td>
                    <td className="font-medium">{p.b}</td>
                    <td className="tabular-nums">
                      <RBar value={p.pearson} />
                    </td>
                    <td className="tabular-nums">{p.spearman ?? '—'}</td>
                    <td className="text-[13px]">{p.strength}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* ------------------------------------- categorical associations */}
        <div className="panel p-5">
          <h3 className="text-[19px] font-medium">Categorical association (Cramér's V)</h3>
          {rel.categorical_associations.length === 0 ? (
            <p className="mt-3 text-[14.5px] text-ink-soft">
              No categorical pair reached V ≥ 0.3.
            </p>
          ) : (
            <ul className="mt-4 space-y-2.5 text-[14.5px]">
              {rel.categorical_associations.map((p, i) => (
                <li
                  key={`${p.a}-${p.b}-${i}`}
                  className="flex items-center justify-between gap-3 border-b border-line/15 pb-2"
                >
                  <span>
                    {p.a} <span className="text-ink-soft">×</span> {p.b}
                  </span>
                  <span className="tabular-nums font-medium">{p.cramers_v}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ------------------------------------------ mutual information */}
        <div className="panel p-5">
          <h3 className="text-[19px] font-medium">Mutual information</h3>
          <p className="mt-1 text-[13.5px] text-ink-soft">
            10-bin discretization against the first low-cardinality categorical column.
          </p>
          {rel.mutual_information.length === 0 ? (
            <p className="mt-3 text-[14.5px] text-ink-soft">Not computable for this dataset.</p>
          ) : (
            <ul className="mt-4 space-y-2.5 text-[14.5px]">
              {rel.mutual_information.map((m, i) => (
                <li key={`${m.feature}-${i}`} className="border-b border-line/15 pb-2">
                  <div className="flex items-center justify-between gap-3">
                    <span>{m.feature}</span>
                    <span className="tabular-nums font-medium">{m.mutual_information}</span>
                  </div>
                  <span className="text-[12.5px] text-ink-soft">vs {m.target}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* ---------------------------------------------- correlation matrix */}
      <div className="panel p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h3 className="text-[19px] font-medium">Pearson correlation matrix</h3>
          <span className="flex items-center gap-1.5 text-[13px] text-ink-soft">
            <Info size={13} aria-hidden />
            {rel.labels.length} numeric columns
          </span>
        </div>
        <div className="scroll-ink mt-4 overflow-x-auto">
          <table className="table-grid">
            <thead>
              <tr>
                <th></th>
                {rel.labels.map((l) => (
                  <th key={l} className="max-w-[110px] truncate" title={l}>
                    {l}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rel.labels.map((row, i) => (
                <tr key={row}>
                  <td className="font-medium">{row}</td>
                  {rel.labels.map((col, j) => {
                    const v = rel.pearson[i]?.[j]
                    const defined = v !== null && v !== undefined && Number.isFinite(v)
                    return (
                      <td
                        key={col}
                        className="text-center tabular-nums"
                        style={{
                          background: defined ? heat(v) : undefined,
                          color: defined && Math.abs(v) > 0.6 ? '#fff' : undefined,
                        }}
                        title={defined ? `${row} × ${col} = ${v.toFixed(3)}` : 'not computed'}
                      >
                        {defined ? v.toFixed(2) : '·'}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function heat(v: number) {
  if (v >= 0) return `rgba(47,143,131,${0.12 + v * 0.88})`
  return `rgba(212,69,61,${0.12 + -v * 0.88})`
}

function RBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.abs(value) * 100)
  const positive = value >= 0
  return (
    <span className="flex items-center gap-2">
      <span className="block h-2 w-20 overflow-hidden rounded-full border border-line/40 bg-mist">
        <span
          className={`block h-full ${positive ? 'bg-teal' : 'bg-danger'}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      {value.toFixed(3)}
    </span>
  )
}
