"""Citizen fines from routine-violation videos: videos, fines, unmatched_violations

Revision ID: 005
Revises: 004
Create Date: 2026-10-07

New tables only; nothing existing is altered.
* videos: every processed / registered video.
* fines: one row per (plate, violation type) per processing run, linked to the
  EXISTING citizen account (users.id) and vehicle (vehicles.id) that owns the
  plate. Re-running a video issues NEW fines by design.
* unmatched_violations: violations whose plate was unreadable or not registered
  in the vehicles table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_videos_filename", "videos", ["filename"])

    op.create_table(
        "fines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", UUID(as_uuid=True), sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("number_plate", sa.String(20), nullable=False),
        sa.Column("violation_type", sa.String(100), nullable=False),
        sa.Column("fine_amount", sa.Float(), nullable=False),
        sa.Column("snapshot_image_path", sa.String(1024), nullable=True),
        sa.Column("clip_path", sa.String(1024), nullable=True),
        sa.Column("plate_status", sa.String(32), nullable=True),
        sa.Column("evidence_time_s", sa.Float(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="Unpaid"),
    )
    op.create_index("ix_fines_user_id_detected_at", "fines", ["user_id", "detected_at"])
    op.create_index("ix_fines_job_id", "fines", ["job_id"])

    op.create_table(
        "unmatched_violations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("number_plate", sa.String(20), nullable=True),
        sa.Column("plate_raw", sa.String(64), nullable=True),
        sa.Column("plate_status", sa.String(32), nullable=True),
        sa.Column("violation_type", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("snapshot_image_path", sa.String(1024), nullable=True),
        sa.Column("evidence_time_s", sa.Float(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_unmatched_violations_job_id", "unmatched_violations", ["job_id"])


def downgrade() -> None:
    op.drop_table("unmatched_violations")
    op.drop_table("fines")
    op.drop_table("videos")
