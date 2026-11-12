"""Welcome email on a user's first login

Revision ID: 008
Revises: 007
Create Date: 2026-11-12

- users.welcome_email_sent_at: set once the welcome email went out, so it is
  sent exactly once. Accounts that already exist are marked as welcomed: only
  users created from now on get the email.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("welcome_email_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET welcome_email_sent_at = COALESCE(created_at, now())")


def downgrade() -> None:
    op.drop_column("users", "welcome_email_sent_at")
