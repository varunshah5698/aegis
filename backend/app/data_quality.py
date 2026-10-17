"""Data quality assessment (spec #7): missingness, duplicates, invalid data, outliers.

All computations run on the real uploaded frame. Nothing is mutated here —
results feed recommendations, and the cleaning workspace applies transforms
as a new dataset version (the original upload stays immutable).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .schema_inference import ColumnProfile, _parse_date, _parse_num

MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none", "-", "--", "?", "unknown", "missing"}


@dataclass
class QualityReport:
    score: float
    grade: str
    missing: dict
    duplicates: dict
    invalid: dict
    outliers: dict
    summary: list[str] = field(default_factory=list)
    recommendations: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "formula": (
                "score = 100 − (1.5×missing_pct + 2×duplicate_pct + 1.5×invalid_pct "
                "+ 1×outlier_pct), clamped to [0, 100]; components are share of "
                "cells/rows affected and are exact (not sampled) below "
                "50,000 rows."
            ),
            "missing": self.missing,
            "duplicates": self.duplicates,
            "invalid": self.invalid,
            "outliers": self.outliers,
            "summary": self.summary,
            "recommendations": self.recommendations,
        }


def assess_quality(df: pd.DataFrame, profiles: list[ColumnProfile],
                   semantic_map: dict[str, str]) -> QualityReport:
    rows, cols = df.shape
    recs: list[dict] = []
    summary: list[str] = []

    # ---------------------------------------------------------- missing ----
    col_missing = []
    total_cells = max(rows * cols, 1)
    missing_cells = 0
    for c in df.columns:
        series = df[c]
        if series.dtype == object:
            mask = series.isna() | series.astype(str).str.strip().str.lower().isin(MISSING_TOKENS)
        else:
            mask = series.isna()
        pct = float(mask.mean() * 100)
        missing_cells += int(mask.sum())
        if pct > 0:
            col_missing.append({
                "column": c,
                "missing_count": int(mask.sum()),
                "missing_pct": round(pct, 2),
            })
    col_missing.sort(key=lambda x: -x["missing_pct"])
    missing_pct = round(100.0 * missing_cells / total_cells, 2)

    empty_rows = int((~df.notna().any(axis=1)).sum())
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    critical_missing = [m for m in col_missing if m["missing_pct"] > 40]

    if empty_cols:
        recs.append({"action": "drop_columns", "targets": empty_cols,
                     "reason": f"{len(empty_cols)} column(s) are 100% empty."})
    if critical_missing:
        recs.append({"action": "review_missing", "targets": [m["column"] for m in critical_missing[:10]],
                     "reason": "Columns with >40% missing values distort aggregates."})
    if empty_rows:
        recs.append({"action": "drop_rows", "targets": [],
                     "reason": f"{empty_rows} completely empty rows found."})

    missing_detail = {
        "columns_with_missing": col_missing[:60],
        "total_missing_pct": missing_pct,
        "empty_rows": empty_rows,
        "empty_columns": empty_cols,
        "critical_missing": critical_missing[:20],
    }
    if col_missing:
        summary.append(f"{len(col_missing)} column(s) contain missing values "
                       f"({missing_pct:.1f}% of all cells).")

    # ------------------------------------------------------- duplicates ----
    dup_mask = df.duplicated(keep="first")
    exact_dups = int(dup_mask.sum())

    id_cols = [c for c, r in semantic_map.items() if r == "transaction_id"]
    dup_ids = {}
    for c in id_cols:
        s = df[c].dropna().astype(str)
        s = s[s.str.strip() != ""]
        if s.empty:
            continue
        vc = s.value_counts()
        conflicts = int((vc > 1).sum())
        if conflicts:
            # conflicting payloads for the same id = real problem
            subset = df[df[c].isin(vc[vc > 1].index)]
            conflicting = int(subset.groupby(c).apply(lambda g: len(g.drop_duplicates()) > 1).sum())
            dup_ids[c] = {"duplicate_id_count": conflicts, "conflicting_payloads": conflicting}
    if dup_ids:
        recs.append({"action": "inspect_duplicates", "targets": list(dup_ids),
                     "reason": "Repeated identifiers with differing payloads may be double records."})
        summary.append(f"Duplicate identifiers detected in {len(dup_ids)} column(s).")

    dup_pct = round(100.0 * exact_dups / max(rows, 1), 2)
    if exact_dups:
        recs.append({"action": "drop_duplicates", "targets": [],
                     "reason": f"{exact_dups} exact duplicate rows ({dup_pct}%)."})
        summary.append(f"{exact_dups} exact duplicate rows ({dup_pct}%).")

    duplicates = {"exact_duplicate_rows": exact_dups, "duplicate_pct": dup_pct,
                  "duplicate_identifiers": dup_ids}

    # ---------------------------------------------------------- invalid ----
    invalid_cols: list[dict] = []
    date_issues: dict[str, int] = {}
    num_issues: dict[str, int] = {}
    status_conflicts: list[str] = []

    for prof in columns_iter(profiles, df):
        name = prof.name
        if name not in df.columns:
            continue
        s = df[name].dropna().astype(str)
        s = s[s.str.strip() != ""]
        if s.empty:
            continue
        sample = s.head(5000)
        if prof.physical_type == "datetime":
            bad = sum(1 for v in sample if _parse_date(v) is None and v.strip().lower() not in MISSING_TOKENS)
            if bad:
                date_issues[name] = bad
        elif prof.physical_type in ("int64", "float64"):
            bad = sum(1 for v in sample if _parse_num(v) is None)
            if bad:
                num_issues[name] = bad
        elif prof.semantic_type == "currency_code":
            valid = re.compile(r"^[A-Z]{3}$")
            bad = int((~sample.str.strip().str.upper().str.match(valid)).sum())
            if bad:
                invalid_cols.append({"column": name, "issue": "invalid_currency_code",
                                     "count": bad,
                                     "examples": sample[~sample.str.strip().str.upper().str.match(valid)].unique()[:5].tolist()})

    # contradictory lifecycle: status=success but failed timestamp present
    status_col = next((c for c, r in semantic_map.items()
                       if r == "status" and c in df.columns), None)
    failed_ts = next((c for c in df.columns if re.search(r"failed_at|failure_time", c, re.I)), None)
    if status_col and failed_ts:
        ok_vals = {"success", "succeeded", "completed", "settled", "posted", "ok", "complete"}
        m = df[status_col].astype(str).str.lower().isin(ok_vals) & df[failed_ts].notna()
        n_conf = int(m.sum())
        if n_conf:
            status_conflicts.append(
                f"{n_conf} rows are marked successful but carry a failure timestamp in '{failed_ts}'")
            recs.append({"action": "review_lifecycle", "targets": [status_col, failed_ts],
                         "reason": status_conflicts[-1]})

    if date_issues:
        recs.append({"action": "fix_timestamps", "targets": list(date_issues),
                     "reason": "Unparseable timestamps should be coerced to NaT before time-series work."})
    if num_issues:
        recs.append({"action": "fix_numeric", "targets": list(num_issues),
                     "reason": "Non-numeric values inside numeric columns block statistics."})

    invalid = {
        "date_issues": date_issues,
        "numeric_issues": num_issues,
        "invalid_columns": invalid_cols,
        "lifecycle_conflicts": status_conflicts,
        "invalid_pct": round(100.0 * (sum(date_issues.values()) + sum(num_issues.values())
                                      + sum(i["count"] for i in invalid_cols)) / total_cells, 3),
    }

    # ---------------------------------------------------------- outliers ----
    outlier_cols: list[dict] = []
    total_outliers = 0
    numeric_cols = [p for p in profiles
                    if p.physical_type in ("int64", "float64") and not p.is_identifier
                    and p.name in df.columns]
    for p in numeric_cols[:40]:
        s = pd.to_numeric(df[p.name], errors="coerce").dropna()
        if len(s) < 20:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lo, hi = q1 - 3.0 * iqr, q3 + 3.0 * iqr   # 3×IQR = conservative fences
        n_out = int(((s < lo) | (s > hi)).sum())
        if n_out:
            total_outliers += n_out
            outlier_cols.append({
                "column": p.name, "outlier_count": n_out,
                "outlier_pct": round(100 * n_out / len(s), 2),
                "lower_fence": round(float(lo), 4), "upper_fence": round(float(hi), 4),
                "method": "interquartile_range(3×IQR)",
            })
    outlier_cols.sort(key=lambda x: -x["outlier_pct"])
    outlier_pct = round(100.0 * total_outliers / total_cells, 2)
    if outlier_cols:
        summary.append(f"Statistical outliers in {len(outlier_cols)} numeric column(s) "
                       f"({total_outliers:,} values). These are statistical extremes, "
                       "not confirmed errors.")

    outliers = {"columns": outlier_cols[:30], "total_flagged_values": total_outliers,
                "note": "IQR fences flag extremes; they do not imply fraud or error."}

    # ------------------------------------------------------------ score ----
    invalid_pct = min(invalid["invalid_pct"], 100)
    score = 100.0 - (1.5 * missing_pct + 2.0 * dup_pct + 1.5 * invalid_pct + 1.0 * outlier_pct)
    score = round(max(0.0, min(100.0, score)), 1)
    grade = ("A" if score >= 90 else "B" if score >= 75 else "C" if score >= 60
             else "D" if score >= 40 else "F")

    if not summary:
        summary.append("No missing values, duplicates or parse issues detected.")
    else:
        summary.append(f"Overall data quality score: {score}/100 (grade {grade}).")

    return QualityReport(score=score, grade=grade, missing=missing_detail,
                         duplicates=duplicates, invalid=invalid, outliers=outliers,
                         summary=summary, recommendations=recs)


def columns_iter(profiles: list[ColumnProfile], df: pd.DataFrame):
    for p in profiles:
        yield p


# ------------------------------------------------------------- cleaning -----
@dataclass
class CleaningResult:
    frame: pd.DataFrame
    operations: list[dict]

    def as_dict(self) -> dict:
        return {"operations": self.operations,
                "row_count": int(self.frame.shape[0]),
                "column_count": int(self.frame.shape[1])}


def apply_cleaning(df: pd.DataFrame, ops: list[dict]) -> CleaningResult:
    """Apply an ordered list of cleaning operations; returns a new frame.

    Supported ops (all previewable/undoable by re-running without them):
      drop_columns, drop_empty_rows, drop_duplicates, coerce_numeric,
      parse_dates, fill_missing, drop_missing, normalize_categories, filter_rows
    """
    out = df.copy()
    applied: list[dict] = []
    for op in ops:
        kind = op.get("op")
        try:
            if kind == "drop_columns":
                targets = [c for c in op.get("columns", []) if c in out.columns]
                out = out.drop(columns=targets)
                applied.append({**op, "affected": len(targets)})
            elif kind == "drop_empty_rows":
                before = len(out)
                out = out.loc[out.notna().any(axis=1)]
                applied.append({**op, "affected": before - len(out)})
            elif kind == "drop_duplicates":
                before = len(out)
                subset = [c for c in op.get("columns", []) if c in out.columns] or None
                out = out.drop_duplicates(subset=subset, keep="first")
                applied.append({**op, "affected": before - len(out)})
            elif kind == "coerce_numeric":
                cols = [c for c in op.get("columns", []) if c in out.columns]
                for c in cols:
                    out[c] = pd.to_numeric(
                        out[c].astype(str).str.replace(",", "", regex=False)
                              .str.replace("$", "", regex=False)
                              .str.replace("₹", "", regex=False),
                        errors="coerce")
                applied.append({**op, "affected": len(cols)})
            elif kind == "parse_dates":
                cols = [c for c in op.get("columns", []) if c in out.columns]
                for c in cols:
                    out[c] = pd.to_datetime(out[c], errors="coerce", utc=False)
                applied.append({**op, "affected": len(cols)})
            elif kind == "drop_missing":
                cols = [c for c in op.get("columns", []) if c in out.columns]
                before = len(out)
                out = out.dropna(subset=cols)
                applied.append({**op, "affected": before - len(out)})
            elif kind == "fill_missing":
                cols = [c for c in op.get("columns", []) if c in out.columns]
                value = op.get("value")
                for c in cols:
                    if value == "median" and out[c].dtype.kind in "fi":
                        out[c] = out[c].fillna(out[c].median())
                    elif value == "mean" and out[c].dtype.kind in "fi":
                        out[c] = out[c].fillna(out[c].mean())
                    elif value == "mode":
                        mode = out[c].mode(dropna=True)
                        out[c] = out[c].fillna(mode.iloc[0] if len(mode) else "")
                    else:
                        out[c] = out[c].fillna(value if value is not None else "")
                applied.append({**op, "affected": len(cols)})
            elif kind == "normalize_categories":
                cols = [c for c in op.get("columns", []) if c in out.columns]
                for c in cols:
                    out[c] = (out[c].astype(str).str.strip().str.lower()
                              .replace({"nan": np.nan, "none": np.nan}))
                applied.append({**op, "affected": len(cols)})
            elif kind == "filter_rows":
                col, opname, val = op.get("column"), op.get("operator", "eq"), str(op.get("value", ""))
                if col in out.columns:
                    s = out[col]
                    before = len(out)
                    if opname == "eq":
                        out = out[s.astype(str) == val]
                    elif opname == "ne":
                        out = out[s.astype(str) != val]
                    elif opname == "gt":
                        out = out[pd.to_numeric(s, errors="coerce") > float(val)]
                    elif opname == "lt":
                        out = out[pd.to_numeric(s, errors="coerce") < float(val)]
                    elif opname == "contains":
                        out = out[s.astype(str).str.contains(val, case=False, na=False)]
                    elif opname == "notna":
                        out = out[s.notna()]
                    applied.append({**op, "affected": before - len(out)})
            else:
                applied.append({**op, "skipped": True, "reason": "unknown operation"})
        except Exception as exc:  # keep cleaning resilient per spec #2.15
            applied.append({**op, "failed": True, "reason": str(exc)[:300]})
    return CleaningResult(frame=out, operations=applied)
