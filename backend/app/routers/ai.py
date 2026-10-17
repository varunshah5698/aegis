"""AI routes — grounded narration over computed analysis results.

Every endpoint follows the same contract:

1. deterministic code loads/derives the facts (never the model),
2. the facts are sent to the model as EVIDENCE with strict grounding rules,
3. the response is validated (JSON schema where structured) and returned
   alongside the evidence it was allowed to use, plus a provenance note.

If the provider fails, the endpoint returns a typed error and the deterministic
answer is still available to the UI — a failure is never papered over with an
invented model response.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .. import ai, ai_grounding, assistant
from ..database import get_db
from ..models import AnalysisRun, AuditEvent, Dataset
from ..pipeline import load_frame_for_run
from ..routers.auth import current_user
from ..security import get_session_user

router = APIRouter(prefix="/api/ai", tags=["ai"])

MAX_QUESTION_CHARS = 600
MAX_HISTORY_TURNS = 8


# ----------------------------------------------------------------- buckets --
class _Bucket:
    """Very small in-process limiter: N AI calls per user per minute."""

    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < 60]
            if len(hits) >= self.per_minute:
                self._hits[key] = hits
                return 60 - (now - hits[0])
            hits.append(now)
            self._hits[key] = hits
            return 0.0


limiter = _Bucket(20)


def _throttle(request: Request, user) -> None:
    from .. import config

    limiter.per_minute = config.AI_RATE_LIMIT_PER_MINUTE
    key = user.id if user else (request.client.host if request.client else "anon")
    wait = limiter.check(key)
    if wait > 0:
        raise HTTPException(429, f"Too many AI requests. Try again in {int(wait) + 1}s.",
                            headers={"Retry-After": str(int(wait) + 1)})


def _run_for(run_id: str, request: Request, db) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    user = get_session_user(db, request.cookies.get("finsentry_session"))
    if user is not None:
        if run.user_id not in (None, user.id):
            raise HTTPException(403, "Not authorized for this run.")
    elif run.user_id is not None:
        raise HTTPException(403, "Not authorized for this run.")
    return run


def _manifest(run: AnalysisRun) -> dict:
    if not run.manifest_path or not Path(run.manifest_path).exists():
        raise HTTPException(409, f"Analysis not finished yet (status: {run.status}). "
                                 "AI narration needs completed results.")
    return json.loads(Path(run.manifest_path).read_text(encoding="utf-8"))


def _provider_error(exc: ai.AiError, action: str) -> HTTPException:
    return HTTPException(exc.status_code, str(exc), headers={"X-AI-Error": exc.code})


def _note(model: str, latency_ms: int, extra: str = "") -> str:
    base = ("Narration by the language model over values computed by the analysis "
            f"engine ({model}, {latency_ms} ms). The model does not compute metrics.")
    return f"{base} {extra}".strip()


def _audit(db, user, action: str, run_id: str = "", detail: dict | None = None) -> None:
    db.add(AuditEvent(user_id=getattr(user, "id", None), action=action,
                      resource_type="run" if run_id else "ai",
                      resource_id=run_id, detail=detail or {}))
    db.commit()


# ------------------------------------------------------------------ status --
@router.get("/status")
def ai_status(user=Depends(current_user)):
    """Configuration/health snapshot. Never includes the key."""
    info = ai.status()
    info["features"] = ["insights", "summary", "explain", "ask", "narrate",
                        "section", "dataset-insights", "workspace-summary"]
    return info


# ---------------------------------------------------------------- insights --
INSIGHTS_SCHEMA = {
    "type": "object",
    "required": ["headline", "summary", "insights"],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["title", "detail"],
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "severity": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


class RunPayload(BaseModel):
    run_id: str = Field(min_length=4, max_length=64)


@router.post("/insights")
def insights(payload: RunPayload, request: Request, db=Depends(get_db),
             user=Depends(current_user)):
    """Graphical-dashboard companion: 3–6 grounded insight cards."""
    _throttle(request, user)
    run = _run_for(payload.run_id, request, db)
    evidence = ai_grounding.run_evidence(_manifest(run))
    user_prompt = (
        "EVIDENCE (computed by the analysis engine — the only permitted source of facts):\n"
        f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
        "TASK: Write an analyst briefing for this dataset.\n"
        "- headline: one sentence naming the single most important thing.\n"
        "- summary: 2–3 sentences on what the data shows.\n"
        "- insights: 3 to 6 cards. Each needs a short title, a detail sentence that "
        "cites the specific computed value it rests on (include the number), an "
        "optional severity from {info, low, medium, high, critical}, and the exact "
        "computed evidence string you relied on.\n"
        "- limitations: up to 3 short caveats grounded in the evidence's own "
        "limitations or warnings.\n"
        "If a detector found nothing, say so plainly — an empty result is a result."
    )
    try:
        completion = ai.complete(system=ai.GROUNDING_RULES, user=user_prompt,
                                 json_schema=INSIGHTS_SCHEMA, max_tokens=1100)
    except ai.AiError as exc:
        _audit(db, user, "ai.insights_failed", run.id, {"code": exc.code})
        raise _provider_error(exc, "insights")
    data = completion.data or {}
    unsupported = ai.unsupported_numbers(json.dumps(data, default=str), evidence)
    _audit(db, user, "ai.insights", run.id,
           {"model": completion.model, "unsupported_numbers": len(unsupported)})
    return {
        "run_id": run.id,
        "model": completion.model,
        "latency_ms": completion.latency_ms,
        "truncated": completion.truncated,
        **data,
        "evidence": evidence,
        "provenance": _note(completion.model, completion.latency_ms,
                            f"Unverified numbers in the text: {len(unsupported)}."),
        "unsupported_numbers": unsupported,
    }


# ----------------------------------------------------------------- summary --
SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["headline", "summary", "priorities"],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "priorities": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


@router.post("/summary")
def summary(payload: RunPayload, request: Request, db=Depends(get_db),
            user=Depends(current_user)):
    """Executive summary of a finished analysis, grounded in its own numbers."""
    _throttle(request, user)
    run = _run_for(payload.run_id, request, db)
    evidence = ai_grounding.run_evidence(_manifest(run))
    user_prompt = (
        "EVIDENCE:\n"
        f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
        "TASK: executive summary for a compliance reviewer.\n"
        "- headline: the finding that deserves attention first, with its number.\n"
        "- summary: 3–4 sentences tying data quality, detections and model signals "
        "together, using only evidence values.\n"
        "- priorities: 3 to 5 concrete next actions, each naming the evidence "
        "(finding title or metric) that motivates it.\n"
        "- limitations: up to 3 caveats drawn from the evidence.\n"
        "Never imply guilt; these are review candidates."
    )
    try:
        completion = ai.complete(system=ai.GROUNDING_RULES, user=user_prompt,
                                 json_schema=SUMMARY_SCHEMA, max_tokens=900)
    except ai.AiError as exc:
        _audit(db, user, "ai.summary_failed", run.id, {"code": exc.code})
        raise _provider_error(exc, "summary")
    data = completion.data or {}
    unsupported = ai.unsupported_numbers(json.dumps(data, default=str), evidence)
    _audit(db, user, "ai.summary", run.id, {"model": completion.model})
    return {"run_id": run.id, "model": completion.model,
            "latency_ms": completion.latency_ms, **data, "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms),
            "unsupported_numbers": unsupported}


# ----------------------------------------------------------------- explain --
EXPLAIN_SCHEMA = {
    "type": "object",
    "required": ["explanation", "why_it_matters", "next_steps"],
    "properties": {
        "explanation": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "false_positive_check": {"type": "string"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


class ExplainPayload(RunPayload):
    finding_index: int = Field(default=0, ge=0, le=200)
    big_row: bool = False


@router.post("/explain")
def explain(payload: ExplainPayload, request: Request, db=Depends(get_db),
            user=Depends(current_user)):
    """Explain one detection or alert using only its stored evidence."""
    _throttle(request, user)
    run = _run_for(payload.run_id, request, db)
    manifest = _manifest(run)
    findings = (((manifest.get("financial") or {}).get("modules") or {})
                .get("patterns") or {}).get("findings") or []
    if not findings:
        raise HTTPException(404, "This run produced no detections to explain.")
    if payload.finding_index >= len(findings):
        raise HTTPException(404, f"Detection #{payload.finding_index} does not exist "
                                 f"(this run has {len(findings)}).")
    finding = findings[payload.finding_index]
    evidence = ai_grounding.finding_evidence(manifest, finding)
    user_prompt = (
        "EVIDENCE for a single detection:\n"
        f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
        "TASK: explain this detection to an analyst.\n"
        "- explanation: what the detector observed and why it triggered, citing the "
        "threshold and row count from the evidence.\n"
        "- why_it_matters: the risk pattern this could represent, phrased as a "
        "hypothesis to check.\n"
        "- next_steps: 2–4 specific checks, each referencing a field or value in "
        "the evidence.\n"
        "- false_positive_check: how this could be legitimate.\n"
        "- limitations: up to 2 caveats.\n"
        "Do not assert that fraud occurred."
    )
    try:
        completion = ai.complete(system=ai.GROUNDING_RULES, user=user_prompt,
                                 json_schema=EXPLAIN_SCHEMA, max_tokens=800)
    except ai.AiError as exc:
        _audit(db, user, "ai.explain_failed", run.id, {"code": exc.code})
        raise _provider_error(exc, "explain")
    data = completion.data or {}
    unsupported = ai.unsupported_numbers(json.dumps(data, default=str), evidence)
    _audit(db, user, "ai.explain", run.id,
           {"model": completion.model, "kind": finding.get("kind")})
    return {"run_id": run.id, "model": completion.model,
            "latency_ms": completion.latency_ms,
            "finding": {"kind": finding.get("kind"), "title": finding.get("title"),
                        "severity": finding.get("severity")},
            **data,
            "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms),
            "unsupported_numbers": unsupported}


# --------------------------------------------------------------------- ask --
class AskPayload(RunPayload):
    question: str = Field(min_length=2, max_length=MAX_QUESTION_CHARS)
    history: list[dict] = Field(default_factory=list)


@router.post("/ask")
def ask(payload: AskPayload, request: Request, db=Depends(get_db),
        user=Depends(current_user)):
    """Grounded Q&A: deterministic facts first, then model narration.

    The deterministic answer is always present in the response, so a provider
    outage degrades the wording, never the substance.
    """
    _throttle(request, user)
    run = _run_for(payload.run_id, request, db)
    manifest = _manifest(run)

    frame_cache: dict = {}

    def load():
        if "df" not in frame_cache:
            frame_cache["df"] = load_frame_for_run(run)
        return frame_cache["df"]

    facts = assistant.answer(payload.question, manifest, load)
    evidence = {
        "question": payload.question,
        "computed_topic": facts.get("topic"),
        "computed_answer": facts.get("answer"),
        "computed_data": _bounded(facts.get("data")),
        "computed_limitations": facts.get("limitations"),
        "analysis_context": {
            "filename": manifest.get("filename"),
            "rows": (manifest.get("overview") or {}).get("row_count"),
            "quality_score": (manifest.get("quality") or {}).get("score"),
            "detection_count": len((((manifest.get("financial") or {}).get("modules")
                                     or {}).get("patterns") or {}).get("findings") or []),
        },
        "conversation_so_far": [
            {"role": str(t.get("role"))[:12], "text": str(t.get("text"))[:400]}
            for t in (payload.history or [])[-MAX_HISTORY_TURNS:]
            if isinstance(t, dict)
        ],
    }
    notes = ""
    completion = None
    try:
        completion = ai.complete(
            system=ai.GROUNDING_RULES,
            user=(
                "EVIDENCE computed by the analysis engine for the analyst's question:\n"
                f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                "TASK: answer the analyst's question in at most four sentences using only "
                "the computed answer and data above. Keep every figure identical to the "
                "computed values. If the computed answer says the question could not be "
                "mapped or the data is unavailable, say so and name what is missing. "
                "Plain prose, no headings."
            ),
            max_tokens=420,
            temperature=0.15,
        )
    except ai.AiError as exc:
        notes = f"Model narration unavailable ({exc.code}). Showing computed results."
        _audit(db, user, "ai.ask_degraded", run.id, {"code": exc.code})

    if completion is not None:
        unsupported = ai.unsupported_numbers(completion.text, evidence)
        _audit(db, user, "ai.ask", run.id,
               {"model": completion.model, "topic": facts.get("topic")})
    else:
        unsupported = []

    return {
        "run_id": run.id,
        "question": facts.get("question"),
        "topic": facts.get("topic"),
        "confidence": facts.get("confidence"),
        "answer": facts.get("answer"),                 # deterministic, always
        "ai_answer": completion.text if completion else None,
        "model": completion.model if completion else None,
        "latency_ms": completion.latency_ms if completion else None,
        "llm_note": (_note(completion.model, completion.latency_ms,
                           f"Unverified numbers in the narration: {len(unsupported)}.")
                     if completion else notes),
        "data": facts.get("data"),
        "chart_hint": facts.get("chart_hint"),
        "scope": facts.get("scope"),
        "limitations": facts.get("limitations"),
        "follow_ups": facts.get("follow_ups"),
        "evidence": evidence,
        "unsupported_numbers": unsupported,
    }


def _bounded(value, limit: int = 6000):
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return None
    return value if len(text) <= limit else {"truncated": text[:limit]}


# ----------------------------------------------------------------- narrate --
NARRATE_SCHEMA = {
    "type": "object",
    "required": ["reading", "what_to_check"],
    "properties": {
        "reading": {"type": "string"},
        "what_to_check": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}


class NarratePayload(RunPayload):
    chart_id: str = Field(default="", max_length=80)
    chart_index: int = Field(default=0, ge=0, le=200)


@router.post("/narrate")
def narrate(payload: NarratePayload, request: Request, db=Depends(get_db),
            user=Depends(current_user)):
    """Explain a specific chart using the values already computed for it."""
    _throttle(request, user)
    run = _run_for(payload.run_id, request, db)
    manifest = _manifest(run)
    charts = manifest.get("charts") or []
    chart = next((c for c in charts if c.get("id") == payload.chart_id), None) \
        if payload.chart_id else None
    if chart is None:
        if payload.chart_index >= len(charts):
            raise HTTPException(404, "No chart available to describe on this run.")
        chart = charts[payload.chart_index]
    evidence = {
        "chart": {
            "id": chart.get("id"), "type": chart.get("type"),
            "title": chart.get("title"), "subtitle": chart.get("subtitle"),
            "x": chart.get("x"), "y": chart.get("y"), "series": chart.get("series"),
            "columns": chart.get("columns"), "note": chart.get("note"),
            "points": (chart.get("data") or [])[:30],
            "point_count": len(chart.get("data") or []),
        },
        "dataset": {
            "filename": manifest.get("filename"),
            "rows": (manifest.get("overview") or {}).get("row_count"),
        },
    }
    try:
        completion = ai.complete(
            system=ai.GROUNDING_RULES,
            user=("EVIDENCE for one chart:\n"
                  f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                  "TASK: - reading: 2–3 sentences on what this chart shows, citing the "
                  "actual point values or their range from the evidence.\n"
                  "- what_to_check: 2–3 follow-up checks.\n"
                  "- limitations: up to 2 caveats about reading this chart."),
            json_schema=NARRATE_SCHEMA, max_tokens=600, temperature=0.2)
    except ai.AiError as exc:
        _audit(db, user, "ai.narrate_failed", run.id, {"code": exc.code})
        raise _provider_error(exc, "narrate")
    data = completion.data or {}
    _audit(db, user, "ai.narrate", run.id, {"model": completion.model,
                                            "chart": chart.get("id")})
    return {"run_id": run.id, "model": completion.model,
            "latency_ms": completion.latency_ms,
            "chart": {"id": chart.get("id"), "title": chart.get("title")},
            **data, "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms)}


# ----------------------------------------------------------------- section --
SECTION_SCHEMA = {
    "type": "object",
    "required": ["headline", "reading", "watchouts"],
    "properties": {
        "headline": {"type": "string"},
        "reading": {"type": "string"},
        "watchouts": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
}

SECTION_TASKS: dict[str, str] = {
    "overview": "the dataset's shape, quality score and ranked findings",
    "quality": "the data-quality report: missingness, duplicates, invalid values, outliers",
    "schema": "the inferred column meanings and which modules they unlock",
    "exploration": "the generated charts and what each one plots",
    "relationships": "the statistically significant column relationships",
    "machine_learning": "the supervised model, its metrics and feature importances",
    "anomaly": "the unsupervised anomaly detection results and flagged rows",
    "forecast": "the time-series forecast, its backtest error and next points",
    "financial": "the financial-crime detectors and the findings they produced",
    "network": "the entity network, link counts and highest-value participants",
    "records": "the raw row counts behind the record browser",
}


class SectionPayload(RunPayload):
    section: str = Field(min_length=3, max_length=32)


@router.post("/section")
def section_analysis(payload: SectionPayload, request: Request, db=Depends(get_db),
                     user=Depends(current_user)):
    """Narrate one workspace module from that module's own computed values."""
    _throttle(request, user)
    section = payload.section.strip().lower()
    if section not in ai_grounding.SECTIONS:
        raise HTTPException(422, f"Unknown section '{payload.section}'. "
                                 f"Expected one of: {', '.join(ai_grounding.SECTIONS)}.")
    run = _run_for(payload.run_id, request, db)
    evidence = ai_grounding.section_evidence(_manifest(run), section)
    focus = SECTION_TASKS.get(section, section)
    try:
        completion = ai.complete(
            system=ai.GROUNDING_RULES,
            user=(
                f"EVIDENCE for one module of an analysis ({section} — {focus}):\n"
                f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                "TASK: explain this module's numbers to an analyst.\n"
                "- headline: one sentence stating the single most important "
                "value you can see, with that value quoted exactly.\n"
                "- reading: 2–3 sentences on what these numbers mean, citing the "
                "specific computed values (counts, percentages, metrics) that "
                "support each claim.\n"
                "- watchouts: 2–3 concrete things to check or treat with care, "
                "each tied to a value in the evidence.\n"
                "- limitations: up to 2 caveats about this module's own inputs.\n"
                "Only use values present in the evidence. If the module computed "
                "nothing, say so plainly instead of inventing results."
            ),
            json_schema=SECTION_SCHEMA, max_tokens=700, temperature=0.2)
    except ai.AiError as exc:
        _audit(db, user, "ai.section_failed", run.id,
               {"code": exc.code, "section": section})
        raise _provider_error(exc, f"section:{section}")
    data = completion.data or {}
    unsupported = ai.unsupported_numbers(json.dumps(data, default=str), evidence)
    _audit(db, user, "ai.section", run.id,
           {"model": completion.model, "section": section,
            "unsupported_numbers": len(unsupported)})
    return {"run_id": run.id, "section": section,
            "model": completion.model, "latency_ms": completion.latency_ms,
            "truncated": completion.truncated, **data,
            "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms),
            "unsupported_numbers": unsupported}


# -------------------------------------------------------------- dataset AI --
@router.post("/dataset-insights")
def dataset_insights(payload: RunPayload, request: Request, db=Depends(get_db),
                     user=Depends(current_user)):
    """Insights for a dataset that has no completed run yet (pre-analysis)."""
    _throttle(request, user)
    ds = db.get(Dataset, payload.run_id)          # reused field: dataset id
    if ds is None or ds.deleted_at is not None:
        raise HTTPException(404, "Dataset not found.")
    user_row = get_session_user(db, request.cookies.get("finsession_session"))
    if user_row is None:
        user_row = get_session_user(db, request.cookies.get("finsentry_session"))
    if ds.user_id not in (None, getattr(user_row, "id", None)):
        raise HTTPException(403, "Not authorized for this dataset.")

    from .. import data_quality, schema_inference
    from ..csv_io import read_csv

    raw = Path(ds.source_path).read_bytes()
    _, rows = read_csv(raw, ds.delimiter, ds.encoding)
    import pandas as pd
    frame = pd.DataFrame(rows)
    inference = schema_inference.infer_schema(frame)
    report = data_quality.assess_quality(frame, inference.columns, inference.semantic_map)
    evidence = ai_grounding.dataset_evidence(ds, inference.as_dict(), report.as_dict())
    try:
        completion = ai.complete(
            system=ai.GROUNDING_RULES,
            user=("EVIDENCE for an uploaded file that has not been analysed yet:\n"
                  f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                  "TASK: - headline: one sentence on what this file contains.\n"
                  "- summary: 2–3 sentences on its structure and any quality issue, "
                  "citing computed values.\n"
                  "- insights: 3 to 5 preparation notes (column types detected, "
                  "missing data, what analysis this file can and cannot support).\n"
                  "- limitations: up to 3 caveats.\n"
                  "Do not describe findings — no analysis has run yet."),
            json_schema=INSIGHTS_SCHEMA, max_tokens=900)
    except ai.AiError as exc:
        _audit(db, user, "ai.dataset_insights_failed", ds.id, {"code": exc.code})
        raise _provider_error(exc, "dataset-insights")
    data = completion.data or {}
    _audit(db, user, "ai.dataset_insights", ds.id, {"model": completion.model})
    return {"dataset_id": ds.id, "model": completion.model,
            "latency_ms": completion.latency_ms, **data, "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms)}


# ------------------------------------------------------------- workspace AI --
WORKSPACE_SCHEMA = {
    "type": "object",
    "required": ["headline", "summary", "focus"],
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "focus": {"type": "array", "items": {"type": "string"}},
    },
}


@router.post("/workspace-summary")
def workspace_summary(request: Request, db=Depends(get_db),
                      user=Depends(current_user)):
    """Where-should-I-look summary across the customer's whole workspace."""
    _throttle(request, user)
    datasets = list(db.scalars(select(Dataset)
                               .where(Dataset.user_id == user.id,
                                      Dataset.deleted_at.is_(None))
                               .order_by(Dataset.created_at.desc()).limit(25)))
    runs = list(db.scalars(select(AnalysisRun)
                           .where(AnalysisRun.user_id == user.id)))
    by_status: dict[str, int] = {}
    for r in runs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    overview = {
        "datasets": len(datasets),
        "runs_total": len(runs),
        "runs_by_status": by_status,
        "latest": [{"id": r.id, "status": r.status,
                    "created_at": r.created_at.isoformat() if r.created_at else None}
                   for r in sorted(runs, key=lambda r: r.created_at or None,
                                   reverse=True)[:5]],
    }
    catalog = [{"filename": d.original_filename, "row_count": d.row_count,
                "column_count": d.column_count,
                "validation_status": d.validation_status,
                "runs": [{"id": r.id, "status": r.status, "progress": r.progress}
                         for r in d.runs[:3]]}
               for d in datasets]
    evidence = ai_grounding.workspace_evidence(overview, catalog)
    try:
        completion = ai.complete(
            system=ai.GROUNDING_RULES,
            user=("EVIDENCE: counts and catalog of one customer's workspace:\n"
                  f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                  "TASK: - headline: the state of this workspace in one sentence with numbers.\n"
                  "- summary: 2–3 sentences.\n"
                  "- focus: 2–4 next actions naming the file or run they concern."),
            json_schema=WORKSPACE_SCHEMA, max_tokens=600)
    except ai.AiError as exc:
        raise _provider_error(exc, "workspace-summary")
    data = completion.data or {}
    _audit(db, user, "ai.workspace_summary", "", {"model": completion.model})
    return {"model": completion.model, "latency_ms": completion.latency_ms,
            **data, "evidence": evidence,
            "provenance": _note(completion.model, completion.latency_ms)}
