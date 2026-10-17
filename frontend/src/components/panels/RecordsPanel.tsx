import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, FilterX, Loader2, Search, Table2 } from 'lucide-react'
import { api } from '../../lib/api'
import { AiSection } from '../AiPanel'
import type { Manifest } from '../../lib/types'

interface RecordsResponse {
  total: number
  filtered: number
  offset: number
  limit: number
  columns: string[]
  rows: (string | number | null)[][]
  sampled: boolean
}

/**
 * Dataset explorer: server-side search, sort and pagination so a 50k-row file
 * never ships to the browser (spec #14, #20).
 */
export default function RecordsPanel({
  runId,
  manifest,
}: {
  runId: string
  manifest: Manifest
}) {
  const [page, setPage] = useState(0)
  const [limit, setLimit] = useState(25)
  const [search, setSearch] = useState('')
  const [column, setColumn] = useState('')
  const [sort, setSort] = useState('')
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc')
  const [open, setOpen] = useState(false)

  const params = useMemo(() => {
    const p = new URLSearchParams({
      limit: String(limit),
      offset: String(page * limit),
    })
    if (search) p.set('q', search)
    if (column) p.set('column', column)
    if (sort) {
      p.set('sort', sort)
      p.set('direction', direction)
    }
    return p.toString()
  }, [limit, page, search, column, sort, direction])

  const { data, isPending } = useQuery<RecordsResponse>({
    queryKey: ['records', runId, params],
    queryFn: () => api.get<RecordsResponse>(`/api/runs/${runId}/records?${params}`),
    enabled: !!runId && open,
    placeholderData: (prev) => prev,
    staleTime: 10_000,
  })

  const totalPages = data ? Math.max(1, Math.ceil(data.filtered / limit)) : 1

  if (!open) {
    return (
      <button
        type="button"
        className="panel flex w-full items-center justify-between gap-4 px-6 py-5 text-left"
        onClick={() => setOpen(true)}
      >
        <span className="flex items-center gap-3">
          <Table2 size={19} aria-hidden />
          <span>
            <span className="block text-[17px] font-medium">Inspect the underlying records</span>
            <span className="block text-[14.5px] text-ink-soft">
              Search, sort and page through the file server-side
            </span>
          </span>
        </span>
        <span className="chip bg-lime">open</span>
      </button>
    )
  }

  const columns = manifest.columns.map((c) => c.name)

  return (
    <div className="panel p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-[19px] font-medium">Records</h3>
        <button
          type="button"
          className="btn btn-ghost px-3.5 py-1.5 text-[14px]"
          onClick={() => setOpen(false)}
        >
          Hide
        </button>
      </div>

      <div className="mt-4">
        <AiSection runId={runId} section="records" label="Explain what I am looking at" />
      </div>

      {/* --------------------------------------------------------- controls */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="relative min-w-[240px] flex-1">
          <Search size={16} className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft" aria-hidden />
          <input
            className="field py-2.5 pl-10"
            placeholder={`Search ${column ? column : 'all rows'}…`}
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(0)
            }}
            aria-label="Search records"
          />
        </label>
        <select
          className="rounded-[14px] border border-line bg-paper px-3 py-2.5 text-[14.5px]"
          value={column}
          onChange={(e) => {
            setColumn(e.target.value)
            setPage(0)
          }}
          aria-label="Search column"
        >
          <option value="">all columns</option>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select
          className="rounded-[14px] border border-line bg-paper px-3 py-2.5 text-[14.5px]"
          value={sort}
          onChange={(e) => {
            setSort(e.target.value)
            setPage(0)
          }}
          aria-label="Sort column"
        >
          <option value="">no sort</option>
          {columns.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        {sort && (
          <button
            type="button"
            className="chip"
            onClick={() => setDirection((d) => (d === 'asc' ? 'desc' : 'asc'))}
          >
            {direction === 'asc' ? 'ascending' : 'descending'}
          </button>
        )}
        {(search || column || sort) && (
          <button
            type="button"
            className="chip"
            onClick={() => {
              setSearch('')
              setColumn('')
              setSort('')
              setDirection('asc')
              setPage(0)
            }}
          >
            <FilterX size={13} aria-hidden />
            Reset
          </button>
        )}
      </div>

      {/* ------------------------------------------------------------ table */}
      <div className="scroll-ink mt-4 max-h-[540px] overflow-auto rounded-[14px] border border-line/30">
        {isPending || !data ? (
          <div className="flex items-center gap-3 px-5 py-8">
            <Loader2 size={17} className="animate-spin" aria-hidden />
            <span className="text-[15px] text-ink-soft">Loading records…</span>
          </div>
        ) : (
          <table className="table-grid">
            <thead>
              <tr>
                <th className="w-14">#</th>
                {data.columns.map((c) => (
                  <th key={c}>
                    <button
                      type="button"
                      className="flex items-center gap-1 hover:underline"
                      onClick={() => {
                        if (sort === c) {
                          setDirection((d) => (d === 'asc' ? 'desc' : 'asc'))
                        } else {
                          setSort(c)
                          setDirection('asc')
                        }
                        setPage(0)
                      }}
                      title={`Sort by ${c}`}
                    >
                      {c}
                      {sort === c && <span aria-hidden>{direction === 'asc' ? '↑' : '↓'}</span>}
                    </button>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row, i) => (
                <tr key={i} className="hover:bg-mist/70">
                  <td className="tabular-nums text-ink-soft">{data.offset + i + 1}</td>
                  {row.map((cell, j) => (
                    <td key={j} className="max-w-[240px] whitespace-nowrap">
                      <span className="block truncate" title={cell === null ? '' : String(cell)}>
                        {cell === null || cell === '' ? (
                          <span className="text-ink-soft/50">—</span>
                        ) : typeof cell === 'number' ? (
                          cell.toLocaleString()
                        ) : (
                          String(cell)
                        )}
                      </span>
                    </td>
                  ))}
                </tr>
              ))}
              {data.rows.length === 0 && (
                <tr>
                  <td colSpan={data.columns.length + 1} className="py-8 text-center text-ink-soft">
                    No row matches this search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* ------------------------------------------------------- pagination */}
      {data && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[14px]">
          <span className="text-ink-soft">
            {data.filtered.toLocaleString()} of {data.total.toLocaleString()} rows
            {data.filtered !== data.total && ' (filtered)'}
            {data.sampled ? ' · large file: exact count' : ''}
          </span>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-ink-soft">
              per page
              <select
                className="rounded-[10px] border border-line bg-paper px-2 py-1"
                value={limit}
                onChange={(e) => {
                  setLimit(Number(e.target.value))
                  setPage(0)
                }}
              >
                {[10, 25, 50, 100].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="chip disabled:opacity-40"
              disabled={page === 0}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeft size={14} aria-hidden />
              Prev
            </button>
            <span className="tabular-nums">
              {page + 1} / {totalPages}
            </span>
            <button
              type="button"
              className="chip disabled:opacity-40"
              disabled={page + 1 >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
              <ChevronRight size={14} aria-hidden />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
