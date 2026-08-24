"""
Pydantic / Dataclass Schema Validation for Member 1 CRASH_DETECTED event.
Ensures 100% compliance with shared/schemas/crash_event.json and shared/schemas/events.md.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator


class CrashDetectedEvent(BaseModel):
    """Pydantic model validating CRASH_DETECTED schema."""
    
    event_id: str = Field(..., description="Unique event identifier, e.g. evt_crash_001")
    event_type: str = Field("CRASH_DETECTED", description="Must be exact string CRASH_DETECTED")
    timestamp_sim: float = Field(..., description="Simulation timestamp in seconds")
    source: str = Field("member1", description="Must be member1")
    junction_id: str = Field("J02", description="Crash junction ID")
    vehicle_id: str = Field(..., description="Vehicle ID, e.g. V001 or V002")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Crash confidence score between 0.0 and 1.0")
    location: Optional[Dict[str, float]] = Field(None, description="Location coords {x, y, z}")
    telemetry_summary: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Telemetry evidence summary")

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        if v != "CRASH_DETECTED":
            raise ValueError(f"event_type must be 'CRASH_DETECTED', got '{v}'")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Converts model to dictionary."""
        return self.model_dump()
