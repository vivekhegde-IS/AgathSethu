"""
AGHAT SETHU — Owners' answers to a crash alert ("are you safe?").

The mobile app and the website both call
    POST /api/citizen/incidents/{ref}/confirm
with {"accident_occurred": bool} (the app's original shape) or
{"response": "accident" | "not_serious" | "false_alarm", "note": "..."}.

``ref`` is whatever id the owner's crash notification carries:
  * CR-XXXXXXXXXX  a crash_reports incident key (live crash pipeline)
  * <uuid>         an incidents.id (RFID / camera incident pipeline)

Rules
  * Only the owner of a vehicle the crash was raised for may answer. A car that
    was merely NAMED as a partner does not count (that stays with the review
    queue, see crash_notify.py), so the answer endpoint never leaks it.
  * "accident" needs no review: the control room just sees it.
  * "false_alarm" / "not_serious" wait for the authority (review_status =
    pending). Only an accepted answer changes the incident (false_positive /
    severity low), so a driver cannot hide a real crash with one tap.
  * Answering again replaces the answer. Switching back to "accident" after a
    false alarm was accepted reopens the incident.

Every change is committed first, then broadcast (services/events.py).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.citizen_fines import Notification
from app.models.live import CrashReport, CrashResponse
from app.models.models import Incident, IncidentVehicle, User, Vehicle
from app.services import events
from app.services.plate_validation import format_plate

RESPONSES = ("accident", "not_serious", "false_alarm")
RESPONSE_LABELS = {"accident": "Accident confirmed by owner",
                   "not_serious": "Owner reports: minor, not serious",
                   "false_alarm": "Owner reports: false alarm"}
KIND_REVIEW_OUTCOME = "review_outcome"     # no "crash" in the name: the app raises its alarm on those
_CRASH_KEY = re.compile(r"^CR-[0-9A-F]{10}$")


def parse_ref(ref: str) -> tuple[str, str] | None:
    """('crash', 'CR-...') or ('incident', '<uuid>'), None when it is neither."""
    ref = (ref or "").strip()
    if _CRASH_KEY.match(ref.upper()):
        return "crash", ref.upper()
    try:
        return "incident", str(uuid.UUID(ref))
    except ValueError:
        return None


def owned_vehicle(db: Session, user: User, kind: str, ref: str) -> Vehicle | None:
    """The caller's vehicle this crash was raised for, or None."""
    vehicles = db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()
    if not vehicles:
        return None
    if kind == "crash":
        report = (db.query(CrashReport)
                  .filter(CrashReport.incident_key == ref, CrashReport.source == "own",
                          CrashReport.vehicle_id.in_([v.id for v in vehicles]))
                  .order_by(CrashReport.created_at).first())
        return next((v for v in vehicles if report is not None and v.id == report.vehicle_id), None)
    by_plate = {v.plate_number: v for v in vehicles}
    involved = (db.query(IncidentVehicle)
                .filter(IncidentVehicle.incident_id == ref, IncidentVehicle.role == "involved",
                        IncidentVehicle.plate_norm.in_(list(by_plate))).first())
    return by_plate.get(involved.plate_norm) if involved is not None else None


def find_response(db: Session, user_id, ref: str) -> CrashResponse | None:
    return (db.query(CrashResponse)
            .filter(CrashResponse.user_id == user_id, CrashResponse.incident_ref == ref).one_or_none())


def _iso(value):
    return value.isoformat() if value else None


def response_view(db: Session, row: CrashResponse | None, for_authority: bool = False) -> dict | None:
    if row is None:
        return None
    view = {"id": row.id, "incident_id": row.incident_ref, "incident_ref": row.incident_ref,
            "ref_kind": row.ref_kind, "response": row.response,
            "accident_occurred": row.response != "false_alarm",
            "label": RESPONSE_LABELS.get(row.response, row.response), "note": row.note,
            "channel": row.channel, "responded_at": _iso(row.responded_at),
            "review_status": row.review_status, "review_note": row.review_note,
            "reviewed_at": _iso(row.reviewed_at)}
    if for_authority:
        owner = db.get(User, row.user_id)
        vehicle = db.get(Vehicle, row.vehicle_id) if row.vehicle_id else None
        view.update(owner_name=owner.full_name if owner else None,
                    owner_phone=owner.phone if owner else None,
                    plate=(format_plate(vehicle.plate_number) or vehicle.plate_number) if vehicle else None,
                    letter=vehicle.carla_letter if vehicle else None)
    return view


def _publish(db: Session, event_type: str, row: CrashResponse) -> None:
    events.publish(event_type, {"response": response_view(db, row, for_authority=False)},
                   user_ids=[row.user_id], authority=False)
    events.publish(event_type, {"response": response_view(db, row, for_authority=True)}, authority=True)


def _reopen_if_closed(db: Session, row: CrashResponse) -> None:
    """The owner now says it WAS an accident after a false alarm was accepted."""
    if row.ref_kind != "incident":
        return
    incident = db.get(Incident, row.incident_ref)
    if incident is not None and incident.status == "false_positive":
        incident.status = "under_investigation"
        incident.resolved_at = incident.resolved_by = None
        incident.resolution_note = None


def _mark_crash_notes_read(db: Session, user_id, kind: str, ref: str, now: datetime) -> None:
    """Answered = seen: the app's background service alarms on UNREAD crash
    notifications, so the phone must not ring again for this crash."""
    query = db.query(Notification).filter(Notification.user_id == user_id, Notification.read_at.is_(None))
    if kind == "incident":
        rows = query.filter(Notification.incident_id == ref).all()
    else:
        rows = [n for n in query.filter(Notification.kind == "crash")
                if (n.data or {}).get("incident_key") == ref]
    for note in rows:
        note.read_at = now


def record_response(db: Session, user: User, kind: str, ref: str, vehicle: Vehicle, response: str,
                    note: str | None, channel: str) -> CrashResponse:
    note = (note or "").strip()[:1000] or None
    row = find_response(db, user.id, ref)
    now = datetime.now(timezone.utc)
    _mark_crash_notes_read(db, user.id, kind, ref, now)
    if row is None:
        row = CrashResponse(user_id=user.id, vehicle_id=vehicle.id, incident_ref=ref, ref_kind=kind,
                            response=response, note=note, channel=channel, responded_at=now,
                            review_status=None if response == "accident" else "pending")
        db.add(row)
    else:
        if row.response != response:
            if response == "accident" and row.review_status == "accepted":
                _reopen_if_closed(db, row)
            row.review_status = None if response == "accident" else "pending"
            row.reviewed_by = row.reviewed_at = None
            row.review_note = None
        row.response, row.channel, row.responded_at = response, channel, now
        row.note = note if note is not None else row.note
    db.commit()
    db.refresh(row)
    _publish(db, "crash.response", row)
    return row


def decide_response(db: Session, row: CrashResponse, authority: User, accept: bool,
                    note: str | None) -> CrashResponse:
    """Accept or reject an owner's false-alarm / not-serious answer."""
    row.review_status = "accepted" if accept else "rejected"
    row.reviewed_by, row.reviewed_at = authority.id, datetime.now(timezone.utc)
    row.review_note = (note or "").strip()[:1000] or None
    if accept and row.ref_kind == "incident":
        incident = db.get(Incident, row.incident_ref)
        if incident is not None:
            if row.response == "false_alarm":
                incident.status = "false_positive"
                incident.resolved_at, incident.resolved_by = row.reviewed_at, authority.id
                incident.resolution_note = row.review_note or "Owner reported a false alarm; authority accepted."
            elif row.response == "not_serious":
                incident.severity = "low"
    vehicle = db.get(Vehicle, row.vehicle_id) if row.vehicle_id else None
    plate = (format_plate(vehicle.plate_number) or vehicle.plate_number) if vehicle else "your vehicle"
    what = "false alarm" if row.response == "false_alarm" else "minor crash"
    if accept:
        title, text = "Crash report updated", (f"The traffic authority accepted your report that the crash alert "
                                                f"for {plate} was a {what}.")
    else:
        title, text = "Crash still under review", (f"The traffic authority is still treating the crash alert for "
                                                   f"{plate} as an incident. Call 112 if you need help.")
    if row.review_note:
        text += f" Note: {row.review_note}"
    note_row = Notification(user_id=row.user_id, kind=KIND_REVIEW_OUTCOME, title=title, message=text,
                            plate_norm=vehicle.plate_number if vehicle else None,
                            data={"incident_key": row.incident_ref, "response_id": row.id,
                                  "review_status": row.review_status})
    db.add(note_row)
    db.commit()
    db.refresh(row)
    db.refresh(note_row)
    _publish(db, "crash.response_reviewed", row)
    from app.services.crash_notify import notification_view   # avoid an import cycle
    events.publish("notification.created", {"notification": notification_view(note_row)},
                   user_ids=[row.user_id], authority=False)
    return row
