"""FinSentry FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .database import init_db
from .pipeline import runner
from .routers import ai, analysis, assistant, auth, datasets, meta, workspace


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    runner.start()
    # mark orphaned runs AND their in-flight jobs from a previous process, so
    # a restarted server can never leave the workspace spinning forever
    from .database import SessionLocal
    from .models import AnalysisRun, Job, utcnow
    db = SessionLocal()
    try:
        stale_runs = db.query(AnalysisRun).filter(
            AnalysisRun.status.in_(["running", "pending"])).all()
        ids = [r.id for r in stale_runs]
        for run in stale_runs:
            run.status = "failed"
            run.error = "Interrupted by server restart — retry from the run screen."
            run.finished_at = utcnow()
        if ids:
            for job in db.query(Job).filter(Job.run_id.in_(ids),
                                            Job.status.in_(["running", "pending"])).all():
                job.status = "failed"
                job.error = "Interrupted by server restart before the stage finished."
                job.detail = "interrupted"
                job.finished_at = utcnow()
        db.commit()
    finally:
        db.close()
    yield
    runner.stop()


app = FastAPI(
    title=f"{config.BRAND['name']} API",
    description=f"{config.BRAND['descriptor']} — {config.BRAND['tagline']}",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={
        "detail": "Internal server error",
        "path": request.url.path,
    })


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "brand": config.BRAND,
        "limits": {
            "max_upload_bytes": config.MAX_UPLOAD_BYTES,
            "max_rows": config.MAX_ROWS,
            "max_columns": config.MAX_COLUMNS,
        },
        "providers": {
            "llm_configured": config.llm_configured(),
            "ai_configured": config.ai_configured(),
            "ai_provider": config.AI_PROVIDER if config.ai_configured() else None,
            # Health must stay offline-safe: report the pinned model only. Use
            # /api/ai/status for a live provider + model verification.
            "ai_model": config.AI_MODEL or None,
            "fx_provider_configured": config.fx_provider_configured(),
            # Which component actually delivers sign-in passcodes. Health stays
            # offline-safe: this is configuration, not a live provider probe.
            "otp_provider": config.otp_provider(),
        },
        "stack": {"database": config.DATABASE_URL.split("://")[0],
                  "workers": config.WORKERS},
    }


for router in (auth.router, datasets.router, analysis.router,
               assistant.router, meta.router, workspace.router, ai.router):
    app.include_router(router)
