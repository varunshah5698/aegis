"""Supabase Auth (GoTrue) email OTP integration.

No network is used anywhere in this file: the HTTP transport is monkeypatched,
so the suite proves our request/response handling without sending real email or
spending the project's mail quota. The live endpoint contract these tests
encode was verified against the project's own GoTrue instance:

* ``POST /auth/v1/otp``    with ``{"email": …}`` (400 validation_failed when absent)
* ``POST /auth/v1/verify`` with ``{"email", "token", "type": "email"}``
  (403 ``otp_expired`` for a wrong token)
"""
from __future__ import annotations

import uuid

import httpx
import pytest

from app import config, supabase_auth
from app.database import SessionLocal
from app.models import AuditEvent, User

KEY = "sb_publishable_test_key_do_not_use"
URL = "https://testref.supabase.co"


def _email() -> str:
    return f"sb-{uuid.uuid4().hex[:12]}@test.dev"


@pytest.fixture()
def supabase(monkeypatch):
    """Point the app at a (fake) configured Supabase project."""
    monkeypatch.setattr(config, "SUPABASE_URL", URL, raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", KEY, raising=False)


@pytest.fixture()
def transport(monkeypatch):
    """Replace httpx.Client with a recorder that replays canned responses."""

    def install(responses):
        calls: list[dict] = []

        class _Client:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def _reply(self):
                item = responses.pop(0) if responses else httpx.Response(500, json={})
                if isinstance(item, Exception):
                    raise item
                return item

            def post(self, url, json=None, headers=None, params=None):
                calls.append({"method": "POST", "url": url, "json": json,
                              "headers": headers or {}, "params": params})
                return self._reply()

            def get(self, url, headers=None, params=None):
                calls.append({"method": "GET", "url": url, "json": None,
                              "headers": headers or {}, "params": params})
                return self._reply()

        monkeypatch.setattr(supabase_auth.httpx, "Client", _Client)
        return calls

    return install


# --------------------------------------------------------------------------- #
# configuration
# --------------------------------------------------------------------------- #


def test_project_url_tolerates_pasted_rest_suffix(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co/rest/v1/")
    assert config._supabase_project_url() == "https://abc.supabase.co"
    monkeypatch.setenv("SUPABASE_URL", "https://abc.supabase.co")
    assert config._supabase_project_url() == "https://abc.supabase.co"


def test_provider_selection_priority(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", URL, raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", KEY, raising=False)
    assert config.otp_provider() == "supabase"
    assert config.otp_ttl_seconds() == config.SUPABASE_OTP_TTL_SECONDS

    monkeypatch.setattr(config, "SUPABASE_KEY", "", raising=False)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com", raising=False)
    monkeypatch.setattr(config, "SMTP_FROM", "a@example.com", raising=False)
    assert config.otp_provider() == "smtp"
    assert config.otp_ttl_seconds() == config.OTP_TTL_SECONDS

    monkeypatch.setattr(config, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(config, "SMTP_FROM", "", raising=False)
    assert config.otp_provider() == "dev_console"


def test_otp_provider_override_wins_over_detection(monkeypatch):
    """`OTP_PROVIDER` is the escape hatch when a provider is unusable."""
    monkeypatch.setattr(config, "SUPABASE_URL", URL, raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", KEY, raising=False)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com", raising=False)
    monkeypatch.setattr(config, "SMTP_FROM", "a@example.com", raising=False)

    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "dev_console")
    assert config.otp_provider() == "dev_console"
    # the countdown must follow the provider that actually issues the code
    assert config.otp_ttl_seconds() == config.OTP_TTL_SECONDS

    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "smtp")
    assert config.otp_provider() == "smtp"
    assert config.otp_ttl_seconds() == config.OTP_TTL_SECONDS

    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "supabase")
    assert config.otp_provider() == "supabase"
    assert config.otp_ttl_seconds() == config.SUPABASE_OTP_TTL_SECONDS


def test_override_to_an_unusable_provider_falls_back_instead_of_breaking(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", URL, raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", KEY, raising=False)
    monkeypatch.setattr(config, "SMTP_HOST", "", raising=False)
    monkeypatch.setattr(config, "SMTP_FROM", "", raising=False)

    # no SMTP sender configured: asking for smtp must not strand the user
    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "smtp")
    assert config.otp_provider() == "supabase"

    monkeypatch.setattr(config, "SUPABASE_KEY", "", raising=False)
    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "supabase")
    assert config.otp_provider() == "dev_console"


def test_status_never_includes_the_key(supabase):
    info = supabase_auth.status()
    assert info["configured"] is True
    assert info["project_host"] == "testref.supabase.co"
    assert KEY not in str(info)


# --------------------------------------------------------------------------- #
# request/verify plumbing
# --------------------------------------------------------------------------- #


def test_send_otp_posts_the_documented_payload(supabase, transport):
    calls = transport([httpx.Response(200, json={})])
    supabase_auth.send_otp("user@example.com")
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == f"{URL}/auth/v1/otp"
    assert call["json"] == {"email": "user@example.com", "create_user": True}
    assert call["headers"]["apikey"] == KEY
    assert call["headers"]["Authorization"] == f"Bearer {KEY}"
    # GoTrue reads redirect_to from the query string only; a body field is
    # silently dropped and the link goes to Site URL instead.
    assert call["params"] == {"redirect_to": config.SUPABASE_REDIRECT_TO}
    assert "redirect_to" not in call["json"]


def test_verify_otp_returns_the_identity(supabase, transport):
    calls = transport([httpx.Response(200, json={"access_token": "jwt",
                                                 "user": {"id": "sb-user-1",
                                                          "email": "User@Example.com"}})])
    identity = supabase_auth.verify_otp("user@example.com", "123456")
    assert identity.user_id == "sb-user-1"
    assert identity.email == "user@example.com"        # normalised
    assert calls[0]["url"] == f"{URL}/auth/v1/verify"
    assert calls[0]["json"] == {"email": "user@example.com", "token": "123456",
                                "type": "email"}


def test_verify_without_a_user_identity_is_a_failure(supabase, transport):
    transport([httpx.Response(200, json={"access_token": "jwt"})])
    with pytest.raises(supabase_auth.SupabaseUnavailable):
        supabase_auth.verify_otp("user@example.com", "123456")


def test_error_taxonomy_maps_provider_responses():
    rate = supabase_auth._error_from(httpx.Response(
        429, json={"error_code": "over_email_send_rate_limit",
                   "msg": "For security purposes, you can only request this after 47 seconds."}))
    assert isinstance(rate, supabase_auth.SupabaseRateLimited)
    assert rate.retry_after == 47 and rate.status_code == 429

    expired = supabase_auth._error_from(httpx.Response(
        403, json={"error_code": "otp_expired", "msg": "Token has expired or is invalid"}))
    assert isinstance(expired, supabase_auth.SupabaseInvalidCode)
    assert expired.status_code == 401

    bad_input = supabase_auth._error_from(httpx.Response(
        400, json={"error_code": "validation_failed", "msg": "Invalid email"}))
    assert isinstance(bad_input, supabase_auth.SupabaseValidationError)

    down = supabase_auth._error_from(httpx.Response(503, json={}))
    assert isinstance(down, supabase_auth.SupabaseUnavailable)


def test_transport_failure_is_reported_and_not_retried(supabase, transport):
    calls = transport([httpx.ConnectError("boom")])
    with pytest.raises(supabase_auth.SupabaseUnavailable):
        supabase_auth.send_otp("user@example.com")
    # a silent retry would deliver a second passcode
    assert len(calls) == 1


def test_unconfigured_provider_refuses_to_send(monkeypatch, transport):
    monkeypatch.setattr(config, "SUPABASE_URL", "", raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", "", raising=False)
    calls = transport([])
    with pytest.raises(supabase_auth.SupabaseNotConfigured):
        supabase_auth.send_otp("user@example.com")
    assert calls == []


# --------------------------------------------------------------------------- #
# the API endpoints a user actually hits
# --------------------------------------------------------------------------- #


def test_provider_endpoint_advertises_supabase(client, supabase):
    body = client.get("/api/auth/provider").json()
    assert body["otp_provider"] == "supabase"
    assert body["mode"] == "supabase_otp"
    assert body["otp_delivery"] == "email"
    assert body["otp_ttl_seconds"] == config.SUPABASE_OTP_TTL_SECONDS
    assert body["link_enabled"] is True
    assert body["link_callback"] == config.SUPABASE_REDIRECT_TO
    assert KEY not in str(body)


def test_request_sends_by_email_and_never_returns_a_code(client, supabase, transport):
    calls = transport([httpx.Response(200, json={})])
    email = _email()
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery"] == "email"
    assert body["provider"] == "supabase"
    assert body["expires_in_seconds"] == config.SUPABASE_OTP_TTL_SECONDS
    assert "dev_code" not in body                  # the whole point of the switch
    assert KEY not in r.text
    assert calls[0]["json"]["email"] == email

    db = SessionLocal()
    try:
        row = (db.query(AuditEvent)
               .filter(AuditEvent.action == "auth.otp_requested",
                       AuditEvent.resource_id == email[:64])
               .order_by(AuditEvent.created_at.desc()).first())
        assert row is not None
        assert row.detail["provider"] == "supabase"
        assert row.detail["delivery"] == "email"
    finally:
        db.close()


def test_request_maps_provider_rate_limit_to_429(client, supabase, transport):
    transport([httpx.Response(429, json={
        "error_code": "over_email_send_rate_limit",
        "msg": "For security purposes, you can only request this after 41 seconds."})])
    r = client.post("/api/auth/otp/request", json={"email": _email()})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "41"
    assert KEY not in r.text


def test_builtin_mailer_quota_names_the_real_fix():
    """The built-in sender's hourly cap is not a 30-second cooldown."""
    err = supabase_auth._error_from(httpx.Response(
        429, json={"error_code": "over_email_send_rate_limit",
                   "msg": "email rate limit exceeded"}))
    assert isinstance(err, supabase_auth.SupabaseRateLimited)
    assert err.retry_after == supabase_auth.BUILTIN_MAILER_WINDOW_SECONDS
    assert "SMTP" in str(err), str(err)


def test_failed_send_leaves_no_local_cooldown(client, supabase, transport):
    """A send the provider refused was never delivered, so retrying must work."""
    email = _email()
    transport([httpx.Response(429, json={"error_code": "over_email_send_rate_limit",
                                         "msg": "email rate limit exceeded"}),
               httpx.Response(200, json={})])
    first = client.post("/api/auth/otp/request", json={"email": email})
    assert first.status_code == 429
    assert first.headers["Retry-After"] == str(supabase_auth.BUILTIN_MAILER_WINDOW_SECONDS)
    # ...and the cooldown it must NOT have created would have refused this one
    second = client.post("/api/auth/otp/request", json={"email": email})
    assert second.status_code == 200, second.text


def test_override_to_dev_console_skips_the_provider_entirely(client, supabase,
                                                             transport, monkeypatch):
    calls = transport([])
    monkeypatch.setattr(config, "OTP_PROVIDER_PREFERENCE", "dev_console")
    email = _email()
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery"] == "dev_console"
    assert body["length"] == 6 and len(body["dev_code"]) == 6
    assert calls == []                      # no mail quota spent, no quota error
    assert client.get("/api/auth/provider").json()["otp_provider"] == "dev_console"

    login = client.post("/api/auth/otp/verify",
                        json={"email": email, "code": body["dev_code"]})
    assert login.status_code == 200, login.text
    assert client.get("/api/auth/me").json()["email"] == email
    client.cookies.clear()


def test_request_surfaces_provider_outage_instead_of_faking_success(client, supabase,
                                                                   transport):
    transport([httpx.ConnectError("dns")])
    r = client.post("/api/auth/otp/request", json={"email": _email()})
    assert r.status_code == 503
    assert "Supabase" in r.json()["detail"]


def test_request_rejects_bad_email_at_the_provider(client, supabase, transport):
    transport([httpx.Response(400, json={"error_code": "validation_failed",
                                         "msg": "Unable to validate email address"})])
    r = client.post("/api/auth/otp/request", json={"email": _email()})
    assert r.status_code == 400


def test_request_cooldown_survives_the_provider_switch(client, supabase, transport):
    transport([httpx.Response(200, json={}), httpx.Response(200, json={})])
    email = _email()
    assert client.post("/api/auth/otp/request", json={"email": email}).status_code == 200
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_verify_creates_a_local_session_without_storing_a_code(client, supabase,
                                                               transport):
    client.cookies.clear()
    email = _email()
    transport([httpx.Response(200, json={"user": {"id": "sb-9", "email": email}})])
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": "123456", "display_name": "Supabase User"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
    assert KEY not in r.text

    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["email"] == email

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        assert user.password_hash == "otp-only"      # no password can log in
        login = (db.query(AuditEvent)
                 .filter(AuditEvent.user_id == user.id,
                         AuditEvent.action == "auth.login")
                 .order_by(AuditEvent.created_at.desc()).first())
        assert login.detail["method"] == "supabase_otp"
        assert login.detail["supabase_user_id"] == "sb-9"
        # we never persist a passcode for the external provider
        from app.models import EmailOtp
        rows = db.query(EmailOtp).filter(EmailOtp.email == email).all()
        assert all(row.code_hash != "123456" for row in rows)
    finally:
        db.close()
    client.cookies.clear()


def test_verify_rejects_a_wrong_token_and_creates_nothing(client, supabase, transport):
    client.cookies.clear()
    email = _email()
    transport([httpx.Response(403, json={"error_code": "otp_expired",
                                         "msg": "Token has expired or is invalid"})])
    r = client.post("/api/auth/otp/verify", json={"email": email, "code": "000000"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    db = SessionLocal()
    try:
        assert db.query(User).filter(User.email == email).count() == 0
    finally:
        db.close()


def test_verify_maps_provider_outage_to_503(client, supabase, transport):
    transport([httpx.Response(502, json={})])
    r = client.post("/api/auth/otp/verify", json={"email": _email(), "code": "123456"})
    assert r.status_code == 503
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------- #
# sign-in links (what Supabase actually emails by default)
# --------------------------------------------------------------------------- #


def test_verify_token_hash_uses_the_link_contract(supabase, transport):
    calls = transport([httpx.Response(200, json={"user": {"id": "sb-2",
                                                          "email": "Link@Example.com"}})])
    identity = supabase_auth.verify_token_hash("abc123hash", "magiclink")
    assert identity.user_id == "sb-2"
    assert identity.email == "link@example.com"
    assert calls[0]["url"] == f"{URL}/auth/v1/verify"
    assert calls[0]["json"] == {"token_hash": "abc123hash", "type": "magiclink"}


def test_identify_resolves_the_access_token(supabase, transport):
    calls = transport([httpx.Response(200, json={"id": "sb-3", "email": "User@Example.com"})])
    identity = supabase_auth.identify("jwt-from-fragment")
    assert identity.user_id == "sb-3"
    assert identity.email == "user@example.com"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == f"{URL}/auth/v1/user"
    assert calls[0]["headers"]["Authorization"] == "Bearer jwt-from-fragment"


def test_identify_rejects_a_dead_access_token(supabase, transport):
    transport([httpx.Response(403, json={"error_code": "bad_jwt", "msg": "invalid JWT"})])
    with pytest.raises(supabase_auth.SupabaseInvalidCode) as exc:
        supabase_auth.identify("expired")
    assert "link" in str(exc.value).lower()


def test_redeem_access_token_signs_the_user_in(client, supabase, transport):
    client.cookies.clear()
    email = _email()
    transport([httpx.Response(200, json={"id": "sb-11", "email": email})])
    r = client.post("/api/auth/supabase/redeem", json={"access_token": "jwt-abc",
                                                         "type": "magiclink"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == email
    assert KEY not in r.text
    assert client.get("/api/auth/me").status_code == 200

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).one()
        assert user.password_hash == "otp-only"
        login = (db.query(AuditEvent)
                 .filter(AuditEvent.user_id == user.id, AuditEvent.action == "auth.login")
                 .order_by(AuditEvent.created_at.desc()).first())
        assert login.detail["method"] == "supabase_link"
        assert login.detail["supabase_user_id"] == "sb-11"
    finally:
        db.close()
    client.cookies.clear()


def test_redeem_token_hash_works_once(client, supabase, transport):
    client.cookies.clear()
    email = _email()
    transport([
        httpx.Response(200, json={"user": {"id": "sb-12", "email": email}}),
        httpx.Response(403, json={"error_code": "otp_expired",
                                  "msg": "Token has expired or is invalid"}),
    ])
    r = client.post("/api/auth/supabase/redeem", json={"token_hash": "hash-1"})
    assert r.status_code == 200, r.text
    client.cookies.clear()

    r = client.post("/api/auth/supabase/redeem", json={"token_hash": "hash-1"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_redeem_rejects_a_dead_link_without_creating_an_account(client, supabase, transport):
    client.cookies.clear()
    transport([httpx.Response(403, json={"error_code": "otp_expired",
                                         "msg": "Token has expired or is invalid"})])
    r = client.post("/api/auth/supabase/redeem", json={"access_token": "stale-jwt"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401

    db = SessionLocal()
    try:
        assert (db.query(AuditEvent).filter(AuditEvent.action == "auth.link_failed").count()
                >= 1)
    finally:
        db.close()


def test_redeem_requires_exactly_one_credential(client, supabase, transport):
    calls = transport([])
    assert client.post("/api/auth/supabase/redeem", json={}).status_code == 422
    assert client.post("/api/auth/supabase/redeem",
                       json={"access_token": "a", "token_hash": "b"}).status_code == 422
    assert client.post("/api/auth/supabase/redeem",
                       json={"token_hash": "h", "type": "not-a-type"}).status_code == 422
    # nothing reached the provider
    assert calls == []


def test_redeem_is_refused_when_supabase_is_not_the_provider(client, monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_URL", "", raising=False)
    monkeypatch.setattr(config, "SUPABASE_KEY", "", raising=False)
    r = client.post("/api/auth/supabase/redeem", json={"token_hash": "hash-1"})
    assert r.status_code == 409
