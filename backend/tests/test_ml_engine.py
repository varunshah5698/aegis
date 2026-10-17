"""Target-leakage screen and leakage-resistant split selection."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.ml_engine import _split, detect_target_leakage


def _y(n: int, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.integers(0, 2, n), name="label")


def test_flags_pure_categorical_proxy():
    rng = np.random.default_rng(1)
    y = pd.Series(rng.integers(0, 2, 400), name="label")
    X = pd.DataFrame({
        "scenario": np.where(y == 1, "fan_out", "normal"),
        "noise": rng.normal(size=400),
    })
    leaks = detect_target_leakage(X, y)
    assert "scenario" in leaks
    assert "noise" not in leaks


def test_flags_numeric_feature_with_no_class_overlap():
    rng = np.random.default_rng(2)
    y = pd.Series(rng.integers(0, 2, 400), name="label")
    X = pd.DataFrame({
        "perfect": y * 1000 + rng.uniform(0, 9, 400),   # pos ≥1000, neg <10
        "overlapping": rng.uniform(0, 100, 400),
    })
    leaks = detect_target_leakage(X, y)
    assert "perfect" in leaks
    assert "overlapping" not in leaks


def test_good_but_not_perfect_predictor_is_kept():
    rng = np.random.default_rng(3)
    y = pd.Series(rng.integers(0, 2, 400), name="label")
    X = pd.DataFrame({"signal": y * 3 + rng.normal(0, 2, 400)})
    leaks = detect_target_leakage(X, y)
    assert leaks == []


def test_short_series_is_skipped():
    y = pd.Series([0, 1] * 50, name="label")
    X = pd.DataFrame({"a": y.astype(float)})
    assert detect_target_leakage(X, y) == []


def test_time_split_uses_chronological_cut():
    y = pd.Series([0, 1] * 50)
    strategy: list[str] = []
    tr, te = _split(y, 100, "initiated_at_utc", None, strategy)
    assert list(tr) == list(range(80))
    assert list(te) == list(range(80, 100))
    assert strategy and "time-based" in strategy[0]


def test_group_split_hold_out_contains_both_classes():
    # 40 pure groups: any acceptable fold must contain both classes, and the
    # fallback (stratified) must as well — a single-class fold makes metrics
    # meaningless.
    rng = np.random.default_rng(4)
    y = pd.Series(rng.integers(0, 2, 400))
    groups = pd.Series([f"g{i % 40}" for i in range(400)], name="account")
    strategy: list[str] = []
    tr, te = _split(y, 400, None, groups, strategy)
    assert y.iloc[te].nunique() == 2
    assert y.iloc[tr].nunique() == 2
    assert strategy


def test_stratified_fallback_when_no_groups_or_time():
    y = pd.Series([0] * 300 + [1] * 100)
    strategy: list[str] = []
    tr, te = _split(y, 400, None, None, strategy)
    assert y.iloc[te].nunique() == 2
    assert "stratified" in strategy[0] or "random" in strategy[0]
