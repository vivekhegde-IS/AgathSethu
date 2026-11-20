"""
AGHAT SETHU — Live dashboards: owner /me, authority live feed + review queue,
and the /ws/events socket.

Owner (role citizen = "vehicle owner"); every query is scoped to the caller:
  GET  /api/me/overview                 own vehicle(s), fines, notifications, text messages
  POST /api/me/fines/{id}/dispute       dispute an unpaid fine
  POST /api/me/sms/read-all             mark text messages read
  (pay: existing POST /api/citizen/fines/{id}/pay, which now broadcasts fine.updated)

Authority:
  GET  /api/authority/live              fleet, recent fines, crash reports, review queue
  POST /api/authority/fines             issue a fine to a vehicle
  POST /api/authority/fines/{id}/uphold reject a dispute (back to Unpaid)
  POST /api/authority/review/{id}/confirm | /reject
  POST /api/authority/crash-responses/{id}/accept | /reject
                                        an owner's "false alarm" / "not serious" answer

Socket: /ws/events. The first message must be {"type": "auth", "token": "<JWT>"}
(kept out of the URL so it never lands in access logs). The server then puts
the socket in `authority` or `user:<id>` - the client cannot choose.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import false
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.fleet import normalize_plate
from app.dependencies.deps import require_authority, require_citizen, user_from_token
from app.models.citizen_fines import Fine, Notification
from app.models.live import CrashReport, CrashResponse, ReviewItem, SmsMessage
from app.models.models import User, Vehicle
from app.services import crash_response, events
from app.services.crash_notify import (decide_review, notification_view, report_view, review_view,
                                       vehicle_view)
from app.services.live_fines import fine_view, issue_fine, publish_fine
from app.services.sms import sms_view

router = APIRouter(tags=["Live dashboards"])
NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}
AUTH_TIMEOUT_S = 10.0


# ── owner ────────────────────────────────────────────────────────────────────────
@router.get("/api/me/overview")
def my_overview(response: Response, user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    vehicles = db.query(Vehicle).filter(Vehicle.owner_id == user.id).order_by(Vehicle.plate_number).all()
    fines = (db.query(Fine).filter(Fine.user_id == user.id)
             .order_by(Fine.detected_at.desc(), Fine.id.desc()).limit(200).all())
    notes = (db.query(Notification).filter(Notification.user_id == user.id)
             .order_by(Notification.created_at.desc()).limit(200).all())
    sms = (db.query(SmsMessage).filter(SmsMessage.user_id == user.id)
           .order_by(SmsMessage.created_at.desc()).limit(100).all())
    reports = (db.query(CrashReport)
               .filter(CrashReport.vehicle_id.in_([v.id for v in vehicles]) if vehicles else false(),
                       CrashReport.source == "own")
               .order_by(CrashReport.created_at.desc()).limit(50).all())
    return {
        "user": {"id": str(user.id), "username": user.username, "full_name": user.full_name,
                 "phone": user.phone, "google_linked": user.google_sub is not None,
                 "google_email": user.google_email},
        "vehicles": [vehicle_view(v) for v in vehicles],
        "fines": [fine_view(db, f) for f in fines],
        "notifications": [notification_view(n) for n in notes],
        "unread": sum(1 for n in notes if n.read_at is None),
        "sms": [sms_view(m) for m in sms],
        "sms_unread": sum(1 for m in sms if m.read_at is None),
        "crashes": [report_view(db, r, for_authority=False) for r in reports],
    }


class DisputeRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/api/me/fines/{fine_id}/dispute")
def dispute_fine(fine_id: int, body: DisputeRequest, user: User = Depends(require_citizen),
                 db: Session = Depends(get_db)):
    fine = (db.query(Fine).filter(Fine.id == fine_id, Fine.user_id == user.id)
            .with_for_update().one_or_none())
    if fine is None:
        raise HTTPException(status_code=404, detail="Fine not found")
    if fine.status != "Unpaid":
        raise HTTPException(status_code=409, detail=f"A {fine.status.lower()} fine cannot be disputed")
    fine.status, fine.dispute_reason = "Disputed", body.reason.strip()
    fine.disputed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(fine)
    publish_fine(db, fine, "fine.updated")
    return fine_view(db, fine)


@router.post("/api/me/sms/read-all")
def read_all_sms(user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    count = (db.query(SmsMessage).filter(SmsMessage.user_id == user.id, SmsMessage.read_at.is_(None))
             .update({SmsMessage.read_at: datetime.now(timezone.utc)}, synchronize_session=False))
    db.commit()
    return {"marked_read": count}


# ── authority ────────────────────────────────────────────────────────────────────
@router.get("/api/authority/live", dependencies=[Depends(require_authority)])
def authority_live(response: Response, db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    crash_response.sweep_overdue(db)
    fleet = db.query(Vehicle).filter(Vehicle.carla_letter.isnot(None)).order_by(Vehicle.carla_letter).all()
    fines = db.query(Fine).order_by(Fine.detected_at.desc(), Fine.id.desc()).limit(100).all()
    reports = db.query(CrashReport).order_by(CrashReport.created_at.desc()).limit(100).all()
    reviews = (db.query(ReviewItem).order_by((ReviewItem.status == "pending").desc(),
                                             ReviewItem.created_at.desc()).limit(100).all())
    answers = (db.query(CrashResponse).order_by((CrashResponse.review_status == "pending").desc(),
                                                CrashResponse.responded_at.desc()).limit(100).all())
    return {
        "fleet": [vehicle_view(v, db.get(User, v.owner_id)) for v in fleet],
        "fines": [fine_view(db, f, for_authority=True) for f in fines],
        "crashes": [report_view(db, r, for_authority=True) for r in reports],
        "reviews": [review_view(db, r) for r in reviews],
        "pending_reviews": sum(1 for r in reviews if r.status == "pending"),
        "responses": [crash_response.response_view(db, r, for_authority=True)
                      | {"case": crash_response.case_view(db, r.incident_ref)} for r in answers],
        "pending_responses": sum(1 for r in answers if r.review_status == "pending"),
    }


class IssueFineRequest(BaseModel):
    vehicle: str = Field(description="CARLA letter A-H, or a registered plate")
    amount: float = Field(gt=0, le=100000)
    reason: str = Field(min_length=3, max_length=100)
    location: str | None = Field(default=None, max_length=255)

    @field_validator("reason", "location")
    @classmethod
    def _strip(cls, v):
        return " ".join(v.split()) if isinstance(v, str) else v


def _vehicle(db: Session, ref: str) -> Vehicle | None:
    ref = (ref or "").strip().upper()
    if len(ref) == 1:
        return db.query(Vehicle).filter(Vehicle.carla_letter == ref).one_or_none()
    return db.query(Vehicle).filter(Vehicle.plate_number == normalize_plate(ref)).one_or_none()


@router.post("/api/authority/fines", status_code=status.HTTP_201_CREATED)
def authority_issue_fine(body: IssueFineRequest, authority: User = Depends(require_authority),
                         db: Session = Depends(get_db)):
    vehicle = _vehicle(db, body.vehicle)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="No registered vehicle matches")
    fine = issue_fine(db, authority, vehicle, body.amount, body.reason, body.location)
    return fine_view(db, fine, for_authority=True)


@router.post("/api/authority/fines/{fine_id}/uphold", dependencies=[Depends(require_authority)])
def uphold_fine(fine_id: int, db: Session = Depends(get_db)):
    fine = db.query(Fine).filter(Fine.id == fine_id).with_for_update().one_or_none()
    if fine is None:
        raise HTTPException(status_code=404, detail="Fine not found")
    if fine.status != "Disputed":
        raise HTTPException(status_code=409, detail="Only a disputed fine can be upheld")
    fine.status = "Unpaid"
    db.commit()
    db.refresh(fine)
    publish_fine(db, fine, "fine.updated")
    return fine_view(db, fine, for_authority=True)


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


def _decide(review_id: int, confirm: bool, body: DecisionRequest | None, authority: User, db: Session):
    item = db.query(ReviewItem).filter(ReviewItem.id == review_id).with_for_update().one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Review item not found")
    if item.status != "pending":
        raise HTTPException(status_code=409, detail=f"Already {item.status}")
    decide_review(db, item, authority, confirm, body.note if body else None)
    return review_view(db, item)


@router.post("/api/authority/review/{review_id}/confirm")
def confirm_review(review_id: int, body: DecisionRequest | None = None,
                   authority: User = Depends(require_authority), db: Session = Depends(get_db)):
    return _decide(review_id, True, body, authority, db)


@router.post("/api/authority/review/{review_id}/reject")
def reject_review(review_id: int, body: DecisionRequest | None = None,
                  authority: User = Depends(require_authority), db: Session = Depends(get_db)):
    return _decide(review_id, False, body, authority, db)


def _decide_answer(response_id: int, accept: bool, body: DecisionRequest | None, authority: User,
                   db: Session):
    row = db.query(CrashResponse).filter(CrashResponse.id == response_id).with_for_update().one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Owner response not found")
    if row.review_status != "pending":
        raise HTTPException(status_code=409, detail="This answer does not need a decision")
    crash_response.decide_response(db, row, authority, accept, body.note if body else None)
    return crash_response.response_view(db, row, for_authority=True)


@router.post("/api/authority/crash-responses/{response_id}/accept")
def accept_answer(response_id: int, body: DecisionRequest | None = None,
                  authority: User = Depends(require_authority), db: Session = Depends(get_db)):
    """Accept an owner's false alarm (incident -> false_positive) or not serious (severity -> low)."""
    return _decide_answer(response_id, True, body, authority, db)


@router.post("/api/authority/crash-responses/{response_id}/reject")
def reject_answer(response_id: int, body: DecisionRequest | None = None,
                  authority: User = Depends(require_authority), db: Session = Depends(get_db)):
    """Keep treating it as a crash; the owner is told."""
    return _decide_answer(response_id, False, body, authority, db)


# ── socket ───────────────────────────────────────────────────────────────────────
def _rooms_for(token: str | None):
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        if user is None:
            return None, None
        if user.role in ("authority", "admin"):
            return user, {events.AUTHORITY_ROOM}
        return user, {events.user_room(user.id)}
    finally:
        db.close()


@router.websocket("/ws/events")
async def events_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT_S)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    token = first.get("token") if isinstance(first, dict) and first.get("type") == "auth" else None
    user, rooms = await asyncio.to_thread(_rooms_for, token)
    if user is None:
        await websocket.send_json({"type": "error", "detail": "Invalid or expired token"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    sub_id, sub = events.hub.subscribe(rooms)
    await websocket.send_json({"type": "ready", "role": user.role, "user_id": str(user.id)})

    async def _send():
        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), timeout=25.0)
            except asyncio.TimeoutError:
                event = {"type": "ping"}
            if sub.dropped:
                await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
                return
            await websocket.send_json(event)

    async def _receive():
        while True:
            await websocket.receive_text()      # pongs / keep-alives; detects disconnect

    tasks = [asyncio.create_task(_send()), asyncio.create_task(_receive())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        events.hub.unsubscribe(sub_id)
