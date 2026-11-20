"""Automatic crash case outcome from the owners' answers

Revision ID: 011
Revises: 010
Create Date: 2026-11-20

- crash_case_outcomes: one row per crash (CR-... key or incidents.id):
  waiting | resolved | not_resolved, why, and the 30 s partner deadline.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "crash_case_outcomes",
        sa.Column("incident_ref", sa.String(64), primary_key=True),
        sa.Column("ref_kind", sa.String(12), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(24), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("first_answer_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_crash_case_outcomes_waiting", "crash_case_outcomes", ["outcome", "deadline_at"])


def downgrade() -> None:
    op.drop_index("ix_crash_case_outcomes_waiting", table_name="crash_case_outcomes")
    op.drop_table("crash_case_outcomes")
