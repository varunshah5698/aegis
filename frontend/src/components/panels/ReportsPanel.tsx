import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, FileBarChart, FileJson, FileSpreadsheet, Loader2, Plus } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { AiSummary } from '../AiPanel'

interface ReportFiles {
  files: { name: string; size: number }[]
  registered: { kind: string; format: string; size: number; created_at: string }[]
}

const ICONS: Record<string, React.ComponentType<{ size?: number }>> = {
  md: FileBarChart,
  json: FileJson,
  csv: FileBarChart,
  xlsx: FileSpreadsheet,
}

export default function ReportsPanel({ runId }: { runId: string }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState('')

  const { data, isPending } = useQuery<ReportFiles>({
    queryKey: ['reports', runId],
    queryFn: () => api.get<ReportFiles>(`/api/runs/${runId}/reports`),
    enabled: !!runId,
  })

  const generate = useMutation({
    mutationFn: () => api.post<{ ok: boolean; files: { name: string }[] }>(`/api/runs/${runId}/reports`),
    onSuccess: () => {
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['reports', runId] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Report generation failed.'),
  })

  const reportKind = (name: string): string => {
    if (name.startsWith('executive')) return 'Executive'
    if (name.startsWith('technical')) return 'Technical'
    if (name.startsWith('investigation')) return 'Investigation'
    if (name.includes('findings')) return 'Findings (CSV)'
    if (name.includes('descriptive')) return 'Statistics (CSV)'
    if (name.includes('workbook')) return 'Workbook (XLSX)'
    return 'Artifact'
  }

  const files = data?.files ?? []
  const grouped = {
    markdown: files.filter((f) => f.name.endsWith('.md')),
    json: files.filter((f) => f.name.endsWith('.json')),
    table: files.filter((f) => f.name.endsWith('.csv') || f.name.endsWith('.xlsx')),
  }

  return (
    <div className="space-y-6">
      <AiSummary runId={runId} />

      <div className="panel p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h2 className="text-[26px] font-medium tracking-[-0.03em]">
              Reports & <span className="marker">exports</span>
            </h2>
            <p className="mt-1 text-[14.5px] text-ink-soft">
              Rendered from the persisted manifest — every figure traces to a computed result.
            </p>
          </div>
          <button
            type="button"
            className="btn"
            disabled={generate.isPending}
            onClick={() => generate.mutate()}
          >
            {generate.isPending ? (
              <>
                <Loader2 size={15} className="animate-spin" aria-hidden />
                Generating…
              </>
            ) : (
              <>
                <Plus size={15} aria-hidden />
                Generate reports
              </>
            )}
          </button>
        </div>

        {error && (
          <p className="mt-4 rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14.5px] text-danger">
            {error}
          </p>
        )}
        {generate.isSuccess && (
          <p className="mt-4 rounded-[14px] border border-teal bg-teal/10 px-4 py-3 text-[14.5px]">
            {generate.data.files.length} artifact(s) written to the run directory.
          </p>
        )}

        {isPending ? (
          <div className="mt-6 flex items-center gap-3 text-ink-soft">
            <Loader2 size={16} className="animate-spin" aria-hidden />
            <span className="text-[15px]">Listing existing reports…</span>
          </div>
        ) : files.length === 0 ? (
          <div className="mt-6 flex flex-col items-center gap-3 rounded-[24px] border border-dashed border-line/40 px-6 py-12 text-center">
            <FileBarChart size={28} className="text-ink-soft" aria-hidden />
            <p className="text-[16.5px] font-medium">No reports yet</p>
            <p className="max-w-[48ch] text-[14.5px] text-ink-soft">
              Generate the executive, technical and investigation reports — plus CSV/XLSX
              exports — from this run's results.
            </p>
          </div>
        ) : (
          <div className="mt-6 grid gap-5 md:grid-cols-3">
            <Group title="Documents" items={grouped.markdown} runId={runId} kindOf={reportKind} />
            <Group title="Structured data" items={grouped.json} runId={runId} kindOf={reportKind} />
            <Group title="Spreadsheets & tables" items={grouped.table} runId={runId} kindOf={reportKind} />
          </div>
        )}
      </div>

      <div className="panel p-5">
        <h3 className="text-[18px] font-medium">What each report contains</h3>
        <dl className="mt-4 grid gap-4 md:grid-cols-3">
          {[
            [
              'Executive',
              'Dataset overview, quality findings, ranked insights, anomaly highlights, recommended investigative steps and provenance.',
            ],
            [
              'Technical',
              'Schema mapping with confidence, transformations, statistical methods, model-selection rationale, metrics, feature importance and reproducibility details.',
            ],
            [
              'Investigation',
              'Entities of interest, trigger evidence with thresholds and methods, transfer paths, reconciliation status, calculation methodology and review status.',
            ],
          ].map(([title, body]) => (
            <div key={title} className="rounded-[14px] border border-line/30 bg-mist p-4">
              <dt className="text-[16px] font-medium">{title} report</dt>
              <dd className="mt-1.5 text-[14px] leading-relaxed text-ink-soft">{body}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-4 text-[13.5px] text-ink-soft">
          Reports never include fabricated metrics; unsupported modules are listed as
          limitations rather than omitted silently.
        </p>
      </div>
    </div>
  )
}

function Group({
  title,
  items,
  runId,
  kindOf,
}: {
  title: string
  items: { name: string; size: number }[]
  runId: string
  kindOf: (name: string) => string
}) {
  if (!items.length) return null
  return (
    <div>
      <h4 className="text-[14.5px] font-medium text-ink-soft">{title}</h4>
      <ul className="mt-3 space-y-2.5">
        {items.map((f) => {
          const ext = f.name.split('.').pop() ?? ''
          const Icon = ICONS[ext] ?? FileBarChart
          return (
            <li key={f.name}>
              <a
                href={`/api/runs/${runId}/reports/download?filename=${encodeURIComponent(f.name)}`}
                className="flex items-center gap-3 rounded-[14px] border border-line/30 px-3.5 py-2.5 transition-colors hover:bg-mist"
                download
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-lime ring-1 ring-line">
                  <Icon size={16} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[14.5px] font-medium">{kindOf(f.name)}</span>
                  <span className="block truncate text-[12.5px] text-ink-soft">{f.name}</span>
                </span>
                <span className="flex shrink-0 items-center gap-1.5 text-[12.5px] text-ink-soft">
                  {formatSize(f.size)}
                  <Download size={13} aria-hidden />
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function formatSize(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}
