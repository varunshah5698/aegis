import { useCallback, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowRight,
  ArrowUpRight,
  BadgeCheck,
  CalendarCheck,
  CheckCircle2,
  CreditCard,
  Database,
  FileSpreadsheet,
  FileText,
  FolderSearch,
  History,
  LayoutDashboard,
  MessagesSquare,
  ShieldCheck,
  Sparkles,
  UploadCloud,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { DatasetOut, HealthInfo, ValidationOut } from '../lib/types'

/* ------------------------------------------------------------------ */
/* Content                                                               */
/* ------------------------------------------------------------------ */

const SECTION_NAV: [string, string][] = [
  ['#product', 'Product'],
  ['#how', 'How it works'],
  ['#try', 'Live demo'],
  ['#after-signin', 'After sign-in'],
  ['#pricing', 'Pricing'],
  ['#faq', 'FAQ'],
]

const CAPABILITIES = [
  'Anomaly detection',
  'Money-flow networks',
  'Schema inference',
  'Interactive charts',
  'ML classifiers',
  'Audit-ready reports',
  'Data-quality scoring',
  'Pattern library',
]

const FEATURES: { icon: typeof LayoutDashboard; accent: string; title: string; body: string; tag: string }[] = [
  {
    icon: LayoutDashboard,
    accent: 'bg-lime text-ink',
    title: 'Your own dashboard',
    body: 'Every file you analyze becomes a personal workspace with charts, findings, and reports waiting for you when you return.',
    tag: 'After sign-in',
  },
  {
    icon: FolderSearch,
    accent: 'bg-sky-300 text-ink',
    title: 'Browse and search the catalog',
    body: 'Filter past analyses by status, search by file name, and reopen any completed result with a single click.',
    tag: 'After sign-in',
  },
  {
    icon: FileText,
    accent: 'bg-violet-300 text-ink',
    title: 'A detail page for every item',
    body: 'Each dataset gets one home: inferred schema, quality score, record browser, and downloads side by side.',
    tag: 'After sign-in',
  },
  {
    icon: CalendarCheck,
    accent: 'bg-amber-300 text-ink',
    title: 'Book or schedule a review',
    body: 'Reserve time with an analyst directly from a finding. Choose a slot, receive a confirmation, done.',
    tag: 'Booking',
  },
  {
    icon: CreditCard,
    accent: 'bg-teal-300 text-ink',
    title: 'Pay and check out',
    body: 'Upgrade when the work demands more. Simple plans, one checkout step, and receipts delivered by email.',
    tag: 'Checkout',
  },
  {
    icon: UploadCloud,
    accent: 'bg-rose-300 text-ink',
    title: 'Post and upload your own content',
    body: 'Add new CSV files at any moment. Instant validation tells you exactly what parsed and what needs attention.',
    tag: 'Try below',
  },
  {
    icon: MessagesSquare,
    accent: 'bg-orange-300 text-ink',
    title: 'Message and comment',
    body: 'Discuss a flagged transaction, ask a follow-up question, and keep the thread attached to the evidence.',
    tag: 'After sign-in',
  },
  {
    icon: ShieldCheck,
    accent: 'bg-fuchsia-300 text-ink',
    title: 'Admin area',
    body: 'Manage customers, plans, and workspaces from a single console with a complete audit trail behind it.',
    tag: 'Admins',
  },
]

const STEPS: [string, string][] = [
  ['Understand', 'Aegis reads your file and infers column types, meanings, and structure. No configuration or mapping required.'],
  ['Prepare', 'Missing values, duplicates, invalid records, and outliers are measured and reported. Nothing is changed silently.'],
  ['Analyze', 'Statistics, charts, machine-learning checks, and financial modules run as real background jobs you can watch.'],
  ['Explain', 'Every finding ships with its method, thresholds, and limitations, plus a downloadable report you can share.'],
]

const PROCESS_STAGES = [
  'Upload validation',
  'CSV parsing',
  'Schema inference',
  'Semantic mapping',
  'Data quality',
  'Statistical profiling',
  'Analysis planning',
  'Machine learning',
  'Visualizations',
  'Findings and report',
]

const AFTER_SIGNIN: [string, string, string][] = [
  ['01', 'Sign in with a passcode', 'Enter your email and Aegis sends a one-time passcode. No password to create, remember, or reset. Sessions are secure cookies.'],
  ['02', 'Land on your dashboard', 'Your catalog, detail pages, uploads, messages, and comments live here. Everything is scoped to your account.'],
  ['03', 'Book, pay, and manage', 'Schedule review time, check out with a plan upgrade, and administer customers and workspaces from the admin area.'],
]

const TIERS: { name: string; price: string; per: string; blurb: string; cta: string; hot: boolean; points: string[] }[] = [
  {
    name: 'Starter',
    price: '$0',
    per: 'free forever',
    blurb: 'For exploring Aegis with your own files.',
    cta: 'Start free',
    hot: false,
    points: ['1 personal workspace', '3 analyses per month', 'Shared catalog access', 'CSV and JSON exports'],
  },
  {
    name: 'Professional',
    price: '$29',
    per: 'per analyst / month',
    blurb: 'For people who work with data every day.',
    cta: 'Start 14-day trial',
    hot: true,
    points: ['Unlimited analyses', 'Booking and checkout', 'Priority compute queue', 'Markdown and XLSX reports'],
  },
  {
    name: 'Business',
    price: 'Custom',
    per: 'annual billing',
    blurb: 'For teams with compliance requirements.',
    cta: 'Talk to us',
    hot: false,
    points: ['Admin console and SSO', 'Audit exports', 'Dedicated support', 'Data-retention controls'],
  },
]

const FAQS: [string, string][] = [
  [
    'What files can I upload?',
    'Comma-separated CSV files up to 200 MB, 500,000 rows, and 1,000 columns. Excel workbooks need one extra step: export the sheet as CSV first, then drop it in below.',
  ],
  [
    'Do I need an account?',
    'You can browse this page and try the demo without one. Signing in takes a single emailed passcode — no password — and unlocks your dashboard, history, booking, and checkout.',
  ],
  [
    'Where does my data go?',
    'Files are parsed and stored on the Aegis server inside your workspace. Nothing is sent to third-party AI or market-data providers unless an integration is explicitly configured, and the app tells you when it is not.',
  ],
  [
    'How much should I trust a finding?',
    'Findings are statistical patterns, each delivered with its method, thresholds, and limitations. Treat them as starting points for human review, never as determinations of wrongdoing.',
  ],
  [
    'Can I take my results elsewhere?',
    'Yes. Records, charts, and reports export as JSON, CSV, Markdown, and XLSX, and every export carries the same provenance note as the screen it came from.',
  ],
]

const BARS = [34, 52, 44, 68, 58, 82, 64, 92, 74, 60, 86, 70]

/* ------------------------------------------------------------------ */
/* Page                                                                  */
/* ------------------------------------------------------------------ */

export default function Landing() {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)

  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [validation, setValidation] = useState<ValidationOut | null>(null)
  const [starting, setStarting] = useState(false)

  const { data: health } = useQuery<HealthInfo>({
    queryKey: ['health'],
    queryFn: () => api.get<HealthInfo>('/api/health'),
    staleTime: 300_000,
  })

  const { data: demo } = useQuery<{ available: boolean; size_bytes?: number }>({
    queryKey: ['demo'],
    queryFn: () => api.get<{ available: boolean; size_bytes?: number }>('/api/demo/exists'),
    staleTime: 60_000,
  })

  const { data: datasets, refetch: refetchDatasets } = useQuery<DatasetOut[]>({
    queryKey: ['datasets'],
    queryFn: () => api.get<DatasetOut[]>('/api/datasets'),
    staleTime: 15_000,
  })

  const maxMB = Math.round((health?.limits?.max_upload_bytes ?? 209715200) / (1024 * 1024))

  const upload = useMutation<ValidationOut, ApiError, File>({
    mutationFn: (f) => {
      const form = new FormData()
      form.append('file', f)
      setProgress(8)
      return api.postForm<ValidationOut>('/api/datasets/upload', form).then((r) => {
        setProgress(100)
        return r
      })
    },
    onSuccess: (result) => {
      setValidation(result)
      setError('')
      setProgress(null)
      void refetchDatasets()
    },
    onError: (err) => {
      setValidation(null)
      setProgress(null)
      setError(err.message || 'Upload failed.')
    },
  })

  const pickFile = useCallback(
    (f: File | null | undefined) => {
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
      upload.mutate(f)
    },
    [health, maxMB, upload],
  )

  async function startAnalysis(datasetId: string) {
    setStarting(true)
    setError('')
    try {
      const res = await api.post<{ run_id: string; status: string }>('/api/runs/start', {
        dataset_id: datasetId,
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

  async function useDemo() {
    setError('')
    setValidation(null)
    setFile(null)
    setProgress(8)
    try {
      const res = await fetch('/api/demo/download', { credentials: 'include' })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new ApiError(res.status, body?.detail || 'Demo dataset unavailable.')
      }
      const blob = await res.blob()
      const f = new File([blob], 'aegis_demo_dataset.csv', { type: 'text/csv' })
      setFile(f)
      const form = new FormData()
      form.append('file', f)
      form.append('is_demo', 'true')
      const result = await api.postForm<ValidationOut>('/api/datasets/upload', form)
      setValidation(result)
      setProgress(100)
      void refetchDatasets()
    } catch (e) {
      setProgress(null)
      setError(e instanceof ApiError ? e.message : 'Demo dataset could not be loaded.')
    }
  }

  return (
    <div className="bg-ink text-paper">
      {/* In-page navigation: the structure of this page at a glance */}
      <nav aria-label="On this page" className="sticky top-[86px] z-30 border-b border-paper/12 bg-ink/95 backdrop-blur">
        <div className="shell flex items-center gap-1 overflow-x-auto py-2.5 text-[14px] font-medium">
          {SECTION_NAV.map(([href, label]) => (
            <a
              key={href}
              href={href}
              className="shrink-0 rounded-full px-3.5 py-1.5 text-paper/70 transition hover:bg-white/[0.06] hover:text-lime"
            >
              {label}
            </a>
          ))}
        </div>
      </nav>

      {/* ------------------------------------------------------- hero */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              'radial-gradient(52rem 30rem at 85% -10%, rgba(185,255,102,0.16), transparent 60%), radial-gradient(40rem 26rem at -10% 110%, rgba(167,139,250,0.14), transparent 60%)',
          }}
        />
        <div className="shell relative grid gap-12 pt-14 pb-14 lg:grid-cols-[1fr_1.05fr] lg:gap-14 lg:pt-20 lg:pb-16">
          <div>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-lime/60 px-3 py-1 text-[13px] font-medium text-lime">
              <Sparkles size={14} aria-hidden />
              Aegis · AI financial intelligence
            </span>
            <h1 className="mt-6 text-[46px] leading-[1.02] font-medium tracking-[-0.035em] sm:text-[64px]">
              Your data knows something. <span className="text-lime">Aegis finds out what.</span>
            </h1>
            <p className="mt-6 max-w-[54ch] text-[18px] leading-relaxed text-paper/75">
              Upload a CSV of financial transactions and receive a complete investigation
              workspace: hidden patterns uncovered, suspicious activity flagged, interactive
              visualizations generated, and insights you can act on. No SQL, no setup,
              no chart wrangling.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/login" className="btn btn-lime">
                Get started free
                <span className="grid size-7 place-items-center rounded-full bg-ink text-lime">
                  <ArrowRight size={14} aria-hidden />
                </span>
              </Link>
              <a
                href="#try"
                className="inline-flex items-center gap-3 rounded-[14px] border border-paper/30 px-6 py-3 text-[17px] font-medium text-paper transition hover:border-lime hover:text-lime"
              >
                Try the live demo
              </a>
            </div>
            <p className="mt-4 text-[14px] text-paper/60">
              Passwordless sign-in with a one-time email passcode · Your dashboard, catalog, and history wait behind it
            </p>

            <dl className="mt-8 grid max-w-[34rem] grid-cols-2 gap-3 text-[14px] sm:grid-cols-4">
              <Stat label="Analysis stages" value="16" />
              <Stat label="Demo rows" value="50k" />
              <Stat label="Report formats" value="4" />
              <Stat label="Data shared" value="None" />
            </dl>
          </div>

          {/* ------------------------------------------ hero visual */}
          <div className="relative" aria-hidden>
            <div className="rounded-[32px] border border-paper/15 bg-white/[0.04] p-6 backdrop-blur sm:p-7">
              <div className="flex items-center justify-between">
                <div className="flex gap-1.5">
                  <span className="size-2.5 rounded-full bg-rose-300" />
                  <span className="size-2.5 rounded-full bg-amber-300" />
                  <span className="size-2.5 rounded-full bg-lime" />
                </div>
                <p className="font-mono text-[12px] text-paper/50">aegis · workspace preview</p>
              </div>

              <div className="mt-5 grid grid-cols-3 gap-3">
                {[
                  ['Flagged flows', '184', 'text-lime'],
                  ['Patterns found', '39', 'text-violet-300'],
                  ['Quality score', '98.6', 'text-sky-300'],
                ].map(([label, value, tone]) => (
                  <div key={label} className="rounded-[16px] border border-paper/12 bg-ink/60 px-4 py-3">
                    <p className={`text-[24px] font-semibold tabular-nums ${tone}`}>{value}</p>
                    <p className="mt-0.5 text-[12px] text-paper/60">{label}</p>
                  </div>
                ))}
              </div>

              <div className="mt-3 rounded-[16px] border border-paper/12 bg-ink/60 p-4">
                <div className="flex h-28 items-end gap-1.5">
                  {BARS.map((h, i) => (
                    <span
                      key={i}
                      style={{ height: `${h}%` }}
                      className={`flex-1 rounded-t-[5px] ${
                        i === 7 ? 'bg-lime' : i % 3 === 0 ? 'bg-violet-300/80' : 'bg-sky-300/60'
                      }`}
                    />
                  ))}
                </div>
                <p className="mt-2 font-mono text-[11px] text-paper/45">volume by week · structuring band highlighted</p>
              </div>

              <ul className="mt-3 space-y-2 text-[13px]">
                {[
                  ['bg-lime', 'Rapid pass-through — 3 hops in 41 minutes'],
                  ['bg-amber-300', 'Round-amount burst sitting just under the limit'],
                ].map(([dot, text]) => (
                  <li
                    key={text}
                    className="flex items-center gap-3 rounded-[12px] border border-paper/12 bg-ink/60 px-4 py-2.5"
                  >
                    <span className={`size-2.5 shrink-0 rounded-full ${dot}`} />
                    <span className="text-paper/85">{text}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="absolute -top-4 -right-2 hidden rotate-3 rounded-[14px] border border-line bg-lime px-4 py-2 text-[13px] font-semibold text-ink sm:block">
              +3 patterns found
            </div>
            <div className="absolute -bottom-4 -left-2 hidden -rotate-2 rounded-[14px] border border-paper/20 bg-ink px-4 py-2 text-[13px] text-paper/85 sm:block">
              Report ready · XLSX + Markdown
            </div>
          </div>
        </div>

        {/* ----------------------------------------------- capability strip */}
        <div className="relative border-y border-paper/12 bg-white/[0.02]">
          <div className="shell flex flex-wrap items-center gap-x-8 gap-y-3 py-5 text-[14px] font-medium text-paper/70">
            {CAPABILITIES.map((c) => (
              <span key={c} className="inline-flex items-center gap-2">
                <BadgeCheck size={15} className="text-lime" aria-hidden />
                {c}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* -------------------------------------------------- product grid */}
      <section id="product" className="shell scroll-mt-36 pt-20">
        <Eyebrow>One account, everything included</Eyebrow>
        <h2 className="mt-5 max-w-[22ch] text-[38px] leading-[1.08] font-medium tracking-[-0.03em] sm:text-[46px]">
          Built for customers, <span className="text-lime">ready for business.</span>
        </h2>
        <p className="mt-5 max-w-[64ch] text-[17px] leading-relaxed text-paper/70">
          Sign in once and the full product opens up: your personal dashboard, a searchable
          catalog of past work, detail pages, booking, checkout, uploads, messages, and an
          admin console. Everything below is included — most of it unlocks the moment you sign in.
        </p>

        <div className="mt-10 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {FEATURES.map(({ icon: Icon, accent, title, body, tag }) => (
            <article
              key={title}
              className="flex flex-col rounded-[26px] border border-paper/12 bg-white/[0.04] p-6 transition-colors hover:border-paper/30"
            >
              <div className="flex items-center justify-between">
                <span className={`grid size-11 place-items-center rounded-[12px] ${accent}`}>
                  <Icon size={20} aria-hidden />
                </span>
                <span className="rounded-full border border-paper/20 px-2.5 py-1 text-[11.5px] font-medium text-paper/60">
                  {tag}
                </span>
              </div>
              <h3 className="mt-4 text-[19px] font-medium">{title}</h3>
              <p className="mt-2 text-[14.5px] leading-relaxed text-paper/65">{body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------- how it works */}
      <section id="how" className="shell scroll-mt-36 pt-20">
        <Eyebrow>How it works</Eyebrow>
        <h2 className="mt-5 max-w-[20ch] text-[38px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[44px]">
          From raw CSV to <span className="text-lime">answers in four steps</span>
        </h2>
        <div className="mt-10 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <article key={title} className="rounded-[26px] border border-paper/12 bg-white/[0.04] p-7">
              <span className="grid size-11 place-items-center rounded-[12px] bg-lime text-[17px] font-semibold text-ink">
                {i + 1}
              </span>
              <h3 className="mt-5 text-[22px] font-medium">{title}</h3>
              <p className="mt-3 text-[15.5px] leading-relaxed text-paper/65">{body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------ live demo */}
      <section id="try" className="shell scroll-mt-36 pt-20">
        <div className="grid items-end justify-between gap-6 lg:grid-cols-[1fr_auto]">
          <div>
            <Eyebrow>Live demo · no account needed</Eyebrow>
            <h2 className="mt-5 max-w-[20ch] text-[38px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[44px]">
              Start with a file. <span className="text-lime">Leave with answers.</span>
            </h2>
            <p className="mt-4 max-w-[60ch] text-[16px] leading-relaxed text-paper/65">
              Drop a CSV below to see validation and kick off a real analysis. Demo runs are public
              to this browser — <Link to="/login" className="text-lime underline decoration-lime/50 underline-offset-4 hover:decoration-lime">sign in</Link> to
              keep workspaces on your dashboard, revisit them later, and unlock booking and checkout.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-3 rounded-[14px] border border-paper/30 px-6 py-3 text-[16px] font-medium text-paper transition hover:border-lime hover:text-lime disabled:opacity-45"
            onClick={useDemo}
            disabled={!demo?.available}
            title={demo?.available ? 'Load the 50k-row synthetic reference file' : 'Generate it with scripts/generate_dataset.py'}
          >
            <Database size={16} aria-hidden />
            {demo?.available ? 'Try the demo dataset' : 'Demo not generated'}
          </button>
        </div>

        <div className="mt-8 rounded-[32px] border border-paper/15 bg-white/[0.04] p-6 sm:p-8">
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
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              pickFile(e.dataTransfer.files?.[0])
            }}
            className={`flex min-h-[240px] w-full flex-col items-center justify-center gap-4 rounded-[24px] border-2 border-dashed px-6 py-10 text-center transition-colors ${
              dragging ? 'border-lime bg-lime/10' : 'border-paper/30 bg-ink/60'
            }`}
            aria-label="Drop a CSV file or click to browse"
          >
            <span className="grid size-16 place-items-center rounded-full bg-lime text-ink">
              <UploadCloud size={28} aria-hidden />
            </span>
            <span className="text-[19px] font-medium">
              Drag one CSV here, or click to browse
            </span>
            <span className="text-[14px] text-paper/60">
              .csv · up to {maxMB} MB · {(health?.limits?.max_rows ?? 500000).toLocaleString()} rows
              · {maxColumns(health)} columns
            </span>
          </button>

          {/* status region */}
          <div aria-live="polite" className="mt-5">
            {progress !== null && !validation && (
              <div className="flex items-center gap-4 rounded-[14px] border border-paper/20 bg-ink/60 px-4 py-3">
                <span className="size-3 shrink-0 animate-pulse rounded-full bg-lime" />
                <span className="text-[15px]">
                  Uploading and validating <b className="break-all">{file?.name}</b>…
                </span>
              </div>
            )}

            {error && (
              <div className="flex items-start gap-3 rounded-[14px] border border-danger bg-danger/15 px-4 py-3">
                <AlertTriangle size={18} className="mt-0.5 shrink-0 text-danger" aria-hidden />
                <div>
                  <p className="text-[15px] font-medium text-danger">Upload rejected</p>
                  <p className="mt-1 text-[14px] text-paper/70">{error}</p>
                  <button
                    type="button"
                    className="mt-2 text-[14px] font-medium text-paper underline decoration-lime decoration-[3px] underline-offset-4"
                    onClick={() => {
                      setError('')
                      setFile(null)
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {validation && (
              <div className="card p-5 text-ink">
                <div className="flex items-center gap-3">
                  <CheckCircle2 size={20} className="text-teal" aria-hidden />
                  <p className="text-[16px] font-medium break-all">{validation.filename}</p>
                </div>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-[14px] sm:grid-cols-4">
                  <Fact label="Rows" value={validation.row_count.toLocaleString()} />
                  <Fact label="Columns" value={String(validation.column_count)} />
                  <Fact label="Delimiter" value={describeDelimiter(validation.delimiter)} />
                  <Fact label="Encoding" value={validation.encoding} />
                </dl>

                {validation.warnings.length > 0 && (
                  <ul className="mt-4 space-y-1.5 text-[13.5px] text-ink-soft">
                    {validation.warnings.slice(0, 4).map((w) => (
                      <li key={w} className="flex gap-2">
                        <AlertTriangle size={14} className="mt-1 shrink-0 text-amber" aria-hidden />
                        {w}
                      </li>
                    ))}
                  </ul>
                )}

                {validation.sample_rows.length > 0 && (
                  <div className="scroll-ink mt-4 overflow-x-auto rounded-[14px] border border-line/30">
                    <table className="table-grid text-[12.5px]">
                      <thead>
                        <tr>
                          {validation.headers.slice(0, 8).map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                          {validation.headers.length > 8 && <th>…</th>}
                        </tr>
                      </thead>
                      <tbody>
                        {validation.sample_rows.slice(0, 4).map((row, i) => (
                          <tr key={i}>
                            {row.slice(0, 8).map((cell, j) => (
                              <td key={j} className="max-w-[180px] truncate">
                                {cell}
                              </td>
                            ))}
                            {row.length > 8 && <td>…</td>}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                <div className="mt-5 flex flex-wrap gap-3">
                  <button
                    type="button"
                    className="btn"
                    disabled={starting}
                    onClick={() => startAnalysis(validation.dataset_id)}
                  >
                    {starting ? 'Starting…' : 'Start analysis'}
                    <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                      <ArrowRight size={14} aria-hidden />
                    </span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setValidation(null)
                      setFile(null)
                      inputRef.current?.click()
                    }}
                  >
                    Replace file
                  </button>
                  <button
                    type="button"
                    className="btn btn-ghost"
                    onClick={() => {
                      setValidation(null)
                      setFile(null)
                      setError('')
                    }}
                  >
                    Cancel
                  </button>
                </div>
                <p className="mt-4 text-[13.5px] text-ink-soft">
                  Starting an analysis opens the processing view. If you are signed out you will be
                  asked to sign in first so the workspace is saved to your account.
                </p>
              </div>
            )}
          </div>
        </div>

        <p id="privacy" className="mt-4 max-w-[64ch] scroll-mt-36 text-[14px] leading-relaxed text-paper/55">
          Files are parsed and stored on the server inside your workspace. Nothing is
          sent to third-party AI or market-data providers unless an integration is
          explicitly configured — and the app says so when it is not.
        </p>
      </section>

      {/* -------------------------------------------------- pipeline strip */}
      <section id="process" className="shell scroll-mt-36 pt-16">
        <div className="rounded-[32px] border border-lime/40 bg-lime/[0.06] p-8 sm:p-10">
          <div className="flex flex-wrap items-baseline justify-between gap-4">
            <h2 className="text-[28px] font-medium text-lime sm:text-[32px]">
              Real backend stages, not animations
            </h2>
            <p className="max-w-[46ch] text-[15px] text-paper/70">
              The processing screen reports each job as the worker completes it.
              What you see below is what actually executes.
            </p>
          </div>
          <ol className="mt-7 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {PROCESS_STAGES.map((s, i) => (
              <li
                key={s}
                className="flex items-center gap-3 rounded-[14px] border border-paper/15 bg-ink/60 px-4 py-3 text-[14.5px]"
              >
                <span className="font-mono tabular-nums text-lime">
                  {String(i + 1).padStart(2, '0')}
                </span>
                {s}
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* --------------------------------------------- after sign-in flow */}
      <section id="after-signin" className="shell scroll-mt-36 pt-20">
        <Eyebrow>After this page · sign-in required</Eyebrow>
        <h2 className="mt-5 max-w-[22ch] text-[38px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[44px]">
          Sign in <span className="text-lime">and the product opens up.</span>
        </h2>
        <p className="mt-5 max-w-[64ch] text-[17px] leading-relaxed text-paper/70">
          This landing page is public. Everything past it belongs to your account: by hook or by
          crook, workspaces, bookings, payments, and messages are tied to the person who signed in.
          Signed-out visitors are sent to sign-in first, then returned to where they were headed.
        </p>
        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {AFTER_SIGNIN.map(([n, title, body]) => (
            <article key={n} className="rounded-[26px] border border-paper/12 bg-white/[0.04] p-7">
              <p className="font-mono text-[14px] text-lime">{n}</p>
              <h3 className="mt-3 text-[22px] font-medium">{title}</h3>
              <p className="mt-3 text-[15.5px] leading-relaxed text-paper/65">{body}</p>
            </article>
          ))}
        </div>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/login" className="btn btn-lime">
            Continue with passcode
            <span className="grid size-7 place-items-center rounded-full bg-ink text-lime">
              <ArrowRight size={14} aria-hidden />
            </span>
          </Link>
          <a
            href="#pricing"
            className="inline-flex items-center gap-3 rounded-[14px] border border-paper/30 px-6 py-3 text-[17px] font-medium text-paper transition hover:border-lime hover:text-lime"
          >
            Compare plans
          </a>
        </div>
      </section>

      {/* ------------------------------------------------------ pricing */}
      <section id="pricing" className="shell scroll-mt-36 pt-20">
        <Eyebrow>Pricing</Eyebrow>
        <h2 className="mt-5 max-w-[20ch] text-[38px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[44px]">
          Start free. <span className="text-lime">Pay when it earns its keep.</span>
        </h2>
        <p className="mt-5 max-w-[60ch] text-[17px] leading-relaxed text-paper/70">
          Prices in USD. Checkout unlocks after sign-in from your own dashboard.
          Every plan includes the catalog, exports, and the audit trail.
        </p>

        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {TIERS.map((t) => (
            <article
              key={t.name}
              className={`relative rounded-[26px] border p-7 ${
                t.hot
                  ? 'border-lime bg-lime/[0.08]'
                  : 'border-paper/12 bg-white/[0.04]'
              }`}
            >
              {t.hot && (
                <span className="absolute -top-3.5 left-7 rounded-full bg-lime px-3 py-1 text-[12.5px] font-semibold text-ink">
                  Most popular
                </span>
              )}
              <h3 className="text-[20px] font-medium">{t.name}</h3>
              <p className="mt-3">
                <span className="text-[42px] font-medium tracking-tight">{t.price}</span>{' '}
                <span className="text-[14px] text-paper/60">{t.per}</span>
              </p>
              <p className="mt-2 text-[15px] text-paper/65">{t.blurb}</p>
              <ul className="mt-5 space-y-2.5 text-[14.5px] text-paper/80">
                {t.points.map((p) => (
                  <li key={p} className="flex gap-2.5">
                    <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-lime" aria-hidden />
                    {p}
                  </li>
                ))}
              </ul>
              <Link
                to="/login"
                className={`mt-7 inline-flex w-full items-center justify-center gap-2 rounded-[14px] px-6 py-3 text-[16px] font-medium transition ${
                  t.hot
                    ? 'bg-lime text-ink hover:brightness-105'
                    : 'border border-paper/30 text-paper hover:border-lime hover:text-lime'
                }`}
              >
                {t.cta}
                <ArrowUpRight size={16} aria-hidden />
              </Link>
            </article>
          ))}
        </div>
      </section>

      {/* ---------------------------------------------------------- faq */}
      <section id="faq" className="shell scroll-mt-36 pt-20">
        <Eyebrow>FAQ</Eyebrow>
        <h2 className="mt-5 max-w-[20ch] text-[38px] leading-[1.1] font-medium tracking-[-0.03em] sm:text-[44px]">
          Questions, <span className="text-lime">answered.</span>
        </h2>
        <div className="mt-8 grid gap-3 lg:grid-cols-2">
          {FAQS.map(([q, a]) => (
            <details
              key={q}
              className="group rounded-[20px] border border-paper/12 bg-white/[0.04] px-6 py-5"
            >
              <summary className="cursor-pointer list-none text-[17px] font-medium marker:hidden [&::-webkit-details-marker]:hidden">
                <span className="flex items-center justify-between gap-4">
                  {q}
                  <ArrowRight
                    size={17}
                    aria-hidden
                    className="shrink-0 text-lime transition-transform group-open:rotate-90"
                  />
                </span>
              </summary>
              <p className="mt-3 text-[15px] leading-relaxed text-paper/65">{a}</p>
            </details>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------ final cta */}
      <section className="shell pt-20">
        <div
          className="relative overflow-hidden rounded-[32px] border border-paper/15 px-8 py-14 text-center sm:px-12"
          style={{
            background:
              'radial-gradient(36rem 18rem at 50% -30%, rgba(185,255,102,0.22), transparent 65%), #14151c',
          }}
        >
          <h2 className="mx-auto max-w-[18ch] text-[36px] leading-[1.08] font-medium tracking-[-0.03em] sm:text-[48px]">
            Bring a CSV. <span className="text-lime">Leave with answers.</span>
          </h2>
          <p className="mx-auto mt-4 max-w-[52ch] text-[16px] text-paper/70">
            Your first workspace is free and the demo dataset is ready when you are.
            Sign-in takes one emailed passcode — no password to invent or forget.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <a href="#try" className="btn btn-lime">
              Try the demo
              <span className="grid size-7 place-items-center rounded-full bg-ink text-lime">
                <ArrowRight size={14} aria-hidden />
              </span>
            </a>
            <Link
              to="/login"
              className="inline-flex items-center gap-3 rounded-[14px] border border-paper/30 px-6 py-3 text-[17px] font-medium text-paper transition hover:border-lime hover:text-lime"
            >
              Sign in
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------ history */}
      <section className="shell pt-16 pb-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <h2 className="flex items-center gap-3 text-[30px] font-medium tracking-[-0.03em]">
            <History size={26} aria-hidden />
            Recent analyses
          </h2>
          <span className="text-[14px] text-paper/60">
            {datasets?.length ?? 0} dataset{datasets?.length === 1 ? '' : 's'} in this workspace
          </span>
        </div>

        {!datasets?.length ? (
          <div className="mt-6 flex flex-col items-center gap-3 rounded-[26px] border border-paper/12 bg-white/[0.04] px-6 py-14 text-center">
            <FileSpreadsheet size={30} className="text-paper/50" aria-hidden />
            <p className="text-[17px] font-medium">No uploads yet</p>
            <p className="max-w-[46ch] text-[15px] text-paper/65">
              Drop a CSV in the live demo above to create your first workspace. Analyses appear here
              with their status so you can reopen results after a refresh. Sign in to keep them on
              your personal dashboard.
            </p>
            <Link
              to="/login"
              className="mt-2 inline-flex items-center gap-2 rounded-[14px] bg-lime px-4 py-2 text-[14px] font-medium text-ink"
            >
              Sign in to save work
              <ArrowRight size={14} aria-hidden />
            </Link>
          </div>
        ) : (
          <ul className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {datasets.slice(0, 9).map((d) => {
              const latest = d.runs?.[0]
              const target =
                latest && latest.status === 'completed'
                  ? `/run/${latest.id}`
                  : latest
                    ? `/run/${latest.id}/process`
                    : null
              return (
                <li key={d.id} className="rounded-[26px] border border-paper/12 bg-white/[0.04] p-6">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[17px] font-medium break-all">{d.filename}</p>
                    <StatusDot status={latest?.status ?? 'none'} />
                  </div>
                  <dl className="mt-4 grid grid-cols-3 gap-2 text-[13.5px]">
                    <Stat label="Rows" value={d.row_count.toLocaleString()} />
                    <Stat label="Cols" value={String(d.column_count)} />
                    <Stat label="Size" value={formatBytes(d.size_bytes)} />
                  </dl>
                  <div className="mt-5 flex flex-wrap gap-3">
                    {target ? (
                      <Link
                        to={target}
                        className="inline-flex items-center gap-2 rounded-[14px] bg-lime px-4 py-2 text-[14px] font-medium text-ink"
                      >
                        Open workspace
                        <span className="grid size-6 place-items-center rounded-full bg-ink text-lime">
                          <ArrowRight size={12} aria-hidden />
                        </span>
                      </Link>
                    ) : (
                      <button
                        type="button"
                        className="inline-flex items-center gap-2 rounded-[14px] bg-lime px-4 py-2 text-[14px] font-medium text-ink disabled:opacity-45"
                        disabled={starting}
                        onClick={() => startAnalysis(d.id)}
                      >
                        Analyze
                      </button>
                    )}
                    <button
                      type="button"
                      className="rounded-[14px] border border-paper/30 px-4 py-2 text-[14px] text-paper transition hover:border-lime hover:text-lime"
                      onClick={async () => {
                        if (!window.confirm(`Delete ${d.filename} and its analyses? This cannot be undone.`)) return
                        try {
                          await api.delete(`/api/datasets/${d.id}`)
                          void refetchDatasets()
                        } catch (e) {
                          setError(e instanceof ApiError ? e.message : 'Could not delete the dataset.')
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Bits                                                                  */
/* ------------------------------------------------------------------ */

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="inline-flex items-center gap-1.5 rounded-full border border-paper/25 px-3 py-1 text-[13px] font-medium text-paper/75">
      {children}
    </p>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-paper/15 bg-white/[0.04] px-3 py-2">
      <dt className="text-[12px] text-paper/60">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
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

function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed: 'bg-lime',
    partial: 'bg-amber-300',
    running: 'bg-sky-300',
    failed: 'bg-danger',
    cancelled: 'bg-paper/40',
    none: 'bg-paper/25',
  }
  return (
    <span
      className={`size-3 shrink-0 rounded-full ${map[status] ?? 'bg-paper/25'}`}
      title={status}
      aria-label={`status: ${status}`}
    />
  )
}

function describeDelimiter(d: string) {
  return d === '\t' ? 'tab' : d === ';' ? 'semicolon' : d === '|' ? 'pipe' : 'comma'
}

function formatBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function maxColumns(h?: HealthInfo) {
  return (h?.limits?.max_columns ?? 1000).toLocaleString()
}
