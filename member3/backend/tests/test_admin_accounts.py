"""Admin approval of officer sign-ups (the mobile app's "Officer Approvals" tab).
Needs a *_test database (conftest.py)."""

import uuid

import pytest
from conftest import DB_OK, TEST_PASSWORD, bearer, login

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.models import User  # noqa: E402


@pytest.fixture()
def accounts(fleet):
    tag = uuid.uuid4().hex[:8]
    admin_email, officer_email = f"admin-{tag}@test.local", f"officer-{tag}@test.local"
    db = SessionLocal()
    try:
        admin = User(email=admin_email, full_name="Test Admin", role="admin", status="active",
                     password_hash=hash_password(TEST_PASSWORD))
        officer = User(email=officer_email, full_name="Pending Officer", role="authority",
                       status="pending_approval", badge_number="B-1", jurisdiction="Zone 1",
                       password_hash=hash_password(TEST_PASSWORD))
        db.add_all([admin, officer])
        db.commit()
        ids = {"admin": admin_email, "officer": officer_email, "officer_id": str(officer.id)}
    finally:
        db.close()
    yield ids
    db = SessionLocal()
    try:
        db.query(User).filter(User.email.in_([admin_email, officer_email])).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def test_admin_lists_and_approves_pending_officer(client, accounts):
    admin = login(client, accounts["admin"])
    listed = client.get("/api/admin/authority-accounts", headers=bearer(admin)).json()
    mine = next(i for i in listed["items"] if i["id"] == accounts["officer_id"])
    assert mine["name"] == "Pending Officer" and mine["status"] == "pending_approval"
    assert mine["badge_number"] == "B-1"

    r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/approve", headers=bearer(admin))
    assert r.status_code == 200 and r.json()["status"] == "active"
    listed = client.get("/api/admin/authority-accounts", headers=bearer(admin)).json()
    assert all(i["id"] != accounts["officer_id"] for i in listed["items"])
    login(client, accounts["officer"])              # the approved officer can now sign in


def test_only_admins_reach_admin_routes(client, accounts):
    authority = login(client, "authority.admin")    # authority role, not admin
    assert client.get("/api/admin/authority-accounts", headers=bearer(authority)).status_code == 403
    assert client.get("/api/admin/authority-accounts").status_code == 401
    admin = login(client, accounts["admin"])
    assert client.post("/api/admin/authority-accounts/not-a-uuid/approve", headers=bearer(admin)).status_code == 404
