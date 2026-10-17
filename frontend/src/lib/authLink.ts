/**
 * Parsing for Supabase Auth email sign-in links.
 *
 * A link the browser follows lands on our callback with the session in the URL
 * *fragment*:
 *
 *   /auth/callback#access_token=…&refresh_token=…&expires_in=3600
 *                 &token_type=bearer&type=magiclink
 *
 * The same link carries a single-use `token` in its query string, which is what
 * we hand to Supabase when the browser refuses to open it (nothing listening on
 * the redirect port, mail client stripping the fragment, link opened on another
 * device, …). Both shapes are parsed here so the login page and the callback page
 * agree on what a "link" is.
 */

export interface AuthLinkCredentials {
  access_token?: string
  token_hash?: string
  type: string
  error?: string
  error_description?: string
}

/** A bare token hash (what `/auth/v1/verify` accepts) is long and URL-safe. */
const TOKEN_HASH = /^[A-Za-z0-9_-]{20,}$/

function normaliseType(value: string | null): string {
  const raw = (value || '').trim().toLowerCase().replace(/[-_]/g, '')
  if (raw === 'signup' || raw === 'email' || raw === 'recovery') return raw
  return 'magiclink'
}

function collect(segment: string, out: AuthLinkCredentials): void {
  const params = new URLSearchParams(segment)

  if (!out.error && params.get('error')) out.error = params.get('error') ?? undefined
  if (!out.error_description && params.get('error_description')) {
    out.error_description = params.get('error_description') ?? undefined
  }
  if (!out.access_token && params.get('access_token')) {
    out.access_token = params.get('access_token') ?? undefined
  }

  if (!out.token_hash) {
    const hash = params.get('token_hash')
    const token = params.get('token')
    if (hash) out.token_hash = hash
    else if (token && TOKEN_HASH.test(token) && !/^\d+$/.test(token)) out.token_hash = token
  }

  if (params.get('type')) out.type = normaliseType(params.get('type'))
}

/**
 * Extract credentials from anything a user might have: the full URL from the
 * email, just the `#…` fragment, just the `?…` query, or a bare token hash.
 */
export function parseAuthLink(raw: string): AuthLinkCredentials {
  const out: AuthLinkCredentials = { type: 'magiclink' }
  const text = (raw || '').trim()
  if (!text) return out

  const hashAt = text.indexOf('#')
  const queryAt = text.indexOf('?')

  // The fragment is parsed first so its access_token is preferred.
  if (hashAt >= 0) collect(text.slice(hashAt + 1), out)
  if (queryAt >= 0 && (hashAt < 0 || queryAt < hashAt)) {
    collect(text.slice(queryAt + 1, hashAt >= 0 ? hashAt : undefined), out)
  }
  // "access_token=…&type=magiclink" pasted without its leading ?/#.
  if (hashAt < 0 && queryAt < 0 && text.includes('=')) collect(text, out)
  // A bare token hash pasted on its own.
  if (!out.access_token && !out.token_hash && TOKEN_HASH.test(text)) out.token_hash = text

  return out
}

/** True when the credentials are something the backend can actually redeem. */
export function redeemable(creds: AuthLinkCredentials): boolean {
  return Boolean(creds.access_token || creds.token_hash)
}
