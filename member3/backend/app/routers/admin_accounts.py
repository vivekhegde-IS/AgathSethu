"""
AGHAT SETHU — Admin: approve officer (authority) sign-ups.

Authority sign-ups start as status 'pending_approval' and cannot log in until
an admin approves them. These are the routes the mobile app's
"Officer Approvals" tab calls (same paths and shapes as the app's own backend):

  GET  /api/admin/authority-accounts               officers waiting for approval
  POST /api/admin/authority-accounts/{id}/approve  approve one (-> active)

Admins only (require_admin).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_admin
from app.models.models import User

router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])

PENDING = "pending_approval"


def _account_view(user: User) -> dict:
    # both naming styles: the website's (full_name / phone) and the app's (name / mobile)
    return {"id": str(user.id), "name": user.full_name, "full_name": user.full_name, "email": user.email,
            "mobile": user.phone, "phone": user.phone, "role": user.role, "status": user.status,
            "badge_number": user.badge_number, "jurisdiction": user.jurisdiction,
            "created_at": user.created_at.isoformat() if user.created_at else None}


@router.get("/authority-accounts")
def pending_authority_accounts(response: Response, db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    users = (db.query(User).filter(User.role == "authority", User.status == PENDING)
             .order_by(User.created_at).all())
    return {"items": [_account_view(u) for u in users], "total": len(users)}


@router.post("/authority-accounts/{user_id}/approve")
def approve_authority(user_id: str, db: Session = Depends(get_db)):
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Authority account not found.")
    user = db.get(User, uid)
    if user is None or user.role != "authority":
        raise HTTPException(status_code=404, detail="Authority account not found.")
    if user.status == PENDING:
        user.status = "active"
        db.commit()
        db.refresh(user)
    return _account_view(user)
