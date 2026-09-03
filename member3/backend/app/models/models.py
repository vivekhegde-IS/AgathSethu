"""
AGHAT SETHU — SQLAlchemy ORM Models
All database tables for the platform foundation.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


def utcnow():
    return datetime.now(timezone.utc)


# ── Users ─────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(
        Enum("citizen", "authority", "admin", name="user_role", create_type=False),
        nullable=False,
        default="citizen",
    )
    badge_number = Column(String(50), nullable=True)
    phone = Column(String(20), nullable=True)
    status = Column(
        Enum("active", "pending_approval", "suspended", name="user_status", create_type=False),
        nullable=False,
        default="active",
    )
    jurisdiction = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    vehicles = relationship("Vehicle", back_populates="owner", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user")


# ── Vehicles ──────────────────────────────────────────────────────────────────────
class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plate_number = Column(String(20), nullable=False)
    make = Column(String(100), nullable=True)
    model = Column(String(100), nullable=True)
    year = Column(Integer, nullable=True)
    color = Column(String(50), nullable=True)
    vehicle_type = Column(String(50), nullable=True)
    fastag_id = Column(String(100), nullable=True)
    registered_state = Column(String(10), nullable=True, default="KA")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    owner = relationship("User", back_populates="vehicles")
    anpr_detections = relationship("ANPRDetection", back_populates="vehicle")
    rfid_reads = relationship("RFIDRead", back_populates="vehicle")
    violations = relationship("Violation", back_populates="vehicle")
    challans = relationship("Challan", back_populates="vehicle")

    __table_args__ = (
        UniqueConstraint("plate_number", name="uq_vehicles_plate_number"),
        Index("ix_vehicles_plate_number", "plate_number"),
        Index("ix_vehicles_owner_id", "owner_id"),
    )


# ── Junctions ─────────────────────────────────────────────────────────────────────
class Junction(Base):
    __tablename__ = "junctions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    location_description = Column(String(512), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    status = Column(
        Enum("active", "inactive", "maintenance", name="junction_status", create_type=False),
        nullable=False,
        default="active",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    cameras = relationship("Camera", back_populates="junction")
    incidents = relationship("Incident", back_populates="junction")

    __table_args__ = (Index("ix_junctions_status", "status"),)


# ── Cameras ───────────────────────────────────────────────────────────────────────
class Camera(Base):
    __tablename__ = "cameras"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    junction_id = Column(UUID(as_uuid=True), ForeignKey("junctions.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    camera_type = Column(String(50), nullable=True)  # anpr, traffic, speed
    stream_url = Column(String(512), nullable=True)
    direction = Column(String(50), nullable=True)
    status = Column(
        Enum("active", "inactive", "fault", name="camera_status", create_type=False),
        nullable=False,
        default="active",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    junction = relationship("Junction", back_populates="cameras")
    violations = relationship("Violation", back_populates="camera")
    anpr_detections = relationship("ANPRDetection", back_populates="camera")

    __table_args__ = (Index("ix_cameras_junction_id", "junction_id"),)


# ── Violations ────────────────────────────────────────────────────────────────────
class Violation(Base):
    __tablename__ = "violations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    violation_type = Column(String(100), nullable=False)  # speeding, signal, parking, etc.
    severity = Column(
        Enum("low", "medium", "high", "critical", name="severity_level", create_type=False),
        nullable=False,
        default="medium",
    )
    fine_amount = Column(Float, nullable=True)
    speed_recorded = Column(Float, nullable=True)
    speed_limit = Column(Float, nullable=True)
    location_description = Column(String(512), nullable=True)
    evidence_url = Column(String(512), nullable=True)
    status = Column(
        Enum("pending", "issued", "paid", "contested", "dismissed", name="violation_status", create_type=False),
        nullable=False,
        default="pending",
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    vehicle = relationship("Vehicle", back_populates="violations")
    camera = relationship("Camera", back_populates="violations")
    challan = relationship("Challan", back_populates="violation", uselist=False)
    evidence = relationship("Evidence", back_populates="violation")

    __table_args__ = (
        Index("ix_violations_vehicle_id_created_at", "vehicle_id", "created_at"),
        Index("ix_violations_status", "status"),
    )


# ── Incidents ─────────────────────────────────────────────────────────────────────
class Incident(Base):
    __tablename__ = "incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    junction_id = Column(UUID(as_uuid=True), ForeignKey("junctions.id", ondelete="SET NULL"), nullable=True)
    incident_type = Column(String(100), nullable=False)  # crash, anomaly, congestion, etc.
    severity = Column(
        Enum("low", "medium", "high", "critical", name="incident_severity", create_type=False),
        nullable=False,
        default="medium",
    )
    status = Column(
        Enum("detected", "under_investigation", "resolved", "false_positive", name="incident_status", create_type=False),
        nullable=False,
        default="detected",
    )
    description = Column(Text, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    junction = relationship("Junction", back_populates="incidents")
    collision_event = relationship("CollisionEvent", back_populates="incident", uselist=False)
    evidence = relationship("Evidence", back_populates="incident")
    anpr_detections = relationship("ANPRDetection", back_populates="incident")
    rfid_reads = relationship("RFIDRead", back_populates="incident")

    __table_args__ = (
        Index("ix_incidents_junction_id_created_at", "junction_id", "created_at"),
        Index("ix_incidents_status", "status"),
    )


# ── ANPR Detections ───────────────────────────────────────────────────────────────
class ANPRDetection(Base):
    __tablename__ = "anpr_detections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    plate_text = Column(String(50), nullable=False)
    confidence = Column(Float, nullable=True)  # 0.0 – 1.0
    bounding_box = Column(JSON, nullable=True)  # {"x": ..., "y": ..., "w": ..., "h": ...}
    frame_url = Column(String(512), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    vehicle = relationship("Vehicle", back_populates="anpr_detections")
    camera = relationship("Camera", back_populates="anpr_detections")
    incident = relationship("Incident", back_populates="anpr_detections")

    __table_args__ = (
        Index("ix_anpr_vehicle_id_timestamp", "vehicle_id", "timestamp"),
        Index("ix_anpr_incident_id", "incident_id"),
    )


# ── RFID Reads ────────────────────────────────────────────────────────────────────
class RFIDRead(Base):
    __tablename__ = "rfid_reads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    reader_id = Column(String(100), nullable=True)
    tag_id = Column(String(100), nullable=False)
    speed = Column(Float, nullable=True)  # km/h
    lane = Column(String(10), nullable=True)
    direction = Column(String(50), nullable=True)
    fused_position = Column(JSON, nullable=True)  # {"lat": ..., "lng": ...}
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    vehicle = relationship("Vehicle", back_populates="rfid_reads")
    incident = relationship("Incident", back_populates="rfid_reads")

    __table_args__ = (
        Index("ix_rfid_vehicle_id_timestamp", "vehicle_id", "timestamp"),
        Index("ix_rfid_incident_id", "incident_id"),
    )


# ── Collision Events ──────────────────────────────────────────────────────────────
class CollisionEvent(Base):
    __tablename__ = "collision_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True)
    # vehicle_ids stored as JSON array: ["uuid1", "uuid2"]
    vehicle_ids = Column(JSON, nullable=True)
    severity = Column(String(50), nullable=True)
    collision_type = Column(String(100), nullable=True)  # rear-end, side-impact, etc.
    description = Column(Text, nullable=True)
    kalman_confidence = Column(Float, nullable=True)  # Kalman filter confidence score
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    incident = relationship("Incident", back_populates="collision_event")


# ── Challans ──────────────────────────────────────────────────────────────────────
class Challan(Base):
    __tablename__ = "challans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    violation_id = Column(UUID(as_uuid=True), ForeignKey("violations.id", ondelete="SET NULL"), nullable=True, unique=True)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    challan_number = Column(String(50), nullable=True)
    amount = Column(Float, nullable=False)
    due_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        Enum("pending", "paid", "overdue", "waived", name="challan_status", create_type=False),
        nullable=False,
        default="pending",
    )
    issued_at = Column(DateTime(timezone=True), server_default=func.now())
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    violation = relationship("Violation", back_populates="challan")
    vehicle = relationship("Vehicle", back_populates="challans")
    payment = relationship("Payment", back_populates="challan", uselist=False)

    __table_args__ = (Index("ix_challans_vehicle_id_status", "vehicle_id", "status"),)


# ── Payments ──────────────────────────────────────────────────────────────────────
class Payment(Base):
    __tablename__ = "payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    challan_id = Column(UUID(as_uuid=True), ForeignKey("challans.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)
    method = Column(String(50), nullable=True)  # UPI, card, netbanking, FASTag
    transaction_id = Column(String(255), nullable=True)
    gateway_response = Column(JSON, nullable=True)
    status = Column(
        Enum("initiated", "success", "failed", "refunded", name="payment_status", create_type=False),
        nullable=False,
        default="initiated",
    )
    paid_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    challan = relationship("Challan", back_populates="payment")
    user = relationship("User", back_populates="payments")


# ── Evidence ──────────────────────────────────────────────────────────────────────
class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True)
    violation_id = Column(UUID(as_uuid=True), ForeignKey("violations.id", ondelete="CASCADE"), nullable=True)
    evidence_type = Column(String(50), nullable=False)  # image, video, anpr_frame, rfid_log
    url = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    incident = relationship("Incident", back_populates="evidence")
    violation = relationship("Violation", back_populates="evidence")

    __table_args__ = (
        Index("ix_evidence_incident_id", "incident_id"),
        Index("ix_evidence_violation_id", "violation_id"),
    )
