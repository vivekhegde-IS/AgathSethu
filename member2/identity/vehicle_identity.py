from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class VehicleIdentityMapping:
    """Explicitly separates local camera track IDs from project vehicle identity (e.g. TRACK_17 -> V001)."""
    camera_id: str
    junction_id: str
    track_id: str
    vehicle_id: str
    plate_number: Optional[str] = None
    confidence: float = 0.90

class VehicleIdentityManager:
    """Manages identity associations and prevents local track ID ground-truth leakage."""

    def __init__(self):
        # Key: (camera_id, track_id) -> VehicleIdentityMapping
        self.mappings: Dict[tuple, VehicleIdentityMapping] = {}

    def associate_identity(self, camera_id: str, junction_id: str, track_id: str,
                           vehicle_id: str, plate_number: Optional[str] = None,
                           confidence: float = 0.90) -> VehicleIdentityMapping:
        key = (camera_id, track_id)
        mapping = VehicleIdentityMapping(
            camera_id=camera_id,
            junction_id=junction_id,
            track_id=track_id,
            vehicle_id=vehicle_id,
            plate_number=plate_number,
            confidence=confidence
        )
        self.mappings[key] = mapping
        return mapping

    def get_identity_by_track(self, camera_id: str, track_id: str) -> Optional[VehicleIdentityMapping]:
        return self.mappings.get((camera_id, track_id))

    def get_vehicle_id_for_track(self, camera_id: str, track_id: str, fallback_prefix: str = "V") -> str:
        mapping = self.get_identity_by_track(camera_id, track_id)
        if mapping:
            return mapping.vehicle_id
        # Standard track-derived temporary ID if identity not yet confirmed
        return f"{fallback_prefix}_{track_id}"
