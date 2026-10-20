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

    # --- RFID -> camera cross-verification (migration 002) ---
    # run_id scopes everything: alert ids restart every CARLA run, so a run plus
    # the involved plates plus the junction is what makes an incident idempotent.
    run_id = Column(String(64), nullable=True, index=True)
    crash_ts_sim = Column(Float, nullable=True)          # event (sim) time, never wall clock
    crash_frame = Column(Integer, nullable=True)
    crash_junction = Column(String(16), nullable=True)
    world_x = Column(Float, nullable=True)
    world_y = Column(Float, nullable=True)
    world_z = Column(Float, nullable=True)
    dedupe_key = Column(String(255), nullable=True, unique=True)
    # RFID cross-verification (migration 004)
    source = Column(String(16), nullable=True, index=True)       # live | replay | synthetic
    archived = Column(Boolean, nullable=False, default=False, server_default="false")
    run_started_at = Column(DateTime(timezone=True), nullable=True)
    # Officer resolution (migration 007); resolved_at above is set with it
    resolved_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note = Column(Text, nullable=True)

    # Relationships
    junction = relationship("Junction", back_populates="incidents")
    collision_event = relationship("CollisionEvent", back_populates="incident", uselist=False)
    evidence = relationship("Evidence", back_populates="incident")
    anpr_detections = relationship("ANPRDetection", back_populates="incident")
    rfid_reads = relationship("RFIDRead", back_populates="incident")

    __table_args__ = (
        Index("ix_incidents_junction_id_created_at", "junction_id", "created_at"),
        Index("ix_incidents_status", "status"),
        # run_id already carries index=True, which creates ix_incidents_run_id.
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


# =================================================================================
# RFID -> CAMERA PLATE CROSS-VERIFICATION (migration 002)
# =================================================================================


# ── Vehicle Registry ──────────────────────────────────────────────────────────────
class VehicleRegistry(Base):
    """EPC -> plate. The ONLY way a tag becomes a plate.

    An EPC that is not here resolves to a NULL plate and is reported as
    UNREGISTERED_TAG; a plate is never invented for it.
    """

    __tablename__ = "vehicle_registry"

    epc = Column(String(64), primary_key=True)
    plate_norm = Column(String(20), nullable=True, index=True)
    plate_display = Column(String(32), nullable=True)
    state_code = Column(String(8), nullable=True)
    sim_vehicle_id = Column(String(8), nullable=True)   # debug only, never matched on
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Incident Alerts ──────────────────────────────────────────────────────────────
class IncidentAlert(Base):
    """Every crash alert linked to its incident, for the full audit trail."""

    __tablename__ = "incident_alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=False)
    alert_id = Column(String(64), nullable=False)
    run_id = Column(String(64), nullable=True)
    source = Column(String(16), nullable=False)          # physics | imu_gps
    status = Column(String(64), nullable=True)
    timestamp_sim = Column(Float, nullable=True)          # event time
    frame = Column(Integer, nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Idempotency: a retried alert never links twice.
        UniqueConstraint("incident_id", "alert_id", name="uq_incident_alerts_incident_alert"),
        Index("ix_incident_alerts_alert_id", "alert_id"),
    )


# ── Incident Vehicles ────────────────────────────────────────────────────────────
class IncidentVehicle(Base):
    __tablename__ = "incident_vehicles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=False)
    plate_norm = Column(String(20), nullable=False)
    plate_display = Column(String(32), nullable=True)
    epc = Column(String(64), nullable=True)
    role = Column(String(16), nullable=False, default="involved")   # involved | nearby
    sim_vehicle_id = Column(String(8), nullable=True)               # debug only
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("incident_id", "plate_norm", "role", name="uq_incident_vehicles_plate_role"),
        Index("ix_incident_vehicles_epc", "epc"),
    )


# ── RFID Reports (raw archive) ───────────────────────────────────────────────────
class RfidReport(Base):
    """Optional raw archive of normalized reports; UNIQUE is the dedupe."""

    __tablename__ = "rfid_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(String(64), nullable=True)
    reader_id = Column(String(64), nullable=False)
    seq = Column(Integer, nullable=False)
    junction_id = Column(String(16), nullable=False)
    epc = Column(String(64), nullable=False)
    plate_norm = Column(String(20), nullable=True)          # from the registry; NULL if unknown
    registry_status = Column(String(24), nullable=True)     # REGISTERED | UNREGISTERED_TAG
    first_seen_ts = Column(Float, nullable=False)
    last_seen_ts = Column(Float, nullable=False)
    tag_seen_count = Column(Integer, nullable=True)
    rssi_dbm = Column(Float, nullable=True)
    schema = Column(String(32), nullable=True)
    sim_vehicle_id = Column(String(8), nullable=True)      # debug only
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("run_id", "reader_id", "seq", name="uq_rfid_reports_run_reader_seq"),
        Index("ix_rfid_reports_epc_time", "epc", "last_seen_ts"),
    )


# ── Crash-zone RFID snapshot ─────────────────────────────────────────────────────
class CrashZoneRfid(Base):
    __tablename__ = "crash_zone_rfid"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=False)
    junction_id = Column(String(16), nullable=False)
    reader_id = Column(String(64), nullable=True)
    epc = Column(String(64), nullable=False)
    plate_norm = Column(String(20), nullable=True)
    first_seen_ts = Column(Float, nullable=False)
    last_seen_ts = Column(Float, nullable=False)
    report_count = Column(Integer, nullable=False, default=0)
    tag_seen_count = Column(Integer, nullable=False, default=0)
    peak_rssi_dbm = Column(Float, nullable=True)
    role = Column(String(16), nullable=False, default="involved")
    zone = Column(String(16), nullable=False, default="crash", server_default="crash")  # crash | context
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("incident_id", "junction_id", "epc",
                         name="uq_crash_zone_rfid_incident_junction_epc"),
        Index("ix_crash_zone_rfid_incident", "incident_id"),
    )


# ── RFID Sightings ───────────────────────────────────────────────────────────────
class RfidSighting(Base):
    __tablename__ = "rfid_sightings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=False)
    epc = Column(String(64), nullable=False)
    plate_norm = Column(String(20), nullable=True)
    junction_id = Column(String(16), nullable=False)
    reader_id = Column(String(64), nullable=True)
    first_seen_ts = Column(Float, nullable=False)
    last_seen_ts = Column(Float, nullable=False)
    report_count = Column(Integer, nullable=False, default=0)
    tag_seen_count = Column(Integer, nullable=False, default=0)
    peak_rssi_dbm = Column(Float, nullable=True)
    closed = Column(Boolean, nullable=False, default=False)
    finalized = Column(Boolean, nullable=False, default=False, server_default="false")
    version = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_rfid_sightings_incident_epc", "incident_id", "epc"),
    )


# ── Vision Matches ───────────────────────────────────────────────────────────────
class VisionMatch(Base):
    __tablename__ = "vision_matches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sighting_id = Column(UUID(as_uuid=True), ForeignKey("rfid_sightings.id", ondelete="CASCADE"),
                         nullable=False)
    status = Column(String(32), nullable=False)
    rfid_plate = Column(String(20), nullable=True)
    anpr_plate = Column(String(20), nullable=True)
    anpr_confidence = Column(Float, nullable=True)
    edit_distance = Column(Integer, nullable=True)
    camera_id = Column(String(64), nullable=True)
    best_frame_ts = Column(Float, nullable=True)         # event time
    time_delta_s = Column(Float, nullable=True)
    frames_used = Column(Integer, nullable=True)
    all_plates_seen = Column(JSON, nullable=True)
    anpr_model = Column(String(255), nullable=True)
    # rule-based fusion (migration 004)
    rule_assisted = Column(Boolean, nullable=False, default=False, server_default="false")
    match_reason = Column(String(255), nullable=True)
    diff = Column(JSON, nullable=True)               # [{position, anpr, rfid}]
    other_vehicles = Column(JSON, nullable=True)     # valid plates of other vehicles in view
    rejected_reads = Column(JSON, nullable=True)     # [{raw, reasons, frame_ts}]
    per_frame = Column(JSON, nullable=True)          # per-frame raw/corrected/valid/reasons
    max_plate_px = Column(Float, nullable=True)
    cluster_frames = Column(Integer, nullable=True)
    anpr_state_code = Column(String(4), nullable=True)
    version = Column(Integer, nullable=False, default=0, server_default="0")
    finalized = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("sighting_id", name="uq_vision_matches_sighting"),
        Index("ix_vision_matches_status", "status"),
    )


# ── Evidence Files ───────────────────────────────────────────────────────────────
class EvidenceFile(Base):
    """Path + sha256 only: image bytes never go into Postgres."""

    __tablename__ = "evidence_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"),
                         nullable=True)
    vision_match_id = Column(UUID(as_uuid=True), ForeignKey("vision_matches.id", ondelete="CASCADE"),
                             nullable=True)
    owner = Column(String(32), nullable=False)           # incident | vision_match
    kind = Column(String(32), nullable=False)            # annotated_frame | plate_crop | crash_frame
    path = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)
    frame_ts = Column(Float, nullable=True)          # sim time of the frame
    junction_id = Column(String(16), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_evidence_files_incident", "incident_id"),
        Index("ix_evidence_files_vision_match", "vision_match_id"),
    )
