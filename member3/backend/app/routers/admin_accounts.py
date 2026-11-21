"""
AGHAT SETHU — Admin: approve or reject officer (authority) sign-ups.

Authority sign-ups start as status 'pending_approval' and cannot log in until
an admin approves them. The mobile app's "Officer Approvals" tab and the
website's /authority/approvals page use these (same paths and shapes as the
app's own backend):

  GET  /api/admin/authority-accounts               officers waiting for approval
  POST /api/admin/authority-accounts/{id}/approve  approve one (-> active)
  POST /api/admin/authority-accounts/{id}/reject   reject one  (-> suspended: cannot log in)

Both decisions email the officer (services/approval_email.py, background).
Super-admin resolution codes for crashes are at the end of this file.
Admins only (require_admin).
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_admin
from app.models.live import ResolutionCode
from app.models.models import Incident, User
from app.services import resolution_codes
from app.services.approval_email import send_decision_email

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])

PENDING = "pending_approval"
REJECTED = "suspended"


def _account_view(user: User) -> dict:
    # both naming styles: the website's (full_name / phone) and the app's (name / mobile)
    return {"id": str(user.id), "name": user.full_name, "full_name": user.full_name, "email": user.email,
            "mobile": user.phone, "phone": user.phone, "role": user.role, "status": user.status,
            "badge_number": user.badge_number, "jurisdiction": user.jurisdiction,
            "created_at": user.created_at.isoformat() if user.created_at else None}


def _officer(db: Session, user_id: str) -> User:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Authority account not found.")
    user = db.get(User, uid)
    if user is None or user.role != "authority":
        raise HTTPException(status_code=404, detail="Authority account not found.")
    return user


@router.get("/authority-accounts")
def pending_authority_accounts(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    users = (db.query(User).filter(User.role == "authority", User.status == PENDING)
             .order_by(User.created_at).all())
    return {"items": [_account_view(u) for u in users], "total": len(users)}


@router.post("/authority-accounts/{user_id}/approve")
def approve_authority(user_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    user = _officer(db, user_id)
    if user.status != "active":
        user.status = "active"
        db.commit()
        db.refresh(user)
        background.add_task(send_decision_email, user.full_name, user.email, True)
    return _account_view(user)


@router.post("/authority-accounts/{user_id}/reject")
def reject_authority(user_id: str, background: BackgroundTasks, db: Session = Depends(get_db)):
    """The account stays (an audit trail of who asked) but can never sign in."""
    user = _officer(db, user_id)
    if user.status == "active":
        raise HTTPException(status_code=409, detail="This officer is already approved.")
    if user.status != REJECTED:
        user.status = REJECTED
        db.commit()
        db.refresh(user)
        background.add_task(send_decision_email, user.full_name, user.email, False)
    return _account_view(user)


# ── resolution codes (services/resolution_codes.py) ─────────────────────────────
#   GET  /api/admin/resolution-requests              officers waiting for a code
#   POST /api/admin/resolution-requests/{id}/issue   generate it (plain code returned once)
#   POST /api/admin/resolution-requests/{id}/decline
#   POST /api/admin/incidents/{incident_id}/resolution-code   generate one unasked
class IssueRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


def _request_row(db: Session, request_id: int) -> ResolutionCode:
    row = db.get(ResolutionCode, request_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Code request not found.")
    return row


def _issued(db: Session, row: ResolutionCode, code: str) -> dict:
    return {**resolution_codes.request_view(db, row, with_incident=True), "code": code,
            "note": "Shown only now. Give it to the officer at the scene; it works once, for this crash only."}


@router.get("/resolution-requests")
def resolution_requests(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    rows = (db.query(ResolutionCode).filter(ResolutionCode.status == "requested")
            .order_by(ResolutionCode.requested_at).all())
    return {"items": [resolution_codes.request_view(db, r, with_incident=True) for r in rows], "total": len(rows)}


@router.post("/resolution-requests/{request_id}/issue")
def issue_resolution_code(request_id: int, response: Response, admin: User = Depends(require_admin),
                          db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    row, code = resolution_codes.issue(db, _request_row(db, request_id), admin)
    return _issued(db, row, code)


@router.post("/resolution-requests/{request_id}/decline")
def decline_resolution_code(request_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return resolution_codes.request_view(db, resolution_codes.decline(db, _request_row(db, request_id), admin),
                                         with_incident=True)


@router.post("/incidents/{incident_id}/resolution-code")
def generate_resolution_code(incident_id: str, response: Response, body: IssueRequest | None = None,
                             admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        incident = db.get(Incident, uuid.UUID(incident_id))
    except ValueError:
        incident = None
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    if incident.status in ("resolved", "false_positive"):
        raise HTTPException(status_code=409, detail="Incident is already resolved.")
    row, code = resolution_codes.issue_for_incident(db, incident, admin, body.reason if body else None)
    return _issued(db, row, code)
