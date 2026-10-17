"""Shared fixtures.

The environment MUST be configured before any ``app.*`` import so that
``app.config`` picks up the temporary database and artifact directories
instead of the developer's real data store.
"""
from __future__ import annotations

import os
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="finsentry_tests_"))
os.environ["SQLITE_PATH"] = str(_TMP / "test.db")
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
# Tests must never reach a live auth provider or a real mailbox (no quota burn,
# no mail leaving the machine).
# Empty strings win over backend/.env because load_dotenv never overrides keys
# that are already present. Supabase paths are exercised explicitly, with the
# HTTP layer monkeypatched, in tests/test_supabase_auth.py.
for _key in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY",
             "VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY",
             "SMTP_HOST", "SMTP_FROM"):
    os.environ[_key] = ""
# The per-minute AI limiter is a product feature, not a test constraint: the
# suite bursts more calls than a single user would, so lift it here. The limiter
# itself is still exercised for real in test_ai.test_rate_limit_returns_429,
# which lowers the limit for its own requests.
os.environ["AI_RATE_LIMIT_PER_MINUTE"] = "10000"

import pytest  # noqa: E402


def build_sample_csv(rows: int = 240) -> bytes:
    """Deterministic miniature transactions CSV.

    * every 20th row is a labelled anomaly (large RTGS amount),
    * timestamps are spread evenly so a chronological 80/20 split keeps
      both classes in the hold-out fold,
    * amounts overlap slightly between classes so the target-leakage
      screen does not (and must not) drop the amount feature.
    """
    rng = random.Random(11)
    header = (
        "transaction_id,source_account_id,destination_account_id,"
        "initiated_at_utc,source_amount,destination_amount,"
        "transaction_status,payment_rail,transaction_category,"
        "is_cross_border,synthetic_anomaly_label"
    )
    start = datetime(2025, 1, 1, 6, 0)
    lines = [header]
    for i in range(rows):
        t = start + timedelta(hours=12 * i)
        src = f"ACC{i % 40:03d}"
        dst = f"ACC{(i * 7 + 11) % 40:03d}"          # never equals src
        if i % 20 == 19:                              # labelled anomaly
            # coarse buckets: a column of near-unique floats is (correctly)
            # treated as a row fingerprint and excluded from features. Every
            # other anomaly keeps a normal-sized amount so amount and label
            # genuinely overlap and the leakage screen (correctly) keeps it.
            if (i // 20) % 2 == 0:
                amount = round(rng.uniform(100, 8_000) / 50) * 50
            else:
                amount = round(rng.uniform(10_000, 400_000) / 10_000) * 10_000
            status, rail, label, category = "success", "RTGS", 1, "investment"
        else:
            amount = round(rng.uniform(100, 8_000) / 50) * 50
            status = "failed" if i % 13 == 0 else "success"
            rail = ("UPI", "IMPS", "NEFT", "CARD")[i % 4]
            label = 0
            category = ("person_transfer", "merchant_payment", "bill_payment")[i % 3]
        lines.append(
            f"TXN_{i:05d},{src},{dst},{t.strftime('%Y-%m-%d %H:%M:%S')},"
            f"{amount},{amount},{status},{rail},{category},"
            f"{'1' if i % 9 == 0 else '0'},{label}"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


SAMPLE_CSV = build_sample_csv()


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient with the app lifespan (DB init + pipeline runner)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_csv() -> bytes:
    return SAMPLE_CSV
