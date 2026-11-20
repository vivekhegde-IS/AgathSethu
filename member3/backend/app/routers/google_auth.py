"""
AGHAT SETHU — Sign in with Google (vehicle owners only)

Flow: OpenID Connect authorization-code flow, run by the backend, with PKCE
(S256), a single-use `state` and a `nonce`.

  1. POST /api/auth/google/start  {purpose: login|link, tab_nonce}
       Stores sha256(state) + PKCE verifier + nonce + sha256(tab_nonce) in
       oauth_states and returns Google's authorization URL. `link` needs the
       owner's Bearer token (password login first); authority users get 403.
  2. The tab navigates to Google; Google redirects to
     GET /api/auth/google/callback?code&state (GOOGLE_REDIRECT_URI).
       The state row is consumed (single use, 10 min). The code is exchanged
       server-side with the client secret + PKCE verifier; the ID token is
       verified with Google's library (signature, aud == GOOGLE_CLIENT_ID,
       iss, expiry), then email_verified and nonce are checked. The user is
       found by Google's `sub`, never by email (GOOGLE_OWNER_LINKS pre-links
       a username to a Gmail once, then stores the `sub`).
       The result goes into a one-time hand-off code bound to the starting
       tab; the browser is redirected to SITE_URL/auth/google/done?handoff=...
  3. POST /api/auth/google/exchange {handoff, tab_nonce}
       Only the tab holding tab_nonce (sessionStorage is per tab) can redeem
       it. Returns the SAME TokenResponse as password login, so Google and
       password sessions behave identically (REST and /ws/events).

No open sign-up: a Google account that is not linked to a seeded owner gets
"No vehicle is linked to this Google account" and no session. A `sub` linked
to an authority account is refused with 403.

All of it is off (404, button hidden) unless GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI are set.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.dependencies.deps import bearer_scheme, get_current_user, require_citizen
from app.models.live import OAuthState
from app.models.models import User
from app.schemas.schemas import TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth/google", tags=["Google sign-in"])

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
STATE_TTL = timedelta(minutes=10)
HANDOFF_TTL = timedelta(minutes=2)
OWNER_ROLE = "citizen"

MESSAGES = {
    "not_linked": (status.HTTP_401_UNAUTHORIZED, "No vehicle is linked to this Google account"),
    "authority": (status.HTTP_403_FORBIDDEN,
                  "Authority accounts cannot use Google sign-in. Use username and password."),
    "inactive": (status.HTTP_403_FORBIDDEN, "Account is not active"),
    "invalid_token": (status.HTTP_401_UNAUTHORIZED, "Google sign-in could not be verified"),
    "sub_taken": (status.HTTP_409_CONFLICT, "This Google account is already linked to another owner"),
}


class GoogleTokenError(Exception):
    pass


def google_enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and settings.GOOGLE_REDIRECT_URI)


def _require_enabled() -> None:
    if not google_enabled():
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def owner_links() -> dict[str, str]:
    """GOOGLE_OWNER_LINKS 'user=mail,user2=mail2' -> {email: username}."""
    links = {}
    for pair in settings.GOOGLE_OWNER_LINKS.split(","):
        if "=" in pair:
            username, email = (part.strip() for part in pair.split("=", 1))
            if username and email:
                links[email.lower()] = username
    return links


# ── Google calls (patched in tests: no network) ─────────────────────────────────
def _exchange_code(code: str, code_verifier: str) -> str:
    """Authorization code -> ID token (server to server, with the client secret)."""
    response = httpx.post(TOKEN_URL, data={
        "code": code, "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET, "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code", "code_verifier": code_verifier,
    }, timeout=10.0)
    if response.status_code != 200:
        raise GoogleTokenError(f"token endpoint returned {response.status_code}")
    token = response.json().get("id_token")
    if not token:
        raise GoogleTokenError("no id_token in token response")
    return token


def verify_id_token(token: str, expected_nonce: str | None) -> dict:
    """Google's official verification + our own claim checks. Raises GoogleTokenError."""
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        # signature against Google's published keys, aud, iss, exp/iat
        claims = id_token.verify_oauth2_token(token, google_requests.Request(),
                                              audience=settings.GOOGLE_CLIENT_ID)
    except Exception as error:
        raise GoogleTokenError(str(error)) from error
    if claims.get("iss") not in ISSUERS:
        raise GoogleTokenError("wrong issuer")
    if claims.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise GoogleTokenError("wrong audience")
    if claims.get("email_verified") is not True:
        raise GoogleTokenError("email not verified")
    if not claims.get("sub"):
        raise GoogleTokenError("no subject")
    if expected_nonce is not None and not secrets.compare_digest(str(claims.get("nonce") or ""), expected_nonce):
        raise GoogleTokenError("nonce mismatch")
    return claims


# ── endpoints ────────────────────────────────────────────────────────────────────
@router.get("/config")
def google_config():
    return {"enabled": google_enabled()}


class StartRequest(BaseModel):
    purpose: str = Field(pattern="^(login|link)$")
    tab_nonce: str = Field(min_length=16, max_length=128)


@router.post("/start")
def google_start(body: StartRequest, db: Session = Depends(get_db),
                 credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_enabled()
    user_id = None
    if body.purpose == "link":
        user = get_current_user(credentials, db)
        if user.role != OWNER_ROLE:
            raise HTTPException(status_code=403, detail=MESSAGES["authority"][1])
        user_id = user.id
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(24)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.query(OAuthState).filter(OAuthState.expires_at < _now()).delete(synchronize_session=False)
    db.add(OAuthState(id=_sha(state), purpose=body.purpose, user_id=user_id, code_verifier=verifier,
                      nonce=nonce, tab_hash=_sha(body.tab_nonce), expires_at=_now() + STATE_TTL))
    db.commit()
    query = urlencode({
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": "openid email", "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    })
    return {"authorization_url": f"{AUTH_URL}?{query}"}


def _done(**params) -> RedirectResponse:
    return RedirectResponse(f"{settings.SITE_URL.rstrip('/')}/auth/google/done?{urlencode(params)}",
                            status_code=status.HTTP_302_FOUND)


def _login_outcome(db: Session, claims: dict) -> tuple[str, User | None]:
    user = db.query(User).filter(User.google_sub == claims["sub"]).one_or_none()
    if user is None:
        username = owner_links().get(str(claims.get("email") or "").lower())
        candidate = (db.query(User).filter(User.username == username).one_or_none()
                     if username else None)
        if candidate is not None and candidate.google_sub is None:
            if candidate.role != OWNER_ROLE:
                return "authority", None
            candidate.google_sub, candidate.google_email = claims["sub"], claims.get("email")
            candidate.google_linked_at = _now()
            user = candidate
    if user is None:
        return "not_linked", None
    if user.role != OWNER_ROLE:
        return "authority", None
    if user.status != "active":
        return "inactive", None
    return "ok", user


def _link_outcome(db: Session, row: OAuthState, claims: dict) -> tuple[str, User | None]:
    user = db.get(User, row.user_id)
    if user is None or user.status != "active":
        return "inactive", None
    if user.role != OWNER_ROLE:
        return "authority", None
    other = db.query(User).filter(User.google_sub == claims["sub"], User.id != user.id).one_or_none()
    if other is not None:
        return "sub_taken", None
    user.google_sub, user.google_email, user.google_linked_at = claims["sub"], claims.get("email"), _now()
    return "linked", user


@router.get("/callback")
def google_callback(state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    _require_enabled()
    row = db.get(OAuthState, _sha(state)) if state else None
    if row is None or row.purpose not in ("login", "link"):
        return _done(error="invalid_state")
    db.delete(row)              # single use, whatever happens next
    db.commit()
    if row.expires_at < _now():
        return _done(error="invalid_state")
    if error or not code:
        return _done(error="cancelled")
    try:
        claims = verify_id_token(_exchange_code(code, row.code_verifier), row.nonce)
    except GoogleTokenError:
        outcome, user = "invalid_token", None
    else:
        outcome, user = (_login_outcome if row.purpose == "login" else
                         lambda d, c: _link_outcome(d, row, c))(db, claims)
    handoff = secrets.token_urlsafe(32)
    db.add(OAuthState(id=_sha(handoff), purpose="handoff", user_id=user.id if user else None,
                      tab_hash=row.tab_hash, outcome=outcome, expires_at=_now() + HANDOFF_TTL))
    db.commit()
    return _done(handoff=handoff)


class ExchangeRequest(BaseModel):
    handoff: str = Field(min_length=16, max_length=128)
    tab_nonce: str = Field(min_length=16, max_length=128)


@router.post("/exchange")
def google_exchange(body: ExchangeRequest, db: Session = Depends(get_db)):
    _require_enabled()
    row = db.get(OAuthState, _sha(body.handoff))
    if row is None or row.purpose != "handoff":
        raise HTTPException(status_code=400, detail="This sign-in link has expired. Try again.")
    if not secrets.compare_digest(row.tab_hash, _sha(body.tab_nonce)):
        # not consumed: the right tab can still redeem it
        raise HTTPException(status_code=400, detail="This sign-in was started in another tab.")
    db.delete(row)
    db.commit()
    if row.expires_at < _now():
        raise HTTPException(status_code=400, detail="This sign-in link has expired. Try again.")
    if row.outcome in MESSAGES:
        code, detail = MESSAGES[row.outcome]
        raise HTTPException(status_code=code, detail=detail)
    user = db.get(User, row.user_id) if row.user_id else None
    if user is None or user.status != "active":
        raise HTTPException(status_code=403, detail=MESSAGES["inactive"][1])
    if user.role != OWNER_ROLE:       # re-checked at redemption time
        raise HTTPException(status_code=403, detail=MESSAGES["authority"][1])
    if row.outcome == "linked":
        return {"linked": True, "google_email": user.google_email}
    token = create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role})
    return TokenResponse(access_token=token, token_type="bearer", user=UserResponse.model_validate(user))


@router.post("/unlink")
def google_unlink(user: User = Depends(require_citizen), db: Session = Depends(get_db)):
    user.google_sub = user.google_email = user.google_linked_at = None
    db.commit()
    return {"linked": False}
