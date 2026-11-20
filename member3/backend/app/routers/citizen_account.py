"""
AGHAT SETHU — Citizen account: payment history, notifications, crash reports

Citizens only (require_citizen); every query is scoped to the logged-in user.

  GET  /api/citizen/payments                     own payment receipts, newest first
  GET  /api/citizen/notifications                own stored alerts, newest first
  POST /api/citizen/notifications/{id}/read      mark one read
  POST /api/citizen/notifications/read-all       mark all read
  GET  /api/citizen/incidents/{incident_id}      crash report summary, only for an
                                                 incident one of the user's vehicles is in
  POST /api/citizen/incidents/{incident_id}/confirm
                                                 the owner's answer to "are you safe?"
                                                 (mobile app + website; see crash_response.py)

{incident_id} is either an incidents.id UUID or a crash key (CR-XXXXXXXXXX).
"""

from datetime import datetime, timezone

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_citizen
from app.models.citizen_fines import Fine, FinePayment, Notification
from app.models.live import CrashReport, CrashResponse
from app.models.models import Incident, IncidentVehicle, User, Vehicle
from app.services import crash_response
from app.services.notification_service import IST, KIND_CRASH, incident_reference, junction_label
from app.services.plate_validation import format_plate

router = APIRouter(prefix="/api/citizen", tags=["Citizen Account"])

NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _iso(value):
    return value.isoformat() if value else None


@router.get("/payments")
def my_payments(response: Response, user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    rows = (db.query(FinePayment, Fine).join(Fine, Fine.id == FinePayment.fine_id)
            .filter(FinePayment.user_id == user.id)
            .order_by(FinePayment.paid_at.desc(), FinePayment.id.desc()).all())
    return {
        "total_paid": sum(p.amount for p, _ in rows),
        "payments": [{
            "id": p.id, "reference": p.reference, "paid_at": _iso(p.paid_at), "amount": p.amount,
            "method": p.method, "fine_id": f.id, "number_plate": f.number_plate,
            "violation_type": f.violation_type, "detected_at": _iso(f.detected_at),
        } for p, f in rows],
    }


def _incident_ref(n: Notification) -> str | None:
    """The id the owner answers / opens: incidents.id, or the crash key of a
    live-pipeline crash notification (kind "crash")."""
    if n.incident_id:
        return str(n.incident_id)
    if n.kind == "crash":
        return (n.data or {}).get("incident_key")
    return None


def _notification_view(n: Notification, responses: dict | None = None, db: Session | None = None) -> dict:
    ref = _incident_ref(n)
    view = {"id": str(n.id), "kind": n.kind, "title": n.title, "message": n.message,
            "incident_id": ref, "fine_id": n.fine_id,
            "plate_norm": n.plate_norm, "data": n.data or {}, "read": n.read_at is not None,
            "created_at": _iso(n.created_at)}
    if responses is not None and ref:
        view["response"] = crash_response.response_view(db, responses.get(ref))
    return view


@router.get("/notifications")
def my_notifications(response: Response, user: User = Depends(require_citizen),
                     db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    rows = (db.query(Notification).filter(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc()).limit(200).all())
    responses = {r.incident_ref: r for r in db.query(CrashResponse).filter(CrashResponse.user_id == user.id)}
    return {"unread": sum(1 for n in rows if n.read_at is None),
            "notifications": [_notification_view(n, responses, db) for n in rows]}


@router.post("/notifications/read-all")
def read_all(user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    count = (db.query(Notification)
             .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
             .update({Notification.read_at: now}, synchronize_session=False))
    db.commit()
    return {"marked_read": count}


@router.post("/notifications/{notification_id}/read")
def read_one(notification_id: str, user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    note = db.get(Notification, notification_id)
    if note is None or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    if note.read_at is None:
        note.read_at = datetime.now(timezone.utc)
        db.commit()
    return _notification_view(note)


def _status_label(incident_status: str | None, answer: CrashResponse | None) -> str:
    if incident_status == "resolved":
        return "Resolved"
    if incident_status == "false_positive" or (answer is not None and answer.response == "false_alarm"
                                               and answer.review_status == "accepted"):
        return "False alarm"
    return "Under review"


def _my_crash(db: Session, user: User, key: str) -> dict:
    """A live-pipeline crash (CR-...): only the owner's own vehicles are shown -
    a partner naming stays with the authority until it is confirmed."""
    vehicle = crash_response.owned_vehicle(db, user, "crash", key)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    report = (db.query(CrashReport).filter(CrashReport.incident_key == key,
                                           CrashReport.vehicle_id == vehicle.id).first())
    answer = crash_response.find_response(db, user.id, key)
    plate = format_plate(vehicle.plate_number) or vehicle.plate_number
    notes = [n for n in db.query(Notification).filter(Notification.user_id == user.id,
                                                      Notification.kind == "crash")
             if (n.data or {}).get("incident_key") == key]
    return {
        "id": key, "reference": key,
        "crash_at": _iso(report.created_at.astimezone(IST) if report and report.created_at else None),
        "location": report.location if report else "an unknown junction",
        "status": _status_label(None, answer), "resolved_at": None,
        "your_vehicles": [plate], "involved_vehicles": [plate], "role_determined": False,
        "response": crash_response.response_view(db, answer),
        "notifications": [_notification_view(n) for n in notes],
    }


@router.get("/incidents/{incident_id}")
def my_incident(incident_id: str, response: Response, user: User = Depends(require_citizen),
                db: Session = Depends(get_db)):
    """What a citizen may see about a crash their vehicle was involved in:
    reference, time, place, status and the involved plates. No camera frames,
    RFID data or other people's details beyond the plates involved."""
    response.headers.update(NO_STORE)
    parsed = crash_response.parse_ref(incident_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    kind, incident_id = parsed
    if kind == "crash":
        return _my_crash(db, user, incident_id)
    plates = {v.plate_number for v in db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()}
    incident = db.get(Incident, incident_id)
    involved = (db.query(IncidentVehicle).filter(IncidentVehicle.incident_id == incident_id,
                                                 IncidentVehicle.role == "involved").all()
                if incident is not None else [])
    mine = sorted({v.plate_norm for v in involved if v.plate_norm in plates})
    if incident is None or not mine:
        raise HTTPException(status_code=404, detail="Incident not found")
    answer = crash_response.find_response(db, user.id, incident_id)
    when = incident.created_at.astimezone(IST) if incident.created_at else None
    return {
        "id": str(incident.id),
        "reference": incident_reference(incident.id),
        "crash_at": _iso(when),
        "location": junction_label(incident.crash_junction),
        "status": _status_label(incident.status, answer),
        "resolved_at": _iso(incident.resolved_at.astimezone(IST) if incident.resolved_at else None),
        "your_vehicles": [format_plate(p) or p for p in mine],
        "involved_vehicles": sorted({format_plate(v.plate_norm) or v.plate_norm
                                     for v in involved if v.plate_norm}),
        # The system does not determine which vehicle caused the crash.
        "role_determined": False,
        "notifications": [_notification_view(n) for n in db.query(Notification)
                          .filter(Notification.user_id == user.id, Notification.kind == KIND_CRASH,
                                  Notification.incident_id == incident.id).all()],
        "response": crash_response.response_view(db, answer),
    }


class CrashAnswer(BaseModel):
    """The mobile app sends {"accident_occurred": bool}; the website sends
    {"response": ...}. "response" wins when both are given."""
    accident_occurred: bool | None = None
    response: Literal["accident", "not_serious", "false_alarm"] | None = None
    note: str | None = Field(default=None, max_length=1000)
    channel: Literal["app", "web"] = "app"

    @model_validator(mode="after")
    def _one_answer(self):
        if self.response is None:
            if self.accident_occurred is None:
                raise ValueError("Send accident_occurred or response")
            self.response = "accident" if self.accident_occurred else "false_alarm"
        return self


@router.post("/incidents/{incident_id}/confirm")
def answer_crash(incident_id: str, body: CrashAnswer, user: User = Depends(require_citizen),
                 db: Session = Depends(get_db)):
    """The owner's answer to "are you safe?". Recorded at once and shown live to
    the authority; a false alarm / not serious only changes the incident after
    the authority accepts it."""
    parsed = crash_response.parse_ref(incident_id)
    if parsed is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    kind, ref = parsed
    vehicle = crash_response.owned_vehicle(db, user, kind, ref)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    row = crash_response.record_response(db, user, kind, ref, vehicle, body.response, body.note, body.channel)
    return crash_response.response_view(db, row)
