"""
Member 3 Database Repository (Data Access Object Layer).
Handles CRUD queries for Events, Incidents, Evidence, and Vehicle History.
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import desc
from member3.database.models import EventModel, IncidentModel, EvidenceModel, VehicleHistoryModel


class EventRepository:
    """DAO for raw event store."""

    @staticmethod
    def save_event(db: Session, event_data: Dict[str, Any]) -> EventModel:
        existing = db.query(EventModel).filter(EventModel.event_id == event_data["event_id"]).first()
        if existing:
            existing.payload_json = event_data
            if event_data.get("vehicle_id"):
                existing.vehicle_id = event_data["vehicle_id"]
            if event_data.get("plate_number"):
                existing.plate_number = event_data["plate_number"]
            db.commit()
            db.refresh(existing)
            return existing

        event_obj = EventModel(
            event_id=event_data["event_id"],
            event_type=event_data["event_type"],
            timestamp_sim=float(event_data.get("timestamp_sim", 0.0)),
            source=event_data.get("source", "unknown"),
            junction_id=event_data.get("junction_id"),
            vehicle_id=event_data.get("vehicle_id"),
            plate_number=event_data.get("plate_number"),
            payload_json=event_data
        )
        db.add(event_obj)
        db.commit()
        db.refresh(event_obj)
        return event_obj

    @staticmethod
    def get_all_events(db: Session, limit: int = 100) -> List[EventModel]:
        return db.query(EventModel).order_by(EventModel.timestamp_sim.asc()).limit(limit).all()

    @staticmethod
    def get_events_by_type(db: Session, event_type: str) -> List[EventModel]:
        return db.query(EventModel).filter(EventModel.event_type == event_type).order_by(EventModel.timestamp_sim.asc()).all()


class VehicleHistoryRepository:
    """DAO for vehicle movement history."""

    @staticmethod
    def record_observation(
        db: Session,
        vehicle_id: str,
        plate_number: str,
        junction_id: str,
        timestamp_sim: float,
        source_type: str,
        event_id: str,
        details: Dict[str, Any] = None
    ) -> VehicleHistoryModel:
        # Check duplicate observation for same event
        existing = db.query(VehicleHistoryModel).filter(VehicleHistoryModel.event_id == event_id).first()
        if existing:
            return existing

        vh = VehicleHistoryModel(
            vehicle_id=vehicle_id,
            plate_number=plate_number,
            junction_id=junction_id,
            timestamp_sim=timestamp_sim,
            source_type=source_type,
            event_id=event_id,
            details_json=details or {}
        )
        db.add(vh)
        db.commit()
        db.refresh(vh)
        return vh

    @staticmethod
    def get_vehicle_history(db: Session, vehicle_id: str) -> List[VehicleHistoryModel]:
        return db.query(VehicleHistoryModel).filter(
            VehicleHistoryModel.vehicle_id == vehicle_id
        ).order_by(VehicleHistoryModel.timestamp_sim.asc()).all()

    @staticmethod
    def get_last_known_location(db: Session, vehicle_id: str) -> Optional[VehicleHistoryModel]:
        return db.query(VehicleHistoryModel).filter(
            VehicleHistoryModel.vehicle_id == vehicle_id
        ).order_by(VehicleHistoryModel.timestamp_sim.desc()).first()


class IncidentRepository:
    """DAO for incident management and evidence items."""

    @staticmethod
    def save_or_update_incident(
        db: Session,
        incident_id: str,
        crash_junction: str,
        crash_timestamp: float,
        involved_vehicles: List[str],
        suspect_vehicle_id: Optional[str] = None,
        suspect_plate: Optional[str] = None,
        last_known_location: Optional[str] = None,
        route_history: List[str] = None,
        confidence_score: float = 0.95,
        summary_notes: str = ""
    ) -> IncidentModel:
        incident = db.query(IncidentModel).filter(IncidentModel.incident_id == incident_id).first()
        if not incident:
            incident = IncidentModel(
                incident_id=incident_id,
                status="ACTIVE",
                incident_type="HIT_AND_RUN",
                crash_junction=crash_junction,
                crash_timestamp=crash_timestamp,
                involved_vehicles_json=involved_vehicles,
                suspect_vehicle_id=suspect_vehicle_id,
                suspect_plate=suspect_plate,
                last_known_location=last_known_location or crash_junction,
                route_history_json=route_history or [crash_junction],
                confidence_score=confidence_score,
                summary_notes=summary_notes
            )
            db.add(incident)
        else:
            if suspect_vehicle_id:
                incident.suspect_vehicle_id = suspect_vehicle_id
            if suspect_plate:
                incident.suspect_plate = suspect_plate
            if last_known_location:
                incident.last_known_location = last_known_location
            if route_history:
                incident.route_history_json = route_history
            if confidence_score:
                incident.confidence_score = confidence_score
            if summary_notes:
                incident.summary_notes = summary_notes

        db.commit()
        db.refresh(incident)
        return incident

    @staticmethod
    def add_evidence_item(
        db: Session,
        incident_id: str,
        event_id: str,
        event_type: str,
        source: str,
        confidence: float,
        description: str,
        details: Dict[str, Any] = None
    ) -> EvidenceModel:
        existing = db.query(EvidenceModel).filter(
            EvidenceModel.incident_id == incident_id,
            EvidenceModel.event_id == event_id
        ).first()
        if existing:
            return existing

        item = EvidenceModel(
            incident_id=incident_id,
            event_id=event_id,
            event_type=event_type,
            source=source,
            confidence=confidence,
            description=description,
            details_json=details or {}
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    @staticmethod
    def get_incident(db: Session, incident_id: str) -> Optional[IncidentModel]:
        return db.query(IncidentModel).filter(IncidentModel.incident_id == incident_id).first()

    @staticmethod
    def get_all_incidents(db: Session) -> List[IncidentModel]:
        return db.query(IncidentModel).order_by(IncidentModel.updated_at.desc()).all()
