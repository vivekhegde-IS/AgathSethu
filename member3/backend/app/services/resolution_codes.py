"""
AGHAT SETHU — Resolution codes: an officer can mark a crash resolved only with
proof that they dealt with it.

Two ways, either is enough (plus the officer's own password, as before):

  Owner codes     Every owner alerted about the crash gets a 6-digit code with
                  the alert (SMS, app, owner portal). The officer asks each
                  owner for theirs and enters them all (a two-car crash needs
                  both). A code works only for that crash and that owner, and
                  for RESOLUTION_OWNER_CODE_TTL_H after the alert.
                  Owner codes are derived, never stored:
                  HMAC-SHA256(server secret, "crash ref : owner id") -> 6 digits,
                  so the owner can see theirs again at any time and the database
                  holds nothing that would reveal it.

  Super-admin     An owner cannot be reached (no phone, injured, left): the
  code            officer asks for a code; a super admin (role admin) generates
                  it - a random 6-digit number (Python ``secrets``), shown once
                  to the admin, stored only as a hash, valid
                  RESOLUTION_OVERRIDE_TTL_MIN, single use. The admin passes it
                  to the officer (phone / radio). Who asked, who issued and who
                  used it are recorded.

RESOLUTION_MAX_WRONG wrong codes on one crash lock it for RESOLUTION_LOCK_MIN
(a new super-admin code lifts the lock). Crashes the owners resolve themselves
(every owner answered "minor") and the authority accepting an owner's answer do
not need a code: the owners spoke for themselves.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.live import ResolutionAttempt, ResolutionCode
from app.models.models import Incident, User
from app.services import crash_response
from app.services.plate_validation import format_plate

CODE_LEN = 6


def _key() -> bytes:
    # a key of its own, derived from the server secret (never the JWT key itself)
    return hashlib.sha256(f"aghat-resolution-codes:{settings.JWT_SECRET}".encode()).digest()


def owner_code(ref: str, user_id) -> str:
    """The 6-digit code of owner ``user_id`` for crash ``ref`` (CR-... or incident id)."""
    mac = hmac.new(_key(), f"owner:{ref}:{user_id}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(mac[:8], 'big') % 10 ** CODE_LEN:0{CODE_LEN}d}"


def _hash(ref: str, code: str) -> str:
    return hmac.new(_key(), f"override:{ref}:{code}".encode(), hashlib.sha256).hexdigest()


def _clean(codes) -> list[str]:
    out = []
    for c in codes or []:
        digits = re.sub(r"\D", "", str(c))
        if len(digits) == CODE_LEN and digits not in out:
            out.append(digits)
    return out


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ── who holds a code ────────────────────────────────────────────────────────────
def owners_for(db: Session, kind: str, ref: str) -> list[dict]:
    """The owners alerted about this crash: one code each, whatever number of
    their vehicles were involved."""
    owners: dict = {}
    for plate, (vehicle, alerted_at) in crash_response._party_alerts(db, kind, ref).items():
        if vehicle is None or vehicle.owner_id is None:
            continue
        entry = owners.setdefault(vehicle.owner_id, {"user_id": vehicle.owner_id, "plates": [],
                                                     "alerted_at": _aware(alerted_at)})
        entry["plates"].append(format_plate(plate) or plate)
        if alerted_at is not None and (entry["alerted_at"] is None or _aware(alerted_at) < entry["alerted_at"]):
            entry["alerted_at"] = _aware(alerted_at)
    for entry in owners.values():
        start = entry["alerted_at"] or _now()
        entry["expires_at"] = start + timedelta(hours=settings.RESOLUTION_OWNER_CODE_TTL_H)
    return list(owners.values())


def _ref_kind(ref: str) -> str:
    return "crash" if ref.upper().startswith("CR-") else "incident"


def code_for_owner(db: Session, user: User, ref: str, closed: bool = False) -> dict | None:
    """What the owner sees: their code for this crash, while it can still be used."""
    if closed:
        return None
    for entry in owners_for(db, _ref_kind(ref), ref):
        if entry["user_id"] == user.id:
            if entry["expires_at"] <= _now():
                return None
            return {"code": owner_code(ref, user.id), "expires_at": entry["expires_at"].isoformat(),
                    "hint": "Give this code only to the traffic officer who attends your crash. "
                            "They need it to close the case."}
    return None


def alert_line(ref: str, user_id) -> str:
    """Added to the crash alert SMS / notification."""
    return f" Resolution code: {owner_code(ref, user_id)} (give it only to the officer who attends)."


# ── lock-out ────────────────────────────────────────────────────────────────────
def locked_until(db: Session, ref: str) -> datetime | None:
    now = _now()
    since = now - timedelta(minutes=settings.RESOLUTION_LOCK_MIN)
    last_issue = (db.query(ResolutionCode.issued_at).filter(ResolutionCode.incident_ref == ref,
                                                            ResolutionCode.issued_at.isnot(None))
                  .order_by(ResolutionCode.issued_at.desc()).first())
    if last_issue and last_issue[0] and _aware(last_issue[0]) > since:
        since = _aware(last_issue[0])
    wrong = [_aware(a) for (a,) in db.query(ResolutionAttempt.at)
             .filter(ResolutionAttempt.incident_ref == ref, ResolutionAttempt.ok == 0, ResolutionAttempt.at > since)
             .order_by(ResolutionAttempt.at)]
    if len(wrong) < settings.RESOLUTION_MAX_WRONG:
        return None
    until = wrong[-settings.RESOLUTION_MAX_WRONG] + timedelta(minutes=settings.RESOLUTION_LOCK_MIN)
    return until if until > now else None


# ── officer ─────────────────────────────────────────────────────────────────────
def _user_name(db: Session, user_id) -> str | None:
    user = db.get(User, user_id) if user_id else None
    return user.full_name if user else None


def request_view(db: Session, row: ResolutionCode | None, with_incident: bool = False) -> dict | None:
    if row is None:
        return None
    now = _now()
    status = row.status
    if status == "issued" and row.expires_at and _aware(row.expires_at) <= now:
        status = "expired"
    view = {"id": row.id, "incident_ref": row.incident_ref, "status": status, "reason": row.reason,
            "requested_by_name": _user_name(db, row.requested_by),
            "requested_at": row.requested_at.isoformat() if row.requested_at else None,
            "issued_by_name": _user_name(db, row.issued_by),
            "issued_at": row.issued_at.isoformat() if row.issued_at else None,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "used_at": row.used_at.isoformat() if row.used_at else None}
    if with_incident:
        from app.services.notification_service import incident_reference, junction_label
        incident = db.get(Incident, row.incident_id) if row.incident_id else None
        view["incident_id"] = str(row.incident_id) if row.incident_id else None
        view["reference"] = incident_reference(incident.id) if incident else row.incident_ref
        view["location"] = junction_label(incident.crash_junction) if incident else None
        view["crash_at"] = incident.created_at.isoformat() if incident and incident.created_at else None
    return view


def _latest_request(db: Session, ref: str) -> ResolutionCode | None:
    return (db.query(ResolutionCode).filter(ResolutionCode.incident_ref == ref)
            .order_by(ResolutionCode.requested_at.desc(), ResolutionCode.id.desc()).first())


def status_for_officer(db: Session, incident: Incident) -> dict:
    """What the Resolve dialog shows: whose codes are needed (never the codes)."""
    ref = crash_response.case_ref_for_incident(db, incident)
    now = _now()
    owners = []
    for entry in owners_for(db, _ref_kind(ref), ref):
        owners.append({"name": _user_name(db, entry["user_id"]), "plates": entry["plates"],
                       "code_valid": entry["expires_at"] > now, "expires_at": entry["expires_at"].isoformat()})
    lock = locked_until(db, ref)
    return {"incident_ref": ref, "owners": owners,
            "owner_codes_possible": bool(owners) and all(o["code_valid"] for o in owners),
            "request": request_view(db, _latest_request(db, ref)),
            "locked_until": lock.isoformat() if lock else None}


def request_override(db: Session, incident: Incident, officer: User, reason: str | None) -> ResolutionCode:
    """The officer cannot get the owners' codes: ask a super admin for one."""
    ref = crash_response.case_ref_for_incident(db, incident)
    open_row = (db.query(ResolutionCode).filter(ResolutionCode.incident_ref == ref,
                                                ResolutionCode.status == "requested").first())
    if open_row is not None:
        return open_row
    row = ResolutionCode(incident_ref=ref, incident_id=incident.id, status="requested",
                         reason=(reason or "").strip() or None, requested_by=officer.id, requested_at=_now())
    db.add(row)
    db.commit()
    db.refresh(row)
    _announce("resolution.code_requested", db, row)
    return row


def issue(db: Session, row: ResolutionCode, admin: User) -> tuple[ResolutionCode, str]:
    """A super admin generates the code. The plain code is returned this once."""
    if row.status not in ("requested", "issued"):
        raise HTTPException(status_code=409, detail=f"This request is already {row.status}.")
    code = f"{secrets.randbelow(10 ** CODE_LEN):0{CODE_LEN}d}"
    now = _now()
    row.status, row.code_hash = "issued", _hash(row.incident_ref, code)
    row.issued_by, row.issued_at = admin.id, now
    row.expires_at = now + timedelta(minutes=settings.RESOLUTION_OVERRIDE_TTL_MIN)
    db.commit()
    db.refresh(row)
    _announce("resolution.code_issued", db, row)
    return row, code


def issue_for_incident(db: Session, incident: Incident, admin: User, reason: str | None) -> tuple[ResolutionCode, str]:
    """A super admin generates a code without an officer's request (e.g. asked by phone)."""
    ref = crash_response.case_ref_for_incident(db, incident)
    row = (db.query(ResolutionCode).filter(ResolutionCode.incident_ref == ref,
                                           ResolutionCode.status == "requested").first())
    if row is None:
        row = ResolutionCode(incident_ref=ref, incident_id=incident.id, status="requested",
                             reason=(reason or "").strip() or None, requested_by=admin.id, requested_at=_now())
        db.add(row)
        db.flush()
    return issue(db, row, admin)


def decline(db: Session, row: ResolutionCode, admin: User) -> ResolutionCode:
    if row.status != "requested":
        raise HTTPException(status_code=409, detail=f"This request is already {row.status}.")
    row.status, row.issued_by, row.issued_at = "declined", admin.id, _now()
    db.commit()
    db.refresh(row)
    _announce("resolution.code_issued", db, row)
    return row


def _announce(event: str, db: Session, row: ResolutionCode) -> None:
    from app.services import events
    events.publish(event, {"request": request_view(db, row, with_incident=True)})


def verify(db: Session, incident: Incident, officer: User, codes) -> str:
    """Raises 403 / 423 unless ``codes`` close this crash. Returns how:
    "owner" (every owner's code) or "override" (a super-admin code)."""
    ref = crash_response.case_ref_for_incident(db, incident)
    lock = locked_until(db, ref)
    if lock is not None:
        raise HTTPException(status_code=423, detail=(
            f"Too many wrong codes for this crash. Try again after {lock.strftime('%H:%M')} UTC, "
            "or ask the super admin for a new code."))
    given = _clean(codes)
    if not given:
        raise HTTPException(status_code=422, detail="Enter the owner's resolution code (6 digits).")
    now = _now()

    method = None
    for row in (db.query(ResolutionCode).filter(ResolutionCode.incident_ref == ref,
                                                ResolutionCode.status == "issued").all()):
        if row.expires_at and _aware(row.expires_at) > now and any(
                hmac.compare_digest(row.code_hash or "", _hash(ref, c)) for c in given):
            row.status, row.used_by, row.used_at = "used", officer.id, now
            method = "override"
            break
    if method is None:
        owners = [o for o in owners_for(db, _ref_kind(ref), ref)]
        valid = [o for o in owners if o["expires_at"] > now]
        if owners and len(valid) == len(owners) and all(
                any(hmac.compare_digest(owner_code(ref, o["user_id"]), c) for c in given) for o in owners):
            method = "owner"

    db.add(ResolutionAttempt(incident_ref=ref, user_id=officer.id, ok=1 if method else 0, method=method, at=now))
    db.commit()
    if method is None:
        raise HTTPException(status_code=403, detail=_why_wrong(db, ref, given))
    return method


def _why_wrong(db: Session, ref: str, given: list[str]) -> str:
    owners = owners_for(db, _ref_kind(ref), ref)
    if not owners:
        return "No owner was alerted about this crash, so it needs a code from the super admin."
    if any(o["expires_at"] <= _now() for o in owners):
        return "An owner's code has expired. Ask the super admin for a code."
    matched = sum(any(owner_code(ref, o["user_id"]) == c for c in given) for o in owners)
    if matched and matched < len(owners):
        return f"{matched} of {len(owners)} owners' codes are correct. Every owner's code is needed."
    return "The resolution code is not correct."


def resolved_with(db: Session, ref: str) -> str | None:
    row = (db.query(ResolutionAttempt.method).filter(ResolutionAttempt.incident_ref == ref, ResolutionAttempt.ok == 1)
           .order_by(ResolutionAttempt.at.desc()).first())
    return row[0] if row else None
