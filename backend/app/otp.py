"""Passwordless email-OTP login for the Freebuff identity surface (spec #21).

Flow: ``POST /api/auth/otp/request`` creates a short numeric code, stores
only its SHA-256 hash (peppered with SECRET_KEY) and emails it. When no SMTP
sender is configured the code is logged server-side and returned in the
request response instead (keyless dev mode). ``POST /api/auth/otp/verify``
checks the code with a constant-time comparison, enforces expiry, a maximum
number of attempts and single use, then hands back a normal session.

Only stdlib is used for this path — no external OTP vendor or API key is
required. When Supabase Auth is configured it becomes the authority for
passcodes (``supabase_auth.py``): this module then only enforces the per-email
request cooldown and records the request for the audit trail.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import EmailOtp, utcnow

log = logging.getLogger("finsentry.auth")

#: Marks an audit row for a passcode delivered by an external provider
#: (Supabase Auth). Never a valid code hash, so it can never verify.
EXTERNAL_CODE_MARKER = "external-provider-otp"


class OtpRateLimited(Exception):
    """A fresh code may not be requested yet."""

    def __init__(self, retry_after: int):
        super().__init__(f"Too many code requests; retry in {retry_after}s.")
        self.retry_after = retry_after


class OtpDeliveryFailed(Exception):
    """An SMTP sender is configured, but the message could not be handed off.

    Kept separate from "no sender configured": the latter is the keyless dev
    mode that echoes the code back, while a refused send must never be mistaken
    for it — that would leak a live passcode into the API response.
    """

    def __init__(self, retry_after: int):
        super().__init__(f"Too many code requests; retry in {retry_after}s.")
        self.retry_after = retry_after


def generate_code(length: int | None = None) -> str:
    """Cryptographically random zero-padded numeric code."""
    n = length or config.OTP_LENGTH
    return str(secrets.randbelow(10**n)).zfill(n)


def hash_code(code: str) -> str:
    return hashlib.sha256(config.SECRET_KEY.encode("utf-8") + code.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; interpret them as UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _active_codes(db: Session, email: str) -> list[EmailOtp]:
    now = utcnow()
    rows = db.scalars(
        select(EmailOtp)
        .where(EmailOtp.email == email, EmailOtp.consumed_at.is_(None))
        .order_by(EmailOtp.created_at.desc())
    ).all()
    return [r for r in rows if _aware(r.expires_at) > now]


def _prune_expired(db: Session, email: str) -> None:
    now = utcnow()
    rows = db.scalars(select(EmailOtp).where(EmailOtp.email == email)).all()
    stale = [r for r in rows
             if _aware(r.expires_at) <= now - timedelta(hours=1) and r.consumed_at is not None]
    for r in stale:
        db.delete(r)
    if stale:
        db.commit()


def request_code(db: Session, email: str) -> tuple[str, int, bool]:
    """Create a code for *email*.

    Returns ``(plain_code, ttl_seconds, emailed)``. Raises OtpRateLimited
    when the per-email cooldown or the cap on active codes is hit.
    """
    now = utcnow()
    _prune_expired(db, email)
    active = _active_codes(db, email)
    if len(active) >= config.OTP_MAX_ACTIVE_PER_EMAIL:
        oldest = min(active, key=lambda r: r.expires_at)
        retry = max(1, int((_aware(oldest.expires_at) - now).total_seconds()))
        raise OtpRateLimited(retry)
    latest = db.scalars(
        select(EmailOtp)
        .where(EmailOtp.email == email)
        .order_by(EmailOtp.created_at.desc())
    ).first()
    if latest is not None:
        elapsed = (now - _aware(latest.created_at)).total_seconds()
        if elapsed < config.OTP_REQUEST_COOLDOWN_SECONDS:
            raise OtpRateLimited(int(config.OTP_REQUEST_COOLDOWN_SECONDS - elapsed))
    # A fresh code supersedes earlier ones so only one code is ever live.
    for r in active:
        r.consumed_at = now
    code = generate_code()
    row = EmailOtp(
        email=email,
        code_hash=hash_code(code),
        expires_at=now + timedelta(seconds=config.OTP_TTL_SECONDS),
    )
    db.add(row)
    db.commit()
    try:
        emailed = send_code_email(email, code)
    except OtpDeliveryFailed:
        # No email left the building, so the code must not stay redeemable and
        # no cooldown may be left behind: drop the row and let the caller
        # report the failure instead of silently degrading to dev mode.
        db.delete(row)
        db.commit()
        raise
    if not emailed:
        log.warning("OTP for %s: %s (no SMTP sender configured — dev mode)", email, code)
    return code, config.OTP_TTL_SECONDS, emailed


def verify_code(db: Session, email: str, code: str) -> str:
    """Check a code. Returns 'verified' | 'missing' | 'expired' | 'locked' | 'mismatch'."""
    now = utcnow()
    row = db.scalars(
        select(EmailOtp)
        .where(EmailOtp.email == email, EmailOtp.consumed_at.is_(None))
        .order_by(EmailOtp.created_at.desc())
    ).first()
    if row is None:
        return "missing"
    if _aware(row.expires_at) <= now:
        row.consumed_at = now
        db.commit()
        return "expired"
    if row.attempts >= config.OTP_MAX_ATTEMPTS:
        row.consumed_at = now  # lock the code after too many guesses
        db.commit()
        return "locked"
    if not hmac.compare_digest(row.code_hash, hash_code(code.strip())):
        row.attempts += 1
        db.commit()
        return "mismatch"
    row.consumed_at = now
    db.commit()
    return "verified"


def _latest_request_age(db: Session, email: str) -> float | None:
    latest = db.scalars(
        select(EmailOtp)
        .where(EmailOtp.email == email)
        .order_by(EmailOtp.created_at.desc())
    ).first()
    if latest is None:
        return None
    return (utcnow() - _aware(latest.created_at)).total_seconds()


def check_external_cooldown(db: Session, email: str) -> None:
    """Refuse a second request that lands inside the per-email cooldown.

    Read-only on purpose: it runs *before* the provider is called, so a refused
    request never reaches the provider's mail quota.
    """
    elapsed = _latest_request_age(db, email)
    if elapsed is not None and elapsed < config.OTP_REQUEST_COOLDOWN_SECONDS:
        raise OtpRateLimited(int(config.OTP_REQUEST_COOLDOWN_SECONDS - elapsed))


def record_external_request(db: Session, email: str) -> None:
    """Audit row for a code the external provider accepted for delivery.

    Call this **after** the provider reports a successful send. Recording it
    first would leave a cooldown behind for an email that was never sent, so a
    user whose send failed (mail quota, outage, bad address) would be locked
    out locally on top of the provider's own refusal.

    We never see a Supabase passcode, so no hash is stored. The row is marked
    consumed so it can never be mistaken for a redeemable code of ours. Its
    only jobs are the per-email cooldown and the audit trail.
    """
    now = utcnow()
    _prune_expired(db, email)
    db.add(EmailOtp(
        email=email,
        code_hash=EXTERNAL_CODE_MARKER,
        expires_at=now,
        consumed_at=now,
    ))
    db.commit()


def send_code_email(to_email: str, code: str) -> bool:
    """Email the code via the configured SMTP sender. False when unconfigured.

    Raises :class:`OtpDeliveryFailed` when a sender *is* configured but the
    hand-off fails (bad credentials, blocked port, unreachable host).
    """
    if not config.email_configured():
        return False
    minutes = max(1, config.OTP_TTL_SECONDS // 60)
    msg = EmailMessage()
    msg["Subject"] = f"Your {config.BRAND['name']} sign-in code"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_email
    msg.set_content(
        f"Your {config.BRAND['name']} sign-in code is:\n\n    {code}\n\n"
        f"It expires in {minutes} minute(s) and can be used once. "
        "If you did not request it, ignore this email."
    )
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD or "")
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("OTP email to %s failed: %s", to_email, exc)
        raise OtpDeliveryFailed(
            f"the mail sender at {config.SMTP_HOST}:{config.SMTP_PORT} "
            f"refused the message ({exc})") from exc
    return True
