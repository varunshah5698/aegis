import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Sparkles } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { DatasetOut, Manifest } from '../lib/types'
import { Empty, PageHeader } from '../components/ui'
import {
  ActivityTimeline,
  FlowNetwork,
  KpiCards,
  ModelPerformance,
  QualityGauge,
  RiskHeatmap,
} from '../components/insights/InsightComponents'

/**
 * Graphical overview of the most recent finished analysis. Every chart and
 * number comes from the persisted run manifest, nothing is fabricated.
 */
export default function Insights() {
  const { data: datasets, isPending } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })

  const latestRun = useMemo(() => {
    for (const d of datasets ?? []) {
      const run = (d.runs ?? []).find((r) => r.status === 'completed' || r.status === 'partial')
      if (run) return { dataset: d, runId: run.id }
    }
    return null
  }, [datasets])

  const { data: manifest, error, isPending: manifestPending } = useQuery<Manifest>({
    queryKey: ['manifest', latestRun?.runId],
    queryFn: () => api.get<Manifest>(`/api/runs/${latestRun?.runId}/manifest`),
    enabled: !!latestRun,
    retry: false,
  })

  if (isPending) return <p className="py-24 text-center text-ink-soft">Loading insights…</p>

  if (!latestRun) {
    return (
      <>
        <PageHeader eyebrow="Insights" title="Graphical analysis" description="Charts appear here after a dataset finishes an analysis run." />
        <Empty
          text="No finished analysis yet. Upload a CSV and run an analysis to populate these views."
          action={
            <Link to="/upload" className="btn mt-2">
              Upload a dataset <ArrowRight size={15} aria-hidden />
            </Link>
          }
        />
      </>
    )
  }

  if (error) {
    return (
      <Empty
        text={error instanceof ApiError ? error.message : 'Could not load the analysis.'}
      />
    )
  }
  if (manifestPending || !manifest) {
    return <p className="py-24 text-center text-ink-soft">Loading analysis…</p>
  }

  return (
    <>
      <PageHeader
        eyebrow="Insights"
        title={
          <span className="inline-flex items-center gap-3">
            <Sparkles size={26} aria-hidden /> {latestRun.dataset.filename}
          </span>
        }
        description={`Latest finished run · ${latestRun.dataset.row_count.toLocaleString()} rows · ${latestRun.dataset.column_count} columns`}
      />
      <div className="space-y-6">
        <KpiCards manifest={manifest} />
        <div className="grid gap-6 xl:grid-cols-2">
          <RiskHeatmap manifest={manifest} />
          <ActivityTimeline manifest={manifest} />
        </div>
        <div className="grid gap-6 xl:grid-cols-2">
          <FlowNetwork manifest={manifest} />
          <ModelPerformance manifest={manifest} />
        </div>
        <QualityGauge manifest={manifest} />
      </div>
    </>
  )
}
