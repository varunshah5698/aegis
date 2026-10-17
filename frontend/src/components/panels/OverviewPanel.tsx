import { AlertTriangle, Info, ShieldCheck } from 'lucide-react'
import { AiSection } from '../AiPanel'
import type { Manifest } from '../../lib/types'

/** KPI band + ranked key findings, straight from the persisted manifest. */
export default function OverviewPanel({ manifest, runId }: { manifest: Manifest; runId?: string }) {
  const ov = manifest.overview ?? {}
  const findings = manifest.findings?.key_findings ?? []
  const q = manifest.quality
  const tc = ov.time_coverage as { start?: string; end?: string; span_days?: number } | null

  const kpis: { label: string; value: string; hint?: string }[] = [
    { label: 'Rows', value: num(ov.row_count).toLocaleString(), hint: ov.sampled ? 'exact' : 'all rows' },
    { label: 'Columns', value: num(ov.column_count).toLocaleString() },
    { label: 'Quality score', value: q ? `${q.score}/100` : '—', hint: q ? `grade ${q.grade}` : undefined },
    { label: 'Missing cells', value: `${num(ov.missing_pct)}%` },
    { label: 'Duplicate rows', value: `${num(ov.duplicate_pct)}%` },
    {
      label: 'Numeric / categorical',
      value: `${num(ov.numeric_columns)} / ${num(ov.categorical_columns)}`,
    },
    {
      label: 'Processing time',
      value: `${num(ov.processing_seconds)}s`,
      hint: ov.sampled ? 'sampled' : undefined,
    },
    { label: 'File size', value: bytes(num(ov.file_size_bytes)) },
  ]

  const kindLabel: Record<string, string> = {
    observed: 'Observed fact',
    statistical_inference: 'Statistical inference',
    model_output: 'Model output',
    rule_trigger: 'Rule trigger',
  }

  return (
    <div className="space-y-6">
      {runId && <AiSection runId={runId} section="overview" />}

      {/* --------------------------------------------------------- KPI band */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {kpis.map((k) => (
          <div key={k.label} className="panel bg-mist/60 px-4 py-3.5">
            <p className="text-[12.5px] text-ink-soft">{k.label}</p>
            <p className="mt-1 text-[24px] leading-tight font-medium tabular-nums">{k.value}</p>
            {k.hint && <p className="mt-0.5 text-[11.5px] text-ink-soft">{k.hint}</p>}
          </div>
        ))}
      </div>

      {tc && (
        <div className="rounded-[14px] border border-line/30 px-5 py-4 text-[14.5px]">
          <span className="font-medium">Time coverage: </span>
          {tc.start} → {tc.end} <span className="text-ink-soft">({tc.span_days} days)</span>
        </div>
      )}

      {String(ov.sampling_note ?? '') && (
        <p className="flex items-start gap-2 text-[14px] text-ink-soft">
          <Info size={15} className="mt-0.5 shrink-0" aria-hidden />
          {String(ov.sampling_note)}
        </p>
      )}

      {/* -------------------------------------------------------- findings */}
      <div>
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-[28px] font-medium tracking-[-0.03em]">
            Most important <span className="marker">findings</span>
          </h2>
          <span className="text-[14px] text-ink-soft">
            {findings.length} ranked by module priority
          </span>
        </div>

        <ol className="mt-5 space-y-4">
          {findings.map((f, i) => (
            <li key={f.id + i} className="panel p-5">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`grid size-8 place-items-center rounded-full text-[13px] font-semibold ring-1 ring-line ${
                    i === 0 ? 'bg-lime' : 'bg-mist'
                  }`}
                >
                  {i + 1}
                </span>
                <span className="chip bg-mist text-[12px]">{f.category}</span>
                <KindBadge kind={f.kind} label={kindLabel[f.kind] ?? f.kind} />
                {f.severity && <SeverityChip severity={f.severity} />}
              </div>
              <h3 className="mt-3 text-[18.5px] leading-snug font-medium">{f.title}</h3>
              {f.detail && (
                <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{f.detail}</p>
              )}
              {f.evidence && (
                <p className="mt-3 border-t border-line/20 pt-3 text-[13.5px] text-ink-soft">
                  <span className="font-medium text-ink">Evidence: </span>
                  {f.evidence}
                </p>
              )}
            </li>
          ))}
          {!findings.length && (
            <li className="panel p-5 text-[15px] text-ink-soft">
              No finding crossed the reporting threshold for this dataset.
            </li>
          )}
        </ol>
      </div>

      {/* --------------------------------------------------- limitations */}
      <div className="panel bg-ink p-6 text-paper">
        <h3 className="flex items-center gap-2 text-[18px] font-medium text-lime">
          <ShieldCheck size={17} aria-hidden />
          What these results are — and are not
        </h3>
        <ul className="mt-4 grid gap-2.5 text-[14.5px] leading-relaxed text-paper/80 md:grid-cols-2">
          {[...(manifest.limitations ?? []), ...(manifest.plan?.limitations as string[] ?? [])].map(
            (l, i) => (
              <li key={i} className="flex gap-2.5">
                <span className="mt-[9px] size-1.5 shrink-0 rounded-full bg-lime" />
                {l}
              </li>
            ),
          )}
        </ul>
      </div>
    </div>
  )
}

function KindBadge({ kind, label }: { kind: string; label: string }) {
  const tone =
    kind === 'observed'
      ? 'bg-paper'
      : kind === 'statistical_inference'
        ? 'bg-lime'
        : kind === 'model_output'
          ? 'bg-mist'
          : 'bg-amber/25'
  return <span className={`chip ${tone} text-[12px]`}>{label}</span>
}

export function SeverityChip({ severity }: { severity: string }) {
  const tone =
    severity === 'high'
      ? 'border-danger text-danger'
      : severity === 'medium'
        ? 'border-amber text-amber'
        : 'border-line/40 text-ink-soft'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium ${tone}`}>
      <AlertTriangle size={11} aria-hidden />
      {severity} priority
    </span>
  )
}

function num(v: unknown): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function bytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${n} B`
}
