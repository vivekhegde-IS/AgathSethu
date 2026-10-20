"""
AGHAT SETHU — Citizen account: payment history, notifications, crash reports

Citizens only (require_citizen); every query is scoped to the logged-in user.

  GET  /api/citizen/payments                     own payment receipts, newest first
  GET  /api/citizen/notifications                own stored alerts, newest first
  POST /api/citizen/notifications/{id}/read      mark one read
  POST /api/citizen/notifications/read-all       mark all read
  GET  /api/citizen/incidents/{incident_id}      crash report summary, only for an
                                                 incident one of the user's vehicles is in
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_citizen
from app.models.citizen_fines import Fine, FinePayment, Notification
from app.models.models import Incident, IncidentVehicle, User, Vehicle
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


def _notification_view(n: Notification) -> dict:
    return {"id": str(n.id), "kind": n.kind, "title": n.title, "message": n.message,
            "incident_id": str(n.incident_id) if n.incident_id else None, "fine_id": n.fine_id,
            "plate_norm": n.plate_norm, "data": n.data or {}, "read": n.read_at is not None,
            "created_at": _iso(n.created_at)}


@router.get("/notifications")
def my_notifications(response: Response, user: User = Depends(require_citizen),
                     db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    rows = (db.query(Notification).filter(Notification.user_id == user.id)
            .order_by(Notification.created_at.desc()).limit(200).all())
    return {"unread": sum(1 for n in rows if n.read_at is None),
            "notifications": [_notification_view(n) for n in rows]}


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


@router.get("/incidents/{incident_id}")
def my_incident(incident_id: str, user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    """What a citizen may see about a crash their vehicle was involved in:
    reference, time, place, status and the involved plates. No camera frames,
    RFID data or other people's details beyond the plates involved."""
    plates = {v.plate_number for v in db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()}
    incident = db.get(Incident, incident_id)
    involved = (db.query(IncidentVehicle).filter(IncidentVehicle.incident_id == incident_id,
                                                 IncidentVehicle.role == "involved").all()
                if incident is not None else [])
    mine = sorted({v.plate_norm for v in involved if v.plate_norm in plates})
    if incident is None or not mine:
        raise HTTPException(status_code=404, detail="Incident not found")
    when = incident.created_at.astimezone(IST) if incident.created_at else None
    return {
        "id": str(incident.id),
        "reference": incident_reference(incident.id),
        "crash_at": _iso(when),
        "location": junction_label(incident.crash_junction),
        "status": "Resolved" if incident.status == "resolved" else "Under review",
        "resolved_at": _iso(incident.resolved_at.astimezone(IST) if incident.resolved_at else None),
        "your_vehicles": [format_plate(p) or p for p in mine],
        "involved_vehicles": sorted({format_plate(v.plate_norm) or v.plate_norm
                                     for v in involved if v.plate_norm}),
        # The system does not determine which vehicle caused the crash.
        "role_determined": False,
        "notifications": [_notification_view(n) for n in db.query(Notification)
                          .filter(Notification.user_id == user.id, Notification.kind == KIND_CRASH,
                                  Notification.incident_id == incident.id).all()],
    }
