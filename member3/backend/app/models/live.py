"""
AGHAT SETHU — Live crash notifications, authority review queue, SMS log and
Google sign-in state (migration 009); owners' crash answers (migration 010); crash case outcomes (011).
"""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base
import app.models.models  # noqa: F401,E402  (registers users / vehicles)


class CrashReport(Base):
    """One row per vehicle per crash incident: the dedup key for the owner's
    crash notification. ``incident_key`` groups the alerts of one crash (both
    cars of a pair, re-emits within the cooldown)."""

    __tablename__ = "crash_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_key = Column(String(32), nullable=False, index=True)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False)
    alert_id = Column(String(64), nullable=True)
    status = Column(String(64), nullable=True)                # crash_alert status (v1.8)
    source = Column(String(16), nullable=False, default="own")  # own (vehicle's own alert) | partner
    partner_vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"),
                                nullable=True)
    decision_route = Column(String(32), nullable=True)
    timestamp_sim = Column(String(32), nullable=True)
    location = Column(String(255), nullable=True)
    raw = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("incident_key", "vehicle_id", name="uq_crash_reports_incident_vehicle"),
        Index("ix_crash_reports_vehicle_created", "vehicle_id", "created_at"),
    )


class ReviewItem(Base):
    """A partner naming or hit-and-run that waits for the authority. Nothing in
    here reaches the accused owner, or becomes a fine, until it is confirmed."""

    __tablename__ = "review_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    incident_key = Column(String(32), nullable=False, index=True)
    kind = Column(String(16), nullable=False)                 # partner | hit_and_run
    accused_vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"),
                                nullable=False)
    struck_vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"),
                               nullable=True)
    decision_route = Column(String(32), nullable=True)        # mutual_shock | contact_test | carla_physics | not_reported
    evidence = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decision_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("incident_key", "kind", "accused_vehicle_id", name="uq_review_items_incident_kind"),
    )


class SmsMessage(Base):
    """Every text message the system produced, whether or not a real SMS went out."""

    __tablename__ = "sms_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    notification_id = Column(UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"),
                             nullable=True)
    to_number = Column(String(20), nullable=True)
    body = Column(Text, nullable=False)
    provider = Column(String(16), nullable=False)             # console | twilio
    status = Column(String(24), nullable=False)               # stored | sent | skipped_placeholder | failed
    provider_ref = Column(String(64), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (Index("ix_sms_messages_user_created", "user_id", "created_at"),)


class OAuthState(Base):
    """Single-use Google sign-in state. ``purpose``:
    login / link  - between /google/start and the Google callback (state, PKCE, nonce)
    handoff       - between the callback and the tab that started it (one-time code)"""

    __tablename__ = "oauth_states"

    id = Column(String(64), primary_key=True)                 # sha256 of the state / handoff code
    purpose = Column(String(16), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    code_verifier = Column(String(128), nullable=True)
    nonce = Column(String(64), nullable=True)
    tab_hash = Column(String(64), nullable=False)             # sha256 of the starting tab's nonce
    outcome = Column(String(32), nullable=True)               # handoff only: ok | linked | not_linked | ...
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CrashResponse(Base):
    """A vehicle owner's answer to "are you safe?" after a crash alert, from the
    mobile app or the website (migration 010). One row per owner per crash; the
    latest answer wins. ``incident_ref`` is either a crash_reports incident key
    (CR-...) or an incidents.id UUID, so both crash pipelines are covered.

    A "false_alarm" / "not_serious" answer never changes the crash record on its
    own: it waits (review_status = pending) until the authority accepts it."""

    __tablename__ = "crash_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    vehicle_id = Column(UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True)
    incident_ref = Column(String(64), nullable=False)
    ref_kind = Column(String(12), nullable=False)             # crash (CR-...) | incident (UUID)
    response = Column(String(16), nullable=False)             # accident | not_serious | false_alarm
    note = Column(Text, nullable=True)
    channel = Column(String(8), nullable=False, default="app")  # app | web
    responded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    review_status = Column(String(12), nullable=True)         # pending | accepted | rejected (None = accident)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_note = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "incident_ref", name="uq_crash_responses_user_ref"),
        Index("ix_crash_responses_ref", "incident_ref"),
        Index("ix_crash_responses_review", "review_status", "responded_at"),
    )


class CrashCaseOutcome(Base):
    """Automatic outcome of one crash from its owners' answers (migration 011).

    resolved      every involved vehicle's owner answered minor / false alarm
    not_resolved  an owner reported an accident, or the other owner did not
                  answer within CRASH_PARTNER_ANSWER_WINDOW_S
    waiting       some owners answered minor, others still have time
    The authority's accept / reject also lands here (decided_by set)."""

    __tablename__ = "crash_case_outcomes"

    incident_ref = Column(String(64), primary_key=True)      # CR-... key or incidents.id
    ref_kind = Column(String(12), nullable=False)            # crash | incident
    outcome = Column(String(16), nullable=False)             # waiting | resolved | not_resolved
    reason_code = Column(String(24), nullable=True)          # all_minor | accident | no_answer | authority
    reason = Column(Text, nullable=True)
    first_answer_at = Column(DateTime(timezone=True), nullable=True)
    deadline_at = Column(DateTime(timezone=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    decided_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (Index("ix_crash_case_outcomes_waiting", "outcome", "deadline_at"),)


def new_incident_key() -> str:
    return "CR-" + uuid.uuid4().hex[:10].upper()
