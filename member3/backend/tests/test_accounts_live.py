"""Demo fleet accounts, owner isolation (REST + WebSocket), crash -> text
message, review-queue gating and dedup. Needs a *_test database (conftest.py)."""

from datetime import datetime, timedelta, timezone

import pytest
from conftest import DB_OK, TEST_PASSWORD, bearer, login, next_event, open_events

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.fleet import FLEET, resolve_letter  # noqa: E402
from app.core.security import verify_password  # noqa: E402
from app.models.citizen_fines import Fine, Notification  # noqa: E402
from app.models.live import ReviewItem, SmsMessage  # noqa: E402
from app.models.models import User, Vehicle, VehicleRegistry  # noqa: E402
from app.services import crash_notify  # noqa: E402

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)


def alert(letter, status="COLLISION_EVENT_SINGLE_VEHICLE", partner=None, alert_id="MM-000000001", **extra):
    car = FLEET[letter]
    message = {"type": "crash_alert", "alert_id": alert_id, "vehicle_id": letter, "plate_number": car.plate,
               "epc": car.epc, "status": status, "crash_probability": 0.97, "timestamp_sim": 42.5,
               "junction_id": "J01", "gps": {"latitude": 0.000251, "longitude": -0.000258},
               "collision_partner": partner}
    message.update(extra)
    return message


def escape(letter):
    car = FLEET[letter]
    return {"type": "vehicle_state", "vehicle_id": letter, "plate_number": car.plate, "epc": car.epc,
            "state": "POST_CRASH_MOVING", "speed_kmh": 21.0, "distance_from_crash_m": 14.2,
            "escape_confirmed": True, "timestamp_sim": 47.0}


def notes_of(db, user_id):
    return db.query(Notification).filter(Notification.user_id == user_id).all()


# ── seed ─────────────────────────────────────────────────────────────────────────
def test_seed_is_idempotent_and_hashes_only(fleet, credentials_path):
    from seed_demo_fleet import seed

    seed(credentials_path)
    seed(credentials_path)
    db = SessionLocal()
    try:
        usernames = [c.owner_username for c in FLEET.values()] + ["authority.admin"]
        users = db.query(User).filter(User.username.in_(usernames)).all()
        assert len(users) == 9
        for user in users:
            assert user.password_hash.startswith("$2") and TEST_PASSWORD not in user.password_hash
            assert verify_password(TEST_PASSWORD, user.password_hash)
            assert user.phone.startswith("+9100000")             # placeholder only
        roles = {u.username: u.role for u in users}
        assert roles["authority.admin"] == "authority"
        assert {r for n, r in roles.items() if n != "authority.admin"} == {"citizen"}
        vehicles = db.query(Vehicle).filter(Vehicle.carla_letter.isnot(None)).all()
        assert sorted(v.carla_letter for v in vehicles) == list("ABCDEFGH")
        for v in vehicles:
            car = FLEET[v.carla_letter]
            assert (v.plate_number, v.rfid_epc, v.state_name) == (car.plate_norm, car.epc, car.state_name)
            assert db.get(User, v.owner_id).username == car.owner_username
        assert db.query(Vehicle).filter(Vehicle.plate_number == "KA01AT4521").count() == 1
        assert db.get(VehicleRegistry, FLEET["A"].epc).plate_norm == "KA01AT4521"
    finally:
        db.close()


def test_actor_mapping_is_by_stable_identifiers():
    a = FLEET["A"]
    assert a.epc == "E200001722110101A0B1" and FLEET["H"].epc == "E200001722110108A0B8"
    assert resolve_letter(epc=a.epc) == "A"
    assert resolve_letter(vehicle_id="b") == "B"
    assert resolve_letter(plate="tn 09 ck 2365") == "C"
    assert resolve_letter(role_name="aghat_vehicle_D") == "D"
    assert resolve_letter(epc=a.epc, vehicle_id="B") is None            # conflicting: never guess
    assert resolve_letter(epc="E2000000DEADBEEF") is None


# ── login + isolation ────────────────────────────────────────────────────────────
def test_username_login_and_role_separation(client, clean):
    owner, authority = login(client, "arjun.rao"), login(client, "authority.admin")
    assert client.post("/api/auth/login", json={"email": "arjun.rao", "password": "wrong"}).status_code == 401
    assert client.get("/api/me/overview", headers=bearer(authority)).status_code == 403
    for path in ("/api/authority/live",):
        assert client.get(path, headers=bearer(owner)).status_code == 403
    assert client.post("/api/authority/fines", headers=bearer(owner),
                       json={"vehicle": "C", "amount": 500, "reason": "Signal jump"}).status_code == 403
    body = client.get("/api/me/overview", headers=bearer(owner)).json()
    assert [v["letter"] for v in body["vehicles"]] == ["A"]


def test_owner_cannot_touch_another_owners_fine(client, clean):
    authority = login(client, "authority.admin")
    fine = client.post("/api/authority/fines", headers=bearer(authority),
                       json={"vehicle": "B", "amount": 1000, "reason": "Over-speeding", "location": "J02"}).json()
    arjun = bearer(login(client, "arjun.rao"))
    assert all(f["id"] != fine["id"] for f in client.get("/api/me/overview", headers=arjun).json()["fines"])
    assert client.post(f"/api/me/fines/{fine['id']}/dispute", headers=arjun,
                       json={"reason": "Not me"}).status_code == 404
    assert client.post(f"/api/citizen/fines/{fine['id']}/pay", headers=arjun,
                       json={"method": "upi"}).status_code == 404


def test_socket_requires_valid_token(client, fleet):
    with client.websocket_connect("/ws/events") as ws:
        ws.send_json({"type": "auth", "token": "not-a-jwt"})
        assert ws.receive_json()["type"] == "error"


def test_fine_flow_is_live_and_scoped(client, clean):
    authority = login(client, "authority.admin")
    karthik = login(client, "karthik.subramanian")       # car C
    arjun = login(client, "arjun.rao")                   # car A
    with open_events(client, authority) as ws_auth, open_events(client, karthik) as ws_c, \
            open_events(client, arjun) as ws_a:
        r = client.post("/api/authority/fines", headers=bearer(authority),
                        json={"vehicle": "C", "amount": 1500, "reason": "Red-light violation",
                              "location": "Junction 1"})
        assert r.status_code == 201, r.text
        fine_id = r.json()["id"]

        e = next_event(ws_auth)
        assert e["type"] == "fine.issued" and e["data"]["fine"]["id"] == fine_id
        assert e["data"]["fine"]["owner_name"] == "Karthik Subramanian"
        e = next_event(ws_c)
        assert e["type"] == "fine.issued" and e["data"]["fine"]["status"] == "issued"
        assert next_event(ws_c)["type"] == "notification.created"

        # the owner disputes; the authority sees it live
        r = client.post(f"/api/me/fines/{fine_id}/dispute", headers=bearer(karthik), json={"reason": "Was green"})
        assert r.status_code == 200 and r.json()["status"] == "disputed"
        e = next_event(ws_auth)
        assert e["type"] == "fine.updated" and e["data"]["fine"]["status"] == "disputed"

        # Arjun's socket got nothing of C's: his next event is his own fine
        client.post("/api/authority/fines", headers=bearer(authority),
                    json={"vehicle": "A", "amount": 500, "reason": "No seat belt"})
        e = next_event(ws_a)
        assert e["type"] == "fine.issued" and e["data"]["fine"]["letter"] == "A"

    # REST state matches what was pushed
    overview = client.get("/api/me/overview", headers=bearer(karthik)).json()
    assert [f["status"] for f in overview["fines"]] == ["disputed"]
    # pay after uphold
    assert client.post(f"/api/authority/fines/{fine_id}/uphold", headers=bearer(authority)).status_code == 200
    r = client.post(f"/api/citizen/fines/{fine_id}/pay", headers=bearer(karthik), json={"method": "upi"})
    assert r.status_code == 200 and r.json()["status"] == "Paid"


# ── crash -> text message ────────────────────────────────────────────────────────
def test_single_vehicle_crash_notifies_owner_by_sms(client, clean):
    result = crash_notify.handle_crash_alert(alert("A"), now=T0)
    assert result["notified"] is True
    db = SessionLocal()
    try:
        sms = db.query(SmsMessage).filter(SmsMessage.user_id == clean["A"]["user_id"]).all()
        assert len(sms) == 1 and sms[0].provider == "console"
        assert sms[0].body.startswith("Crash detected for your vehicle KA 01 AT 4521 at ")
        assert "Junction 1" in sms[0].body and "Are you safe? Emergency: 112. Resolution code: " in sms[0].body
        assert [n.kind for n in notes_of(db, clean["A"]["user_id"])] == ["crash"]
        assert notes_of(db, clean["B"]["user_id"]) == []
    finally:
        db.close()
    body = client.get("/api/me/overview", headers=bearer(login(client, "arjun.rao"))).json()
    assert body["sms_unread"] == 1 and body["unread"] == 1 and len(body["crashes"]) == 1


def test_dedup_one_notification_per_vehicle_incident(clean):
    crash_notify.handle_crash_alert(alert("A", alert_id="MM-1"), now=T0)
    crash_notify.handle_crash_alert(alert("A", alert_id="MM-1"), now=T0 + timedelta(seconds=1))   # retry
    crash_notify.handle_crash_alert(alert("A", alert_id="MM-7"), now=T0 + timedelta(seconds=30))  # re-emit
    db = SessionLocal()
    try:
        assert db.query(SmsMessage).filter(SmsMessage.user_id == clean["A"]["user_id"]).count() == 1
    finally:
        db.close()
    # a new crash after the cooldown is a new incident
    crash_notify.handle_crash_alert(alert("A", alert_id="MM-9"), now=T0 + timedelta(minutes=30))
    db = SessionLocal()
    try:
        assert db.query(SmsMessage).filter(SmsMessage.user_id == clean["A"]["user_id"]).count() == 2
    finally:
        db.close()


def test_partner_and_hit_and_run_wait_for_review(client, clean):
    authority = login(client, "authority.admin")
    sid = login(client, "siddharth.kulkarni")             # car B: the accused
    with open_events(client, authority) as ws_auth, open_events(client, sid) as ws_b:
        crash_notify.handle_crash_alert(alert("A", "COLLISION_EVENT_CONFIRMED_IMU_GPS", partner="B",
                                              decision_route="mutual_shock"), now=T0)
        crash_notify.handle_crash_alert(alert("B", "COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION",
                                              partner="A", alert_id="MM-2"), now=T0 + timedelta(seconds=1))
        crash_notify.handle_vehicle_state(escape("B"), now=T0 + timedelta(seconds=5))

        types = []
        while len(types) < 3:                       # the "are you safe?" case updates come in between
            event_type = next_event(ws_auth)["type"]
            if event_type != "crash.case_updated":
                types.append(event_type)
        assert types == ["crash.detected", "crash.partner_named", "hit_and_run.detected"]

        # B's owner: only the neutral "are you safe?" alert (never the accusation),
        # then an unrelated fine.
        e = next_event(ws_b)
        assert e["type"] == "crash.detected" and "partner" not in e["data"]["report"]
        e = next_event(ws_b)
        assert e["type"] == "notification.created"
        assert e["data"]["notification"]["message"].startswith("Your vehicle MH 12 BR 7814 may have been involved")
        assert "KA 01" not in e["data"]["notification"]["message"]
        client.post("/api/authority/fines", headers=bearer(authority),
                    json={"vehicle": "B", "amount": 300, "reason": "Parking"})
        assert next_event(ws_b)["type"] == "fine.issued"

    db = SessionLocal()
    try:
        # struck owner (A): crash SMS + "under review", never B's plate
        a_notes = notes_of(db, clean["A"]["user_id"])
        assert sorted(n.kind for n in a_notes) == ["crash", "partner"]
        assert all("MH" not in n.message and "7814" not in n.message for n in a_notes)
        assert any(n.message == crash_notify.UNDER_REVIEW_TEXT for n in a_notes)
        # accused owner (B): one neutral crash alert + SMS; no partner / hit-and-run notification
        assert sorted(n.kind for n in notes_of(db, clean["B"]["user_id"])) == ["crash", "fine_issued"]
        assert db.query(SmsMessage).filter(SmsMessage.user_id == clean["B"]["user_id"]).count() == 1
        items = db.query(ReviewItem).filter(ReviewItem.accused_vehicle_id == clean["B"]["vehicle_id"]).all()
        assert sorted(i.kind for i in items) == ["hit_and_run", "partner"]
        assert all(i.status == "pending" for i in items)
        assert {i.decision_route for i in items} == {"mutual_shock"}
        # no automatic fine for the crash
        assert db.query(Fine).filter(Fine.user_id == clean["B"]["user_id"],
                                     Fine.violation_type != "Parking").count() == 0
        partner_id = next(i.id for i in items if i.kind == "partner")
        run_id = next(i.id for i in items if i.kind == "hit_and_run")
    finally:
        db.close()

    sid_overview = client.get("/api/me/overview", headers=bearer(sid)).json()
    assert len(sid_overview["crashes"]) == 1 and "partner" not in sid_overview["crashes"][0]
    assert len(sid_overview["sms"]) == 1 and "KA 01" not in sid_overview["sms"][0]["body"]

    # authority decisions: owners cannot decide
    assert client.post(f"/api/authority/review/{partner_id}/confirm", headers=bearer(sid)).status_code == 403
    r = client.post(f"/api/authority/review/{partner_id}/confirm", headers=bearer(authority), json={"note": "CCTV"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert client.post(f"/api/authority/review/{partner_id}/reject", headers=bearer(authority)).status_code == 409
    assert client.post(f"/api/authority/review/{run_id}/reject", headers=bearer(authority)).status_code == 200

    db = SessionLocal()
    try:
        b_notes = [n for n in notes_of(db, clean["B"]["user_id"]) if n.kind not in ("fine_issued", "crash")]
        assert [n.kind for n in b_notes] == ["partner"]                     # only the confirmed one
        a_texts = " ".join(n.message for n in notes_of(db, clean["A"]["user_id"]))
        assert "MH 12 BR 7814" in a_texts and "no other vehicle was confirmed" in a_texts
        assert db.query(Fine).filter(Fine.user_id == clean["B"]["user_id"]).count() == 1   # still only parking
    finally:
        db.close()


def test_pipeline_socket_delivers_crash_to_owner(client, clean, monkeypatch):
    """The real ingest path: crash_alert over /ws/carla/cameras -> ack -> owner SMS."""
    monkeypatch.setenv("RFID_ENABLED", "0")
    arjun = login(client, "arjun.rao")
    with open_events(client, arjun) as ws_a:
        with client.websocket_connect("/ws/carla/cameras") as carla:
            carla.send_json(alert("A", alert_id="MM-WS-1"))
            ack = carla.receive_json()
            assert ack["type"] == "crash_alert_ack" and ack["alert_id"] == "MM-WS-1"
            e = next_event(ws_a)
            assert e["type"] == "crash.detected" and e["data"]["report"]["vehicle"]["letter"] == "A"
            assert "partner" not in e["data"]["report"]
            e = next_event(ws_a)
            assert e["type"] == "notification.created" and e["data"]["sms"]["body"].startswith("Crash detected")


def test_new_crash_at_another_junction_alerts_again(clean):
    """Car A crashes with B at J03, then crashes alone at J01 a minute later:
    two crashes, two alerts. A re-sent alert at the same junction is merged."""
    first = crash_notify.handle_crash_alert(
        alert("A", "COLLISION_EVENT_CONFIRMED_IMU_GPS", partner="B", alert_id="MM-J3", junction_id="J03",
              decision_route="mutual_shock"), now=T0)
    resend = crash_notify.handle_crash_alert(alert("A", alert_id="MM-J3b", junction_id="J03"),
                                             now=T0 + timedelta(seconds=10))
    solo = crash_notify.handle_crash_alert(alert("A", alert_id="MM-J1", junction_id="J01"),
                                           now=T0 + timedelta(seconds=67))
    assert resend["incident_key"] == first["incident_key"] and resend["notified"] is False
    assert solo["incident_key"] != first["incident_key"] and solo["notified"] is True
    db = SessionLocal()
    try:
        crash_notes = [n for n in notes_of(db, clean["A"]["user_id"]) if n.kind == "crash"]
        assert len(crash_notes) == 2
        assert db.query(SmsMessage).filter(SmsMessage.user_id == clean["A"]["user_id"]).count() == 2
    finally:
        db.close()
