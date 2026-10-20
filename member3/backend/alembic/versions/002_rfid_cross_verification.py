"""RFID -> camera plate cross-verification

Revision ID: 002
Revises: 001
Create Date: 2026-09-30

Extends ``incidents`` with the run/crash columns the feature needs and creates:

  vehicle_registry, incident_alerts, incident_vehicles, rfid_reports,
  crash_zone_rfid, rfid_sightings, vision_matches, evidence_files

Unique constraints are what make the whole flow idempotent:
  * incidents.dedupe_key                       - one incident per run+plates+junction
  * incident_alerts(incident_id, alert_id)     - a retried alert never links twice
  * incident_vehicles(incident_id, plate_norm, role)
  * rfid_reports(run_id, reader_id, seq)       - the transport may re-send a report
  * crash_zone_rfid(incident_id, epc)
  * vision_matches(sighting_id)                - one (upgradable) match per sighting
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = [
    "evidence_files", "vision_matches", "rfid_sightings",
    "crash_zone_rfid", "rfid_reports", "incident_vehicles",
    "incident_alerts", "vehicle_registry",
]


def upgrade() -> None:
    # ---------------------------------------------------------------- incidents
    op.add_column("incidents", sa.Column("run_id", sa.String(64), nullable=True))
    op.add_column("incidents", sa.Column("crash_ts_sim", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("crash_frame", sa.Integer(), nullable=True))
    op.add_column("incidents", sa.Column("crash_junction", sa.String(16), nullable=True))
    op.add_column("incidents", sa.Column("world_x", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("world_y", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("world_z", sa.Float(), nullable=True))
    op.add_column("incidents", sa.Column("dedupe_key", sa.String(255), nullable=True))
    op.create_index("ix_incidents_run_id", "incidents", ["run_id"])
    op.create_unique_constraint("uq_incidents_dedupe_key", "incidents", ["dedupe_key"])

    # -------------------------------------------------------- vehicle_registry
    op.create_table(
        "vehicle_registry",
        sa.Column("epc", sa.String(64), primary_key=True),
        sa.Column("plate_norm", sa.String(20), nullable=True),
        sa.Column("plate_display", sa.String(32), nullable=True),
        sa.Column("state_code", sa.String(8), nullable=True),
        sa.Column("sim_vehicle_id", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_vehicle_registry_plate_norm", "vehicle_registry", ["plate_norm"])

    # --------------------------------------------------------- incident_alerts
    op.create_table(
        "incident_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("timestamp_sim", sa.Float(), nullable=True),
        sa.Column("frame", sa.Integer(), nullable=True),
        sa.Column("raw", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("incident_id", "alert_id",
                            name="uq_incident_alerts_incident_alert"),
    )
    op.create_index("ix_incident_alerts_alert_id", "incident_alerts", ["alert_id"])

    # ------------------------------------------------------- incident_vehicles
    op.create_table(
        "incident_vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plate_norm", sa.String(20), nullable=False),
        sa.Column("plate_display", sa.String(32), nullable=True),
        sa.Column("epc", sa.String(64), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="involved"),
        sa.Column("sim_vehicle_id", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("incident_id", "plate_norm", "role",
                            name="uq_incident_vehicles_plate_role"),
    )
    op.create_index("ix_incident_vehicles_epc", "incident_vehicles", ["epc"])

    # ------------------------------------------------------------ rfid_reports
    op.create_table(
        "rfid_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", sa.String(64), nullable=True),
        sa.Column("reader_id", sa.String(64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("junction_id", sa.String(16), nullable=False),
        sa.Column("epc", sa.String(64), nullable=False),
        sa.Column("first_seen_ts", sa.Float(), nullable=False),
        sa.Column("last_seen_ts", sa.Float(), nullable=False),
        sa.Column("tag_seen_count", sa.Integer(), nullable=True),
        sa.Column("rssi_dbm", sa.Float(), nullable=True),
        sa.Column("schema", sa.String(32), nullable=True),
        sa.Column("sim_vehicle_id", sa.String(8), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "reader_id", "seq",
                            name="uq_rfid_reports_run_reader_seq"),
    )
    op.create_index("ix_rfid_reports_epc_time", "rfid_reports", ["epc", "last_seen_ts"])

    # --------------------------------------------------------- crash_zone_rfid
    op.create_table(
        "crash_zone_rfid",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("junction_id", sa.String(16), nullable=False),
        sa.Column("reader_id", sa.String(64), nullable=True),
        sa.Column("epc", sa.String(64), nullable=False),
        sa.Column("plate_norm", sa.String(20), nullable=True),
        sa.Column("first_seen_ts", sa.Float(), nullable=False),
        sa.Column("last_seen_ts", sa.Float(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tag_seen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peak_rssi_dbm", sa.Float(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="involved"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("incident_id", "epc", name="uq_crash_zone_rfid_incident_epc"),
    )
    op.create_index("ix_crash_zone_rfid_incident", "crash_zone_rfid", ["incident_id"])

    # ---------------------------------------------------------- rfid_sightings
    op.create_table(
        "rfid_sightings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("epc", sa.String(64), nullable=False),
        sa.Column("plate_norm", sa.String(20), nullable=True),
        sa.Column("junction_id", sa.String(16), nullable=False),
        sa.Column("reader_id", sa.String(64), nullable=True),
        sa.Column("first_seen_ts", sa.Float(), nullable=False),
        sa.Column("last_seen_ts", sa.Float(), nullable=False),
        sa.Column("report_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tag_seen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("peak_rssi_dbm", sa.Float(), nullable=True),
        sa.Column("closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_rfid_sightings_incident_epc", "rfid_sightings",
                    ["incident_id", "epc"])

    # ----------------------------------------------------------- vision_matches
    op.create_table(
        "vision_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sighting_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rfid_sightings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("rfid_plate", sa.String(20), nullable=True),
        sa.Column("anpr_plate", sa.String(20), nullable=True),
        sa.Column("anpr_confidence", sa.Float(), nullable=True),
        sa.Column("edit_distance", sa.Integer(), nullable=True),
        sa.Column("camera_id", sa.String(64), nullable=True),
        sa.Column("best_frame_ts", sa.Float(), nullable=True),
        sa.Column("time_delta_s", sa.Float(), nullable=True),
        sa.Column("frames_used", sa.Integer(), nullable=True),
        sa.Column("all_plates_seen", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("anpr_model", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("sighting_id", name="uq_vision_matches_sighting"),
    )
    op.create_index("ix_vision_matches_status", "vision_matches", ["status"])

    # ----------------------------------------------------------- evidence_files
    op.create_table(
        "evidence_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("vision_match_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("vision_matches.id", ondelete="CASCADE"), nullable=True),
        sa.Column("owner", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_evidence_files_incident", "evidence_files", ["incident_id"])
    op.create_index("ix_evidence_files_vision_match", "evidence_files", ["vision_match_id"])

    # Seed the registry from the EPC formula (test data only).
    op.execute(
        """
        INSERT INTO vehicle_registry (epc, plate_norm, plate_display, state_code, sim_vehicle_id)
        VALUES
          ('E200001722110101A0B1', 'KA01AT4521', 'KA 01 AT 4521', 'KA', 'A'),
          ('E200001722110102A0B2', 'MH12BR7814', 'MH 12 BR 7814', 'MH', 'B'),
          ('E200001722110103A0B3', 'TN09CK2365', 'TN 09 CK 2365', 'TN', 'C'),
          ('E200001722110104A0B4', 'KL07DL9182', 'KL 07 DL 9182', 'KL', 'D'),
          ('E200001722110105A0B5', 'DL03EN6047', 'DL 03 EN 6047', 'DL', 'E'),
          ('E200001722110106A0B6', 'GJ05FP3419', 'GJ 05 FP 3419', 'GJ', 'F'),
          ('E200001722110107A0B7', 'AP16GQ8273', 'AP 16 GQ 8273', 'AP', 'G'),
          ('E200001722110108A0B8', 'TG08HR5196', 'TG 08 HR 5196', 'TG', 'H')
        ON CONFLICT (epc) DO UPDATE SET
          plate_norm = EXCLUDED.plate_norm,
          plate_display = EXCLUDED.plate_display,
          state_code = EXCLUDED.state_code,
          sim_vehicle_id = EXCLUDED.sim_vehicle_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_files_vision_match", table_name="evidence_files")
    op.drop_index("ix_evidence_files_incident", table_name="evidence_files")
    op.drop_index("ix_vision_matches_status", table_name="vision_matches")
    op.drop_index("ix_rfid_sightings_incident_epc", table_name="rfid_sightings")
    op.drop_index("ix_crash_zone_rfid_incident", table_name="crash_zone_rfid")
    op.drop_index("ix_rfid_reports_epc_time", table_name="rfid_reports")
    op.drop_index("ix_incident_vehicles_epc", table_name="incident_vehicles")
    op.drop_index("ix_incident_alerts_alert_id", table_name="incident_alerts")
    op.drop_index("ix_vehicle_registry_plate_norm", table_name="vehicle_registry")

    for table in NEW_TABLES:
        op.drop_table(table)

    op.drop_constraint("uq_incidents_dedupe_key", "incidents", type_="unique")
    op.drop_index("ix_incidents_run_id", table_name="incidents")
    for column in ("dedupe_key", "world_z", "world_y", "world_x",
                   "crash_junction", "crash_frame", "crash_ts_sim", "run_id"):
        op.drop_column("incidents", column)
