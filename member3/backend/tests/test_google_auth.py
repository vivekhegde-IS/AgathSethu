"""Sign in with Google: owners only, linked accounts only, verified on the server.

No network: ID tokens are real RS256 JWTs signed with a key made here, and
Google's own verification code (google.oauth2.id_token) runs on them with its
certificate fetch patched to return our public key. Only the code->token HTTP
exchange is replaced. Needs a *_test database (conftest.py)."""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import DB_OK, bearer, login, next_event, open_events

if not DB_OK:
    pytest.skip("set DATABASE_URL to a *_test database to run these tests", allow_module_level=True)

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from google.auth import crypt, jwt as google_jwt  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.models.models import User  # noqa: E402
from app.routers import google_auth  # noqa: E402

CLIENT_ID = "test-client.apps.googleusercontent.com"
TAB = "tab-nonce-0123456789abcdef"
KID = "test-key-1"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption())
PUBLIC_PEM = _key.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
SIGNER = crypt.RSASigner.from_string(PRIVATE_PEM, key_id=KID)


@pytest.fixture(autouse=True)
def google_env(monkeypatch, fleet):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(settings, "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")
    monkeypatch.setattr(settings, "GOOGLE_OWNER_LINKS", "")
    monkeypatch.setattr(settings, "SITE_URL", "http://localhost:5173")
    # Google's certificate endpoint -> our public key (no network)
    monkeypatch.setattr("google.oauth2.id_token._fetch_certs", lambda request, url: {KID: PUBLIC_PEM})
    _set_sub(fleet, {})
    yield
    _set_sub(fleet, {})


def _set_sub(fleet, subs: dict):
    """{"A": "sub-1", "authority": "sub-x"}; everyone else unlinked."""
    db = SessionLocal()
    try:
        for key, info in fleet.items():
            user = db.get(User, info["user_id"])
            user.google_sub = subs.get(key)
            user.google_email = f"{key.lower()}@gmail.example" if key in subs else None
        db.commit()
    finally:
        db.close()


def make_token(sub, token_nonce, **overrides):
    now = int(time.time())
    claims = {"iss": "https://accounts.google.com", "aud": CLIENT_ID, "sub": sub, "email": f"{sub}@gmail.example",
              "email_verified": True, "iat": now, "exp": now + 600, "nonce": token_nonce}
    claims.update(overrides)
    return google_jwt.encode(SIGNER, claims).decode()


def start(client, purpose="login", headers=None, tab=TAB):
    r = client.post("/api/auth/google/start", json={"purpose": purpose, "tab_nonce": tab}, headers=headers or {})
    assert r.status_code == 200, r.text
    query = parse_qs(urlparse(r.json()["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["client_id"] == [CLIENT_ID]
    return query["state"][0], query["nonce"][0]


def callback(client, monkeypatch, state, token):
    monkeypatch.setattr(google_auth, "_exchange_code", lambda code, verifier: token)
    r = client.get("/api/auth/google/callback", params={"state": state, "code": "auth-code"},
                   follow_redirects=False)
    assert r.status_code == 302
    return parse_qs(urlparse(r.headers["location"]).query)


def google_login(client, monkeypatch, sub, tab=TAB, **claims):
    state, nonce = start(client, tab=tab)
    params = callback(client, monkeypatch, state, make_token(sub, nonce, **claims))
    assert "handoff" in params, params
    return client.post("/api/auth/google/exchange", json={"handoff": params["handoff"][0], "tab_nonce": tab})


# ── configuration ────────────────────────────────────────────────────────────────
def test_disabled_without_env(client, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    assert client.get("/api/auth/google/config").json() == {"enabled": False}
    assert client.post("/api/auth/google/start", json={"purpose": "login", "tab_nonce": TAB}).status_code == 404
    assert client.post("/api/auth/login", json={"email": "arjun.rao", "password": "Fleet#Test2026"}).status_code == 200


# ── login ────────────────────────────────────────────────────────────────────────
def test_linked_owner_gets_the_same_session_and_only_own_data(client, monkeypatch, fleet, clean):
    _set_sub(fleet, {"A": "google-sub-arjun"})
    r = google_login(client, monkeypatch, "google-sub-arjun")
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert r.json()["user"]["username"] == "arjun.rao"
    overview = client.get("/api/me/overview", headers=bearer(token)).json()
    assert [v["letter"] for v in overview["vehicles"]] == ["A"]
    assert client.get("/api/authority/live", headers=bearer(token)).status_code == 403
    # the Google session works on the socket and stays in Arjun's room
    authority = login(client, "authority.admin")
    with open_events(client, token) as ws:
        client.post("/api/authority/fines", headers=bearer(authority),
                    json={"vehicle": "B", "amount": 200, "reason": "Parking"})
        client.post("/api/authority/fines", headers=bearer(authority),
                    json={"vehicle": "A", "amount": 400, "reason": "No helmet"})
        event = next_event(ws)
        assert event["type"] == "fine.issued" and event["data"]["fine"]["letter"] == "A"


def test_unlinked_google_account_is_refused(client, monkeypatch):
    r = google_login(client, monkeypatch, "google-sub-stranger")
    assert r.status_code == 401
    assert r.json()["detail"] == "No vehicle is linked to this Google account"
    assert "access_token" not in r.json()


def test_authority_refused_even_with_linked_sub(client, monkeypatch, fleet):
    _set_sub(fleet, {"authority": "google-sub-officer"})
    r = google_login(client, monkeypatch, "google-sub-officer")
    assert r.status_code == 403 and "access_token" not in r.json()


@pytest.mark.parametrize("claims", [
    {"aud": "someone-else.apps.googleusercontent.com"},
    {"iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600},
    {"email_verified": False},
    {"iss": "https://evil.example.com"},
    {"nonce": "replayed-nonce"},
], ids=["bad_audience", "expired", "unverified_email", "bad_issuer", "wrong_nonce"])
def test_bad_tokens_are_refused(client, monkeypatch, fleet, claims):
    _set_sub(fleet, {"A": "google-sub-arjun"})
    r = google_login(client, monkeypatch, "google-sub-arjun", **claims)
    assert r.status_code == 401 and "access_token" not in r.json()


def test_token_signed_by_another_key_is_refused(client, monkeypatch, fleet):
    _set_sub(fleet, {"A": "google-sub-arjun"})
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    state, nonce = start(client)
    now = int(time.time())
    forged = google_jwt.encode(crypt.RSASigner.from_string(other, key_id=KID), {
        "iss": "accounts.google.com", "aud": CLIENT_ID, "sub": "google-sub-arjun", "email_verified": True,
        "iat": now, "exp": now + 600, "nonce": nonce}).decode()
    params = callback(client, monkeypatch, state, forged)
    r = client.post("/api/auth/google/exchange", json={"handoff": params["handoff"][0], "tab_nonce": TAB})
    assert r.status_code == 401


def test_wrong_or_reused_state_is_refused(client, monkeypatch, fleet):
    _set_sub(fleet, {"A": "google-sub-arjun"})
    state, nonce = start(client)
    token = make_token("google-sub-arjun", nonce)
    assert callback(client, monkeypatch, "forged-state", token) == {"error": ["invalid_state"]}
    assert "handoff" in callback(client, monkeypatch, state, token)
    assert callback(client, monkeypatch, state, token) == {"error": ["invalid_state"]}     # single use


def test_handoff_only_redeems_in_the_starting_tab(client, monkeypatch, fleet):
    _set_sub(fleet, {"A": "google-sub-arjun"})
    state, nonce = start(client, tab=TAB)
    handoff = callback(client, monkeypatch, state, make_token("google-sub-arjun", nonce))["handoff"][0]
    other_tab = client.post("/api/auth/google/exchange", json={"handoff": handoff, "tab_nonce": "x" * 24})
    assert other_tab.status_code == 400
    mine = client.post("/api/auth/google/exchange", json={"handoff": handoff, "tab_nonce": TAB})
    assert mine.status_code == 200
    again = client.post("/api/auth/google/exchange", json={"handoff": handoff, "tab_nonce": TAB})
    assert again.status_code == 400


# ── link / unlink ────────────────────────────────────────────────────────────────
def test_link_then_login_then_unlink(client, monkeypatch, fleet):
    arjun = bearer(login(client, "arjun.rao"))
    assert client.post("/api/auth/google/start", json={"purpose": "link", "tab_nonce": TAB}).status_code == 401
    state, nonce = start(client, "link", headers=arjun)
    params = callback(client, monkeypatch, state, make_token("google-sub-new", nonce))
    r = client.post("/api/auth/google/exchange", json={"handoff": params["handoff"][0], "tab_nonce": TAB})
    assert r.status_code == 200 and r.json()["linked"] is True
    db = SessionLocal()
    try:
        user = db.get(User, fleet["A"]["user_id"])
        assert user.google_sub == "google-sub-new" and user.google_email == "google-sub-new@gmail.example"
    finally:
        db.close()
    assert google_login(client, monkeypatch, "google-sub-new").status_code == 200
    # the same Google account cannot be linked to a second owner
    priya = bearer(login(client, "priya.patel"))
    state, nonce = start(client, "link", headers=priya)
    params = callback(client, monkeypatch, state, make_token("google-sub-new", nonce))
    assert client.post("/api/auth/google/exchange", json={"handoff": params["handoff"][0],
                                                           "tab_nonce": TAB}).status_code == 409
    # unlink
    assert client.post("/api/auth/google/unlink", headers=arjun).json() == {"linked": False}
    assert google_login(client, monkeypatch, "google-sub-new").status_code == 401


def test_authority_cannot_link_or_unlink(client):
    officer = bearer(login(client, "authority.admin"))
    r = client.post("/api/auth/google/start", json={"purpose": "link", "tab_nonce": TAB}, headers=officer)
    assert r.status_code == 403
    assert client.post("/api/auth/google/unlink", headers=officer).status_code == 403


def test_owner_links_allowlist_prelinks_by_sub(client, monkeypatch, fleet):
    monkeypatch.setattr(settings, "GOOGLE_OWNER_LINKS", "priya.patel=priya.demo@gmail.example")
    r = google_login(client, monkeypatch, "google-sub-priya", email="priya.demo@gmail.example")
    assert r.status_code == 200 and r.json()["user"]["username"] == "priya.patel"
    db = SessionLocal()
    try:
        assert db.get(User, fleet["F"]["user_id"]).google_sub == "google-sub-priya"
    finally:
        db.close()
    # from now on it is the sub that matters, not the email
    assert google_login(client, monkeypatch, "google-sub-priya", email="changed@gmail.example").status_code == 200
    assert google_login(client, monkeypatch, "google-sub-other", email="priya.demo@gmail.example").status_code == 401
    # the allowlist can never let the authority in
    monkeypatch.setattr(settings, "GOOGLE_OWNER_LINKS", "authority.admin=boss@gmail.example")
    assert google_login(client, monkeypatch, "google-sub-boss", email="boss@gmail.example").status_code == 403
