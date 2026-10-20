"""Incident resolution, citizen notifications, fine payments

Revision ID: 007
Revises: 006
Create Date: 2026-10-18

- incidents: who resolved an incident and the officer's note (resolved_at and
  status 'resolved' already exist).
- notifications: one stored row per citizen alert (crash involvement, fine
  issued); never regenerated on page load.
- fine_payments: one row per paid fine with its receipt reference; the fine's
  own status stays the single source of Paid/Unpaid.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("resolved_by", postgresql.UUID(as_uuid=True),
                                         sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("incidents", sa.Column("resolution_note", sa.Text(), nullable=True))

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),            # crash_involvement | fine_issued
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("fine_id", sa.Integer(), sa.ForeignKey("fines.id", ondelete="CASCADE"), nullable=True),
        sa.Column("plate_norm", sa.String(20), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "kind", "incident_id", "plate_norm", name="uq_notifications_incident"),
        sa.UniqueConstraint("user_id", "kind", "fine_id", name="uq_notifications_fine"),
    )
    op.create_index("ix_notifications_user_id_created_at", "notifications", ["user_id", "created_at"])

    op.create_table(
        "fine_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("fine_id", sa.Integer(), sa.ForeignKey("fines.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("reference", sa.String(32), nullable=False, unique=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_fine_payments_user_id_paid_at", "fine_payments", ["user_id", "paid_at"])
    op.create_index("ix_fine_payments_paid_at", "fine_payments", ["paid_at"])


def downgrade() -> None:
    op.drop_table("fine_payments")
    op.drop_table("notifications")
    op.drop_column("incidents", "resolution_note")
    op.drop_column("incidents", "resolved_by")
