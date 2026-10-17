import { useMemo, useState } from 'react'
import { ChartColumn, Filter, Sparkles } from 'lucide-react'
import Chart from '../Charts'
import { AiChartNarrate, AiSection } from '../AiPanel'
import type { ChartSpec, Manifest } from '../../lib/types'

/**
 * Ranked gallery of the charts the backend generated. Sorting by relevance
 * keeps the dashboard useful on files with many columns (spec #8.4: rank
 * visualizations by relevance, don't dump dozens of redundant charts).
 */
export default function ChartsPanel({ manifest, runId }: { manifest: Manifest; runId?: string }) {
  const charts: ChartSpec[] = manifest.charts ?? []
  const [limit, setLimit] = useState(9)

  const sorted = useMemo(
    () => [...charts].sort((a, b) => b.relevance - a.relevance),
    [charts],
  )
  const shown = sorted.slice(0, limit)

  if (!charts.length) {
    return (
      <div className="panel flex flex-col items-center gap-3 px-6 py-14 text-center">
        <ChartColumn size={30} className="text-ink-soft" aria-hidden />
        <p className="text-[17px] font-medium">No charts for this dataset</p>
        <p className="max-w-[46ch] text-[15px] text-ink-soft">
          The visualization stage needs numeric, categorical or temporal columns — this file
          did not provide enough usable data.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-[28px] font-medium tracking-[-0.03em]">
            Generated <span className="marker">visualizations</span>
          </h2>
          <p className="mt-1 text-[14.5px] text-ink-soft">
            {charts.length} chart(s), ranked by relevance — every value is computed from your
            uploaded rows.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="chip bg-mist">
            <Filter size={13} aria-hidden />
            showing {shown.length}/{charts.length}
          </span>
          {shown.length < charts.length && (
            <button type="button" className="btn px-4 py-2 text-[14px]" onClick={() => setLimit((n) => n + 9)}>
              Show more
            </button>
          )}
        </div>
      </div>

      {runId && <AiSection runId={runId} section="exploration" label="Explain the chart set" />}

      <div className="grid gap-5 xl:grid-cols-2">
        {shown.map((c) => (
          <div key={c.id} className="panel p-4">
            <Chart spec={c} />
            {runId && (
              <div className="mt-3 border-t border-line/10 pt-1">
                <AiChartNarrate runId={runId} chartId={c.id} />
              </div>
            )}
          </div>
        ))}
      </div>

      {runId && (
        <p className="flex items-center gap-1.5 text-[12.5px] text-ink-soft">
          <Sparkles size={12} aria-hidden />
          “Explain this chart” sends that chart's computed points to the model and returns a
          reading — it never recomputes the values.
        </p>
      )}
    </div>
  )
}
