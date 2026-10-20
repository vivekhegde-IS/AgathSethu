"""Rule-based fusion, versioned sightings, run source/archive, all-junction snapshots

Revision ID: 004
Revises: 003
Create Date: 2026-10-01

* incidents: source (live | replay | synthetic), archived, run_started_at.
  Existing rows are CLASSIFIED (an UPDATE of the new column only, nothing is
  deleted): the tools/simulate_carla_feed.py replays are recognisable by their
  synthetic crash (t=40.0 s, physics alert PHY-800); other feature incidents
  are live; rows not created by this feature (no dedupe_key) stay NULL.
* crash_zone_rfid: zone (crash | context); unique per (incident, junction, epc)
  so the same tag can appear in the crash zone AND a context snapshot.
* rfid_sightings: finalized, version.
* vision_matches: rule_assisted, match_reason, diff, other_vehicles,
  rejected_reads, per_frame, max_plate_px, cluster_frames, anpr_state_code,
  version, finalized.
* evidence_files: frame_ts, junction_id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("source", sa.String(16), nullable=True))
    op.add_column("incidents", sa.Column("archived", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))
    op.add_column("incidents", sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_incidents_source", "incidents", ["source"])

    op.add_column("crash_zone_rfid", sa.Column("zone", sa.String(16), nullable=False,
                                               server_default="crash"))
    op.drop_constraint("uq_crash_zone_rfid_incident_epc", "crash_zone_rfid", type_="unique")
    op.create_unique_constraint("uq_crash_zone_rfid_incident_junction_epc", "crash_zone_rfid",
                                ["incident_id", "junction_id", "epc"])

    op.add_column("rfid_sightings", sa.Column("finalized", sa.Boolean(), nullable=False,
                                              server_default=sa.false()))
    op.add_column("rfid_sightings", sa.Column("version", sa.Integer(), nullable=False,
                                              server_default="0"))

    for name, column in (
        ("rule_assisted", sa.Column("rule_assisted", sa.Boolean(), nullable=False,
                                    server_default=sa.false())),
        ("match_reason", sa.Column("match_reason", sa.String(255), nullable=True)),
        ("diff", sa.Column("diff", sa.JSON(), nullable=True)),
        ("other_vehicles", sa.Column("other_vehicles", sa.JSON(), nullable=True)),
        ("rejected_reads", sa.Column("rejected_reads", sa.JSON(), nullable=True)),
        ("per_frame", sa.Column("per_frame", sa.JSON(), nullable=True)),
        ("max_plate_px", sa.Column("max_plate_px", sa.Float(), nullable=True)),
        ("cluster_frames", sa.Column("cluster_frames", sa.Integer(), nullable=True)),
        ("anpr_state_code", sa.Column("anpr_state_code", sa.String(4), nullable=True)),
        ("version", sa.Column("version", sa.Integer(), nullable=False, server_default="0")),
        ("finalized", sa.Column("finalized", sa.Boolean(), nullable=False,
                                server_default=sa.false())),
    ):
        op.add_column("vision_matches", column)

    op.add_column("evidence_files", sa.Column("frame_ts", sa.Float(), nullable=True))
    op.add_column("evidence_files", sa.Column("junction_id", sa.String(16), nullable=True))

    # ---- classify existing incidents (UPDATE of the new column only)
    op.execute("""
        UPDATE incidents SET source = 'synthetic'
        WHERE dedupe_key IS NOT NULL AND crash_ts_sim = 40.0
          AND EXISTS (SELECT 1 FROM incident_alerts a
                      WHERE a.incident_id = incidents.id AND a.alert_id = 'PHY-800')
    """)
    op.execute("UPDATE incidents SET source = 'live' WHERE dedupe_key IS NOT NULL AND source IS NULL")
    op.execute("UPDATE incidents SET run_started_at = created_at "
               "WHERE dedupe_key IS NOT NULL AND run_started_at IS NULL")


def downgrade() -> None:
    op.drop_column("evidence_files", "junction_id")
    op.drop_column("evidence_files", "frame_ts")
    for name in ("finalized", "version", "anpr_state_code", "cluster_frames", "max_plate_px",
                 "per_frame", "rejected_reads", "other_vehicles", "diff", "match_reason",
                 "rule_assisted"):
        op.drop_column("vision_matches", name)
    op.drop_column("rfid_sightings", "version")
    op.drop_column("rfid_sightings", "finalized")
    op.drop_constraint("uq_crash_zone_rfid_incident_junction_epc", "crash_zone_rfid", type_="unique")
    op.create_unique_constraint("uq_crash_zone_rfid_incident_epc", "crash_zone_rfid",
                                ["incident_id", "epc"])
    op.drop_column("crash_zone_rfid", "zone")
    op.drop_index("ix_incidents_source", table_name="incidents")
    op.drop_column("incidents", "run_started_at")
    op.drop_column("incidents", "archived")
    op.drop_column("incidents", "source")
