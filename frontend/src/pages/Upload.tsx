import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, CheckCircle2, Database, UploadCloud } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { DatasetOut, HealthInfo, ValidationOut } from '../lib/types'
import { AiInsights } from '../components/AiPanel'
import { PageHeader } from '../components/ui'

/**
 * Dedicated upload component: post a CSV, see validation on the spot,
 * then start an analysis or open the detail page.
 */
export default function Upload() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [validation, setValidation] = useState<ValidationOut | null>(null)
  const [starting, setStarting] = useState(false)

  const { data: health } = useQuery<HealthInfo>({
    queryKey: ['health'],
    queryFn: () => api.get<HealthInfo>('/api/health'),
    staleTime: 300_000,
  })

  const { data: demo } = useQuery<{ available: boolean }>({
    queryKey: ['demo'],
    queryFn: () => api.get<{ available: boolean }>('/api/demo/exists'),
    staleTime: 60_000,
  })

  const maxMB = Math.round((health?.limits?.max_upload_bytes ?? 209715200) / (1024 * 1024))

  const upload = useMutation<ValidationOut, ApiError, { f: File; isDemo?: boolean }>({
    mutationFn: ({ f, isDemo }) => {
      const form = new FormData()
      form.append('file', f)
      if (isDemo) form.append('is_demo', 'true')
      return api.postForm<ValidationOut>('/api/datasets/upload', form)
    },
    onSuccess: (result) => {
      setValidation(result)
      setError('')
      void queryClient.invalidateQueries({ queryKey: ['datasets'] })
      void queryClient.invalidateQueries({ queryKey: ['overview'] })
    },
    onError: (err) => {
      setValidation(null)
      setError(err.message || 'Upload failed.')
    },
  })

  function pickFile(f: File | null | undefined) {
    setError('')
    setValidation(null)
    if (!f) return
    if (!f.name.toLowerCase().endsWith('.csv')) {
      setError('Only .csv files are accepted. Export workbooks as CSV first.')
      return
    }
    if (f.size > (health?.limits?.max_upload_bytes ?? 209715200)) {
      setError(`File exceeds the ${maxMB} MB limit.`)
      return
    }
    setFile(f)
    upload.mutate({ f })
  }

  async function useDemo() {
    setError('')
    setValidation(null)
    try {
      const res = await fetch('/api/demo/download', { credentials: 'include' })
      if (!res.ok) throw new ApiError(res.status, 'Demo dataset unavailable.')
      const blob = await res.blob()
      const f = new File([blob], 'aegis_demo_dataset.csv', { type: 'text/csv' })
      setFile(f)
      upload.mutate({ f, isDemo: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Demo dataset could not be loaded.')
    }
  }

  async function startAnalysis() {
    if (!validation) return
    setStarting(true)
    setError('')
    try {
      const res = await api.post<{ run_id: string }>('/api/runs/start', {
        dataset_id: validation.dataset_id,
        column_overrides: {},
        config: {},
      })
      navigate(`/run/${res.run_id}/process`)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not start the analysis run.')
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="mx-auto max-w-[880px]">
      <PageHeader
        eyebrow="Workspace"
        title="Upload a dataset"
        description="Post your own CSV content. Validation reports on the spot, then the file joins your catalog and becomes analyzable on the dashboard."
        actions={
          <button
            type="button"
            className="btn btn-ghost py-2.5"
            onClick={useDemo}
            disabled={!demo?.available || upload.isPending}
          >
            <Database size={15} aria-hidden />
            {demo?.available ? 'Use the demo dataset' : 'Demo not generated'}
          </button>
        }
      />

      <div className="panel p-5 sm:p-6">
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          onChange={(e) => pickFile(e.target.files?.[0])}
        />
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => { e.preventDefault(); setDragging(false); pickFile(e.dataTransfer.files?.[0]) }}
          className={`flex min-h-[220px] w-full flex-col items-center justify-center gap-4 rounded-[18px] border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragging ? 'border-teal bg-teal/10' : 'border-line/25 bg-mist/70'
          }`}
          aria-label="Drop a CSV file or click to browse"
        >
          <span className="grid size-14 place-items-center rounded-[16px] bg-ink text-lime">
            <UploadCloud size={24} aria-hidden />
          </span>
          <span className="text-[19px] font-medium">
            {upload.isPending ? `Uploading ${file?.name ?? 'file'}…` : 'Drag one CSV here, or click to browse'}
          </span>
          <span className="text-[14px] text-ink-soft">
            .csv · up to {maxMB} MB · {(health?.limits?.max_rows ?? 500000).toLocaleString()} rows
          </span>
        </button>

        <div aria-live="polite" className="mt-5">
          {error && (
            <div className="flex items-start gap-3 rounded-[14px] border border-danger bg-danger/10 px-4 py-3">
              <AlertTriangle size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden />
              <div>
                <p className="text-[15px] font-medium text-danger">Upload rejected</p>
                <p className="mt-1 text-[14px] text-ink-soft">{error}</p>
              </div>
            </div>
          )}

          {validation && <ValidationCard v={validation} starting={starting} onStart={startAnalysis} onReplace={() => inputRef.current?.click()} onCancel={() => { setValidation(null); setFile(null) }} />}
        </div>
      </div>

      <RecentUploads />
    </div>
  )
}

function ValidationCard({ v, starting, onStart, onReplace, onCancel }: {
  v: ValidationOut; starting: boolean; onStart: () => void; onReplace: () => void; onCancel: () => void;
}) {
  return (
    <div className="rounded-[16px] border border-teal/40 bg-teal/8 p-5">
      <div className="flex items-center gap-3">
        <CheckCircle2 size={20} className="text-teal" aria-hidden />
        <p className="text-[16px] font-medium break-all">{v.filename}</p>
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-3 text-[14px] sm:grid-cols-4">
        <Fact label="Rows" value={v.row_count.toLocaleString()} />
        <Fact label="Columns" value={String(v.column_count)} />
        <Fact label="Delimiter" value={v.delimiter === '\t' ? 'tab' : v.delimiter} />
        <Fact label="Encoding" value={v.encoding} />
      </dl>
      {v.warnings.length > 0 && (
        <ul className="mt-4 space-y-1.5 text-[13.5px] text-ink-soft">
          {v.warnings.slice(0, 4).map((w) => (
            <li key={w} className="flex gap-2">
              <AlertTriangle size={14} className="mt-1 shrink-0 text-amber" aria-hidden />
              {w}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-5 flex flex-wrap gap-3">
        <button type="button" className="btn" disabled={starting} onClick={onStart}>
          {starting ? 'Starting…' : 'Start analysis'}
          <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
            <ArrowRight size={14} aria-hidden />
          </span>
        </button>
        <button type="button" className="btn btn-ghost" onClick={onReplace}>Replace file</button>
        <Link to={`/datasets/${v.dataset_id}`} className="btn btn-ghost">Detail page</Link>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>

      <div className="mt-5 border-t border-line/20 pt-5">
        <AiInsights
          datasetId={v.dataset_id}
          mode="dataset"
          title="AI read of this upload"
          subtitle="Structure, detected types and preparation notes from the parsed file"
        />
      </div>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-line/25 bg-mist px-3 py-2">
      <dt className="text-[12px] text-ink-soft">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}

function RecentUploads() {
  const { data: datasets } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })
  if (!datasets?.length) return null
  return (
    <div className="mt-6">
      <h2 className="text-[16px] font-semibold">Recent uploads</h2>
      <ul className="mt-3 space-y-2">
        {datasets.slice(0, 5).map((d) => (
          <li key={d.id}>
            <Link
              to={`/datasets/${d.id}`}
              className="flex items-center justify-between gap-3 rounded-[14px] border border-line/12 bg-paper px-4 py-2.5 text-[14px] transition-shadow hover:shadow-md"
            >
              <span className="truncate font-medium">{d.filename}</span>
              <span className="shrink-0 text-[13px] text-ink-soft">
                {d.row_count.toLocaleString()} rows · {d.runs?.[0]?.status ?? 'not analyzed'}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
