import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Menu, X, ShieldCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { AuthUser, HealthInfo } from '../lib/types'

/**
 * Site chrome: Positivus-style header (logo · links · ink CTA) and the dark
 * footer band. The header doubles as the auth surface — when a session exists
 * we show the account chip, otherwise the Freebuff sign-in link.
 */
export default function Layout({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  const location = useLocation()

  const { data: user } = useQuery<AuthUser | null>({
    queryKey: ['me'],
    queryFn: () => api.get<AuthUser>('/api/auth/me'),
    retry: false,
    staleTime: 60_000,
  })

  const { data: health } = useQuery<HealthInfo>({
    queryKey: ['health'],
    queryFn: () => api.get<HealthInfo>('/api/health'),
    staleTime: 300_000,
  })

  useEffect(() => setOpen(false), [location.pathname])

  const brand = health?.brand
  const name = brand?.name ?? 'Aegis'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-line/15 bg-paper/95 backdrop-blur">
        <div className="shell flex h-[86px] items-center justify-between gap-6">
          <Link to="/" className="flex items-center gap-3" aria-label={`${name} home`}>
            <span className="grid size-10 place-items-center rounded-[12px] bg-ink">
              <svg viewBox="0 0 64 64" className="size-6" aria-hidden>
                <path
                  d="M18 44 L18 20 L44 20"
                  stroke="#B9FF66"
                  strokeWidth="7"
                  fill="none"
                  strokeLinecap="square"
                />
                <circle cx="40" cy="40" r="8" fill="#B9FF66" />
              </svg>
            </span>
            <span className="text-[22px] font-semibold tracking-[-0.03em]">{name}</span>
          </Link>

          <nav aria-label="Primary" className="hidden items-center gap-8 text-[16px] md:flex">
            {user ? (
              <>
                <Link to="/dashboard" className="rounded-lg px-1 py-1 text-ink transition-colors hover:[text-decoration:underline_3px_var(--color-lime)]">
                  Dashboard
                </Link>
                <Link to="/catalog" className="rounded-lg px-1 py-1 text-ink transition-colors hover:[text-decoration:underline_3px_var(--color-lime)]">
                  Datasets
                </Link>
                <Link to="/upload" className="rounded-lg px-1 py-1 text-ink transition-colors hover:[text-decoration:underline_3px_var(--color-lime)]">
                  Upload
                </Link>
              </>
            ) : (
              <>
                <NavAnchor href="/#product">Product</NavAnchor>
                <NavAnchor href="/#how">How it works</NavAnchor>
                <NavAnchor href="/#pricing">Pricing</NavAnchor>
                <NavAnchor href="/#faq">FAQ</NavAnchor>
              </>
            )}
          </nav>

          <div className="flex items-center gap-3">
            {user ? (
              <Link to="/dashboard" className="chip hidden bg-lime sm:inline-flex">
                <ShieldCheck size={15} aria-hidden />
                {user.display_name || user.email}
              </Link>
            ) : (
              <Link
                to="/login"
                className="btn hidden text-[15px] sm:inline-flex"
              >
                Sign in
                <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                  <ArrowGlyph />
                </span>
              </Link>
            )}
            <button
              type="button"
              className="grid size-11 place-items-center rounded-[12px] border border-line md:hidden"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-label={open ? 'Close menu' : 'Open menu'}
            >
              {open ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>

        {open && (
          <div className="shell flex flex-col gap-4 pb-6 md:hidden">
            {user ? (
              <>
                <Link to="/dashboard" className="rounded-lg px-1 py-1 text-ink">Dashboard</Link>
                <Link to="/catalog" className="rounded-lg px-1 py-1 text-ink">Datasets</Link>
                <Link to="/upload" className="rounded-lg px-1 py-1 text-ink">Upload</Link>
                <Link to="/booking" className="rounded-lg px-1 py-1 text-ink">Bookings</Link>
                <Link to="/checkout" className="rounded-lg px-1 py-1 text-ink">Billing</Link>
              </>
            ) : (
              <>
                <NavAnchor href="/#product">Product</NavAnchor>
                <NavAnchor href="/#how">How it works</NavAnchor>
                <NavAnchor href="/#pricing">Pricing</NavAnchor>
                <NavAnchor href="/#faq">FAQ</NavAnchor>
              </>
            )}
            <Link to={user ? '/dashboard' : '/login'} className="btn justify-center">
              {user ? 'Open dashboard' : 'Sign in'}
            </Link>
          </div>
        )}
      </header>

      <main className="flex-1">{children}</main>

      <footer className="mt-24 bg-ink text-paper">
        <div className="shell grid gap-10 py-16 md:grid-cols-[1.4fr_1fr_1fr]">
          <div>
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-[12px] bg-lime">
                <svg viewBox="0 0 64 64" className="size-6" aria-hidden>
                  <path d="M18 44 L18 20 L44 20" stroke="#191A23" strokeWidth="7" fill="none" />
                  <circle cx="40" cy="40" r="8" fill="#191A23" />
                </svg>
              </span>
              <span className="text-[22px] font-semibold">{name}</span>
            </div>
            <p className="mt-5 max-w-[46ch] text-[15px] leading-relaxed text-paper/70">
              {brand?.descriptor ?? 'AI Financial Intelligence'} — {brand?.tagline}
            </p>
            <p className="mt-4 text-[13px] leading-relaxed text-paper/45">
              Uploaded files are processed on the server and never sent to external
              providers unless an integration is explicitly configured.
            </p>
          </div>
          <FooterCol
            title="Platform"
            links={[
              ['Dashboard', '/dashboard'],
              ['Catalog', '/catalog'],
              ['Upload', '/upload'],
              ['Book a review', '/booking'],
              ['Billing', '/checkout'],
              ['Upload a CSV', '/#upload'],
              ['How it works', '/#how'],
              ['Pricing', '/#pricing'],
              ['Privacy', '/#privacy'],
              ['Sign in', '/login'],
            ]}
          />
          <FooterCol
            title="Capabilities"
            links={[
              ['Schema inference', '/#how'],
              ['Machine learning', '/#how'],
              ['Money-flow network', '/#how'],
              ['Reports & exports', '/#how'],
            ]}
          />
        </div>
        <div className="border-t border-paper/15">
          <div className="shell flex flex-col gap-2 py-6 text-[13px] text-paper/50 sm:flex-row sm:justify-between">
            <span>© {new Date().getFullYear()} {name}. Analysis results are statistical — not determinations of wrongdoing.</span>
            <span>
              {health?.providers?.llm_configured ? 'LLM configured' : 'Local rule-based assistant'} ·{' '}
              {health?.providers?.fx_provider_configured ? 'live FX' : 'file-embedded FX only'}
            </span>
          </div>
        </div>
      </footer>
    </div>
  )
}

function NavAnchor({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      className="rounded-lg px-1 py-1 text-ink transition-colors hover:[text-decoration:underline_3px_var(--color-lime)]"
    >
      {children}
    </a>
  )
}

function ArrowGlyph() {
  return <svg viewBox="0 0 16 16" className="size-3.5" aria-hidden>
    <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" stroke="currentColor" strokeWidth="2" fill="none" />
  </svg>
}

function FooterCol({ title, links }: { title: string; links: [string, string][] }) {
  return (
    <div>
      <h3 className="text-[17px] font-medium text-lime">{title}</h3>
      <ul className="mt-4 space-y-3 text-[15px]">
        {links.map(([label, href]) => (
          <li key={label}>
            <a href={href} className="text-paper/80 transition-colors hover:text-lime">
              {label}
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}
