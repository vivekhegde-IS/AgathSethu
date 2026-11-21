"""One crash is stored twice: the crash-alert record (CR-..., what the owners
and the mobile app answer) and the RFID / camera incident (what the website's
Incident Radar shows). A decision on either must show on both, so the app and
the website never disagree. Needs a *_test database (conftest.py)."""

import uuid
from datetime import datetime, timezone

import pytest
from conftest import DB_OK, TEST_PASSWORD, bearer, login

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET  # noqa: E402
from app.models.live import CrashCaseOutcome, CrashResponse  # noqa: E402
from app.models.models import Incident, IncidentAlert, IncidentVehicle  # noqa: E402
from app.services import crash_notify, crash_response  # noqa: E402

OWNER = {"A": "arjun.rao", "B": "siddharth.kulkarni"}


@pytest.fixture()
def pair(clean):
    """A two-car crash A <-> B with a unique alert id, as Member 1 sends it."""
    alert_id = f"MM-LINK-{uuid.uuid4().hex[:8]}"
    car = FLEET["A"]
    key = crash_notify.handle_crash_alert({
        "type": "crash_alert", "alert_id": alert_id, "vehicle_id": "A", "plate_number": car.plate,
        "epc": car.epc, "status": "COLLISION_EVENT_CONFIRMED_IMU_GPS", "decision_route": "mutual_shock",
        "timestamp_sim": 50.0, "junction_id": "J03", "collision_partner": "B"},
        now=datetime.now(timezone.utc))["incident_key"]
    made = []
    yield {"key": key, "alert_id": alert_id, "made": made}
    db = SessionLocal()
    try:
        db.query(CrashResponse).filter(CrashResponse.incident_ref == key).delete()
        db.query(CrashCaseOutcome).filter(CrashCaseOutcome.incident_ref == key).delete()
        if made:
            db.query(Incident).filter(Incident.id.in_(made)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def rfid_incident(pair) -> str:
    """The RFID service's incidents row for the same crash (same alert id)."""
    db = SessionLocal()
    try:
        row = Incident(incident_type="crash", severity="high", status="detected", crash_junction="J03",
                       source="live", dedupe_key=f"test-link-{uuid.uuid4().hex}")
        db.add(row)
        db.flush()
        db.add(IncidentAlert(incident_id=row.id, alert_id=pair["alert_id"], source="imu_gps"))
        for letter in ("A", "B"):
            db.add(IncidentVehicle(incident_id=row.id, plate_norm=FLEET[letter].plate_norm, role="involved"))
        db.commit()
        pair["made"].append(row.id)
        return str(row.id)
    finally:
        db.close()


def answer(client, letter, key, body):
    r = client.post(f"/api/citizen/incidents/{key}/confirm", headers=bearer(login(client, OWNER[letter])), json=body)
    assert r.status_code == 200, r.text


def owner_codes(client, key):
    """What each owner reads out to the officer at the scene."""
    return [client.get(f"/api/citizen/incidents/{key}", headers=bearer(login(client, OWNER[letter])))
            .json()["resolution_code"]["code"] for letter in ("A", "B")]


def radar_item(client, incident_id):
    token = login(client, "authority.admin")
    return client.get(f"/api/incidents/{incident_id}", headers=bearer(token)).json()["incident"]


def test_both_minor_resolves_the_radar_incident_too(client, pair):
    incident_id = rfid_incident(pair)
    answer(client, "A", pair["key"], {"response": "not_serious"})
    answer(client, "B", pair["key"], {"accident_occurred": False})
    item = radar_item(client, incident_id)
    assert item["resolved"] is True and item["status"] == "resolved"            # website = app
    assert item["case"]["outcome"] == "resolved" and item["crash_ref"] == pair["key"]
    assert len(item["citizen_responses"]) == 2


def test_incident_written_after_the_case_is_synced_on_load(client, pair):
    answer(client, "A", pair["key"], {"response": "not_serious"})
    answer(client, "B", pair["key"], {"response": "not_serious"})
    incident_id = rfid_incident(pair)                       # the RFID row arrives late
    token = login(client, "authority.admin")
    client.get("/api/incidents/board?view=radar", headers=bearer(token))
    assert radar_item(client, incident_id)["resolved"] is True


def test_one_minor_one_accident_stays_unresolved_on_both(client, pair):
    incident_id = rfid_incident(pair)
    answer(client, "A", pair["key"], {"response": "not_serious"})
    answer(client, "B", pair["key"], {"accident_occurred": True})
    item = radar_item(client, incident_id)
    assert item["resolved"] is False and item["case"]["outcome"] == "not_resolved"
    assert item["severity"] == "critical"


def test_officer_resolving_on_the_radar_resolves_the_app_case(client, pair):
    incident_id = rfid_incident(pair)
    token = login(client, "authority.admin")
    r = client.post(f"/api/incidents/{incident_id}/resolve", headers=bearer(token),
                    json={"password": TEST_PASSWORD, "note": "Cleared at the scene",
                          "codes": owner_codes(client, pair["key"])})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    try:
        case = crash_response.case_view(db, pair["key"])
        assert case["outcome"] == "resolved" and case["reason"] == "Cleared at the scene"
    finally:
        db.close()
    owner = login(client, "arjun.rao")
    detail = client.get(f"/api/citizen/incidents/{pair['key']}", headers=bearer(owner)).json()
    assert detail["status"] == "Resolved"                    # what the app shows


# ── resolved case: only the "fled" label goes ────────────────────────────────────
def _escape(letter):
    car = FLEET[letter]
    return crash_notify.handle_vehicle_state(
        {"type": "vehicle_state", "vehicle_id": letter, "plate_number": car.plate, "epc": car.epc,
         "state": "POST_CRASH_MOVING", "speed_kmh": 20.0, "distance_from_crash_m": 12.0,
         "escape_confirmed": True, "timestamp_sim": 60.0}, now=datetime.now(timezone.utc))


def _hit_and_run_reviews(key):
    from app.models.live import ReviewItem
    db = SessionLocal()
    try:
        return [i.status for i in db.query(ReviewItem).filter(ReviewItem.incident_key == key,
                                                              ReviewItem.kind == "hit_and_run")]
    finally:
        db.close()


def _mark_fled(incident_id, letter):
    db = SessionLocal()
    try:
        db.add(IncidentVehicle(incident_id=incident_id, plate_norm=FLEET[letter].plate_norm, role="fled"))
        db.commit()
    finally:
        db.close()


def test_resolved_case_drops_only_the_fled_label(client, pair):
    incident_id = rfid_incident(pair)
    assert _escape("B")["status"] == "review"                    # B drove away before anyone answered
    _mark_fled(incident_id, "B")
    assert _hit_and_run_reviews(pair["key"]) == ["pending"]
    assert radar_item(client, incident_id)["hit_and_run"] is True

    answer(client, "A", pair["key"], {"response": "not_serious"})
    answer(client, "B", pair["key"], {"response": "not_serious"})  # both minor -> resolved
    assert _hit_and_run_reviews(pair["key"]) == ["dismissed"]
    item = radar_item(client, incident_id)
    assert item["hit_and_run"] is False and item["left_scene_plates"] == []
    assert item["left_scene_excused_plates"] == [FLEET["B"].plate_norm]
    detail = client.get(f"/api/incidents/{incident_id}", headers=bearer(login(client, "authority.admin"))).json()
    assert detail["fled_cleared"] is True and detail["fleeing_vehicles"]       # route / evidence kept
    assert _escape("B")["status"] == "settled"                                 # no new hit-and-run review

    answer(client, "B", pair["key"], {"accident_occurred": True})             # B changes their mind
    assert _hit_and_run_reviews(pair["key"]) == ["pending"]
    assert radar_item(client, incident_id)["hit_and_run"] is True


def test_open_case_keeps_the_fled_label(client, pair):
    incident_id = rfid_incident(pair)
    _escape("B")
    _mark_fled(incident_id, "B")
    answer(client, "A", pair["key"], {"response": "not_serious"})              # B has not answered yet
    assert _hit_and_run_reviews(pair["key"]) == ["pending"]
    assert radar_item(client, incident_id)["hit_and_run"] is True


def test_officer_resolving_keeps_the_fled_label(client, pair):
    """Only the owners' own "minor" answers clear "fled"; an officer's resolve does not."""
    incident_id = rfid_incident(pair)
    _escape("B")
    _mark_fled(incident_id, "B")
    token = login(client, "authority.admin")
    r = client.post(f"/api/incidents/{incident_id}/resolve", headers=bearer(token),
                    json={"password": TEST_PASSWORD, "note": "Cleared",
                          "codes": owner_codes(client, pair["key"])})
    assert r.status_code == 200
    item = radar_item(client, incident_id)
    assert item["resolved"] is True and item["hit_and_run"] is True
    assert _hit_and_run_reviews(pair["key"]) == ["pending"]
