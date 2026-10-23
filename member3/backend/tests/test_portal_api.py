"""End-to-end API tests for the portal changes (access control, profile,
incident resolution and radar day rollover, crash notifications, fine payments
and revenue).

Runs ONLY against a scratch database whose name ends in "_test" (never the
real Aghat_Sethu). Create it once, then:

    set DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/aghat_sethu_test
    python -m alembic upgrade head
    python -m pytest tests/test_portal_api.py -q
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

if not os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].endswith("_test"):
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.citizen_fines import Fine, FinePayment, Notification  # noqa: E402
from app.models.models import Incident, User, Vehicle  # noqa: E402
from app.services.notification_service import IST  # noqa: E402

PASSWORD = "Test@Pass2026"
TAG = uuid.uuid4().hex[:6].upper()


def _user(db, role, name):
    user = User(email=f"{name.lower()}.{TAG.lower()}@example.com", password_hash=hash_password(PASSWORD),
                full_name=name, role=role, status="active",
                badge_number="KA-TEST-1" if role != "citizen" else None)
    db.add(user)
    db.flush()
    return user


def _token(user):
    return {"Authorization": "Bearer " + create_access_token({"sub": str(user.id), "email": user.email,
                                                              "role": user.role})}


@pytest.fixture(scope="module")
def world():
    db = SessionLocal()
    officer = _user(db, "authority", "Officer")
    alice = _user(db, "citizen", "Alice")
    bob = _user(db, "citizen", "Bob")
    carol = _user(db, "citizen", "Carol")
    plate_a, plate_b = f"KA01T{TAG[:4]}", f"KA02T{TAG[:4]}"
    db.add_all([Vehicle(owner_id=alice.id, plate_number=plate_a, vehicle_type="car"),
                Vehicle(owner_id=bob.id, plate_number=plate_b, vehicle_type="car")])
    fine = Fine(user_id=alice.id, number_plate=plate_a, violation_type="NO HELMET", fine_amount=1000.0,
                status="Unpaid")
    incident = Incident(incident_type="crash", severity="high", status="detected", source="live",
                        crash_junction="J02", dedupe_key=f"test-{TAG}-1", run_id=f"test-{TAG}")
    other = Incident(incident_type="crash", severity="high", status="detected", source="live",
                     crash_junction="J03", dedupe_key=f"test-{TAG}-2", run_id=f"test-{TAG}")
    db.add_all([fine, incident, other])
    db.commit()
    ids = dict(officer=officer, alice=alice, bob=bob, carol=carol, plate_a=plate_a, plate_b=plate_b,
               fine_id=fine.id, incident_id=str(incident.id), other_id=str(other.id))
    for key in ("officer", "alice", "bob", "carol"):
        db.refresh(ids[key])
    db.expunge_all()
    db.close()
    yield ids


@pytest.fixture()
def client():
    return TestClient(app)


# ── access control ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path", [
    ("get", "/api/incidents"), ("get", "/api/incidents/board"), ("get", "/api/authority/summary"),
    ("get", "/api/authority/fines"), ("get", "/api/cameras/status"),
    ("get", "/api/anpr/live/detections"), ("get", "/api/routine-violations/jobs/x"),
    ("get", "/api/citizen/fines"), ("get", "/api/citizen/payments"), ("get", "/api/citizen/notifications"),
    ("patch", "/api/auth/me"),
])
def test_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_roles_are_separated(client, world):
    citizen, officer = _token(world["alice"]), _token(world["officer"])
    for path in ("/api/incidents/board", "/api/authority/summary", "/api/authority/fines",
                 "/api/cameras/status", f"/api/incidents/{world['incident_id']}"):
        assert client.get(path, headers=citizen).status_code == 403, path
    for path in ("/api/citizen/fines", "/api/citizen/payments", "/api/citizen/notifications"):
        assert client.get(path, headers=officer).status_code == 403, path


def test_live_camera_socket_needs_authority_token(client, world):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live-cameras") as ws:
            ws.receive_json()
    citizen = _token(world["alice"])["Authorization"].split()[1]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/live-cameras?token={citizen}") as ws:
            ws.receive_json()
    officer = _token(world["officer"])["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/live-cameras?token={officer}") as ws:
        assert ws.receive_json()["type"] == "connected"


def test_camera_status_without_sender(client, world):
    body = client.get("/api/cameras/status", headers=_token(world["officer"])).json()
    assert body["connected"] is False and body["sender_attached"] is False
    assert {c["junction_id"] for c in body["cameras"]} >= {"J01", "J02", "J03"}


# ── profile ──────────────────────────────────────────────────────────────────────
def test_profile_update_persists(client, world):
    headers = _token(world["carol"])
    new_email = f"carol.new.{TAG.lower()}@example.com"
    r = client.patch("/api/auth/me", headers=headers,
                     json={"full_name": "  Carol   Dsouza ", "email": new_email, "phone": "98450 12345"})
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Carol Dsouza" and r.json()["phone"] == "+919845012345"
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["email"] == new_email and me["phone"] == "+919845012345"
    # re-login with the new email works
    login = client.post("/api/auth/login", json={"email": new_email, "password": PASSWORD})
    assert login.status_code == 200 and login.json()["user"]["full_name"] == "Carol Dsouza"
    # validation
    assert client.patch("/api/auth/me", headers=headers,
                        json={"full_name": "C", "email": new_email}).status_code == 422
    assert client.patch("/api/auth/me", headers=headers,
                        json={"full_name": "Carol", "email": new_email, "phone": "12345"}).status_code == 422
    taken = client.patch("/api/auth/me", headers=headers,
                         json={"full_name": "Carol", "email": world["alice"].email})
    assert taken.status_code == 409


# ── crash notifications ──────────────────────────────────────────────────────────
def test_crash_notifies_both_registered_owners(client, world):
    from app.services.rfid.store import Persistence  # the RFID writer that records involved vehicles

    writer = Persistence.__new__(Persistence)
    db = SessionLocal()
    for plate in (world["plate_a"], world["plate_b"], world["plate_a"]):   # repeated write: no duplicate
        writer._write_incident_vehicle(db, {"incident_id": world["incident_id"], "plate_norm": plate,
                                            "role": "involved"})
        db.commit()
    db.close()

    for who, plate in (("alice", world["plate_a"]), ("bob", world["plate_b"])):
        body = client.get("/api/citizen/notifications", headers=_token(world[who])).json()
        crash = [n for n in body["notifications"] if n["kind"] == "crash_involvement"]
        assert len(crash) == 1 and crash[0]["incident_id"] == world["incident_id"]
        assert plate in crash[0]["title"] and "Junction 2" in crash[0]["message"]
        report = client.get(f"/api/citizen/incidents/{world['incident_id']}", headers=_token(world[who]))
        assert report.status_code == 200 and report.json()["location"] == "Junction 2"
        assert report.json()["role_determined"] is False
    # an uninvolved citizen cannot open the report
    assert client.get(f"/api/citizen/incidents/{world['incident_id']}",
                      headers=_token(world["carol"])).status_code == 404
    # read state persists
    alice = _token(world["alice"])
    assert client.post("/api/citizen/notifications/read-all", headers=alice).status_code == 200
    assert client.get("/api/citizen/notifications", headers=alice).json()["unread"] == 0


# ── resolution + radar day rollover ──────────────────────────────────────────────
def test_resolve_requires_password_and_rolls_off_radar(client, world):
    officer = _token(world["officer"])
    url = f"/api/incidents/{world['incident_id']}/resolve"
    assert client.post(url, headers=officer, json={"password": "wrong"}).status_code == 403
    r = client.post(url, headers=officer, json={"password": PASSWORD, "note": "Cleared by patrol"})
    assert r.status_code == 200, r.text
    assert r.json()["resolved"] and r.json()["resolved_by_name"] == "Officer"
    assert client.post(url, headers=officer, json={"password": PASSWORD}).status_code == 409

    # resolved: no longer an active radar incident
    radar = client.get("/api/incidents/board?view=radar", headers=officer).json()
    assert world["incident_id"] not in {i["id"] for i in radar["active"]}
    assert world["other_id"] in {i["id"] for i in radar["active"]}
    # no CARLA sender attached in tests: no incident offers a live feed
    assert all(i["live_feed"] is False for i in radar["active"])

    # an UNRESOLVED incident from yesterday (IST) is off the radar, but in records as unresolved
    db = SessionLocal()
    other = db.get(Incident, world["other_id"])
    yesterday = datetime.now(IST).replace(hour=12) - timedelta(days=1)
    other.created_at = yesterday.astimezone(timezone.utc)
    db.commit()
    db.close()
    radar = client.get("/api/incidents/board?view=radar", headers=officer).json()
    assert world["other_id"] not in {i["id"] for i in radar["active"] + radar["resolved_today"]}
    unresolved = client.get("/api/incidents/board?view=records&status=unresolved&page_size=200",
                            headers=officer).json()
    assert world["other_id"] in {i["id"] for i in unresolved["items"]}

    # date filter (IST calendar day)
    def on(day):
        r = client.get(f"/api/incidents/board?view=records&date={day.isoformat()}&page_size=200", headers=officer)
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}
    today_ids, yesterday_ids = on(datetime.now(IST).date()), on(yesterday.date())
    assert world["incident_id"] in today_ids and world["other_id"] not in today_ids
    assert world["other_id"] in yesterday_ids and world["incident_id"] not in yesterday_ids
    assert client.get("/api/incidents/board?view=records&date=not-a-date", headers=officer).status_code == 422

    # search: incident ID (full / part / any case) or the plate of either vehicle
    from app.services.notification_service import incident_reference
    reference = incident_reference(world["incident_id"])   # e.g. INC-1A2B3C4D
    def find(q, extra=None):
        params = {"view": "records", "q": q, "page_size": 200, **(extra or {})}
        r = client.get("/api/incidents/board", params=params, headers=officer)
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}
    assert find(reference) == {world["incident_id"]}
    assert world["incident_id"] in find(reference.lower().replace("inc-", ""))
    assert world["incident_id"] in find(reference[4:9])
    assert world["incident_id"] in find(world["plate_a"])
    assert world["incident_id"] in find(world["plate_b"][-6:].lower())
    assert world["incident_id"] in find(world["plate_a"], {"date": datetime.now(IST).date().isoformat()})
    assert world["incident_id"] not in find(world["plate_a"], {"date": yesterday.date().isoformat()})
    assert world["incident_id"] not in find("ZZ99ZZ9999")
    records = client.get("/api/incidents/board?view=records&status=resolved&page_size=200",
                         headers=officer).json()
    row = next(i for i in records["items"] if i["id"] == world["incident_id"])
    assert row["resolution_note"] == "Cleared by patrol"
    assert set(row["involved_plates"]) == {world["plate_a"], world["plate_b"]}


# ── fines, payments, revenue ─────────────────────────────────────────────────────
def test_pay_fine_updates_everywhere(client, world):
    alice, bob, officer = _token(world["alice"]), _token(world["bob"]), _token(world["officer"])
    fid = world["fine_id"]
    before = client.get("/api/authority/fines", headers=officer).json()["totals"]
    assert client.post(f"/api/citizen/fines/{fid}/pay", headers=bob, json={"method": "upi"}).status_code == 404
    assert client.post(f"/api/citizen/fines/{fid}/pay", headers=alice, json={"method": "cash"}).status_code == 422
    r = client.post(f"/api/citizen/fines/{fid}/pay", headers=alice, json={"method": "upi"})
    assert r.status_code == 200, r.text
    reference = r.json()["payment"]["reference"]
    assert reference.startswith("RCPT-")
    assert client.post(f"/api/citizen/fines/{fid}/pay", headers=alice, json={"method": "upi"}).status_code == 409

    fines = client.get("/api/citizen/fines", headers=alice).json()
    mine = next(f for f in fines["fines"] if f["id"] == fid)
    assert mine["status"] == "Paid" and mine["payment"]["reference"] == reference
    assert fines["unpaid_count"] == 0
    history = client.get("/api/citizen/payments", headers=alice).json()["payments"]
    assert [p["reference"] for p in history] == [reference]

    after = client.get("/api/authority/fines", headers=officer).json()
    t = after["totals"]
    assert t["collected_amount"] == before["collected_amount"] + 1000.0
    assert t["pending_amount"] == before["pending_amount"] - 1000.0
    month = datetime.now(IST).month
    assert after["monthly_revenue"]["months"][month - 1]["collected"] >= 1000.0

    # challans by issue date (IST day); the totals above are not affected by it
    today = datetime.now(IST).date()
    on_today = client.get(f"/api/authority/fines?date={today.isoformat()}&page_size=200", headers=officer).json()
    assert fid in {f["id"] for f in on_today["fines"]["items"]}
    assert on_today["totals"] == after["totals"]
    on_other = client.get(f"/api/authority/fines?date={(today - timedelta(days=400)).isoformat()}&page_size=200",
                          headers=officer).json()
    assert fid not in {f["id"] for f in on_other["fines"]["items"]}
    paid_today = client.get(f"/api/authority/fines?date={today.isoformat()}&status=Paid&page_size=200",
                            headers=officer).json()
    assert fid in {f["id"] for f in paid_today["fines"]["items"]}
    assert client.get("/api/authority/fines?date=bad", headers=officer).status_code == 422

    # number plate search: full, partial, any spacing / case; combines with the date
    plate = world["plate_a"]
    def by_plate(q, extra=""):
        r = client.get("/api/authority/fines", params={"plate": q, "page_size": 200, **dict(
            p.split("=") for p in extra.split("&") if p)}, headers=officer)
        assert r.status_code == 200, r.text
        return {f["id"] for f in r.json()["fines"]["items"]}
    assert fid in by_plate(plate)
    assert fid in by_plate(f" {plate[:2].lower()} {plate[2:4]}-{plate[4:]} ")
    assert fid in by_plate(plate[-4:])
    assert fid in by_plate(plate, f"date={today.isoformat()}")
    assert fid not in by_plate(plate, f"date={(today - timedelta(days=400)).isoformat()}")
    assert fid not in by_plate("ZZ99ZZ9999")


def test_records_survive_a_new_session(world):
    """What a backend restart relies on: everything is in the database."""
    db = SessionLocal()
    assert db.query(FinePayment).filter(FinePayment.fine_id == world["fine_id"]).count() == 1
    assert db.get(Fine, world["fine_id"]).status == "Paid"
    assert db.get(Incident, world["incident_id"]).resolved_by == world["officer"].id
    assert db.query(Notification).filter(Notification.incident_id == world["incident_id"]).count() == 2
    db.close()


def test_dashboard_summary_counts(client, world):
    body = client.get("/api/authority/summary", headers=_token(world["officer"])).json()
    assert body["crashes"]["total"] >= 2 and body["crashes"]["unresolved"] >= 1
    assert body["violations"]["total"] >= 1
    # helmet violations per IST day: 14 days, oldest first, today last
    by_day = body["violations"]["by_day"]
    assert body["violations"]["chart_type"] == "NO HELMET"
    assert len(by_day) == 14 and by_day == sorted(by_day, key=lambda d: d["date"])
    assert by_day[-1]["count"] >= 1
    # the junction overview endpoint was removed
    assert client.get("/api/authority/junctions", headers=_token(world["officer"])).status_code == 404


# ── multi-junction tracking: one junction of the route ──────────────────────────
def test_junction_page_shows_fled_vehicle_and_owner(client, world):
    from app.models.models import IncidentVehicle, RfidSighting

    epc = f"E2TEST{TAG[:8]}"
    db = SessionLocal()
    db.add_all([
        IncidentVehicle(incident_id=world["other_id"], plate_norm=world["plate_a"], epc=epc, role="involved"),
        IncidentVehicle(incident_id=world["other_id"], plate_norm=world["plate_a"], epc=epc, role="fled"),
        RfidSighting(incident_id=world["other_id"], epc=epc, plate_norm=world["plate_a"], junction_id="J01",
                     first_seen_ts=120.0, last_seen_ts=124.0, report_count=6),
    ])
    db.commit()
    db.close()
    officer = _token(world["officer"])
    base = f"/api/incidents/{world['other_id']}/junctions"

    body = client.get(f"{base}/J01", headers=officer).json()
    assert body["junction"] == {"id": "J01", "label": "Junction 1", "is_crash": False}
    [vehicle] = body["vehicles"]
    assert vehicle["plate_norm"] == world["plate_a"] and vehicle["fled"] is True
    assert vehicle["owner"]["name"] == "Alice"                 # the registered owner
    assert vehicle["sightings"][0]["seen_at"]                  # real (wall-clock) time of the read
    # the crash junction: the vehicle was there, with the crash frames
    crash = client.get(f"{base}/J03", headers=officer).json()
    assert crash["junction"]["is_crash"] is True and len(crash["vehicles"]) == 1
    # a junction it never reached lists nobody; an unknown junction is a 404
    assert client.get(f"{base}/J02", headers=officer).json()["vehicles"] == []
    assert client.get(f"{base}/J09", headers=officer).status_code == 404
    # owner details are authority only
    assert client.get(f"{base}/J01", headers=_token(world["alice"])).status_code == 403


def test_crash_type_and_hit_and_run(client, world):
    """NETRA v1.8 statuses -> two-car / single-vehicle, and hit-and-run."""
    from app.models.models import IncidentAlert, IncidentVehicle

    officer = _token(world["officer"])
    # other_id (set up above): one crashed car that later left, no alerts
    single = client.get(f"/api/incidents/{world['other_id']}", headers=officer).json()["incident"]
    assert single["crash_type"] == "single_vehicle"
    assert single["hit_and_run"] is False and single["left_scene_plates"] == [world["plate_a"]]

    # incident_id: a two-car pair alert, then one of the cars leaves
    db = SessionLocal()
    for alert_id, status in (("T-1", "COLLISION_EVENT_CONFIRMED_IMU_GPS"),
                             ("T-2", "COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION")):
        db.add(IncidentAlert(incident_id=world["incident_id"], alert_id=f"{alert_id}-{TAG}", source="imu_gps",
                             status=status, timestamp_sim=50.0))
    db.commit()
    pair = client.get(f"/api/incidents/{world['incident_id']}", headers=officer).json()["incident"]
    assert pair["crash_type"] == "two_car" and pair["hit_and_run"] is False
    db.add(IncidentVehicle(incident_id=world["incident_id"], plate_norm=world["plate_b"], role="fled"))
    db.commit()
    db.close()
    pair = client.get(f"/api/incidents/{world['incident_id']}", headers=officer).json()["incident"]
    assert pair["hit_and_run"] is True and pair["left_scene_plates"] == [world["plate_b"]]
