import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, UploadCloud } from 'lucide-react'
import { api } from '../lib/api'
import type { DatasetOut } from '../lib/types'
import { AiWorkspaceSummary } from '../components/AiPanel'
import { PageHeader } from '../components/ui'

type StatusFilter = 'all' | 'completed' | 'running' | 'failed' | 'none'
type SortKey = 'newest' | 'name' | 'rows'

/**
 * Browse and search the customer's catalog: every dataset with its latest
 * run status, filterable by text and status, sortable by name, size or age.
 */
export default function Catalog() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [sort, setSort] = useState<SortKey>('newest')

  const { data: datasets, isPending, refetch } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })

  const items = useMemo(() => {
    const needle = q.trim().toLowerCase()
    let rows = (datasets ?? []).filter((d) => {
      if (needle && !d.filename.toLowerCase().includes(needle)) return false
      const s = d.runs?.[0]?.status ?? 'none'
      if (status === 'completed' && s !== 'completed' && s !== 'partial') return false
      if (status === 'running' && !['pending', 'running'].includes(s)) return false
      if (status === 'failed' && !['failed', 'cancelled'].includes(s)) return false
      if (status === 'none' && s !== 'none') return false
      return true
    })
    rows = [...rows].sort((a, b) => {
      if (sort === 'name') return a.filename.localeCompare(b.filename)
      if (sort === 'rows') return b.row_count - a.row_count
      return (b.created_at ?? '').localeCompare(a.created_at ?? '')
    })
    return rows
  }, [datasets, q, status, sort])

  return (
    <>
      <PageHeader
        eyebrow="Workspace"
        title="Datasets"
        description="Every dataset you have uploaded, searchable by name and filterable by analysis status. Open any item for its full detail page."
        actions={
          <Link to="/upload" className="btn py-2.5">
            <UploadCloud size={16} aria-hidden />
            Upload CSV
          </Link>
        }
      />

      <div className="panel flex flex-wrap gap-3 p-4">
        <label className="min-w-[220px] flex-1">
          <span className="sr-only">Search by file name</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by file name…"
            className="field"
          />
        </label>
        <label>
          <span className="sr-only">Filter by status</span>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as StatusFilter)}
            className="field w-auto"
          >
            <option value="all">All statuses</option>
            <option value="completed">Completed</option>
            <option value="running">Running</option>
            <option value="failed">Failed</option>
            <option value="none">Not analyzed</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Sort order</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            className="field w-auto"
          >
            <option value="newest">Newest first</option>
            <option value="name">Name A–Z</option>
            <option value="rows">Most rows</option>
          </select>
        </label>
      </div>

      <div className="mt-5">
        <AiWorkspaceSummary />
      </div>

      {isPending ? (
        <p className="py-16 text-center text-ink-soft">Loading your catalog…</p>
      ) : !items.length ? (
        <div className="panel mt-5 flex flex-col items-center gap-3 p-12 text-center">
          <UploadCloud size={30} className="text-ink-soft" aria-hidden />
          <p className="text-[18px] font-medium">
            {datasets?.length ? 'No matches — try a different search.' : 'Your catalog is empty.'}
          </p>
          <p className="max-w-[48ch] text-[15px] text-ink-soft">
            Upload a CSV to create your first entry, then analyze it on the dashboard.
          </p>
          <Link to="/upload" className="btn mt-2">
            Upload a CSV
            <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
              <ArrowRight size={14} aria-hidden />
            </span>
          </Link>
        </div>
      ) : (
        <>
          <p className="mt-5 text-[13.5px] text-ink-soft">
            {items.length} of {datasets?.length ?? 0} datasets
          </p>
          <ul className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {items.map((d) => {
              const latest = d.runs?.[0]
              const target =
                latest && latest.status === 'completed'
                  ? `/run/${latest.id}`
                  : latest
                    ? `/run/${latest.id}/process`
                    : null
              return (
                <li key={d.id} className="panel panel-hover flex flex-col p-5">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[17px] font-medium break-all">{d.filename}</p>
                    <StatusPill status={latest?.status ?? 'none'} />
                  </div>
                  <dl className="mt-4 grid grid-cols-3 gap-2 text-[13.5px]">
                    <Mini label="Rows" value={d.row_count.toLocaleString()} />
                    <Mini label="Cols" value={String(d.column_count)} />
                    <Mini label="Runs" value={String(d.runs?.length ?? 0)} />
                  </dl>
                  <div className="mt-5 flex flex-wrap gap-2">
                    <Link
                      to={`/datasets/${d.id}`}
                      className="inline-flex items-center gap-2 rounded-[14px] bg-ink px-4 py-2 text-[14px] font-medium text-paper"
                    >
                      Detail page
                    </Link>
                    {target && (
                      <Link
                        to={target}
                        className="inline-flex items-center gap-2 rounded-[14px] bg-lime px-4 py-2 text-[14px] font-medium text-ink"
                      >
                        Open workspace
                      </Link>
                    )}
                    <button
                      type="button"
                      className="rounded-[14px] border border-line/30 px-4 py-2 text-[14px] transition hover:bg-mist"
                      onClick={async () => {
                        await api.delete(`/api/datasets/${d.id}`)
                        void refetch()
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </>
  )
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: 'bg-lime',
    partial: 'bg-amber-300',
    running: 'bg-sky-300',
    pending: 'bg-sky-300',
    failed: 'bg-danger text-paper',
    cancelled: 'bg-mist',
    none: 'bg-mist',
  }
  return (
    <span className={`shrink-0 rounded-full border border-line px-2.5 py-0.5 text-[12px] font-medium ${map[status] ?? 'bg-mist'}`}>
      {status === 'none' ? 'not analyzed' : status}
    </span>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[10px] border border-line/25 bg-mist px-2.5 py-1.5">
      <dt className="text-[11.5px] text-ink-soft">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}
