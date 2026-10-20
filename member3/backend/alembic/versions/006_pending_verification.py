"""Partial-plate violations awaiting RFID fusion / authority review

Revision ID: 006
Revises: 005
Create Date: 2026-10-07

New table only. A violation whose plate is only partially read is stored here
(strict partial pattern, regex, real captured frame, matching registered
plates) instead of fining anyone automatically.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pending_verification",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("track_id", sa.String(64), nullable=True),
        sa.Column("violation_type", sa.String(100), nullable=False),
        sa.Column("partial_pattern", sa.String(64), nullable=False),
        sa.Column("alternative_patterns", sa.JSON(), nullable=True),
        sa.Column("pattern_regex", sa.Text(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("pipeline_plate_status", sa.String(32), nullable=True),
        sa.Column("partial_json", sa.JSON(), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("snapshot_image_path", sa.String(1024), nullable=True),
        sa.Column("evidence_time_s", sa.Float(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("resolved_plate", sa.String(20), nullable=True),
        sa.Column("resolved_by", sa.String(64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_pending_verification_job_id", "pending_verification", ["job_id"])
    op.create_index("ix_pending_verification_status", "pending_verification", ["status"])


def downgrade() -> None:
    op.drop_table("pending_verification")
