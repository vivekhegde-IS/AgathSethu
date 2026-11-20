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
Admins only (require_admin).
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_admin
from app.models.models import User
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
