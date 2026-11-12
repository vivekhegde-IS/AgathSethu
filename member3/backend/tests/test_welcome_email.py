"""Welcome email on the first login: message content per role, and the
send-once rule through the real /api/auth/login route.

The content tests need nothing. The login tests run ONLY against a scratch
database whose name ends in "_test" (see test_portal_api.py):

    set DATABASE_URL=postgresql+psycopg://postgres:<pw>@localhost:5432/aghat_sethu_test
    python -m alembic upgrade head
    python -m pytest tests/test_welcome_email.py -q
"""

import os
import uuid

import pytest

from app.core.config import settings
from app.services import welcome_email
from app.services.welcome_email import build_welcome_message

PASSWORD = "Test@Pass2026"


def _bodies(message):
    return [part.get_content() for part in message.iter_parts()]


def test_citizen_message(monkeypatch):
    monkeypatch.setattr(settings, "SMTP_USER", "aghatsethu.official@gmail.com")
    monkeypatch.setattr(settings, "SITE_URL", "https://aghatsethu.duckdns.org/")
    message = build_welcome_message("Asha <b>Rao</b>", "asha@example.com", "citizen")

    assert message["Subject"] == "Welcome to AGHAT SETHU"
    assert message["From"] == "AGHAT SETHU <aghatsethu.official@gmail.com>"
    assert message["To"] == "asha@example.com"
    text, html = _bodies(message)
    assert "https://aghatsethu.duckdns.org/citizen/dashboard" in text
    assert 'href="https://aghatsethu.duckdns.org/citizen/dashboard"' in html
    assert "Pay fines online" in html
    # the name is user input: escaped in HTML
    assert "Asha &lt;b&gt;Rao&lt;/b&gt;" in html and "<b>Rao</b>" not in html


@pytest.mark.parametrize("role", ["authority", "admin"])
def test_authority_message(monkeypatch, role):
    monkeypatch.setattr(settings, "SITE_URL", "https://aghatsethu.duckdns.org")
    message = build_welcome_message("Inspector Rao", "rao@example.com", role)

    assert message["Subject"] == "Welcome to AGHAT SETHU – Authority Access Activated"
    text, html = _bodies(message)
    assert "https://aghatsethu.duckdns.org/authority/dashboard" in text
    assert "Live junction camera feeds" in html
    assert "Pay fines online" not in html


# --- login route (needs a *_test database) -------------------------------------------

needs_test_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").rsplit("/", 1)[-1].endswith("_test"),
    reason="set DATABASE_URL to a *_test database to run these tests",
)


@pytest.fixture()
def login_env(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.database import SessionLocal
    from app.core.security import hash_password
    from app.main import app
    from app.models.models import User
    from app.routers import auth

    monkeypatch.setattr(settings, "SMTP_USER", "aghatsethu.official@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "app-password")
    sent = []
    monkeypatch.setattr(auth, "send_welcome_email", lambda *args: sent.append(args))

    db = SessionLocal()
    created = []

    def make_user(role="citizen", welcomed=False):
        user = User(email=f"welcome.{uuid.uuid4().hex[:8]}@example.com",
                    password_hash=hash_password(PASSWORD), full_name="Welcome Test",
                    role=role, status="active",
                    badge_number="KA-TEST-1" if role != "citizen" else None)
        if welcomed:
            from datetime import datetime, timezone
            user.welcome_email_sent_at = datetime.now(timezone.utc)
        db.add(user)
        db.commit()
        created.append(user.id)
        return user

    def login(user):
        return TestClient(app).post("/api/auth/login", json={"email": user.email, "password": PASSWORD})

    yield make_user, login, sent, db
    db.query(User).filter(User.id.in_(created)).delete(synchronize_session=False)
    db.commit()
    db.close()


@needs_test_db
def test_first_login_sends_once(login_env):
    make_user, login, sent, db = login_env
    user = make_user("authority")

    assert login(user).status_code == 200
    assert login(user).status_code == 200

    assert [(args[2], args[3]) for args in sent] == [(user.email, "authority")]
    db.refresh(user)
    assert user.welcome_email_sent_at is not None


@needs_test_db
def test_already_welcomed_user_gets_nothing(login_env):
    make_user, login, sent, _ = login_env
    assert login(make_user(welcomed=True)).status_code == 200
    assert sent == []


@needs_test_db
def test_failed_send_is_retried_on_next_login(login_env, monkeypatch):
    make_user, login, sent, db = login_env
    user = make_user()
    from app.routers import auth

    def failing_smtp(*args, **kwargs):
        raise OSError("smtp down")

    # the real sender, with SMTP failing: it must release the claim
    monkeypatch.setattr(auth, "send_welcome_email", welcome_email.send_welcome_email)
    monkeypatch.setattr(welcome_email.smtplib, "SMTP", failing_smtp)
    assert login(user).status_code == 200
    db.refresh(user)
    assert user.welcome_email_sent_at is None

    monkeypatch.setattr(auth, "send_welcome_email", lambda *args: sent.append(args))
    assert login(user).status_code == 200
    assert len(sent) == 1


@needs_test_db
def test_disabled_without_smtp_password(login_env, monkeypatch):
    make_user, login, sent, db = login_env
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    user = make_user()
    assert login(user).status_code == 200
    assert sent == []
    db.refresh(user)
    assert user.welcome_email_sent_at is None
