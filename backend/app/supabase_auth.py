"""Supabase Auth (GoTrue) email one-time passcodes.

Supabase is the **authority** for the passcode: it generates the code, emails
it, and decides whether a submitted token is valid. This app never sees or
stores the code, and it never trusts a client-supplied success claim.

What this module does:

* ``send_otp(email)``   → ``POST {SUPABASE_URL}/auth/v1/otp``      (emails a link/code)
* ``verify_otp(email, token)`` → ``POST {SUPABASE_URL}/auth/v1/verify``
* ``verify_token_hash(hash)``  → ``POST {SUPABASE_URL}/auth/v1/verify``  (link token)
* ``identify(access_token)``   → ``GET  {SUPABASE_URL}/auth/v1/user``

Two things the hosted provider decides, not us:

* the redirect the emailed link points at — GoTrue reads ``redirect_to`` from a
  *query string* (or the ``redirect_to`` header), never from the JSON body, and
  only honours it when scheme+host match the project's Site URL;
* whether the email contains a link, a 6-digit code, or both — that is the
  dashboard's email template, so both redemption paths are supported here.

Only the publishable key is used, and only server-side: the browser never talks
to Supabase in this application, so no key is ever shipped to the client. A
verified token is then exchanged for **our own** local session cookie
(see ``routers/auth.py``), which keeps every existing permission check intact.

Deliberately no automatic retries: retrying a send could deliver a second code
and burn the project's mail quota, so a transport failure is reported instead
of being papered over.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from . import config

#: The GoTrue email OTP lifetime. Supabase's own default (Auth → Email OTP
#: Expiry, 3600s) is reported to the UI so the countdown is not a lie.
OTP_TTL_SECONDS = config.SUPABASE_OTP_TTL_SECONDS

#: How long Supabase's *built-in* mailer blocks after its quota is spent. The
#: built-in sender allows only a couple of messages per hour, and GoTrue
#: reports that as ``over_email_send_rate_limit`` with no "retry after N
#: seconds", so the wait is the hourly window rather than the usual short
#: per-address cooldown. Custom SMTP (Auth → SMTP Settings) removes this cap.
BUILTIN_MAILER_WINDOW_SECONDS = 3600

_RETRY_AFTER = re.compile(r"after (\d+)\s*seconds", re.IGNORECASE)


class SupabaseError(Exception):
    """Any failure talking to Supabase Auth. ``status_code`` is HTTP-facing."""

    code = "supabase_error"
    status_code = 502

    def __init__(self, message: str, *, retry_after: int | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class SupabaseNotConfigured(SupabaseError):
    code = "supabase_not_configured"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Supabase Auth is not configured on the server "
                         "(set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY).")


class SupabaseUnavailable(SupabaseError):
    """Network failure, timeout, or a 5xx from the provider."""

    code = "supabase_unavailable"
    status_code = 503


class SupabaseRateLimited(SupabaseError):
    code = "supabase_rate_limited"
    status_code = 429


class SupabaseInvalidCode(SupabaseError):
    code = "supabase_invalid_code"
    status_code = 401


class SupabaseValidationError(SupabaseError):
    code = "supabase_validation_failed"
    status_code = 400


def configured() -> bool:
    return config.supabase_auth_configured()


def status() -> dict:
    """Configuration snapshot for ``/api/auth/provider``. Never the key."""
    return {
        "configured": configured(),
        "provider": "supabase" if configured() else None,
        "project_host": config.SUPABASE_URL.split("//")[-1].split("/")[0] if configured() else None,
        "otp_ttl_seconds": OTP_TTL_SECONDS,
    }


@dataclass(frozen=True)
class Identity:
    """The verified Supabase identity behind a redeemed passcode."""

    user_id: str
    email: str


def _post(path: str, payload: dict, *, params: dict | None = None,
          invalid_message: str | None = None) -> dict:
    return _send("POST", path, payload, params=params, invalid_message=invalid_message)


def _send(method: str, path: str, payload: dict | None = None, *,
          params: dict | None = None, bearer: str | None = None,
          invalid_message: str | None = None) -> dict:
    if not configured():
        raise SupabaseNotConfigured()
    headers = {
        "apikey": config.SUPABASE_KEY,
        "Authorization": f"Bearer {bearer or config.SUPABASE_KEY}",
        "Content-Type": "application/json",
    }
    url = f"{config.SUPABASE_URL}{path}"
    try:
        with httpx.Client(timeout=float(config.SUPABASE_TIMEOUT_SECONDS)) as client:
            if method == "GET":
                response = client.get(url, headers=headers, params=params)
            else:
                response = client.post(url, json=payload, headers=headers, params=params)
    except httpx.TimeoutException as exc:
        raise SupabaseUnavailable(
            f"Supabase Auth did not answer within {config.SUPABASE_TIMEOUT_SECONDS}s.") from exc
    except httpx.HTTPError as exc:
        raise SupabaseUnavailable(
            "Could not reach Supabase Auth. Check the network and the configured "
            "SUPABASE_URL.") from exc

    if response.status_code >= 400:
        raise _error_from(response, invalid_message)
    try:
        return response.json() if response.content else {}
    except ValueError as exc:
        raise SupabaseUnavailable("Supabase Auth returned a malformed response.") from exc


def _error_from(response: httpx.Response,
                invalid_message: str | None = None) -> SupabaseError:
    """Translate a GoTrue error body into a typed, user-safe error."""
    body: dict = {}
    try:
        parsed = response.json()
        if isinstance(parsed, dict):
            body = parsed
    except ValueError:
        body = {}
    detail = str(body.get("msg") or body.get("message") or body.get("error_description")
                 or f"Supabase Auth returned HTTP {response.status_code}.")
    error_code = str(body.get("error_code") or "")
    retry = None
    match = _RETRY_AFTER.search(detail)
    if match:
        retry = int(match.group(1))

    if response.status_code == 429 or error_code in ("over_email_send_rate_limit",
                                                     "over_request_rate_limit",
                                                     "over_request_rate_limit_per_email"):
        if error_code == "over_email_send_rate_limit" and retry is None:
            # The built-in sender's hourly quota, not a per-address cooldown.
            # Waiting a few seconds will never help, so say what actually does.
            return SupabaseRateLimited(
                "Supabase's built-in email sender is capped at a couple of messages "
                "per hour and its quota is used up, so no code could be sent. Add "
                "custom SMTP in the Supabase dashboard (Authentication → SMTP "
                "Settings) for a real quota, or wait for the hourly window.",
                retry_after=BUILTIN_MAILER_WINDOW_SECONDS)
        return SupabaseRateLimited(
            f"Supabase is rate limiting code requests ({detail}).", retry_after=retry)
    if response.status_code in (401, 403) or error_code in ("otp_expired",
                                                            "otp_disabled",
                                                            "invalid_credentials"):
        return SupabaseInvalidCode(invalid_message
                                   or "That passcode is incorrect or has expired.")
    if response.status_code in (400, 422):
        # Keep the provider's own wording — it names the offending input.
        return SupabaseValidationError(f"Supabase rejected the request: {detail}")
    return SupabaseUnavailable(f"Supabase Auth error (HTTP {response.status_code}): {detail}")


def send_otp(email: str) -> None:
    """Ask Supabase to email a sign-in link (and code, if the template has one).

    ``create_user`` keeps the existing product behaviour: redeeming a token for
    an unknown address creates the account on first sign-in.

    ``redirect_to`` travels in the query string because GoTrue reads it from the
    request form/header — putting it in the JSON body is silently ignored, which
    is exactly how the link ends up on the project's Site URL instead.
    """
    params = {"redirect_to": config.SUPABASE_REDIRECT_TO} if config.SUPABASE_REDIRECT_TO else None
    _post("/auth/v1/otp", {"email": email, "create_user": True}, params=params)


def _identity_from_verify(payload: dict, fallback_email: str = "") -> Identity:
    user = payload.get("user") or {}
    user_id = str(user.get("id") or "")
    if not user_id:
        # A 200 without a user would be a provider contract change: treat it as
        # a failure rather than minting a session on an unverified identity.
        raise SupabaseUnavailable("Supabase verified the token but returned no user identity.")
    return Identity(user_id=user_id,
                    email=str(user.get("email") or fallback_email).strip().lower())


def verify_otp(email: str, token: str) -> Identity:
    """Redeem a passcode with Supabase. Raises SupabaseInvalidCode when wrong."""
    payload = _post("/auth/v1/verify", {"email": email, "token": token, "type": "email"})
    return _identity_from_verify(payload, email)


def verify_token_hash(token_hash: str, token_type: str = "magiclink") -> Identity:
    """Redeem the token from an emailed sign-in link.

    This is how a link gets turned into a session without the browser ever
    following Supabase's redirect: the user (or our callback page) hands us the
    ``token``/``token_hash`` from the URL and Supabase decides if it is live.
    """
    payload = _post("/auth/v1/verify", {"token_hash": token_hash, "type": token_type},
                    invalid_message="That sign-in link is invalid or has already been used.")
    return _identity_from_verify(payload)


def identify(access_token: str) -> Identity:
    """Resolve the user behind a Supabase access token (the link's fragment)."""
    payload = _send("GET", "/auth/v1/user", bearer=access_token,
                    invalid_message="That sign-in link has expired or was already used.")
    user_id = str(payload.get("id") or "")
    email = str(payload.get("email") or "").strip().lower()
    if not user_id or not email:
        raise SupabaseUnavailable("Supabase returned no identity for that access token.")
    return Identity(user_id=user_id, email=email)
