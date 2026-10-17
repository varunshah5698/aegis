import type { LucideIcon } from 'lucide-react'

/**
 * Shared app-surface primitives. These are the building blocks every page in
 * the authenticated shell uses, so panels, headers and stats look identical
 * everywhere instead of each page inventing its own card.
 */

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-[12.5px] font-semibold tracking-[0.12em] text-ink-soft uppercase">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1.5 text-[30px] leading-tight font-semibold tracking-[-0.03em] sm:text-[34px]">
          {title}
        </h1>
        {description && (
          <p className="mt-2 max-w-[74ch] text-[15px] leading-relaxed text-ink-soft">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5">{actions}</div>}
    </header>
  )
}

export function Panel({
  id,
  icon: Icon,
  title,
  subtitle,
  action,
  footer,
  tone = 'paper',
  className = '',
  children,
}: {
  id?: string
  icon?: LucideIcon
  title: string
  subtitle?: string
  action?: React.ReactNode
  footer?: React.ReactNode
  tone?: 'paper' | 'mist' | 'ink'
  className?: string
  children: React.ReactNode
}) {
  const tones: Record<string, string> = {
    paper: 'bg-paper',
    mist: 'bg-mist',
    ink: 'bg-ink text-paper',
  }
  return (
    <section
      id={id}
      className={`panel flex flex-col scroll-mt-24 ${tones[tone]} ${className}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line/10 px-5 py-4">
        <div className="flex min-w-0 items-start gap-3">
          {Icon && (
            <span
              className={`grid size-9 shrink-0 place-items-center rounded-[10px] ${
                'bg-lime text-[#251329]'
              }`}
            >
              <Icon size={16} aria-hidden />
            </span>
          )}
          <div className="min-w-0">
            <h2 className={`text-[16.5px] font-semibold tracking-[-0.01em] ${tone === 'ink' ? 'text-paper' : ''}`}>
              {title}
            </h2>
            {subtitle && (
              <p className={`mt-0.5 text-[13px] leading-snug ${tone === 'ink' ? 'text-paper/60' : 'text-ink-soft'}`}>
                {subtitle}
              </p>
            )}
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </div>
      <div className="flex-1 px-5 py-4">{children}</div>
      {footer && (
        <div
          className={`border-t px-5 py-3 text-[12.5px] ${
            tone === 'ink' ? 'border-paper/15 text-paper/60' : 'border-line/10 text-ink-soft'
          }`}
        >
          {footer}
        </div>
      )}
    </section>
  )
}

export function StatCard({
  icon: Icon,
  label,
  value,
  hint,
  accent = 'bg-lime text-[#251329]',
}: {
  icon?: LucideIcon
  label: string
  value: string
  hint?: string
  accent?: string
}) {
  return (
    <div className="panel flex items-start gap-3.5 p-4.5">
      {Icon && (
        <span className={`grid size-10 shrink-0 place-items-center rounded-[12px] ${accent}`}>
          <Icon size={18} aria-hidden />
        </span>
      )}
      <div className="min-w-0">
        <p className="truncate text-[26px] leading-none font-semibold tabular-nums tracking-[-0.02em]">
          {value}
        </p>
        <p className="mt-1.5 text-[13.5px] font-medium">{label}</p>
        {hint && <p className="mt-0.5 truncate text-[12px] text-ink-soft">{hint}</p>}
      </div>
    </div>
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: React.ReactNode
  tone?: 'neutral' | 'lime' | 'amber' | 'danger' | 'teal' | 'sky' | 'violet'
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-mist text-ink border-line/20',
    lime: 'bg-lime text-ink border-line',
    amber: 'bg-amber/20 text-ink border-amber/50',
    danger: 'bg-danger/12 text-danger border-danger/40',
    teal: 'bg-teal/15 text-ink border-teal/40',
    sky: 'bg-sky-300/30 text-ink border-sky-400/40',
    violet: 'bg-violet-300/30 text-ink border-violet-400/40',
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium whitespace-nowrap ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

export function Empty({ text, action }: { text: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[14px] border border-dashed border-line/25 bg-mist/60 px-5 py-10 text-center">
      <p className="max-w-[46ch] text-[14px] text-ink-soft">{text}</p>
      {action}
    </div>
  )
}

export function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-line/12 bg-mist/70 px-3.5 py-2.5">
      <dt className="text-[11.5px] tracking-wide text-ink-soft uppercase">{label}</dt>
      <dd className="mt-0.5 truncate text-[15px] font-medium" title={value}>
        {value}
      </dd>
    </div>
  )
}

/** Recharts tooltip styled for the app surfaces. */
export function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: { name?: string; value?: number | string; color?: string }[]
  label?: string
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[12px] border border-line/20 bg-paper px-3 py-2 text-[12.5px] shadow-lg">
      {label != null && label !== '' && <p className="font-semibold">{label}</p>}
      {payload.map((p, i) => (
        <p key={i} className="flex items-center gap-1.5 tabular-nums">
          {p.color && <span className="size-2 rounded-full" style={{ background: p.color }} />}
          {p.name ? `${p.name}: ` : ''}
          <b>
            {typeof p.value === 'number'
              ? p.value.toLocaleString(undefined, { maximumFractionDigits: 3 })
              : p.value}
          </b>
        </p>
      ))}
    </div>
  )
}

export const CHART_SERIES = [
  '#FA9D72',
  '#FFF0E2',
  '#6F4679',
  '#C9A6CF',
  '#8A5A94',
  '#D6805A',
  '#4EC9A8',
  '#E8A33D',
]

export function prettify(s: string) {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

export function compactNumber(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return String(v ?? '')
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`
  return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2)
}

export function formatWhen(iso: string | null) {
  if (!iso) return 'unscheduled'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}
