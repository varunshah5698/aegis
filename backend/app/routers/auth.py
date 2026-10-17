"""Authentication routes — the Freebuff sign-in surface (spec #21)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from pydantic import BaseModel, EmailStr, Field

from .. import config, otp, security, supabase_auth
from ..database import get_db
from ..models import AuditEvent, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE = security.COOKIE_NAME


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterPayload(Credentials):
    display_name: str = Field(default="", max_length=120)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    provider: str


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE, value=token, httponly=True, samesite="lax",
        secure=False, max_age=60 * 60 * 24 * 14, path="/",
    )


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


@router.get("/provider")
def provider() -> dict:
    """Identity provider shown on the login page (brand-configurable)."""
    otp_provider = config.otp_provider()
    notes = {
        "supabase": ("Passwordless sign-in: Supabase Auth emails a one-time code. "
                     "Entering it is verified by Supabase and exchanged for a "
                     f"{security.provider_label()} httpOnly session cookie. If the "
                     "project's email template still sends a link, opening that "
                     "link works too."),
        "smtp": ("Passwordless sign-in: we email you a one-time passcode from the "
                 f"configured sender. {security.provider_label()} sessions are "
                 "httpOnly cookies."),
        "dev_console": ("Passwordless sign-in: no email sender is configured, so "
                        "passcodes are printed to the API log and returned in the "
                        "response (development mode only)."),
    }
    return {
        "provider": security.provider_label(),
        "label": f"Continue with {security.provider_label()}",
        "mode": "supabase_otp" if otp_provider == "supabase" else "local_session",
        "note": notes[otp_provider],
        "otp_enabled": True,
        "otp_length": config.OTP_LENGTH,
        "otp_ttl_seconds": config.otp_ttl_seconds(),
        "otp_delivery": "email" if otp_provider in ("supabase", "smtp") else "dev_console",
        "otp_provider": otp_provider,
        "link_enabled": otp_provider == "supabase",
        "link_callback": config.SUPABASE_REDIRECT_TO if otp_provider == "supabase" else "",
    }


# ------------------------------------------------------ Supabase sessions ----
def _supabase_sign_in(db, identity: supabase_auth.Identity, display_name: str,
                      request: Request, response: Response, method: str) -> UserOut:
    """Exchange a Supabase-verified identity for our own session cookie.

    Shared by the passcode and sign-in-link paths so both produce exactly the
    same account, permissions and audit trail.
    """
    user = security.get_user_by_email(db, identity.email)
    if user is None:
        user = security.create_otp_user(db, identity.email, display_name)
        db.add(AuditEvent(user_id=user.id, action="auth.register",
                          resource_type="user", resource_id=user.id,
                          detail={"method": method,
                                  "supabase_user_id": identity.user_id}))
    if not user.is_active:
        db.commit()
        raise HTTPException(403, "This account is deactivated.")
    token = security.create_session(db, user, request.headers.get("user-agent", ""))
    _set_cookie(response, token)
    db.add(AuditEvent(user_id=user.id, action="auth.login",
                      resource_type="user", resource_id=user.id,
                      detail={"method": method, "supabase_user_id": identity.user_id}))
    db.commit()
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   provider=security.provider_label())


class OtpRequestPayload(BaseModel):
    email: EmailStr


class OtpVerifyPayload(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    display_name: str = Field(default="", max_length=120)


@router.post("/otp/request")
def otp_request(payload: OtpRequestPayload, request: Request, db=Depends(get_db)):
    """Email a one-time passcode. Always 200 (no account enumeration)."""
    email = payload.email.strip().lower()

    # ---------------------------------------------------- Supabase Auth ----
    # Supabase generates, emails and later verifies the code; we never see it.
    if config.otp_provider() == "supabase":
        # Checked read-only first: a refused request must not reach the mail
        # quota, and a *failed* send must not leave a cooldown behind either.
        try:
            otp.check_external_cooldown(db, email)
        except otp.OtpRateLimited as exc:
            raise HTTPException(
                429, f"A code was requested too recently. Retry in {exc.retry_after}s.",
                headers={"Retry-After": str(exc.retry_after)})
        try:
            supabase_auth.send_otp(email)
        except supabase_auth.SupabaseRateLimited as exc:
            retry = exc.retry_after or config.OTP_REQUEST_COOLDOWN_SECONDS
            db.add(AuditEvent(user_id=None, action="auth.otp_request_failed",
                              resource_type="user", resource_id=email[:64],
                              detail={"provider": "supabase", "code": exc.code,
                                      "retry_after": retry}))
            db.commit()
            raise HTTPException(429, str(exc),
                                headers={"Retry-After": str(retry)}) from exc
        except supabase_auth.SupabaseError as exc:
            db.add(AuditEvent(user_id=None, action="auth.otp_request_failed",
                              resource_type="user", resource_id=email[:64],
                              detail={"provider": "supabase", "code": exc.code}))
            db.commit()
            raise HTTPException(exc.status_code, str(exc)) from exc
        # The provider accepted the send: only now does a cooldown apply.
        otp.record_external_request(db, email)
        db.add(AuditEvent(user_id=None, action="auth.otp_requested",
                          resource_type="user", resource_id=email[:64],
                          detail={"delivery": "email", "provider": "supabase",
                                  "agent": request.headers.get("user-agent", "")[:120]}))
        db.commit()
        # No dev_code: the passcode left the building in an email.
        return {"ok": True, "email": email,
                "expires_in_seconds": supabase_auth.OTP_TTL_SECONDS,
                "delivery": "email", "length": config.OTP_LENGTH,
                "provider": "supabase"}

    # ------------------------------------------- local code (SMTP or dev) --
    try:
        code, ttl, emailed = otp.request_code(db, email)
    except otp.OtpRateLimited as exc:
        raise HTTPException(
            429, f"A code was requested too recently. Retry in {exc.retry_after}s.",
            headers={"Retry-After": str(exc.retry_after)})
    except otp.OtpDeliveryFailed as exc:
        db.add(AuditEvent(user_id=None, action="auth.otp_request_failed",
                          resource_type="user", resource_id=email[:64],
                          detail={"provider": "smtp", "reason": "delivery_failed"}))
        db.commit()
        raise HTTPException(
            502,
            "We could not send the sign-in email. Check SMTP_HOST, SMTP_USER "
            f"and SMTP_PASSWORD in backend/.env, then try again. ({exc})",
        ) from exc
    db.add(AuditEvent(user_id=None, action="auth.otp_requested",
                      resource_type="user", resource_id=email[:64],
                      detail={"delivery": "email" if emailed else "dev_console",
                              "agent": request.headers.get("user-agent", "")[:120]}))
    db.commit()
    body: dict = {"ok": True, "email": email, "expires_in_seconds": ttl,
            "delivery": "email" if emailed else "dev_console",
            "length": config.OTP_LENGTH}
    if not emailed:
        # Keyless dev mode only: with an SMTP sender configured the code
        # travels by email and is never returned here.
        body["dev_code"] = code
    return body


@router.post("/otp/verify", response_model=UserOut)
def otp_verify(payload: OtpVerifyPayload, response: Response,
               request: Request, db=Depends(get_db)):
    """Redeem a passcode. Auto-creates the account on first sign-in."""
    email = payload.email.strip().lower()

    # ------------------------------------------- Supabase Auth authority ---
    # Supabase decides whether the token is valid; only then do we mint our
    # own session cookie. A failed redemption never creates an account.
    if config.otp_provider() == "supabase":
        try:
            identity = supabase_auth.verify_otp(email, payload.code.strip())
        except supabase_auth.SupabaseInvalidCode as exc:
            db.add(AuditEvent(user_id=None, action="auth.otp_failed",
                              resource_type="user", resource_id=email[:64],
                              detail={"reason": "invalid_code", "provider": "supabase"}))
            db.commit()
            raise HTTPException(401, str(exc)) from exc
        except supabase_auth.SupabaseRateLimited as exc:
            retry = exc.retry_after or 30
            raise HTTPException(429, str(exc),
                                headers={"Retry-After": str(retry)}) from exc
        except supabase_auth.SupabaseError as exc:
            db.add(AuditEvent(user_id=None, action="auth.otp_failed",
                              resource_type="user", resource_id=email[:64],
                              detail={"reason": "provider_error", "provider": "supabase",
                                      "code": exc.code}))
            db.commit()
            raise HTTPException(exc.status_code, str(exc)) from exc
        return _supabase_sign_in(db, identity, payload.display_name, request, response,
                                 "supabase_otp")

    result = otp.verify_code(db, email, payload.code)
    if result != "verified":
        message = {
            "missing": "No active code for this email. Request a new one.",
            "expired": "That code has expired. Request a new one.",
            "locked": "Too many incorrect attempts. Request a new code.",
            "mismatch": "Incorrect code.",
        }[result]
        db.add(AuditEvent(user_id=None, action="auth.otp_failed",
                          resource_type="user", resource_id=email[:64],
                          detail={"reason": result}))
        db.commit()
        raise HTTPException(401, message)
    user = security.get_user_by_email(db, email)
    if user is None:
        user = security.create_otp_user(db, email, payload.display_name)
        db.add(AuditEvent(user_id=user.id, action="auth.register",
                          resource_type="user", resource_id=user.id,
                          detail={"method": "otp"}))
    if not user.is_active:
        raise HTTPException(403, "This account is deactivated.")
    token = security.create_session(db, user, request.headers.get("user-agent", ""))
    _set_cookie(response, token)
    db.add(AuditEvent(user_id=user.id, action="auth.login",
                      resource_type="user", resource_id=user.id,
                      detail={"method": "otp"}))
    db.commit()
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   provider=security.provider_label())


class SupabaseRedeemPayload(BaseModel):
    """A sign-in link redemption.

    ``access_token`` is what the link fragment carries once the browser follows
    it; ``token_hash`` (a.k.a. the link's ``token`` query param) is what we get
    when the link could not be opened and is pasted back instead. Exactly one of
    them must be present.
    """

    access_token: str | None = Field(default=None, max_length=4096)
    token_hash: str | None = Field(default=None, max_length=512)
    type: str = Field(default="magiclink", max_length=32)
    display_name: str = Field(default="", max_length=120)


#: Supabase verification types a sign-in link may carry.
_LINK_TYPES = {"magiclink", "email", "signup", "recovery"}


@router.post("/supabase/redeem", response_model=UserOut)
def supabase_redeem(payload: SupabaseRedeemPayload, response: Response,
                    request: Request, db=Depends(get_db)):
    """Finish a sign-in Supabase started by email (link or pasted link).

    Supabase decides whether the token is live; a failed redemption never
    creates an account and never yields a session.
    """
    if config.otp_provider() != "supabase":
        raise HTTPException(409, "Supabase Auth is not the configured sign-in provider.")

    access_token = (payload.access_token or "").strip()
    token_hash = (payload.token_hash or "").strip()
    if bool(access_token) == bool(token_hash):
        raise HTTPException(422, "Provide exactly one of access_token or token_hash.")
    if token_hash and payload.type not in _LINK_TYPES:
        raise HTTPException(422, f"Unsupported link type '{payload.type}'.")

    method = "supabase_link" if access_token else f"supabase_{payload.type}"
    try:
        identity = (supabase_auth.identify(access_token) if access_token
                    else supabase_auth.verify_token_hash(token_hash, payload.type))
    except supabase_auth.SupabaseInvalidCode as exc:
        db.add(AuditEvent(user_id=None, action="auth.link_failed",
                          resource_type="user", resource_id="signin_link",
                          detail={"reason": "invalid_link", "provider": "supabase",
                                  "kind": method}))
        db.commit()
        raise HTTPException(401, str(exc)) from exc
    except supabase_auth.SupabaseRateLimited as exc:
        retry = exc.retry_after or 30
        raise HTTPException(429, str(exc),
                            headers={"Retry-After": str(retry)}) from exc
    except supabase_auth.SupabaseError as exc:
        db.add(AuditEvent(user_id=None, action="auth.link_failed",
                          resource_type="user", resource_id="signin_link",
                          detail={"reason": "provider_error", "provider": "supabase",
                                  "code": exc.code}))
        db.commit()
        raise HTTPException(exc.status_code, str(exc)) from exc

    return _supabase_sign_in(db, identity, payload.display_name, request, response, method)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload, response: Response,
             request: Request, db=Depends(get_db)):
    email = payload.email.strip().lower()
    if security.get_user_by_email(db, email):
        raise HTTPException(409, "An account with this email already exists.")
    if len(payload.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters.")
    user = security.create_user(db, email, payload.password, payload.display_name)
    token = security.create_session(db, user, request.headers.get("user-agent", ""))
    _set_cookie(response, token)
    db.add(AuditEvent(user_id=user.id, action="auth.register", resource_type="user",
                      resource_id=user.id))
    db.commit()
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   provider=security.provider_label())


@router.post("/login", response_model=UserOut)
def login(payload: Credentials, response: Response, request: Request,
          db=Depends(get_db)):
    user = security.get_user_by_email(db, payload.email)
    if user is None or not security.verify_password(payload.password, user.password_hash):
        db.add(AuditEvent(user_id=user.id if user else None, action="auth.login_failed",
                          resource_type="user", resource_id=payload.email[:64]))
        db.commit()
        raise HTTPException(401, "Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(403, "This account is deactivated.")
    token = security.create_session(db, user, request.headers.get("user-agent", ""))
    _set_cookie(response, token)
    db.add(AuditEvent(user_id=user.id, action="auth.login", resource_type="user",
                      resource_id=user.id))
    db.commit()
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   provider=security.provider_label())


@router.post("/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        security.revoke_session(db, token)
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(request: Request, db=Depends(get_db)):
    user = security.get_session_user(db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Not signed in.")
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   provider=security.provider_label())


# ------------------------------------------------------------ dependency ----
def current_user_optional(request: Request, db=Depends(get_db)) -> User | None:
    return security.get_session_user(db, request.cookies.get(COOKIE))


def current_user(request: Request, db=Depends(get_db)) -> User:
    user = security.get_session_user(db, request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user
