"""
AGHAT SETHU — Fines issued, paid and disputed live (DB first, then broadcast).

Status values stay those of the existing `fines` table: Unpaid (= issued),
Paid, Disputed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.citizen_fines import Fine
from app.models.models import User, Vehicle
from app.services import events
from app.services.crash_notify import notification_view, plate_display
from app.services.notification_service import notify_fine_issued

STATE = {"Unpaid": "issued", "Paid": "paid", "Disputed": "disputed"}


def fine_view(db, fine: Fine, for_authority: bool = False) -> dict:
    vehicle = db.get(Vehicle, fine.vehicle_id) if fine.vehicle_id else None
    view = {"id": fine.id, "vehicle_id": str(fine.vehicle_id) if fine.vehicle_id else None,
            "letter": vehicle.carla_letter if vehicle else None,
            "plate": plate_display(vehicle) if vehicle else fine.number_plate,
            "amount": fine.fine_amount, "reason": fine.violation_type, "location": fine.location,
            "timestamp": fine.detected_at.isoformat() if fine.detected_at else None,
            "status": STATE.get(fine.status, fine.status.lower()), "raw_status": fine.status,
            "dispute_reason": fine.dispute_reason,
            "disputed_at": fine.disputed_at.isoformat() if fine.disputed_at else None}
    if for_authority:
        owner = db.get(User, fine.user_id)
        view["owner_name"] = owner.full_name if owner else None
    return view


def publish_fine(db, fine: Fine, event_type: str, note=None) -> None:
    """After commit: the owner gets their fine, the authority gets it with the owner name."""
    events.publish(event_type, {"fine": fine_view(db, fine)}, user_ids=[fine.user_id], authority=False)
    events.publish(event_type, {"fine": fine_view(db, fine, for_authority=True)})
    if note is not None:
        events.publish("notification.created", {"notification": notification_view(note)},
                       user_ids=[fine.user_id], authority=False)


def issue_fine(db, authority: User, vehicle: Vehicle, amount: float, reason: str,
               location: str | None) -> Fine:
    fine = Fine(user_id=vehicle.owner_id, vehicle_id=vehicle.id, number_plate=vehicle.plate_number,
                violation_type=reason, fine_amount=amount, location=location, issued_by=authority.id,
                status="Unpaid", detected_at=datetime.now(timezone.utc))
    db.add(fine)
    db.flush()
    note = notify_fine_issued(db, fine)
    db.commit()
    db.refresh(fine)
    publish_fine(db, fine, "fine.issued", note)
    return fine
