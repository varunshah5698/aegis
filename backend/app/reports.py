"""Report generation (spec #16).

Reports are rendered strictly from the persisted manifest (real computed
results). No placeholder text, no fabricated metrics.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import config


def build_reports(manifest: dict, ctx: dict, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    written: dict[str, Path] = {}

    executive = _executive(manifest)
    technical = _technical(manifest)
    investigation = _investigation(manifest)

    for kind, doc in (("executive", executive), ("technical", technical),
                      ("investigation", investigation)):
        p = out_dir / f"{kind}_report_{ts}.md"
        p.write_text(_render_markdown(doc), encoding="utf-8")
        written[kind] = p
        jp = out_dir / f"{kind}_report_{ts}.json"
        jp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
        written[f"{kind}_json"] = jp

    # findings + stats CSV exports
    findings_csv = out_dir / f"findings_{ts}.csv"
    _write_findings_csv(manifest, findings_csv)
    written["findings_csv"] = findings_csv

    stats_csv = out_dir / f"descriptive_stats_{ts}.csv"
    _write_stats_csv(manifest, stats_csv)
    written["stats_csv"] = stats_csv

    # XLSX workbook (multi-sheet) when openpyxl is available
    try:
        xlsx = out_dir / f"analysis_workbook_{ts}.xlsx"
        _write_xlsx(manifest, xlsx)
        written["workbook_xlsx"] = xlsx
    except Exception:
        pass

    return written


# ------------------------------------------------------------ documents -----
def _executive(m: dict) -> dict:
    ov = m.get("overview", {}) or {}
    q = m.get("quality") or {}
    findings = (m.get("findings") or {}).get("key_findings", [])
    fin = (m.get("financial") or {}).get("modules") or {}
    summary = fin.get("summary") or {}

    sections = [
        {"heading": "Dataset overview", "lines": [
            f"File: {m.get('filename', '—')}",
            f"Rows: {ov.get('row_count', '—'):,} · Columns: {ov.get('column_count', '—')}"
            if isinstance(ov.get("row_count"), int) else "Rows: —",
            f"Missing cells: {ov.get('missing_pct', '—')}% · Duplicate rows: {ov.get('duplicate_pct', '—')}%",
            f"Time coverage: {_time_coverage(ov)}",
            f"Processing: {ov.get('processing_seconds', '—')}s"
            + (" (sampled)" if ov.get("sampled") else ""),
        ]},
        {"heading": "Data quality findings", "lines": (
            [f"Score {q.get('score')}/100 (grade {q.get('grade')})"] +
            list(q.get("summary", [])) +
            [f"Recommended: {r['action']} — {r['reason']}"
             for r in q.get("recommendations", [])[:5]])},
        {"heading": "Most important insights", "lines": [
            f"[{f.get('kind', 'observed')}] {f['title']} — {f.get('detail', '')}"
            for f in findings[:12]]},
    ]

    if summary.get("metrics"):
        mm = summary["metrics"]
        sections.append({"heading": "Transaction flow summary", "lines": [
            f"Completed: {mm.get('completed_count', 0):,} · Failed: {mm.get('failed_count', 0):,}"
            f" · Pending: {mm.get('pending_count', 0):,}",
            f"Completed volume (native currency): {mm.get('total_volume_completed')}",
            f"Median amount: {mm.get('median_amount_completed')} · "
            f"Largest: {mm.get('largest_transaction')}",
            f"Failure rate: {mm.get('failure_rate_pct')}% · "
            f"Reversals: {mm.get('reversal_count', 0):,} · Refunds: {mm.get('refund_count', 0):,}",
            *summary.get("calc_policy", []),
        ] + list(summary.get("warnings", []))})

    patterns = fin.get("patterns") or {}
    if patterns.get("findings"):
        sections.append({"heading": "Potential anomalies requiring review", "lines": [
            f"[{f['severity']}] {f['title']} — {f['evidence']}"
            for f in patterns["findings"][:8]] + [patterns.get("disclaimer", "")]})

    sections.append({"heading": "Recommended investigative steps", "lines": _next_steps(m)})
    sections.append({"heading": "Analysis provenance", "lines": [
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Analysis version: {m.get('analysis_version')} · "
        f"Dataset version: {m.get('dataset_version')}",
        *[f"Limitation: {x}" for x in m.get("limitations", [])],
    ]})
    return {"title": f"{config.BRAND['name']} — Executive Report",
            "subtitle": m.get("filename", ""), "sections": sections}


def _technical(m: dict) -> dict:
    cols = m.get("columns", [])
    ml = m.get("ml", {}) or {}
    sup = ml.get("supervised") or {}
    rel = m.get("relationships") or {}
    q = m.get("quality") or {}

    mapping_rows = [
        f"{c['name']} → {c['semantic_type']} (confidence {c['semantic_confidence']}) "
        f"{'[override: ' + str(c.get('user_override')) + ']' if c.get('user_override') else ''} "
        f"— {c['reason']}"
        for c in cols[:60]]

    sections = [
        {"heading": "Schema mapping", "lines": mapping_rows},
        {"heading": "Data preparation", "lines": [
            f"Transformations applied: {len((m.get('cleaning') or {}).get('operations', []))}",
            *[f"{op.get('op')}: affected {op.get('affected', 0)}"
              for op in (m.get("cleaning") or {}).get("operations", [])],
            "Original upload preserved unchanged as an immutable artifact.",
        ]},
        {"heading": "Statistical methods", "lines": [
            "Descriptive statistics: exact (numpy/pandas) on "
            + ("a sample" if (m.get("overview") or {}).get("sampled") else "all rows"),
            f"Correlations: Pearson and Spearman with min_periods=10; "
            f"{len(rel.get('strong_pairs', []))} pairs with |r| ≥ 0.3",
            f"Categorical association: bias-corrected Cramér's V",
            f"Mutual information: 10-bin discretization vs first low-cardinality column",
            rel.get("note", ""),
        ]},
        {"heading": "Model selection rationale", "lines": [
            f"Task: {sup.get('task', '—')} · Target: {sup.get('target') or 'none'}",
            f"Split: {sup.get('split_strategy', '—')}",
            f"Train/test: {sup.get('train_size', 0):,}/{sup.get('test_size', 0):,}",
            f"Candidates tried: "
            + ", ".join(f"{x.get('model')} ({'ok' if 'error' not in x else 'failed'})"
                        for x in sup.get("models_tried", [])),
            f"Excluded from features (leakage control): "
            + ", ".join(sup.get("excluded_features", [])[:20]),
        ]},
        {"heading": "Performance metrics", "lines": [
            f"{k}: {v}" for k, v in (sup.get("metrics") or {}).items()] + [
            f"Baseline: {k}={v}" for k, v in (sup.get("baselines") or {}).items()],
        },
        {"heading": "Explainability", "lines": [
            f"{f['feature']}: {f['importance']}"
            for f in sup.get("feature_importance", [])[:15]]
            or ["No model-native importances available for the selected model."]},
        {"heading": "Processing configuration", "lines": [
            f"Capabilities activated: "
            + ", ".join(x["key"] for x in m.get("modules", []) if x["state"] == "active"),
            f"Module states: " + "; ".join(
                f"{x['key']}={x['state']}" for x in m.get("modules", [])),
        ]},
        {"heading": "Warnings and limitations", "lines": (
            list(m.get("warnings", []))[:10] + list(m.get("limitations", [])))},
        {"heading": "Reproducibility", "lines": [
            f"Dataset version: {m.get('dataset_version')}",
            f"Random seed: {42} (fixed across training, sampling and clustering)",
            f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        ]},
    ]
    return {"title": f"{config.BRAND['name']} — Technical Report",
            "subtitle": m.get("filename", ""), "sections": sections}


def _investigation(m: dict) -> dict:
    fin = (m.get("financial") or {}).get("modules") or {}
    patterns = fin.get("patterns") or {}
    net = fin.get("network") or {}
    recon = fin.get("reconciliation") or {}
    findings = patterns.get("findings", [])

    sections = [
        {"heading": "Scope and caveats", "lines": [
            f"Dataset: {m.get('filename')}",
            patterns.get("disclaimer", ""),
            "This report documents potential anomalies for human review; it is not "
            "an accusation or a legal determination.",
        ]},
        {"heading": "Entities of interest", "lines": [
            f"{f['title']} — entity {f['entity']}, {f['row_count']} related rows"
            for f in findings[:20]] or ["No pattern triggered on this dataset."]},
        {"heading": "Trigger evidence and methods", "lines": [
            f"[{f['kind']}] {f['title']}\n    method: {f['method']}\n"
            f"    evidence: {f['evidence']}\n"
            f"    thresholds: {json.dumps(f['thresholds'])}\n"
            f"    confidence: {f['confidence']} · limitations: {f['false_positive_note']}\n"
            f"    next: {f['next_steps']}"
            for f in findings[:20]]},
        {"heading": "Transfer paths", "lines": [
            f"Network: {net.get('node_count', 0):,} entities / "
            f"{net.get('edge_count', 0):,} aggregated flows, total value "
            f"{net.get('total_value')}",
            *[f"{e['source']} → {e['target']}: value {e['value']} across {e['count']} txns"
              for e in sorted(net.get("edges", []), key=lambda x: -x["value"])[:20]],
            *net.get("warnings", []),
        ]},
        {"heading": "Reconciliation status", "lines": (
            [f"Columns examined: {', '.join(recon.get('columns', []))}"] +
            [f"{k}: {json.dumps(v)}" for k, v in recon.get("comparison", {}).items()] +
            ([recon["reason"]] if recon.get("reason") else []))},
        {"heading": "Amounts and calculation methodology", "lines": (
            ((fin.get("summary") or {}).get("calc_policy", [])) or
            ["No amount column identified; monetary calculations were skipped."])},
        {"heading": "Analyst notes and review status", "lines": [
            "Review status: OPEN — awaiting analyst sign-off.",
            "Add notes in the workspace investigation panel; they are stored with the case.",
        ]},
    ]
    return {"title": f"{config.BRAND['name']} — Financial Investigation Report",
            "subtitle": m.get("filename", ""), "sections": sections}


# ------------------------------------------------------------- renderers ----
def _time_coverage(ov: dict) -> str:
    tc = ov.get("time_coverage")
    if not tc:
        return "no time column"
    return f"{tc.get('start')} → {tc.get('end')} ({tc.get('span_days')} days)"


def _next_steps(m: dict) -> list[str]:
    steps: list[str] = []
    q = m.get("quality") or {}
    for r in q.get("recommendations", [])[:3]:
        steps.append(f"{r['action']}: {r['reason']}")
    fin = (m.get("financial") or {}).get("modules") or {}
    for f in (fin.get("patterns") or {}).get("findings", [])[:3]:
        steps.append(f"{f['title']} → {f['next_steps']}")
    if not steps:
        steps.append("No action required — no anomaly crossed the reporting thresholds.")
    return steps


def _render_markdown(doc: dict) -> str:
    lines = [f"# {doc['title']}", f"_{doc['subtitle']}_", ""]
    for sec in doc["sections"]:
        lines.append(f"## {sec['heading']}")
        for item in sec["lines"]:
            if not item:
                continue
            for sub in str(item).split("\n"):
                lines.append(f"- {sub}" if not sub.startswith(" ") else f"  {sub.strip()}")
        lines.append("")
    return "\n".join(lines)


def _write_findings_csv(m: dict, path: Path) -> None:
    findings = (m.get("findings") or {}).get("key_findings", [])
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["category", "title", "detail", "kind", "evidence"])
        w.writeheader()
        for f in findings:
            w.writerow({k: f.get(k, "") for k in w.fieldnames})
    if not findings:
        path.write_text("category,title,detail,kind,evidence\n", encoding="utf-8")


def _write_stats_csv(m: dict, path: Path) -> None:
    stats = m.get("stats", {}) or {}
    numeric = stats.get("numeric", [])
    fields = ["column", "count", "mean", "median", "std", "min", "max", "sum",
              "q1", "q3", "skewness", "kurtosis", "missing"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in numeric:
            w.writerow(row)
    if not numeric:
        path.write_text(",".join(fields) + "\n", encoding="utf-8")


def _write_xlsx(m: dict, path: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    # overview sheet
    ws = wb.active
    ws.title = "overview"
    ov = m.get("overview", {}) or {}
    ws.append(["metric", "value"])
    for k, v in ov.items():
        ws.append([k, json.dumps(v) if isinstance(v, (dict, list)) else v])

    ws2 = wb.create_sheet("descriptive_stats")
    numeric = (m.get("stats", {}) or {}).get("numeric", [])
    if numeric:
        headers = list(numeric[0].keys())
        ws2.append(headers)
        for row in numeric:
            ws2.append([row.get(h) for h in headers])

    ws3 = wb.create_sheet("findings")
    ws3.append(["category", "title", "kind", "detail"])
    for f in (m.get("findings") or {}).get("key_findings", []):
        ws3.append([f.get("category"), f.get("title"), f.get("kind"), f.get("detail")])

    ws4 = wb.create_sheet("columns")
    ws4.append(["column", "physical_type", "semantic_type", "confidence",
                "null_pct", "unique", "reason"])
    for c in m.get("columns", []):
        ws4.append([c["name"], c["physical_type"], c["semantic_type"],
                    c["semantic_confidence"], c["null_pct"], c["unique_count"], c["reason"]])

    ws5 = wb.create_sheet("anomalies")
    ws5.append(["kind", "title", "severity", "entity", "evidence", "method"])
    fin = (m.get("financial") or {}).get("modules") or {}
    for f in (fin.get("patterns") or {}).get("findings", []):
        ws5.append([f["kind"], f["title"], f["severity"], f["entity"],
                    f["evidence"], f["method"]])
    wb.save(path)


def list_report_files(run_artifact_dir: str) -> list[dict]:
    d = Path(run_artifact_dir)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*report*")) + sorted(d.glob("*_report_*")):
        if p.is_file() and p not in [x for x in []]:
            out.append({"name": p.name, "size": p.stat().st_size, "path": str(p)})
    for p in sorted(d.glob("*.xlsx")) + sorted(d.glob("findings_*.csv")) + \
            sorted(d.glob("descriptive_stats_*.csv")):
        out.append({"name": p.name, "size": p.stat().st_size, "path": str(p)})
    seen = set()
    uniq = []
    for item in out:
        if item["name"] in seen:
            continue
        seen.add(item["name"])
        uniq.append(item)
    return uniq
