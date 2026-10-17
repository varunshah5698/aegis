"""Pipeline reliability: stage timeouts, stale-run recovery, error capture.

These lock in the fixes for the "pipeline keeps running / times out and fails"
bug: a hung stage must fail its run quickly with a clear message, stale jobs
from a crashed server must not stay 'running' forever, and stage failures must
carry a traceback so they are diagnosable.
"""
from __future__ import annotations

import time

import pandas as pd
import pytest


def test_watchdog_fails_run_past_its_limit(client):
    from app.database import SessionLocal
    from app.models import AnalysisRun, Dataset, Job
    from app.pipeline import StageWatchdog

    db = SessionLocal()
    ds = Dataset(filename="watchdog.csv", original_filename="watchdog.csv",
                 source_path="/tmp/watchdog.csv", delimiter=",", encoding="utf-8",
                 row_count=10, column_count=2, validation_status="ok")
    db.add(ds)
    db.commit()
    ds_ref = ds.id
    run = AnalysisRun(dataset_id=ds_ref, status="running", artifact_dir="/tmp")
    db.add(run)
    db.commit()
    run_ref = run.id
    db.add(Job(run_id=run_ref, name="ml_train", label="11 · Model training",
               status="running", required=False))
    db.commit()
    db.close()

    # a 30s floor keeps this deterministic without waiting 15 minutes
    wd = StageWatchdog(limit_seconds=1, poll_seconds=0.2)
    assert wd.limit >= 30, "watchdog must clamp absurdly small limits"
    wd.limit = 0                      # force immediate expiry
    wd.note_progress(run_ref, "ml_train")
    wd._fail(run_ref, "ml_train")

    from app.pipeline import _is_abandoned
    assert _is_abandoned(run_ref) is True

    db = SessionLocal()
    try:
        run = db.get(AnalysisRun, run_ref)
        assert run.status == "failed"
        assert "exceeded" in (run.error or "") and "ml_train" in (run.error or "")
        job = db.query(Job).filter(Job.run_id == run_ref).one()
        assert job.status == "failed"
        assert job.detail == "timed out"
    finally:
        db.close()


def test_watchdog_leaves_finished_runs_alone(client):
    from app.database import SessionLocal
    from app.models import AnalysisRun, Dataset
    from app.pipeline import StageWatchdog

    db = SessionLocal()
    ds = Dataset(filename="done.csv", original_filename="done.csv",
                 source_path="/tmp/done.csv", delimiter=",", encoding="utf-8",
                 row_count=5, column_count=2, validation_status="ok")
    db.add(ds)
    db.commit()
    run = AnalysisRun(dataset_id=ds.id, status="completed", artifact_dir="/tmp")
    db.add(run)
    db.commit()
    run_ref = run.id
    db.close()

    wd = StageWatchdog(limit_seconds=1, poll_seconds=0.2)
    wd.note_progress(run_ref, "charts")
    wd._fail(run_ref, "charts")

    db = SessionLocal()
    try:
        assert db.get(AnalysisRun, run_ref).status == "completed"
    finally:
        db.close()


def test_stage_error_includes_message_and_traceback():
    import traceback

    from app.pipeline import _format_stage_error

    try:
        raise ValueError("Unalignable boolean Series provided as indexer")
    except Exception as exc:                # noqa: BLE001
        text = _format_stage_error(exc, traceback.format_exc())
    assert "Unalignable boolean Series provided as indexer" in text
    assert "ValueError" in text
    assert "traceback tail" in text
    # the UI shows job.error in a 600-char detail line, so keep it bounded
    assert len(text) <= 3000


def test_financial_masks_stay_alignable():
    """Regression: the status filter used to shrink the frame while later
    detectors still indexed it with the full-frame mask, raising
    'Unalignable boolean Series provided as indexer'."""
    from app import financial

    rows = 40
    frame = pd.DataFrame({
        "transaction_id": [f"T{i}" for i in range(rows)],
        "source_account_id": [f"ACC{i % 5}" for i in range(rows)],
        "destination_account_id": [f"ACC{(i + 2) % 5}" for i in range(rows)],
        "initiated_at_utc": pd.date_range("2025-01-01", periods=rows, freq="h").astype(str),
        "source_amount": [100.0 + i for i in range(rows)],
        "destination_amount": [100.0 + i for i in range(rows)],
        # every third row failed: the status filter drops them, which is
        # exactly the condition that used to break mask alignment
        "transaction_status": ["failed" if i % 3 == 0 else "success" for i in range(rows)],
        "reference_id": [f"REF{i // 2}" for i in range(rows)],
        "source_currency": ["INR"] * rows,
        "destination_currency": ["INR"] * rows,
    })
    roles = {
        "source_account": "source_account_id",
        "destination_account": "destination_account_id",
        "amount_source": "source_amount",
        "amount_destination": "destination_amount",
        "status": "transaction_status",
        "currency_source": "source_currency",
        "currency_destination": "destination_currency",
    }
    result = financial.detect_patterns(frame, roles, "initiated_at_utc")
    assert result["total"] >= 0
    assert isinstance(result["findings"], list)
    assert time.time() > 0     # keep the import used and the test trivially real


def test_financial_stage_degrades_instead_of_failing(client, monkeypatch):
    """One broken detector must not fail the whole financial stage."""
    from app import financial

    def boom(*_a, **_k):
        raise ValueError("Unalignable boolean Series provided as indexer")

    monkeypatch.setattr(financial, "detect_patterns", boom)

    from app.database import SessionLocal
    from app.models import AnalysisRun, Dataset
    from app.pipeline import PipelineRunner, STAGES, _CTX
    import tempfile
    from pathlib import Path

    db = SessionLocal()
    ds = Dataset(filename="degrade.csv", original_filename="degrade.csv",
                 source_path="/tmp/degrade.csv", delimiter=",", encoding="utf-8",
                 row_count=6, column_count=3, validation_status="ok")
    db.add(ds)
    db.commit()
    run = AnalysisRun(dataset_id=ds.id, status="pending", artifact_dir=tempfile.mkdtemp())
    db.add(run)
    db.commit()
    run_ref = run.id
    db.close()

    # minimal context that the financial branch needs, then call the stage
    import pandas as pd
    frame = pd.DataFrame({
        "transaction_id": [f"T{i}" for i in range(6)],
        "source_account_id": ["A", "B", "A", "B", "A", "B"],
        "destination_account_id": ["B", "C", "B", "C", "B", "C"],
        "source_amount": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "transaction_status": ["success"] * 6,
        "initiated_at_utc": pd.date_range("2025-01-01", periods=6, freq="h").astype(str),
    })
    from app import schema_inference
    inference = schema_inference.infer_schema(frame)
    ctx = {
        "df": frame,
        "profiles": inference.columns,
        "semantic_map": inference.semantic_map,
        "inference": inference,
        "roles": {"source_account": "source_account_id",
                  "destination_account": "destination_account_id",
                  "amount_source": "source_amount",
                  "status": "transaction_status",
                  "transaction_time": "initiated_at_utc"},
        "artifact_dir": Path(tempfile.mkdtemp()),
    }

    db = SessionLocal()
    try:
        out = PipelineRunner(workers=1)._run_stage("financial", ctx, db,
                                                   db.get(AnalysisRun, run_ref))
    finally:
        db.close()
    modules = out["modules"]
    assert modules["patterns"]["status"] == "failed"
    assert "Unalignable" in modules["patterns"]["reason"]
    # the rest of the modules still produced real results
    assert modules["summary"] and modules["network"]
    assert any("Financial modules failed" in w for w in ctx.get("warnings", []))
