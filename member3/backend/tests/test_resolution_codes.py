"""Resolving a crash needs the owners' resolution codes or a super-admin code
(services/resolution_codes.py). Needs a *_test database (conftest.py)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import DB_OK, TEST_PASSWORD, bearer, login

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.live import CrashCaseOutcome, CrashResponse, ResolutionAttempt, ResolutionCode  # noqa: E402
from app.models.models import Incident, IncidentAlert, IncidentVehicle, User  # noqa: E402
from app.services import crash_notify, resolution_codes  # noqa: E402

OWNER = {"A": "arjun.rao", "B": "siddharth.kulkarni"}


@pytest.fixture()
def crash(clean):
    """A two-car crash A <-> B (crash alert CR-... + the Radar's incidents row) and a super admin."""
    alert_id = f"MM-CODE-{uuid.uuid4().hex[:8]}"
    car = FLEET["A"]
    key = crash_notify.handle_crash_alert({
        "type": "crash_alert", "alert_id": alert_id, "vehicle_id": "A", "plate_number": car.plate,
        "epc": car.epc, "status": "COLLISION_EVENT_CONFIRMED_IMU_GPS", "decision_route": "mutual_shock",
        "timestamp_sim": 50.0, "junction_id": "J03", "collision_partner": "B"},
        now=datetime.now(timezone.utc))["incident_key"]
    admin_email = f"admin-{uuid.uuid4().hex[:8]}@test.local"
    db = SessionLocal()
    try:
        row = Incident(incident_type="crash", severity="high", status="detected", crash_junction="J03",
                       source="live", dedupe_key=f"test-code-{uuid.uuid4().hex}")
        db.add(row)
        db.flush()
        db.add(IncidentAlert(incident_id=row.id, alert_id=alert_id, source="imu_gps"))
        for letter in ("A", "B"):
            db.add(IncidentVehicle(incident_id=row.id, plate_norm=FLEET[letter].plate_norm, role="involved"))
        db.add(User(email=admin_email, full_name="Super Admin", role="admin", status="active",
                    password_hash=hash_password(TEST_PASSWORD)))
        db.commit()
        incident_id = str(row.id)
    finally:
        db.close()
    yield {"key": key, "incident_id": incident_id, "admin": admin_email}
    db = SessionLocal()
    try:
        for model in (CrashResponse, CrashCaseOutcome, ResolutionCode, ResolutionAttempt):
            db.query(model).filter(model.incident_ref == key).delete()
        db.query(Incident).filter(Incident.id == incident_id).delete(synchronize_session=False)
        db.query(User).filter(User.email == admin_email).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def officer():
    return "authority.admin"


def owner_code(client, letter, key):
    r = client.get(f"/api/citizen/incidents/{key}", headers=bearer(login(client, OWNER[letter])))
    assert r.status_code == 200, r.text
    return r.json()["resolution_code"]


def resolve(client, crash, **codes):
    token = login(client, officer())
    return client.post(f"/api/incidents/{crash['incident_id']}/resolve", headers=bearer(token),
                       json={"password": TEST_PASSWORD, "note": "At the scene", **codes})


def test_each_owner_gets_their_own_code(client, crash):
    a, b = owner_code(client, "A", crash["key"]), owner_code(client, "B", crash["key"])
    assert len(a["code"]) == 6 and a["code"].isdigit() and a["code"] != b["code"]
    assert owner_code(client, "A", crash["key"])["code"] == a["code"]          # same code every time
    notes = client.get("/api/citizen/notifications", headers=bearer(login(client, OWNER["A"]))).json()
    assert a["code"] in str(notes)                                             # and it is in the alert text


def test_officer_sees_whose_codes_are_needed_not_the_codes(client, crash):
    token = login(client, officer())
    status = client.get(f"/api/incidents/{crash['incident_id']}/resolution-code", headers=bearer(token)).json()
    assert status["owner_codes_possible"] is True and len(status["owners"]) == 2
    assert owner_code(client, "A", crash["key"])["code"] not in str(status)


def test_two_car_crash_needs_both_owner_codes(client, crash):
    a, b = owner_code(client, "A", crash["key"])["code"], owner_code(client, "B", crash["key"])["code"]
    r = resolve(client, crash, codes=[a])
    assert r.status_code == 403 and "1 of 2" in r.json()["detail"]
    assert resolve(client, crash, codes=["000000" if a != "000000" else "111111", b]).status_code == 403
    r = resolve(client, crash, codes=[b, a])
    assert r.status_code == 200 and r.json()["resolved"] and r.json()["resolved_with"] == "owner"
    assert owner_code(client, "A", crash["key"]) is None                       # hidden once resolved


def test_super_admin_code_when_owner_unreachable(client, crash):
    token = bearer(login(client, officer()))
    r = client.post(f"/api/incidents/{crash['incident_id']}/resolution-code/request", headers=token,
                    json={"reason": "Owner B taken to hospital"})
    assert r.status_code == 200 and r.json()["status"] == "requested"
    admin = bearer(login(client, crash["admin"]))
    assert client.get("/api/admin/resolution-requests", headers=token).status_code == 403   # officers cannot issue
    pending = client.get("/api/admin/resolution-requests", headers=admin).json()["items"]
    mine = next(p for p in pending if p["incident_id"] == crash["incident_id"])
    assert mine["reason"] == "Owner B taken to hospital" and mine["requested_by_name"]
    issued = client.post(f"/api/admin/resolution-requests/{mine['id']}/issue", headers=admin).json()
    code = issued["code"]
    assert len(code) == 6 and issued["status"] == "issued"
    db = SessionLocal()
    try:                                                                       # only a hash is stored
        row = db.get(ResolutionCode, mine["id"])
        assert row.code_hash and code not in row.code_hash
    finally:
        db.close()
    r = resolve(client, crash, code=code)
    assert r.status_code == 200 and r.json()["resolved_with"] == "override"


def test_super_admin_code_works_once_and_expires(client, crash):
    admin = bearer(login(client, crash["admin"]))
    code = client.post(f"/api/admin/incidents/{crash['incident_id']}/resolution-code", headers=admin,
                       json={"reason": "Officer phoned in"}).json()["code"]
    db = SessionLocal()
    try:
        row = db.query(ResolutionCode).filter(ResolutionCode.incident_ref == crash["key"]).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    assert resolve(client, crash, code=code).status_code == 403                # expired
    code = client.post(f"/api/admin/incidents/{crash['incident_id']}/resolution-code", headers=admin).json()["code"]
    assert resolve(client, crash, code=code).status_code == 200
    db = SessionLocal()
    try:
        used = [r.status for r in db.query(ResolutionCode).filter(ResolutionCode.incident_ref == crash["key"])]
        assert "used" in used
    finally:
        db.close()


def test_wrong_codes_lock_the_crash_until_a_new_admin_code(client, crash):
    a, b = owner_code(client, "A", crash["key"])["code"], owner_code(client, "B", crash["key"])["code"]
    wrong = next(f"{n:06d}" for n in range(1, 99) if f"{n:06d}" not in (a, b))
    for _ in range(5):
        assert resolve(client, crash, codes=[wrong]).status_code == 403
    assert resolve(client, crash, codes=[a, b]).status_code == 423            # locked, even with right codes
    admin = bearer(login(client, crash["admin"]))
    code = client.post(f"/api/admin/incidents/{crash['incident_id']}/resolution-code", headers=admin).json()["code"]
    assert resolve(client, crash, code=code).status_code == 200


def test_owner_answers_still_resolve_without_a_code(client, crash):
    """Every owner answered "minor": the owners spoke for themselves, no code needed."""
    for letter in ("A", "B"):
        r = client.post(f"/api/citizen/incidents/{crash['key']}/confirm",
                        headers=bearer(login(client, OWNER[letter])), json={"response": "not_serious"})
        assert r.status_code == 200
    token = login(client, officer())
    item = client.get(f"/api/incidents/{crash['incident_id']}", headers=bearer(token)).json()["incident"]
    assert item["resolved"] is True and item["resolved_with"] is None


def test_code_is_bound_to_its_crash():
    assert resolution_codes.owner_code("CR-AAAA", "u1") != resolution_codes.owner_code("CR-BBBB", "u1")
    assert resolution_codes.owner_code("CR-AAAA", "u1") != resolution_codes.owner_code("CR-AAAA", "u2")
