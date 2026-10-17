"""Synthetic dataset generator invariants (spec #6)."""
from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_dataset.py"
_spec = importlib.util.spec_from_file_location("generate_dataset", _SCRIPT)
assert _spec and _spec.loader
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)


def _rows():
    return gen.make_generator(seed=42, rows=300)


def test_generates_requested_scale_with_both_classes():
    rows = _rows()
    assert len(rows) >= 300
    labels = {r["synthetic_anomaly_label"] for r in rows}
    assert labels == {"0", "1"}


def test_anomaly_rate_in_sane_band_at_scale():
    # scenario counts have per-kind floors, so the few-percent band only
    # holds once the dataset is large enough for the proportional terms
    rows = gen.make_generator(seed=42, rows=12_000)
    rate = sum(1 for r in rows if r["synthetic_anomaly_label"] == "1") / len(rows)
    assert 0.02 < rate < 0.10, rate


def test_rows_only_contain_declared_columns():
    allowed = set(gen.FIELDNAMES)
    for r in _rows()[:200]:
        assert set(r) <= allowed


def test_timestamps_within_generator_bounds():
    for r in _rows():
        raw = r["initiated_at_utc"]
        try:
            t = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue                      # intentional data-quality defect
        assert gen.START <= t <= gen.END


def test_seconds_since_previous_never_negative():
    # regression: prior_stats once computed gaps against a future event
    for r in _rows():
        v = r["seconds_since_previous_source"]
        if v == "" or v is None:
            continue
        assert int(v) >= 0


def test_anomalies_never_transfer_to_themselves():
    for r in _rows():
        if r["synthetic_anomaly_label"] == "1":
            assert r["source_account_id"] != r["destination_account_id"]


def test_scenario_accounts_are_not_a_handful_of_fixed_ids():
    # regression: pick_active once shadowed the loop variable so every
    # scenario instance reused the same accounts (trivially separable)
    rows = _rows()
    anom_srcs = {r["source_account_id"] for r in rows
                 if r["synthetic_anomaly_label"] == "1"}
    # hundreds of anomaly instances at rows=300 → many distinct sources
    assert len(anom_srcs) >= 40


def test_scenario_labelling_is_consistent():
    for r in _rows():
        cat = r["synthetic_scenario_category"]
        if r["synthetic_anomaly_label"] == "1":
            assert cat != "normal"
            assert r["synthetic_scenario_id"]
        else:
            assert cat == "normal"
            assert not r["synthetic_scenario_id"]
