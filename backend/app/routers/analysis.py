"""Analysis runs: start, status, cancel, retry, results, charts, reports."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from .. import config, reports
from ..database import get_db
from ..models import AnalysisRun, AuditEvent, Dataset, Job, Report, utcnow
from ..pipeline import STAGES, load_frame_for_run, runner
from ..schemas import StartAnalysisPayload
from ..security import get_session_user

router = APIRouter(prefix="/api/runs", tags=["analysis"])


def _user(request: Request, db):
    from ..security import COOKIE_NAME
    return get_session_user(db, request.cookies.get(COOKIE_NAME))


def _owned_run(run_id: str, request: Request, db) -> AnalysisRun:
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "Analysis run not found.")
    user = _user(request, db)
    if user is not None:
        if run.user_id not in (None, user.id):
            raise HTTPException(403, "Not authorized for this run.")
    elif run.user_id is not None:
        raise HTTPException(403, "Not authorized for this run.")
    return run


@router.post("/start")
def start(payload: StartAnalysisPayload, request: Request, db=Depends(get_db)):
    ds = db.get(Dataset, payload.dataset_id)
    if ds is None or ds.deleted_at is not None:
        raise HTTPException(404, "Dataset not found.")
    user = _user(request, db)
    if user is not None and ds.user_id not in (None, user.id):
        raise HTTPException(403, "Not authorized for this dataset.")

    run = AnalysisRun(
        dataset_id=ds.id, user_id=user.id if user else ds.user_id,
        status="pending", column_overrides=payload.column_overrides,
        config=payload.config, artifact_dir="",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    run_dir = config.ARTIFACT_DIR / run.id
    run_dir.mkdir(parents=True, exist_ok=True)
    run.artifact_dir = str(run_dir)
    db.add(AuditEvent(user_id=user.id if user else None, action="analysis.start",
                      resource_type="run", resource_id=run.id,
                      detail={"dataset": ds.id}))
    # create job rows so status reflects real stages
    for stage in STAGES:
        db.add(Job(run_id=run.id, name=stage["name"], label=stage["label"],
                   required=stage["required"]))
    db.commit()

    runner.enqueue(run.id)
    return {"run_id": run.id, "status": run.status,
            "stages": [{"name": s["name"], "label": s["label"]} for s in STAGES]}


@router.get("/{run_id}/status")
def status(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    jobs = list(db.scalars(select(Job).where(Job.run_id == run.id)
                           .order_by(Job.id)))
    order = {s["name"]: i for i, s in enumerate(STAGES)}
    jobs.sort(key=lambda j: order.get(j.name, 99))
    return {
        "run_id": run.id,
        "status": run.status,
        "progress": run.progress,
        "current_stage": run.current_stage,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "jobs": [{"name": j.name, "label": j.label, "status": j.status,
                  "required": j.required, "detail": j.detail,
                  "error": (j.error or "")[:600] or None,
                  "started_at": j.started_at.isoformat() if j.started_at else None,
                  "finished_at": j.finished_at.isoformat() if j.finished_at else None}
                 for j in jobs],
    }


@router.post("/{run_id}/cancel")
def cancel(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    if run.status in ("completed", "failed", "partial"):
        raise HTTPException(409, f"Run already {run.status}; cannot cancel.")
    run.status = "cancelled"
    run.finished_at = utcnow()
    db.add(AuditEvent(user_id=run.user_id, action="analysis.cancel",
                      resource_type="run", resource_id=run.id))
    db.commit()
    return {"ok": True, "status": run.status}


@router.post("/{run_id}/retry")
def retry(run_id: str, request: Request, db=Depends(get_db)):
    """Re-run only the stages that failed or were skipped."""
    run = _owned_run(run_id, request, db)
    if run.status == "running":
        raise HTTPException(409, "Run is already in progress.")
    jobs = list(db.scalars(select(Job).where(Job.run_id == run.id)))
    reset = 0
    for j in jobs:
        if j.status in ("failed", "cancelled"):
            j.status = "pending"
            j.error = None
            j.detail = "queued for retry"
            j.started_at = None
            j.finished_at = None
            reset += 1
    if reset == 0:
        raise HTTPException(409, "No failed stages to retry.")
    run.status = "pending"
    run.error = None
    run.finished_at = None
    db.commit()
    runner.enqueue(run.id)
    return {"ok": True, "retried_stages": reset}


# ------------------------------------------------------------- results ------
@router.get("/{run_id}/manifest")
def manifest(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    if not run.manifest_path or not Path(run.manifest_path).exists():
        raise HTTPException(409, f"Manifest not ready (run status: {run.status}).")
    return json.loads(Path(run.manifest_path).read_text(encoding="utf-8"))


@router.get("/{run_id}/stage/{stage_name}")
def stage_result(run_id: str, stage_name: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    job = db.scalar(select(Job).where(Job.run_id == run.id, Job.name == stage_name))
    if job is None:
        raise HTTPException(404, "Stage not found.")
    if not job.result_path or not Path(job.result_path).exists():
        raise HTTPException(409, f"Stage has no persisted result (status {job.status}).")
    return json.loads(Path(job.result_path).read_text(encoding="utf-8"))


@router.get("/{run_id}/charts")
def charts(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    m = _load_manifest(run)
    return {"charts": m.get("charts", []),
            "chart_count": len(m.get("charts", []))}


@router.get("/{run_id}/records")
def records(run_id: str, request: Request, db=Depends(get_db), limit: int = 100,
            offset: int = 0, q: str = "", column: str = "", sort: str = "",
            direction: str = "asc", filters: str = ""):
    """Server-side filtered, sorted, paginated record browsing."""
    run = _owned_run(run_id, request, db)
    frame = load_frame_for_run(run)
    total = len(frame)

    if column and column in frame.columns and q:
        mask = frame[column].astype(str).str.contains(q, case=False, na=False, regex=False)
        frame = frame[mask]
    if filters:
        try:
            fdefs = json.loads(filters)
            for f in fdefs:
                c, op, v = f.get("column"), f.get("op", "eq"), str(f.get("value", ""))
                if c in frame.columns:
                    s = frame[c].astype(str)
                    if op == "eq":
                        frame = frame[s == v]
                    elif op == "contains":
                        frame = frame[s.str.contains(v, case=False, na=False, regex=False)]
                    elif op == "ne":
                        frame = frame[s != v]
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(422, "Invalid filters JSON.")
    if sort and sort in frame.columns:
        frame = frame.sort_values(sort, ascending=(direction != "desc"),
                                  kind="mergesort")
    page = frame.iloc[max(offset, 0):max(offset, 0) + min(max(limit, 1), 500)]
    return {
        "total": int(total),
        "filtered": int(len(frame)),
        "offset": int(offset),
        "limit": int(limit),
        "columns": list(page.columns),
        "rows": json.loads(page.to_json(orient="values", date_format="iso")),
        "sampled": total > config.SAMPLE_ROWS_FOR_EXPENSIVE,
    }


@router.get("/{run_id}/findings")
def findings(run_id: str, request: Request, db=Depends(get_db)):
    m = _load_manifest(_owned_run(run_id, request, db))
    return m.get("findings", {})


@router.get("/{run_id}/network")
def network(run_id: str, request: Request, db=Depends(get_db),
            top_n: int = 120, currency: str = "", status: str = ""):
    """Re-query the network server-side with filters (spec #10.2)."""
    from ..financial import build_transfer_network
    run = _owned_run(run_id, request, db)
    m = _load_manifest(run)
    if not (m.get("financial") or {}).get("activated"):
        raise HTTPException(409, "Financial module was not activated for this dataset.")
    frame = load_frame_for_run(run)
    roles = m.get("roles", {})
    net = build_transfer_network(frame, roles, top_n=min(top_n, 400),
                                 currency_filter=currency or None,
                                 status_filter=status or None)
    return net.as_dict()


@router.get("/{run_id}/data-quality")
def data_quality(run_id: str, request: Request, db=Depends(get_db)):
    m = _load_manifest(_owned_run(run_id, request, db))
    if not m.get("quality"):
        raise HTTPException(409, "Quality stage has not completed.")
    return m["quality"]


# -------------------------------------------------------------- reports -----
@router.post("/{run_id}/reports")
def create_report(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    m = _load_manifest(run)
    art = Path(run.artifact_dir)
    # rebuild from the persisted manifest (real results only)
    ctx = {"manifest": m, "artifact_dir": art}

    class _Ctx(dict):
        pass
    # build_reports only needs manifest + artifact dir
    written = reports.build_reports(m, {"manifest": m}, art)
    for kind in ("executive", "technical", "investigation"):
        p = written.get(kind)
        if p and p.exists():
            exists = db.scalar(select(Report).where(Report.run_id == run.id,
                                                    Report.kind == kind,
                                                    Report.format == "md"))
            if exists:
                exists.path = str(p)
                exists.size_bytes = p.stat().st_size
            else:
                db.add(Report(run_id=run.id, kind=kind, format="md", path=str(p),
                              size_bytes=p.stat().st_size))
    db.add(AuditEvent(user_id=run.user_id, action="report.create",
                      resource_type="run", resource_id=run.id))
    db.commit()
    return {"ok": True,
            "files": [{"name": k, "path": str(v), "size": v.stat().st_size}
                      for k, v in written.items() if Path(v).exists()]}


@router.get("/{run_id}/reports")
def list_reports(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    files = reports.list_report_files(run.artifact_dir)
    rows = list(db.scalars(select(Report).where(Report.run_id == run.id)))
    return {"files": files,
            "registered": [{"kind": r.kind, "format": r.format, "size": r.size_bytes,
                            "created_at": r.created_at.isoformat()}
                           for r in rows]}


@router.get("/{run_id}/reports/download")
def download_report(run_id: str, filename: str, request: Request,
                    db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    art = Path(run.artifact_dir).resolve()
    target = (art / Path(filename).name).resolve()
    if not str(target).startswith(str(art)) or not target.exists():
        raise HTTPException(404, "Report file not found.")
    media = ("text/markdown" if target.suffix == ".md" else
             "application/json" if target.suffix == ".json" else
             "text/csv" if target.suffix == ".csv" else
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    return FileResponse(target, media_type=media, filename=target.name)


@router.get("/{run_id}/history")
def run_history(run_id: str, request: Request, db=Depends(get_db)):
    run = _owned_run(run_id, request, db)
    rows = list(db.scalars(select(AnalysisRun)
                           .where(AnalysisRun.dataset_id == run.dataset_id)
                           .order_by(AnalysisRun.created_at.desc()).limit(20)))
    return [{"run_id": r.id, "status": r.status, "progress": r.progress,
             "created_at": r.created_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in rows]


def _load_manifest(run: AnalysisRun) -> dict:
    if not run.manifest_path or not Path(run.manifest_path).exists():
        raise HTTPException(409, f"Manifest not ready (run status: {run.status}).")
    return json.loads(Path(run.manifest_path).read_text(encoding="utf-8"))
