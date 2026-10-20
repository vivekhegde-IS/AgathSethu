"""Mark each archived RFID report with its registry resolution

Revision ID: 003
Revises: 002
Create Date: 2026-09-30

A real reader only knows the EPC, so the plate on an archived report comes from
``vehicle_registry``. An EPC that is not registered is stored with a NULL plate
and ``registry_status = 'UNREGISTERED_TAG'`` - a plate is never invented.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("rfid_reports", sa.Column("plate_norm", sa.String(20), nullable=True))
    op.add_column("rfid_reports", sa.Column("registry_status", sa.String(24), nullable=True))
    op.create_index("ix_rfid_reports_registry_status", "rfid_reports", ["registry_status"])


def downgrade() -> None:
    op.drop_index("ix_rfid_reports_registry_status", table_name="rfid_reports")
    op.drop_column("rfid_reports", "registry_status")
    op.drop_column("rfid_reports", "plate_norm")
