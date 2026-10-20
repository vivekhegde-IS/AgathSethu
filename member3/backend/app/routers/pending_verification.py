"""
AGHAT SETHU — Partial-plate violations (authority only)

Violations whose plate was only partially read: strict partial pattern, real
captured frame and the registered plates that fit it. Nobody is fined for
these; they wait for RFID fusion or authority review. Authority / admin only
(require_authority) - never exposed to citizens.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.dependencies.deps import require_authority
from app.models.citizen_fines import PendingVerification
from app.models.models import User
from app.services.fine_service import static_file

router = APIRouter(prefix="/api/authority/pending-verifications", tags=["Partial Plates (Authority)"])

NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


@router.get("")
def list_pending(response: Response, status: str | None = "pending",
                 _: User = Depends(require_authority), db: Session = Depends(get_db)):
    response.headers.update(NO_STORE)
    query = db.query(PendingVerification).options(joinedload(PendingVerification.video))
    if status and status != "all":
        query = query.filter(PendingVerification.status == status)
    rows = query.order_by(PendingVerification.detected_at.desc(), PendingVerification.id.desc()).all()
    return {"items": [{
        "id": r.id,
        "detected_at": r.detected_at.isoformat() if r.detected_at else None,
        "video_name": r.video.filename if getattr(r, "video", None) else None,
        "job_id": r.job_id,
        "track_id": r.track_id,
        "violation_type": r.violation_type,
        "partial_pattern": r.partial_pattern,
        "alternative_patterns": r.alternative_patterns or [],
        "regex": r.pattern_regex,
        "is_complete": r.is_complete,
        "confidence": r.confidence,
        "pipeline_plate_status": r.pipeline_plate_status,
        "segments": (r.partial_json or {}).get("segments"),
        "raw_ocr_text": (r.partial_json or {}).get("raw_ocr_text"),
        "corrections": (r.partial_json or {}).get("corrections") or [],
        "candidates": r.candidates or [],
        "evidence_time_s": r.evidence_time_s,
        "status": r.status,
        "image_url": f"/api/authority/pending-verifications/{r.id}/snapshot" if r.snapshot_image_path else None,
    } for r in rows]}


@router.get("/{pending_id}/snapshot")
def pending_snapshot(pending_id: int, _: User = Depends(require_authority), db: Session = Depends(get_db)):
    row = db.get(PendingVerification, pending_id)
    path = static_file(row.snapshot_image_path) if row else None
    if path is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(path, media_type="image/jpeg", headers=NO_STORE)
