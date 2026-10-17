"""Meta routes: brand, demo dataset, capabilities."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import config
from ..database import get_db
from ..csv_io import validate_csv_bytes

router = APIRouter(prefix="/api", tags=["meta"])

DEMO_NAME = "finsentry_master_dataset.csv"


@router.get("/brand")
def brand() -> dict:
    return {**config.BRAND,
            "limits": {"max_upload_bytes": config.MAX_UPLOAD_BYTES,
                       "max_rows": config.MAX_ROWS}}


@router.get("/demo/exists")
def demo_exists() -> dict:
    p = _demo_path()
    ok = p is not None and p.exists()
    info = {"available": ok, "filename": DEMO_NAME}
    if ok:
        info["size_bytes"] = p.stat().st_size
    return info


@router.get("/demo/sample")
def demo_sample():
    """Small preview of the demo file so the landing page can show structure."""
    p = _demo_path()
    if p is None or not p.exists():
        raise HTTPException(404, "Demo dataset not generated yet. "
                                 "Run scripts/generate_dataset.py.")
    raw = p.read_bytes()[:200_000]
    res = validate_csv_bytes(raw, DEMO_NAME)
    return {"filename": DEMO_NAME,
            "headers": res.headers,
            "sample_rows": res.sample_rows[:5],
            "note": "Preview is from the first 200 KB of the file."}


@router.get("/demo/download")
def demo_download():
    p = _demo_path()
    if p is None or not p.exists():
        raise HTTPException(404, "Demo dataset not generated yet.")
    return FileResponse(p, media_type="text/csv", filename=DEMO_NAME)


def _demo_path() -> Path | None:
    candidates = [
        config.PROJECT_DIR / "data" / DEMO_NAME,
        config.PROJECT_DIR / DEMO_NAME,
        config.UPLOAD_DIR / DEMO_NAME,
    ]
    for c in candidates:
        if c.exists():
            return c
    return None
