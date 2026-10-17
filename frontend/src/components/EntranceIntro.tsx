import { useEffect, useState } from 'react'

const STORAGE_KEY = 'aegis-intro-seen'
const DURATION_MS = 2600

/** Candlestick series: [open, close, high, low] on a 0–100 scale. */
const CANDLES: [number, number, number, number][] = [
  [40, 52, 58, 36],
  [52, 46, 56, 42],
  [46, 61, 66, 44],
  [61, 58, 64, 54],
  [58, 70, 74, 56],
  [70, 66, 72, 62],
  [66, 78, 82, 64],
  [78, 74, 80, 70],
]

const TICKER = ['AEGIS/USD  +2.41%', 'FLOW  184 flagged', 'RECON  matched 99.2%', 'VOLUME  ▲ 12.8%', 'RISK  band 88–100k', 'QUALITY  98.6']

/**
 * One-time 3D entrance. A coin turns in space, candlesticks grow in depth
 * order and a ticker scrolls, then the overlay fades into the page.
 * Shown once per browser session; clicking anywhere skips it.
 */
export default function EntranceIntro() {
  const [visible, setVisible] = useState(false)
  const [leaving, setLeaving] = useState(false)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    try {
      if (sessionStorage.getItem(STORAGE_KEY)) return
      sessionStorage.setItem(STORAGE_KEY, '1')
    } catch {
      // storage can be blocked; the intro simply plays every load in that case
    }
    setVisible(true)
    const fade = window.setTimeout(() => setLeaving(true), DURATION_MS)
    const done = window.setTimeout(() => setVisible(false), DURATION_MS + 600)
    return () => {
      window.clearTimeout(fade)
      window.clearTimeout(done)
    }
  }, [])

  if (!visible) return null

  return (
    <div
      role="presentation"
      aria-hidden
      onClick={() => setVisible(false)}
      className={`fixed inset-0 z-[100] flex cursor-pointer flex-col items-center justify-center overflow-hidden bg-ink transition-opacity duration-700 ${
        leaving ? 'opacity-0' : 'opacity-100'
      }`}
      style={{ perspective: '1400px' }}
    >
      {/* spinning coin */}
      <div className="intro-coin relative size-44" style={{ transformStyle: 'preserve-3d' }}>
        <div className="intro-coin-face absolute inset-0 grid place-items-center rounded-full border-[6px] border-lime bg-lime text-ink shadow-[0_0_60px_rgba(185,255,102,0.45)]">
          <span className="text-[64px] font-bold">$</span>
        </div>
        <div
          className="intro-coin-face absolute inset-0 grid place-items-center rounded-full border-[6px] border-lime bg-ink text-lime"
          style={{ transform: 'rotateY(180deg)' }}
        >
          <svg viewBox="0 0 64 64" className="size-16" aria-hidden>
            <path d="M18 44 L18 20 L44 20" stroke="currentColor" strokeWidth="7" fill="none" />
            <circle cx="40" cy="40" r="8" fill="currentColor" />
          </svg>
        </div>
      </div>

      {/* rising candlesticks in 3D */}
      <div className="mt-10 flex h-40 items-end gap-3" style={{ transformStyle: 'preserve-3d' }}>
        {CANDLES.map(([open, close, high, low], i) => {
          const up = close >= open
          const body = Math.abs(close - open)
          return (
            <div
              key={i}
              className="relative h-full w-4"
            >
              <div
                className="intro-candle absolute inset-x-0 bottom-0 h-full"
                style={{ animationDelay: `${0.5 + i * 0.12}s` }}
              >
                <span
                  className="absolute left-1/2 w-px -translate-x-1/2 bg-paper/60"
                  style={{ bottom: `${low}%`, height: `${high - low}%` }}
                />
                <span
                  className={`absolute inset-x-0 rounded-[3px] ${up ? 'bg-lime' : 'bg-danger'}`}
                  style={{ bottom: `${Math.min(open, close)}%`, height: `${Math.max(body, 4)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>

      {/* ticker */}
      <div className="mt-10 w-[min(92vw,640px)] overflow-hidden border-y border-paper/15 py-2">
        <div className="intro-ticker flex w-max gap-10 font-mono text-[13px] tracking-wide text-paper/70 uppercase">
          {[...TICKER, ...TICKER].map((t, i) => (
            <span key={i}>{t}</span>
          ))}
        </div>
      </div>

      <p className="mt-8 text-[15px] font-medium tracking-[0.2em] text-paper/80 uppercase">
        Aegis · financial intelligence
      </p>
      <p className="mt-2 text-[12px] text-paper/40">click to skip</p>
    </div>
  )
}
