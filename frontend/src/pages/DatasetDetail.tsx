import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  MessagesSquare,
  Play,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { AiInsights } from '../components/AiPanel'
import { PageHeader } from '../components/ui'
import type { DatasetComment, DatasetOut, QualityReport, SchemaOut } from '../lib/types'

/**
 * Detail page for one catalog item: file facts, schema and quality summary,
 * its analysis runs, and the message thread attached to the evidence.
 */
export default function DatasetDetail() {
  const { datasetId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [starting, setStarting] = useState(false)
  const [runError, setRunError] = useState('')
  const [draft, setDraft] = useState('')
  const [commentError, setCommentError] = useState('')

  const { data: datasets } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })
  const dataset = datasets?.find((d) => d.id === datasetId)

  const { data: schema } = useQuery<SchemaOut>({
    queryKey: ['dataset-schema', datasetId],
    queryFn: () => api.get<SchemaOut>(`/api/datasets/${datasetId}/schema`),
    enabled: !!datasetId,
    retry: false,
    staleTime: 60_000,
  })

  const { data: quality } = useQuery<QualityReport>({
    queryKey: ['dataset-quality', datasetId],
    queryFn: () => api.get<QualityReport>(`/api/datasets/${datasetId}/quality`),
    enabled: !!datasetId,
    retry: false,
    staleTime: 60_000,
  })

  const { data: comments } = useQuery<DatasetComment[]>({
    queryKey: ['comments', datasetId],
    queryFn: () => api.get<DatasetComment[]>(`/api/datasets/${datasetId}/comments`),
    enabled: !!datasetId,
    staleTime: 10_000,
  })

  const postComment = useMutation<DatasetComment, ApiError, string>({
    mutationFn: (text) =>
      api.post<DatasetComment>(`/api/datasets/${datasetId}/comments`, { text }),
    onSuccess: () => {
      setDraft('')
      setCommentError('')
      void queryClient.invalidateQueries({ queryKey: ['comments', datasetId] })
    },
    onError: (err) => setCommentError(err.message),
  })

  async function startAnalysis() {
    setStarting(true)
    setRunError('')
    try {
      const res = await api.post<{ run_id: string }>('/api/runs/start', {
        dataset_id: datasetId,
        column_overrides: {},
        config: {},
      })
      navigate(`/run/${res.run_id}/process`)
    } catch (e) {
      setRunError(e instanceof ApiError ? e.message : 'Could not start the analysis run.')
    } finally {
      setStarting(false)
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${dataset?.filename ?? 'this dataset'}?`)) return
    await api.delete(`/api/datasets/${datasetId}`)
    void queryClient.invalidateQueries({ queryKey: ['datasets'] })
    navigate('/catalog')
  }

  return (
    <div>
      <PageHeader
        eyebrow="Dataset detail"
        title={dataset?.filename ?? 'Dataset'}
        description={
          dataset && (
            <>
              {dataset.row_count.toLocaleString()} rows · {dataset.column_count} columns ·{' '}
              {(dataset.size_bytes / (1024 * 1024)).toFixed(1)} MB · validation {dataset.validation_status}
              {' · '}
              <Link to="/dashboard" className="font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4">
                analyze on the dashboard
              </Link>
            </>
          )
        }
        actions={
          <>
            <Link to="/catalog" className="btn btn-ghost py-2.5">
              <ArrowLeft size={15} aria-hidden />
              Datasets
            </Link>
            <button
              type="button"
              onClick={remove}
              className="inline-flex items-center gap-2 rounded-[12px] border border-danger/40 px-3.5 py-2.5 text-[13.5px] font-medium text-danger hover:bg-danger/10"
            >
              <Trash2 size={14} aria-hidden />
              Delete
            </button>
          </>
        }
      />

      <div className="mb-4">
        <AiInsights
          datasetId={datasetId}
          mode="dataset"
          icon={Sparkles}
          title="AI read of this file"
          subtitle="What the file contains and whether the analysis can trust it"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* schema summary */}
        <div className="panel p-5">
          <h2 className="text-[16.5px] font-semibold">Field structure</h2>
          {!schema ? (
            <p className="mt-2 text-[14.5px] text-ink-soft">Schema inference unavailable for this file.</p>
          ) : (
            <>
              <p className="mt-1 text-[14px] text-ink-soft">
                {schema.columns.length} columns profiled · {schema.warnings.length} warnings
              </p>
              <ul className="scroll-ink mt-4 max-h-[320px] space-y-1.5 overflow-y-auto text-[13.5px]">
                {schema.columns.slice(0, 40).map((c) => (
                  <li key={c.name} className="flex items-baseline justify-between gap-3 border-b border-line/15 pb-1">
                    <span className="truncate font-medium">{c.name}</span>
                    <span className="shrink-0 text-ink-soft">{c.semantic_type} · {c.physical_type}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        {/* quality summary */}
        <div className="panel p-5">
          <h2 className="text-[16.5px] font-semibold">Data quality</h2>
          {!quality ? (
            <p className="mt-2 text-[14.5px] text-ink-soft">Quality scoring unavailable for this file.</p>
          ) : (
            <>
              <p className="mt-2">
                <span className="text-[44px] leading-none font-medium tabular-nums">{quality.score}</span>
                <span className="text-[15px] text-ink-soft"> / 100 · grade {quality.grade}</span>
              </p>
              <ul className="mt-4 list-disc space-y-1.5 pl-5 text-[14px] text-ink-soft">
                {quality.summary.slice(0, 6).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      {/* runs */}
      <div className="panel panel-hover mt-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[16.5px] font-semibold">Analysis runs</h2>
          <button type="button" className="btn text-[15px]" disabled={starting} onClick={startAnalysis}>
            {starting ? 'Starting…' : 'Run new analysis'}
            <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
              <Play size={13} aria-hidden />
            </span>
          </button>
        </div>
        {runError && <p className="mt-3 text-[14px] text-danger">{runError}</p>}
        {!dataset?.runs?.length ? (
          <p className="mt-3 text-[14.5px] text-ink-soft">No runs yet — start the first analysis above.</p>
        ) : (
          <ul className="mt-4 space-y-2">
            {dataset.runs.map((r) => (
              <li key={r.id}>
                <Link
                  to={r.status === 'completed' ? `/run/${r.id}` : `/run/${r.id}/process`}
                  className="flex items-center justify-between gap-3 rounded-[12px] border border-line/25 bg-paper px-4 py-2.5 text-[14.5px] hover:bg-mist"
                >
                  <span className="font-mono text-[13px]">{r.id.slice(0, 8)}</span>
                  <span className="text-ink-soft">{r.status} · {r.progress}%</span>
                  <ArrowRight size={15} className="shrink-0" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* comments */}
      <div className="panel mt-4 p-5">
        <h2 className="flex items-center gap-2 text-[16.5px] font-semibold">
          <MessagesSquare size={19} aria-hidden />
          Messages and comments
        </h2>
        <p className="mt-1 text-[14px] text-ink-soft">
          Discuss this dataset — the thread stays attached to the evidence.
        </p>
        {!comments?.length ? (
          <p className="mt-4 text-[14.5px] text-ink-soft">No messages yet. Start the conversation below.</p>
        ) : (
          <ul className="mt-4 space-y-2.5">
            {comments.map((c) => (
              <li key={c.id} className={`max-w-[60ch] rounded-[14px] border px-4 py-2.5 ${c.mine ? 'border-line bg-mist' : 'border-line/25 bg-paper'}`}>
                <p className="text-[13px] font-medium text-ink-soft">
                  {c.author}{c.mine ? ' · you' : ''} · {c.created_at ? new Date(c.created_at).toLocaleString() : ''}
                </p>
                <p className="mt-1 text-[15px] whitespace-pre-wrap">{c.text}</p>
              </li>
            ))}
          </ul>
        )}
        <form
          className="mt-4 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault()
            if (draft.trim()) postComment.mutate(draft.trim())
          }}
        >
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Write a message…"
            maxLength={2000}
            className="field flex-1"
          />
          <button type="submit" className="btn text-[15px]" disabled={postComment.isPending || !draft.trim()}>
            Send
          </button>
        </form>
        {commentError && <p className="mt-2 text-[14px] text-danger">{commentError}</p>}
      </div>
    </div>
  )
}
