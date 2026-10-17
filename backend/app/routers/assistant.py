"""Assistant routes — allowlisted natural-language queries over real results."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from .. import ai, assistant, config
from ..database import get_db
from ..models import AnalysisRun, AuditEvent
from ..pipeline import load_frame_for_run
from ..schemas import AssistantPayload, NotePayload
from ..security import get_session_user

router = APIRouter(prefix="/api/runs", tags=["assistant"])


def _user(request: Request, db):
    from ..security import COOKIE_NAME
    return get_session_user(db, request.cookies.get(COOKIE_NAME))


def _owned_run(run_id: str, request: Request, db) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Run not found.")
    user = _user(request, db)
    if user is not None:
        if run.user_id not in (None, user.id):
            raise HTTPException(403, "Not authorized.")
    elif run.user_id is not None:
        raise HTTPException(403, "Not authorized.")
    return run


@router.post("/{run_id}/ask")
def ask(run_id: str, payload: AssistantPayload, request: Request, db=Depends(get_db)):
    """Deterministic answer, plus AI narration when a provider is configured.

    The computed answer is authoritative and always returned: if the provider
    fails, `answer` is unchanged and `llm_note` explains the degradation rather
    than the user receiving an invented reply.
    """
    run = _owned_run(run_id, request, db)
    if not run.manifest_path or not Path(run.manifest_path).exists():
        raise HTTPException(409, f"Analysis not finished yet (status: {run.status}).")
    import json
    manifest = json.loads(Path(run.manifest_path).read_text(encoding="utf-8"))

    frame_cache: dict = {}

    def load() -> pd.DataFrame:
        if "df" not in frame_cache:
            frame_cache["df"] = load_frame_for_run(run)
        return frame_cache["df"]

    result = assistant.answer(payload.question, manifest, load)

    # ---- optional AI narration over the computed answer (never arithmetic) ----
    if config.ai_configured():
        from .. import ai_grounding
        evidence = {
            "question": payload.question,
            "computed_topic": result.get("topic"),
            "computed_answer": result.get("answer"),
            "computed_data": result.get("data"),
            "computed_limitations": result.get("limitations"),
            "dataset": {"filename": manifest.get("filename"),
                        "rows": (manifest.get("overview") or {}).get("row_count")},
            "detections": [
                {"title": f.get("title"), "severity": f.get("severity"),
                 "evidence": f.get("evidence")}
                for f in (((manifest.get("financial") or {}).get("modules") or {})
                          .get("patterns") or {}).get("findings", [])[:8]
            ],
        }
        try:
            completion = ai.complete(
                system=ai.GROUNDING_RULES,
                user=("EVIDENCE computed by the analysis engine for this question:\n"
                      f"<evidence>{json.dumps(evidence, ensure_ascii=False, default=str)}</evidence>\n\n"
                      "TASK: answer in at most four sentences using only the computed "
                      "values above, keeping every figure identical. If the computed "
                      "answer reports the question could not be mapped, say so and name "
                      "what is missing. Plain prose."),
                max_tokens=420, temperature=0.15)
            result["ai_answer"] = completion.text
            result["model"] = completion.model
            result["latency_ms"] = completion.latency_ms
            result["unsupported_numbers"] = ai.unsupported_numbers(completion.text, evidence)
            result["llm_note"] = (
                f"Explained by {completion.model} over values computed by the engine "
                f"({completion.latency_ms} ms). The model does not compute metrics.")
        except ai.AiError as exc:
            result["ai_answer"] = None
            result["model"] = None
            result["llm_note"] = (f"AI narration unavailable ({exc.code}). "
                                  "This answer is the engine's computed result.")
    else:
        result["ai_answer"] = None

    db.add(AuditEvent(user_id=run.user_id, action="assistant.ask",
                      resource_type="run", resource_id=run.id,
                      detail={"topic": result.get("topic"),
                              "ai": bool(result.get("ai_answer"))}))
    db.commit()
    return result


@router.post("/{run_id}/notes")
def add_note(run_id: str, payload: NotePayload, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    note_path = Path(run.artifact_dir) / "analyst_notes.jsonl"
    import json
    from ..models import utcnow
    entry = {"at": utcnow().isoformat(timespec="seconds"),
             "text": payload.text.strip()}
    if entry["text"]:
        with note_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    notes = []
    if note_path.exists():
        notes = [json.loads(x) for x in note_path.read_text(encoding="utf-8").splitlines() if x]
    return {"ok": True, "notes": notes}
