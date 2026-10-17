import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  KeyRound,
  Link2,
  Lock,
  Mail,
  MessageSquareText,
  Timer,
  UserPlus,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { parseAuthLink, redeemable } from '../lib/authLink'
import type { AuthUser, ProviderInfo } from '../lib/types'

const emailForm = z.object({
  email: z.string().email('Enter a valid email address'),
  display_name: z.string().max(120).optional(),
})
type EmailValues = z.infer<typeof emailForm>

const credentials = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(8, 'At least 8 characters'),
  display_name: z.string().max(120).optional(),
})
type Credentials = z.infer<typeof credentials>

interface OtpRequestResponse {
  ok: boolean
  email: string
  expires_in_seconds: number
  delivery: 'email' | 'dev_console'
  length: number
  /** supabase | smtp when the code was emailed; absent in dev mode. */
  provider?: string
  dev_code?: string
}

interface OtpState {
  email: string
  length: number
  expiresAt: number
  devCode?: string
  delivery: string
  provider?: string
}

/**
 * Freebuff sign-in surface. Passwordless email passcodes are the primary
 * flow (request a code, enter it, get a session cookie); the legacy
 * email+password form stays available under the Password tab for existing
 * accounts. Sessions are httpOnly cookies throughout.
 */
export default function Login() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'passcode' | 'password'>('passcode')
  const [pwMode, setPwMode] = useState<'login' | 'register'>('login')
  const [otpStep, setOtpStep] = useState<'email' | 'code'>('email')
  const [otp, setOtp] = useState<OtpState | null>(null)
  const [code, setCode] = useState('')
  const [codeError, setCodeError] = useState('')
  const [cooldownUntil, setCooldownUntil] = useState(0)
  const [now, setNow] = useState(() => Date.now())
  const [linkValue, setLinkValue] = useState('')
  const [linkError, setLinkError] = useState('')
  const autoSubmitted = useRef('')

  const { data: provider } = useQuery<ProviderInfo>({
    queryKey: ['provider'],
    queryFn: () => api.get<ProviderInfo>('/api/auth/provider'),
    staleTime: 600_000,
  })

  const [searchParams] = useSearchParams()
  const rawNext = searchParams.get('next') || '/dashboard'
  // same-origin paths only — never bounce to an external URL
  const next = rawNext.startsWith('/') && !rawNext.startsWith('//') ? rawNext : '/'

  function signedIn(user: AuthUser) {
    queryClient.setQueryData(['me'], user)
    void queryClient.invalidateQueries({ queryKey: ['me'] })
    navigate(next, { replace: true })
  }

  // ---------------------------------------------------------- passcode ----
  const emailFormApi = useForm<EmailValues>({ resolver: zodResolver(emailForm) })

  const requestCode = useMutation<OtpRequestResponse, ApiError, EmailValues>({
    mutationFn: (values) => api.post<OtpRequestResponse>('/api/auth/otp/request', values),
    onSuccess: (res, values) => {
      setCode('')
      setCodeError('')
      autoSubmitted.current = ''
      setOtp({
        email: res.email || values.email,
        length: res.length || 6,
        expiresAt: Date.now() + (res.expires_in_seconds || 600) * 1000,
        devCode: res.dev_code,
        delivery: res.delivery,
        provider: res.provider,
      })
      setOtpStep('code')
      setCooldownUntil(Date.now() + 30_000)
    },
  })

  const verifyCode = useMutation<AuthUser, ApiError, { email: string; code: string }>({
    mutationFn: ({ email, code: c }) =>
      api.post<AuthUser>('/api/auth/otp/verify', { email, code: c }),
    onSuccess: (user) => signedIn(user),
    onError: (err) => {
      setCodeError(err.message)
      autoSubmitted.current = ''
    },
  })

  // Supabase emails a *link* by default, and a link only becomes a session if
  // something redeems its token. Following it works when the browser can reach
  // the redirect target; pasting it here works even when it cannot (wrong port,
  // mail client stripped the fragment, opened on another device).
  const redeemLink = useMutation<AuthUser, ApiError, string>({
    mutationFn: async (raw) => {
      const creds = parseAuthLink(raw)
      if (creds.error) {
        throw new ApiError(
          400,
          creds.error_description || 'That sign-in link has expired. Request a new one.',
        )
      }
      if (!redeemable(creds)) {
        throw new ApiError(400, 'Paste the full sign-in link from the email — it carries a token.')
      }
      return api.post<AuthUser>(
        '/api/auth/supabase/redeem',
        creds.access_token
          ? { access_token: creds.access_token, type: creds.type }
          : { token_hash: creds.token_hash, type: creds.type },
      )
    },
    onSuccess: (user) => {
      setLinkValue('')
      setLinkError('')
      signedIn(user)
    },
    onError: (err) => setLinkError(err.message),
  })

  // live countdown for resend + expiry
  useEffect(() => {
    if (otpStep !== 'code') return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [otpStep])

  // auto-submit once a full-length code is typed or pasted
  useEffect(() => {
    if (otpStep !== 'code' || !otp) return
    const digits = code.replace(/\D/g, '')
    if (digits.length === otp.length && autoSubmitted.current !== digits) {
      autoSubmitted.current = digits
      setCodeError('')
      verifyCode.mutate({ email: otp.email, code: digits })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, otpStep, otp])

  function onEmailSubmit(values: EmailValues) {
    setCodeError('')
    requestCode.mutate(values)
  }

  function resend() {
    if (!otp || Date.now() < cooldownUntil) return
    setCodeError('')
    requestCode.mutate({ email: otp.email })
  }

  // ---------------------------------------------------------- password ----
  const {
    register,
    handleSubmit,
    formState: { errors },
    reset: resetPw,
  } = useForm<Credentials>({ resolver: zodResolver(credentials) })
  const [pwError, setPwError] = useState('')

  const pwMutation = useMutation<AuthUser, ApiError, { path: string; values: Credentials }>({
    mutationFn: ({ path, values }) => api.post<AuthUser>(path, values),
    onSuccess: (user) => {
      resetPw()
      signedIn(user)
    },
  })

  function onPasswordSubmit(values: Credentials) {
    setPwError('')
    const path = pwMode === 'login' ? '/api/auth/login' : '/api/auth/register'
    pwMutation.mutate({ path, values })
  }

  function switchMode(next: 'passcode' | 'password') {
    setMode(next)
    setCodeError('')
    setPwError('')
  }

  const providerName = provider?.provider ?? 'Freebuff'
  const isSupabase = provider?.otp_provider === 'supabase'
  const otpLength = otp?.length ?? provider?.otp_length ?? 6
  const otpTtlMinutes = Math.max(1, Math.round((provider?.otp_ttl_seconds ?? 600) / 60))
  const cooldownLeft = Math.max(0, Math.ceil((cooldownUntil - now) / 1000))
  const codeExpired = otp ? now > otp.expiresAt : false

  const linkPanel = isSupabase ? (
    <details className="mt-5 rounded-[14px] border border-line bg-paper px-4 py-3">
      <summary className="cursor-pointer text-[14px] font-medium">
        Already have the sign-in link?
      </summary>
      <p className="mt-2 text-[13px] leading-relaxed text-ink-soft">
        If the link will not open (nothing is listening on the address it points
        at, or the token got stripped), paste the whole link here and we will
        finish sign-in for you.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (redeemLink.isPending || !linkValue.trim()) return
          setLinkError('')
          redeemLink.mutate(linkValue)
        }}
        className="mt-3 space-y-2"
        noValidate
      >
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-medium">Sign-in link from the email</span>
          <span className="relative block">
            <Link2
              size={16}
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-ink-soft"
            />
            <input
              type="text"
              spellCheck={false}
              autoComplete="off"
              aria-label="Sign-in link from the email"
              placeholder="http://localhost:54321/auth/v1/verify?token=…"
              value={linkValue}
              onChange={(e) => {
                setLinkValue(e.target.value)
                setLinkError('')
              }}
              className="field pl-10 font-mono text-[12.5px]"
            />
          </span>
        </label>
        {linkError && (
          <p
            role="alert"
            className="rounded-[12px] border border-danger/40 bg-danger/8 px-3 py-2 text-[13px] text-danger"
          >
            {linkError}
          </p>
        )}
        <button
          type="submit"
          disabled={redeemLink.isPending || !linkValue.trim()}
          className="btn w-full justify-center"
        >
          {redeemLink.isPending ? 'Completing sign-in…' : 'Complete sign-in'}
          <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
            <Link2 size={14} aria-hidden />
          </span>
        </button>
      </form>
    </details>
  ) : null

  return (
    <div className="shell grid min-h-[78vh] items-center gap-12 py-16 lg:grid-cols-[1.05fr_1fr]">
      {/* ---------------------------------------------------- brand panel */}
      <section className="hidden lg:block">
        <span className="chip bg-lime">{providerName} identity</span>
        <h1 className="mt-6 text-[54px] leading-[1.04] font-medium tracking-[-0.035em]">
          Sign in to keep your <span className="marker">analysis history</span> and
          reports.
        </h1>
        <p className="mt-6 max-w-[52ch] text-[17px] leading-relaxed text-ink-soft">
          Uploads, runs and saved findings stay attached to your account so they
          survive a refresh or a restart. Sessions are httpOnly cookies — the token
          is never readable from browser JavaScript.
        </p>
        <ul className="mt-8 space-y-3 text-[15px]">
          {[
            'Passwordless sign-in: a 6-digit code emailed to you, nothing to remember',
            'Single-use links and codes, short expiry, locked after 5 wrong guesses',
            'PBKDF2-HMAC-SHA256 hashing for legacy password accounts',
            'Server-side session records with explicit expiry',
            'Workspace isolation: every dataset is scoped to its owner',
            'Audit events for passcode requests, logins and dataset access',
          ].map((item) => (
            <li key={item} className="flex gap-3">
              <span className="mt-[7px] size-2.5 shrink-0 rounded-[3px] bg-lime ring-1 ring-line" />
              {item}
            </li>
          ))}
        </ul>
      </section>

      {/* -------------------------------------------------------- form */}
      <section className="card p-7 sm:p-10">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="grid size-11 place-items-center rounded-[12px] bg-ink text-lime">
              <KeyRound size={20} aria-hidden />
            </span>
            <div>
              <p className="text-[19px] font-medium">
                {mode === 'passcode'
                  ? isSupabase
                    ? 'Sign in with your email'
                    : 'Sign in with a passcode'
                  : 'Use your password'}
              </p>
              <p className="text-[14px] text-ink-soft">Continue with {providerName}</p>
            </div>
          </div>
          <Link to="/" className="chip" aria-label="Back to upload">
            <ArrowLeft size={15} aria-hidden />
            Home
          </Link>
        </div>

        <div className="mt-7 grid grid-cols-2 gap-3" role="tablist" aria-label="Authentication method">
          {(
            [
              ['passcode', 'Passcode'],
              ['password', 'Password'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={mode === key}
              onClick={() => switchMode(key)}
              className={`rounded-[14px] border border-line px-4 py-2.5 text-[15px] font-medium ${
                mode === key ? 'bg-ink text-paper' : 'bg-paper'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'passcode' ? (
          otpStep === 'email' ? (
            <form
              onSubmit={emailFormApi.handleSubmit(onEmailSubmit)}
              className="mt-6 space-y-4"
              noValidate
            >
              <label className="block">
                <span className="mb-1.5 block text-[14px] font-medium">Email</span>
                <span className="relative block">
                  <Mail
                    size={17}
                    aria-hidden
                    className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft"
                  />
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    className="field pl-11"
                    {...emailFormApi.register('email')}
                  />
                </span>
                {emailFormApi.formState.errors.email && (
                  <span className="mt-1.5 block text-[13px] text-danger">
                    {emailFormApi.formState.errors.email.message}
                  </span>
                )}
              </label>

              <label className="block">
                <span className="mb-1.5 block text-[14px] font-medium">
                  Display name <span className="text-ink-soft">(for new accounts)</span>
                </span>
                <span className="relative block">
                  <UserPlus
                    size={17}
                    aria-hidden
                    className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft"
                  />
                  <input
                    type="text"
                    autoComplete="name"
                    placeholder="How should we address you?"
                    className="field pl-11"
                    {...emailFormApi.register('display_name')}
                  />
                </span>
              </label>

              {(codeError || requestCode.error) && (
                <p
                  role="alert"
                  className="rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14px] text-danger"
                >
                  {codeError ||
                    (requestCode.error instanceof ApiError
                      ? requestCode.error.message
                      : 'Something went wrong. Check the API server and try again.')}
                </p>
              )}

              <button type="submit" disabled={requestCode.isPending} className="btn w-full justify-center">
                {requestCode.isPending
                  ? 'Sending code…'
                  : isSupabase
                    ? 'Email me a sign-in code'
                    : 'Email me a passcode'}
                <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                  <MessageSquareText size={14} aria-hidden />
                </span>
              </button>
              <p className="text-[13px] leading-relaxed text-ink-soft">
                New here? Entering the {otpLength}-digit code creates your account
                automatically. It works once and expires in {otpTtlMinutes} minute
                {otpTtlMinutes === 1 ? '' : 's'}.
              </p>
            </form>
          ) : (
            <div className="mt-6 space-y-4">
              <div className="rounded-[14px] border border-line bg-paper px-4 py-3 text-[14px]">
                <p className="text-ink-soft">
                  Email sent to <span className="font-medium text-ink">{otp?.email}</span>
                  {otp?.delivery === 'email' ? ' — check your inbox.' : '.'}
                </p>
                {otp?.delivery === 'email' && (
                  <p className="mt-1 text-[12.5px] text-ink-soft">
                    {otp.provider === 'supabase'
                      ? 'Sent and verified by Supabase Auth; the code never passes through this app. If the email carries a sign-in link instead of a code, paste that link into the box at the bottom of this card.'
                      : 'Delivered by the configured mail sender.'}
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setOtpStep('email')
                    setOtp(null)
                    setCode('')
                    setCodeError('')
                  }}
                  className="mt-1 font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4"
                >
                  Use a different email
                </button>
              </div>

              {otp?.devCode && (
                <div
                  role="status"
                  className="rounded-[14px] border border-line bg-lime/25 px-4 py-3 text-[14px]"
                >
                  <p className="font-medium">Development mode — no email sender configured.</p>
                  <p className="mt-1 text-ink-soft">
                    Your passcode is{' '}
                    <button
                      type="button"
                      onClick={() => setCode(otp.devCode ?? '')}
                      className="font-mono text-[16px] font-bold tracking-[0.2em] text-ink underline decoration-lime decoration-[3px] underline-offset-4"
                      title="Click to fill"
                    >
                      {otp.devCode}
                    </button>{' '}
                    (click to fill).
                  </p>
                </div>
              )}

              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  if (!otp || verifyCode.isPending) return
                  const digits = code.replace(/\D/g, '')
                  if (digits.length !== otp.length) {
                    setCodeError(`Enter the ${otp.length}-digit code.`)
                    return
                  }
                  autoSubmitted.current = digits
                  setCodeError('')
                  verifyCode.mutate({ email: otp.email, code: digits })
                }}
                className="space-y-4"
                noValidate
              >
                <label className="block">
                  <span className="mb-1.5 block text-[14px] font-medium">
                    {otpLength}-digit code from the email
                  </span>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    autoFocus
                    placeholder={'·'.repeat(otpLength)}
                    value={code}
                    onChange={(e) => {
                      setCode(e.target.value.replace(/\D/g, '').slice(0, otpLength))
                      setCodeError('')
                    }}
                    className="field text-center font-mono text-[22px] tracking-[0.35em]"
                  />
                </label>

                {(codeError || verifyCode.error) && (
                  <p
                    role="alert"
                    className="rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14px] text-danger"
                  >
                    {codeError ||
                      (verifyCode.error instanceof ApiError
                        ? verifyCode.error.message
                        : 'Something went wrong. Check the API server and try again.')}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={verifyCode.isPending}
                  className="btn w-full justify-center"
                >
                  {verifyCode.isPending ? 'Verifying…' : `Sign in with ${providerName}`}
                  <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                    <KeyRound size={14} aria-hidden />
                  </span>
                </button>
              </form>

              <div className="flex items-center justify-between text-[14px]">
                <span className="inline-flex items-center gap-1.5 text-ink-soft">
                  <Timer size={15} aria-hidden />
                  {codeExpired ? (
                    <span className="font-medium text-danger">
                      Code expired — request a new one.
                    </span>
                  ) : (
                    otp && (
                      <>Code valid for {Math.max(0, Math.ceil((otp.expiresAt - now) / 1000 / 60))} more min</>
                    )
                  )}
                </span>
                <button
                  type="button"
                  onClick={resend}
                  disabled={cooldownLeft > 0 || requestCode.isPending}
                  className="font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4 disabled:text-ink-soft disabled:no-underline"
                >
                  {cooldownLeft > 0 ? `Resend in ${cooldownLeft}s` : 'Resend code'}
                </button>
              </div>
            </div>
          )
        ) : (
          <>
            <div className="mt-7 grid grid-cols-2 gap-3" role="tablist" aria-label="Password mode">
              <button
                type="button"
                role="tab"
                aria-selected={pwMode === 'login'}
                onClick={() => {
                  setPwMode('login')
                  setPwError('')
                  resetPw()
                }}
                className={`rounded-[14px] border border-line px-4 py-2.5 text-[15px] font-medium ${
                  pwMode === 'login' ? 'bg-ink text-paper' : 'bg-paper'
                }`}
              >
                Sign in
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={pwMode === 'register'}
                onClick={() => {
                  setPwMode('register')
                  setPwError('')
                  resetPw()
                }}
                className={`rounded-[14px] border border-line px-4 py-2.5 text-[15px] font-medium ${
                  pwMode === 'register' ? 'bg-ink text-paper' : 'bg-paper'
                }`}
              >
                Create account
              </button>
            </div>

            <form onSubmit={handleSubmit(onPasswordSubmit)} className="mt-6 space-y-4" noValidate>
              <label className="block">
                <span className="mb-1.5 block text-[14px] font-medium">Email</span>
                <span className="relative block">
                  <Mail
                    size={17}
                    aria-hidden
                    className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft"
                  />
                  <input
                    type="email"
                    autoComplete="email"
                    placeholder="you@company.com"
                    className="field pl-11"
                    {...register('email')}
                  />
                </span>
                {errors.email && (
                  <span className="mt-1.5 block text-[13px] text-danger">
                    {errors.email.message}
                  </span>
                )}
              </label>

              <label className="block">
                <span className="mb-1.5 block text-[14px] font-medium">Password</span>
                <span className="relative block">
                  <Lock
                    size={17}
                    aria-hidden
                    className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft"
                  />
                  <input
                    type="password"
                    autoComplete={pwMode === 'login' ? 'current-password' : 'new-password'}
                    placeholder="At least 8 characters"
                    className="field pl-11"
                    {...register('password')}
                  />
                </span>
                {errors.password && (
                  <span className="mt-1.5 block text-[13px] text-danger">
                    {errors.password.message}
                  </span>
                )}
              </label>

              {pwMode === 'register' && (
                <label className="block">
                  <span className="mb-1.5 block text-[14px] font-medium">
                    Display name <span className="text-ink-soft">(optional)</span>
                  </span>
                  <span className="relative block">
                    <UserPlus
                      size={17}
                      aria-hidden
                      className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-soft"
                    />
                    <input
                      type="text"
                      autoComplete="name"
                      placeholder="How should we address you?"
                      className="field pl-11"
                      {...register('display_name')}
                    />
                  </span>
                </label>
              )}

              {(pwError || pwMutation.error) && (
                <p
                  role="alert"
                  className="rounded-[14px] border border-danger bg-danger/8 px-4 py-3 text-[14px] text-danger"
                >
                  {pwError ||
                    (pwMutation.error instanceof ApiError
                      ? pwMutation.error.message
                      : 'Something went wrong. Check the API server and try again.')}
                </p>
              )}

              <button type="submit" disabled={pwMutation.isPending} className="btn w-full justify-center">
                {pwMutation.isPending
                  ? 'Checking…'
                  : pwMode === 'login'
                    ? `Sign in with ${providerName}`
                    : `Create ${providerName} account`}
                <span className="grid size-7 place-items-center rounded-full bg-lime text-ink">
                  <UserPlus size={14} aria-hidden />
                </span>
              </button>
            </form>
          </>
        )}

        <p className="mt-5 text-[14px] leading-relaxed text-ink-soft">{provider?.note}</p>

        {mode === 'passcode' && <div className="mt-5">{linkPanel}</div>}

        <p className="mt-4 border-t border-line/20 pt-4 text-[14px] text-ink-soft">
          You can also{' '}
          <Link
            to="/"
            className="font-medium text-ink underline decoration-lime decoration-[3px] underline-offset-4"
          >
            upload without an account
          </Link>{' '}
          — analysis still works, history stays on this device until you sign in.
        </p>
      </section>
    </div>
  )
}
