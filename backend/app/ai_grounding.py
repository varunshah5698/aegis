"""Grounding: turn persisted analysis results into compact evidence bundles.

The LLM is allowed to *narrate*; it is never allowed to compute. Every number
that reaches a prompt is produced here from deterministic results (the run
manifest, quality report, schema and dataset rows), and the same bundle is
echoed back to the browser so a reader can check the model's wording against
the underlying values.
"""
from __future__ import annotations

from typing import Any


def _round(value: Any, digits: int = 4) -> Any:
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return value


def run_evidence(manifest: dict) -> dict:
    """Evidence bundle for one completed analysis run."""
    overview = manifest.get("overview") or {}
    quality = manifest.get("quality") or {}
    findings = ((manifest.get("findings") or {}).get("key_findings") or [])
    financial = manifest.get("financial") or {}
    modules = financial.get("modules") or {}
    patterns = modules.get("patterns") or {}
    network = modules.get("network") or {}
    ml = manifest.get("ml") or {}
    anomaly = ml.get("anomaly") or {}
    supervised = ml.get("supervised") or {}
    forecast = manifest.get("forecast") or {}
    columns = manifest.get("columns") or []

    evidence: dict[str, Any] = {
        "dataset": {
            "filename": manifest.get("filename"),
            "rows": overview.get("row_count"),
            "columns": overview.get("column_count"),
            "numeric_columns": overview.get("numeric_columns"),
            "categorical_columns": overview.get("categorical_columns"),
            "datetime_columns": overview.get("datetime_columns"),
            "missing_pct": overview.get("missing_pct"),
            "duplicate_pct": overview.get("duplicate_pct"),
            "time_coverage": overview.get("time_coverage"),
        },
        "analysis": {
            "modules_active": [m["key"] for m in manifest.get("modules", [])
                               if m.get("state") == "active"],
            "analysis_version": manifest.get("analysis_version"),
            "warnings": (manifest.get("warnings") or [])[:8],
            "limitations": (manifest.get("limitations") or [])[:8],
        },
        "quality": {
            "score": quality.get("score"),
            "grade": quality.get("grade"),
            "summary": (quality.get("summary") or [])[:6],
            "missing_columns": [
                {"column": c.get("column"), "missing_pct": c.get("missing_pct")}
                for c in ((quality.get("missing") or {}).get("columns_with_missing") or [])[:8]
            ],
        },
        "detections": [
            {
                "kind": f.get("kind"),
                "severity": f.get("severity"),
                "title": f.get("title"),
                "evidence": f.get("evidence"),
                "method": f.get("method"),
                "rows": f.get("row_count"),
                "confidence": f.get("confidence"),
                "false_positive_note": f.get("false_positive_note"),
                "next_steps": f.get("next_steps"),
            }
            for f in (patterns.get("findings") or [])[:12]
        ],
        "detection_totals": {
            "total": patterns.get("total"),
            "by_severity": _severity_counts(patterns.get("findings") or []),
        },
        "network": {
            "entities": network.get("node_count"),
            "links": network.get("edge_count"),
            "top_entities": [
                {"label": n.get("label"), "in_value": _round(n.get("in_value"), 2),
                 "out_value": _round(n.get("out_value"), 2),
                 "pagerank": _round(n.get("pagerank"), 5)}
                for n in sorted(network.get("nodes") or [],
                                key=lambda n: -(n.get("in_value", 0) + n.get("out_value", 0)))[:8]
            ] if network.get("status") == "completed" else [],
        },
        "machine_learning": {
            "anomaly_method": anomaly.get("method"),
            "anomaly_status": anomaly.get("status"),
            "anomalies_flagged": ((anomaly.get("metrics") or {}).get("flagged")
                                  if anomaly.get("metrics") else None),
            "top_anomalies": [
                {"row_index": a.get("row_index"), "score": _round(a.get("score"), 5),
                 "reasons": [(r.get("feature"), _round(r.get("value"), 3),
                              _round(r.get("deviation_sigma"), 2))
                             for r in (a.get("reasons") or [])[:3]]}
                for a in (anomaly.get("anomalies") or [])[:6]
            ],
            "supervised": {
                "task": supervised.get("task"),
                "best_model": supervised.get("best_model"),
                "metrics": {k: _round(v) for k, v in (supervised.get("metrics") or {}).items()
                            if isinstance(v, (int, float))},
                "top_features": [
                    {"feature": f.get("feature"), "importance": _round(f.get("importance"))}
                    for f in (supervised.get("feature_importance") or [])[:8]
                ],
                "excluded_features": (supervised.get("excluded_features") or [])[:10],
                "limitations": (supervised.get("limitations") or [])[:4],
            },
        },
        "forecast": {
            "status": forecast.get("status"),
            "target": forecast.get("target"),
            "method": forecast.get("method"),
            "mae": _round(forecast.get("mae"), 3),
            "rmse": _round(forecast.get("rmse"), 3),
            "mape_pct": _round(forecast.get("mape_pct"), 3),
            "next_points": [{"t": p.get("t"), "forecast": _round(p.get("forecast"), 2)}
                            for p in (forecast.get("future") or [])[:7]],
        },
        "key_findings": [
            {"category": f.get("category"), "title": f.get("title"),
             "detail": (f.get("detail") or "")[:400], "evidence": (f.get("evidence") or "")[:300]}
            for f in findings[:10]
        ],
        "column_semantics": [
            {"name": c.get("name"), "semantic_type": c.get("semantic_type"),
             "physical_type": c.get("physical_type")}
            for c in columns[:40]
        ],
    }
    return evidence


#: Which computed slices each workspace module may narrate. Keeping the slice
#: small keeps the prompt focused and makes it obvious what the model could see.
SECTIONS: dict[str, list[str]] = {
    "overview": ["dataset", "analysis", "key_findings", "detection_totals"],
    "quality": ["dataset", "quality"],
    "schema": ["column_semantics", "analysis"],
    "exploration": ["dataset", "charts"],
    "relationships": ["dataset", "relationships"],
    "machine_learning": ["dataset", "machine_learning"],
    "anomaly": ["dataset", "machine_learning"],
    "forecast": ["dataset", "forecast"],
    "financial": ["dataset", "detections", "detection_totals"],
    "network": ["dataset", "network"],
    "records": ["dataset", "quality", "detection_totals"],
}


def section_evidence(manifest: dict, section: str) -> dict:
    """Evidence bundle for one workspace module.

    Only the computed results that module actually renders are included, so a
    narration can never lean on findings from a tab the reader is not looking at.
    """
    if section not in SECTIONS:
        raise KeyError(section)
    full = run_evidence(manifest)
    full["charts"] = [
        {"id": c.get("id"), "type": c.get("type"), "title": c.get("title"),
         "x": c.get("x"), "y": c.get("y"), "points": len(c.get("data") or [])}
        for c in (manifest.get("charts") or [])[:24]
    ]
    rel = manifest.get("relationships") or {}
    full["relationships"] = {
        "columns_compared": len(rel.get("labels") or []),
        "strong_pairs": [
            {"a": p.get("a"), "b": p.get("b"), "pearson": _round(p.get("pearson"), 3),
             "spearman": _round(p.get("spearman"), 3), "strength": p.get("strength"),
             "method": p.get("method"), "p_value": _round(p.get("p_value"), 6)}
            for p in (rel.get("strong_pairs") or [])[:12]
        ],
        "note": rel.get("note") or rel.get("summary"),
    }
    evidence = {key: full[key] for key in SECTIONS[section] if key in full}
    evidence["section"] = section
    return evidence


def _severity_counts(findings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        key = str(f.get("severity") or "info").lower()
        counts[key] = counts.get(key, 0) + 1
    return counts


def finding_evidence(manifest: dict, finding: dict) -> dict:
    """Evidence for explaining one detection or alert."""
    return {
        "dataset": {
            "filename": manifest.get("filename"),
            "rows": (manifest.get("overview") or {}).get("row_count"),
            "columns": (manifest.get("overview") or {}).get("column_count"),
        },
        "finding": {
            "kind": finding.get("kind"),
            "title": finding.get("title"),
            "severity": finding.get("severity"),
            "entity": finding.get("entity"),
            "evidence": finding.get("evidence"),
            "method": finding.get("method"),
            "thresholds": finding.get("thresholds"),
            "time_range": finding.get("time_range"),
            "row_count": finding.get("row_count"),
            "confidence": finding.get("confidence"),
            "false_positive_note": finding.get("false_positive_note"),
            "next_steps": finding.get("next_steps"),
            "examples": _bounded_examples(finding.get("examples")),
        },
        "disclaimer": ("Findings are statistical review candidates produced by "
                       "deterministic detectors; they are not proof of wrongdoing."),
    }


def _bounded_examples(examples: Any, limit: int = 5) -> list[dict]:
    out: list[dict] = []
    for row in list(examples or [])[:limit]:
        if isinstance(row, dict):
            out.append({k: row[k] for k in list(row)[:8]})
        else:
            out.append({"value": str(row)[:80]})
    return out


def dataset_evidence(dataset: Any, schema: dict | None, quality: dict | None) -> dict:
    """Evidence for a dataset that has no completed analysis yet."""
    return {
        "dataset": {
            "filename": getattr(dataset, "original_filename", None),
            "rows": getattr(dataset, "row_count", None),
            "columns": getattr(dataset, "column_count", None),
            "size_bytes": getattr(dataset, "size_bytes", None),
            "validation_status": getattr(dataset, "validation_status", None),
            "validation_messages": (getattr(dataset, "validation_messages", None) or [])[:5],
        },
        "schema": {
            "columns": [
                {"name": c.get("name"), "semantic_type": c.get("semantic_type"),
                 "physical_type": c.get("physical_type"),
                 "null_pct": c.get("null_pct"),
                 "unique_count": c.get("unique_count")}
                for c in ((schema or {}).get("columns") or [])[:40]
            ],
            "warnings": ((schema or {}).get("warnings") or [])[:6],
        },
        "quality": {
            "score": (quality or {}).get("score"),
            "grade": (quality or {}).get("grade"),
            "summary": ((quality or {}).get("summary") or [])[:6],
        },
    }


def workspace_evidence(overview: dict, datasets: list[dict]) -> dict:
    """Evidence for the catalog/dashboard level summary."""
    return {
        "workspace": {
            "datasets": overview.get("datasets"),
            "runs_total": overview.get("runs_total"),
            "runs_by_status": overview.get("runs_by_status"),
            "upcoming_bookings": overview.get("upcoming_bookings"),
            "recent_orders": overview.get("recent_orders"),
        },
        "catalog": [
            {"filename": d.get("filename"), "rows": d.get("row_count"),
             "columns": d.get("column_count"),
             "validation_status": d.get("validation_status"),
             "latest_run_status": ((d.get("runs") or [{}])[0] or {}).get("status")}
            for d in (datasets or [])[:25]
        ],
    }
