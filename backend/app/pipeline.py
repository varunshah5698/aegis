

"""Analysis pipeline and persistent background job runner (spec #4.3, #17).

Jobs are real: a bounded thread pool picks run-stages off a queue, updates the
`jobs` table, writes artifacts to disk and records failures per stage so one
failing module never blocks the rest (spec #2.15). State survives a browser
refresh because it lives in the database, not in memory.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from . import config, data_quality, eda, financial, ml_engine, schema_inference
from .database import SessionLocal
from .models import AnalysisRun, Job, utcnow

logger = logging.getLogger("aegis.pipeline")

STAGES: list[dict] = [
    {"name": "validate", "label": "1 · Upload validation", "required": True},
    {"name": "parse", "label": "2 · CSV parsing", "required": True},
    {"name": "schema", "label": "3 · Schema inference", "required": True},
    {"name": "mapping", "label": "4 · Semantic column mapping", "required": True},
    {"name": "quality", "label": "5 · Data quality assessment", "required": True},
    {"name": "profiling", "label": "6 · Statistical profiling", "required": True},
    {"name": "prepare", "label": "7 · Data preparation", "required": True},
    {"name": "planning", "label": "8 · Analysis planning", "required": True},
    {"name": "exploration", "label": "9 · Exploratory analysis", "required": True},
    {"name": "ml_eligibility", "label": "10 · ML eligibility checks", "required": True},
    {"name": "ml_train", "label": "11 · Model training", "required": False},
    {"name": "financial", "label": "12 · Financial analytics", "required": False},
    {"name": "charts", "label": "13 · Visualization generation", "required": True},
    {"name": "findings", "label": "14 · Findings generation", "required": True},
    {"name": "workspace", "label": "15 · Workspace assembly", "required": True},
    {"name": "report", "label": "16 · Report preparation", "required": False},
]

# Shared per-run context lives in memory only for the duration of one run
# (results are persisted to disk immediately after each stage).
_CTX: dict[str, dict] = {}
_CTX_LOCK = threading.Lock()

# Runs whose stage blew past the timeout are abandoned: the watchdog marks the
# run failed so the UI (and the database) tell the truth immediately, and the
# worker stops at the next stage boundary instead of running the whole pipeline.
_ABANDONED: set[str] = set()
_ABANDON_LOCK = threading.Lock()


def _abandon(run_id: str) -> None:
    with _ABANDON_LOCK:
        _ABANDONED.add(run_id)


def _is_abandoned(run_id: str) -> bool:
    with _ABANDON_LOCK:
        return run_id in _ABANDONED


def _release(run_id: str) -> None:
    with _ABANDON_LOCK:
        _ABANDONED.discard(run_id)


def _format_stage_error(exc: Exception, tb: str) -> str:
    """Human-readable failure line plus the traceback tail for debugging."""
    message = str(exc).strip() or exc.__class__.__name__
    tail = tb.strip().splitlines()[-6:]
    return (f"{exc.__class__.__name__}: {message}\n"
            f"--- traceback tail ---\n" + "\n".join(tail))[:3000]


class PipelineRunner:
    def __init__(self, workers: int = config.WORKERS):
        self._q: queue.Queue[str] = queue.Queue()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="finsentry")
        self._started = False
        self._stop = threading.Event()

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        watchdog.start()
        for _ in range(max(1, config.WORKERS)):
            self._executor.submit(self._worker)

    def enqueue(self, run_id: str) -> None:
        self.start()
        self._q.put(run_id)

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------------------- worker --
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                run_id = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._execute(run_id)
            except Exception:
                _mark_run_failed(run_id, traceback.format_exc()[-4000:])
            finally:
                self._q.task_done()

    # ------------------------------------------------------------ executor --
    def _execute(self, run_id: str) -> None:
        db = SessionLocal()
        try:
            run = db.get(AnalysisRun, run_id)
            if run is None:
                return
            if run.status == "cancelled":
                return
            run.status = "running"
            run.started_at = utcnow()
            run.current_stage = "starting"
            db.commit()

            artifact_dir = Path(run.artifact_dir)
            artifact_dir.mkdir(parents=True, exist_ok=True)

            dataset_path = run.dataset.source_path
            overrides = dict(run.column_overrides or {})
            ctx: dict = {"run_id": run_id, "overrides": overrides, "artifact_dir": artifact_dir}
            with _CTX_LOCK:
                _CTX[run_id] = ctx

            total = len(STAGES)
            for idx, stage in enumerate(STAGES):
                db.refresh(run)
                if run.status == "cancelled":
                    _finish_stage(db, run_id, stage["name"], "cancelled", "Run cancelled by user.")
                    break
                # A watchdog can abandon a run whose stage outlived the
                # timeout; stop this worker instead of continuing blindly.
                with _ABANDON_LOCK:
                    if run_id in _ABANDONED:
                        break
                job = _get_job(db, run_id, stage["name"])
                # Every execution rebuilds the shared context end-to-end: cheap
                # deterministic stages re-run so a partial retry always sees a
                # populated ctx (a skipped stage would leave later ones empty).
                job.status = "running"
                job.started_at = job.started_at or utcnow()
                run.current_stage = stage["label"]
                run.progress = int(idx / total * 100)
                db.commit()
                watchdog.note_progress(run_id, stage["name"])

                try:
                    detail = self._run_stage(stage["name"], ctx, db, run)
                    job = _get_job(db, run_id, stage["name"])
                    job.status = detail.pop("_status", "completed")
                    job.detail = str(detail.pop("_detail", ""))[:600]
                    job.finished_at = utcnow()
                    if detail:
                        job.result_path = _save_json(
                            artifact_dir / f"stage_{stage['name']}.json", detail)
                    run = db.get(AnalysisRun, run_id)
                    run.progress = int((idx + 1) / total * 100)
                    db.commit()
                except _SkipStage as skip:
                    job = _get_job(db, run_id, stage["name"])
                    job.status = "skipped"
                    job.detail = str(skip)[:600]
                    job.finished_at = utcnow()
                    db.commit()
                except Exception as exc:
                    tb = traceback.format_exc()[-3000:]
                    job = _get_job(db, run_id, stage["name"])
                    job.status = "failed"
                    # Keep the message short for the UI, but always persist the
                    # traceback — without it a stage failure is undiagnosable
                    # ("Unalignable boolean Series" tells you nothing on its own).
                    job.error = _format_stage_error(exc, tb)
                    job.detail = "stage failed — remaining stages continue"
                    job.finished_at = utcnow()
                    db.commit()

            # finalize
            run = db.get(AnalysisRun, run_id)
            if run.status == "cancelled":
                pass
            else:
                jobs = list(db.scalars(select(Job).where(Job.run_id == run_id)))
                required_failed = any(j.status == "failed" for j in jobs if _required(j.name))
                any_failed = any(j.status == "failed" for j in jobs)
                completed = sum(1 for j in jobs if j.status == "completed")
                if required_failed:
                    run.status = "failed"
                    run.error = "One or more required stages failed."
                elif any_failed:
                    run.status = "partial"
                    run.error = "Some optional modules failed; results are partial."
                else:
                    run.status = "completed"
                    run.error = None
                run.finished_at = utcnow()
                run.progress = 100
                run.current_stage = f"done ({completed}/{len(jobs)} stages)"
                db.commit()
        finally:
            db.close()
            _release(run_id)
            with _CTX_LOCK:
                _CTX.pop(run_id, None)

    # ------------------------------------------------------------- stages ---
    def _run_stage(self, name: str, ctx: dict, db, run: AnalysisRun) -> dict:
        df = ctx.get("df")
        profiles: list[schema_inference.ColumnProfile] = ctx.get("profiles") or []

        # ---------------------------------------------------------------- --
        if name == "validate":
            path = Path(run.dataset.source_path)
            if not path.exists():
                raise RuntimeError("Uploaded file no longer exists on disk.")
            raw = path.read_bytes()
            result = ctx["validation"] = csv_validate(raw, path.name)
            if not result.ok:
                raise RuntimeError("; ".join(result.messages) or "validation failed")
            return {"_detail": f"{result.row_count:,} rows × {result.column_count} columns "
                               f"({result.status})", **{k: v for k, v in result.as_dict().items()
                                                        if k not in ("sample_rows", "headers")}}

        # ---------------------------------------------------------------- --
        if name == "parse":
            path = Path(run.dataset.source_path)
            raw = path.read_bytes()
            v = ctx["validation"]          # csv_io.ValidationResult
            headers, rows = _read(raw, v.delimiter, v.encoding)
            if not rows:
                raise RuntimeError("No data rows could be parsed from the file.")
            frame = pd.DataFrame(rows)
            # preserve numeric types where the whole column parses
            for c in frame.columns:
                converted = pd.to_numeric(frame[c].astype(str).str.replace(",", "", regex=False),
                                          errors="coerce")
                if converted.notna().mean() >= 0.9 and frame[c].astype(str).str.strip().ne("").mean() >= 0.9:
                    frame[c] = converted
            ctx["df"] = frame
            ctx["headers"] = headers
            # persist normalized parquet-like copy (CSV) for later re-loads
            frame.to_csv(ctx["artifact_dir"] / "parsed.csv", index=False)
            return {"_detail": f"parsed {len(frame):,} rows", "rows": int(len(frame)),
                    "columns": int(frame.shape[1])}

        # ---------------------------------------------------------------- --
        if name == "schema":
            assert df is not None
            inf = ctx["inference"] = schema_inference.infer_schema(df)
            ctx["profiles"] = inf.columns
            ctx["semantic_map"] = dict(inf.semantic_map)
            # apply user overrides made before rerun
            for col, role in (ctx.get("overrides") or {}).items():
                if col in ctx["semantic_map"] or role:
                    ctx["semantic_map"][col] = role
            return {"_detail": f"{len(inf.columns)} columns profiled",
                    **inf.as_dict()}

        # ---------------------------------------------------------------- --
        if name == "mapping":
            assert df is not None
            inferred = ctx["inference"]
            uncertain = [c.as_dict() for c in ctx["profiles"]
                         if c.semantic_confidence < 0.7][:40]
            # merge user overrides
            for col, role in (ctx.get("overrides") or {}).items():
                if role and col in df.columns:
                    ctx["semantic_map"][col] = role
                    for p in ctx["profiles"]:
                        if p.name == col:
                            p.user_override = role
                            p.semantic_confidence = 1.0
                            p.reason = "user override"
            caps = schema_inference._assess_capabilities(
                df, ctx["semantic_map"], ctx["profiles"])
            ctx["inference"].capabilities = caps
            ctx["roles"] = _resolve_roles(ctx["semantic_map"])
            return {"_detail": f"{len(ctx['roles'])} semantic roles resolved; "
                               f"{len(uncertain)} low-confidence columns",
                    "roles": ctx["roles"], "uncertain": uncertain, "capabilities": caps}

        # ---------------------------------------------------------------- --
        if name == "quality":
            assert df is not None
            report = ctx["quality"] = data_quality.assess_quality(
                df, ctx["profiles"], ctx["semantic_map"])
            return {"_detail": f"score {report.score}/100 ({report.grade})", **report.as_dict()}

        # ---------------------------------------------------------------- --
        if name == "profiling":
            assert df is not None
            sampled = False
            work = df
            if len(df) > config.SAMPLE_ROWS_FOR_EXPENSIVE:
                work = df.sample(config.SAMPLE_ROWS_FOR_EXPENSIVE, random_state=42)
                sampled = True
            ctx["stats"] = eda.descriptive_stats(work, ctx["profiles"])
            ctx["sampled"] = sampled
            return {"_detail": f"{len(ctx['stats']['numeric'])} numeric, "
                               f"{len(ctx['stats']['categorical'])} categorical profiles"
                               + (" (sampled)" if sampled else ""),
                    "numeric_count": len(ctx["stats"]["numeric"]),
                    "categorical_count": len(ctx["stats"]["categorical"]),
                    "temporal_count": len(ctx["stats"]["temporal"])}

        # ---------------------------------------------------------------- --
        if name == "prepare":
            assert df is not None
            ops = list((run.config or {}).get("cleaning_ops", []))
            if ops:
                result = data_quality.apply_cleaning(df, ops)
                ctx["df"] = result.frame
                df = result.frame
                ctx["cleaning"] = result.as_dict()
                return {"_detail": f"{len(result.operations)} transformation(s) applied",
                        **result.as_dict()}
            ctx["cleaning"] = {"operations": [], "row_count": int(len(df)),
                               "column_count": int(df.shape[1])}
            return {"_detail": "no transformations requested — original upload preserved",
                    "row_count": int(len(df)), "column_count": int(df.shape[1]),
                    "note": "Original upload stored immutably at its source path."}

        # ---------------------------------------------------------------- --
        if name == "planning":
            assert df is not None
            caps = ctx["inference"].capabilities
            plan = {
                "selected_tasks": [k for k, v in caps.items() if str(v.get("state", "")).startswith("available")],
                "unsupported": {k: v.get("reason", "") for k, v in caps.items()
                                if v.get("state") == "unavailable"},
                "needs_configuration": {k: v.get("reason", "") for k, v in caps.items()
                                        if v.get("state") == "needs configuration"},
                "limitations": ctx["inference"].warnings,
            }
            ctx["plan"] = plan
            return {"_detail": f"{len(plan['selected_tasks'])} modules activated", **plan}

        # ---------------------------------------------------------------- --
        if name == "exploration":
            assert df is not None
            rel = ctx["relationships"] = eda.relationships(df, ctx["profiles"])
            ctx["overview"] = eda.dataset_overview(
                df, ctx["profiles"],
                file_bytes=run.dataset.size_bytes,
                elapsed_s=_elapsed_seconds(run.started_at),
                sampled=ctx.get("sampled", False))
            fc = ctx["inference"].capabilities.get("forecasting", {})
            ctx["forecast"] = (ml_engine.run_forecast(df, ctx["profiles"])
                               if fc.get("state", "").startswith("available") else
                               {"status": "unavailable",
                                "reason": fc.get("reason", "Forecasting not supported.")})
            return {"_detail": f"{len(rel['strong_pairs'])} significant relationships found",
                    "overview": ctx["overview"],
                    "strong_pair_count": len(rel["strong_pairs"]),
                    "forecast_status": ctx["forecast"].get("status")}

        # ---------------------------------------------------------------- --
        if name == "ml_eligibility":
            assert df is not None
            caps = ctx["inference"].capabilities
            target = caps.get("ml_classification", {}).get("target") or caps.get(
                "ml_regression", {}).get("target")
            ctx["target"] = target
            eligibility = {
                "classification": caps.get("ml_classification"),
                "regression": caps.get("ml_regression"),
                "clustering": caps.get("ml_clustering"),
                "anomaly": caps.get("ml_anomaly"),
                "forecasting": caps.get("forecasting"),
                "target": target,
                "label_columns_excluded_from_features": [
                    c for c, r in ctx["semantic_map"].items() if r == "target"],
            }
            return {"_detail": f"target={target or 'none (unsupervised only)'}", **eligibility}

        # ---------------------------------------------------------------- --
        if name == "ml_train":
            assert df is not None
            caps = ctx["inference"].capabilities
            results: dict = {"supervised": None, "clustering": None, "anomaly": None}
            statuses: list[str] = []
            target = ctx.get("target")
            # semantic_map is column → role; invert it to find the label column
            label_col = next((c for c, r in ctx["semantic_map"].items() if r == "target"), None)

            if target and str(caps.get("ml_classification", {}).get("state", "")).startswith("available"):
                r = ml_engine.run_supervised(df, ctx["profiles"], target, "classification",
                                             ctx.get("overrides"))
                results["supervised"] = r.as_dict()
                statuses.append(r.status)
            elif target and str(caps.get("ml_regression", {}).get("state", "")).startswith("available"):
                r = ml_engine.run_supervised(df, ctx["profiles"], target, "regression",
                                             ctx.get("overrides"))
                results["supervised"] = r.as_dict()
                statuses.append(r.status)
            else:
                results["supervised"] = {
                    "task": "none", "status": "unavailable",
                    "reason": caps.get("ml_classification", {}).get(
                        "reason", "No usable target column."),
                    "limitations": ["Unsupervised methods below still ran."]}
                statuses.append("unavailable")

            if str(caps.get("ml_clustering", {}).get("state", "")).startswith("available"):
                c = ml_engine.run_clustering(df, ctx["profiles"])
                results["clustering"] = c.as_dict()
                statuses.append(c.status)
            if str(caps.get("ml_anomaly", {}).get("state", "")).startswith("available"):
                a = ml_engine.run_anomaly_detection(df, ctx["profiles"], label_col)
                results["anomaly"] = a.as_dict()
                statuses.append(a.status)

            ctx["ml_block"] = results      # consumed by findings + manifest
            completed = [s for s in statuses if s == "completed"]
            if completed:
                status = "completed" if len(completed) == len(statuses) else "completed"
                return {"_status": status,
                        "_detail": f"completed: {', '.join(s for s in statuses if s == 'completed')}"
                                   f" | {'; '.join(s for s in statuses if s != 'completed')}",
                        **results}
            raise RuntimeError("No ML method could run: " +
                               "; ".join(str(results[k] and results[k].get("reason"))
                                        for k in results if results[k]))

        # ---------------------------------------------------------------- --
        if name == "financial":
            assert df is not None
            caps = ctx["inference"].capabilities
            roles: dict[str, str | None] = ctx.get("roles", {})
            time_col = roles.get("transaction_time") or roles.get("datetime")
            if time_col is None:
                time_col = next((p.name for p in ctx["profiles"]
                                 if p.semantic_type == "datetime"), None)
            any_financial = any(str(caps.get(k, {}).get("state", "")).startswith("available")
                                for k in ("transaction_summary", "transfer_network",
                                          "currency", "reconciliation", "payments"))
            out: dict = {"activated": bool(any_financial), "modules": {}}
            if not any_financial:
                raise _SkipStage("No transaction-like columns detected — this module is "
                                 "not applicable to this dataset.")
            # Each detector is independent: one detector tripping over an
            # unusual column must not fail the stage. Failures are recorded on
            # the module result and surfaced as run warnings instead.
            failed_modules: list[str] = []
            for key, fn in (
                ("summary", lambda: financial.summarize_transactions(
                    df, roles, time_col).as_dict()),
                ("network", lambda: financial.build_transfer_network(df, roles).as_dict()),
                ("patterns", lambda: financial.detect_patterns(df, roles, time_col)),
                ("currency", lambda: financial.currency_analysis(df, roles)),
                ("reconciliation", lambda: _reconciliation(df, roles)),
                ("performance", lambda: _payment_performance(df, roles)),
            ):
                try:
                    out["modules"][key] = fn()
                except Exception as exc:  # noqa: BLE001 - degrade, do not fail
                    failed_modules.append(key)
                    out["modules"][key] = {
                        "status": "failed",
                        "reason": f"{exc.__class__.__name__}: {exc}",
                        "warnings": [],
                    }
                    logger.exception("financial module %s failed", key)
            if failed_modules:
                warnings = list(ctx.get("warnings") or [])
                warnings.append("Financial modules failed and were skipped: "
                                + ", ".join(failed_modules)
                                + ". Other results are unaffected.")
                ctx["warnings"] = warnings
            ctx["financial"] = out
            patterns = out["modules"].get("patterns") or {}
            n_find = int(patterns.get("total", 0) or 0)
            nodes = int((out["modules"].get("network") or {}).get("node_count", 0) or 0)
            if len(failed_modules) == 6:
                raise _SkipStage("Every financial module failed on this dataset: "
                                 + ", ".join(failed_modules))
            detail = f"network {nodes} nodes, {n_find} findings"
            if failed_modules:
                detail += f" ({len(failed_modules)} module(s) failed: " \
                          + ", ".join(failed_modules) + ")"
            return {"_detail": detail, **out}

        # ---------------------------------------------------------------- --
        if name == "charts":
            assert df is not None
            charts = eda.build_charts(df, ctx["profiles"], ctx["semantic_map"],
                                      ctx.get("relationships"))
            # add network/sankey chart when financial module produced a graph
            fin = ctx.get("financial") or {}
            net = (fin.get("modules") or {}).get("network") or {}
            if net.get("status") == "completed" and net.get("edges"):
                top = sorted(net["edges"], key=lambda e: -e["value"])[:25]
                sankey = [{"source": e["source"], "target": e["target"],
                           "value": round(max(e["value"], 0.0001), 2)} for e in top]
                charts.insert(0, {
                    "id": "flow_sankey", "type": "sankey",
                    "title": "Top money flows (source → destination)",
                    "subtitle": f"Top {len(sankey)} aggregated edges by value",
                    "columns": ["source", "destination"], "data": sankey,
                    "x": "source", "y": "value", "series": ["target"],
                    "relevance": 0.97, "note": "Aggregated server-side; filtered top edges.",
                })
            ctx["charts"] = charts
            return {"_detail": f"{len(charts)} chart(s) generated", "charts": charts}

        # ---------------------------------------------------------------- --
        if name == "findings":
            assert df is not None
            findings = _compile_findings(ctx)
            ctx["findings"] = findings
            return {"_detail": f"{len(findings['key_findings'])} key findings", **findings}

        # ---------------------------------------------------------------- --
        if name == "workspace":
            if not ctx.get("profiles") or not ctx.get("inference"):
                raise RuntimeError("Schema inference produced no result — cannot assemble "
                                   "the workspace. Fix the dataset or mapping and retry.")
            manifest = _build_manifest(ctx, run)
            ctx["manifest"] = manifest
            path = ctx["artifact_dir"] / "manifest.json"
            _save_json(path, manifest)
            run = db.get(AnalysisRun, run.id)
            run.manifest_path = str(path)
            db.commit()
            return {"_detail": f"workspace built with {len(manifest['modules'])} modules",
                    "modules": manifest["modules"]}

        # ---------------------------------------------------------------- --
        if name == "report":
            if not ctx.get("manifest"):
                raise RuntimeError("Workspace manifest missing — reports cannot be built.")
            from .reports import build_reports
            paths = build_reports(ctx["manifest"], ctx, ctx["artifact_dir"])
            return {"_detail": f"{len(paths)} report artifact(s) prepared",
                    "reports": [{"kind": k, "path": str(p)} for k, p in paths.items()]}

        raise RuntimeError(f"unknown stage {name}")


class _SkipStage(Exception):
    pass


def _elapsed_seconds(started) -> float:
    """Seconds since run start, tolerant of naive datetimes from SQLite."""
    if started is None:
        return 0.0
    if started.tzinfo is None:
        from datetime import timezone as _tz
        started = started.replace(tzinfo=_tz.utc)
    return max(0.0, (utcnow() - started).total_seconds())


def _required(stage_name: str) -> bool:
    return next(s["required"] for s in STAGES if s["name"] == stage_name)


def csv_validate(raw: bytes, filename: str):
    from .csv_io import validate_csv_bytes
    return validate_csv_bytes(raw, filename)


def _read(raw: bytes, delimiter: str, encoding: str):
    from .csv_io import read_csv
    return read_csv(raw, delimiter=delimiter, encoding=encoding)


def _resolve_roles(semantic_map: dict[str, str]) -> dict[str, str | None]:
    wanted = ["source_account", "destination_account", "sender", "receiver",
              "amount_source", "amount_destination", "currency_source",
              "currency_destination", "fx_rate", "fee_amount", "transaction_time",
              "settlement_time", "status", "category", "country", "institution",
              "payment_rail", "customer_id", "merchant_id", "device", "risk_label",
              "email", "phone", "datetime", "target"]
    inv: dict[str, str | None] = {}
    for role in wanted:
        inv[role] = next((c for c, r in semantic_map.items() if r == role), None)
    return inv


def _reconciliation(df: pd.DataFrame, roles: dict[str, str | None]) -> dict:
    cols = [c for c in df.columns if "reconcil" in c.lower()
            or "settlement" in c.lower()]
    if not cols:
        return {"status": "unavailable",
                "reason": "No reconciliation columns (expected/observed settlement) in this file."}
    out: dict = {"status": "completed", "columns": cols}
    status_col = next((c for c in cols if c.endswith("status")), None)
    if status_col:
        vc = df[status_col].astype(str).str.strip().value_counts().head(10)
        out["status_breakdown"] = [{"status": str(k), "count": int(v),
                                    "pct": round(100 * v / max(len(df), 1), 2)}
                                   for k, v in vc.items()]
    e = next((c for c in cols if c.startswith("expected_settlement_amount")), None)
    o = next((c for c in cols if c.startswith("observed_settlement_amount")), None)
    if e and o:
        ev = pd.to_numeric(df[e], errors="coerce")
        ov = pd.to_numeric(df[o], errors="coerce")
        m = ev.notna() & ov.notna()
        diff = (ev[m] - ov[m])
        out["comparison"] = {
            "compared_rows": int(m.sum()),
            "matched": int((diff.abs() <= 0.01).sum()),
            "mismatched": int((diff.abs() > 0.01).sum()),
            "total_difference": round(float(diff.sum()), 4),
            "max_abs_difference": round(float(diff.abs().max()), 4) if m.sum() else None,
        }
    diff_col = next((c for c in cols if "difference_amount" in c), None)
    if diff_col:
        d = pd.to_numeric(df[diff_col], errors="coerce").dropna()
        if len(d):
            out["difference_stats"] = {
                "count": int(len(d)), "non_zero": int((d.abs() > 0.01).sum()),
                "sum": round(float(d.sum()), 4),
                "max": round(float(d.abs().max()), 4),
            }
    return out


def _payment_performance(df: pd.DataFrame, roles: dict[str, str | None]) -> dict:
    out: dict = {"status": "unavailable", "reason": "No status column detected."}
    status_col = roles.get("status")
    if not status_col or status_col not in df.columns:
        return out
    out["status"] = "completed"
    st = df[status_col].astype(str).str.strip().str.lower()
    n = max(len(df), 1)
    from .financial import FAILED_STATES, PENDING_STATES, SUCCESS_STATES
    out["rates"] = {
        "success_pct": round(100 * float(st.isin(SUCCESS_STATES).sum()) / n, 2),
        "failure_pct": round(100 * float(st.isin(FAILED_STATES).sum()) / n, 2),
        "pending_pct": round(100 * float(st.isin(PENDING_STATES).sum()) / n, 2),
        "denominator": "all rows in the uploaded file",
    }
    # duration columns
    for label, pat in (("processing", r"processing_duration"),
                       ("settlement", r"settlement_duration")):
        col = next((c for c in df.columns if re_search(pat, c)), None)
        if col:
            v = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(v):
                out[label] = {
                    "column": col, "count": int(len(v)),
                    "mean_seconds": round(float(v.mean()), 2),
                    "median_seconds": round(float(v.median()), 2),
                    "p95_seconds": round(float(v.quantile(0.95)), 2),
                    "max_seconds": round(float(v.max()), 2),
                }
    # by channel
    chan = roles.get("payment_rail") or roles.get("category")
    if chan and chan in df.columns:
        g = pd.crosstab(df[chan].astype(str).str.strip(), st)
        rows = []
        for idx, row in g.head(15).iterrows():
            total = int(row.sum())
            rows.append({
                "channel": str(idx)[:40], "total": total,
                "success_pct": round(100 * float(row.get("success", 0)) / max(total, 1), 2),
                "failure_pct": round(100 * float(row.get("failed", 0)) / max(total, 1), 2),
            })
        out["by_channel"] = rows
    return out


def re_search(pat: str, s: str) -> bool:
    import re
    return bool(re.search(pat, s, re.I))


def _compile_findings(ctx: dict) -> dict:
    """Assemble a cross-module 'most important findings' list with provenance."""
    items: list[dict] = []
    overview = ctx.get("overview", {})
    quality = ctx.get("quality")
    rel = ctx.get("relationships", {})
    fin = ctx.get("financial") or {}
    manifest_charts = ctx.get("charts") or []
    anomaly = ((ctx.get("ml_results") or {}).get("anomaly")) if ctx.get("ml_results") else None

    if quality:
        items.append({
            "id": "quality", "category": "Data quality",
            "title": f"Data quality score {quality.score}/100 (grade {quality.grade})",
            "detail": " ".join(quality.summary[:2]),
            "kind": "observed", "evidence": "Computed over all rows and cells.",
        })
    if overview:
        items.append({
            "id": "shape", "category": "Dataset",
            "title": f"{overview['row_count']:,} rows × {overview['column_count']} columns "
                     f"with {overview['missing_pct']}% missing cells",
            "detail": overview.get("sampling_note", ""),
            "kind": "observed", "evidence": "Exact counts from the parsed file.",
        })
    if rel.get("strong_pairs"):
        top = rel["strong_pairs"][0]
        items.append({
            "id": "rel", "category": "Relationships",
            "title": f"Strongest relationship: {top['a']} ↔ {top['b']} "
                     f"(r = {top['pearson']})",
            "detail": f"{top['strength']} {'' if top['pearson'] >= 0 else 'negative'}"
                      f"linear association. {top['note']}",
            "kind": "statistical_inference",
            "evidence": "Pearson correlation over complete pairwise observations.",
        })
    # ML findings
    ml_block = ctx.get("ml_block") or {}
    sup = ml_block.get("supervised") or {}
    if sup.get("status") == "completed":
        if sup.get("metrics"):
            mname = ", ".join(f"{k}={v}" for k, v in list(sup["metrics"].items())[:4])
            items.append({
                "id": "ml", "category": "Machine learning",
                "title": f"{sup.get('best_model', 'Model')} "
                         f"({sup.get('task', '')}) — {mname}",
                "detail": f"Split: {sup.get('split_strategy')}. "
                          f"Excluded label columns: {', '.join(sup.get('excluded_features', [])[:6]) or 'none'}.",
                "kind": "model_output",
                "evidence": f"Hold-out evaluation on {sup.get('test_size', 0):,} rows.",
            })
        if sup.get("feature_importance"):
            fi = sup["feature_importance"][:3]
            items.append({
                "id": "ml_imp", "category": "Machine learning",
                "title": "Top predictive features: " +
                         ", ".join(f["feature"] for f in fi),
                "detail": "Model-native importance; association only, not causal.",
                "kind": "model_output",
                "evidence": f"From {sup.get('best_model')} trained on this dataset.",
            })
    anomaly = ml_block.get("anomaly") or {}
    if anomaly.get("status") == "completed":
        items.append({
            "id": "anomaly", "category": "Anomalies",
            "title": f"{anomaly['metrics'].get('flagged', 0):,} rows flagged as anomalies "
                     f"({anomaly['metrics'].get('flagged_pct', 0)}%) by IsolationForest",
            "detail": "Unsupervised rarity score — not a fraud determination. "
                      + " ".join(anomaly.get("limitations", [])[:1]),
            "kind": "model_output",
            "evidence": f"{anomaly.get('sample_size', 0):,} rows scored.",
        })
    net = (fin.get("modules") or {}).get("network") or {}
    if net.get("status") == "completed":
        items.append({
            "id": "network", "category": "Money flow",
            "title": f"Transfer network: {net['node_count']:,} entities, "
                     f"{net['edge_count']:,} aggregated flows",
            "detail": f"Weakly connected components: "
                      f"{net['metrics'].get('weakly_connected_components', '—')}. "
                      f"{net.get('warnings', [''])[0]}",
            "kind": "observed",
            "evidence": "Aggregated from source→destination pairs in the file.",
        })
    patterns = (fin.get("modules") or {}).get("patterns") or {}
    for f in (patterns.get("findings") or [])[:4]:
        items.append({
            "id": f"pat_{f['kind']}_{f['entity'][:8]}", "category": "Potential anomalies",
            "title": f["title"], "detail": f["evidence"],
            "kind": "rule_trigger",
            "evidence": f["method"],
            "severity": f["severity"],
        })
    fx = (fin.get("modules") or {}).get("currency") or {}
    if fx.get("status") == "completed" and fx.get("native_totals"):
        totals = ", ".join(f"{t['currency']} {t.get('native_total')}"
                           for t in fx["native_totals"][:3])
        items.append({
            "id": "fx", "category": "Currency",
            "title": f"Native-currency totals: {totals}",
            "detail": "Amounts are never summed across currencies. " +
                      " ".join(fx.get("warnings", [])[:1]),
            "kind": "observed",
            "evidence": "Grouped sums per currency code column.",
        })

    if not items:
        items.append({
            "id": "none", "category": "Dataset", "title": "Analysis completed",
            "detail": "No standout finding crossed the reporting thresholds.",
            "kind": "observed", "evidence": "",
        })
    return {
        "key_findings": items,
        "provenance": {
            "dataset": {"rows": overview.get("row_count"),
                        "columns": overview.get("column_count")},
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "note": "Each finding is labeled observed / statistical_inference / "
                    "model_output / rule_trigger.",
        },
    }


def _build_manifest(ctx: dict, run: AnalysisRun) -> dict:
    caps = ctx["inference"].capabilities
    modules = []
    module_plan = [
        ("overview", "Dataset overview", True),
        ("quality", "Data quality", True),
        ("exploration", "Exploratory analysis", True),
        ("relationships", "Statistical relationships", caps["relationships"]["state"].startswith("available")),
        ("ml", "Machine learning", True),
        ("anomaly", "Anomaly detection", caps["ml_anomaly"]["state"].startswith("available")),
        ("financial", "Financial transfers", ctx.get("financial", {}).get("activated", False)),
        ("network", "Transfer network", (ctx.get("financial", {}).get("modules", {})
                                         .get("network", {}) or {}).get("status") == "completed"),
        ("currency", "Currency analytics", caps["currency"]["state"].startswith("available")),
        ("payments", "Payment performance", caps["payments"]["state"].startswith("available")),
        ("reconciliation", "Reconciliation", caps["reconciliation"]["state"].startswith("available")),
        ("forecast", "Forecasting", (ctx.get("forecast") or {}).get("status") == "completed"),
        ("assistant", "AI dataset assistant", True),
        ("reports", "Reports", True),
    ]
    for key, label, active in module_plan:
        state = "active" if active else "inactive"
        reason = ""
        if not active:
            reason = (caps.get(key, {}) or {}).get("reason") or \
                "Prerequisite columns were not detected in this dataset."
            if key in ("network", "financial") and not reason:
                reason = "Transaction source/destination columns not detected."
        modules.append({"key": key, "label": label, "state": state, "reason": reason})

    manifest = {
        "run_id": run.id,
        "dataset_id": run.dataset_id,
        "filename": run.dataset.original_filename,
        "brand": config.BRAND,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "analysis_version": "1.0",
        "dataset_version": run.dataset.checksum[:12] or run.dataset.id[:12],
        "columns": [c.as_dict() for c in ctx["profiles"]],
        "semantic_map": ctx["semantic_map"],
        "roles": ctx.get("roles", {}),
        "capabilities": caps,
        "modules": modules,
        "overview": ctx.get("overview", {}),
        "quality": ctx.get("quality").as_dict() if ctx.get("quality") else None,
        "stats": ctx.get("stats", {}),
        "relationships": ctx.get("relationships", {}),
        "forecast": ctx.get("forecast", {}),
        "ml": ctx.get("ml_block", {}),
        "financial": ctx.get("financial", {}),
        "charts": ctx.get("charts", []),
        "findings": ctx.get("findings", {}),
        "cleaning": ctx.get("cleaning", {}),
        "plan": ctx.get("plan", {}),
        "warnings": (ctx.get("inference").warnings if ctx.get("inference") else [])
                    + (ctx.get("quality").summary if ctx.get("quality") else []),
        "limitations": _manifest_limitations(ctx),
    }
    return manifest


def _manifest_limitations(ctx: dict) -> list[str]:
    lim = [
        "Statistical association does not imply causation.",
        "Uploaded files are user-provided; synthetic labels do not prove fraud.",
    ]
    fx = config.fx_provider_configured()
    if not fx:
        lim.append("No live exchange-rate provider is configured — currency analysis "
                   "uses only rates embedded in the uploaded file.")
    if config.ai_configured():
        lim.append(f"AI narration is enabled ({config.AI_PROVIDER}); the model explains "
                   "computed values only and never calculates them.")
    else:
        lim.append("No LLM provider is configured — the assistant answers from "
                   "computed results using a rule-based planner.")
    if ctx.get("sampled"):
        lim.append("Some statistics were computed on a sample of the dataset.")
    return lim


# ------------------------------------------------------------- helpers ------
def _get_job(db, run_id: str, name: str) -> Job:
    job = db.scalar(select(Job).where(Job.run_id == run_id, Job.name == name))
    if job is None:
        stage = next(s for s in STAGES if s["name"] == name)
        job = Job(run_id=run_id, name=name, label=stage["label"],
                  required=stage["required"])
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


def _save_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, default=_json_default), encoding="utf-8")
    return str(path)


def _json_default(o):
    import numpy as np
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if (v != v or v in (float("inf"), float("-inf"))) else v
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, (datetime,)):
        return o.isoformat(timespec="seconds")
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _finish_stage(db, run_id: str, name: str, status: str, detail: str) -> None:
    job = db.scalar(select(Job).where(Job.run_id == run_id, Job.name == name))
    if job:
        job.status = status
        job.detail = detail
        job.finished_at = utcnow()
        db.commit()


def _mark_run_failed(run_id: str, tb: str) -> None:
    db = SessionLocal()
    try:
        run = db.get(AnalysisRun, run_id)
        if run:
            run.status = "failed"
            run.error = tb[-3000:]
            run.finished_at = utcnow()
            db.commit()
    finally:
        db.close()


class StageWatchdog:
    """Fails runs whose current stage outlives the configured budget.

    Without this a single hung stage leaves the run 'running' forever: the
    workspace screen polls, never finishes, and the user sees a pipeline that
    looks like it timed out. The watchdog stamps the run and the running job
    with a clear timeout message so the UI can offer a retry.
    """

    def __init__(self, limit_seconds: int, poll_seconds: int = 10):
        self.limit = max(30, limit_seconds)
        self.poll = poll_seconds
        self._progress: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def note_progress(self, run_id: str, stage: str) -> None:
        with self._lock:
            self._progress[run_id] = (stage, time.monotonic())

    def forget(self, run_id: str) -> None:
        with self._lock:
            self._progress.pop(run_id, None)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="finsentry-watchdog",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.poll):
            cutoff = time.monotonic() - self.limit
            with self._lock:
                stale = [(rid, st) for rid, (st, ts) in self._progress.items() if ts < cutoff]
            for run_id, stage in stale:
                self._fail(run_id, stage)

    def _fail(self, run_id: str, stage: str) -> None:
        minutes = self.limit / 60
        message = (f"Stage '{stage}' exceeded the {minutes:.0f} minute limit and was "
                   f"abandoned. Retry the run, or upload a smaller file if this repeats.")
        db = SessionLocal()
        try:
            run = db.get(AnalysisRun, run_id)
            if run is None or run.status in ("completed", "partial", "failed", "cancelled"):
                self.forget(run_id)
                return
            run.status = "failed"
            run.error = message
            run.finished_at = utcnow()
            for job in db.scalars(select(Job).where(Job.run_id == run_id,
                                                    Job.status == "running")):
                job.status = "failed"
                job.error = message
                job.detail = "timed out"
                job.finished_at = utcnow()
            db.commit()
        finally:
            db.close()
        _abandon(run_id)
        self.forget(run_id)


watchdog = StageWatchdog(config.STAGE_TIMEOUT_SECONDS)

runner = PipelineRunner()


def load_frame_for_run(run: AnalysisRun) -> pd.DataFrame:
    """Reload the parsed (or raw) frame for a completed run."""
    art = Path(run.artifact_dir) / "parsed.csv"
    if art.exists():
        return pd.read_csv(art, low_memory=False, nrows=config.MAX_ROWS)
    from .csv_io import read_csv
    raw = Path(run.dataset.source_path).read_bytes()
    _, rows = read_csv(raw, run.dataset.delimiter, run.dataset.encoding)
    return pd.DataFrame(rows)
