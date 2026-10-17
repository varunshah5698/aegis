"""Authentication: password hashing, sessions, and the Freebuff identity provider.

Passwords use PBKDF2-HMAC-SHA256 with a per-user salt (stdlib only). Sessions
are opaque random tokens stored server-side in `user_sessions` and delivered as
httpOnly cookies — tokens are never exposed to frontend JavaScript (spec #21).

The brand identity provider (default "Freebuff") is the sign-in surface shown on
the login page. Local email/password accounts are the working credential path;
an external SSO handshake can be layered on the same session table later.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import User, UserSession, utcnow

COOKIE_NAME = "finsentry_session"


# ------------------------------------------------------------- passwords ----
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, config.PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${config.PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# -------------------------------------------------------------- sessions ----
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    expires = utcnow() + timedelta(hours=config.SESSION_TTL_HOURS)
    db.add(
        UserSession(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=expires,
            user_agent=user_agent[:255],
        )
    )
    db.commit()
    return token


def get_session_user(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.get(UserSession, _hash_token(token))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        db.delete(row)
        db.commit()
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: Session, token: str) -> None:
    row = db.get(UserSession, _hash_token(token))
    if row is not None:
        db.delete(row)
        db.commit()


# ---------------------------------------------------------------- users -----
def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.strip().lower()))


def create_user(db: Session, email: str, password: str, display_name: str = "") -> User:
    user = User(
        email=email.strip().lower(),
        display_name=display_name or email.split("@")[0],
        password_hash=hash_password(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_otp_user(db: Session, email: str, display_name: str = "") -> User:
    """Passwordless account: the hash sentinel has no '$' segments, so
    verify_password() always rejects it and only OTP can open a session."""
    user = User(
        email=email.strip().lower(),
        display_name=display_name or email.split("@")[0],
        password_hash="otp-only",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def provider_label() -> str:
    """The identity provider shown on the login page (brand-configurable)."""
    return config.BRAND["auth_provider"]
