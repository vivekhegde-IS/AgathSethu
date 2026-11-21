"""Resolution codes: a crash is resolved only with the owners' codes or a
super-admin code

Revision ID: 012
Revises: 011
Create Date: 2026-11-21

- resolution_codes: officer requests / super-admin issued codes (hash only).
- resolution_attempts: wrong-code lock-out and how each crash was closed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _user_fk(name: str) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"),
                     nullable=True)


def upgrade() -> None:
    op.create_table(
        "resolution_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_ref", sa.String(64), nullable=False, index=True),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="CASCADE"),
                  nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="requested"),
        sa.Column("reason", sa.Text(), nullable=True),
        _user_fk("requested_by"),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=True),
        _user_fk("issued_by"),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _user_fk("used_by"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "resolution_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_ref", sa.String(64), nullable=False),
        _user_fk("user_id"),
        sa.Column("ok", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("method", sa.String(12), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_resolution_attempts_ref_at", "resolution_attempts", ["incident_ref", "at"])


def downgrade() -> None:
    op.drop_index("ix_resolution_attempts_ref_at", table_name="resolution_attempts")
    op.drop_table("resolution_attempts")
    op.drop_table("resolution_codes")
