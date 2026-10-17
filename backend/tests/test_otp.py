"""Passwordless email-OTP sign-in (Freebuff identity surface)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app import config, otp
from app.database import SessionLocal
from app.models import EmailOtp, User, utcnow


def _email() -> str:
    return f"otp-{uuid.uuid4().hex[:12]}@test.dev"


def _request(client, email: str) -> dict:
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 200, r.text
    return r.json()


def _wrong_code(right: str) -> str:
    return ("0" if right[0] != "0" else "1") + right[1:]


def test_provider_advertises_otp(client):
    body = client.get("/api/auth/provider").json()
    assert body["otp_enabled"] is True
    assert body["otp_length"] == 6
    assert body["otp_ttl_seconds"] == 600
    assert body["otp_delivery"] == "dev_console"


def test_request_returns_dev_code_without_smtp(client):
    body = _request(client, _email())
    assert body["ok"] is True
    assert body["delivery"] == "dev_console"
    assert len(body["dev_code"]) == body["length"] == 6
    assert body["dev_code"].isdigit()
    assert body["expires_in_seconds"] == 600


def test_request_rejects_bad_email(client):
    r = client.post("/api/auth/otp/request", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_verify_wrong_code_rejected(client):
    email = _email()
    body = _request(client, email)
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": _wrong_code(body["dev_code"])})
    assert r.status_code == 401


def test_verify_success_creates_session_and_user(client):
    email = _email()
    body = _request(client, email)
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": body["dev_code"],
                          "display_name": "Otp User"})
    assert r.status_code == 200, r.text
    user = r.json()
    assert user["email"] == email
    assert user["display_name"] == "Otp User"
    assert user["provider"] == "Freebuff"

    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == email

    db = SessionLocal()
    try:
        row = db.query(User).filter(User.email == email).one()
        # sentinel hash: password login must never accept it
        assert row.password_hash == "otp-only"
    finally:
        db.close()

    r = client.post("/api/auth/login", json={"email": email, "password": "anything-1"})
    assert r.status_code == 401


def test_code_is_single_use(client):
    email = _email()
    body = _request(client, email)
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": body["dev_code"]})
    assert r.status_code == 200
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": body["dev_code"]})
    assert r.status_code == 401


def test_request_cooldown(client):
    email = _email()
    _request(client, email)
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_expired_code_rejected(client):
    email = _email()
    body = _request(client, email)
    db = SessionLocal()
    try:
        row = (db.query(EmailOtp).filter(EmailOtp.email == email)
               .order_by(EmailOtp.created_at.desc()).one())
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": body["dev_code"]})
    assert r.status_code == 401
    assert "expired" in r.json()["detail"].lower()


def test_lockout_after_too_many_attempts(client):
    email = _email()
    body = _request(client, email)
    wrong = _wrong_code(body["dev_code"])
    for _ in range(5):
        r = client.post("/api/auth/otp/verify",
                        json={"email": email, "code": wrong})
        assert r.status_code == 401
    # even the right code is now dead
    r = client.post("/api/auth/otp/verify",
                    json={"email": email, "code": body["dev_code"]})
    assert r.status_code == 401
    assert "many" in r.json()["detail"].lower()


def test_unknown_email_verify_rejected(client):
    r = client.post("/api/auth/otp/verify",
                    json={"email": _email(), "code": "123456"})
    assert r.status_code == 401


# --------------------------------------------------------------------------- #
# SMTP delivery (the "real email" provider)
# --------------------------------------------------------------------------- #


def _smtp_on(monkeypatch):
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.test.dev", raising=False)
    monkeypatch.setattr(config, "SMTP_FROM", "aegis@test.dev", raising=False)
    assert config.otp_provider() == "smtp"


def test_smtp_send_failure_is_an_error_not_dev_mode(monkeypatch):
    """A configured sender that refuses must not look like keyless dev mode."""
    _smtp_on(monkeypatch)

    def refuse(*_args, **_kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(otp.smtplib, "SMTP", refuse)
    with pytest.raises(otp.OtpDeliveryFailed):
        otp.send_code_email("b@test.dev", "123456")


def test_failed_smtp_send_leaks_no_code_and_no_cooldown(client, monkeypatch):
    email = _email()
    _smtp_on(monkeypatch)

    def refuse(_email, _code):
        raise otp.OtpDeliveryFailed("sender refused the message")

    monkeypatch.setattr(otp, "send_code_email", refuse)
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 502, r.text
    assert "dev_code" not in r.text
    assert "SMTP_HOST" in r.json()["detail"]      # tells you what to fix

    # the failed attempt left neither a live code nor a cooldown behind
    monkeypatch.setattr(otp, "send_code_email", lambda _email, _code: True)
    r = client.post("/api/auth/otp/request", json={"email": email})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery"] == "email"
    assert "dev_code" not in body
    assert body["length"] == 6
