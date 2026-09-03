"""Initial schema — all AGHAT SETHU tables

Revision ID: 001
Revises:
Create Date: 2026-09-02

Creates all 12 tables for the project foundation:
users, vehicles, junctions, cameras, violations, incidents,
anpr_detections, rfid_reads, collision_events, challans, payments, evidence
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create Enum types if they don't exist
    user_role = postgresql.ENUM("citizen", "authority", "admin", name="user_role", create_type=False)
    user_status = postgresql.ENUM("active", "pending_approval", "suspended", name="user_status", create_type=False)
    junction_status = postgresql.ENUM("active", "inactive", "maintenance", name="junction_status", create_type=False)
    camera_status = postgresql.ENUM("active", "inactive", "fault", name="camera_status", create_type=False)
    severity_level = postgresql.ENUM("low", "medium", "high", "critical", name="severity_level", create_type=False)
    violation_status = postgresql.ENUM("pending", "issued", "paid", "contested", "dismissed", name="violation_status", create_type=False)
    incident_severity = postgresql.ENUM("low", "medium", "high", "critical", name="incident_severity", create_type=False)
    incident_status = postgresql.ENUM("detected", "under_investigation", "resolved", "false_positive", name="incident_status", create_type=False)
    challan_status = postgresql.ENUM("pending", "paid", "overdue", "waived", name="challan_status", create_type=False)
    payment_status = postgresql.ENUM("initiated", "success", "failed", "refunded", name="payment_status", create_type=False)

    for enum in [
        user_role, user_status, junction_status, camera_status, severity_level,
        violation_status, incident_severity, incident_status, challan_status, payment_status
    ]:
        enum.create(bind, checkfirst=True)

    # ── users ─────────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", postgresql.ENUM("citizen", "authority", "admin", name="user_role", create_type=False), nullable=False, server_default="citizen"),
        sa.Column("badge_number", sa.String(50), nullable=True),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("status", postgresql.ENUM("active", "pending_approval", "suspended", name="user_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("jurisdiction", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── junctions ─────────────────────────────────────────────────────────────────
    op.create_table(
        "junctions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location_description", sa.String(512), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("status", postgresql.ENUM("active", "inactive", "maintenance", name="junction_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_junctions_status", "junctions", ["status"])

    # ── cameras ───────────────────────────────────────────────────────────────────
    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("junction_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("junctions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("camera_type", sa.String(50), nullable=True),
        sa.Column("stream_url", sa.String(512), nullable=True),
        sa.Column("direction", sa.String(50), nullable=True),
        sa.Column("status", postgresql.ENUM("active", "inactive", "fault", name="camera_status", create_type=False), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_cameras_junction_id", "cameras", ["junction_id"])

    # ── vehicles ──────────────────────────────────────────────────────────────────
    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plate_number", sa.String(20), nullable=False),
        sa.Column("make", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("color", sa.String(50), nullable=True),
        sa.Column("vehicle_type", sa.String(50), nullable=True),
        sa.Column("fastag_id", sa.String(100), nullable=True),
        sa.Column("registered_state", sa.String(10), nullable=True, server_default="KA"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_vehicles_plate_number", "vehicles", ["plate_number"])
    op.create_index("ix_vehicles_plate_number", "vehicles", ["plate_number"])
    op.create_index("ix_vehicles_owner_id", "vehicles", ["owner_id"])

    # ── incidents ─────────────────────────────────────────────────────────────────
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("junction_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("junctions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_type", sa.String(100), nullable=False),
        sa.Column("severity", postgresql.ENUM("low", "medium", "high", "critical", name="incident_severity", create_type=False), nullable=False, server_default="medium"),
        sa.Column("status", postgresql.ENUM("detected", "under_investigation", "resolved", "false_positive", name="incident_status", create_type=False), nullable=False, server_default="detected"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_incidents_junction_id_created_at", "incidents", ["junction_id", "created_at"])
    op.create_index("ix_incidents_status", "incidents", ["status"])

    # ── violations ────────────────────────────────────────────────────────────────
    op.create_table(
        "violations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("violation_type", sa.String(100), nullable=False),
        sa.Column("severity", postgresql.ENUM("low", "medium", "high", "critical", name="severity_level", create_type=False), nullable=False, server_default="medium"),
        sa.Column("fine_amount", sa.Float, nullable=True),
        sa.Column("speed_recorded", sa.Float, nullable=True),
        sa.Column("speed_limit", sa.Float, nullable=True),
        sa.Column("location_description", sa.String(512), nullable=True),
        sa.Column("evidence_url", sa.String(512), nullable=True),
        sa.Column("status", postgresql.ENUM("pending", "issued", "paid", "contested", "dismissed", name="violation_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_violations_vehicle_id_created_at", "violations", ["vehicle_id", "created_at"])
    op.create_index("ix_violations_status", "violations", ["status"])

    # ── anpr_detections ───────────────────────────────────────────────────────────
    op.create_table(
        "anpr_detections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plate_text", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("bounding_box", postgresql.JSON, nullable=True),
        sa.Column("frame_url", sa.String(512), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_anpr_vehicle_id_timestamp", "anpr_detections", ["vehicle_id", "timestamp"])
    op.create_index("ix_anpr_incident_id", "anpr_detections", ["incident_id"])

    # ── rfid_reads ────────────────────────────────────────────────────────────────
    op.create_table(
        "rfid_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reader_id", sa.String(100), nullable=True),
        sa.Column("tag_id", sa.String(100), nullable=False),
        sa.Column("speed", sa.Float, nullable=True),
        sa.Column("lane", sa.String(10), nullable=True),
        sa.Column("direction", sa.String(50), nullable=True),
        sa.Column("fused_position", postgresql.JSON, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_rfid_vehicle_id_timestamp", "rfid_reads", ["vehicle_id", "timestamp"])
    op.create_index("ix_rfid_incident_id", "rfid_reads", ["incident_id"])

    # ── collision_events ──────────────────────────────────────────────────────────
    op.create_table(
        "collision_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("vehicle_ids", postgresql.JSON, nullable=True),
        sa.Column("severity", sa.String(50), nullable=True),
        sa.Column("collision_type", sa.String(100), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("kalman_confidence", sa.Float, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # ── challans ──────────────────────────────────────────────────────────────────
    op.create_table(
        "challans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("violation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("violations.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("challan_number", sa.String(50), nullable=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", postgresql.ENUM("pending", "paid", "overdue", "waived", name="challan_status", create_type=False), nullable=False, server_default="pending"),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_challans_vehicle_id_status", "challans", ["vehicle_id", "status"])

    # ── payments ──────────────────────────────────────────────────────────────────
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("challan_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("challans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Float, nullable=False),
        sa.Column("method", sa.String(50), nullable=True),
        sa.Column("transaction_id", sa.String(255), nullable=True),
        sa.Column("gateway_response", postgresql.JSON, nullable=True),
        sa.Column("status", postgresql.ENUM("initiated", "success", "failed", "refunded", name="payment_status", create_type=False), nullable=False, server_default="initiated"),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # ── evidence ──────────────────────────────────────────────────────────────────
    op.create_table(
        "evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("violation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("violations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("evidence_type", sa.String(50), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("metadata_json", postgresql.JSON, nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_evidence_incident_id", "evidence", ["incident_id"])
    op.create_index("ix_evidence_violation_id", "evidence", ["violation_id"])


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("evidence")
    op.drop_table("payments")
    op.drop_table("challans")
    op.drop_table("collision_events")
    op.drop_table("rfid_reads")
    op.drop_table("anpr_detections")
    op.drop_table("violations")
    op.drop_table("incidents")
    op.drop_table("vehicles")
    op.drop_table("cameras")
    op.drop_table("junctions")
    op.drop_table("users")

    # Drop enum types
    bind = op.get_bind()
    for enum_name in ["user_role", "user_status", "junction_status",
                      "camera_status", "severity_level", "violation_status",
                      "incident_severity", "incident_status",
                      "challan_status", "payment_status"]:
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
