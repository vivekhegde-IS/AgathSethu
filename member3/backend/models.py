"""
Member 3 FastAPI Backend Pydantic Schemas.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class IngestEventRequest(BaseModel):
    event_id: str = Field(..., example="evt_crash_001")
    event_type: str = Field(..., example="CRASH_DETECTED")
    timestamp_sim: float = Field(..., example=102.43)
    source: str = Field(..., example="member1")
    junction_id: Optional[str] = Field("J02", example="J02")
    vehicle_id: Optional[str] = Field(None, example="V001")
    plate_number: Optional[str] = Field(None, example="KA05XY5678")
    confidence: Optional[float] = Field(0.95, example=0.95)
    telemetry_summary: Optional[Dict[str, Any]] = None
    vehicle_ids: Optional[List[str]] = None
    camera_id: Optional[str] = None
    reader_id: Optional[str] = None
    tag_id: Optional[str] = None


class RFIDTriggerRequest(BaseModel):
    reader_id: str = Field("RFID_J03_R01", example="RFID_J03_R01")
    junction_id: str = Field("J03", example="J03")
    vehicle_id: str = Field("V002", example="V002")
    tag_id: str = Field("TAG_V002_99B", example="TAG_V002_99B")
    plate_number: str = Field("KA05XY5678", example="KA05XY5678")
    timestamp_sim: float = Field(125.10, example=125.10)
    distance_m: float = Field(5.0, example=5.0)


class EventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp_sim: float
    source: str
    junction_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    plate_number: Optional[str] = None
    payload_json: Dict[str, Any]


class IncidentSummaryResponse(BaseModel):
    incident_id: str
    status: str
    incident_type: str
    crash_junction: str
    crash_timestamp: float
    involved_vehicles: List[str]
    suspect_vehicle_id: Optional[str] = None
    suspect_plate: Optional[str] = None
    last_known_location: str
    route_history: List[str]
    confidence_score: float
    summary_notes: Optional[str] = None


class IncidentDetailResponse(IncidentSummaryResponse):
    evidence_items: List[Dict[str, Any]]
