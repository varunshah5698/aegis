import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Info } from 'lucide-react'
import type { ChartSpec } from '../lib/types'

const LIME = '#B9FF66'
const INK = '#191A23'
const SERIES = [INK, '#2f8f83', '#8fb8d9', '#e8a33d', '#d4453d', '#7a7b8a']

const compact = (v: unknown): string => {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '')
  if (Math.abs(n) >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2)
}

/**
 * Renders a backend ChartSpec. All values arrive precomputed from the API —
 * this component never derives or invents numbers.
 */
export default function Chart({ spec }: { spec: ChartSpec }) {
  return (
    <figure className="card flex h-full flex-col p-6">
      <figcaption>
        <h3 className="text-[19px] font-medium">{spec.title}</h3>
        {spec.subtitle && <p className="mt-1 text-[14px] text-ink-soft">{spec.subtitle}</p>}
      </figcaption>
      <div className="mt-5 min-h-[260px] flex-1">
        <ChartBody spec={spec} />
      </div>
      {(spec.note || spec.columns.length > 0) && (
        <div className="mt-4 flex flex-wrap items-start gap-x-4 gap-y-1 border-t border-line/20 pt-3 text-[13px] text-ink-soft">
          {spec.note && (
            <span className="flex gap-1.5">
              <Info size={13} className="mt-0.5 shrink-0" aria-hidden />
              {spec.note}
            </span>
          )}
          <span>Columns: {spec.columns.join(', ')}</span>
        </div>
      )}
    </figure>
  )
}

function ChartBody({ spec }: { spec: ChartSpec }) {
  if (!spec.data?.length) {
    return <p className="text-[15px] text-ink-soft">No data points for this chart.</p>
  }

  switch (spec.type) {
    case 'area':
      return (
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={spec.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <defs>
              <linearGradient id={`fill-${spec.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#191A23" stopOpacity={0.25} />
                <stop offset="100%" stopColor="#191A23" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#191a2325" vertical={false} />
            <XAxis dataKey={spec.x} tick={{ fontSize: 11 }} minTickGap={28} />
            <YAxis tickFormatter={compact} tick={{ fontSize: 11 }} width={52} />
            <Tooltip content={<InkTooltip />} />
            <Area
              type="monotone"
              dataKey={spec.y}
              stroke={INK}
              strokeWidth={2}
              fill={`url(#fill-${spec.id})`}
              name={spec.y}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      )

    case 'line':
      return (
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={spec.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#191a2325" vertical={false} />
            <XAxis dataKey={spec.x} tick={{ fontSize: 11 }} minTickGap={24} />
            <YAxis tickFormatter={compact} tick={{ fontSize: 11 }} width={52} />
            <Tooltip content={<InkTooltip />} />
            <Legend />
            <Line
              type="monotone"
              dataKey={spec.y}
              stroke={INK}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
            {spec.series
              .filter((s) => s !== spec.y)
              .map((s, i) => (
                <Line
                  key={s}
                  type="monotone"
                  dataKey={s}
                  stroke={SERIES[(i + 1) % SERIES.length]}
                  strokeWidth={2}
                  strokeDasharray="5 4"
                  dot={false}
                  isAnimationActive={false}
                />
              ))}
          </LineChart>
        </ResponsiveContainer>
      )

    case 'stacked_bar':
      return (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={spec.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#191a2325" vertical={false} />
            <XAxis dataKey={spec.x} tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={56} />
            <YAxis tickFormatter={compact} tick={{ fontSize: 11 }} width={52} />
            <Tooltip content={<InkTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {spec.series.map((s, i) => (
              <Bar
                key={s}
                dataKey={s}
                stackId="a"
                fill={SERIES[i % SERIES.length]}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )

    case 'pareto':
      return (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={spec.data} margin={{ top: 4, right: 48, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#191a2325" vertical={false} />
            <XAxis dataKey={spec.x} tick={{ fontSize: 11 }} interval={0} angle={-18} textAnchor="end" height={56} />
            <YAxis yAxisId="left" tickFormatter={compact} tick={{ fontSize: 11 }} width={52} />
            <YAxis yAxisId="right" orientation="right" domain={[0, 100]} tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} width={44} />
            <Tooltip content={<InkTooltip />} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar yAxisId="left" dataKey={spec.y} fill={INK} isAnimationActive={false} />
            <Line
              yAxisId="right"
              type="stepAfter"
              dataKey={spec.series[0] ?? 'cum_pct'}
              stroke="#2f8f83"
              strokeWidth={2}
              dot={{ r: 3 }}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      )

    case 'heatmap':
      return <Heatmap spec={spec} />

    case 'sankey':
      return <SankeyFlow spec={spec} />

    case 'bar':
    default:
      return (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={spec.data} margin={{ top: 4, right: 8, bottom: 4, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#191a2325" vertical={false} />
            <XAxis
              dataKey={spec.x}
              tick={{ fontSize: 11 }}
              interval={spec.data.length > 14 ? 'preserveStartEnd' : 0}
              angle={spec.data.length > 8 ? -22 : 0}
              textAnchor={spec.data.length > 8 ? 'end' : 'middle'}
              height={spec.data.length > 8 ? 64 : 34}
            />
            <YAxis tickFormatter={compact} tick={{ fontSize: 11 }} width={52} />
            <Tooltip content={<InkTooltip />} cursor={{ fill: '#B9FF6666' }} />
            <Bar dataKey={spec.y} isAnimationActive={false}>
              {spec.data.map((_, i) => (
                <Cell key={i} fill={i === 0 ? LIME : INK} stroke={INK} strokeWidth={i === 0 ? 1 : 0} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )
  }
}

/* ------------------------------------------------------------- tooltip --- */
function InkTooltip(props: {
  active?: boolean
  payload?: { name?: string; value?: number | string; color?: string }[]
  label?: string | number
}) {
  const { active, payload, label } = props
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[10px] border border-line bg-paper px-3 py-2 text-[13px] shadow-none">
      <p className="font-medium">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-ink-soft">
          {p.name}: <span className="font-medium tabular-nums text-ink">{compact(p.value)}</span>
        </p>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------- heatmap --- */
function Heatmap({ spec }: { spec: ChartSpec }) {
  const labels = spec.columns
  const cells = new Map<string, number>()
  for (const d of spec.data) {
    cells.set(`${d.a}||${d.b}`, Number(d.value))
  }
  const size = labels.length
  if (!size) return <p className="text-[15px] text-ink-soft">No columns to correlate.</p>

  return (
    <div className="scroll-ink overflow-x-auto">
      <div style={{ minWidth: Math.max(320, size * 54) }}>
        <div
          className="grid gap-[2px]"
          style={{ gridTemplateColumns: `minmax(90px, 1.4fr) repeat(${size}, minmax(34px, 1fr))` }}
        >
          <span />
          {labels.map((l) => (
            <span key={l} className="truncate pb-1 text-[10.5px] text-ink-soft" title={l}>
              {shorten(l)}
            </span>
          ))}
          {labels.map((row) => (
            <RowCells key={row} row={row} labels={labels} cells={cells} />
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 text-[12px] text-ink-soft">
          <span>−1</span>
          <span className="h-3 w-40 rounded-[4px] border border-line"
            style={{ background: 'linear-gradient(90deg,#d4453d,#ffffff,#2f8f83)' }} />
          <span>+1</span>
          <span className="ml-3">Pearson correlation</span>
        </div>
      </div>
    </div>
  )
}

function RowCells({ row, labels, cells }: { row: string; labels: string[]; cells: Map<string, number> }) {
  return (
    <>
      <span className="truncate pr-2 text-right text-[10.5px] text-ink-soft" title={row}>
        {shorten(row)}
      </span>
      {labels.map((col) => {
        const v = cells.get(`${row}||${col}`)
        const defined = v !== undefined && Number.isFinite(v)
        return (
          <span
            key={col}
            title={defined ? `${row} × ${col}: ${v.toFixed(3)}` : 'not computed'}
            className="grid h-8 place-items-center rounded-[4px] border border-line/20 text-[10.5px] tabular-nums"
            style={{ background: defined ? heatColor(v) : '#f4f4f4', color: defined && Math.abs(v) > 0.55 ? '#fff' : INK }}
          >
            {defined ? v.toFixed(2) : '·'}
          </span>
        )
      })}
    </>
  )
}

function heatColor(v: number) {
  const t = Math.max(-1, Math.min(1, v))
  if (t >= 0) {
    const a = t
    return `rgba(47,143,131,${0.15 + a * 0.85})`
  }
  const a = -t
  return `rgba(212,69,61,${0.15 + a * 0.85})`
}

function shorten(s: string) {
  return s.length > 14 ? `${s.slice(0, 13)}…` : s
}

/* ---------------------------------------------------------------- sankey --- */
function SankeyFlow({ spec }: { spec: ChartSpec }) {
  // Server sends source/target names + value; build an indexed graph for SVG.
  const nodes: string[] = []
  const index = new Map<string, number>()
  const idx = (n: string) => {
    if (!index.has(n)) {
      index.set(n, nodes.length)
      nodes.push(n)
    }
    return index.get(n)!
  }
  const links = spec.data.map((d) => ({
    source: idx(String(d.source)),
    target: idx(String(d.target)),
    value: Math.max(Number(d.value) || 0, 0),
    sourceName: String(d.source),
    targetName: String(d.target),
  }))

  if (!links.length) return <p className="text-[15px] text-ink-soft">No flows to draw.</p>

  const width = 760
  const height = 320
  const nodeW = 14
  const maxVal = Math.max(...links.map((l) => l.value), 1)

  const srcTotals = new Map<number, number>()
  const tgtTotals = new Map<number, number>()
  for (const l of links) {
    srcTotals.set(l.source, (srcTotals.get(l.source) ?? 0) + l.value)
    tgtTotals.set(l.target, (tgtTotals.get(l.target) ?? 0) + l.value)
  }
  const layout = (totals: Map<number, number>, x: number) => {
    const pos = new Map<number, { y: number; h: number }>()
    const entries = [...totals.entries()].sort((a, b) => b[1] - a[1])
    const totalVal = entries.reduce((s, [, v]) => s + v, 0) || 1
    let y = 4
    const gap = 6
    const usable = height - 8 - gap * (entries.length - 1)
    for (const [id, v] of entries) {
      const h = Math.max(6, (v / totalVal) * usable)
      pos.set(id, { y, h })
      y += h + gap
    }
    return { pos, x }
  }
  const left = layout(srcTotals, 0)
  const right = layout(tgtTotals, width - nodeW)

  let cursorLeft = new Map<number, number>()
  let cursorRight = new Map<number, number>()
  for (const [id, p] of left.pos) cursorLeft.set(id, p.y)
  for (const [id, p] of right.pos) cursorRight.set(id, p.y)

  const paths = links.map((l, i) => {
    const lp = left.pos.get(l.source)
    const rp = right.pos.get(l.target)
    if (!lp || !rp) return null
    const lh = Math.max(2, (l.value / (srcTotals.get(l.source) || 1)) * lp.h)
    const rh = Math.max(2, (l.value / (tgtTotals.get(l.target) || 1)) * rp.h)
    const ly = cursorLeft.get(l.source) ?? lp.y
    const ry = cursorRight.get(l.target) ?? rp.y
    cursorLeft.set(l.source, ly + lh)
    cursorRight.set(l.target, ry + rh)
    const x0 = nodeW
    const x1 = width - nodeW
    const mid = (x0 + x1) / 2
    const d = `M${x0},${ly} C${mid},${ly} ${mid},${ry} ${x1},${ry} L${x1},${ry + rh} C${mid},${ry + rh} ${mid},${ly + lh} ${x0},${ly + lh} Z`
    return {
      key: `${l.sourceName}-${l.targetName}-${i}`,
      d,
      stroke: `rgba(25,26,35,${0.12 + 0.5 * (l.value / maxVal)})`,
      title: `${l.sourceName} → ${l.targetName}: ${compact(l.value)}`,
    }
  }).filter(Boolean) as { key: string; d: string; stroke: string; title: string }[]

  return (
    <div className="scroll-ink overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="h-[320px] w-full min-w-[620px]" role="img"
        aria-label="Sankey diagram of top aggregated flows">
        {paths.map((p) => (
          <path key={p.key} d={p.d} fill={p.stroke}>
            <title>{p.title}</title>
          </path>
        ))}
        {[...left.pos.entries()].map(([id, p]) => (
          <g key={`l${id}`}>
            <rect x={0} y={p.y} width={nodeW} height={p.h} fill={INK} rx={3}>
              <title>{nodes[id]}</title>
            </rect>
            <text x={nodeW + 5} y={p.y + p.h / 2 + 3.5} fontSize={10} fill={INK}>
              {shorten(nodes[id])}
            </text>
          </g>
        ))}
        {[...right.pos.entries()].map(([id, p]) => (
          <g key={`r${id}`}>
            <rect x={width - nodeW} y={p.y} width={nodeW} height={p.h} fill="#2f8f83" rx={3}>
              <title>{nodes[id]}</title>
            </rect>
            <text x={width - nodeW - 5} y={p.y + p.h / 2 + 3.5} fontSize={10} fill={INK} textAnchor="end">
              {shorten(nodes[id])}
            </text>
          </g>
        ))}
      </svg>
      <p className="mt-2 text-[12.5px] text-ink-soft">
        Hover a ribbon for the aggregated value. Flow widths are proportional to value on
        the top {links.length} edges returned by the server.
      </p>
    </div>
  )
}
