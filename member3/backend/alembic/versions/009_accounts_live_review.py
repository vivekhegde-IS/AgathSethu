"""Demo accounts, Google sign-in, live crash notifications, review queue, SMS

Revision ID: 009
Revises: 008
Create Date: 2026-11-20

- users: username (demo login), google_sub (UNIQUE) / google_email / google_linked_at
- vehicles: carla_letter (A-H, UNIQUE), carla_role_name, rfid_epc (UNIQUE), state_name
- fines: location, issued_by, dispute_reason, disputed_at (status gains 'Disputed')
- crash_reports: one row per vehicle per crash incident (notification dedup)
- review_items: partner naming / hit-and-run awaiting the authority
- sms_messages: every text message produced (console or real provider)
- oauth_states: single-use Google sign-in state and tab hand-off codes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("google_sub", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("google_email", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("google_linked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_users_username", "users", ["username"])
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])

    op.add_column("vehicles", sa.Column("carla_letter", sa.String(1), nullable=True))
    op.add_column("vehicles", sa.Column("carla_role_name", sa.String(64), nullable=True))
    op.add_column("vehicles", sa.Column("rfid_epc", sa.String(64), nullable=True))
    op.add_column("vehicles", sa.Column("state_name", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_vehicles_carla_letter", "vehicles", ["carla_letter"])
    op.create_unique_constraint("uq_vehicles_rfid_epc", "vehicles", ["rfid_epc"])

    op.add_column("fines", sa.Column("location", sa.String(255), nullable=True))
    op.add_column("fines", sa.Column("issued_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"),
                                     nullable=True))
    op.add_column("fines", sa.Column("dispute_reason", sa.Text(), nullable=True))
    op.add_column("fines", sa.Column("disputed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "crash_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_key", sa.String(32), nullable=False),
        sa.Column("vehicle_id", UUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="own"),
        sa.Column("partner_vehicle_id", UUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_route", sa.String(32), nullable=True),
        sa.Column("timestamp_sim", sa.String(32), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("incident_key", "vehicle_id", name="uq_crash_reports_incident_vehicle"),
    )
    op.create_index("ix_crash_reports_incident_key", "crash_reports", ["incident_key"])
    op.create_index("ix_crash_reports_vehicle_created", "crash_reports", ["vehicle_id", "created_at"])

    op.create_table(
        "review_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_key", sa.String(32), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("accused_vehicle_id", UUID, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("struck_vehicle_id", UUID, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decision_route", sa.String(32), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("incident_key", "kind", "accused_vehicle_id", name="uq_review_items_incident_kind"),
    )
    op.create_index("ix_review_items_incident_key", "review_items", ["incident_key"])

    op.create_table(
        "sms_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notification_id", UUID, sa.ForeignKey("notifications.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_number", sa.String(20), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider_ref", sa.String(64), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sms_messages_user_created", "sms_messages", ["user_id", "created_at"])

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_verifier", sa.String(128), nullable=True),
        sa.Column("nonce", sa.String(64), nullable=True),
        sa.Column("tab_hash", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")
    op.drop_index("ix_sms_messages_user_created", table_name="sms_messages")
    op.drop_table("sms_messages")
    op.drop_index("ix_review_items_incident_key", table_name="review_items")
    op.drop_table("review_items")
    op.drop_index("ix_crash_reports_vehicle_created", table_name="crash_reports")
    op.drop_index("ix_crash_reports_incident_key", table_name="crash_reports")
    op.drop_table("crash_reports")
    for column in ("disputed_at", "dispute_reason", "issued_by", "location"):
        op.drop_column("fines", column)
    op.drop_constraint("uq_vehicles_rfid_epc", "vehicles", type_="unique")
    op.drop_constraint("uq_vehicles_carla_letter", "vehicles", type_="unique")
    for column in ("state_name", "rfid_epc", "carla_role_name", "carla_letter"):
        op.drop_column("vehicles", column)
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_constraint("uq_users_username", "users", type_="unique")
    for column in ("google_linked_at", "google_email", "google_sub", "username"):
        op.drop_column("users", column)
