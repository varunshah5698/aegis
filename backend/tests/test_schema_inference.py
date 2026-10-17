"""Column profiling and dataset schema inference."""
from __future__ import annotations

import json

import pandas as pd

from app.schema_inference import infer_schema, profile_column


def test_profile_numeric_strings():
    p = profile_column("source_amount", pd.Series(["100.5", "2000", "3", ""]))
    assert p.physical_type in ("float64", "int64")
    assert p.null_pct > 0


def test_profile_integer_column():
    p = profile_column("retry_count", pd.Series(["0", "1", "2", "3"]))
    assert p.physical_type == "int64"


def test_profile_datetime_strings():
    p = profile_column("initiated_at_utc",
                        pd.Series(["2025-01-01 10:00:00", "2025-03-05 11:30:00"]))
    assert p.physical_type == "datetime"
    assert p.semantic_type == "datetime"


def test_profile_empty_column():
    p = profile_column("empty_col", pd.Series(["", "", ""]))
    assert p.physical_type == "empty"


def test_label_column_detected_as_target():
    p = profile_column("synthetic_anomaly_label", pd.Series(["0", "1", "1", "0"] * 60))
    assert p.is_target is True
    assert p.semantic_type == "target"


def test_generic_words_ending_in_y_are_not_targets():
    # regression: the target regex once matched any name ending in "y"
    for name in ("company", "entry", "country", "category"):
        p = profile_column(name, pd.Series(["alpha", "beta", "gamma"] * 60))
        assert p.is_target is False, name


def _sample_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "transaction_id": [f"T{i:04d}" for i in range(60)],
        "source_account_id": [f"ACC{i % 7}" for i in range(60)],
        "destination_account_id": [f"ACC{(i + 3) % 7}" for i in range(60)],
        "initiated_at_utc": pd.date_range(
            "2025-01-01", periods=60, freq="D").strftime("%Y-%m-%d %H:%M:%S"),
        "source_amount": [100.0 + i * 13 for i in range(60)],
        "transaction_status": ["success"] * 56 + ["failed"] * 4,
        "synthetic_anomaly_label": [i % 20 == 19 for i in range(60)],
    })


def test_infer_schema_profiles_every_column():
    inf = infer_schema(_sample_frame())
    assert len(inf.columns) == 7
    assert inf.detected["row_count"] == 60
    assert inf.detected["target_columns"] == 1
    assert inf.detected["datetime_columns"] == 1
    assert inf.detected["identifier_columns"] == 1


def test_infer_schema_resolves_semantic_roles():
    inf = infer_schema(_sample_frame())
    m = inf.semantic_map
    assert m["transaction_id"] == "transaction_id"
    assert m["source_account_id"] == "source_account"
    assert m["destination_account_id"] == "destination_account"
    assert m["initiated_at_utc"] == "transaction_time"
    assert m["source_amount"] == "amount_source"
    assert m["transaction_status"] == "status"
    assert m["synthetic_anomaly_label"] == "risk_label"


def test_infer_schema_capabilities_and_serialization():
    inf = infer_schema(_sample_frame())
    assert isinstance(inf.capabilities, dict) and inf.capabilities
    payload = inf.as_dict()
    json.dumps(payload)  # must be JSON serializable end to end
    assert len(payload["columns"]) == 7
