"""Exploratory data analysis and chart specification generation (spec #8).

Everything here computes from the real frame. Charts are emitted as
declarative specs (type + data + encodings) that the frontend renders with
Recharts/ECharts-style components; every chart carries a relevance score so
the dashboard only shows useful ones (spec #8.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .freq import month_rule
from .schema_inference import ColumnProfile

MAX_CHARTS = 24


# ------------------------------------------------------------- overview -----
def dataset_overview(df: pd.DataFrame, profiles: list[ColumnProfile],
                     file_bytes: int, elapsed_s: float, sampled: bool) -> dict:
    numeric = [p for p in profiles if p.physical_type in ("int64", "float64")]
    cats = [p for p in profiles if p.semantic_type == "categorical"]
    dates = [p for p in profiles if p.semantic_type == "datetime"]
    mem = int(df.memory_usage(deep=True).sum())

    time_coverage = None
    if dates:
        s = pd.to_datetime(df[dates[0].name], errors="coerce")
        if s.notna().any():
            time_coverage = {
                "column": dates[0].name,
                "start": str(s.min())[:19],
                "end": str(s.max())[:19],
                "span_days": int((s.max() - s.min()).days),
            }

    dup_pct = round(100.0 * float(df.duplicated().mean()), 2)
    missing_pct = round(100.0 * float(df.isna().mean().mean()), 2)

    # quality score matches data_quality.assess_quality formula (documented there)
    quality = round(max(0.0, 100 - (1.5 * missing_pct + 2.0 * dup_pct)), 1)

    return {
        "row_count": int(len(df)),
        "column_count": int(df.shape[1]),
        "file_size_bytes": int(file_bytes),
        "memory_bytes": int(mem),
        "numeric_columns": len(numeric),
        "categorical_columns": len(cats),
        "datetime_columns": len(dates),
        "time_coverage": time_coverage,
        "missing_pct": missing_pct,
        "duplicate_pct": dup_pct,
        "quality_score": quality,
        "processing_seconds": round(elapsed_s, 2),
        "sampled": sampled,
        "sampling_note": ("Expensive computations used a sample; counts are exact."
                          if sampled else "All computations used the full dataset."),
    }


# ---------------------------------------------------- descriptive stats -----
def descriptive_stats(df: pd.DataFrame, profiles: list[ColumnProfile],
                      max_cols: int = 60) -> dict:
    numeric_out: list[dict] = []
    categorical_out: list[dict] = []
    temporal_out: list[dict] = []

    for p in profiles[:max_cols]:
        name = p.name
        if name not in df.columns:
            continue
        s = df[name]

        if p.semantic_type == "datetime" or p.physical_type == "datetime":
            ts = pd.to_datetime(s, errors="coerce")
            if ts.notna().sum() == 0:
                continue
            diffs = ts.dropna().sort_values().diff().dropna()
            temporal_out.append({
                "column": name,
                "count": int(ts.notna().sum()),
                "min": str(ts.min())[:19],
                "max": str(ts.max())[:19],
                "span_days": int((ts.max() - ts.min()).days),
                "median_gap_seconds": round(float(diffs.dt.total_seconds().median()), 1)
                if len(diffs) else None,
                "duplicate_timestamps": int(ts.duplicated().sum()),
            })
            continue

        if p.physical_type in ("int64", "float64"):
            if p.is_identifier:
                continue
            v = pd.to_numeric(s, errors="coerce").dropna()
            if v.empty:
                continue
            q = v.quantile([0.25, 0.5, 0.75])
            numeric_out.append({
                "column": name,
                "count": int(v.count()),
                "missing": int(v.isna().sum()),
                "mean": _r(v.mean()),
                "median": _r(v.median()),
                "std": _r(v.std()),
                "variance": _r(v.var()),
                "min": _r(v.min()),
                "max": _r(v.max()),
                "sum": _r(v.sum()),
                "range": _r(v.max() - v.min()),
                "q1": _r(q.loc[0.25]),
                "q3": _r(q.loc[0.75]),
                "iqr": _r(q.loc[0.75] - q.loc[0.25]),
                "p5": _r(v.quantile(0.05)),
                "p95": _r(v.quantile(0.95)),
                "skewness": _r(v.skew()),
                "kurtosis": _r(v.kurtosis()),
                "zeros": int((v == 0).sum()),
                "positives": int((v > 0).sum()),
                "negatives": int((v < 0).sum()),
            })
        elif p.semantic_type in ("categorical", "boolean", "currency_code", "geographic"):
            s2 = s.dropna().astype(str).str.strip()
            s2 = s2[s2 != ""]
            if s2.empty:
                continue
            vc = s2.value_counts()
            top = vc.head(12)
            n = int(len(s2))
            shares = (top / n)
            entropy = float(-(shares * np.log2(shares)).sum()) if len(shares) else 0.0
            max_entropy = math.log2(len(vc)) if len(vc) > 1 else 1.0
            categorical_out.append({
                "column": name,
                "count": n,
                "unique": int(vc.size),
                "missing": int(len(s) - n),
                "top": [{"value": k, "count": int(v), "pct": round(100 * v / n, 2)}
                        for k, v in top.items()],
                "rare_categories": int((vc < max(1, n * 0.001)).sum()),
                "imbalance_ratio": round(float(vc.iloc[0] / max(vc.iloc[-1], 1)), 2)
                if len(vc) > 1 else 0.0,
                "normalized_entropy": round(entropy / max_entropy, 3) if max_entropy else 0,
            })
    return {"numeric": numeric_out, "categorical": categorical_out, "temporal": temporal_out}


def _r(x, nd: int = 5) -> float | None:
    if x is None:
        return None
    try:
        if isinstance(x, (np.floating, float)):
            if math.isnan(x) or math.isinf(x):
                return None
            return round(float(x), nd)
        if isinstance(x, (np.integer, int)):
            return int(x)
    except (TypeError, ValueError):
        return None
    return None


# ---------------------------------------------------------- relationships ---
def relationships(df: pd.DataFrame, profiles: list[ColumnProfile],
                  max_cols: int = 24) -> dict:
    """Pearson + Spearman correlations, categorical association, mutual info."""
    num_cols = [p.name for p in profiles
                if p.physical_type in ("int64", "float64") and not p.is_identifier
                and p.name in df.columns][:max_cols]
    pearson: list[list[float]] = []
    spearman: list[list[float]] = []
    labels = num_cols
    if len(num_cols) >= 2:
        sub = df[num_cols].apply(pd.to_numeric, errors="coerce")
        pearson_m = sub.corr(method="pearson", min_periods=10)
        spearman_m = sub.corr(method="spearman", min_periods=10)
        pearson = [[_r(v) for v in row] for row in pearson_m.to_numpy()]
        spearman = [[_r(v) for v in row] for row in spearman_m.to_numpy()]

    # strongest non-trivial pairs
    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            r = pearson[i][j] if pearson else None
            if r is None or math.isnan(r):
                continue
            if abs(r) >= 0.3:
                pairs.append({"a": labels[i], "b": labels[j], "pearson": round(r, 3),
                              "spearman": round(spearman[i][j], 3)
                              if spearman and spearman[i][j] is not None else None,
                              "strength": ("strong" if abs(r) >= 0.7
                                           else "moderate" if abs(r) >= 0.4 else "weak"),
                              "note": "Association only — correlation does not imply causation."})
    pairs.sort(key=lambda x: -abs(x["pearson"]))

    # categorical association (cramér's V) for top low-cardinality pairs
    cat_cols = [p.name for p in profiles
                if p.semantic_type in ("categorical", "boolean") and 1 < p.unique_count <= 20
                and p.name in df.columns][:10]
    cat_pairs = []
    for i in range(len(cat_cols)):
        for j in range(i + 1, len(cat_cols)):
            v = _cramers_v(df[cat_cols[i]], df[cat_cols[j]])
            if v is not None and v >= 0.3:
                cat_pairs.append({"a": cat_cols[i], "b": cat_cols[j],
                                  "cramers_v": round(v, 3)})
    cat_pairs.sort(key=lambda x: -x["cramers_v"])

    mutual = _mutual_information(df, profiles)

    return {
        "labels": labels,
        "pearson": pearson,
        "spearman": spearman,
        "strong_pairs": pairs[:15],
        "categorical_associations": cat_pairs[:12],
        "mutual_information": mutual[:12],
        "note": ("Pearson measures linear association; Spearman monotonic association. "
                 "Neither establishes causation."),
    }


def _cramers_v(a: pd.Series, b: pd.Series) -> float | None:
    try:
        ct = pd.crosstab(a.astype(str), b.astype(str))
        if ct.empty or ct.shape[0] < 2 or ct.shape[1] < 2:
            return None
        chi2 = _chi2(ct.to_numpy())
        n = ct.to_numpy().sum()
        if n == 0:
            return None
        phi2 = chi2 / n
        r, k = ct.shape
        phi2corr = max(0.0, phi2 - ((k - 1) * (r - 1)) / (n - 1))
        rcorr = r - ((r - 1) ** 2) / (n - 1)
        kcorr = k - ((k - 1) ** 2) / (n - 1)
        denom = min(kcorr - 1, rcorr - 1)
        if denom <= 0:
            return None
        return math.sqrt(phi2corr / denom)
    except Exception:
        return None


def _chi2(obs: np.ndarray) -> float:
    row = obs.sum(axis=1, keepdims=True)
    col = obs.sum(axis=0, keepdims=True)
    total = obs.sum()
    if total == 0:
        return 0.0
    exp = row * col / total
    with np.errstate(divide="ignore", invalid="ignore"):
        stats = np.where(exp > 0, (obs - exp) ** 2 / exp, 0.0)
    return float(stats.sum())


def _mutual_information(df: pd.DataFrame, profiles: list[ColumnProfile]) -> list[dict]:
    """Discretize numeric columns (10 bins) and compute MI with the first
    low-cardinality categorical column — a cheap, honest information signal."""
    cat = next((p.name for p in profiles
                if p.semantic_type in ("categorical", "boolean") and 2 < p.unique_count <= 15
                and p.name in df.columns), None)
    out = []
    if not cat:
        return out
    y = df[cat].astype(str)
    for p in profiles:
        if p.physical_type not in ("int64", "float64") or p.is_identifier or p.name == cat:
            continue
        x = pd.to_numeric(df[p.name], errors="coerce")
        mask = x.notna() & y.notna()
        if mask.sum() < 30:
            continue
        xb = pd.cut(x[mask], bins=10, duplicates="drop").astype(str)
        mi = _mi(xb[mask].to_numpy(), y[mask].to_numpy())
        out.append({"feature": p.name, "target": cat, "mutual_information": round(mi, 4)})
    out.sort(key=lambda d: -d["mutual_information"])
    return out


def _mi(x: np.ndarray, y: np.ndarray) -> float:
    n = len(x)
    if n == 0:
        return 0.0
    joint = pd.crosstab(pd.Series(x), pd.Series(y), normalize=True)
    px = joint.sum(axis=1).to_numpy()
    py = joint.sum(axis=0).to_numpy()
    m = joint.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        log_term = np.where(m > 0, np.log2(m / (px[:, None] * py[None, :] + 1e-12) + 1e-12), 0.0)
    return float((np.where(m > 0, m, 0) * log_term).sum())


# ------------------------------------------------------------- charts -------
@dataclass
class ChartSpec:
    id: str
    type: str
    title: str
    subtitle: str = ""
    columns: list[str] = field(default_factory=list)
    data: list = field(default_factory=list)
    x: str = ""
    y: str = ""
    series: list[str] = field(default_factory=list)
    unit: str = ""
    relevance: float = 0.5
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "title": self.title,
            "subtitle": self.subtitle, "columns": self.columns, "data": self.data,
            "x": self.x, "y": self.y, "series": self.series, "unit": self.unit,
            "relevance": round(self.relevance, 2), "note": self.note,
        }


def build_charts(df: pd.DataFrame, profiles: list[ColumnProfile],
                 semantic_map: dict[str, str], rel: dict | None = None) -> list[dict]:
    charts: list[ChartSpec] = []
    p_by_name = {p.name: p for p in profiles}
    numeric = [p for p in profiles
               if p.physical_type in ("int64", "float64") and not p.is_identifier
               and p.name in df.columns]
    cats = [p for p in profiles
            if p.semantic_type in ("categorical", "boolean", "currency_code", "geographic")
            and 1 < p.unique_count <= 60 and p.name in df.columns]
    dates = [p for p in profiles if p.semantic_type == "datetime" and p.name in df.columns]

    # 1. time series — volume over time (highest value when a date exists)
    time_col = next((c for c, r in semantic_map.items()
                     if r in ("transaction_time", "datetime") and c in df.columns), None)
    time_col = time_col or (dates[0].name if dates else None)
    amount_col = next((c for c, r in semantic_map.items()
                       if r == "amount_source" and c in df.columns), None)
    if time_col:
        ts = df.copy()
        ts[time_col] = pd.to_datetime(ts[time_col], errors="coerce")
        ts = ts.dropna(subset=[time_col]).sort_values(time_col)
        if len(ts):
            if amount_col:
                ts[amount_col] = pd.to_numeric(ts[amount_col], errors="coerce")
            # choose a bucket that keeps the series readable
            span = (ts[time_col].max() - ts[time_col].min())
            rule = (month_rule() if span.days > 400 else "D" if span.days > 3 else "h"
                    if span.total_seconds() < 6 * 3600 else "D")
            grouped = ts.set_index(time_col)
            agg = {"count": ("size",)}
            label = "Transactions over time"
            if amount_col:
                agg["value"] = (amount_col, "sum")
                label = f"{amount_col} over time"
            try:
                g = grouped.resample(rule).agg(**{"count": agg["count"],
                                                  **({"value": agg["value"]} if amount_col else {})})
                g = g.tail(400).reset_index()
                data = []
                for _, row in g.iterrows():
                    item = {"t": str(row[time_col])[:19], "count": int(row["count"])}
                    if amount_col and "value" in row:
                        item["value"] = _r(row["value"]) or 0
                    data.append(item)
                charts.append(ChartSpec(
                    id="timeseries_volume", type="area", title=label,
                    subtitle=f"Bucketed by {rule} · {len(ts):,} rows",
                    columns=[time_col] + ([amount_col] if amount_col else []),
                    data=data, x="t", y="value" if amount_col else "count",
                    unit="", relevance=0.95,
                    note="Resampled to at most 400 points for rendering."))
            except Exception:
                pass

    # 2. distributions — histograms for top numeric columns
    for p in numeric[:4]:
        s = pd.to_numeric(df[p.name], errors="coerce").dropna()
        if len(s) < 10:
            continue
        try:
            counts, edges = np.histogram(s, bins=min(30, max(8, int(np.sqrt(len(s))))))
            data = [{"bin": f"{edges[i]:,.4g}–{edges[i + 1]:,.4g}",
                     "x0": round(float(edges[i]), 4), "x1": round(float(edges[i + 1]), 4),
                     "count": int(counts[i])} for i in range(len(counts))]
            charts.append(ChartSpec(
                id=f"hist_{p.name}", type="bar", title=f"Distribution of {p.name}",
                subtitle=f"mean {_r(s.mean()):,.4g} · median {_r(s.median()):,.4g} · "
                         f"{p.distribution}",
                columns=[p.name], data=data, x="bin", y="count",
                relevance=0.85 if p.semantic_type in ("currency_amount", "float", "integer") else 0.6))
        except Exception:
            continue

    # 3. category frequency — top cats
    for p in cats[:5]:
        vc = df[p.name].astype(str).replace("", np.nan).dropna().value_counts().head(12)
        if vc.empty:
            continue
        data = [{"name": str(k)[:40], "count": int(v)} for k, v in vc.items()]
        charts.append(ChartSpec(
            id=f"freq_{p.name}", type="bar",
            title=f"Top values in {p.name}",
            subtitle=f"{p.unique_count} distinct values · showing top {len(vc)}",
            columns=[p.name], data=data, x="name", y="count",
            relevance=0.8 if p.unique_count <= 30 else 0.55))

    # 4. correlation heatmap
    if rel and rel.get("labels") and len(rel["labels"]) >= 3:
        labels = rel["labels"]
        heat = []
        for i, a in enumerate(labels):
            for j, b in enumerate(labels):
                v = rel["pearson"][i][j]
                if v is None:
                    continue
                heat.append({"a": a, "b": b, "value": round(v, 3)})
        charts.append(ChartSpec(
            id="corr_heatmap", type="heatmap", title="Correlation heatmap",
            subtitle="Pearson correlation between numeric columns",
            columns=labels, data=heat, x="a", y="b", relevance=0.9,
            note="Values near ±1 move together; this is not causation."))

    # 5. pareto — category contribution to a numeric amount
    amount_for_pareto = amount_col or (numeric[0].name if numeric else None)
    if cats and amount_for_pareto:
        pcat = cats[0].name
        tmp = df[[pcat, amount_for_pareto]].copy()
        tmp[amount_for_pareto] = pd.to_numeric(tmp[amount_for_pareto], errors="coerce")
        tmp = tmp.dropna()
        g = (tmp.groupby(tmp[pcat].astype(str))[amount_for_pareto].sum()
                .sort_values(ascending=False).head(10))
        if len(g) >= 3 and g.sum() > 0:
            cum = (g.cumsum() / g.sum() * 100).round(1)
            data = [{"name": str(k)[:40], "value": _r(v) or 0, "cum_pct": float(cum[k])}
                    for k, v in g.items()]
            charts.append(ChartSpec(
                id=f"pareto_{pcat}", type="pareto",
                title=f"Pareto: {amount_for_pareto} by {pcat}",
                subtitle="Top categories with cumulative share",
                columns=[pcat, amount_for_pareto], data=data, x="name", y="value",
                series=["cum_pct"], relevance=0.7))

    # 6. stacked status breakdown when status × category exists
    status_col = next((c for c, r in semantic_map.items() if r == "status" and c in df.columns), None)
    if status_col and cats:
        cc = next(c.name for c in cats if c.name != status_col)
        ct = pd.crosstab(df[cc].astype(str).replace("", "unknown").head(200_000),
                         df[status_col].astype(str).replace("", "unknown").head(200_000))
        if ct.shape[1] >= 2 and ct.shape[0] >= 2:
            ct = ct.loc[ct.sum(axis=1).sort_values(ascending=False).head(8).index]
            data = []
            for idx, row in ct.iterrows():
                item = {"name": str(idx)[:40]}
                for col in ct.columns:
                    item[str(col)[:30]] = int(row[col])
                data.append(item)
            charts.append(ChartSpec(
                id="stacked_status", type="stacked_bar",
                title=f"{status_col} by {cc}", subtitle="Counts per category",
                columns=[cc, status_col], data=data, x="name",
                series=[str(c)[:30] for c in ct.columns], relevance=0.8))

    # 7. geographic distribution
    geo = next((p.name for p in profiles
                if p.semantic_type == "geographic" and 1 < p.unique_count <= 60
                and p.name in df.columns), None)
    if geo:
        vc = df[geo].astype(str).replace("", np.nan).dropna().value_counts().head(15)
        data = [{"name": str(k)[:40], "count": int(v)} for k, v in vc.items()]
        charts.append(ChartSpec(
            id=f"geo_{geo}", type="bar", title=f"Records by {geo}",
            subtitle=f"Top {len(data)} regions by row count",
            columns=[geo], data=data, x="name", y="count", relevance=0.75))

    charts.sort(key=lambda c: -c.relevance)
    return [c.as_dict() for c in charts[:MAX_CHARTS]]
