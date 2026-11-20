"""Owners' answers to a crash alert ("are you safe?") from the app or website

Revision ID: 010
Revises: 009
Create Date: 2026-11-20

- crash_responses: one row per owner per crash (incident_ref = CR-... key or
  incidents.id). false_alarm / not_serious wait for the authority (review_status).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "crash_responses",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", UUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("incident_ref", sa.String(64), nullable=False),
        sa.Column("ref_kind", sa.String(12), nullable=False),
        sa.Column("response", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("channel", sa.String(8), nullable=False, server_default="app"),
        sa.Column("responded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("review_status", sa.String(12), nullable=True),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.UniqueConstraint("user_id", "incident_ref", name="uq_crash_responses_user_ref"),
    )
    op.create_index("ix_crash_responses_ref", "crash_responses", ["incident_ref"])
    op.create_index("ix_crash_responses_review", "crash_responses", ["review_status", "responded_at"])


def downgrade() -> None:
    op.drop_index("ix_crash_responses_review", table_name="crash_responses")
    op.drop_index("ix_crash_responses_ref", table_name="crash_responses")
    op.drop_table("crash_responses")
