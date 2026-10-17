"""Financial transaction intelligence (spec #10, #11, #12).

Activates only when the semantic mapper found transaction-like columns.
All figures carry an explicit calculation policy; nothing is asserted as
proven wrongdoing — outputs are "potential"/"requires review" findings.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
import pandas as pd

from .freq import month_rule

RANDOM_STATE = 42

SUCCESS_STATES = {"success", "succeeded", "completed", "complete", "settled",
                  "posted", "ok", "approved", "captured", "paid", "processed"}
FAILED_STATES = {"failed", "failure", "declined", "rejected", "error", "cancelled",
                 "canceled", "returned", "chargeback"}
PENDING_STATES = {"pending", "processing", "in_progress", "authorized", "initiated",
                  "in_transit", "scheduled", "queued", "open"}


def _norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower()


@dataclass
class FinancialSummary:
    status: str
    reason: str = ""
    metrics: dict = field(default_factory=dict)
    volume_by_time: list = field(default_factory=list)
    volume_by_channel: list = field(default_factory=list)
    volume_by_currency: list = field(default_factory=list)
    status_breakdown: list = field(default_factory=list)
    calc_policy: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason, "metrics": self.metrics,
                "volume_by_time": self.volume_by_time,
                "volume_by_channel": self.volume_by_channel,
                "volume_by_currency": self.volume_by_currency,
                "status_breakdown": self.status_breakdown,
                "calc_policy": self.calc_policy, "warnings": self.warnings}


def summarize_transactions(df: pd.DataFrame, roles: dict[str, str | None],
                           time_col: str | None) -> FinancialSummary:
    res = FinancialSummary(status="completed")
    amt = roles.get("amount_source") or roles.get("amount_destination")
    if not amt:
        res.status = "unavailable"
        res.reason = "No amount column could be identified."
        return res

    amount = pd.to_numeric(df[amt], errors="coerce")
    status_col = roles.get("status")
    policy = [
        f"Amount column: '{amt}' (raw numeric coercion, invalid entries → NaN).",
        "Completed monetary movement = rows whose status maps to a success state "
        "(or all rows when no status column exists).",
        "Failed and pending rows are excluded from 'completed volume'.",
        "Reversals/refunds are counted separately, never subtracted silently.",
    ]

    status_series = None
    if status_col:
        status_series = _norm(df[status_col])

    def state_mask(states: set[str]) -> pd.Series:
        if status_series is None:
            return pd.Series(True, index=df.index)
        return status_series.isin(states)

    ok = state_mask(SUCCESS_STATES)
    failed = state_mask(FAILED_STATES) if status_series is not None else pd.Series(False, index=df.index)
    pending = state_mask(PENDING_STATES) if status_series is not None else pd.Series(False, index=df.index)
    unknown_status = (pd.Series(False, index=df.index) if status_series is None
                      else ~(ok | failed | pending))

    completed_amount = amount[ok]
    cur_col = roles.get("currency_source")
    multi_currency = False
    if cur_col and cur_col in df.columns:
        codes = df[cur_col].astype(str).str.upper().str.strip()
        multi_currency = codes[ok].nunique() > 1

    reversal_col = next((c for c in df.columns
                         if re.search(r"is_reversal|^reversal$", c, re.I)), None)
    refund_col = next((c for c in df.columns if re.search(r"is_refund|^refund$", c, re.I)), None)

    def _truthy(col: str) -> pd.Series:
        v = df[col]
        if v.dtype == bool:
            return v.fillna(False)
        return _norm(v).isin({"true", "1", "yes", "y", "1.0"})

    n_rev = int(_truthy(reversal_col).sum()) if reversal_col else 0
    n_ref = int(_truthy(refund_col).sum()) if refund_col else 0

    src_acct = roles.get("source_account")
    dst_acct = roles.get("destination_account")
    res.metrics = {
        "row_count": int(len(df)),
        "completed_count": int(ok.sum()),
        "failed_count": int(failed.sum()),
        "pending_count": int(pending.sum()),
        "unknown_status_count": int(unknown_status.sum()),
        "total_volume_completed": _r(completed_amount.sum()),
        "average_amount_completed": _r(completed_amount.mean()),
        "median_amount_completed": _r(completed_amount.median()),
        "largest_transaction": _r(amount.max()),
        "smallest_transaction": _r(amount.min()),
        "negative_amount_count": int((amount < 0).sum()),
        "distinct_source_accounts": int(df[src_acct].nunique()) if src_acct else None,
        "distinct_destination_accounts": int(df[dst_acct].nunique()) if dst_acct else None,
        "reversal_count": n_rev,
        "refund_count": n_ref,
        "failure_rate_pct": round(100 * float(failed.sum()) / max(int(len(df)), 1), 2),
        "reversal_rate_pct": round(100 * n_rev / max(int(len(df)), 1), 2),
        "multi_currency": multi_currency,
        "amount_column": amt,
        "status_column": status_col,
        "amount_sums_are_native_currency_only": multi_currency,
    }
    if multi_currency:
        res.warnings.append(
            "Multiple currencies detected — totals are sums of native amounts and must "
            "not be read as a single-currency total. Use the per-currency breakdown.")

    fee_col = next((c for c in df.columns
                    if re.search(r"^(fee_amount|fees|fee)$", c, re.I)), None)
    if fee_col:
        fee = pd.to_numeric(df[fee_col], errors="coerce")
        res.metrics["total_fees"] = _r(fee.sum())
        res.metrics["avg_fee"] = _r(fee.mean())

    # volume over time
    if time_col and time_col in df.columns:
        ts = pd.to_datetime(df[time_col], errors="coerce")
        tmp = pd.DataFrame({"t": ts, "amount": amount, "ok": ok})
        tmp = tmp.dropna(subset=["t"])
        if len(tmp):
            span = (tmp["t"].max() - tmp["t"].min()).days
            rule = month_rule() if span > 400 else "D" if span > 3 else "h"
            g = (tmp[tmp["ok"]].set_index("t").resample(rule)
                   .agg(count=("amount", "size"), value=("amount", "sum"))
                   .tail(400).reset_index())
            res.volume_by_time = [
                {"t": str(r["t"])[:19], "count": int(r["count"]), "value": _r(r["value"]) or 0}
                for _, r in g.iterrows()]

    # channel / rail breakdown
    chan = roles.get("payment_rail") or roles.get("category")
    if chan and chan in df.columns:
        g = (df.assign(_a=amount, _ok=ok)
               .groupby(df[chan].astype(str).str.strip().replace("", "unknown"))
               .agg(count=("_a", "size"),
                    volume=("_a", lambda s: float(pd.to_numeric(s, errors="coerce").sum())),
                    completed=("_ok", "sum"))
               .sort_values("count", ascending=False).head(15))
        res.volume_by_channel = [
            {"channel": str(idx)[:40], "count": int(r["count"]),
             "volume": _r(r["volume"]), "completed": int(r["completed"])}
            for idx, r in g.iterrows()]

    # per-currency breakdown (native)
    if cur_col and cur_col in df.columns:
        tmp = pd.DataFrame({"c": df[cur_col].astype(str).str.upper().str.strip(),
                            "a": amount, "ok": ok})
        g = (tmp.groupby("c")
                .agg(count=("a", "size"), volume=("a", "sum"),
                     completed_volume=("a", lambda s: float(s[tmp.loc[s.index, "ok"]].sum()))
                     if False else ("a", "sum"))
                .sort_values("count", ascending=False).head(15))
        res.volume_by_currency = [
            {"currency": str(idx), "count": int(r["count"]), "volume": _r(r["volume"])}
            for idx, r in g.iterrows()]
        # proper completed volume per currency
        cv = tmp[tmp["ok"]].groupby("c")["a"].sum()
        for item in res.volume_by_currency:
            item["completed_volume"] = _r(cv.get(item["currency"], 0))

    if status_col:
        vc = status_series.value_counts().head(10)
        res.status_breakdown = [{"status": str(k), "count": int(v),
                                 "pct": round(100 * v / max(len(df), 1), 2)}
                                for k, v in vc.items()]

    res.calc_policy = policy
    return res


def _r(x, nd: int = 4):
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------- network ------
@dataclass
class NetworkResult:
    status: str
    reason: str = ""
    node_count: int = 0
    edge_count: int = 0
    total_value: float | None = None
    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    communities: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"status": self.status, "reason": self.reason,
                "node_count": self.node_count, "edge_count": self.edge_count,
                "total_value": self.total_value, "nodes": self.nodes,
                "edges": self.edges, "metrics": self.metrics,
                "communities": self.communities, "warnings": self.warnings}


def build_transfer_network(df: pd.DataFrame, roles: dict[str, str | None],
                           top_n: int = 120, currency_filter: str | None = None,
                           status_filter: str | None = None) -> NetworkResult:
    src, dst = roles.get("source_account"), roles.get("destination_account")
    res = NetworkResult(status="completed")
    if not src or not dst:
        res.status = "unavailable"
        res.reason = ("Source and destination account columns are required. "
                      "Map them in the column-mapping panel to enable this analysis.")
        return res

    work = df[[src, dst]].copy()
    amt_col = roles.get("amount_source") or roles.get("amount_destination")
    if amt_col:
        work["__amount"] = pd.to_numeric(df[amt_col], errors="coerce").fillna(0)
    else:
        work["__amount"] = 0.0

    if currency_filter and roles.get("currency_source"):
        work = work[df[roles["currency_source"]].astype(str).str.upper().str.strip() == currency_filter]
    if status_filter and roles.get("status"):
        work = work[_norm(df[roles["status"]]) == status_filter.lower()]

    work[src] = work[src].astype(str).str.strip()
    work[dst] = work[dst].astype(str).str.strip()
    work = work[(work[src] != "") & (work[dst] != "") & (work[src] != "nan") & (work[dst] != "nan")]
    work = work[work[src] != work[dst]]

    if work.empty:
        res.status = "unavailable"
        res.reason = "No eligible source→destination pairs after filtering."
        return res

    # server-side aggregation: never ship unlimited graph data (spec #10.2)
    agg = (work.groupby([src, dst])
               .agg(count=("__amount", "size"), value=("__amount", "sum"))
               .reset_index())
    agg = agg.sort_values("value", ascending=False)

    degree = Counter()
    for _, r in agg.iterrows():
        degree[r[src]] += 1
        degree[r[dst]] += 1
    keep = {n for n, _ in degree.most_common(top_n)}
    agg = agg[agg[src].isin(keep) & agg[dst].isin(keep)]

    total_nodes_all = int(work[src].nunique() + work[dst].nunique())
    total_edges_all = int(len(agg))
    if total_nodes_all > top_n:
        res.warnings.append(
            f"Graph has {total_nodes_all:,} entities; showing the top {len(keep)} by "
            "connectivity (aggregated server-side).")

    G = nx.DiGraph()
    for _, r in agg.iterrows():
        G.add_edge(r[src], r[dst], count=int(r["count"]), value=float(r["value"]))

    out_val = defaultdict(float)
    in_val = defaultdict(float)
    out_cnt = defaultdict(int)
    in_cnt = defaultdict(int)
    for u, v, d in G.edges(data=True):
        out_val[u] += d["value"]
        in_val[v] += d["value"]
        out_cnt[u] += d["count"]
        in_cnt[v] += d["count"]

    pagerank = nx.pagerank(G, weight="value", max_iter=60) if G.number_of_nodes() else {}
    try:
        communities = nx.community.greedy_modularity_communities(G.to_undirected(), weight="value")
    except Exception:
        communities = []

    # layout (deterministic spring) so the client renders without heavy deps
    pos = nx.spring_layout(G, seed=RANDOM_STATE, weight="value", k=0.6, iterations=60) \
        if G.number_of_nodes() else {}

    max_val = max([d["value"] for _, _, d in G.edges(data=True)] + [1.0])
    for n in list(G.nodes()):
        G.nodes[n]["out"] = out_val[n]
        G.nodes[n]["in"] = in_val[n]

    comm_of = {}
    for i, c in enumerate(communities):
        for n in c:
            comm_of[n] = i

    nodes = []
    for n in G.nodes():
        p = pos.get(n, np.array([0.0, 0.0]))
        nodes.append({
            "id": n,
            "label": _mask_id(n),
            "x": round(float(p[0]), 5), "y": round(float(p[1]), 5),
            "out_value": round(out_val[n], 2), "in_value": round(in_val[n], 2),
            "out_count": out_cnt[n], "in_count": in_cnt[n],
            "net_flow": round(out_val[n] - in_val[n], 2),
            "degree": int(G.degree(n)),
            "pagerank": round(float(pagerank.get(n, 0.0)), 6),
            "community": comm_of.get(n, -1),
        })
    nodes.sort(key=lambda d: -(d["out_value"] + d["in_value"]))
    edges = [{"source": u, "target": v, "count": d["count"],
              "value": round(d["value"], 2),
              "width": round(1 + 7 * (d["value"] / max_val), 2)}
             for u, v, d in G.edges(data=True)]

    res.nodes = nodes
    res.edges = edges
    res.node_count = G.number_of_nodes()
    res.edge_count = G.number_of_edges()
    res.total_value = round(float(sum(d["value"] for _, _, d in G.edges(data=True))), 2)
    res.metrics = {
        "density": round(float(nx.density(G)), 5) if G.number_of_nodes() > 1 else 0.0,
        "weakly_connected_components": int(nx.number_weakly_connected_components(G)),
        "strongly_connected_components": int(nx.number_strongly_connected_components(G)),
        "reciprocal_edges": int(sum(1 for u, v in G.edges() if G.has_edge(v, u))),
        "top_pagerank": [
            {"entity": _mask_id(n), "pagerank": round(float(p), 6)}
            for n, p in sorted(pagerank.items(), key=lambda kv: -kv[1])[:8]],
        "community_count": len(communities),
        "aggregation": f"{len(keep)} of {total_nodes_all} entities shown",
    }
    res.communities = [{"community": i, "size": len(c)} for i, c in enumerate(communities)]
    res.warnings.append(
        "Network position (centrality, community) is descriptive — it is not "
        "evidence of wrongdoing.")
    return res


def _mask_id(v: str, keep: int = 4) -> str:
    v = str(v)
    if len(v) <= keep * 2:
        return v
    return f"{v[:keep]}…{v[-3:]}"


# ------------------------------------------------- suspicious patterns ------
@dataclass
class Finding:
    kind: str
    title: str
    severity: str              # info | medium | high
    evidence: str
    method: str
    thresholds: dict
    entity: str = ""
    entity_masked: str = ""
    row_count: int = 0
    examples: list = field(default_factory=list)
    time_range: dict = field(default_factory=dict)
    confidence: str = "moderate"
    false_positive_note: str = ""
    next_steps: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "title": self.title, "severity": self.severity,
            "evidence": self.evidence, "method": self.method,
            "thresholds": self.thresholds, "entity": self.entity_masked or self.entity,
            "row_count": self.row_count, "examples": self.examples,
            "time_range": self.time_range, "confidence": self.confidence,
            "false_positive_note": self.false_positive_note,
            "next_steps": self.next_steps,
        }


def detect_patterns(df: pd.DataFrame, roles: dict[str, str | None],
                    time_col: str | None, max_findings: int = 60) -> dict:
    """Explainable pattern detectors (spec #10.4)."""
    findings: list[Finding] = []
    src, dst = roles.get("source_account"), roles.get("destination_account")
    amt = roles.get("amount_source") or roles.get("amount_destination")
    status_col = roles.get("status")

    work = df.copy()
    if amt:
        work["__amt"] = pd.to_numeric(df[amt], errors="coerce")
    else:
        work["__amt"] = np.nan

    if time_col and time_col in df.columns:
        work["__t"] = pd.to_datetime(df[time_col], errors="coerce")
    else:
        work["__t"] = pd.NaT

    if status_col:
        st = _norm(df[status_col])
        # Boolean masks must always carry the same index as the frame they
        # select from: pandas raises "Unalignable boolean Series" when a mask
        # built from one frame is used as an indexer on another (e.g. after the
        # row filter below shrinks the frame).
        keep_mask = (st.isin(SUCCESS_STATES)
                     | ~st.isin(SUCCESS_STATES | FAILED_STATES | PENDING_STATES))
        keep_mask = keep_mask.reindex(work.index, fill_value=False)
        work = work[keep_mask]
        ok_mask = st.isin(SUCCESS_STATES).reindex(work.index, fill_value=False)
    else:
        ok_mask = pd.Series(True, index=work.index)
    ok_mask = ok_mask.reindex(work.index, fill_value=False)

    # ---------- 1. structuring / potential splitting --------------------
    if amt and src:
        findings.extend(_detect_splitting(work, src, amt, time_col))

    # ---------- 2. rapid pass-through -----------------------------------
    if amt and src and dst:
        findings.extend(_detect_passthrough(work, src, dst, amt))

    # ---------- 3. cycles ----------------------------------------------
    if src and dst:
        findings.extend(_detect_cycles(work, src, dst, amt))

    # ---------- 4. fan-in / fan-out ------------------------------------
    if src and dst:
        findings.extend(_detect_fan(work, src, dst, amt))

    # ---------- 5. behavioral anomalies on amounts/frequency -----------
    findings.extend(_detect_behavioral(work, src, amt, time_col))

    # ---------- 6. payment / reconciliation anomalies ------------------
    findings.extend(_detect_payment_issues(df, roles, work))

    # severity ordering
    order = {"high": 0, "medium": 1, "info": 2}
    findings.sort(key=lambda f: order.get(f.severity, 3))
    if len(findings) > max_findings:
        findings = findings[:max_findings]

    return {
        "findings": [f.as_dict() for f in findings],
        "total": len(findings),
        "disclaimer": (
            "These are statistical patterns and rule triggers, labeled as potential "
            "anomalies requiring review. They do not establish that any person or "
            "transaction committed fraud, money laundering, or any crime."),
        "methodology": {
            "structuring": "≥3 same-sign transactions to one counterparty inside 24h "
                           "whose individual amounts fall below a data-derived threshold "
                           "while their sum exceeds it.",
            "pass_through": "Funds received and ≥70% forwarded to a different entity "
                            "within 60 minutes.",
            "cycles": "Directed cycles of length 3–6 in the aggregated transfer graph "
                      "with total value ≥ threshold.",
            "fan": "Entities beyond the 99th percentile of unique counterparties "
                   "in/out, compared against the median.",
            "behavioral": "Robust z-score (MAD) on transaction amount and per-entity "
                          "|z| > 6.",
            "payment": "Contradictory statuses, repeated references, failure bursts, "
                       "settlement delays, amount mismatches.",
        },
    }


def _detect_splitting(work: pd.DataFrame, src: str, amt: str,
                      time_col: str | None) -> list[Finding]:
    out: list[Finding] = []
    sub = work.dropna(subset=[amt])
    if sub.empty or len(sub) < 100:
        return out
    a = sub[amt]
    p95 = float(a.quantile(0.95))
    p99 = float(a.quantile(0.99))
    # threshold: 95th percentile — "near-threshold" clustering is the signal
    threshold = p95 if p95 > 0 else p99
    if threshold <= 0:
        return out
    near = sub[(a > threshold * 0.75) & (a < threshold)]

    group_cols = [src]
    dst = next((c for c in ("__dst",) if c in near.columns), None)
    if "destination" in near.columns:
        pass
    if near.empty:
        return out

    if "__t" in near.columns and near["__t"].notna().any():
        near = near.copy()
        near["__bucket"] = near["__t"].dt.floor("24h")
        group_cols = group_cols + ["__bucket"]

    agg = (near.groupby(group_cols)[amt]
               .agg(count="size", total="sum", lo="min", hi="max")
               .reset_index())
    agg = agg[agg["count"] >= 3]
    agg = agg[agg["total"] >= threshold]
    agg = agg.sort_values("total", ascending=False).head(10)

    for _, r in agg.iterrows():
        entity = str(r[src])
        findings_time = {}
        if "__bucket" in r.index and pd.notna(r["__bucket"]):
            findings_time = {"start": str(r["__bucket"])[:19],
                             "end": str(pd.Timestamp(r["__bucket"]) + pd.Timedelta(hours=24))[:19]}
        out.append(Finding(
            kind="structuring",
            title=f"Potential transaction splitting — {_mask_id(entity)}",
            severity="medium",
            evidence=(f"{int(r['count'])} transactions between {_r(r['lo'])} and {_r(r['hi'])} "
                      f"totaling {_r(r['total'])} — individually below the "
                      f"{_r(threshold)} threshold (95th percentile)."),
            method="Threshold clustering over data-derived 95th percentile",
            thresholds={"near_threshold_lower": round(threshold * 0.75, 4),
                        "threshold_p95": round(threshold, 4),
                        "min_transactions": 3, "window": "24h" if "__bucket" in
                        [c for c in near.columns] else "unbounded"},
            entity=entity, row_count=int(r["count"]),
            time_range=findings_time,
            examples=[{"amount": _r(r["lo"])}, {"amount": _r(r["hi"])}],
            confidence="low-moderate",
            false_positive_note=("Legitimate businesses batch payments at round values "
                                 "near thresholds; proximity is not proof."),
            next_steps=("Review the referenced transactions' counterparties, purpose codes "
                        "and historical baseline for this entity."),
        ))
    return out


def _detect_passthrough(work: pd.DataFrame, src: str, dst: str, amt: str) -> list[Finding]:
    out: list[Finding] = []
    if "__t" not in work.columns or work["__t"].isna().all():
        return out
    sub = work.dropna(subset=["__t", amt]).sort_values("__t")
    if len(sub) < 100:
        return out

    incoming: dict[str, list[tuple[pd.Timestamp, float]]] = defaultdict(list)
    outgoing: dict[str, list[tuple[pd.Timestamp, float]]] = defaultdict(list)
    for _, r in sub.iterrows():
        incoming[str(r[dst])].append((r["__t"], float(r[amt])))
        outgoing[str(r[src])].append((r["__t"], float(r[amt])))

    candidates = []
    window = pd.Timedelta(minutes=60)
    for entity in list(incoming.keys())[:4000]:
        ins = sorted(incoming.get(entity, []))
        outs = sorted(outgoing.get(entity, []))
        if not ins or not outs:
            continue
        total_in = sum(v for _, v in ins)
        if total_in <= 0:
            continue
        for t_in, v_in in ins:
            if v_in <= 0:
                continue
            forwarded = 0.0
            hit_times = []
            for t_out, v_out in outs:
                if t_in < t_out <= t_in + window:
                    forwarded += max(v_out, 0.0)
                    hit_times.append(t_out)
            ratio = forwarded / v_in
            if ratio >= 0.7 and len(hit_times) >= 1 and v_in > 0:
                candidates.append((entity, t_in, v_in, forwarded, ratio, len(hit_times)))
                break
    candidates.sort(key=lambda x: -x[2])
    for entity, t_in, v_in, fwd, ratio, n in candidates[:8]:
        out.append(Finding(
            kind="pass_through",
            title=f"Rapid pass-through pattern — {_mask_id(entity)}",
            severity="high" if ratio >= 0.95 and v_in > 0 else "medium",
            evidence=(f"Received {_r(v_in)} at {str(t_in)[:19]} and forwarded "
                      f"{_r(fwd)} ({ratio:.0%}) to other entities within 60 minutes "
                      f"across {n} outgoing transaction(s)."),
            method="Inbound→outbound matching within a 60-minute window (≥70% forwarded)",
            thresholds={"forward_ratio": 0.7, "window_minutes": 60},
            entity=entity, row_count=n,
            time_range={"start": str(t_in)[:19],
                        "end": str(t_in + window)[:19]},
            examples=[{"in": _r(v_in), "forwarded": _r(fwd), "ratio": round(ratio, 3)}],
            confidence="moderate",
            false_positive_note=("Payment processors, wallets and merchant acquirers "
                                 "legitimately relay funds; observe patterns, not single events."),
            next_steps=("Trace the counterparty chain, check merchant/payroll purpose "
                        "codes, and compare against this entity's historical velocity."),
        ))
    return out


def _detect_cycles(work: pd.DataFrame, src: str, dst: str, amt: str) -> list[Finding]:
    out: list[Finding] = []
    sub = work.copy()
    if amt:
        agg = (sub.groupby([src, dst])[amt].agg(["size", "sum"]).reset_index())
        agg.columns = [src, dst, "count", "value"]
    else:
        agg = sub.groupby([src, dst]).size().reset_index(name="count")
        agg["value"] = 0.0
    agg = agg[agg[src] != agg[dst]]
    if agg.empty or len(agg) < 10:
        return out
    # Bound the search: cycles are only reported for length 3–6, so prune the
    # graph to the highest-value edges first. Without these bounds,
    # simple_cycles on a dense 49k-edge digraph enumerates millions of cycles.
    agg = agg.sort_values("value", ascending=False).head(4000)
    G = nx.from_pandas_edgelist(agg, src, dst, edge_attr=["count", "value"],
                                create_using=nx.DiGraph)
    if G.number_of_nodes() > 20_000 or G.number_of_edges() > 8_000:
        top = (agg.groupby(src)["value"].sum().sort_values(ascending=False)
               .head(3_000).index)
        G = G.subgraph(top)
    try:
        cycles = nx.simple_cycles(G, length_bound=6)
    except TypeError:
        cycles = nx.simple_cycles(G)
    except Exception:
        return out
    found = 0
    seen: set[frozenset] = set()
    for cyc in cycles:
        if found >= 5:
            break
        if not (3 <= len(cyc) <= 6):
            continue
        key = frozenset(cyc)
        if key in seen:
            continue
        seen.add(key)
        found += 1
        total = 0.0
        path = []
        for i in range(len(cyc)):
            u, v = cyc[i], cyc[(i + 1) % len(cyc)]
            w = 0.0
            if G.has_edge(u, v):
                w = float(G.edges[u, v].get("value", 0) or 0)
            total += w
            path.append(f"{_mask_id(u)} → {_mask_id(v)}")
        out.append(Finding(
            kind="circular_transfer",
            title=f"Circular transfer path ({len(cyc)} entities)",
            severity="medium" if total > 0 else "info",
            evidence=("Path: " + "; ".join(path) +
                      f". Aggregated value {_r(total)} across the cycle."),
            method="Directed cycle enumeration (networkx.simple_cycles, length bound 6, "
                   "top-4000-value edge subgraph)",
            thresholds={"min_length": 3, "max_length": 6},
            entity=cyc[0], row_count=len(cyc),
            examples=[{"path": p} for p in path],
            confidence="low",
            false_positive_note=("A graph cycle alone does not prove illegal activity — "
                                 "refunds, settlements and treasury sweeps naturally cycle."),
            next_steps=("Check timing gaps and whether amounts decay (fees) or match "
                        "exactly (layering), and inspect the entities' purposes."),
        ))
    return out


def _detect_fan(work: pd.DataFrame, src: str, dst: str, amt: str) -> list[Finding]:
    out: list[Finding] = []
    if len(work) < 200:
        return out
    fan_out = work.groupby(src)[dst].nunique()
    fan_in = work.groupby(dst)[src].nunique()
    for label, series, direction in (("fan-out", fan_out, "outbound"),
                                     ("fan-in", fan_in, "inbound")):
        if series.empty or series.nunique() < 3:
            continue
        p99 = float(series.quantile(0.99))
        median = float(series.median())
        hot = series[series >= max(p99, median * 10)].sort_values(ascending=False).head(6)
        for entity, n in hot.items():
            out.append(Finding(
                kind=label,
                title=f"Unusual {label} — {_mask_id(str(entity))}",
                severity="info",
                evidence=(f"{int(n)} unique {'recipients' if direction == 'outbound' else 'senders'} "
                          f"vs median {median:.0f} and 99th percentile {p99:.0f} "
                          f"across the dataset."),
                method="Unique-counterparty counting vs distribution percentiles",
                thresholds={"p99": round(p99, 2), "median": round(median, 2),
                            "min_unique": int(max(p99, median * 10))},
                entity=str(entity), row_count=int(n),
                confidence="low",
                false_positive_note=("Merchants, payroll processors and marketplaces "
                                     "legitimately show extreme counterparty counts."),
                next_steps=("Compare against the entity's type, historical baseline and "
                            "whether counterparties are first-time recipients."),
            ))
    return out


def _detect_behavioral(work: pd.DataFrame, src: str | None, amt: str,
                       time_col: str | None) -> list[Finding]:
    out: list[Finding] = []
    if not amt or amt not in work.columns:
        return out
    s = pd.to_numeric(work[amt], errors="coerce").dropna()
    if len(s) < 100:
        return out
    med = float(s.median())
    mad = float((s - med).abs().median())
    if mad <= 0:
        return out
    z = 0.6745 * (s - med) / mad
    extreme = s[z.abs() > 6]
    if len(extreme):
        out.append(Finding(
            kind="amount_anomaly",
            title=f"Extreme amounts vs robust baseline ({len(extreme):,} rows)",
            severity="medium",
            evidence=(f"{len(extreme):,} transactions exceed |z|>6 on the MAD scale "
                      f"(median {_r(med)}, MAD {_r(mad)}); max value {_r(s.max())}."),
            method="Robust z-score using median absolute deviation",
            thresholds={"z_threshold": 6, "median": round(med, 4), "mad": round(mad, 4)},
            row_count=int(len(extreme)),
            examples=[{"amount": _r(v)} for v in extreme.head(5).tolist()],
            confidence="moderate",
            false_positive_note=("Large legitimate payments exist; magnitude alone is "
                                 "not suspicious."),
            next_steps="Review the top extreme transactions for purpose and counterparty.",
        ))
    if time_col and src and "__t" in work.columns:
        g = work.dropna(subset=["__t"]).groupby(src).agg(
            n=(amt, "size"), total=(amt, "sum"))
        if len(g) >= 30:
            gmed = float(g["n"].median())
            gmadd = float((g["n"] - gmed).abs().median())
            if gmadd > 0:
                gz = 0.6745 * (g["n"] - gmed) / gmadd
                hot = gz[gz > 6].sort_values(ascending=False).head(5)
                for entity, val in hot.items():
                    out.append(Finding(
                        kind="velocity_anomaly",
                        title=f"Unusual transaction velocity — {_mask_id(str(entity))}",
                        severity="info",
                        evidence=(f"{int(g.loc[entity, 'n'])} transactions vs entity median "
                                  f"{gmed:.0f} (robust z={val:.1f})."),
                        method="Per-entity transaction count vs MAD baseline",
                        thresholds={"z_threshold": 6, "median_count": round(gmed, 2)},
                        entity=str(entity), row_count=int(g.loc[entity, "n"]),
                        confidence="low",
                        false_positive_note="Seasonality and campaigns raise legitimate volume.",
                        next_steps="Compare with the entity's own seasonal pattern.",
                    ))
    return out


def _detect_payment_issues(df: pd.DataFrame, roles: dict[str, str | None],
                           work: pd.DataFrame) -> list[Finding]:
    out: list[Finding] = []
    status_col = roles.get("status")
    findings_meta: list[dict] = []

    # contradictory status / lifecycle
    if status_col:
        st = _norm(df[status_col])
        success = st.isin(SUCCESS_STATES)
        failed_ts = next((c for c in df.columns
                          if re.search(r"failed_at|failure_at", c, re.I)), None)
        if failed_ts:
            n = int((success & df[failed_ts].notna()).sum())
            if n:
                findings_meta.append(dict(
                    kind="status_conflict",
                    title=f"Contradictory lifecycle: {n} rows marked successful with a failure timestamp",
                    severity="medium",
                    evidence=f"'{status_col}' = success while '{failed_ts}' is populated in {n} rows.",
                    method="Cross-field status/timestamp validation",
                    thresholds={"expected": 0}, row_count=n,
                    false_positive_note="Schema drift can mimic this pattern.",
                    next_steps="Confirm whether failed_at records retries on successful payments."))

        fail_vals = st.isin(FAILED_STATES)
        fail_rate = float(fail_vals.mean())
        if fail_rate > 0.15 and len(df) >= 100:
            findings_meta.append(dict(
                kind="failure_burst",
                title=f"Elevated failure rate ({fail_rate:.1%})",
                severity="info",
                evidence=f"{int(fail_vals.sum()):,} of {len(df):,} rows are in a failed state.",
                method="Status distribution vs expected operating range",
                thresholds={"warn_above": 0.15}, row_count=int(fail_vals.sum()),
                false_positive_note="Batch windows and issuer outages raise failure rates.",
                next_steps="Slice failures by channel, institution and time window."))

    # repeated references — masks below are computed on this frame's own index
    # so they stay alignable even when callers pass a pre-filtered subset.
    df = df.reset_index(drop=True)
    ref_col = next((c for c in df.columns
                    if re.search(r"reference_id|original_transaction_id|ref$", c, re.I)), None)
    if ref_col:
        s_full = df[ref_col].astype(str).str.strip()
        valid = (s_full != "") & (s_full.str.lower() != "nan")
        s = s_full[valid]
        vc = s.value_counts()
        dups = vc[vc > 1]
        if len(dups) >= 1:
            conflicts = 0
            top = dups.head(50)
            for val, cnt in top.items():
                rows = df.loc[s.index[s == val]]
                if status_col and rows[status_col].astype(str).nunique() > 1:
                    conflicts += 1
            n_rows = int(dups.sum())
            out.append(Finding(
                kind="duplicate_reference",
                title=f"Repeated reference values ({len(dups):,} distinct, {n_rows:,} rows)",
                severity="medium" if conflicts else "info",
                evidence=(f"'{ref_col}' repeats; {conflicts} of the top repeated values "
                          f"carry conflicting statuses."),
                method="Reference frequency counting with status consistency check",
                thresholds={"min_occurrences": 2, "conflicting": conflicts},
                row_count=n_rows, examples=[{"value": _mask_id(str(k), 6), "count": int(v)}
                                            for k, v in dups.head(5).items()],
                confidence="moderate" if conflicts else "low",
                false_positive_note="Legitimate retries reuse references by design.",
                next_steps="Inspect whether duplicates map to distinct settlement events."))

    # settlement delays / reconciliation mismatch
    exp_col = next((c for c in df.columns if re.search(r"expected_settlement_amount", c, re.I)), None)
    obs_col = next((c for c in df.columns if re.search(r"observed_settlement_amount", c, re.I)), None)
    if exp_col and obs_col:
        e = pd.to_numeric(df[exp_col], errors="coerce")
        o = pd.to_numeric(df[obs_col], errors="coerce")
        mask = e.notna() & o.notna()
        if mask.sum() >= 20:
            diff = (e[mask] - o[mask]).abs()
            tol = max(0.01, float(diff.median()) * 3)
            bad = diff[diff > tol]
            if len(bad):
                out.append(Finding(
                    kind="reconciliation_mismatch",
                    title=f"Expected vs observed settlement mismatch ({len(bad):,} rows)",
                    severity="medium" if len(bad) / mask.sum() < 0.2 else "high",
                    evidence=(f"{len(bad):,} of {int(mask.sum()):,} reconcilable rows differ by "
                              f"more than {_r(tol)} (median diff {_r(float(diff.median()))})."),
                    method="Pairwise expected/observed comparison with 3×median tolerance",
                    thresholds={"tolerance": round(tol, 4), "compared_rows": int(mask.sum())},
                    row_count=int(len(bad)),
                    examples=[{"expected": _r(e[mask].loc[i]), "observed": _r(o[mask].loc[i]),
                               "difference": _r(diff.loc[i])} for i in bad.head(5).index],
                    confidence="high",
                    false_positive_note="Rounding and FX timing explain small diffs.",
                    next_steps="Group mismatches by currency, institution and reconciliation status."))

    delay_col = next((c for c in df.columns
                      if re.search(r"settlement_delay_flag|delay_flag", c, re.I)), None)
    if delay_col:
        v = _norm(df[delay_col])
        n = int(v.isin({"true", "1", "yes", "y", "1.0"}).sum())
        if n:
            out.append(Finding(
                kind="settlement_delay",
                title=f"Delayed settlements flagged in {n:,} rows",
                severity="info",
                evidence=f"'{delay_col}' is true in {n:,} rows "
                         f"({100 * n / max(len(df), 1):.1f}%).",
                method="Flag column counting",
                thresholds={}, row_count=n,
                confidence="high",
                false_positive_note="SLA definitions vary by rail and corridor.",
                next_steps="Break delays down by institution and payment rail."))

    for m in findings_meta:
        out.append(Finding(false_positive_note=m.pop("false_positive_note", ""),
                           next_steps=m.pop("next_steps", ""),
                           **m))
    return out


# -------------------------------------------------------------- currency ----
def currency_analysis(df: pd.DataFrame, roles: dict[str, str | None]) -> dict:
    src_cur = roles.get("currency_source")
    dst_cur = roles.get("currency_destination")
    fx = roles.get("fx_rate")
    src_amt = roles.get("amount_source")
    dst_amt = roles.get("amount_destination")
    out: dict = {"status": "unavailable", "reason": "", "pairs": [],
                 "native_totals": [], "rate_stats": {}, "warnings": [], "methodology": []}

    if not (src_cur or dst_cur):
        out["reason"] = "No currency code columns were detected."
        return out
    out["status"] = "completed"
    out["methodology"] = [
        "Native totals are computed per currency — amounts are never summed across currencies.",
        "FX analysis uses rates embedded in the uploaded rows only; no live feed is configured.",
        "Synthetic reference rates are labeled as synthetic when the source column says so.",
    ]

    if src_cur and src_cur in df.columns:
        s = df[src_cur].astype(str).str.upper().str.strip()
        amt = pd.to_numeric(df.get(src_amt), errors="coerce") if src_amt else None
        g = s.value_counts().head(12)
        totals = {}
        if amt is not None:
            totals = df.groupby(s)[src_amt].apply(
                lambda col: float(pd.to_numeric(col, errors="coerce").sum()))
        out["native_totals"] = [
            {"currency": str(c), "count": int(n),
             "native_total": _r(float(totals.get(str(c), 0))) if len(totals) else None}
            for c, n in g.items()]
        out["currencies"] = [str(c) for c in g.index.tolist()]

    if fx and fx in df.columns:
        r = pd.to_numeric(df[fx], errors="coerce").dropna()
        r = r[r > 0]
        if len(r) >= 5:
            spread = float((r.quantile(0.75) - r.quantile(0.25)))
            out["rate_stats"] = {
                "observations": int(len(r)),
                "min": _r(float(r.min())), "max": _r(float(r.max())),
                "mean": _r(float(r.mean())), "median": _r(float(r.median())),
                "std": _r(float(r.std())),
                "volatility_pct": _r(float(r.std() / r.mean() * 100), 3) if r.mean() else None,
                "iqr": _r(spread),
                "pct_change": _r(float((r.iloc[-1] - r.iloc[0]) / r.iloc[0] * 100), 3),
                "coverage": "scattered per-transaction observations (not a continuous series)",
            }
            out["warnings"].append(
                "These rates are observations embedded in transaction rows, not an "
                "independent exchange-rate time series.")
            # time series of rates if a time column exists
            time_col = next((c for c in df.columns if re.search(r"fx_rate_timestamp|initiated_at", c, re.I)), None)
            if time_col:
                ts = pd.to_datetime(df[time_col], errors="coerce")
                tmp = pd.DataFrame({"t": ts, "r": pd.to_numeric(df[fx], errors="coerce")})
                tmp = tmp.dropna().sort_values("t")
                if len(tmp) >= 10:
                    span = (tmp["t"].max() - tmp["t"].min()).days
                    rule = month_rule() if span > 400 else "D" if span > 7 else "h"
                    g = tmp.set_index("t").resample(rule)["r"].mean().tail(300)
                    out["rate_series"] = [{"t": str(i)[:19], "rate": _r(v)}
                                          for i, v in g.items() if pd.notna(v)]
                    out["rate_stats"]["bucket"] = rule

    # conversion consistency check
    if fx and src_amt and dst_amt and all(c in df.columns for c in (fx, src_amt, dst_amt)):
        a = pd.to_numeric(df[src_amt], errors="coerce")
        b = pd.to_numeric(df[dst_amt], errors="coerce")
        rate = pd.to_numeric(df[fx], errors="coerce")
        mask = a.notna() & b.notna() & rate.notna() & (rate > 0)
        if mask.sum() >= 20:
            expected = a[mask] * rate[mask]
            rel = ((expected - b[mask]).abs() / expected.abs().replace(0, np.nan))
            bad = int((rel > 0.01).sum())
            out["conversion_check"] = {
                "compared_rows": int(mask.sum()),
                "rows_over_1pct_error": bad,
                "error_rate_pct": round(100 * bad / int(mask.sum()), 2),
                "formula": "expected_destination = source_amount × fx_rate_to_destination",
                "note": "Tolerance 1%; mismatches may indicate fee handling or rate drift.",
            }
            if bad:
                out["warnings"].append(
                    f"{bad} rows where source×rate differs from destination by >1%.")
    return out
