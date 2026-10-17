import { useEffect } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import AppShell from './components/AppShell'
import EntranceIntro from './components/EntranceIntro'
import Layout from './components/Layout'
import Admin from './pages/Admin'
import AuthCallback from './pages/AuthCallback'
import Booking from './pages/Booking'
import Catalog from './pages/Catalog'
import Checkout from './pages/Checkout'
import Dashboard from './pages/Dashboard'
import Insights from './pages/Insights'
import DatasetDetail from './pages/DatasetDetail'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Processing from './pages/Processing'
import Upload from './pages/Upload'
import Workspace from './pages/Workspace'
import { api } from './lib/api'
import type { AuthUser } from './lib/types'

/**
 * Everything past the landing page requires sign-in (by hook or by crook):
 * signed-out visitors bounce to /login and come back to where they were
 * headed. The landing and sign-in pages keep the marketing chrome; every
 * app page renders inside the sidebar shell.
 */
function RequireAuth() {
  const location = useLocation()
  const { data: user, isLoading, isError } = useQuery<AuthUser | null>({
    queryKey: ['me'],
    queryFn: () => api.get<AuthUser>('/api/auth/me'),
    retry: false,
    staleTime: 60_000,
  })

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3">
        <span className="size-4 animate-spin rounded-full border-2 border-line border-t-transparent" />
        <span className="text-[15px] text-ink-soft">Checking your session…</span>
      </div>
    )
  }
  if (isError || !user) {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname)}`} replace />
  }
  return <AppShell />
}

/**
 * Every email sign-in link carries its session in the URL fragment. If Supabase
 * sends the browser to any path other than the callback (it falls back to the
 * project's Site URL when `redirect_to` is not allowed), the token would sit
 * unread in the address bar — so anything that looks like a link result is
 * forwarded to the page that redeems it.
 */
function AuthLinkCapture() {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (location.pathname === '/auth/callback') return
    const { hash, search } = window.location
    if (!/(^|[#&])(access_token|error)=/.test(hash)) return
    navigate({ pathname: '/auth/callback', search, hash }, { replace: true })
  }, [location.pathname, navigate])

  return null
}

export default function App() {
  return (
    <>
      <EntranceIntro />
      <AuthLinkCapture />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route
          path="/"
          element={
            <Layout>
              <Landing />
            </Layout>
          }
        />

        {/* authenticated app: sidebar shell wraps every nested page */}
        <Route element={<RequireAuth />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/catalog" element={<Catalog />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/datasets/:datasetId" element={<DatasetDetail />} />
          <Route path="/booking" element={<Booking />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/admin" element={<Admin />} />
          <Route path="/run/:runId" element={<Workspace />} />
          <Route path="/run/:runId/process" element={<Processing />} />
        </Route>

        <Route
          path="*"
          element={
            <Layout>
              <Landing />
            </Layout>
          }
        />
      </Routes>
    </>
  )
}
