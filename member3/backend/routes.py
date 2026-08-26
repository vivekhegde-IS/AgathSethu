"""
Member 3 FastAPI Router & REST Endpoints.
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from member3.database.db import get_db_session
from member3.database.repository import EventRepository, IncidentRepository, VehicleHistoryRepository
from member3.backend.models import (
    IngestEventRequest,
    RFIDTriggerRequest,
    EventResponse,
    IncidentSummaryResponse,
    IncidentDetailResponse
)
from member3.integration.event_ingestion import EventIngestionPipeline
from member3.rfid.simulator import RFIDReaderSimulator
from member3.fusion_engine import EvidenceFusionEngine

router = APIRouter()
rfid_simulator = RFIDReaderSimulator(reader_id="RFID_J03_R01", junction_id="J03")


@router.get("/health")
def health_check():
    return {
        "status": "UP",
        "service": "Member 3 Backend API & Fusion Engine",
        "system": "Hit-and-Run Detection System"
    }


@router.post("/api/events", status_code=201)
def ingest_event(payload: IngestEventRequest, db: Session = Depends(get_db_session)):
    """API endpoint to ingest an incoming event from Member 1, Member 2, or RFID."""
    pipeline = EventIngestionPipeline(db=db)
    raw_dict = payload.dict(exclude_unset=True)
    norm = pipeline.ingest_raw_event(raw_dict)
    if not norm:
        raise HTTPException(status_code=400, detail="Event validation or normalization failed.")

    # Automatically trigger fusion engine to update incident state
    fusion = EvidenceFusionEngine(db=db)
    fusion.run_fusion_pipeline()

    return {"status": "INGESTED", "event_id": norm["event_id"], "normalized": norm}


@router.get("/api/events", response_model=List[EventResponse])
def get_all_events(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db_session)):
    """Retrieves all ingested events sorted by timestamp."""
    events = EventRepository.get_all_events(db, limit=limit)
    res = []
    for evt in events:
        res.append(EventResponse(
            event_id=evt.event_id,
            event_type=evt.event_type,
            timestamp_sim=evt.timestamp_sim,
            source=evt.source,
            junction_id=evt.junction_id,
            vehicle_id=evt.vehicle_id,
            plate_number=evt.plate_number,
            payload_json=evt.payload_json or {}
        ))
    return res


@router.get("/api/incidents", response_model=List[IncidentSummaryResponse])
def get_all_incidents(db: Session = Depends(get_db_session)):
    """Returns list of active incidents."""
    incidents = IncidentRepository.get_all_incidents(db)
    res = []
    for inc in incidents:
        res.append(IncidentSummaryResponse(
            incident_id=inc.incident_id,
            status=inc.status,
            incident_type=inc.incident_type,
            crash_junction=inc.crash_junction,
            crash_timestamp=inc.crash_timestamp,
            involved_vehicles=inc.involved_vehicles_json or [],
            suspect_vehicle_id=inc.suspect_vehicle_id,
            suspect_plate=inc.suspect_plate,
            last_known_location=inc.last_known_location or inc.crash_junction,
            route_history=inc.route_history_json or [],
            confidence_score=inc.confidence_score,
            summary_notes=inc.summary_notes
        ))
    return res


@router.get("/api/incidents/{incident_id}", response_model=IncidentDetailResponse)
def get_incident_detail(incident_id: str, db: Session = Depends(get_db_session)):
    """Returns comprehensive incident details including evidence items."""
    inc = IncidentRepository.get_incident(db, incident_id)
    if not inc:
        # Try running fusion first to see if incident can be created from events
        fusion = EvidenceFusionEngine(db=db)
        fusion.run_fusion_pipeline(incident_id)
        inc = IncidentRepository.get_incident(db, incident_id)

    if not inc:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found.")

    evidence_list = []
    for item in inc.evidence_items:
        evidence_list.append({
            "id": item.id,
            "event_id": item.event_id,
            "event_type": item.event_type,
            "source": item.source,
            "confidence": item.confidence,
            "description": item.description,
            "details": item.details_json
        })

    return IncidentDetailResponse(
        incident_id=inc.incident_id,
        status=inc.status,
        incident_type=inc.incident_type,
        crash_junction=inc.crash_junction,
        crash_timestamp=inc.crash_timestamp,
        involved_vehicles=inc.involved_vehicles_json or [],
        suspect_vehicle_id=inc.suspect_vehicle_id,
        suspect_plate=inc.suspect_plate,
        last_known_location=inc.last_known_location or inc.crash_junction,
        route_history=inc.route_history_json or [],
        confidence_score=inc.confidence_score,
        summary_notes=inc.summary_notes,
        evidence_items=evidence_list
    )


@router.post("/api/rfid/trigger")
def trigger_rfid_scan(req: RFIDTriggerRequest, db: Session = Depends(get_db_session)):
    """Triggers virtual RFID tag read and ingests generated RFID_DETECTED event."""
    evt = rfid_simulator.detect_tag(
        vehicle_id=req.vehicle_id,
        tag_id=req.tag_id,
        plate_number=req.plate_number,
        timestamp_sim=req.timestamp_sim,
        distance_m=req.distance_m
    )
    if not evt:
        return {"status": "SKIPPED", "message": "Tag out of range or cooldown active."}

    pipeline = EventIngestionPipeline(db=db)
    norm = pipeline.ingest_raw_event(evt)

    # Re-run fusion
    fusion = EvidenceFusionEngine(db=db)
    fusion.run_fusion_pipeline()

    return {"status": "INGESTED", "event": norm}


@router.post("/api/demo/run")
def run_end_to_end_fusion_demo(db: Session = Depends(get_db_session)):
    """Runs complete ingestion from Member 1 & Member 2 outputs, triggers RFID at J03, and runs fusion engine."""
    pipeline = EventIngestionPipeline(db=db)
    ingested = pipeline.ingest_from_upstream_files()

    # Trigger RFID for V002 at J03
    rfid_evt = rfid_simulator.detect_tag("V002", "TAG_V002_99B", "KA05XY5678", 125.10, distance_m=5.0)
    if rfid_evt:
        pipeline.ingest_raw_event(rfid_evt)

    fusion = EvidenceFusionEngine(db=db)
    report = fusion.run_fusion_pipeline("INC-000001")

    return {
        "status": "DEMO_COMPLETED",
        "events_ingested_count": len(ingested),
        "incident_report": report
    }
