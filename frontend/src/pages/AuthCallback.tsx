import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, KeyRound } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { parseAuthLink, redeemable } from '../lib/authLink'
import type { AuthUser } from '../lib/types'

/**
 * Landing page for the sign-in link Supabase emails.
 *
 * Supabase redirects here with the session in the URL fragment — or, if the
 * browser could not follow the link, the user pastes that same link and we send
 * the token to our API instead. Either way the backend asks Supabase whether the
 * token is live and only then sets our own httpOnly session cookie.
 */
export default function AuthCallback() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(true)
  const started = useRef(false)

  const rawNext = searchParams.get('next') || '/dashboard'
  // same-origin paths only — a link must never bounce to an external origin
  const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/dashboard'

  useEffect(() => {
    if (started.current) return
    started.current = true

    const creds = parseAuthLink(window.location.href)

    // Never leave a token sitting in the address bar, history or a shared link.
    if (creds.access_token || creds.token_hash) {
      window.history.replaceState(null, '', '/auth/callback')
    }

    if (creds.error) {
      setPending(false)
      setError(
        creds.error_description ||
          (creds.error === 'access_denied'
            ? 'That sign-in link has expired or was already used. Request a new one.'
            : `Supabase refused the sign-in (${creds.error}).`),
      )
      return
    }

    if (!redeemable(creds)) {
      setPending(false)
      setError(
        'This page finishes an email sign-in. Open the link from your inbox, or paste it on the sign-in page.',
      )
      return
    }

    const body = creds.access_token
      ? { access_token: creds.access_token, type: creds.type }
      : { token_hash: creds.token_hash, type: creds.type }

    api
      .post<AuthUser>('/api/auth/supabase/redeem', body)
      .then((user) => {
        queryClient.setQueryData(['me'], user)
        void queryClient.invalidateQueries({ queryKey: ['me'] })
        navigate(next, { replace: true })
      })
      .catch((err: unknown) => {
        setPending(false)
        setError(
          err instanceof ApiError
            ? err.message
            : 'Sign-in could not be completed. Check the API server and try again.',
        )
      })
  }, [navigate, next, queryClient])

  return (
    <div className="shell flex min-h-[70vh] items-center justify-center py-16">
      <section className="card w-full max-w-[520px] p-8 sm:p-10">
        <div className="flex items-center gap-3">
          <span className="grid size-11 place-items-center rounded-[12px] bg-ink text-lime">
            {error ? <AlertTriangle size={20} aria-hidden /> : <KeyRound size={20} aria-hidden />}
          </span>
          <div>
            <p className="text-[19px] font-medium">
              {error ? 'That link did not work' : 'Finishing sign-in'}
            </p>
            <p className="text-[14px] text-ink-soft">
              {error ? 'Nothing was signed in.' : 'Verifying your link with Supabase Auth…'}
            </p>
          </div>
        </div>

        {error ? (
          <>
            <p
              role="alert"
              className="mt-6 rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14px] text-danger"
            >
              {error}
            </p>
            <Link to="/login" className="btn mt-6 w-full justify-center">
              Back to sign in
              <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                <KeyRound size={14} aria-hidden />
              </span>
            </Link>
            <p className="mt-4 text-[13px] leading-relaxed text-ink-soft">
              Links work once and expire. On the sign-in page you can request a fresh
              one, or paste the link from the email if your browser would not open it.
            </p>
          </>
        ) : (
          <p className="mt-6 flex items-center gap-3 text-[15px] text-ink-soft">
            <span
              className="size-4 animate-spin rounded-full border-2 border-line border-t-transparent"
              aria-hidden
            />
            {pending ? 'Checking the link…' : 'Redirecting…'}
          </p>
        )}
      </section>
    </div>
  )
}
