import { useMemo } from 'react'
import { Activity, AlertTriangle, Clock, Gauge, Network, Sparkles } from 'lucide-react'
import type { Finding, Manifest } from '../../lib/types'
import { Badge, Empty, Panel, StatCard, prettify } from '../ui'

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

function findingsOf(m: Manifest): Finding[] {
  const p = m.financial?.modules?.patterns
  return p && Array.isArray(p.findings) ? p.findings : []
}

/* ------------------------------------------------------------ 1. KPI ---- */

/** Sparkline over a numeric series, drawn as SVG. */
export function Sparkline({ values, tone = '#b9ff66' }: { values: number[]; tone?: string }) {
  if (values.length < 2) return <span className="text-[12px] text-ink-soft">no trend</span>
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${100 - ((v - min) / span) * 100}`)
  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-10 w-full" aria-hidden>
      <polyline points={pts.join(' ')} fill="none" stroke={tone} strokeWidth="3" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

export function KpiCards({ manifest }: { manifest: Manifest }) {
  const findings = findingsOf(manifest)
  const nodes = manifest.financial?.modules?.network?.nodes ?? []
  const flowSeries = [...nodes].sort((a, b) => a.in_value + a.out_value - (b.in_value + b.out_value))
    .map((n) => n.in_value + n.out_value)
  const missing = manifest.quality?.missing.total_missing_pct ?? 0
  const metrics = manifest.ml?.supervised?.metrics ?? {}
  const rawF1 = metrics.f1_weighted ?? metrics.f1
  const f1 = typeof rawF1 === 'number' ? rawF1 : undefined
  const high = findings.filter((f) => ['critical', 'high'].includes((f.severity || '').toLowerCase())).length

  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <div className="panel p-4">
        <StatCard icon={AlertTriangle} label="Detections" value={String(findings.length)} hint={`${high} high or critical`} accent="bg-amber/25 text-ink" />
        <div className="mt-3"><Sparkline values={flowSeries.length ? flowSeries : [0, 0]} tone="#e8a33d" /></div>
      </div>
      <div className="panel p-4">
        <StatCard icon={Gauge} label="Quality score" value={manifest.quality ? String(manifest.quality.score) : '—'} hint={manifest.quality ? `grade ${manifest.quality.grade} · ${missing.toFixed(1)}% missing` : 'not scored'} accent="bg-violet-300/40 text-ink" />
      </div>
      <div className="panel p-4">
        <StatCard icon={Network} label="Accounts in flow" value={String(nodes.length)} hint={`${manifest.financial?.modules?.network?.edge_count ?? 0} links`} accent="bg-teal/20 text-ink" />
        <div className="mt-3"><Sparkline values={flowSeries.slice(-12).length ? flowSeries.slice(-12) : [0, 0]} tone="#2f8f83" /></div>
      </div>
      <div className="panel p-4">
        <StatCard icon={Activity} label="Model F1" value={f1 !== undefined ? f1.toFixed(3) : '—'} hint={manifest.ml?.supervised?.best_model ?? 'no trained model'} accent="bg-lime text-ink" />
      </div>
    </div>
  )
}

/* ------------------------------------------------------ 2. Heatmap ------ */

export function RiskHeatmap({ manifest }: { manifest: Manifest }) {
  const findings = findingsOf(manifest)
  const kinds = [...new Set(findings.map((f) => f.kind || 'other'))]
  const sevs = SEVERITY_ORDER.filter((s) => findings.some((f) => (f.severity || 'info').toLowerCase() === s))
  if (!kinds.length) return <Empty text="No detections in this run, so there is no risk grid to show." />
  const count = (k: string, s: string) =>
    findings.filter((f) => (f.kind || 'other') === k && (f.severity || 'info').toLowerCase() === s)
      .reduce((n, f) => n + (f.row_count || 1), 0)
  const max = Math.max(1, ...kinds.flatMap((k) => sevs.map((s) => count(k, s))))
  return (
    <Panel icon={Sparkles} title="Risk heatmap" subtitle="Rows affected, by pattern and severity">
      <div className="overflow-x-auto">
        <table className="w-full border-separate border-spacing-[6px] text-[13px]">
          <thead>
            <tr>
              <th className="text-left font-medium text-ink-soft">Pattern</th>
              {sevs.map((s) => (
                <th key={s} className="font-medium text-ink-soft capitalize">{s}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {kinds.map((k) => (
              <tr key={k}>
                <td className="pr-3 whitespace-nowrap">{prettify(k)}</td>
                {sevs.map((s) => {
                  const v = count(k, s)
                  const a = v / max
                  return (
                    <td
                      key={s}
                      title={`${v.toLocaleString()} rows`}
                      className="h-10 min-w-[72px] rounded-[10px] text-center font-medium tabular-nums"
                      style={{ background: v ? `rgba(185,255,102,${0.15 + a * 0.85})` : '#f4f4f4' }}
                    >
                      {v ? v.toLocaleString() : '·'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

/* ------------------------------------------------------ 3. Network ------ */

export function FlowNetwork({ manifest }: { manifest: Manifest }) {
  const net = manifest.financial?.modules?.network
  const nodes = net?.nodes ?? []
  const edges = net?.edges ?? []
  if (!net || net.status !== 'completed' || !nodes.length) {
    return <Empty text={net?.reason || 'The money-flow network needs source and destination accounts in this file.'} />
  }
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const top = [...nodes].sort((a, b) => b.pagerank - a.pagerank).slice(0, 6)
  const maxW = Math.max(1, ...edges.map((e) => e.width || e.value))
  const color = (c: number) => ['#191a23', '#2f8f83', '#8fb8d9', '#e8a33d', '#d4453d', '#a78bfa'][c % 6]
  return (
    <Panel icon={Network} title="Money-flow network" subtitle={`${nodes.length} accounts · ${edges.length} links · colour = community`}>
      <svg viewBox="0 0 100 100" className="aspect-square w-full rounded-[14px] bg-mist" role="img" aria-label="Transaction flow network">
        {edges.slice(0, 400).map((e, i) => {
          const a = byId.get(e.source)
          const b = byId.get(e.target)
          if (!a || !b) return null
          return (
            <line
              key={i}
              x1={a.x * 100} y1={a.y * 100} x2={b.x * 100} y2={b.y * 100}
              stroke="#191a23" strokeOpacity="0.25"
              strokeWidth={Math.max(0.2, ((e.width || e.value) / maxW) * 1.4)}
            />
          )
        })}
        {nodes.map((n) => (
          <circle key={n.id} cx={n.x * 100} cy={n.y * 100} r={Math.min(3.2, 0.8 + n.pagerank * 900)} fill={color(n.community)}>
            <title>{`${n.label} · in ${n.in_value.toLocaleString()} · out ${n.out_value.toLocaleString()}`}</title>
          </circle>
        ))}
      </svg>
      <ol className="mt-4 space-y-1.5 text-[13.5px]">
        {top.map((n) => (
          <li key={n.id} className="flex items-center justify-between gap-3">
            <span className="truncate font-medium">{n.label}</span>
            <span className="tabular-nums text-ink-soft">{(n.in_value + n.out_value).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

/* -------------------------------------------------- 4. Model performance -- */

export function ModelPerformance({ manifest }: { manifest: Manifest }) {
  const sup = manifest.ml?.supervised
  const anomaly = manifest.ml?.anomaly
  if (!sup || sup.status !== 'completed') {
    return <Empty text={sup?.reason || 'No supervised model was trained for this file.'} />
  }
  const metrics = Object.entries(sup.metrics).filter(([, v]) => typeof v === 'number').slice(0, 6)
  const cm = sup.confusion ?? []
  const cmMax = Math.max(1, ...cm.flat())
  const imp = (sup.feature_importance ?? []).slice(0, 8)
  const impMax = Math.max(1e-9, ...imp.map((f) => Math.abs(f.importance)))
  return (
    <Panel icon={Activity} title="Model performance" subtitle={`${sup.best_model} · ${sup.split_strategy}`} className="h-full">
      <dl className="grid grid-cols-3 gap-2">
        {metrics.map(([k, v]) => (
          <div key={k} className="rounded-[12px] bg-mist px-3 py-2">
            <dt className="text-[11.5px] text-ink-soft uppercase">{prettify(k)}</dt>
            <dd className="font-semibold tabular-nums">{(v as number).toFixed(3)}</dd>
          </div>
        ))}
      </dl>
      {cm.length === 2 && (
        <div className="mt-5">
          <p className="mb-2 text-[13px] font-medium">Confusion matrix</p>
          <div className="grid grid-cols-2 gap-1.5 text-center text-[13px] font-medium">
            {cm.flat().map((v, i) => (
              <div key={i} className="rounded-[10px] py-3 tabular-nums" style={{ background: `rgba(25,26,35,${0.06 + (v / cmMax) * 0.7})`, color: v / cmMax > 0.5 ? '#fff' : '#191a23' }}>
                {v.toLocaleString()}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="mt-5 space-y-2">
        <p className="text-[13px] font-medium">Feature importance</p>
        {imp.map((f) => (
          <div key={f.feature}>
            <div className="flex justify-between text-[12.5px]"><span className="truncate">{prettify(f.feature)}</span><span className="tabular-nums text-ink-soft">{f.importance.toFixed(3)}</span></div>
            <div className="mt-1 h-2 rounded-full bg-mist"><div className="h-2 rounded-full bg-ink" style={{ width: `${(Math.abs(f.importance) / impMax) * 100}%` }} /></div>
          </div>
        ))}
      </div>
      {anomaly && anomaly.status === 'completed' && (
        <p className="mt-4 text-[12.5px] text-ink-soft">Unsupervised {anomaly.method}: {anomaly.anomalies.length} rows flagged for review.</p>
      )}
    </Panel>
  )
}

/* ------------------------------------------------------ 5. Timeline ----- */

export function ActivityTimeline({ manifest }: { manifest: Manifest }) {
  const items = useMemo(
    () =>
      findingsOf(manifest)
        .map((f) => ({ f, t: f.time_range?.start ?? '' }))
        .sort((a, b) => (a.t < b.t ? -1 : a.t > b.t ? 1 : 0))
        .slice(0, 12),
    [manifest],
  )
  if (!items.length) return <Empty text="No timestamped detections to place on a timeline." />
  return (
    <Panel icon={Clock} title="Activity timeline" subtitle="Detections in time order">
      <ol className="relative space-y-4 border-l-2 border-ink/15 pl-5">
        {items.map(({ f, t }, i) => (
          <li key={i} className="relative">
            <span className="absolute -left-[27px] top-1.5 size-3 rounded-full bg-lime ring-2 ring-ink" />
            <p className="text-[12px] text-ink-soft tabular-nums">{t || 'no timestamp'}</p>
            <p className="text-[14.5px] font-medium">{f.title}</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <Badge tone={f.severity === 'high' || f.severity === 'critical' ? 'danger' : 'neutral'}>{f.severity || 'info'}</Badge>
              <Badge>{prettify(f.kind || 'other')}</Badge>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  )
}

/* ------------------------------------------------------ 6. Gauge -------- */

export function QualityGauge({ manifest }: { manifest: Manifest }) {
  const q = manifest.quality
  if (!q) return <Empty text="Quality has not been scored for this run." />
  const score = Math.max(0, Math.min(100, q.score))
  const r = 44
  const c = 2 * Math.PI * r
  const color = score >= 85 ? '#2f8f83' : score >= 65 ? '#e8a33d' : '#d4453d'
  const worst = q.missing.columns_with_missing.slice().sort((a, b) => b.missing_pct - a.missing_pct).slice(0, 6)
  return (
    <Panel icon={Gauge} title="Data quality" subtitle={`Grade ${q.grade} · ${q.formula}`}>
      <div className="flex items-center gap-6">
        <svg viewBox="0 0 120 120" className="size-36 shrink-0" role="img" aria-label={`Quality score ${score} of 100`}>
          <circle cx="60" cy="60" r={r} fill="none" stroke="#f4f4f4" strokeWidth="12" />
          <circle cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="12" strokeLinecap="round"
            strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 60 60)" />
          <text x="60" y="66" textAnchor="middle" fontSize="24" fontWeight="600" fill="#191a23">{score}</text>
        </svg>
        <ul className="min-w-0 flex-1 space-y-2.5">
          {worst.map((w) => (
            <li key={w.column}>
              <div className="flex justify-between text-[12.5px]"><span className="truncate">{w.column}</span><span className="tabular-nums text-ink-soft">{w.missing_pct.toFixed(1)}%</span></div>
              <div className="mt-1 h-1.5 rounded-full bg-mist"><div className="h-1.5 rounded-full bg-amber" style={{ width: `${Math.min(100, w.missing_pct)}%` }} /></div>
            </li>
          ))}
          {!worst.length && <li className="text-[13.5px] text-ink-soft">No missing values were found.</li>}
        </ul>
      </div>
    </Panel>
  )
}
