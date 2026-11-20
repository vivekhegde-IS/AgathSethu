"""Shared fixtures for the demo-fleet / live-dashboard / Google sign-in tests.

These tests touch the database, so they run ONLY against a scratch database
whose name ends in "_test" (each test module skips itself otherwise):

    set DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/aghat_sethu_test
    python -m alembic upgrade head
    python -m pytest tests -q

The fleet is seeded with TEST passwords (never the real demo ones) from a
temporary credentials file.
"""

import os

import pytest

TEST_PASSWORD = "Fleet#Test2026"
DB_OK = os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].endswith("_test")


def _credentials_file(tmp_path_factory):
    from app.core.fleet import FLEET

    path = tmp_path_factory.mktemp("creds") / "demo_credentials.local.md"
    rows = [f"| {c.letter} | {c.plate} | {c.owner_name} | {c.owner_username} | `{TEST_PASSWORD}` |"
            for c in FLEET.values()]
    rows.append(f"| - | - | Authority | authority.admin | `{TEST_PASSWORD}` |")
    path.write_text("| Car | Plate | Owner | Username | Password |\n|---|---|---|---|---|\n"
                    + "\n".join(rows) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def credentials_path(tmp_path_factory):
    if not DB_OK:
        pytest.skip("set DATABASE_URL to a *_test database")
    return _credentials_file(tmp_path_factory)


@pytest.fixture(scope="session")
def fleet(credentials_path):
    """Seeded fleet: {"A": {...}, ..., "authority": {...}} with ids."""
    from app.core.database import SessionLocal
    from app.core.fleet import FLEET
    from app.models.models import User, Vehicle
    from seed_demo_fleet import seed

    seed(credentials_path)
    db = SessionLocal()
    try:
        out = {}
        for letter, car in FLEET.items():
            user = db.query(User).filter(User.username == car.owner_username).one()
            vehicle = db.query(Vehicle).filter(Vehicle.carla_letter == letter).one()
            out[letter] = {"user_id": user.id, "vehicle_id": vehicle.id, "username": car.owner_username,
                           "plate": car.plate, "plate_norm": car.plate_norm, "epc": car.epc}
        authority = db.query(User).filter(User.username == "authority.admin").one()
        out["authority"] = {"user_id": authority.id, "username": "authority.admin"}
        # Google links from earlier runs would leak between tests
        db.query(User).filter(User.id.in_([v["user_id"] for v in out.values()])).update(
            {User.google_sub: None, User.google_email: None, User.google_linked_at: None},
            synchronize_session=False)
        db.commit()
        return out
    finally:
        db.close()


@pytest.fixture()
def clean(fleet):
    """Remove fines / crash reports / reviews / notifications / SMS of the fleet."""
    from app.core.database import SessionLocal
    from app.models.citizen_fines import Fine, FinePayment, Notification
    from app.models.live import CrashReport, ReviewItem, SmsMessage

    user_ids = [v["user_id"] for v in fleet.values()]
    vehicle_ids = [v["vehicle_id"] for k, v in fleet.items() if k != "authority"]
    db = SessionLocal()
    try:
        db.query(SmsMessage).filter(SmsMessage.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(Notification).filter(Notification.user_id.in_(user_ids)).delete(synchronize_session=False)
        db.query(ReviewItem).filter(ReviewItem.accused_vehicle_id.in_(vehicle_ids)).delete(synchronize_session=False)
        db.query(CrashReport).filter(CrashReport.vehicle_id.in_(vehicle_ids)).delete(synchronize_session=False)
        fine_ids = [f for (f,) in db.query(Fine.id).filter(Fine.user_id.in_(user_ids))]
        if fine_ids:
            db.query(FinePayment).filter(FinePayment.fine_id.in_(fine_ids)).delete(synchronize_session=False)
            db.query(Fine).filter(Fine.id.in_(fine_ids)).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    return fleet


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def login(client, username: str, password: str = TEST_PASSWORD) -> str:
    response = client.post("/api/auth/login", json={"email": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def next_event(ws) -> dict:
    """Next real event from /ws/events (keep-alive pings skipped)."""
    while True:
        event = ws.receive_json()
        if event.get("type") != "ping":
            return event


def open_events(client, token: str):
    """Context manager: an authenticated /ws/events socket (already 'ready')."""
    class _Socket:
        def __enter__(self):
            self._cm = client.websocket_connect("/ws/events")
            self.ws = self._cm.__enter__()
            self.ws.send_json({"type": "auth", "token": token})
            ready = self.ws.receive_json()
            assert ready["type"] == "ready", ready
            return self.ws

        def __exit__(self, *exc):
            return self._cm.__exit__(*exc)

    return _Socket()
