"""
AGHAT SETHU — Citizen Fine ORM Models (migration 005)

Fines generated from routine-violation videos. A fine belongs to the existing
citizen account (users) that owns the plate in the existing vehicles table.
"""

import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base
# Registers `users` / `vehicles`, which the foreign keys below reference by name,
# so this module works no matter which models module is imported first.
import app.models.models  # noqa: F401,E402


# ── Videos ────────────────────────────────────────────────────────────────────────
class Video(Base):
    __tablename__ = "videos"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, index=True)
    path = Column(String(1024), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    fines = relationship("Fine", back_populates="video")


# ── Fines ─────────────────────────────────────────────────────────────────────────
class Fine(Base):
    __tablename__ = "fines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(64), nullable=True, index=True)       # processing run that issued it
    number_plate = Column(String(20), nullable=False)
    violation_type = Column(String(100), nullable=False)
    fine_amount = Column(Float, nullable=False)
    snapshot_image_path = Column(String(1024), nullable=True)
    clip_path = Column(String(1024), nullable=True)
    plate_status = Column(String(32), nullable=True)               # confirmed | low_confidence
    evidence_time_s = Column(Float, nullable=True)                 # position in the video
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status = Column(String(16), nullable=False, default="Unpaid", server_default="Unpaid")

    video = relationship("Video", back_populates="fines")

    __table_args__ = (Index("ix_fines_user_id_detected_at", "user_id", "detected_at"),)


# ── Unmatched violations (plate unreadable or not registered) ─────────────────────
class UnmatchedViolation(Base):
    __tablename__ = "unmatched_violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(64), nullable=True, index=True)
    number_plate = Column(String(20), nullable=True)               # normalized; NULL if unreadable
    plate_raw = Column(String(64), nullable=True)
    plate_status = Column(String(32), nullable=True)
    violation_type = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)                          # not_registered | unreadable_plate
    snapshot_image_path = Column(String(1024), nullable=True)
    evidence_time_s = Column(Float, nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ── Pending verification (partial plates: never fined automatically) ──────────────
class PendingVerification(Base):
    """A violation whose plate was only partially read. Holds the strict
    partial pattern, the real captured frame and the registered plates that
    fit it, until RFID fusion or an authority resolves it. Never shown to
    citizens."""

    __tablename__ = "pending_verification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    video_id = Column(Integer, ForeignKey("videos.id", ondelete="SET NULL"), nullable=True)
    job_id = Column(String(64), nullable=True, index=True)
    track_id = Column(String(64), nullable=True)                   # raw tracker id the reads came from
    violation_type = Column(String(100), nullable=False)
    partial_pattern = Column(String(64), nullable=False)           # e.g. "KA __ AT 3514"
    alternative_patterns = Column(JSON, nullable=True)
    pattern_regex = Column(Text, nullable=False)
    is_complete = Column(Boolean, nullable=False, default=False)
    confidence = Column(Float, nullable=True)
    pipeline_plate_status = Column(String(32), nullable=True)      # unreadable | low_confidence
    partial_json = Column(JSON, nullable=True)                     # full analysis (segments, reads, corrections)
    candidates = Column(JSON, nullable=True)                       # [{"plate", "score", "vehicle_id"}]
    snapshot_image_path = Column(String(1024), nullable=True)      # relative to static/
    evidence_time_s = Column(Float, nullable=True)
    status = Column(String(24), nullable=False, default="pending", server_default="pending")
    resolved_plate = Column(String(20), nullable=True)
    resolved_by = Column(String(64), nullable=True)                # rfid | authority:<user id>
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    detected_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    video = relationship("Video")


# ── Fine payments (migration 007) ─────────────────────────────────────────────────
class FinePayment(Base):
    """One row per paid fine: the receipt the citizen keeps. The payment
    itself is simulated; the record is real and is what revenue is summed from."""

    __tablename__ = "fine_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fine_id = Column(Integer, ForeignKey("fines.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)
    method = Column(String(32), nullable=False)                    # upi | card | netbanking
    reference = Column(String(32), nullable=False, unique=True)    # receipt number shown to the citizen
    paid_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    fine = relationship("Fine")


# ── Citizen notifications (migration 007) ─────────────────────────────────────────
class Notification(Base):
    """A stored citizen alert. Written once when the event happens (crash
    involvement, fine issued) and only marked read afterwards."""

    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String(32), nullable=False)                      # crash_involvement | fine_issued
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True)
    fine_id = Column(Integer, ForeignKey("fines.id", ondelete="CASCADE"), nullable=True)
    plate_norm = Column(String(20), nullable=True)
    data = Column(JSON, nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "kind", "incident_id", "plate_norm", name="uq_notifications_incident"),
        UniqueConstraint("user_id", "kind", "fine_id", name="uq_notifications_fine"),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
    )
