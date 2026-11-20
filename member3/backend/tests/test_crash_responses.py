"""Owners' "are you safe?" answers from the mobile app / website: ownership,
the app's request shape, live delivery to the authority, and the rule that a
false alarm only changes anything after the authority accepts it.
Needs a *_test database (conftest.py)."""

from datetime import datetime, timezone

import pytest
from conftest import DB_OK, bearer, login, next_event, open_events

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET  # noqa: E402
from app.models.citizen_fines import Notification  # noqa: E402
from app.models.live import CrashResponse  # noqa: E402
from app.models.models import Incident, IncidentVehicle  # noqa: E402
from app.services import crash_notify  # noqa: E402

T0 = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


@pytest.fixture()
def fresh(clean):
    db = SessionLocal()
    try:
        db.query(CrashResponse).filter(
            CrashResponse.user_id.in_([v["user_id"] for v in clean.values()])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return clean


def crash(letter, alert_id="MM-RESP-1"):
    car = FLEET[letter]
    message = {"type": "crash_alert", "alert_id": alert_id, "vehicle_id": letter, "plate_number": car.plate,
               "epc": car.epc, "status": "COLLISION_EVENT_SINGLE_VEHICLE", "crash_probability": 0.97,
               "timestamp_sim": 12.0, "junction_id": "J01"}
    return crash_notify.handle_crash_alert(message, now=T0)["incident_key"]


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
    r = client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(other),
                    json={"accident_occurred": False})
    assert r.status_code == 404
    assert client.post(f"/api/citizen/incidents/{key}/confirm", json={"accident_occurred": False}).status_code == 401
    assert client.post("/api/citizen/incidents/not-an-id/confirm", headers=bearer(other),
                       json={"accident_occurred": False}).status_code == 404


def test_app_false_alarm_reaches_authority_live_and_waits_for_review(client, fresh):
    key = crash("A")
    owner = login(client, "arjun.rao")
    authority = login(client, "authority.admin")
    with open_events(client, authority) as ws_auth:
        # the mobile app's original request shape
        r = client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(owner),
                        json={"accident_occurred": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["incident_id"] == key and body["accident_occurred"] is False
        assert body["response"] == "false_alarm" and body["review_status"] == "pending"
        event = next_event(ws_auth)
        assert event["type"] == "crash.response"
        assert event["data"]["response"]["plate"] == "KA 01 AT 4521"
        assert event["data"]["response"]["owner_name"]

    # answered = read, so the app's background service does not ring again
    notes = client.get("/api/citizen/notifications", headers=bearer(owner)).json()["notifications"]
    crash_note = next(n for n in notes if n["kind"] == "crash")
    assert crash_note["read"] is True and crash_note["response"]["response"] == "false_alarm"

    live = client.get("/api/authority/live", headers=bearer(authority)).json()
    assert live["pending_responses"] >= 1
    report = next(c for c in live["crashes"] if c["incident_key"] == key)
    assert report["owner_response"]["response"] == "false_alarm"

    response_id = body["id"]
    with open_events(client, owner) as ws_owner:
        r = client.post(f"/api/authority/crash-responses/{response_id}/accept", headers=bearer(authority),
                        json={"note": "Checked the camera"})
        assert r.status_code == 200 and r.json()["review_status"] == "accepted"
        types = {next_event(ws_owner)["type"], next_event(ws_owner)["type"]}
        assert types == {"crash.response_reviewed", "notification.created"}
    assert client.post(f"/api/authority/crash-responses/{response_id}/accept",
                       headers=bearer(authority)).status_code == 409
    detail = client.get(f"/api/citizen/incidents/{key}", headers=bearer(owner)).json()
    assert detail["status"] == "False alarm" and detail["response"]["review_status"] == "accepted"
    # the owner cannot use the authority endpoint
    assert client.post(f"/api/authority/crash-responses/{response_id}/reject",
                       headers=bearer(owner)).status_code == 403


def test_website_not_serious_then_accident_needs_no_review(client, fresh):
    key = crash("A")
    owner = login(client, "arjun.rao")
    r = client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(owner),
                    json={"response": "not_serious", "note": "Scratch only", "channel": "web"})
    assert r.json()["review_status"] == "pending" and r.json()["accident_occurred"] is True
    r = client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(owner),
                    json={"accident_occurred": True})
    assert r.json()["response"] == "accident" and r.json()["review_status"] is None
    db = SessionLocal()
    try:
        assert db.query(CrashResponse).filter(CrashResponse.incident_ref == key).count() == 1
    finally:
        db.close()


def test_incident_uuid_false_alarm_marks_incident_false_positive_and_can_reopen(client, fresh):
    db = SessionLocal()
    try:
        incident = Incident(incident_type="crash", severity="high", status="detected", crash_junction="J02",
                            source="synthetic")
        db.add(incident)
        db.flush()
        db.add(IncidentVehicle(incident_id=incident.id, plate_norm=fresh["A"]["plate_norm"], role="involved"))
        db.commit()
        incident_id = str(incident.id)
    finally:
        db.close()
    owner = login(client, "arjun.rao")
    authority = login(client, "authority.admin")
    try:
        r = client.post(f"/api/citizen/incidents/{incident_id}/confirm", headers=bearer(owner),
                        json={"accident_occurred": False})
        assert r.status_code == 200, r.text
        client.post(f"/api/authority/crash-responses/{r.json()['id']}/accept", headers=bearer(authority))
        db = SessionLocal()
        try:
            assert db.get(Incident, incident_id).status == "false_positive"
        finally:
            db.close()
        # owner changes their mind: it WAS an accident -> incident reopens
        client.post(f"/api/citizen/incidents/{incident_id}/confirm", headers=bearer(owner),
                    json={"accident_occurred": True})
        db = SessionLocal()
        try:
            assert db.get(Incident, incident_id).status == "under_investigation"
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            db.query(CrashResponse).filter(CrashResponse.incident_ref == incident_id).delete()
            db.query(Notification).filter(Notification.user_id == fresh["A"]["user_id"]).delete()
            db.query(Incident).filter(Incident.id == incident_id).delete()
            db.commit()
        finally:
            db.close()
