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


@pytest.fixture()
def mails(monkeypatch):
    from app.routers import admin_accounts
    sent = []
    monkeypatch.setattr(admin_accounts, "send_decision_email",
                        lambda name, email, approved: sent.append((email, approved)))
    return sent


def test_citizens_get_403_on_admin_routes(client, accounts):
    citizen = login(client, "arjun.rao")
    assert client.get("/api/admin/authority-accounts", headers=bearer(citizen)).status_code == 403
    for action in ("approve", "reject"):
        r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/{action}", headers=bearer(citizen))
        assert r.status_code == 403
    officer = login(client, "authority.admin")
    r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/reject", headers=bearer(officer))
    assert r.status_code == 403


def test_approve_emails_the_officer(client, accounts, mails):
    admin = login(client, accounts["admin"])
    r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/approve", headers=bearer(admin))
    assert r.json()["status"] == "active" and mails == [(accounts["officer"], True)]
    client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/approve", headers=bearer(admin))
    assert len(mails) == 1                                     # approving twice does not email twice
    r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/reject", headers=bearer(admin))
    assert r.status_code == 409                                # an approved officer is not "rejected"


def test_reject_blocks_login_and_emails(client, accounts, mails):
    admin = login(client, accounts["admin"])
    r = client.post(f"/api/admin/authority-accounts/{accounts['officer_id']}/reject", headers=bearer(admin))
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert mails == [(accounts["officer"], False)]
    r = client.post("/api/auth/login", json={"email": accounts["officer"], "password": TEST_PASSWORD})
    assert r.status_code in (401, 403)
    listed = client.get("/api/admin/authority-accounts", headers=bearer(admin)).json()
    assert all(i["id"] != accounts["officer_id"] for i in listed["items"])


def test_admin_reaches_every_authority_area(client, accounts):
    admin = bearer(login(client, accounts["admin"]))
    for path in ("/api/authority/live", "/api/incidents/board?view=radar", "/api/authority/summary",
                 "/api/authority/fines", "/api/incidents?source=all"):
        assert client.get(path, headers=admin).status_code == 200, path


def test_decision_email_text():
    from app.services.approval_email import _deliverable, build_decision_message
    ok = build_decision_message("Ravi K", "ravi@gov.example.in", True)
    assert "You can now sign in" in ok.get_body(("plain",)).get_content()
    no = build_decision_message("Ravi K", "ravi@gov.example.in", False)
    assert "not approved" in no.get_body(("plain",)).get_content() and "sign in" not in no["Subject"].lower()
    assert not _deliverable("x@example.com") and not _deliverable("x@test.local") and _deliverable("x@gmail.com")
