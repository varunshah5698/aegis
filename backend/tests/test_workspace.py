"""Workspace tests: overview, bookings, comments, checkout, admin."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from conftest import SAMPLE_CSV


def _email() -> str:
    return f"ws-{uuid.uuid4().hex[:12]}@test.dev"


def _register(client, email: str | None = None):
    email = email or _email()
    r = client.post("/api/auth/register",
                    json={"email": email, "password": "Str0ngPass!9"})
    assert r.status_code == 201, r.text
    return email


def _upload(client):
    r = client.post("/api/datasets/upload",
                    files={"file": ("sample.csv", SAMPLE_CSV, "text/csv")},
                    data={"is_demo": "true"})
    assert r.status_code == 200, r.text
    return r.json()["dataset_id"]


def test_overview_requires_auth(client):
    client.cookies.clear()
    r = client.get("/api/workspaces/overview")
    assert r.status_code == 401


def test_bookings_flow(client):
    _register(client)
    r = client.get("/api/bookings")
    assert r.status_code == 200 and r.json() == []

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post("/api/bookings", json={"topic": "Past review",
                                           "scheduled_at": past})
    assert r.status_code == 422

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    r = client.post("/api/bookings", json={"topic": "Q3 review",
                                           "detail": "Walk through flagged flows",
                                           "scheduled_at": future})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    assert r.json()["status"] == "upcoming"

    r = client.get("/api/bookings")
    assert len(r.json()) == 1

    r = client.post(f"/api/bookings/{bid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"

    r = client.post(f"/api/bookings/{bid}/cancel")
    assert r.status_code == 409


def test_comments_flow(client):
    _register(client)
    dsid = _upload(client)

    r = client.get(f"/api/datasets/{dsid}/comments")
    assert r.status_code == 200 and r.json() == []

    r = client.post(f"/api/datasets/{dsid}/comments", json={"text": "  "})
    assert r.status_code == 422

    r = client.post(f"/api/datasets/{dsid}/comments",
                    json={"text": "This spike needs a second look."})
    assert r.status_code == 201, r.text
    assert r.json()["mine"] is True

    r = client.get(f"/api/datasets/{dsid}/comments")
    assert len(r.json()) == 1


def test_checkout_flow(client):
    _register(client)
    r = client.get("/api/plans")
    assert r.status_code == 200
    assert {p["key"] for p in r.json()} >= {"starter", "professional"}

    r = client.post("/api/checkout", json={"plan": "nope"})
    assert r.status_code == 422

    r = client.post("/api/checkout", json={"plan": "professional"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "paid" and body["amount_cents"] == 2900

    r = client.get("/api/orders")
    assert len(r.json()) == 1

    r = client.get("/api/workspaces/overview")
    assert r.status_code == 200
    assert r.json()["recent_orders"][0]["plan"] == "professional"


def test_admin_forbidden_without_config(client):
    _register(client)
    for path in ("/api/admin/users", "/api/admin/datasets",
                 "/api/admin/runs", "/api/admin/audit"):
        r = client.get(path)
        assert r.status_code == 403, path
