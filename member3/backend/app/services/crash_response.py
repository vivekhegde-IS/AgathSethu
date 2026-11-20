"""
AGHAT SETHU — Owners' answers to a crash alert ("are you safe?") and the
crash case outcome that follows from them.

The mobile app and the website both call
    POST /api/citizen/incidents/{ref}/confirm
with {"accident_occurred": bool} (the app's original shape) or
{"response": "accident" | "not_serious" | "false_alarm", "note": "..."}.

``ref`` is whatever id the owner's crash notification carries:
  * CR-XXXXXXXXXX  a crash_reports incident key (live crash pipeline)
  * <uuid>         an incidents.id (RFID / camera incident pipeline)

Who may answer
  The owner of any vehicle the crash was raised for: the car whose sensors
  raised it and the car named as its partner (both get the "are you safe?"
  alert, see crash_notify.py). The accusation itself stays in the review queue.

Case outcome (crash_case_outcomes), re-evaluated on every answer
  "minor" = not_serious or false_alarm ("no need to involve the authority").
  * Every involved vehicle's owner answered minor  -> RESOLVED automatically
      (single-vehicle crash: that one owner; two-vehicle crash: both owners).
      An incidents row is set to status "resolved".
  * Any owner answered "accident"                  -> NOT RESOLVED
  * An owner has not answered within CRASH_PARTNER_ANSWER_WINDOW_S (30 s)
    of their alert: their answer is recorded as "no_answer" (severe), like
    the app's own 30 s auto-report as an accident  -> NOT RESOLVED (stays so)
  * Otherwise                                      -> WAITING
  A vehicle whose owner cannot answer (unregistered) never answers, so such
  a crash is never auto-resolved.
  NOT RESOLVED cases keep the minor answers "pending": the authority accepts
  (resolve: false alarm -> false_positive) or rejects them by hand.
  Changing an answer to "accident" later reopens an auto-resolved case.

Every change is committed first, then broadcast (services/events.py).
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.citizen_fines import Notification
from app.models.live import CrashCaseOutcome, CrashReport, CrashResponse
from app.models.models import Incident, IncidentAlert, IncidentVehicle, User, Vehicle
from app.services import events
from app.services.plate_validation import format_plate

log = logging.getLogger(__name__)

RESPONSES = ("accident", "not_serious", "false_alarm")
MINOR = ("not_serious", "false_alarm")
RESPONSES_SEVERE = ("accident", "no_answer")
RESPONSE_LABELS = {"accident": "Accident confirmed by owner",
                   "not_serious": "Owner reports: minor, not serious",
                   "false_alarm": "Owner reports: false alarm",
                   "no_answer": "No answer within 30 s (treated as severe)"}
KIND_REVIEW_OUTCOME = "review_outcome"     # no "crash" in the name: the app raises its alarm on those
_CRASH_KEY = re.compile(r"^CR-[0-9A-F]{10}$")
_case_lock = threading.Lock()              # one evaluation of a case at a time (answers + timer)


def parse_ref(ref: str) -> tuple[str, str] | None:
    """('crash', 'CR-...') or ('incident', '<uuid>'), None when it is neither."""
    ref = (ref or "").strip()
    if _CRASH_KEY.match(ref.upper()):
        return "crash", ref.upper()
    try:
        return "incident", str(uuid.UUID(ref))
    except ValueError:
        return None


def ref_kind(ref: str) -> str:
    return "crash" if _CRASH_KEY.match(ref) else "incident"


def owned_vehicle(db: Session, user: User, kind: str, ref: str) -> Vehicle | None:
    """The caller's vehicle this crash was raised for, or None."""
    vehicles = db.query(Vehicle).filter(Vehicle.owner_id == user.id).all()
    if not vehicles:
        return None
    if kind == "crash":
        report = (db.query(CrashReport)
                  .filter(CrashReport.incident_key == ref,
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


def _display(plate: str | None) -> str:
    return (format_plate(plate) or plate) if plate else "an unregistered vehicle"


# ── views ────────────────────────────────────────────────────────────────────────
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
                    plate=_display(vehicle.plate_number) if vehicle else None,
                    letter=vehicle.carla_letter if vehicle else None)
    return view


def responses_for(db: Session, ref: str) -> list[CrashResponse]:
    return (db.query(CrashResponse).filter(CrashResponse.incident_ref == ref)
            .order_by(CrashResponse.responded_at.desc()).all())


def case_view(db: Session, ref: str) -> dict | None:
    """The crash's outcome from its owners' answers (None until someone answers)."""
    row = db.get(CrashCaseOutcome, ref)
    if row is None:
        return None
    parties = _parties(db, row.ref_kind, ref)
    answers = _answers(db, ref)
    return {"incident_ref": ref, "outcome": row.outcome, "reason_code": row.reason_code, "reason": row.reason,
            "automatic": row.decided_by is None, "deadline_at": _iso(row.deadline_at),
            "severe": row.outcome == "not_resolved" and row.reason_code in RESPONSES_SEVERE,
            "decided_at": _iso(row.decided_at),
            "vehicles": [{"plate": _display(p), "answer": answers[p].response if p in answers else None}
                         for p in sorted(parties)]}


# ── case evaluation ──────────────────────────────────────────────────────────────
def _parties(db: Session, kind: str, ref: str) -> set[str]:
    """Plates of every vehicle involved in this crash."""
    return set(_party_alerts(db, kind, ref))


def _party_alerts(db: Session, kind: str, ref: str) -> dict[str, tuple[Vehicle | None, datetime | None]]:
    """plate -> (registered vehicle or None, when its owner was alerted)."""
    out: dict[str, tuple[Vehicle | None, datetime | None]] = {}
    if kind == "crash":
        for report in db.query(CrashReport).filter(CrashReport.incident_key == ref).order_by(CrashReport.created_at):
            vehicle = db.get(Vehicle, report.vehicle_id)
            if vehicle is not None and vehicle.plate_number not in out:
                out[vehicle.plate_number] = (vehicle, report.created_at)
        return out
    incident = db.get(Incident, ref)
    alerted = incident.created_at if incident is not None else None
    for (plate,) in db.query(IncidentVehicle.plate_norm).filter(IncidentVehicle.incident_id == ref,
                                                                IncidentVehicle.role == "involved"):
        if plate and plate not in out:
            vehicle = (db.query(Vehicle).filter(Vehicle.plate_number == plate, Vehicle.is_active.is_(True))
                       .first())
            out[plate] = (vehicle, alerted)
    return out


def _answers(db: Session, ref: str) -> dict[str, CrashResponse]:
    """plate -> latest answer for that vehicle."""
    out: dict[str, CrashResponse] = {}
    for row in db.query(CrashResponse).filter(CrashResponse.incident_ref == ref).order_by(CrashResponse.responded_at):
        vehicle = db.get(Vehicle, row.vehicle_id) if row.vehicle_id else None
        if vehicle is not None:
            out[vehicle.plate_number] = row
    return out


def _note(db: Session, user_id, plate: str | None, ref: str, title: str, text: str, outbox: list) -> None:
    note = Notification(user_id=user_id, kind=KIND_REVIEW_OUTCOME, title=title, message=text, plate_norm=plate,
                        data={"incident_key": ref, "marker": "case_outcome"})
    db.add(note)
    outbox.append((note, user_id))


# ── one crash, two records ───────────────────────────────────────────────────────
# A CARLA crash is stored twice: the crash alert record (crash_reports, key
# CR-..., what owners and the app answer) and the RFID / camera incident
# (incidents, what the Incident Radar and Evidence Records show). They share
# Member 1's alert_id, which restarts every run, so the link is
# "same alert_id, recorded within LINK_WINDOW_S of each other". Every case
# decision is applied to both, so the app and the website always agree.
CLOSED = ("resolved", "false_positive")
LINK_WINDOW_S = 120.0


def incidents_for_crash(db: Session, key: str) -> list[Incident]:
    """The incidents rows of the same crash as crash key ``key``."""
    reports = db.query(CrashReport.alert_id, CrashReport.created_at).filter(CrashReport.incident_key == key).all()
    alert_ids = {a for a, _ in reports if a}
    if not alert_ids:
        return []
    window = timedelta(seconds=LINK_WINDOW_S)
    lo, hi = min(t for _, t in reports) - window, max(t for _, t in reports) + window
    ids = {i for (i,) in db.query(IncidentAlert.incident_id)
           .filter(IncidentAlert.alert_id.in_(alert_ids), IncidentAlert.created_at.between(lo, hi))}
    return db.query(Incident).filter(Incident.id.in_(ids)).all() if ids else []


def crash_key_for_incident(db: Session, incident: Incident) -> str | None:
    """The crash key (CR-...) of the same crash as this incidents row, if any."""
    window = timedelta(seconds=LINK_WINDOW_S)
    for alert_id, created in (db.query(IncidentAlert.alert_id, IncidentAlert.created_at)
                              .filter(IncidentAlert.incident_id == incident.id)):
        if not alert_id or created is None:
            continue
        report = (db.query(CrashReport.incident_key)
                  .filter(CrashReport.alert_id == alert_id,
                          CrashReport.created_at.between(created - window, created + window))
                  .order_by(CrashReport.created_at).first())
        if report is not None:
            return report[0]
    return None


def owners_settled(db: Session, ref: str | None) -> bool:
    """EVERY owner of the crash answered minor / no authority needed, and the
    case resolved that way (not an officer's decision). A car that drove away
    is then not labelled "fled" or "hit-and-run"; its route and evidence stay."""
    if not ref:
        return False
    case = db.get(CrashCaseOutcome, ref)
    return case is not None and case.outcome == "resolved" and case.reason_code == "all_minor"


SETTLED_NOTE = "Every owner reported a minor crash and it was resolved: leaving the scene is not an offence."


def _excuse_escapes(db: Session, ref: str, settled: bool, outbox: list) -> None:
    """Close (settled) or reopen (no longer settled) the crash's hit-and-run reviews."""
    from app.models.live import ReviewItem
    now = datetime.now(timezone.utc)
    if settled:
        items = db.query(ReviewItem).filter(ReviewItem.incident_key == ref, ReviewItem.kind == "hit_and_run",
                                            ReviewItem.status == "pending").all()
        for item in items:
            item.status, item.decided_at, item.decision_note = "dismissed", now, SETTLED_NOTE
    else:
        items = db.query(ReviewItem).filter(ReviewItem.incident_key == ref, ReviewItem.kind == "hit_and_run",
                                            ReviewItem.status == "dismissed",
                                            ReviewItem.decision_note == SETTLED_NOTE).all()
        for item in items:
            item.status, item.decided_at, item.decision_note = "pending", None, None
    for item in items:
        outbox.append(("review", item))


def case_ref_for_incident(db: Session, incident: Incident) -> str:
    """Where this incident's owner answers and case live: its crash key, else its own id."""
    return crash_key_for_incident(db, incident) or str(incident.id)


def _incidents_of(db: Session, kind: str, ref: str) -> list[Incident]:
    if kind == "incident":
        incident = db.get(Incident, ref)
        return [incident] if incident is not None else []
    return incidents_for_crash(db, ref)


def _close_incident(incident: Incident, now: datetime, by_id, reason: str | None, false_positive: bool) -> bool:
    if incident.status in CLOSED:
        return False
    incident.status = "false_positive" if false_positive else "resolved"
    incident.resolved_at, incident.resolved_by = now, by_id
    incident.resolution_note = reason
    return True


def _resolve(db: Session, kind: str, ref: str, answers: dict, now: datetime, reason: str,
             by: User | None, outbox: list, false_positive: bool = False) -> None:
    for incident in _incidents_of(db, kind, ref):
        _close_incident(incident, now, by.id if by else None, reason, false_positive)
    for plate, row in answers.items():
        if row.response in MINOR and row.review_status == "pending":
            row.review_status, row.reviewed_at = "accepted", now
            row.reviewed_by = by.id if by else None
            row.review_note = row.review_note or reason
        _note(db, row.user_id, plate, ref, "Crash case resolved",
              f"The crash case for {_display(plate)} is closed: {reason}", outbox)


def _reopen(db: Session, kind: str, ref: str, answers: dict) -> None:
    for incident in _incidents_of(db, kind, ref):
        if incident.status in CLOSED:
            incident.status = "under_investigation"
            incident.resolved_at = incident.resolved_by = None
            incident.resolution_note = None
    for row in answers.values():
        if row.response in MINOR and row.review_status == "accepted":
            row.review_status, row.reviewed_at, row.reviewed_by = "pending", None, None


def _evaluate(db: Session, kind: str, ref: str, now: datetime, outbox: list) -> CrashCaseOutcome | None:
    parties = _party_alerts(db, kind, ref)
    if not parties:
        return db.get(CrashCaseOutcome, ref)
    answers = _answers(db, ref)
    row = db.get(CrashCaseOutcome, ref)
    if row is None:
        row = CrashCaseOutcome(incident_ref=ref, ref_kind=kind, outcome="waiting")
        db.add(row)
    previous = row.outcome
    window = timedelta(seconds=settings.CRASH_PARTNER_ANSWER_WINDOW_S)

    def due(plate: str) -> datetime | None:
        alerted = parties[plate][1]
        return alerted + window if alerted is not None else None

    # An owner who has not answered 30 s after their alert: recorded as "no_answer"
    for plate, (vehicle, _alerted) in parties.items():
        deadline = due(plate)
        if plate in answers or deadline is None or now < deadline:
            continue
        if vehicle is not None and vehicle.owner_id is not None:
            answers[plate] = CrashResponse(user_id=vehicle.owner_id, vehicle_id=vehicle.id, incident_ref=ref,
                                           ref_kind=kind, response="no_answer", channel="system",
                                           responded_at=now, review_status=None)
            db.add(answers[plate])
    minor = [a for a in answers.values() if a.response in MINOR]
    if minor and row.first_answer_at is None:
        row.first_answer_at = min(a.responded_at for a in minor)

    accident = sorted(p for p, a in answers.items() if a.response == "accident")
    missing = sorted(p for p in parties if p not in answers)
    silent = sorted([p for p, a in answers.items() if a.response == "no_answer"]
                    + [p for p in missing if due(p) is not None and now >= due(p)])     # unregistered cars
    pending = [p for p in missing if p not in silent]
    row.deadline_at = min((due(p) for p in pending if due(p) is not None), default=None)

    if accident:
        outcome, code = "not_resolved", "accident"
        reason = f"Owner of {', '.join(_display(p) for p in accident)} reported an accident."
    elif row.decided_by is not None:
        return row                          # the authority decided; only an accident reopens it
    elif row.outcome == "not_resolved" and row.reason_code == "no_answer":
        return row                          # a late answer does not undo the flag
    elif silent:
        outcome, code = "not_resolved", "no_answer"
        reason = (f"No answer from the owner of {', '.join(_display(p) for p in silent)} "
                  f"within {int(window.total_seconds())} s: treated as severe.")
    elif not missing:
        outcome, code = "resolved", "all_minor"
        reason = ("The owner reported a minor crash / no need for the authority." if len(parties) == 1 else
                  f"All {len(parties)} involved owners reported a minor crash / no need for the authority.")
    else:
        outcome, code = "waiting", None
        reason = f"Waiting for the owner of {', '.join(_display(p) for p in missing)} to answer."

    if (outcome, code, reason) == (row.outcome, row.reason_code, row.reason):
        return row
    row.outcome, row.reason_code, row.reason = outcome, code, reason
    row.decided_at = now if outcome != "waiting" else None
    row.decided_by = None
    if outcome == "resolved" and previous != "resolved":
        _resolve(db, kind, ref, answers, now, reason, None, outbox)
    elif outcome != "resolved" and previous == "resolved":
        _reopen(db, kind, ref, answers)
    if kind == "crash":
        _excuse_escapes(db, ref, outcome == "resolved" and code == "all_minor", outbox)
    if outcome == "not_resolved" and code in RESPONSES_SEVERE:
        for incident in _incidents_of(db, kind, ref):
            if incident.status not in CLOSED:
                incident.severity = "critical"
    outbox.append(("case", ref))
    return row


def _flush(db: Session, ref: str, outbox: list) -> None:
    """Commit, then broadcast the case and any owner notifications."""
    db.commit()
    from app.services.crash_notify import notification_view   # avoid an import cycle
    if any(item == ("case", ref) for item in outbox):
        view = case_view(db, ref)
        owners = {r.user_id for r in responses_for(db, ref)}
        events.publish("crash.case_updated", {"case": view}, user_ids=list(owners), authority=True)
    for item in outbox:
        if item[0] == "review":
            from app.services.crash_notify import review_view
            events.publish("review.updated", {"review": review_view(db, item[1])}, authority=True)
            continue
        if isinstance(item[0], Notification):
            db.refresh(item[0])
            events.publish("notification.created", {"notification": notification_view(item[0])},
                           user_ids=[item[1]], authority=False)


def refresh_case(db: Session, kind: str, ref: str, now: datetime | None = None) -> CrashCaseOutcome | None:
    """Re-evaluate one crash case, commit and broadcast. Schedules the 30 s
    check while it is waiting."""
    now = now or datetime.now(timezone.utc)
    outbox: list = []
    with _case_lock:
        row = _evaluate(db, kind, ref, now, outbox)
        _flush(db, ref, outbox)
    if row is not None and row.outcome == "waiting" and row.deadline_at is not None:
        _schedule(kind, ref, row.deadline_at)
    return row


def _schedule(kind: str, ref: str, at: datetime) -> None:
    delay = max(0.0, (at - datetime.now(timezone.utc)).total_seconds()) + 0.5
    timer = threading.Timer(delay, _timer_fire, args=(kind, ref))
    timer.daemon = True
    timer.start()


def _timer_fire(kind: str, ref: str) -> None:
    from app.core.database import SessionLocal
    db = SessionLocal()
    try:
        refresh_case(db, kind, ref)
    except Exception:                      # never let a timer thread crash the server
        log.exception("crash case check failed for %s", ref)
        db.rollback()
    finally:
        db.close()


def sweep_overdue(db: Session, now: datetime | None = None) -> None:
    """Settle waiting cases whose 30 s passed (covers a server restart)."""
    now = now or datetime.now(timezone.utc)
    overdue = (db.query(CrashCaseOutcome.incident_ref, CrashCaseOutcome.ref_kind)
               .filter(CrashCaseOutcome.outcome == "waiting", CrashCaseOutcome.deadline_at <= now).all())
    for ref, kind in overdue:
        refresh_case(db, kind, ref, now)
    sync_linked_incidents(db, now)


def sync_linked_incidents(db: Session, now: datetime | None = None, days: int = 7) -> int:
    """Apply decided crash cases to their incidents rows. The RFID incident
    can be written after the case was decided (or before this link existed),
    so this runs whenever the authority pages load. Returns rows changed."""
    now = now or datetime.now(timezone.utc)
    changed = 0
    cases = (db.query(CrashCaseOutcome)
             .filter(CrashCaseOutcome.ref_kind == "crash", CrashCaseOutcome.outcome != "waiting",
                     CrashCaseOutcome.updated_at >= now - timedelta(days=days)).all())
    for case in cases:
        for incident in incidents_for_crash(db, case.incident_ref):
            if case.outcome == "resolved":
                false_alarm = case.reason_code == "authority" and any(
                    r.response == "false_alarm" and r.review_status == "accepted"
                    for r in responses_for(db, case.incident_ref))
                changed += _close_incident(incident, case.decided_at or now, case.decided_by, case.reason,
                                           false_alarm)
            elif (case.reason_code in RESPONSES_SEVERE and incident.status not in CLOSED
                  and incident.severity != "critical"):
                incident.severity = "critical"
                changed += 1
    if changed:
        db.commit()
    return changed


def authority_close_case(db: Session, incident: Incident, officer: User, note: str | None) -> None:
    """An officer resolved the incident on the Radar (password + note): close
    the linked crash case too, so owners and the app see "Resolved"."""
    key = crash_key_for_incident(db, incident)
    ref, kind = (key, "crash") if key else (str(incident.id), "incident")
    now = datetime.now(timezone.utc)
    reason = (note or "").strip() or "Resolved by the traffic authority."
    outbox: list = []
    with _case_lock:
        case = db.get(CrashCaseOutcome, ref)
        if case is None:
            if kind == "incident" and not responses_for(db, ref):
                return                         # no crash alert and nobody answered: nothing to mirror
            case = CrashCaseOutcome(incident_ref=ref, ref_kind=kind, outcome="waiting")
            db.add(case)
        if case.outcome == "resolved":
            return
        _resolve(db, kind, ref, _answers(db, ref), now, reason, officer, outbox)
        case.outcome, case.reason_code, case.reason = "resolved", "authority", reason
        case.decided_at, case.decided_by = now, officer.id
        outbox.append(("case", ref))
        _flush(db, ref, outbox)


# ── answers ──────────────────────────────────────────────────────────────────────
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


def _publish(db: Session, event_type: str, row: CrashResponse) -> None:
    events.publish(event_type, {"response": response_view(db, row, for_authority=False)},
                   user_ids=[row.user_id], authority=False)
    events.publish(event_type, {"response": response_view(db, row, for_authority=True)}, authority=True)


def record_response(db: Session, user: User, kind: str, ref: str, vehicle: Vehicle, response: str,
                    note: str | None, channel: str, now: datetime | None = None) -> CrashResponse:
    note = (note or "").strip()[:1000] or None
    row = find_response(db, user.id, ref)
    now = now or datetime.now(timezone.utc)
    _mark_crash_notes_read(db, user.id, kind, ref, now)
    if row is None:
        row = CrashResponse(user_id=user.id, vehicle_id=vehicle.id, incident_ref=ref, ref_kind=kind,
                            response=response, note=note, channel=channel, responded_at=now,
                            review_status=None if response == "accident" else "pending")
        db.add(row)
    else:
        if row.response != response:
            row.review_status = None if response == "accident" else "pending"
            row.reviewed_by = row.reviewed_at = None
            row.review_note = None
        row.response, row.channel, row.responded_at = response, channel, now
        row.note = note if note is not None else row.note
    db.commit()
    db.refresh(row)
    _publish(db, "crash.response", row)
    refresh_case(db, kind, ref, now)
    db.refresh(row)
    return row


def decide_response(db: Session, row: CrashResponse, authority: User, accept: bool,
                    note: str | None) -> CrashResponse:
    """The authority accepts (resolve the case) or rejects (keep it open) an
    owner's minor / false-alarm answer. Accepting a false alarm sets the
    incident to false_positive; accepting a minor crash resolves it."""
    now = datetime.now(timezone.utc)
    note = (note or "").strip()[:1000] or None
    row.review_status = "accepted" if accept else "rejected"
    row.reviewed_by, row.reviewed_at, row.review_note = authority.id, now, note
    outbox: list = []
    with _case_lock:
        case = db.get(CrashCaseOutcome, row.incident_ref)
        if case is None:
            case = CrashCaseOutcome(incident_ref=row.incident_ref, ref_kind=row.ref_kind, outcome="waiting")
            db.add(case)
        answers = _answers(db, row.incident_ref)
        if accept:
            what = "a false alarm" if row.response == "false_alarm" else "a minor crash"
            reason = note or f"The traffic authority accepted the owner's report of {what}."
            if row.ref_kind == "incident" and row.response == "not_serious":
                incident = db.get(Incident, row.incident_ref)
                if incident is not None:
                    incident.severity = "low"
            _resolve(db, row.ref_kind, row.incident_ref, answers, now, reason, authority, outbox,
                     false_positive=row.response == "false_alarm")
            case.outcome, case.reason_code, case.reason = "resolved", "authority", reason
        else:
            vehicle = db.get(Vehicle, row.vehicle_id) if row.vehicle_id else None
            plate = vehicle.plate_number if vehicle else None
            reason = note or "The traffic authority kept the crash case open."
            _note(db, row.user_id, plate, row.incident_ref, "Crash still under review",
                  f"The traffic authority is still treating the crash alert for {_display(plate)} as an "
                  f"incident. Call 112 if you need help." + (f" Note: {note}" if note else ""), outbox)
            case.outcome, case.reason_code, case.reason = "not_resolved", "authority", reason
        case.decided_at, case.decided_by = now, authority.id
        outbox.append(("case", row.incident_ref))
        _flush(db, row.incident_ref, outbox)
    db.refresh(row)
    _publish(db, "crash.response_reviewed", row)
    return row
