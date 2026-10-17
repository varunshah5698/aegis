"""Pandas frequency-alias compatibility.

pandas 2.2 deprecated and pandas 3.0 removed the old ``M``/``Y``/``W`` month
and year aliases in favour of ``ME``/``YE``/``W-SUN``. Resampling code calls
``month_rule()`` so it works on either major version.
"""
from __future__ import annotations

import pandas as pd


def month_rule() -> str:
    """Month-end resample rule valid for the installed pandas version."""
    for alias in ("ME", "M"):
        try:
            pd.tseries.frequencies.to_offset(alias)
            return alias
        except ValueError:
            continue
    return "ME"


def year_rule() -> str:
    for alias in ("YE", "Y"):
        try:
            pd.tseries.frequencies.to_offset(alias)
            return alias
        except ValueError:
            continue
    return "YE"
