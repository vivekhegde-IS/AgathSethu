"""
AGHAT SETHU — Citizen notifications

Written once, when the event happens, inside the caller's session/transaction:
  - crash_involvement: a registered vehicle was recorded as involved in a crash
    incident (both vehicles of a two-vehicle crash get one each)
  - fine_issued: a fine was issued to the citizen's vehicle

Idempotent: the unique constraints on `notifications` plus the existence check
below mean a retried write never creates a second alert.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from app.models.citizen_fines import Fine, Notification
from app.models.models import Incident, Vehicle

IST = ZoneInfo("Asia/Kolkata")
KIND_CRASH = "crash_involvement"
KIND_FINE = "fine_issued"


def junction_label(junction_id: str | None) -> str:
    """J01 -> Junction 1 (the only names the system has)."""
    if junction_id and junction_id.upper().startswith("J") and junction_id[1:].isdigit():
        return f"Junction {int(junction_id[1:])}"
    return junction_id or "an unknown junction"


def incident_reference(incident_id) -> str:
    """Short, stable reference shown to people: first 8 hex chars of the id."""
    return f"INC-{str(incident_id).replace('-', '')[:8].upper()}"


def _owner_vehicle(session, plate_norm: str | None) -> Vehicle | None:
    if not plate_norm:
        return None
    return (session.query(Vehicle)
            .filter(Vehicle.plate_number == plate_norm, Vehicle.is_active.is_(True)).first())


def notify_crash_involvement(session, incident_id, plate_norm: str | None) -> Notification | None:
    """Alert the owner of `plate_norm` that their vehicle was involved."""
    vehicle = _owner_vehicle(session, plate_norm)
    if vehicle is None:
        return None
    exists = (session.query(Notification.id)
              .filter(Notification.user_id == vehicle.owner_id, Notification.kind == KIND_CRASH,
                      Notification.incident_id == incident_id,
                      Notification.plate_norm == plate_norm).first())
    if exists:
        return None
    incident = session.get(Incident, incident_id)
    when = incident.created_at.astimezone(IST) if incident is not None and incident.created_at else None
    where = junction_label(incident.crash_junction if incident is not None else None)
    reference = incident_reference(incident_id)
    note = Notification(
        user_id=vehicle.owner_id, kind=KIND_CRASH, incident_id=incident_id, plate_norm=plate_norm,
        title=f"Your vehicle {plate_norm} was involved in a road crash",
        message=(f"Crash incident {reference} was recorded at {where}"
                 + (f" on {when.strftime('%d %b %Y, %I:%M %p')} IST" if when else "")
                 + f". Your vehicle {plate_norm} is listed as involved. "
                 "Contact the traffic authority with this reference if you have questions."),
        data={"reference": reference, "junction_id": incident.crash_junction if incident is not None else None,
              "location": where, "crash_at": when.isoformat() if when else None},
    )
    session.add(note)
    return note


def notify_fine_issued(session, fine: Fine) -> Notification | None:
    exists = (session.query(Notification.id)
              .filter(Notification.user_id == fine.user_id, Notification.kind == KIND_FINE,
                      Notification.fine_id == fine.id).first())
    if exists:
        return None
    note = Notification(
        user_id=fine.user_id, kind=KIND_FINE, fine_id=fine.id, plate_norm=fine.number_plate,
        title=f"New e-challan for {fine.number_plate}",
        message=(f"A {fine.violation_type} violation was recorded for your vehicle {fine.number_plate}. "
                 f"Fine amount: Rs {fine.fine_amount:,.0f}. Challan no. {fine.id}."),
        data={"fine_id": fine.id, "amount": fine.fine_amount, "violation_type": fine.violation_type},
    )
    session.add(note)
    return note
