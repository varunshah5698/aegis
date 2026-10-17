"""AI dataset assistant (spec #15).

Architecture: an allowlisted query-planning layer maps a natural-language
question to validated analytical operations. The backend computes every
number; the assistant only formats real results. When an LLM provider is
configured (env OPENAI_API_KEY) it may *rewrite/summarize* the answer, but
the figures always come from the computed operation result — the LLM never
does arithmetic and never sees raw rows unless authorized.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd

from . import config

# ------------------------------------------------------------- planner ------
@dataclass
class Intent:
    name: str
    args: dict = field(default_factory=dict)
    confidence: float = 0.5


TOPIC_PATTERNS: list[tuple[str, list[str]]] = [
    ("findings", [r"important findings", r"key findings", r"summary", r"summar",
                  r"top insight", r"what did you find", r"overview", r"explain this dataset",
                  r"in simple language"]),
    ("quality", [r"missing", r"inconsistent", r"quality", r"duplicate", r"dirty",
                 r"null", r"empty"]),
    ("top_outgoing", [r"highest outgoing", r"top sender", r"largest senders",
                      r"most outgoing", r"who sends", r"sent (the )?most",
                      r"sends? (the )?most", r"largest (outbound|sent|payer|sender)",
                      r"outbound (transfer|payment|value|amount)", r"paid (the )?most",
                      r"received the most from"]),
    ("top_incoming", [r"highest incoming", r"top receiver", r"who receives",
                      r"most incoming", r"received (the )?most", r"receives? (the )?most",
                      r"largest (inbound|received|payee|receiver)",
                      r"inbound (transfer|payment|value|amount)"]),
    ("passthrough", [r"pass[- ]?through", r"layering", r"rapid"]),
    ("cycles", [r"cycle", r"circular", r"round[- ]?trip"]),
    ("flagged", [r"flagged", r"why was this", r"anomal", r"outlier", r"suspicious"]),
    ("compare_status", [r"compare successful", r"successful and failed",
                        r"success vs", r"failure rate"]),
    ("currency", [r"currency", r"exchange", r"conversion", r"fx", r"multicurrency"]),
    ("model_features", [r"model feature", r"important feature", r"feature importance",
                        r"why did the model"]),
    ("period_compare", [r"compare this time", r"previous period", r"vs the previous",
                        r"over time"]),
    ("missing_fields", [r"additional field", r"which fields", r"improve this analysis",
                        r"what should i add"]),
    ("chart", [r"explain this chart", r"what does this chart", r"describe the chart"]),
    ("records", [r"show the transaction", r"supporting record", r"show rows",
                 r"show records", r"which records"]),
    ("report", [r"executive report", r"generate a report", r"create report"]),
    ("forecast", [r"forecast", r"predict", r"future", r"next week"]),
]

ALLOWED_TOPICS = {t for t, _ in TOPIC_PATTERNS}


def plan(question: str) -> Intent:
    q = question.lower().strip()
    best: tuple[str, float] | None = None
    for topic, pats in TOPIC_PATTERNS:
        for pat in pats:
            if re.search(pat, q):
                score = 0.9 if len(pat) > 12 else 0.75
                if best is None or score > best[1]:
                    best = (topic, score)
    if best:
        return Intent(best[0], confidence=best[1])
    if re.search(r"(how many|count|rows|columns|shape|size)", q):
        return Intent("overview", confidence=0.7)
    if re.search(r"(top|highest|largest|most)\s+\w+", q):
        return Intent("top_categories", confidence=0.6)
    return Intent("unknown", confidence=0.2)


# ------------------------------------------------------------ executor ------
def answer(question: str, manifest: dict, load_frame) -> dict:
    """Execute the planned intent against persisted results.

    `load_frame` is a callable returning the parsed DataFrame (lazily).
    """
    intent = plan(question)
    ctx = {"question": question, "topic": intent.name, "confidence": intent.confidence,
           "scope": "This analysis covers the uploaded dataset only."}
    try:
        payload = _EXECUTORS.get(intent.name, _exec_unknown)(question, manifest, load_frame)
    except Exception as exc:
        payload = {"answer": f"The request could not be completed: {exc}",
                   "data": None, "unable": True}
    ctx.update(payload)
    ctx["limitations"] = _limitations(manifest, intent.name)
    if not config.llm_configured():
        ctx["llm_note"] = ("No external LLM provider is configured — answers are produced "
                           "by the rule-based query planner over computed results.")
    ctx["follow_ups"] = _followups(intent.name, manifest)
    return ctx


def _limitations(manifest: dict, topic: str) -> list[str]:
    lim = ["Answers are computed from this dataset only.",
           "Association does not imply causation."]
    if topic in ("flagged", "passthrough", "cycles", "top_outgoing", "top_incoming"):
        lim.append("Pattern triggers are review candidates, not proof of wrongdoing.")
    lim.extend(list(manifest.get("limitations", []))[:2])
    return lim


def _followups(topic: str, manifest: dict) -> list[str]:
    common = ["What are the most important findings?", "What is missing or inconsistent?"]
    extra = {
        "flagged": ["Find transaction cycles", "Show potential rapid pass-through patterns."],
        "cycles": ["Which entities appear in multiple cycles?"],
        "currency": ["Compare successful and failed transactions."],
        "model_features": ["Why was this record flagged?"],
        "findings": ["Explain the most important model features.", "Generate an executive report."],
    }
    return (extra.get(topic) or []) + [c for c in common if c.lower() != topic]


# ---------------------------------------------------------- executors -------
def _exec_unknown(q, m, load):
    return {"answer": "I could not map that question to an allowlisted analytical "
                      "operation. Try asking about findings, data quality, top senders "
                      "or receivers, anomalies, cycles, currency, or model features.",
            "data": None, "unable": True}


def _exec_findings(q, m, load):
    items = (m.get("findings") or {}).get("key_findings", [])
    if not items:
        return {"answer": "No findings were generated for this dataset.", "data": None}
    lines = [f"{i + 1}. [{f['category']}] {f['title']} — {f['detail']}"
             for i, f in enumerate(items[:8])]
    return {"answer": "Key findings, ordered by module:\n" + "\n".join(lines),
            "data": {"findings": items[:8]}}


def _exec_quality(q, m, load):
    qd = m.get("quality") or {}
    miss = (qd.get("missing") or {}).get("columns_with_missing", [])[:8]
    dups = qd.get("duplicates") or {}
    inv = qd.get("invalid") or {}
    lines = [f"Quality score: {qd.get('score')}/100 (grade {qd.get('grade')})."]
    lines += [f"{c['column']}: {c['missing_pct']}% missing ({c['missing_count']:,} values)"
              for c in miss] or ["No column contains missing values."]
    lines.append(f"Exact duplicate rows: {dups.get('exact_duplicate_rows', 0):,} "
                 f"({dups.get('duplicate_pct', 0)}%).")
    if inv.get("date_issues"):
        lines.append(f"Unparseable timestamps in: {', '.join(inv['date_issues'])}.")
    if inv.get("numeric_issues"):
        lines.append(f"Non-numeric values inside numeric columns: "
                     f"{', '.join(inv['numeric_issues'])}.")
    for r in (qd.get("recommendations") or [])[:3]:
        lines.append(f"Recommendation → {r['action']}: {r['reason']}")
    return {"answer": "\n".join(lines),
            "data": {"score": qd.get("score"), "missing": miss, "duplicates": dups}}


def _exec_overview(q, m, load):
    ov = m.get("overview", {})
    cols = m.get("columns", [])
    cap = m.get("capabilities", {})
    active = [x["key"] for x in m.get("modules", []) if x["state"] == "active"]
    lines = [
        f"{m.get('filename')}: {ov.get('row_count', 0):,} rows × "
        f"{ov.get('column_count', 0)} columns.",
        f"{ov.get('numeric_columns', 0)} numeric, {ov.get('categorical_columns', 0)} "
        f"categorical, {ov.get('datetime_columns', 0)} datetime columns.",
        f"Missing cells {ov.get('missing_pct')}%; duplicate rows {ov.get('duplicate_pct')}%.",
        f"Activated modules: {', '.join(active)}.",
    ]
    tc = ov.get("time_coverage")
    if tc:
        lines.append(f"Time coverage {tc['start']} → {tc['end']} "
                     f"({tc['span_days']} days).")
    unsupported = {k: v.get("reason") for k, v in cap.items() if v.get("state") == "unavailable"}
    if unsupported:
        lines.append("Not supported by this file: " +
                     "; ".join(f"{k} — {v}" for k, v in list(unsupported.items())[:4]))
    lines.append("Column meanings: " + "; ".join(
        f"{c['name']}={c['semantic_type']}" for c in cols[:10]))
    return {"answer": "\n".join(lines), "data": {"overview": ov}}


def _exec_top_outgoing(q, m, load):
    return _exec_network_top(q, m, load, direction="out")


def _exec_top_incoming(q, m, load):
    return _exec_network_top(q, m, load, direction="in")


def _exec_network_top(q, m, load, direction="out"):
    net = ((m.get("financial") or {}).get("modules") or {}).get("network") or {}
    if net.get("status") != "completed":
        reason = net.get("reason", "Network analysis is unavailable for this dataset.")
        return {"answer": reason, "data": None, "unable": True}
    key = "out_value" if direction == "out" else "in_value"
    keyn = "out_count" if direction == "out" else "in_count"
    top = sorted(net.get("nodes", []), key=lambda n: -n.get(key, 0))[:10]
    verb = "sent" if direction == "out" else "received"
    lines = [f"Top {len(top)} entities by value {verb} (masked IDs):"]
    for i, n in enumerate(top, 1):
        lines.append(f"{i}. {n['label']} — {n[key]:,.2f} across {n[keyn]:,} transactions "
                     f"(net {n['net_flow']:,.2f})")
    lines.append(net.get("warnings", [""])[0])
    return {"answer": "\n".join(lines),
            "data": {"nodes": top},
            "chart_hint": {"type": "bar", "x": "label", "y": key, "rows": top}}


def _exec_passthrough(q, m, load):
    return _exec_pattern(q, m, load, "pass_through")


def _exec_cycles(q, m, load):
    return _exec_pattern(q, m, load, "circular_transfer")


def _exec_pattern(q, m, load, kind):
    patterns = ((m.get("financial") or {}).get("modules") or {}).get("patterns") or {}
    hits = [f for f in patterns.get("findings", []) if f["kind"] == kind]
    if not hits:
        return {"answer": f"No '{kind}' pattern was detected under the configured "
                          "thresholds. This means none crossed the threshold — not that "
                          "none exists.",
                "data": {"findings": []}}
    lines = [f"{len(hits)} '{kind}' finding(s) requiring review:"]
    for i, f in enumerate(hits[:6], 1):
        lines.append(f"{i}. {f['title']} [{f['severity']}]\n   {f['evidence']}\n"
                     f"   method: {f['method']}\n   next: {f['next_steps']}")
    lines.append(patterns.get("disclaimer", ""))
    return {"answer": "\n".join(lines), "data": {"findings": hits[:6]},
            "records": [f.get("examples", []) for f in hits[:6]]}


def _exec_flagged(q, m, load):
    ml = m.get("ml") or {}
    anomaly = ml.get("anomaly") or {}
    patterns = ((m.get("financial") or {}).get("modules") or {}).get("patterns") or {}
    parts = []
    data = {"anomaly": anomaly, "rule_findings": patterns.get("findings", [])[:5]}
    if anomaly.get("status") == "completed":
        mm = anomaly.get("metrics", {})
        parts.append(f"IsolationForest flagged {mm.get('flagged', 0):,} rows "
                     f"({mm.get('flagged_pct')}%) out of {anomaly.get('sample_size', 0):,} scored.")
        agree = mm.get("agreement_with_label")
        if agree:
            parts.append(f"Against the synthetic ground-truth label: "
                         f"precision {agree['precision']}, recall {agree['recall']} "
                         f"({agree['support_positive']} positives).")
        parts.append("Top flagged rows and their dominant deviations:")
        for i, a in enumerate(anomaly.get("anomalies", [])[:5], 1):
            why = "; ".join(f"{r['feature']}={r['value']} ({r['deviation_sigma']}σ from median)"
                            for r in a.get("reasons", []))
            parts.append(f"{i}. row {a['row_index']} score {a['score']} — {why}")
        parts.extend(anomaly.get("limitations", [])[:1])
    else:
        parts.append(f"Anomaly model unavailable: {anomaly.get('reason', 'not run')}")
    if patterns.get("findings"):
        parts.append("Rule-based findings also apply:")
        for f in patterns["findings"][:3]:
            parts.append(f"- {f['title']}: {f['evidence']}")
    return {"answer": "\n".join(parts), "data": data}


def _exec_compare_status(q, m, load):
    fin = (m.get("financial") or {}).get("modules") or {}
    summary = fin.get("summary") or {}
    perf = fin.get("performance") or {}
    if summary.get("status") != "completed" or not summary.get("metrics"):
        reason = summary.get("reason", "No status/amount columns for comparison.")
        return {"answer": reason, "data": None, "unable": True}
    mm = summary["metrics"]
    bd = summary.get("status_breakdown", [])
    lines = [
        f"Completed: {mm.get('completed_count', 0):,} · Failed: {mm.get('failed_count', 0):,} "
        f"· Pending: {mm.get('pending_count', 0):,} · Other: {mm.get('unknown_status_count', 0):,}",
        f"Failure rate: {mm.get('failure_rate_pct')}% of all rows "
        f"(denominator: every row in the file).",
        f"Completed volume (native units): {mm.get('total_volume_completed')} · "
        f"median amount {mm.get('median_amount_completed')}",
    ]
    if bd:
        lines.append("Status distribution: " +
                     ", ".join(f"{s['status']} {s['pct']}%" for s in bd[:6]))
    if perf.get("by_channel"):
        lines.append("By channel: " + "; ".join(
            f"{c['channel']} success {c['success_pct']}% / failure {c['failure_pct']}%"
            for c in perf["by_channel"][:5]))
    lines.extend(summary.get("calc_policy", [])[:3])
    return {"answer": "\n".join(lines),
            "data": {"metrics": mm, "breakdown": bd},
            "chart_hint": {"type": "bar", "x": "status", "y": "count", "rows": bd}}


def _exec_currency(q, m, load):
    cur = ((m.get("financial") or {}).get("modules") or {}).get("currency") or {}
    if cur.get("status") != "completed":
        return {"answer": cur.get("reason", "Currency analysis unavailable."), "data": None,
                "unable": True}
    lines = ["Native-currency totals (never summed across currencies):"]
    for t in cur.get("native_totals", []):
        lines.append(f"- {t['currency']}: {t['count']:,} rows, native total {t.get('native_total')}")
    rs = cur.get("rate_stats") or {}
    if rs:
        lines.append(f"Embedded FX observations: {rs.get('observations')} · "
                     f"min {rs.get('min')} · max {rs.get('max')} · "
                     f"volatility {rs.get('volatility_pct')}% · {rs.get('coverage')}")
    cc = cur.get("conversion_check")
    if cc:
        lines.append(f"Conversion check ({cc['formula']}): {cc['rows_over_1pct_error']:,} of "
                     f"{cc['compared_rows']:,} rows differ by >1% ({cc['error_rate_pct']}%).")
    lines.extend(cur.get("warnings", []))
    lines.extend(cur.get("methodology", []))
    return {"answer": "\n".join(lines), "data": cur}


def _exec_model_features(q, m, load):
    sup = (m.get("ml") or {}).get("supervised") or {}
    if sup.get("status") != "completed":
        return {"answer": sup.get("reason", "No supervised model was trained on this "
                                            "dataset, so there are no feature importances."),
                "data": None, "unable": True}
    fi = sup.get("feature_importance", [])
    if not fi:
        return {"answer": f"The selected model ({sup.get('best_model')}) does not expose "
                          "native feature importances.", "data": None, "unable": True}
    lines = [f"{sup.get('best_model')} ({sup.get('task')}) — held-out metrics: "
             + ", ".join(f"{k}={v}" for k, v in list(sup.get("metrics", {}).items())[:4]),
             "Top features by model-native importance:"]
    for i, f in enumerate(fi[:10], 1):
        lines.append(f"{i}. {f['feature']}: {f['importance']}")
    lines.append("Excluded from features to prevent leakage: "
                 + ", ".join(sup.get("excluded_features", [])[:10]))
    lines.append("Importance reflects predictive association, not causation.")
    return {"answer": "\n".join(lines), "data": {"importance": fi[:20]},
            "chart_hint": {"type": "bar", "x": "feature", "y": "importance", "rows": fi[:10]}}


def _exec_period_compare(q, m, load):
    fin = (m.get("financial") or {}).get("modules") or {}
    series = fin.get("summary", {}).get("volume_by_time") or []
    if len(series) < 4:
        ov = m.get("forecast") or {}
        if ov.get("status") == "completed":
            return _exec_forecast(q, m, load)
        return {"answer": "Not enough time-bucketed data to compare periods.",
                "data": None, "unable": True}
    half = len(series) // 2
    a, b = series[:half], series[half:]
    sa = sum(x.get("value") or 0 for x in a)
    sb = sum(x.get("value") or 0 for x in b)
    ca = sum(x.get("count") or 0 for x in a)
    cb = sum(x.get("count") or 0 for x in b)
    delta = ((sb - sa) / sa * 100) if sa else None
    lines = [
        f"First half: {ca:,} transactions, value {sa:,.2f} "
        f"({a[0].get('t', '')[:10]} → {a[-1].get('t', '')[:10]})",
        f"Second half: {cb:,} transactions, value {sb:,.2f} "
        f"({b[0].get('t', '')[:10]} → {b[-1].get('t', '')[:10]})",
        f"Change: {delta:+.1f}% in value, {cb - ca:+,} in count" if delta is not None
        else f"Change: {cb - ca:+,} in count",
    ]
    return {"answer": "\n".join(lines), "data": {"first": a, "second": b},
            "chart_hint": {"type": "line", "x": "t", "y": "value", "rows": series}}


def _exec_missing_fields(q, m, load):
    cap = m.get("capabilities", {})
    un = {k: v.get("reason", "") for k, v in cap.items() if v.get("state") == "unavailable"}
    lines = ["The following analyses are unavailable and what would enable them:"]
    mapping = {
        "transfer_network": "map explicit source/destination account columns",
        "reconciliation": "add expected/observed settlement amount and date columns",
        "currency": "add currency code and amount columns",
        "fx": "add fx_rate and currency columns",
        "timeseries": "add a date/timestamp column",
        "ml_classification": "add a label/target column (e.g. outcome, is_fraud)",
        "relationships": "add at least two numeric columns",
        "payments": "add a status column",
    }
    if not un:
        lines.append("Nothing missing — every module is active for this dataset.")
    for k, r in un.items():
        lines.append(f"- {k}: {r} → {mapping.get(k, 'add the required columns')}")
    return {"answer": "\n".join(lines), "data": un}


def _exec_chart(q, m, load):
    charts = m.get("charts", [])
    if not charts:
        return {"answer": "No chart is available for this dataset.", "data": None,
                "unable": True}
    c = charts[0]
    lines = [f"'{c['title']}' — {c['subtitle']}",
             f"Type: {c['type']} · {len(c['data'])} data points · "
             f"relevance {c['relevance']}",
             f"Columns: {', '.join(c['columns'])}"]
    if c.get("note"):
        lines.append(c["note"])
    return {"answer": "\n".join(lines), "data": c}


def _exec_records(q, m, load):
    """Return supporting rows for the top finding (server-side, bounded)."""
    findings = (m.get("findings") or {}).get("key_findings", [])
    df = load()
    n = min(20, max(1, len(q.split())))
    sample = df.head(10)
    answer = (f"Supporting records: showing the first {len(sample)} rows of "
              f"{len(df):,}. Use the workspace table with filters to inspect specific "
              f"transactions; the assistant returns bounded samples only.")
    return {"answer": answer,
            "data": {"columns": list(sample.columns),
                     "rows": json.loads(sample.to_json(orient="records", date_format="iso"))},
            "records_count": len(df),
            "top_finding": findings[0] if findings else None}


def _exec_report(q, m, load):
    return {"answer": "Report generation runs from the Reports panel — it renders the "
                      "executive, technical and investigation reports from these "
                      "persisted results (JSON, Markdown, CSV and XLSX).",
            "data": {"modules": [x["key"] for x in m.get("modules", [])
                                 if x["state"] == "active"]},
            "action": "open_reports"}


def _exec_forecast(q, m, load):
    f = m.get("forecast") or {}
    if f.get("status") != "completed":
        return {"answer": f.get("reason", "Forecasting is unavailable for this dataset."),
                "data": None, "unable": True}
    lines = [f"Seasonal-naive forecast on '{f['target']}' "
             f"({f['points']} daily points, backtest {f['backtest_points']}):",
             f"Backtest MAE {f['mae']} · RMSE {f['rmse']} · MAPE {f.get('mape_pct')}%",
             "Next 7 days:"]
    for x in f.get("future", []):
        lines.append(f"- {x['t']}: {x['forecast']}")
    lines.append(f.get("note", ""))
    return {"answer": "\n".join(lines), "data": f,
            "chart_hint": {"type": "line", "x": "t", "y": "forecast",
                           "rows": f.get("future", [])}}


def _exec_top_categories(q, m, load):
    stats = m.get("stats", {}) or {}
    cats = stats.get("categorical", [])
    if not cats:
        return {"answer": "This dataset has no low-cardinality categorical columns to rank.",
                "data": None, "unable": True}
    c = cats[0]
    lines = [f"Top values in {c['column']} ({c['unique']} distinct):"]
    for i, t in enumerate(c["top"][:8], 1):
        lines.append(f"{i}. {t['value']}: {t['count']:,} ({t['pct']}%)")
    return {"answer": "\n".join(lines), "data": c,
            "chart_hint": {"type": "bar", "x": "value", "y": "count", "rows": c["top"]}}


_EXECUTORS = {
    "findings": _exec_findings,
    "quality": _exec_quality,
    "overview": _exec_overview,
    "top_outgoing": _exec_top_outgoing,
    "top_incoming": _exec_top_incoming,
    "passthrough": _exec_passthrough,
    "cycles": _exec_cycles,
    "flagged": _exec_flagged,
    "compare_status": _exec_compare_status,
    "currency": _exec_currency,
    "model_features": _exec_model_features,
    "period_compare": _exec_period_compare,
    "missing_fields": _exec_missing_fields,
    "chart": _exec_chart,
    "records": _exec_records,
    "report": _exec_report,
    "forecast": _exec_forecast,
    "top_categories": _exec_top_categories,
}
