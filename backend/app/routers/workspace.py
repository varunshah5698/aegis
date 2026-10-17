"""Workspace routes: the post-login dashboard surface.

Bookings (schedule a review), dataset comments (message threads), demo
checkout (orders), a dashboard overview, and the admin console. Everything
here requires a session cookie; admin endpoints additionally require the
account email to be listed in ADMIN_EMAILS.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import config
from ..database import get_db
from ..models import (
    AnalysisRun,
    AuditEvent,
    Booking,
    Dataset,
    DatasetComment,
    Order,
    User,
    utcnow,
)
from ..security import COOKIE_NAME, get_session_user

router = APIRouter(prefix="/api", tags=["workspace"])


def _me(request: Request, db) -> User:
    user = get_session_user(db, request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    return user


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# -------------------------------------------------------------- overview ----
@router.get("/workspaces/overview")
def overview(request: Request, db=Depends(get_db)):
    """Dashboard home numbers: datasets, runs by status, bookings, orders."""
    user = _me(request, db)
    ds_ids = list(db.scalars(
        select(Dataset.id).where(Dataset.deleted_at.is_(None),
                                 Dataset.user_id == user.id)))
    runs = list(db.scalars(
        select(AnalysisRun).where(AnalysisRun.user_id == user.id)))
    by_status: dict[str, int] = {}
    for r in runs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    upcoming = db.scalar(
        select(func.count()).select_from(Booking).where(
            Booking.user_id == user.id, Booking.status == "upcoming")) or 0
    orders = list(db.scalars(
        select(Order).where(Order.user_id == user.id)
        .order_by(Order.created_at.desc()).limit(5)))
    bookings = list(db.scalars(
        select(Booking).where(Booking.user_id == user.id,
                              Booking.status == "upcoming")
        .order_by(Booking.scheduled_at).limit(5)))
    latest_runs = sorted(
        runs, key=lambda r: r.created_at or utcnow(), reverse=True)[:5]
    return {
        "datasets": len(ds_ids),
        "runs_total": len(runs),
        "runs_by_status": by_status,
        "upcoming_bookings": upcoming,
        "latest_runs": [
            {"id": r.id, "dataset_id": r.dataset_id, "status": r.status,
             "progress": r.progress, "created_at": _iso(r.created_at)}
            for r in latest_runs
        ],
        "upcoming": [
            {"id": b.id, "topic": b.topic, "scheduled_at": _iso(b.scheduled_at),
             "status": b.status} for b in bookings
        ],
        "recent_orders": [
            {"id": o.id, "plan": o.plan, "amount_cents": o.amount_cents,
             "status": o.status, "created_at": _iso(o.created_at)}
            for o in orders
        ],
    }


# -------------------------------------------------------------- bookings ----
class BookingPayload(BaseModel):
    topic: str = Field(min_length=2, max_length=160)
    detail: str = Field(default="", max_length=600)
    scheduled_at: datetime


def _booking_out(b: Booking) -> dict:
    return {"id": b.id, "topic": b.topic, "detail": b.detail,
            "scheduled_at": _iso(b.scheduled_at), "status": b.status,
            "created_at": _iso(b.created_at)}


@router.get("/bookings")
def list_bookings(request: Request, db=Depends(get_db)):
    user = _me(request, db)
    rows = list(db.scalars(
        select(Booking).where(Booking.user_id == user.id)
        .order_by(Booking.scheduled_at)))
    return [_booking_out(b) for b in rows]


@router.post("/bookings", status_code=201)
def create_booking(payload: BookingPayload, request: Request, db=Depends(get_db)):
    user = _me(request, db)
    when = payload.scheduled_at
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when < utcnow():
        raise HTTPException(422, "Choose a future date and time for the review.")
    b = Booking(user_id=user.id, topic=payload.topic.strip(),
                detail=payload.detail.strip(), scheduled_at=when)
    db.add(b)
    db.add(AuditEvent(user_id=user.id, action="booking.create",
                      resource_type="booking", resource_id=b.id,
                      detail={"topic": b.topic}))
    db.commit()
    db.refresh(b)
    return _booking_out(b)


@router.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, request: Request, db=Depends(get_db)):
    user = _me(request, db)
    b = db.get(Booking, booking_id)
    if b is None or b.user_id != user.id:
        raise HTTPException(404, "Booking not found.")
    if b.status != "upcoming":
        raise HTTPException(409, f"Booking is already {b.status}.")
    b.status = "cancelled"
    db.add(AuditEvent(user_id=user.id, action="booking.cancel",
                      resource_type="booking", resource_id=b.id))
    db.commit()
    return _booking_out(b)


# -------------------------------------------------------------- comments ----
class CommentPayload(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _dataset_owned(dataset_id: str, user: User, db) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds is None or ds.deleted_at is not None:
        raise HTTPException(404, "Dataset not found.")
    if ds.user_id not in (None, user.id):
        raise HTTPException(403, "Not authorized for this dataset.")
    return ds


@router.get("/datasets/{dataset_id}/comments")
def list_comments(dataset_id: str, request: Request, db=Depends(get_db)):
    user = _me(request, db)
    _dataset_owned(dataset_id, user, db)
    rows = list(db.scalars(
        select(DatasetComment)
        .where(DatasetComment.dataset_id == dataset_id)
        .order_by(DatasetComment.created_at)))
    return [{"id": c.id, "author": c.author, "text": c.text,
             "created_at": _iso(c.created_at),
             "mine": c.user_id == user.id} for c in rows]


@router.post("/datasets/{dataset_id}/comments", status_code=201)
def post_comment(dataset_id: str, payload: CommentPayload, request: Request,
                 db=Depends(get_db)):
    user = _me(request, db)
    ds = _dataset_owned(dataset_id, user, db)
    text = payload.text.strip()
    if not text:
        raise HTTPException(422, "Message text must not be empty.")
    c = DatasetComment(dataset_id=ds.id, user_id=user.id,
                       author=user.display_name or user.email, text=text)
    db.add(c)
    db.add(AuditEvent(user_id=user.id, action="dataset.comment",
                      resource_type="dataset", resource_id=ds.id))
    db.commit()
    db.refresh(c)
    return {"id": c.id, "author": c.author, "text": c.text,
            "created_at": _iso(c.created_at), "mine": True}


# ---------------------------------------------------------------- orders ----
class CheckoutPayload(BaseModel):
    plan: str = Field(min_length=2, max_length=40)


@router.get("/orders")
def list_orders(request: Request, db=Depends(get_db)):
    user = _me(request, db)
    rows = list(db.scalars(
        select(Order).where(Order.user_id == user.id)
        .order_by(Order.created_at.desc())))
    return [{"id": o.id, "plan": o.plan, "amount_cents": o.amount_cents,
             "status": o.status, "created_at": _iso(o.created_at)} for o in rows]


@router.get("/plans")
def list_plans():
    return [{"key": k, "name": v["name"], "amount_cents": v["amount_cents"],
             "amount": f"${v['amount_cents'] / 100:,.2f}"}
            for k, v in config.PLANS.items()]


@router.post("/checkout", status_code=201)
def checkout(payload: CheckoutPayload, request: Request, db=Depends(get_db)):
    """Demo checkout: records the order as paid immediately.

    Clearly labelled demo behaviour — a live integration would create a
    pending order and confirm it from a payment-provider webhook.
    """
    user = _me(request, db)
    key = payload.plan.strip().lower()
    if key not in config.PLANS:
        raise HTTPException(422, f"Unknown plan: {payload.plan}.")
    plan = config.PLANS[key]
    o = Order(user_id=user.id, plan=key,
              amount_cents=plan["amount_cents"], status="paid")
    db.add(o)
    db.add(AuditEvent(user_id=user.id, action="order.checkout",
                      resource_type="order", resource_id=o.id,
                      detail={"plan": key, "mode": "demo"}))
    db.commit()
    db.refresh(o)
    return {"id": o.id, "plan": o.plan, "amount_cents": o.amount_cents,
            "amount": f"${o.amount_cents / 100:,.2f}",
            "status": o.status, "created_at": _iso(o.created_at),
            "note": "Demo checkout — no real payment was processed."}


# ----------------------------------------------------------------- admin ----
def _admin(request: Request, db) -> User:
    user = _me(request, db)
    if not config.is_admin_email(user.email):
        raise HTTPException(403, "Admin access only.")
    return user


@router.get("/admin/users")
def admin_users(request: Request, db=Depends(get_db), limit: int = 100):
    _admin(request, db)
    rows = list(db.scalars(select(User).order_by(User.created_at.desc())
                           .limit(min(limit, 500))))
    return [{"id": u.id, "email": u.email, "display_name": u.display_name,
             "is_active": u.is_active, "created_at": _iso(u.created_at)}
            for u in rows]


@router.get("/admin/datasets")
def admin_datasets(request: Request, db=Depends(get_db), limit: int = 100):
    _admin(request, db)
    rows = list(db.scalars(select(Dataset).order_by(Dataset.created_at.desc())
                           .limit(min(limit, 500))))
    return [{"id": d.id, "filename": d.original_filename,
             "user_id": d.user_id, "rows": d.row_count, "cols": d.column_count,
             "status": d.validation_status, "deleted": d.deleted_at is not None,
             "created_at": _iso(d.created_at)} for d in rows]


@router.get("/admin/runs")
def admin_runs(request: Request, db=Depends(get_db), limit: int = 100):
    _admin(request, db)
    rows = list(db.scalars(select(AnalysisRun).order_by(AnalysisRun.created_at.desc())
                           .limit(min(limit, 500))))
    return [{"id": r.id, "dataset_id": r.dataset_id, "user_id": r.user_id,
             "status": r.status, "progress": r.progress,
             "created_at": _iso(r.created_at)} for r in rows]


@router.get("/admin/audit")
def admin_audit(request: Request, db=Depends(get_db), limit: int = 100):
    _admin(request, db)
    rows = list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc())
                           .limit(min(limit, 500))))
    return [{"action": a.action, "user_id": a.user_id,
             "resource_type": a.resource_type, "resource_id": a.resource_id,
             "created_at": _iso(a.created_at)} for a in rows]
