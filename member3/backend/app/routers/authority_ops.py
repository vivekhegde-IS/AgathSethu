"""
AGHAT SETHU — Authority operations: dashboard summary, fines & revenue

Authority only. Every number is computed from stored records at request time;
months and days are Asia/Kolkata.

  GET /api/authority/summary      home dashboard counts + latest crash frame
  GET /api/authority/fines        fines list (filter/paginate) + revenue views
"""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.deps import require_authority
from app.models.citizen_fines import Fine, FinePayment
from app.models.models import EvidenceFile, Incident
from app.services.fine_service import normalize_plate
from app.services.notification_service import IST, incident_reference, junction_label

router = APIRouter(prefix="/api/authority", tags=["Authority Operations"],
                   dependencies=[Depends(require_authority)])

TZ = "Asia/Kolkata"


def _iso(value):
    return value.isoformat() if value else None


def _ist_day_start() -> datetime:
    return datetime.combine(datetime.now(IST).date(), time.min, tzinfo=IST)


def _live_incidents(db: Session):
    return (db.query(Incident)
            .filter(Incident.dedupe_key.isnot(None), Incident.source == "live",
                    Incident.archived.is_(False)))


# Frame kinds that show the crash itself, best first.
FRAME_KINDS = ("crash_frame", "hero_frame", "annotated_frame", "primary_frame")


@router.get("/summary")
def summary(db: Session = Depends(get_db)):
    today = _ist_day_start()
    incidents = _live_incidents(db)
    unresolved = incidents.filter(Incident.status != "resolved")
    fines = db.query(Fine)

    by_type = (db.query(Fine.violation_type, func.count(Fine.id))
               .group_by(Fine.violation_type).order_by(func.count(Fine.id).desc()).all())
    pending = (db.query(func.count(Fine.id), func.coalesce(func.sum(Fine.fine_amount), 0.0))
               .filter(Fine.status != "Paid").one())
    collected = db.query(func.count(FinePayment.id), func.coalesce(func.sum(FinePayment.amount), 0.0)).one()

    latest_frame = None
    for kind in FRAME_KINDS:
        row = (db.query(EvidenceFile, Incident).join(Incident, Incident.id == EvidenceFile.incident_id)
               .filter(EvidenceFile.kind == kind, Incident.source == "live",
                       Incident.archived.is_(False), Incident.dedupe_key.isnot(None))
               .order_by(EvidenceFile.created_at.desc()).first())
        if row is not None:
            evidence, incident = row
            latest_frame = {
                "incident_id": str(incident.id), "reference": incident_reference(incident.id),
                "location": junction_label(evidence.junction_id or incident.crash_junction),
                "url": f"/api/incidents/{incident.id}/evidence/{evidence.id}",
                "captured_at": _iso(evidence.created_at), "kind": evidence.kind,
            }
            break

    recent = incidents.order_by(Incident.created_at.desc()).limit(5).all()
    return {
        "crashes": {
            "total": incidents.count(),
            "unresolved": unresolved.count(),
            "today": incidents.filter(Incident.created_at >= today).count(),
            "resolved_today": incidents.filter(Incident.status == "resolved",
                                               Incident.resolved_at >= today).count(),
        },
        "violations": {
            "total": fines.count(),
            "today": fines.filter(Fine.detected_at >= today).count(),
            "by_type": [{"violation_type": t, "count": c} for t, c in by_type],
        },
        "fines": {
            "pending_count": pending[0], "pending_amount": float(pending[1]),
            "paid_count": collected[0], "collected_amount": float(collected[1]),
        },
        "latest_crash_frame": latest_frame,
        "recent_incidents": [{
            "id": str(i.id), "reference": incident_reference(i.id),
            "location": junction_label(i.crash_junction), "created_at": _iso(i.created_at),
            "resolved": i.status == "resolved",
        } for i in recent],
    }


@router.get("/fines")
def fines_and_revenue(
    status: str = Query("all", description="all | Unpaid | Paid"),
    day: date | None = Query(None, alias="date", description="challans issued on this IST day (YYYY-MM-DD)"),
    plate: str | None = Query(None, max_length=20, description="number plate, full or partial (spaces ignored)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    year: int | None = Query(None, ge=2000, le=2100, description="year of the monthly revenue view"),
    db: Session = Depends(get_db),
):
    year = year or datetime.now(IST).year
    query = db.query(Fine)
    if status in ("Unpaid", "Paid"):
        query = query.filter(Fine.status == status)
    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=IST)
        query = query.filter(Fine.detected_at >= start, Fine.detected_at < start + timedelta(days=1))
    plate_norm = normalize_plate(plate)
    if plate_norm:
        # plates are stored normalised (letters and digits only)
        query = query.filter(Fine.number_plate.contains(plate_norm, autoescape=True))
    total = query.count()
    rows = (query.order_by(Fine.detected_at.desc(), Fine.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    payments = {p.fine_id: p for p in db.query(FinePayment)
                .filter(FinePayment.fine_id.in_([f.id for f in rows])).all()} if rows else {}

    issued = db.query(func.count(Fine.id), func.coalesce(func.sum(Fine.fine_amount), 0.0)).one()
    pending = (db.query(func.count(Fine.id), func.coalesce(func.sum(Fine.fine_amount), 0.0))
               .filter(Fine.status != "Paid").one())
    paid = db.query(func.count(FinePayment.id), func.coalesce(func.sum(FinePayment.amount), 0.0)).one()

    paid_ist = func.timezone(TZ, FinePayment.paid_at)
    monthly = dict(
        (int(m), (int(c), float(a))) for m, c, a in
        db.query(extract("month", paid_ist), func.count(FinePayment.id), func.sum(FinePayment.amount))
        .filter(extract("year", paid_ist) == year).group_by(extract("month", paid_ist)).all())

    issued_ist = func.timezone(TZ, Fine.detected_at)
    issued_by_year = {int(y): (int(c), float(a)) for y, c, a in
                      db.query(extract("year", issued_ist), func.count(Fine.id), func.sum(Fine.fine_amount))
                      .group_by(extract("year", issued_ist)).all()}
    paid_by_year = {int(y): (int(c), float(a)) for y, c, a in
                    db.query(extract("year", paid_ist), func.count(FinePayment.id), func.sum(FinePayment.amount))
                    .group_by(extract("year", paid_ist)).all()}
    pending_by_year = {int(y): (int(c), float(a)) for y, c, a in
                       db.query(extract("year", issued_ist), func.count(Fine.id), func.sum(Fine.fine_amount))
                       .filter(Fine.status != "Paid").group_by(extract("year", issued_ist)).all()}

    return {
        "totals": {
            "issued_count": issued[0], "issued_amount": float(issued[1]),
            "pending_count": pending[0], "pending_amount": float(pending[1]),
            "paid_count": paid[0], "collected_amount": float(paid[1]),
        },
        "monthly_revenue": {
            "year": year,
            "months": [{"month": m, "payments": monthly.get(m, (0, 0.0))[0],
                        "collected": monthly.get(m, (0, 0.0))[1]} for m in range(1, 13)],
        },
        "annual": [{
            "year": y,
            "issued_count": issued_by_year.get(y, (0, 0.0))[0],
            "issued_amount": issued_by_year.get(y, (0, 0.0))[1],
            "collected_count": paid_by_year.get(y, (0, 0.0))[0],
            "collected_amount": paid_by_year.get(y, (0, 0.0))[1],
            "pending_count": pending_by_year.get(y, (0, 0.0))[0],
            "pending_amount": pending_by_year.get(y, (0, 0.0))[1],
        } for y in sorted(set(issued_by_year) | set(paid_by_year), reverse=True)],
        "fines": {
            "total": total, "page": page, "page_size": page_size,
            "items": [{
                "id": f.id, "number_plate": f.number_plate, "violation_type": f.violation_type,
                "fine_amount": f.fine_amount, "status": f.status, "detected_at": _iso(f.detected_at),
                "paid_at": _iso(payments[f.id].paid_at) if f.id in payments else None,
                "reference": payments[f.id].reference if f.id in payments else None,
            } for f in rows],
        },
    }
