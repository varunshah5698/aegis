"""End-to-end API tests: auth → upload → full 16-stage analysis run → artifacts."""
from __future__ import annotations

import time
import uuid

from conftest import SAMPLE_CSV


def _email() -> str:
    return f"qa-{uuid.uuid4().hex[:12]}@test.dev"


def test_health_and_brand(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "limits" in body and "providers" in body

    r = client.get("/api/brand")
    assert r.status_code == 200
    assert r.json()["name"]


def test_register_login_and_duplicate(client):
    email, password = _email(), "Str0ngPass!9"

    r = client.post("/api/auth/register",
                    json={"email": email, "password": password,
                          "display_name": "QA Bot"})
    assert r.status_code == 201, r.text
    assert r.json()["email"] == email

    r = client.post("/api/auth/register",
                    json={"email": email, "password": password})
    assert r.status_code == 409

    r = client.post("/api/auth/login", json={"email": email, "password": "wrong-pass-1"})
    assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200

    r = client.post("/api/auth/register",
                    json={"email": _email(), "password": "short"})
    assert r.status_code == 422


def test_upload_rejects_invalid_files(client):
    r = client.post("/api/datasets/upload",
                    files={"file": ("book.xlsx", b"PK\x03\x04junk", "text/csv")})
    assert r.status_code == 422

    r = client.post("/api/datasets/upload",
                    files={"file": ("empty.csv", b"", "text/csv")})
    assert r.status_code == 422


def test_dataset_upload_preview_and_delete(client, sample_csv):
    client.post("/api/auth/register",
                json={"email": _email(), "password": "Str0ngPass!9"})

    r = client.post("/api/datasets/upload",
                    files={"file": ("sample.csv", sample_csv, "text/csv")},
                    data={"is_demo": "true"})
    assert r.status_code == 200, r.text
    body = r.json()
    dsid = body["dataset_id"]
    assert body["row_count"] == 240
    assert body["column_count"] == 11
    assert body["status"] in ("ok", "warning")

    r = client.get(f"/api/datasets/{dsid}/preview")
    assert r.status_code == 200 and r.json()

    r = client.get(f"/api/datasets/{dsid}/schema")
    assert r.status_code == 200 and r.json()

    r = client.get(f"/api/datasets/{dsid}/quality")
    assert r.status_code == 200 and r.json()

    r = client.delete(f"/api/datasets/{dsid}")
    assert r.status_code == 200

    ids = [d["id"] for d in client.get("/api/datasets").json()]
    assert dsid not in ids


def test_full_analysis_flow(client, sample_csv):
    """Upload → run all stages → verify ML honesty and artifact endpoints."""
    client.post("/api/auth/register",
                json={"email": _email(), "password": "Str0ngPass!9",
                      "display_name": "Flow Bot"})

    r = client.post("/api/datasets/upload",
                    files={"file": ("sample.csv", sample_csv, "text/csv")})
    assert r.status_code == 200, r.text
    dsid = r.json()["dataset_id"]

    r = client.post("/api/runs/start", json={"dataset_id": dsid})
    assert r.status_code == 200, r.text
    rid = r.json()["run_id"]

    # poll until terminal
    deadline = time.monotonic() + 300
    status, jobs = "", []
    while time.monotonic() < deadline:
        r = client.get(f"/api/runs/{rid}/status")
        assert r.status_code == 200, r.text
        body = r.json()
        status, jobs = body["status"], body["jobs"]
        if status in ("completed", "partial", "failed", "cancelled"):
            break
        time.sleep(1.0)

    failed = {j["name"]: (j.get("error") or j.get("detail"))
              for j in jobs if j["status"] not in ("completed", "skipped")}
    assert status == "completed", f"run={status} failures={failed}"
    # every required stage must have completed
    required = {j["name"] for j in jobs if j.get("required")}
    done = {j["name"] for j in jobs if j["status"] == "completed"}
    assert required <= done, f"required stages not completed: {required - done}"

    # ---- ML honesty ------------------------------------------------------
    sup = client.get(f"/api/runs/{rid}/stage/ml_train").json()
    sup = sup.get("supervised", sup)
    assert sup["status"] == "completed", sup.get("reason")
    assert sup["split_strategy"], "split strategy must be reported"
    metrics = sup["metrics"]
    for key in ("accuracy", "f1_weighted", "precision_weighted", "recall_weighted"):
        assert 0.0 <= metrics[key] <= 1.0, key
    # the hold-out fold must contain both classes (a single-class fold makes
    # ROC-AUC undefined and 1.0 metrics meaningless)
    assert len(sup["per_class"]) == 2, sup["per_class"]
    assert sum(c["support"] for c in sup["per_class"]) == sup["test_size"]
    assert sup["baselines"]["majority_class_accuracy"] < 1.0
    # the leakage screen must have dropped the perfectly-predictive columns:
    # in the sample, transaction_category ("investment" ⇒ label 1 only) is a
    # perfect proxy and must be excluded from the feature matrix
    assert any("Leakage detection excluded" in l for l in sup["limitations"])
    assert "transaction_category" in sup["excluded_features"]
    # …while amount merely overlaps the classes and must be kept
    assert "source_amount" in sup["features_used"]

    # ---- artifact endpoints ---------------------------------------------
    charts = client.get(f"/api/runs/{rid}/charts").json()
    assert charts["chart_count"] >= 1
    assert len(charts["charts"]) == charts["chart_count"]

    manifest = client.get(f"/api/runs/{rid}/manifest")
    assert manifest.status_code == 200
    m = manifest.json()
    assert "roles" in m and "charts" in m

    findings = client.get(f"/api/runs/{rid}/findings")
    assert findings.status_code == 200 and findings.json()

    records = client.get(f"/api/runs/{rid}/records", params={"limit": 5})
    assert records.status_code == 200 and records.json()

    dq = client.get(f"/api/runs/{rid}/data-quality")
    assert dq.status_code == 200 and dq.json()

    hist = client.get(f"/api/runs/{rid}/history")
    assert hist.status_code == 200

    net = client.get(f"/api/runs/{rid}/network")
    assert net.status_code == 200, net.text
    assert net.json()["node_count"] >= 2

    # ---- reports ---------------------------------------------------------
    r = client.post(f"/api/runs/{rid}/reports")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["files"], "report stage produced no files"

    r = client.get(f"/api/runs/{rid}/reports")
    assert r.status_code == 200
    files = r.json()["files"]
    assert files

    target = next((f["name"] for f in files if str(f["name"]).endswith(".md")),
                  files[0]["name"])
    dl = client.get(f"/api/runs/{rid}/reports/download", params={"filename": target})
    assert dl.status_code == 200
    assert len(dl.content) > 0
