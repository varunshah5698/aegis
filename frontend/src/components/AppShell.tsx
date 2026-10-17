import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BarChart3,
  CalendarCheck,
  CreditCard,
  Database,
  FolderSearch,
  LayoutDashboard,
  LogOut,
  Menu,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-react'
import { api } from '../lib/api'
import type { AuthUser, HealthInfo } from '../lib/types'

const GROUPS: {
  label: string
  items: { to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }[]
}[] = [
  {
    label: 'Workspace',
    items: [
      { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/insights', label: 'Insights', icon: Sparkles },
      { to: '/catalog', label: 'Datasets', icon: FolderSearch },
      { to: '/upload', label: 'Upload', icon: UploadCloud },
    ],
  },
  {
    label: 'Commercial',
    items: [
      { to: '/booking', label: 'Bookings', icon: CalendarCheck },
      { to: '/checkout', label: 'Billing', icon: CreditCard },
    ],
  },
  {
    label: 'Administration',
    items: [{ to: '/admin', label: 'Admin console', icon: ShieldCheck }],
  },
]

/**
 * Authenticated app shell: a persistent left sidebar with grouped navigation,
 * a slim top bar carrying the current section and the account menu, and a
 * full-width content area. Marketing pages keep their own chrome.
 */
export default function AppShell() {
  const [drawer, setDrawer] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

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

  useEffect(() => setDrawer(false), [location.pathname])

  const name = health?.brand?.name ?? 'Aegis'
  const current =
    GROUPS.flatMap((g) => g.items).find((i) => location.pathname.startsWith(i.to))?.label ??
    (location.pathname.startsWith('/run') || location.pathname.startsWith('/datasets')
      ? 'Analysis'
      : 'Workspace')

  async function signOut() {
    try {
      await api.post('/api/auth/logout')
    } finally {
      queryClient.clear()
      navigate('/', { replace: true })
    }
  }

  const initials = (user?.display_name || user?.email || '?').slice(0, 2).toUpperCase()

  const sidebar = (
    <div className="flex h-full flex-col bg-ink text-paper">
      <div className="flex items-center gap-3 px-5 py-5">
        <Link to="/" className="flex items-center gap-3" aria-label={`${name} home`}>
          <span className="grid size-9 place-items-center rounded-[11px] bg-lime text-ink">
            <svg viewBox="0 0 64 64" className="size-5" aria-hidden>
              <path d="M18 44 L18 20 L44 20" stroke="currentColor" strokeWidth="8" fill="none" />
              <circle cx="40" cy="40" r="8" fill="currentColor" />
            </svg>
          </span>
          <span className="text-[19px] font-semibold tracking-[-0.02em]">{name}</span>
        </Link>
      </div>

      <nav aria-label="Sections" className="flex-1 space-y-6 overflow-y-auto px-3 pb-4">
        {GROUPS.map((group) => (
          <div key={group.label}>
            <p className="px-3 pb-2 text-[10.5px] font-semibold tracking-[0.14em] text-paper/40 uppercase">
              {group.label}
            </p>
            <ul className="space-y-1">
              {group.items.map(({ to, label, icon: Icon }) => (
                <li key={to}>
                  <NavLink
                    to={to}
                    className={({ isActive }) =>
                      `group flex items-center gap-3 rounded-[11px] px-3 py-2.5 text-[14.5px] font-medium transition-colors ${
                        isActive
                          ? 'bg-lime text-ink'
                          : 'text-paper/75 hover:bg-white/[0.07] hover:text-paper'
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        <Icon size={17} aria-hidden className={isActive ? '' : 'text-paper/60 group-hover:text-lime'} />
                        {label}
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}

        <div>
          <p className="px-3 pb-2 text-[10.5px] font-semibold tracking-[0.14em] text-paper/40 uppercase">
            Product
          </p>
          <ul className="space-y-1 text-[14.5px] font-medium">
            {[
              ['/', 'Landing page', BarChart3],
              ['/#pricing', 'Pricing', CreditCard],
            ].map(([to, label, Icon]) => {
              const I = Icon as typeof BarChart3
              return (
                <li key={to as string}>
                  <a
                    href={to as string}
                    className="flex items-center gap-3 rounded-[11px] px-3 py-2.5 text-paper/75 transition-colors hover:bg-white/[0.07] hover:text-paper"
                  >
                    <I size={17} aria-hidden />
                    {label as string}
                  </a>
                </li>
              )
            })}
          </ul>
        </div>
      </nav>

      <div className="border-t border-paper/12 p-3">
        <div className="flex items-center gap-3 rounded-[12px] bg-white/[0.05] px-3 py-2.5">
          <span className="grid size-9 shrink-0 place-items-center rounded-full bg-lime text-[13px] font-bold text-ink">
            {initials}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13.5px] font-medium">{user?.display_name || 'Signed in'}</p>
            <p className="truncate text-[11.5px] text-paper/50">{user?.email}</p>
          </div>
          <button
            type="button"
            onClick={signOut}
            title="Sign out"
            className="grid size-8 shrink-0 place-items-center rounded-[9px] text-paper/60 transition-colors hover:bg-white/10 hover:text-lime"
          >
            <LogOut size={15} aria-hidden />
            <span className="sr-only">Sign out</span>
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-mist/60">
      {/* desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[254px] lg:block">{sidebar}</aside>

      {/* mobile drawer */}
      {drawer && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-ink/50 backdrop-blur-sm"
            onClick={() => setDrawer(false)}
            aria-hidden
          />
          <div className="absolute inset-y-0 left-0 w-[264px] shadow-2xl">
            {sidebar}
            <button
              type="button"
              onClick={() => setDrawer(false)}
              className="absolute top-5 right-4 grid size-8 place-items-center rounded-[9px] bg-white/10 text-paper"
              aria-label="Close navigation"
            >
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      <div className="lg:pl-[254px]">
        {/* top bar */}
        <header className="sticky top-0 z-30 border-b border-line/10 bg-paper/85 backdrop-blur">
          <div className="flex h-[64px] items-center gap-3 px-4 sm:px-6">
            <button
              type="button"
              onClick={() => setDrawer(true)}
              className="grid size-10 place-items-center rounded-[11px] border border-line/15 lg:hidden"
              aria-label="Open navigation"
            >
              <Menu size={18} />
            </button>
            <p className="flex items-center gap-2 text-[14px] font-medium">
              <Database size={15} className="text-ink-soft" aria-hidden />
              <span className="text-ink-soft">{name}</span>
              <span className="text-ink-soft">/</span>
              {current}
            </p>
            <div className="ml-auto flex items-center gap-2.5">
              <Link
                to="/upload"
                className="inline-flex items-center gap-2 rounded-[11px] bg-ink px-3.5 py-2 text-[13.5px] font-medium text-paper transition hover:-translate-y-px"
              >
                <UploadCloud size={15} aria-hidden />
                New upload
              </Link>
              <span className="hidden items-center gap-2 rounded-full border border-line/15 bg-paper px-3 py-1.5 text-[13px] font-medium sm:inline-flex">
                <span className="size-2 rounded-full bg-teal" />
                {user?.display_name || user?.email || 'Signed in'}
              </span>
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1360px] px-4 py-7 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
