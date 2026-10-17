"""pandas version compatibility helpers (M→ME alias migration)."""
from __future__ import annotations

import pandas as pd

from app.freq import month_rule, year_rule


def test_month_rule_returns_valid_offset():
    alias = month_rule()
    pd.tseries.frequencies.to_offset(alias)  # must not raise


def test_year_rule_returns_valid_offset():
    alias = year_rule()
    pd.tseries.frequencies.to_offset(alias)  # must not raise


def test_month_rule_resample_works():
    idx = pd.date_range("2024-01-15", periods=100, freq="D")
    df = pd.DataFrame({"v": range(100)}, index=idx)
    out = df.resample(month_rule()).sum()
    assert len(out) >= 3
    assert int(out["v"].sum()) == sum(range(100))
