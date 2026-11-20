"""
AGHAT SETHU — Crash alerts -> owner text message, authority review queue.

Called by /ws/carla/cameras (live CARLA runs, the offline replay tool and
tools/simulate_events.py all speak the same v1.8 messages):

  crash_alert     handle_crash_alert()
  vehicle_state   handle_vehicle_state()  (escape_confirmed = hit-and-run)

Rules
  * Every registered vehicle in a crash gets its owner an "Are you safe?"
    alert (SMS-style message + in-app notification of kind "crash"), once per
    owner per incident (re-emits inside CRASH_NOTIFY_COOLDOWN_S are merged):
    the car whose own sensors raised it, and the car named as its
    collision_partner (or named by a PARTNER_ASSOCIATION alert). The partner's
    alert is neutral ("may have been involved") - it never names the other car
    or says who caused it - so both owners can answer and the two-car rules in
    crash_response.py apply.
  * The ACCUSATION (partner naming) and a hit-and-run are still never shown to
    the accused owner and never become a fine automatically. They wait in
    review_items until the authority confirms or rejects. Meanwhile the struck
    car's owner sees only "Another vehicle may have been involved; under review".

Every change is committed first, then broadcast (services/events.py).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.fleet import vehicle_for_message
from app.models.citizen_fines import Notification
from app.models.live import CrashReport, CrashResponse, ReviewItem, new_incident_key
from app.models.models import User, Vehicle
from app.services import events
from app.services.notification_service import IST, junction_label
from app.services.plate_validation import format_plate
from app.services.sms import send_sms, sms_view

STATUS_PARTNER = "COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION"
STATUS_PHYSICS = "COLLISION_EVENT_CONFIRMED_CARLA_PHYSICS"
STATUS_SINGLE = "COLLISION_EVENT_SINGLE_VEHICLE"
ROUTES = {"mutual_shock", "contact_test"}
ROUTE_LABELS = {"mutual_shock": "Mutual shock (both cars' IMUs)",
                "contact_test": "Contact test (one IMU + GPS contact)",
                "carla_physics": "CARLA collision sensor",
                "not_reported": "Route not reported by the pipeline"}
# An escape can be reported a while after the crash it belongs to.
ESCAPE_WINDOW_S = 600.0

KIND_CRASH = "crash"
KIND_PARTNER = "partner"
KIND_HIT_AND_RUN = "hit_and_run"
UNDER_REVIEW_TEXT = "Another vehicle may have been involved; under review."

_lock = threading.Lock()     # one crash message at a time: incident grouping is read-then-write


# ── views ────────────────────────────────────────────────────────────────────────
def plate_display(vehicle: Vehicle | None) -> str | None:
    if vehicle is None:
        return None
    return format_plate(vehicle.plate_number) or vehicle.plate_number


def vehicle_view(vehicle: Vehicle | None, owner: User | None = None) -> dict | None:
    if vehicle is None:
        return None
    view = {"id": str(vehicle.id), "letter": vehicle.carla_letter, "plate": plate_display(vehicle),
            "plate_norm": vehicle.plate_number, "state": vehicle.state_name, "rfid_epc": vehicle.rfid_epc}
    if owner is not None:
        view["owner_name"] = owner.full_name
        view["owner_user_id"] = str(owner.id)
    return view


def notification_view(n: Notification) -> dict:
    return {"id": str(n.id), "kind": n.kind, "type": {"crash_involvement": "crash", "fine_issued": "fine"}
            .get(n.kind, n.kind), "title": n.title, "message": n.message, "plate_norm": n.plate_norm,
            "data": n.data or {}, "read": n.read_at is not None,
            "created_at": n.created_at.isoformat() if n.created_at else None}


def _owner(db, vehicle: Vehicle | None) -> User | None:
    return db.get(User, vehicle.owner_id) if vehicle is not None else None


def report_view(db, report: CrashReport, for_authority: bool) -> dict:
    vehicle = db.get(Vehicle, report.vehicle_id)
    view = {"id": report.id, "incident_key": report.incident_key, "status": report.status,
            "source": report.source, "location": report.location, "timestamp_sim": report.timestamp_sim,
            "created_at": report.created_at.isoformat() if report.created_at else None,
            "vehicle": vehicle_view(vehicle, _owner(db, vehicle) if for_authority else None)}
    owner = _owner(db, vehicle)
    answer = (db.query(CrashResponse).filter(CrashResponse.user_id == owner.id,
                                             CrashResponse.incident_ref == report.incident_key).one_or_none()
              if owner is not None else None)
    from app.services.crash_response import case_view, response_view   # avoid an import cycle
    view["owner_response"] = response_view(db, answer, for_authority=for_authority)
    view["case"] = case_view(db, report.incident_key)
    if for_authority:
        partner = db.get(Vehicle, report.partner_vehicle_id) if report.partner_vehicle_id else None
        view.update(alert_id=report.alert_id, decision_route=report.decision_route,
                    decision_route_label=ROUTE_LABELS.get(report.decision_route or ""),
                    partner=vehicle_view(partner, _owner(db, partner)))
    return view


def review_view(db, item: ReviewItem) -> dict:
    accused = db.get(Vehicle, item.accused_vehicle_id)
    struck = db.get(Vehicle, item.struck_vehicle_id) if item.struck_vehicle_id else None
    return {"id": item.id, "incident_key": item.incident_key, "kind": item.kind, "status": item.status,
            "decision_route": item.decision_route,
            "decision_route_label": ROUTE_LABELS.get(item.decision_route or ""),
            "accused": vehicle_view(accused, _owner(db, accused)),
            "struck": vehicle_view(struck, _owner(db, struck)),
            "evidence": item.evidence or {}, "decision_note": item.decision_note,
            "decided_at": item.decided_at.isoformat() if item.decided_at else None,
            "created_at": item.created_at.isoformat() if item.created_at else None}


# ── helpers ──────────────────────────────────────────────────────────────────────
def decision_route(message: dict) -> str | None:
    route = str(message.get("decision_route") or "").strip().lower()
    if route in ROUTES:
        return route
    status = message.get("status")
    if status == STATUS_PHYSICS:
        return "carla_physics"
    if status == STATUS_SINGLE:
        return None
    return "not_reported"


def location_text(message: dict) -> str:
    junction = message.get("junction_id")
    where = junction_label(junction) if junction else "an unknown junction"
    gps = message.get("gps") or {}
    if isinstance(gps, dict) and gps.get("latitude") is not None and gps.get("longitude") is not None:
        try:
            where += f" (GPS {float(gps['latitude']):.5f}, {float(gps['longitude']):.5f})"
        except (TypeError, ValueError):
            pass
    return where


def _incident_key(db, vehicle_ids, now: datetime, window_s: float) -> str | None:
    """The incident a recent report of any of these vehicles belongs to."""
    ids = [v for v in vehicle_ids if v is not None]
    if not ids:
        return None
    recent = (db.query(CrashReport)
              .filter(CrashReport.vehicle_id.in_(ids),
                      CrashReport.created_at >= now - timedelta(seconds=window_s))
              .order_by(CrashReport.created_at.desc()).first())
    return recent.incident_key if recent is not None else None


def _notify(db, user: User, kind: str, title: str, message: str, plate_norm: str | None,
            data: dict) -> Notification:
    note = Notification(user_id=user.id, kind=kind, title=title, message=message,
                        plate_norm=plate_norm, data=data)
    db.add(note)
    db.flush()
    return note


def _has_note(db, user_id, kind: str, incident_key: str, marker: str) -> bool:
    for (data,) in db.query(Notification.data).filter(Notification.user_id == user_id,
                                                      Notification.kind == kind):
        if (data or {}).get("incident_key") == incident_key and (data or {}).get("marker") == marker:
            return True
    return False


def _under_review_note(db, struck: Vehicle | None, incident_key: str, outbox: list) -> None:
    """Tell the struck car's owner that a second vehicle is under review - no plate."""
    owner = _owner(db, struck)
    if owner is None or _has_note(db, owner.id, KIND_PARTNER, incident_key, "under_review"):
        return
    note = _notify(db, owner, KIND_PARTNER, "Crash under review", UNDER_REVIEW_TEXT, struck.plate_number,
                   {"incident_key": incident_key, "marker": "under_review"})
    outbox.append(("notification.created", {"notification": None, "_note": note}, [owner.id], False))


def _flush(db, outbox: list) -> None:
    """Commit, then broadcast (DB first)."""
    db.commit()
    for event_type, data, user_ids, authority in outbox:
        if "_note" in data:
            data = {"notification": notification_view(data["_note"]), **({"sms": sms_view(data["_sms"])}
                                                                         if "_sms" in data else {})}
        events.publish(event_type, data, user_ids=user_ids, authority=authority)


def _create_review(db, kind: str, incident_key: str, accused: Vehicle, struck: Vehicle | None,
                   route: str | None, evidence: dict) -> ReviewItem | None:
    exists = (db.query(ReviewItem).filter(ReviewItem.incident_key == incident_key, ReviewItem.kind == kind,
                                          ReviewItem.accused_vehicle_id == accused.id).one_or_none())
    if exists is not None:
        if struck is not None and exists.struck_vehicle_id is None:
            exists.struck_vehicle_id = struck.id
        return None
    item = ReviewItem(incident_key=incident_key, kind=kind, accused_vehicle_id=accused.id,
                      struck_vehicle_id=struck.id if struck is not None else None,
                      decision_route=route, evidence=evidence, status="pending")
    db.add(item)
    db.flush()
    return item


# ── crash_alert ──────────────────────────────────────────────────────────────────
def handle_crash_alert(message: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    with _lock:
        db = SessionLocal()
        try:
            return _handle_crash_alert(db, message, now)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _handle_crash_alert(db, message: dict, now: datetime) -> dict:
    vehicle = vehicle_for_message(db, message)
    if vehicle is None:
        return {"status": "unknown_vehicle"}
    partner = vehicle_for_message(db, message, "partner") if message.get("collision_partner") else None
    if partner is not None and partner.id == vehicle.id:
        partner = None
    status = message.get("status")
    is_own = status != STATUS_PARTNER
    route = decision_route(message)
    window = settings.CRASH_NOTIFY_COOLDOWN_S
    incident_key = (_incident_key(db, [vehicle.id, partner.id if partner else None], now, window)
                    or new_incident_key())
    location = location_text(message)
    outbox: list = []
    result = {"incident_key": incident_key, "notified": False, "review_item": None}

    report = (db.query(CrashReport).filter(CrashReport.incident_key == incident_key,
                                           CrashReport.vehicle_id == vehicle.id).one_or_none())
    first_own = False
    created_now = report is None
    if report is None:
        report = CrashReport(incident_key=incident_key, vehicle_id=vehicle.id,
                             alert_id=str(message.get("alert_id") or "")[:64] or None, status=status,
                             source="own" if is_own else "partner",
                             partner_vehicle_id=partner.id if partner else None, decision_route=route,
                             timestamp_sim=str(message.get("timestamp_sim") or "")[:32] or None,
                             location=location, raw=_slim(message), created_at=now)
        db.add(report)
        db.flush()
        first_own = is_own
    elif is_own and report.source != "own":
        # the car's own sensors fired after it was first named as a partner
        report.source, report.status, report.alert_id = "own", status, report.alert_id or message.get("alert_id")
        first_own = True
    if partner is not None and report.partner_vehicle_id is None:
        report.partner_vehicle_id = partner.id

    if first_own:
        if _alert_owner(db, vehicle, report, incident_key, location, now, outbox, neutral=False):
            result["notified"] = True
        outbox.append(("crash.detected", {"report": report_view(db, report, for_authority=True)}, [], True))
    elif created_now and not is_own:
        # this car was named as the partner by another car's alert: ask its owner too
        if _alert_owner(db, vehicle, report, incident_key, location, now, outbox, neutral=True):
            result["notified"] = True

    if partner is not None:
        # the other car of the pair: make it a party of the crash and ask its owner
        partner_report = (db.query(CrashReport).filter(CrashReport.incident_key == incident_key,
                                                       CrashReport.vehicle_id == partner.id).one_or_none())
        if partner_report is None:
            partner_report = CrashReport(incident_key=incident_key, vehicle_id=partner.id, source="partner",
                                         partner_vehicle_id=vehicle.id, decision_route=route,
                                         alert_id=str(message.get("alert_id") or "")[:64] or None,
                                         status=STATUS_PARTNER,
                                         timestamp_sim=str(message.get("timestamp_sim") or "")[:32] or None,
                                         location=location, raw=_slim(message), created_at=now)
            db.add(partner_report)
            db.flush()
        if _alert_owner(db, partner, partner_report, incident_key, location, now, outbox, neutral=True):
            result["partner_notified"] = True

    if partner is not None:
        # accused = the car named as partner; struck = the car whose alert named it
        accused, struck = (partner, vehicle) if is_own else (vehicle, partner)
        item = _create_review(db, KIND_PARTNER, incident_key, accused, struck, route, {
            "alert_id": message.get("alert_id"), "status": status,
            "pair_distance_m": message.get("pair_distance_m"),
            "relative_speed_kmh": message.get("relative_speed_kmh"),
            "closing_distance_m": message.get("closing_distance_m"),
            "association_score": message.get("association_score"), "location": location})
        if item is not None:
            result["review_item"] = item.id
            outbox.append(("crash.partner_named", {"review": review_view(db, item)}, [], True))
            _under_review_note(db, struck, incident_key, outbox)

    _flush(db, outbox)
    # start the "are you safe?" clock: unanswered after 30 s -> severe / not resolved
    from app.services import crash_response   # avoid an import cycle
    crash_response.refresh_case(db, "crash", incident_key, now)
    result["status"] = "notified" if result["notified"] else "recorded"
    return result


def _alert_owner(db, vehicle: Vehicle, report: CrashReport, incident_key: str, location: str,
                 now: datetime, outbox: list, neutral: bool) -> bool:
    """The "Are you safe?" alert to this vehicle's owner, once per incident.
    ``neutral`` (the partner car): never names the other car or a cause."""
    owner = _owner(db, vehicle)
    if owner is None or _has_note(db, owner.id, KIND_CRASH, incident_key, "crash"):
        return False
    when = now.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")
    plate = plate_display(vehicle)
    if neutral:
        title = f"Possible crash: {plate}"
        text = (f"Your vehicle {plate} may have been involved in a crash at {when}, {location}. "
                f"Are you safe? Emergency: 112.")
    else:
        title = f"Crash detected: {plate}"
        text = f"Crash detected for your vehicle {plate} at {when}, {location}. Are you safe? Emergency: 112."
    note = _notify(db, owner, KIND_CRASH, title, text, vehicle.plate_number,
                   {"incident_key": incident_key, "marker": "crash", "report_id": report.id,
                    "location": location, "crash_at": now.isoformat()})
    sms = send_sms(db, owner, text, notification_id=note.id)
    # the owner's own view: their vehicle only, never the partner
    outbox.append(("crash.detected", {"report": report_view(db, report, for_authority=False)}, [owner.id], False))
    outbox.append(("notification.created", {"_note": note, "_sms": sms}, [owner.id], False))
    return True


def _slim(message: dict) -> dict:
    keep = ("type", "alert_id", "vehicle_id", "plate_number", "epc", "status", "crash_probability",
            "timestamp_sim", "frame", "junction_id", "collision_partner", "pair_distance_m",
            "relative_speed_kmh", "closing_distance_m", "association_score", "decision_route", "gps",
            "world_location", "received_at")
    return {k: message.get(k) for k in keep if k in message}


# ── vehicle_state (escape) ───────────────────────────────────────────────────────
def handle_vehicle_state(message: dict, now: datetime | None = None) -> dict:
    if not message.get("escape_confirmed"):
        return {"status": "ignored"}
    now = now or datetime.now(timezone.utc)
    with _lock:
        db = SessionLocal()
        try:
            return _handle_escape(db, message, now)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def _handle_escape(db, message: dict, now: datetime) -> dict:
    vehicle = vehicle_for_message(db, message)
    if vehicle is None:
        return {"status": "unknown_vehicle"}
    recent = (db.query(CrashReport).filter(CrashReport.vehicle_id == vehicle.id,
                                           CrashReport.created_at >= now - timedelta(seconds=ESCAPE_WINDOW_S))
              .order_by(CrashReport.created_at.desc()).first())
    incident_key = recent.incident_key if recent is not None else new_incident_key()
    struck = None
    if recent is not None:
        if recent.partner_vehicle_id:
            struck = db.get(Vehicle, recent.partner_vehicle_id)
        else:
            other = (db.query(CrashReport).filter(CrashReport.incident_key == incident_key,
                                                  CrashReport.vehicle_id != vehicle.id).first())
            struck = db.get(Vehicle, other.vehicle_id) if other is not None else None
    named = (db.query(ReviewItem).filter(ReviewItem.incident_key == incident_key,
                                         ReviewItem.kind == KIND_PARTNER).first())
    route = (named.decision_route if named is not None
             else recent.decision_route if recent is not None else None)
    item = _create_review(db, KIND_HIT_AND_RUN, incident_key, vehicle, struck, route, {
                              "speed_kmh": message.get("speed_kmh"),
                              "distance_from_crash_m": message.get("distance_from_crash_m"),
                              "timestamp_sim": message.get("timestamp_sim"),
                              "state": message.get("state"),
                              # "rfid_sighting": its tag was read at another junction after the crash
                              # (used when Member 1's escape report did not arrive)
                              "basis": message.get("basis") or "escape_confirmed",
                              "seen_at_junction": message.get("junction_id")})
    outbox: list = []
    if item is not None:
        outbox.append(("hit_and_run.detected", {"review": review_view(db, item)}, [], True))
        _under_review_note(db, struck, incident_key, outbox)
    _flush(db, outbox)
    return {"status": "review" if item is not None else "duplicate", "incident_key": incident_key,
            "review_item": item.id if item is not None else None}


# ── authority decision ───────────────────────────────────────────────────────────
def decide_review(db, item: ReviewItem, authority: User, confirm: bool, note: str | None) -> ReviewItem:
    """Confirm or reject. Only a confirmation reveals the accused plate - to the
    accused owner and to the struck owner. Never issues a fine."""
    item.status = "confirmed" if confirm else "rejected"
    item.decided_by, item.decided_at = authority.id, datetime.now(timezone.utc)
    item.decision_note = (note or "").strip()[:1000] or None
    accused = db.get(Vehicle, item.accused_vehicle_id)
    struck = db.get(Vehicle, item.struck_vehicle_id) if item.struck_vehicle_id else None
    outbox: list = [("review.updated", {"review": None, "_item": item}, [], True)]
    data = {"incident_key": item.incident_key, "review_id": item.id, "marker": f"review_{item.status}"}
    what = "left the scene of" if item.kind == KIND_HIT_AND_RUN else "was involved in"
    kind = KIND_HIT_AND_RUN if item.kind == KIND_HIT_AND_RUN else KIND_PARTNER
    if confirm:
        owner = _owner(db, accused)
        if owner is not None:
            text = (f"The traffic authority has recorded that your vehicle {plate_display(accused)} {what} "
                    f"crash {item.incident_key}"
                    + (f" with vehicle {plate_display(struck)}" if struck is not None else "")
                    + ". Contact the traffic control room with this reference.")
            n = _notify(db, owner, kind, f"Crash {item.incident_key}: your vehicle was identified", text,
                        accused.plate_number, data)
            outbox.append(("notification.created", {"_note": n}, [owner.id], False))
        struck_owner = _owner(db, struck)
        if struck_owner is not None:
            text = (f"Review complete for crash {item.incident_key}: the traffic authority confirmed that "
                    f"vehicle {plate_display(accused)} {what} the crash.")
            n = _notify(db, struck_owner, kind, "Other vehicle confirmed", text, struck.plate_number, data)
            outbox.append(("notification.created", {"_note": n}, [struck_owner.id], False))
    else:
        struck_owner = _owner(db, struck)
        if struck_owner is not None:
            text = (f"Review complete for crash {item.incident_key}: no other vehicle was confirmed.")
            n = _notify(db, struck_owner, kind, "Review closed", text, struck.plate_number, data)
            outbox.append(("notification.created", {"_note": n}, [struck_owner.id], False))
    db.commit()
    for event_type, payload, user_ids, authority_room in outbox:
        if "_item" in payload:
            payload = {"review": review_view(db, payload["_item"])}
        elif "_note" in payload:
            payload = {"notification": notification_view(payload["_note"])}
        events.publish(event_type, payload, user_ids=user_ids, authority=authority_room)
    return item
