import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, Search } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { NetworkResult } from '../lib/types'

/**
 * Interactive directed money-flow graph. The backend computes layout
 * (deterministic spring), aggregation and metrics — the browser only draws the
 * bounded node/edge set it receives (spec #10.2: server-side aggregation,
 * level-of-detail rendering).
 */
export default function NetworkGraph({ runId }: { runId: string }) {
  const [topN, setTopN] = useState(90)
  const [selected, setSelected] = useState<string | null>(null)
  const [hover, setHover] = useState<string | null>(null)

  const { data, isPending, error, refetch } = useQuery<NetworkResult>({
    queryKey: ['network', runId, topN],
    queryFn: () => api.get<NetworkResult>(`/api/runs/${runId}/network?top_n=${topN}`),
    enabled: !!runId,
    retry: false,
    staleTime: 60_000,
  })

  const focus = useMemo(() => {
    if (!data) return null
    const node = data.nodes.find((n) => n.id === selected || n.label === selected)
    if (!node) return null
    const edges = data.edges.filter((e) => e.source === node.id || e.target === node.id)
    const neighborIds = new Set(edges.flatMap((e) => [e.source, e.target]))
    return { node, edges, neighborIds }
  }, [data, selected])

  if (error instanceof ApiError) {
    return (
      <div className="card p-6">
        <p className="font-medium">Network unavailable</p>
        <p className="mt-1 text-[15px] text-ink-soft">{error.message}</p>
      </div>
    )
  }
  if (isPending || !data) {
    return (
      <div className="card flex items-center gap-3 p-8">
        <Loader2 size={18} className="animate-spin" aria-hidden />
        <span className="text-[15px] text-ink-soft">Loading aggregated network…</span>
      </div>
    )
  }
  if (data.status !== 'completed') {
    return (
      <div className="card p-6">
        <p className="font-medium">Transfer network not available</p>
        <p className="mt-1 text-[15px] text-ink-soft">{data.reason}</p>
      </div>
    )
  }

  const W = 780
  const H = 520
  // server layout is in [-1,1] spring space → map to viewBox with padding
  const pad = 46
  const px = (x: number) => pad + ((x + 1) / 2) * (W - pad * 2)
  const py = (y: number) => pad + ((y + 1) / 2) * (H - pad * 2)
  const maxVal = Math.max(...data.nodes.map((n) => n.out_value + n.in_value), 1)
  const radius = (v: number) => 5 + 17 * Math.sqrt(Math.max(v, 0) / maxVal)

  const nodeById = new Map(data.nodes.map((n) => [n.id, n]))

  return (
    <div className="space-y-5">
      {/* ------------------------------------------------------------ controls */}
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-3 text-[14.5px]">
          <span className="whitespace-nowrap">Entities shown</span>
          <input
            type="range"
            min={30}
            max={200}
            step={10}
            value={topN}
            onChange={(e) => setTopN(Number(e.target.value))}
            className="w-40 accent-[#191A23]"
          />
          <span className="tabular-nums font-medium">{data.nodes.length}</span>
        </label>
        <span className="chip bg-mist">{data.edge_count.toLocaleString()} flows</span>
        <span className="chip bg-mist">total {data.total_value?.toLocaleString() ?? '—'}</span>
        <button
          type="button"
          className="btn btn-ghost px-4 py-2 text-[14px]"
          onClick={() => void refetch()}
        >
          Refresh
        </button>
        {selected && (
          <button
            type="button"
            className="btn px-4 py-2 text-[14px]"
            onClick={() => setSelected(null)}
          >
            Clear selection
          </button>
        )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.7fr_1fr]">
        {/* ------------------------------------------------------------- graph */}
        <div className="card overflow-hidden p-4">
          <div className="scroll-ink overflow-x-auto">
            <svg
              viewBox={`0 0 ${W} ${H}`}
              className="h-[520px] w-full min-w-[560px]"
              role="img"
              aria-label="Directed transfer network"
            >
              <defs>
                <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6"
                  markerHeight="6" orient="auto-start-reverse">
                  <path d="M0,0 L8,4 L0,8 z" fill="#191A23" />
                </marker>
              </defs>

              {data.edges.map((e, i) => {
                const s = nodeById.get(e.source)
                const t = nodeById.get(e.target)
                if (!s || !t) return null
                const active =
                  !focus || e.source === focus.node.id || e.target === focus.node.id
                return (
                  <line
                    key={`${e.source}-${e.target}-${i}`}
                    x1={px(s.x)}
                    y1={py(s.y)}
                    x2={px(t.x)}
                    y2={py(t.y)}
                    stroke="#191A23"
                    strokeWidth={Math.min(e.width, 6)}
                    opacity={active ? 0.5 : 0.07}
                    markerEnd={active ? 'url(#arrow)' : undefined}
                  >
                    <title>
                      {s.label} → {t.label}: {e.value.toLocaleString()} across {e.count} txns
                    </title>
                  </line>
                )
              })}

              {data.nodes.map((n) => {
                const r = radius(n.out_value + n.in_value)
                const isFocus = focus?.node.id === n.id
                const isNeighbor = focus?.neighborIds.has(n.id)
                const isHover = hover === n.label
                const dim = focus && !isFocus && !isNeighbor
                const fill = n.net_flow < 0 ? '#B9FF66' : '#191A23'
                const stroke = n.net_flow < 0 ? '#191A23' : '#B9FF66'
                return (
                  <g
                    key={n.id}
                    transform={`translate(${px(n.x)},${py(n.y)})`}
                    opacity={dim ? 0.15 : 1}
                    onMouseEnter={() => setHover(n.label)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => setSelected(isFocus ? null : n.id)}
                    tabIndex={0}
                    role="button"
                    aria-label={`Entity ${n.label}, net flow ${n.net_flow}`}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelected(isFocus ? null : n.id)
                      }
                    }}
                    className="cursor-pointer focus:outline-none"
                  >
                    <circle
                      r={r}
                      fill={fill}
                      stroke={isFocus || isHover ? '#2f8f83' : stroke}
                      strokeWidth={isFocus ? 4 : 2}
                    />
                    {(isHover || isFocus || data.nodes.length <= 40) && (
                      <text
                        y={-r - 6}
                        textAnchor="middle"
                        fontSize={11}
                        fill="#191A23"
                        fontWeight={isFocus ? 600 : 400}
                      >
                        {n.label}
                      </text>
                    )}
                  </g>
                )
              })}
            </svg>
          </div>
          <p className="mt-1 px-2 text-[13px] text-ink-soft">
            Node size = combined flow · edge width = value · lime ring = net receiver ·
            click a node to isolate its neighbourhood. {data.warnings?.[0]}
          </p>
        </div>

        {/* ---------------------------------------------------------- inspector */}
        <div className="space-y-5">
          {focus ? (
            <div className="card p-6">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-[14px] text-ink-soft">Entity</p>
                  <p className="text-[24px] font-medium">{focus.node.label}</p>
                </div>
                <span className="chip bg-lime">{focus.node.community >= 0 ? `community ${focus.node.community}` : 'no community'}</span>
              </div>
              <dl className="mt-5 grid grid-cols-2 gap-3 text-[14px]">
                <Stat label="Sent" value={focus.node.out_value.toLocaleString()} />
                <Stat label="Received" value={focus.node.in_value.toLocaleString()} />
                <Stat label="Net flow" value={focus.node.net_flow.toLocaleString()} />
                <Stat label="Degree" value={String(focus.node.degree)} />
                <Stat label="Outgoing txns" value={focus.node.out_count.toLocaleString()} />
                <Stat label="Incoming txns" value={focus.node.in_count.toLocaleString()} />
                <Stat label="PageRank" value={focus.node.pagerank.toFixed(5)} />
                <Stat label="Connections" value={String(focus.edges.length)} />
              </dl>

              <h4 className="mt-6 text-[16px] font-medium">Direct connections</h4>
              <ul className="mt-2 max-h-64 space-y-2 overflow-y-auto scroll-ink pr-1">
                {focus.edges
                  .slice()
                  .sort((a, b) => b.value - a.value)
                  .map((e, i) => {
                    const outbound = e.source === focus.node.id
                    const other = outbound ? e.target : e.source
                    return (
                      <li key={i} className="rounded-[12px] border border-line/25 px-3 py-2 text-[13.5px]">
                        <span className={outbound ? 'text-teal' : 'text-ink-soft'}>
                          {outbound ? '→ sends to' : '← receives from'}
                        </span>{' '}
                        <button
                          type="button"
                          className="font-medium underline decoration-lime decoration-2 underline-offset-2"
                          onClick={() => setSelected(other)}
                        >
                          {nodeById.get(other)?.label ?? other}
                        </button>
                        <span className="block text-ink-soft">
                          {e.value.toLocaleString()} across {e.count} transaction{e.count === 1 ? '' : 's'}
                        </span>
                      </li>
                    )
                  })}
              </ul>
            </div>
          ) : (
            <div className="card p-6">
              <h4 className="text-[17px] font-medium">Inspect an entity</h4>
              <p className="mt-2 text-[14.5px] leading-relaxed text-ink-soft">
                Click any node to see sent/received totals, PageRank, community and its
                direct connections. Search by masked ID:
              </p>
              <NodeSearch
                nodes={data.nodes}
                onPick={(id) => setSelected(id)}
              />
            </div>
          )}

          {/* graph metrics */}
          <div className="card p-6">
            <h4 className="text-[17px] font-medium">Graph metrics</h4>
            <dl className="mt-4 space-y-2.5 text-[14.5px]">
              <Row label="Entities" value={String(data.node_count)} />
              <Row label="Aggregated flows" value={String(data.edge_count)} />
              <Row label="Density" value={String(data.metrics.density)} />
              <Row label="Weakly connected components" value={String(data.metrics.weakly_connected_components)} />
              <Row label="Strongly connected components" value={String(data.metrics.strongly_connected_components)} />
              <Row label="Reciprocal edges" value={String(data.metrics.reciprocal_edges)} />
              <Row label="Communities" value={String(data.metrics.community_count)} />
              <Row label="Coverage" value={String(data.metrics.aggregation)} />
            </dl>
            <div className="mt-4 border-t border-line/20 pt-3 text-[13px] text-ink-soft">
              Top PageRank:{' '}
              {(data.metrics.top_pagerank as { entity: string; pagerank: number }[] | undefined)
                ?.map((t) => `${t.entity} (${t.pagerank})`)
                .join(', ') || '—'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function NodeSearch({
  nodes,
  onPick,
}: {
  nodes: NetworkResult['nodes']
  onPick: (id: string) => void
}) {
  const [q, setQ] = useState('')
  const hits = q
    ? nodes.filter((n) => n.label.toLowerCase().includes(q.toLowerCase())).slice(0, 6)
    : []
  return (
    <div className="mt-4">
      <label className="relative block">
        <Search size={16} className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft" aria-hidden />
        <input
          className="field pl-10"
          placeholder="Search entity ID…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </label>
      {hits.length > 0 && (
        <ul className="mt-3 space-y-2">
          {hits.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className="w-full rounded-[12px] border border-line/25 px-3 py-2 text-left text-[14px] hover:bg-mist"
                onClick={() => onPick(n.id)}
              >
                {n.label} <span className="text-ink-soft">· net {n.net_flow.toLocaleString()}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-line/25 bg-mist px-3 py-2">
      <dt className="text-[12px] text-ink-soft">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/15 pb-2">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  )
}
