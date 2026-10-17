import { useEffect, useMemo } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertOctagon, ArrowLeft, CheckCircle2, Circle, Loader2, RotateCcw, Square } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { RunStatus } from '../lib/types'

const TERMINAL = ['completed', 'partial', 'failed', 'cancelled']

/**
 * Live pipeline screen: polls the real job table. Each row flips to
 * completed/failed/skipped only when the backend worker says so — there is no
 * client-side fake progress (spec #4.3).
 */
export default function Processing() {
  const { runId = '' } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, error, refetch } = useQuery<RunStatus>({
    queryKey: ['run-status', runId],
    queryFn: () => api.get<RunStatus>(`/api/runs/${runId}/status`),
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && TERMINAL.includes(status) ? false : 900
    },
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 3,
  })

  // when the run finishes, prime the manifest cache and jump to the workspace
  useEffect(() => {
    if (!data) return
    if (data.status === 'completed' || data.status === 'partial') {
      const t = setTimeout(() => navigate(`/run/${runId}`, { replace: true }), 700)
      return () => clearTimeout(t)
    }
    if (data.status === 'failed') {
      void queryClient.invalidateQueries({ queryKey: ['run-jobs', runId] })
    }
    return
  }, [data?.status, runId, navigate, queryClient, data])

  const cancel = useMutation({
    mutationFn: () => api.post(`/api/runs/${runId}/cancel`),
    onSuccess: () => void refetch(),
  })
  const retry = useMutation({
    mutationFn: () => api.post(`/api/runs/${runId}/retry`),
    onSuccess: () => void refetch(),
  })

  const jobs = useMemo(() => data?.jobs ?? [], [data])
  const done = jobs.filter((j) => j.status === 'completed').length
  const failed = jobs.filter((j) => j.status === 'failed')
  const status = data?.status ?? 'loading'

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="py-24 text-center">
        <AlertOctagon size={34} className="mx-auto text-danger" aria-hidden />
        <h1 className="mt-4 text-[30px] font-medium">Run not found</h1>
        <p className="mt-2 text-ink-soft">{error.message}</p>
        <Link to="/" className="btn mt-6">Back to upload</Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[980px]">
      <Link to="/" className="chip" >
        <ArrowLeft size={15} aria-hidden />
        Upload
      </Link>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-5">
        <div>
          <h1 className="text-[38px] leading-tight font-medium tracking-[-0.03em]">
            {TERMINAL.includes(status) ? (
              <>
                Analysis <span className="marker">{statusLabel(status)}</span>
              </>
            ) : (
              <>
                Analyzing <span className="marker">your dataset</span>
              </>
            )}
          </h1>
          <p className="mt-2 text-[16px] text-ink-soft">
            {data?.current_stage || 'Queued — waiting for a worker…'}
          </p>
        </div>
        <div className="flex gap-3">
          {status === 'running' || status === 'pending' ? (
            <button type="button" className="btn btn-ghost" onClick={() => cancel.mutate()}>
              <Square size={15} aria-hidden />
              Cancel
            </button>
          ) : null}
          {(failed.length > 0 || status === 'failed') && status !== 'running' ? (
            <button type="button" className="btn" onClick={() => retry.mutate()} disabled={retry.isPending}>
              <RotateCcw size={15} aria-hidden />
              Retry failed stages
            </button>
          ) : null}
          {TERMINAL.includes(status) && status !== 'failed' ? (
            <button type="button" className="btn" onClick={() => navigate(`/run/${runId}`)}>
              Open workspace
            </button>
          ) : null}
        </div>
      </div>

      {/* overall progress = stages completed / total (from the DB) */}
      <div className="mt-6">
        <div className="mb-2 flex items-baseline justify-between text-[14px]">
          <span className="text-ink-soft">
            {done} of {jobs.length || 16} stages complete
          </span>
          <span className="font-medium tabular-nums">{data?.progress ?? 0}%</span>
        </div>
        <div
          className="h-3 w-full overflow-hidden rounded-full border border-line bg-mist"
          role="progressbar"
          aria-valuenow={data?.progress ?? 0}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-lime transition-[width] duration-500"
            style={{ width: `${data?.progress ?? 0}%` }}
          />
        </div>
      </div>

      {/* ---------------------------------------------------- stage list */}
      <ol className="mt-6 space-y-2.5">
        {jobs.map((j) => (
          <li key={j.name} className="stage-row">
            <span className="shrink-0">
              <StageIcon status={j.status} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="text-[15.5px] font-medium">{j.label}</span>
                {!j.required && (
                  <span className="chip px-2 py-0.5 text-[11.5px]">optional</span>
                )}
              </div>
              {j.detail && (
                <p className="mt-1 text-[13.5px] break-words text-ink-soft">{j.detail}</p>
              )}
              {j.error && (
                <p className="mt-1 text-[13.5px] break-words text-danger">{j.error}</p>
              )}
            </div>
            <span className={`shrink-0 text-[13px] ${statusTone(j.status)}`}>
              {j.status === 'running' && (
                <Loader2 size={14} className="mr-1 inline animate-spin" aria-hidden />
              )}
              {j.status}
            </span>
          </li>
        ))}
        {jobs.length === 0 && (
          <li className="stage-row text-[15px] text-ink-soft">
            <Loader2 size={16} className="animate-spin" aria-hidden />
            Registering stages…
          </li>
        )}
      </ol>

      {/* --------------------------------------------------- summary box */}
      {status === 'partial' && (
        <div className="mt-8 rounded-[14px] border border-amber bg-amber/10 px-5 py-4">
          <p className="font-medium">Partial results</p>
          <p className="mt-1 text-[14.5px] text-ink-soft">
            {failed.length} optional module(s) failed; everything else completed. Open the
            workspace to see which modules are available, or retry the failed stages.
          </p>
        </div>
      )}
      {status === 'failed' && (
        <div className="mt-8 rounded-[14px] border border-danger bg-danger/8 px-5 py-4">
          <p className="font-medium text-danger">Required stage failed</p>
          <p className="mt-1 text-[14.5px] text-ink-soft">
            {data?.error || failed.map((f) => `${f.label}: ${f.error ?? 'error'}`).join(' · ')}
          </p>
        </div>
      )}
      {TERMINAL.includes(status) && status !== 'failed' && (
        <div className="mt-8 rounded-[14px] border border-line bg-lime/30 px-5 py-4">
          <p className="font-medium">Results persisted</p>
          <p className="mt-1 text-[14.5px] text-ink-soft">
            Manifest, charts and findings are stored server-side — reopening this URL after
            a refresh returns the same workspace.
          </p>
        </div>
      )}
    </div>
  )
}

function StageIcon({ status }: { status: string }) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={20} className="text-teal" aria-label="completed" />
    case 'running':
      return <Loader2 size={20} className="animate-spin" aria-label="running" />
    case 'failed':
      return <AlertOctagon size={20} className="text-danger" aria-label="failed" />
    case 'skipped':
      return <Circle size={20} className="text-amber" aria-label="skipped" />
    case 'cancelled':
      return <Square size={18} className="text-ink-soft" aria-label="cancelled" />
    default:
      return <Circle size={20} className="text-ink-soft/45" aria-label="pending" />
  }
}

function statusTone(status: string) {
  if (status === 'completed') return 'text-teal'
  if (status === 'failed') return 'text-danger'
  if (status === 'skipped') return 'text-amber'
  if (status === 'running') return 'text-ink'
  return 'text-ink-soft/70'
}

function statusLabel(status: string) {
  if (status === 'completed') return 'complete'
  if (status === 'partial') return 'partial'
  return status
}
