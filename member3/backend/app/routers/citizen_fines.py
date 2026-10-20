"""
AGHAT SETHU — Citizen Fines Router

Fines issued from routine-violation videos to the logged-in citizen.
Uses the existing citizen login (JWT via get_current_user); every query is
scoped to current_user.id, so a citizen only ever sees their own fines.
Reads the same `fines` table (same DATABASE_URL) the authority-side video
pipeline writes to.

Evidence is served by these endpoints rather than a public /static mount, so
one citizen cannot open another citizen's violation images by URL.
"""

import secrets
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_citizen as get_current_user
from app.models.citizen_fines import Fine, FinePayment
from app.models.models import User, Vehicle
from app.services.fine_service import static_file

router = APIRouter(prefix="/api/citizen/fines", tags=["Citizen Fines"])

NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _own_fine(db: Session, fine_id: int, user: User) -> Fine:
    fine = db.get(Fine, fine_id)
    # Someone else's fine is reported exactly like a missing one.
    if fine is None or fine.user_id != user.id:
        raise HTTPException(status_code=404, detail="Fine not found")
    return fine


def _evidence(relative: str | None, media_type: str) -> FileResponse:
    path = static_file(relative)
    if path is None:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return FileResponse(path, media_type=media_type, headers=NO_STORE)


@router.get("")
def my_fines(response: Response, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    fines = (db.query(Fine).filter(Fine.user_id == current_user.id)
             .order_by(Fine.detected_at.desc(), Fine.id.desc()).all())
    vehicles = (db.query(Vehicle).filter(Vehicle.owner_id == current_user.id)
                .order_by(Vehicle.plate_number).all())
    payments = {p.fine_id: p for p in db.query(FinePayment)
                .filter(FinePayment.fine_id.in_([f.id for f in fines])).all()} if fines else {}
    return {
        "total_unpaid": sum(f.fine_amount for f in fines if f.status == "Unpaid"),
        "unpaid_count": sum(1 for f in fines if f.status == "Unpaid"),
        "vehicles": [{"id": str(v.id), "plate_number": v.plate_number, "vehicle_type": v.vehicle_type,
                      "unpaid_count": sum(1 for f in fines if f.vehicle_id == v.id and f.status == "Unpaid")}
                     for v in vehicles],
        "fines": [{
            "id": f.id,
            "detected_at": f.detected_at.isoformat() if f.detected_at else None,
            "number_plate": f.number_plate,
            "violation_type": f.violation_type,
            "video_name": f.video.filename if f.video else None,
            "fine_amount": f.fine_amount,
            "status": f.status,
            "plate_status": f.plate_status,
            "evidence_time_s": f.evidence_time_s,
            "image_path": f.snapshot_image_path,          # relative to static/, e.g. violations/<file>.jpg
            "image_url": f"/api/citizen/fines/{f.id}/snapshot" if f.snapshot_image_path else None,
            "clip_url": f"/api/citizen/fines/{f.id}/clip" if f.clip_path else None,
            "payment": _payment_view(payments[f.id]) if f.id in payments else None,
        } for f in fines],
    }


@router.get("/{fine_id}/snapshot")
def fine_snapshot(fine_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _evidence(_own_fine(db, fine_id, current_user).snapshot_image_path, "image/jpeg")


@router.get("/{fine_id}/clip")
def fine_clip(fine_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _evidence(_own_fine(db, fine_id, current_user).clip_path, "video/webm")


def _payment_view(p: FinePayment) -> dict:
    return {"id": p.id, "fine_id": p.fine_id, "amount": p.amount, "method": p.method,
            "reference": p.reference, "paid_at": p.paid_at.isoformat() if p.paid_at else None}


class PayRequest(BaseModel):
    method: Literal["upi", "card", "netbanking"]


def _new_reference(db: Session) -> str:
    """Receipt number: RCPT-YYYYMMDD-XXXXXXXX (random, checked unique)."""
    while True:
        ref = f"RCPT-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(4).upper()}"
        if db.query(FinePayment.id).filter(FinePayment.reference == ref).first() is None:
            return ref


@router.post("/{fine_id}/pay")
def pay_fine(fine_id: int, body: PayRequest, current_user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    """Simulated payment, real record: marks the fine Paid and stores the receipt.
    Row-locked, so a double click cannot pay twice."""
    fine = (db.query(Fine).filter(Fine.id == fine_id, Fine.user_id == current_user.id)
            .with_for_update().one_or_none())
    if fine is None:
        raise HTTPException(status_code=404, detail="Fine not found")
    if fine.status == "Paid":
        raise HTTPException(status_code=409, detail="This fine is already paid")
    payment = FinePayment(fine_id=fine.id, user_id=current_user.id, amount=fine.fine_amount,
                          method=body.method, reference=_new_reference(db),
                          paid_at=datetime.now(timezone.utc))
    fine.status = "Paid"
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return {"fine_id": fine.id, "status": fine.status, "payment": _payment_view(payment)}
