"""Dataset routes: upload, validation, preview, schema, mapping, history."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from .. import config, data_quality, schema_inference
from ..csv_io import validate_csv_bytes
from ..database import SessionLocal, get_db
from ..models import AnalysisRun, AuditEvent, Dataset, utcnow
from ..security import get_session_user
from ..schemas import (ColumnMappingPayload, CleaningPayload, DatasetOut,
                        PreviewOut, QualityOut, SchemaOut, ValidationOut)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])

SAFE_EXT = re.compile(r"^[A-Za-z0-9._-]+$")


def _owner_filter(query, user):
    if user is None:
        return query.filter(Dataset.user_id.is_(None))
    return query.filter((Dataset.user_id == user.id) | (Dataset.user_id.is_(None)))


def _get_owned(dataset_id: str, user, db) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.deleted_at is not None:
        raise HTTPException(404, "Dataset not found.")
    if user is not None:
        if ds.user_id not in (None, user.id):
            raise HTTPException(403, "Not authorized for this dataset.")
    elif ds.user_id is not None:
        raise HTTPException(403, "Not authorized for this dataset.")
    return ds


def _user(request: Request, db):
    from ..security import COOKIE_NAME
    return get_session_user(db, request.cookies.get(COOKIE_NAME))


@router.post("/upload", response_model=ValidationOut)
async def upload(request: Request, file: UploadFile = File(...),
                 is_demo: bool = Form(False), db=Depends(get_db)):
    user = _user(request, db)
    name = Path(file.filename or "upload.csv").name
    if not SAFE_EXT.match(name):
        raise HTTPException(422, "Invalid filename characters.")
    if not name.lower().endswith(".csv"):
        raise HTTPException(422, "Only .csv files are accepted.")

    raw = await file.read()
    if len(raw) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File exceeds "
                                 f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.")

    result = validate_csv_bytes(raw, name)
    if not result.ok:
        raise HTTPException(422, {"message": "File failed validation",
                                  "errors": result.messages})

    checksum = hashlib.sha256(raw).hexdigest()
    stored = config.UPLOAD_DIR / f"{checksum[:32]}_{re.sub(r'[^A-Za-z0-9._-]', '_', name)}"
    stored.write_bytes(raw)

    ds = Dataset(
        user_id=user.id if user else None,
        filename=stored.name,
        original_filename=name,
        size_bytes=len(raw),
        checksum=checksum,
        delimiter=result.delimiter,
        encoding=result.encoding,
        row_count=result.row_count,
        column_count=result.column_count,
        validation_status=result.status,
        validation_messages=result.warnings + result.messages,
        source_path=str(stored),
        is_demo=is_demo,
    )
    db.add(ds)
    db.add(AuditEvent(user_id=user.id if user else None, action="dataset.upload",
                      resource_type="dataset", resource_id=ds.id,
                      detail={"rows": result.row_count, "cols": result.column_count}))
    db.commit()
    db.refresh(ds)

    return ValidationOut(
        dataset_id=ds.id, filename=name, size_bytes=len(raw),
        row_count=result.row_count, column_count=result.column_count,
        delimiter=result.delimiter, encoding=result.encoding,
        status=result.status, messages=result.messages, warnings=result.warnings,
        headers=result.headers, sample_rows=result.sample_rows,
    )


@router.get("", response_model=list[DatasetOut])
def list_datasets(request: Request, db=Depends(get_db), limit: int = 50):
    user = _user(request, db)
    q = select(Dataset).where(Dataset.deleted_at.is_(None)).order_by(
        Dataset.created_at.desc()).limit(min(limit, 200))
    rows = list(db.scalars(_owner_filter(q, user)))
    out = []
    for ds in rows:
        runs = list(db.scalars(select(AnalysisRun).where(AnalysisRun.dataset_id == ds.id)
                               .order_by(AnalysisRun.created_at.desc())))
        out.append(_dataset_out(ds, runs[:5]))
    return out


def _dataset_out(ds: Dataset, runs: list[AnalysisRun]) -> DatasetOut:
    return DatasetOut(
        id=ds.id, filename=ds.original_filename, size_bytes=ds.size_bytes,
        row_count=ds.row_count, column_count=ds.column_count,
        validation_status=ds.validation_status, is_demo=ds.is_demo,
        created_at=ds.created_at.isoformat() if ds.created_at else None,
        runs=[{"id": r.id, "status": r.status, "created_at":
               r.created_at.isoformat() if r.created_at else None,
               "progress": r.progress} for r in runs],
    )


@router.get("/{dataset_id}/preview", response_model=PreviewOut)
def preview(dataset_id: str, request: Request, db=Depends(get_db), rows: int = 25):
    ds = _get_owned(dataset_id, _user(request, db), db)
    frame = _load(ds, limit_rows=max(rows, 1) + 1)
    head = frame.head(min(rows, config.PREVIEW_ROWS * 4))
    return PreviewOut(
        columns=list(frame.columns),
        rows=json.loads(head.to_json(orient="values", date_format="iso")),
        total_rows=int(len(frame)),
        truncated=len(frame) > len(head),
        column_types={c: str(frame[c].dtype) for c in frame.columns},
    )


@router.get("/{dataset_id}/schema", response_model=SchemaOut)
def schema(dataset_id: str, request: Request, db=Depends(get_db)):
    ds = _get_owned(dataset_id, _user(request, db), db)
    frame = _load(ds)
    inf = schema_inference.infer_schema(frame)
    d = inf.as_dict()
    return SchemaOut(**d, row_count=int(len(frame)))


@router.get("/{dataset_id}/quality", response_model=QualityOut)
def quality(dataset_id: str, request: Request, db=Depends(get_db)):
    ds = _get_owned(dataset_id, _user(request, db), db)
    frame = _load(ds)
    inf = schema_inference.infer_schema(frame)
    report = data_quality.assess_quality(frame, inf.columns, inf.semantic_map)
    return QualityOut(**report.as_dict())


@router.post("/{dataset_id}/mapping")
def save_mapping(dataset_id: str, payload: ColumnMappingPayload, request: Request,
                 db=Depends(get_db)):
    """Persist per-column semantic overrides for the next analysis run."""
    ds = _get_owned(dataset_id, _user(request, db), db)
    frame = _load(ds)
    unknown = [c for c in payload.mapping if c not in frame.columns]
    if unknown:
        raise HTTPException(422, f"Unknown columns: {', '.join(unknown[:8])}")
    valid_roles = set(schema_inference.ALIASES.keys()) | {
        "target", "datetime", "categorical", "identifier", "text",
        "numeric", "currency_amount", "geographic", "none"}
    bad = {c: r for c, r in payload.mapping.items() if r not in valid_roles}
    if bad:
        raise HTTPException(422, {"message": "Unknown semantic role",
                                  "roles": sorted(valid_roles)})
    # store on the most recent run config (or create a pending draft run config)
    run = db.scalar(select(AnalysisRun).where(AnalysisRun.dataset_id == ds.id)
                    .order_by(AnalysisRun.created_at.desc()))
    clean = {c: ("" if r == "none" else r) for c, r in payload.mapping.items()}
    if run is not None:
        run.column_overrides = {**(run.column_overrides or {}), **clean}
    else:
        run = AnalysisRun(dataset_id=ds.id, user_id=ds.user_id, status="pending",
                          column_overrides=clean, artifact_dir="")
        db.add(run)
    db.add(AuditEvent(user_id=ds.user_id, action="dataset.mapping",
                      resource_type="dataset", resource_id=ds.id,
                      detail={"columns": len(clean)}))
    db.commit()
    return {"ok": True, "mapping": clean,
            "run_id": run.id if run else None}


@router.post("/{dataset_id}/cleaning-preview")
def cleaning_preview(dataset_id: str, payload: CleaningPayload, request: Request,
                     db=Depends(get_db)):
    ds = _get_owned(dataset_id, _user(request, db), db)
    frame = _load(ds)
    result = data_quality.apply_cleaning(frame, payload.operations)
    before_after = {"before": {"rows": int(len(frame)), "columns": int(frame.shape[1])},
                    "after": {"rows": int(result.frame.shape[0]),
                              "columns": int(result.frame.shape[1])},
                    "operations": result.operations,
                    "sample_before": json.loads(frame.head(5).to_json(orient="records")),
                    "sample_after": json.loads(result.frame.head(5).to_json(orient="records"))}
    return before_after


@router.get("/{dataset_id}/file")
def download_original(dataset_id: str, request: Request, db=Depends(get_db)):
    ds = _get_owned(dataset_id, _user(request, db), db)
    path = Path(ds.source_path)
    if not path.exists():
        raise HTTPException(404, "Source file no longer exists.")
    return FileResponse(path, media_type="text/csv", filename=ds.original_filename)


@router.delete("/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request, db=Depends(get_db),
                   purge: bool = False):
    ds = _get_owned(dataset_id, _user(request, db), db)
    user = _user(request, db)
    ds.deleted_at = utcnow()
    if purge:
        # spec #21: configurable deletion of the source + derived artifacts
        for run in db.scalars(select(AnalysisRun).where(AnalysisRun.dataset_id == ds.id)):
            if run.artifact_dir:
                _rmtree(run.artifact_dir)
        p = Path(ds.source_path)
        if p.exists():
            p.unlink()
        db.delete(ds)
    db.add(AuditEvent(user_id=user.id if user else None, action="dataset.delete",
                      resource_type="dataset", resource_id=ds.id, detail={"purge": purge}))
    db.commit()
    return {"ok": True, "purged": purge}


def _rmtree(path_str: str) -> None:
    import shutil
    p = Path(path_str)
    if p.is_dir() and config.DATA_DIR in p.parents:
        shutil.rmtree(p, ignore_errors=True)


def _load(ds: Dataset, limit_rows: int | None = None) -> pd.DataFrame:
    path = Path(ds.source_path)
    if not path.exists():
        raise HTTPException(404, "Source file no longer exists on disk.")
    try:
        frame = pd.read_csv(path, sep=ds.delimiter, encoding=ds.encoding,
                            dtype=str, keep_default_na=False, na_values=[""],
                            low_memory=False,
                            nrows=limit_rows or config.MAX_ROWS)
    except Exception as exc:
        raise HTTPException(422, f"Could not re-parse the file: {exc}")
    if frame.empty and limit_rows is None:
        # fall back to python engine for unusual dialects
        try:
            frame = pd.read_csv(path, sep=ds.delimiter, encoding=ds.encoding,
                                dtype=str, engine="python", nrows=config.MAX_ROWS)
        except Exception as exc:
            raise HTTPException(422, f"Could not re-parse the file: {exc}")
    # normalize headers like the upload path does
    from ..csv_io import normalize_headers
    frame.columns = normalize_headers([str(c) for c in frame.columns])
    return frame
