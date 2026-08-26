"""
Member 3 Database ORM Models.
Defines tables for Events, Incidents, Evidence Items, and Vehicle History.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from member3.database.db import Base


class EventModel(Base):
    """Raw Ingested Event Store."""

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_id = Column(String(64), unique=True, index=True, nullable=False)
    event_type = Column(String(64), index=True, nullable=False)
    timestamp_sim = Column(Float, nullable=False, index=True)
    source = Column(String(32), nullable=False)
    junction_id = Column(String(32), index=True)
    vehicle_id = Column(String(32), index=True)
    plate_number = Column(String(32), index=True)
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class IncidentModel(Base):
    """Incident Management Model."""

    __tablename__ = "incidents"

    incident_id = Column(String(64), primary_key=True, index=True)
    status = Column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, RESOLVED
    incident_type = Column(String(64), default="HIT_AND_RUN", nullable=False)
    crash_junction = Column(String(32), nullable=False)
    crash_timestamp = Column(Float, nullable=False)
    involved_vehicles_json = Column(JSON, nullable=False)  # ["V001", "V002"]
    suspect_vehicle_id = Column(String(32), index=True)
    suspect_plate = Column(String(32), index=True)
    last_known_location = Column(String(32), index=True)
    route_history_json = Column(JSON, nullable=False)  # ["J02", "J03", "J04"]
    confidence_score = Column(Float, default=0.95)
    summary_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    evidence_items = relationship("EvidenceModel", back_populates="incident", cascade="all, delete-orphan")


class EvidenceModel(Base):
    """Evidence Items Attached to Incidents."""

    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    incident_id = Column(String(64), ForeignKey("incidents.incident_id"), nullable=False)
    event_id = Column(String(64), nullable=False)
    event_type = Column(String(64), nullable=False)
    source = Column(String(32), nullable=False)
    confidence = Column(Float, default=1.0)
    description = Column(String(256))
    details_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    incident = relationship("IncidentModel", back_populates="evidence_items")


class VehicleHistoryModel(Base):
    """Sequenced Vehicle Location Observations across Junctions."""

    __tablename__ = "vehicle_history"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    vehicle_id = Column(String(32), index=True, nullable=False)
    plate_number = Column(String(32), index=True)
    junction_id = Column(String(32), index=True, nullable=False)
    timestamp_sim = Column(Float, nullable=False, index=True)
    source_type = Column(String(32), nullable=False)  # member1, member2_anpr, member2_vision, member3_rfid
    event_id = Column(String(64), nullable=False)
    details_json = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
