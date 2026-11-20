"""Owners' "are you safe?" answers from the mobile app / website and the
automatic crash case outcome:

  single vehicle, owner answers minor / false alarm        -> resolved
  two vehicles, both owners answer minor                    -> resolved
  two vehicles, one minor + the other accident              -> not resolved
  two vehicles, one minor + the other silent for 30 s       -> not resolved
  not resolved -> authority accepts ("resolve as false alarm") -> false_positive

Needs a *_test database (conftest.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import DB_OK, bearer, login, next_event, open_events

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET  # noqa: E402
from app.models.citizen_fines import Notification  # noqa: E402
from app.models.live import CrashCaseOutcome, CrashResponse  # noqa: E402
from app.models.models import Incident, IncidentVehicle  # noqa: E402
from app.services import crash_notify, crash_response  # noqa: E402

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
OWNER = {"A": "arjun.rao", "B": "siddharth.kulkarni", "C": "karthik.subramanian"}


@pytest.fixture()
def fresh(clean, monkeypatch):
    monkeypatch.setattr(crash_response, "_schedule", lambda *a, **k: None)   # no timer threads in tests
    db = SessionLocal()
    try:
        users = [v["user_id"] for v in clean.values()]
        refs = [r for (r,) in db.query(CrashResponse.incident_ref).filter(CrashResponse.user_id.in_(users))]
        db.query(CrashResponse).filter(CrashResponse.user_id.in_(users)).delete(synchronize_session=False)
        if refs:
            db.query(CrashCaseOutcome).filter(CrashCaseOutcome.incident_ref.in_(refs)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return clean


def crash(letter, alert_id="MM-RESP-1", partner=None, now=T0):
    car = FLEET[letter]
    message = {"type": "crash_alert", "alert_id": alert_id, "vehicle_id": letter, "plate_number": car.plate,
               "epc": car.epc, "status": "COLLISION_EVENT_SINGLE_VEHICLE", "crash_probability": 0.97,
               "timestamp_sim": 12.0, "junction_id": "J01", "collision_partner": partner}
    if partner:
        message.update(status="COLLISION_EVENT_CONFIRMED_IMU_GPS", decision_route="mutual_shock")
    return crash_notify.handle_crash_alert(message, now=now)["incident_key"]


def two_car_crash():
    key = crash("A", alert_id="MM-PAIR-A", partner="B")
    assert crash("B", alert_id="MM-PAIR-B", partner="A") == key
    return key


def answer(client, letter, ref, body):
    r = client.post(f"/api/citizen/incidents/{ref}/confirm", headers=bearer(login(client, OWNER[letter])), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def case(ref):
    db = SessionLocal()
    try:
        return crash_response.case_view(db, ref)
    finally:
        db.close()


# ── the app's request shape, ownership ───────────────────────────────────────────
def test_notification_carries_the_crash_key_the_app_answers(client, fresh):
    key = crash("A")
    token = login(client, "arjun.rao")
    notes = client.get("/api/citizen/notifications", headers=bearer(token)).json()["notifications"]
    crash_note = next(n for n in notes if n["kind"] == "crash")
    assert crash_note["incident_id"] == key and crash_note["response"] is None
    detail = client.get(f"/api/citizen/incidents/{key}", headers=bearer(token))
    assert detail.status_code == 200 and detail.json()["status"] == "Under review"


def test_only_the_crashed_cars_owner_may_answer(client, fresh):
    key = crash("A")
    other = login(client, "siddharth.kulkarni")          # owns car B, not in this crash
    assert client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(other),
                       json={"accident_occurred": False}).status_code == 404
    assert client.post(f"/api/citizen/incidents/{key}/confirm", json={"accident_occurred": False}).status_code == 401
    assert client.post("/api/citizen/incidents/not-an-id/confirm", headers=bearer(other),
                       json={"accident_occurred": False}).status_code == 404


# ── single vehicle ───────────────────────────────────────────────────────────────
def test_single_vehicle_minor_answer_resolves_at_once_and_live(client, fresh):
    key = crash("A")
    authority = login(client, "authority.admin")
    with open_events(client, authority) as ws_auth:
        body = answer(client, "A", key, {"accident_occurred": False})        # the app's false alarm
        assert body["incident_id"] == key and body["accident_occurred"] is False
        assert body["response"] == "false_alarm" and body["review_status"] == "accepted"
        types = [next_event(ws_auth)["type"], next_event(ws_auth)["type"]]
        assert types == ["crash.response", "crash.case_updated"]
    assert case(key)["outcome"] == "resolved" and case(key)["automatic"] is True

    owner = login(client, "arjun.rao")
    detail = client.get(f"/api/citizen/incidents/{key}", headers=bearer(owner)).json()
    assert detail["status"] == "Resolved" and detail["case"]["reason_code"] == "all_minor"
    notes = client.get("/api/citizen/notifications", headers=bearer(owner)).json()["notifications"]
    assert next(n for n in notes if n["kind"] == "crash")["read"] is True     # the phone stops ringing
    live = client.get("/api/authority/live", headers=bearer(authority)).json()
    assert next(c for c in live["crashes"] if c["incident_key"] == key)["case"]["outcome"] == "resolved"


def test_single_vehicle_accident_is_not_resolved_and_reopens(client, fresh):
    key = crash("A")
    answer(client, "A", key, {"response": "not_serious"})
    assert case(key)["outcome"] == "resolved"
    answer(client, "A", key, {"accident_occurred": True})                     # changed their mind
    assert case(key)["outcome"] == "not_resolved" and case(key)["reason_code"] == "accident"


# ── two vehicles ─────────────────────────────────────────────────────────────────
def test_two_vehicles_both_minor_resolves(client, fresh):
    key = two_car_crash()
    answer(client, "A", key, {"response": "not_serious"})
    assert case(key)["outcome"] == "waiting"
    answer(client, "B", key, {"accident_occurred": False})
    c = case(key)
    assert c["outcome"] == "resolved" and {v["answer"] for v in c["vehicles"]} == {"not_serious", "false_alarm"}


def test_two_vehicles_minor_and_accident_is_not_resolved(client, fresh):
    key = two_car_crash()
    answer(client, "A", key, {"response": "not_serious"})
    answer(client, "B", key, {"accident_occurred": True})
    assert case(key)["outcome"] == "not_resolved" and case(key)["reason_code"] == "accident"


def test_two_vehicles_partner_silent_30s_is_not_resolved_then_authority_resolves(client, fresh):
    key = two_car_crash()
    a = answer(client, "A", key, {"accident_occurred": False})
    assert a["review_status"] == "pending" and case(key)["outcome"] == "waiting"
    db = SessionLocal()
    try:
        crash_response.sweep_overdue(db, now=datetime.now(timezone.utc) + timedelta(seconds=20))
        assert crash_response.case_view(db, key)["outcome"] == "waiting"           # still inside 30 s
        crash_response.sweep_overdue(db, now=datetime.now(timezone.utc) + timedelta(seconds=31))
        c = crash_response.case_view(db, key)
        assert c["outcome"] == "not_resolved" and c["reason_code"] == "no_answer"
        assert "MH 12 BR 7814" in c["reason"]
    finally:
        db.close()
    answer(client, "B", key, {"response": "not_serious"})                     # too late: stays flagged
    assert case(key)["outcome"] == "not_resolved"

    authority = login(client, "authority.admin")
    r = client.post(f"/api/authority/crash-responses/{a['id']}/accept", headers=bearer(authority),
                    json={"note": "Checked the camera"})
    assert r.status_code == 200 and r.json()["review_status"] == "accepted"
    c = case(key)
    assert c["outcome"] == "resolved" and c["automatic"] is False and c["reason"] == "Checked the camera"


# ── incidents table (UUID) ───────────────────────────────────────────────────────
@pytest.fixture()
def incident(fresh):
    db = SessionLocal()
    try:
        row = Incident(incident_type="crash", severity="high", status="detected", crash_junction="J02",
                       source="synthetic", dedupe_key=f"test-resp-{datetime.now().timestamp()}")
        db.add(row)
        db.flush()
        db.add(IncidentVehicle(incident_id=row.id, plate_norm=fresh["A"]["plate_norm"], role="involved"))
        db.add(IncidentVehicle(incident_id=row.id, plate_norm="KA99ZZ0001", role="involved"))   # unregistered
        db.commit()
        incident_id = str(row.id)
    finally:
        db.close()
    yield incident_id
    db = SessionLocal()
    try:
        db.query(CrashResponse).filter(CrashResponse.incident_ref == incident_id).delete()
        db.query(CrashCaseOutcome).filter(CrashCaseOutcome.incident_ref == incident_id).delete()
        db.query(Notification).filter(Notification.user_id == fresh["A"]["user_id"]).delete()
        db.query(Incident).filter(Incident.id == incident_id).delete()
        db.commit()
    finally:
        db.close()


def test_incident_with_unanswerable_partner_needs_the_authority(client, incident):
    a = answer(client, "A", incident, {"accident_occurred": False})
    db = SessionLocal()
    try:
        crash_response.sweep_overdue(db, now=datetime.now(timezone.utc) + timedelta(seconds=31))
        assert db.get(Incident, incident).status == "detected"                  # not auto-resolved
    finally:
        db.close()
    authority = login(client, "authority.admin")
    detail = client.get(f"/api/incidents/{incident}", headers=bearer(authority)).json()["incident"]
    assert detail["latest_citizen_response"]["id"] == a["id"]
    assert detail["case"]["outcome"] == "not_resolved" and detail["resolved"] is False

    # "Resolve as false alarm"
    client.post(f"/api/authority/crash-responses/{a['id']}/accept", headers=bearer(authority))
    db = SessionLocal()
    try:
        row = db.get(Incident, incident)
        assert row.status == "false_positive" and row.resolved_at is not None and row.resolved_by is not None
    finally:
        db.close()
    detail = client.get(f"/api/incidents/{incident}", headers=bearer(authority)).json()["incident"]
    assert detail["resolved"] is True and detail["false_alarm"] is True

    # the owner now says it WAS an accident -> reopened
    answer(client, "A", incident, {"accident_occurred": True})
    db = SessionLocal()
    try:
        assert db.get(Incident, incident).status == "under_investigation"
    finally:
        db.close()
