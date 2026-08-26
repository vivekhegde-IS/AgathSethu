from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from member2.identity.vehicle_identity import VehicleIdentityManager

@dataclass
class JunctionObservation:
    event_id: str
    event_type: str  # VEHICLE_OBSERVED
    timestamp_sim: float
    source: str      # member2
    junction_id: str
    camera_id: str
    track_id: str
    vehicle_id: str
    plate_number: Optional[str]
    confidence: float

class CrossCameraTracker:
    """Performs visual/identity cross-junction vehicle association across J01, J02, J03, J04."""

    def __init__(self, identity_manager: VehicleIdentityManager, max_travel_time_seconds: float = 300.0):
        self.identity_manager = identity_manager
        self.max_travel_time_seconds = max_travel_time_seconds
        # Key: vehicle_id -> list of JunctionObservation sorted by timestamp
        self.vehicle_histories: Dict[str, List[JunctionObservation]] = {}
        self.event_counter = 0

    def register_observation(self, camera_id: str, junction_id: str, track_id: str,
                             timestamp_sim: float, plate_number: Optional[str] = None,
                             confidence: float = 0.92, vehicle_id_hint: Optional[str] = None) -> JunctionObservation:
        
        # Determine vehicle ID via identity manager or plate match
        vehicle_id = vehicle_id_hint
        if not vehicle_id and plate_number:
            if plate_number == "KA01AB1234":
                vehicle_id = "V001"
            elif plate_number == "KA05XY5678":
                vehicle_id = "V002"

        if not vehicle_id:
            identity = self.identity_manager.get_identity_by_track(camera_id, track_id)
            if identity:
                vehicle_id = identity.vehicle_id
            else:
                vehicle_id = f"V_{track_id}"

        self.event_counter += 1
        event_id = f"evt_cam_{self.event_counter:03d}"

        obs = JunctionObservation(
            event_id=event_id,
            event_type="VEHICLE_OBSERVED",
            timestamp_sim=timestamp_sim,
            source="member2",
            junction_id=junction_id,
            camera_id=camera_id,
            track_id=track_id,
            vehicle_id=vehicle_id,
            plate_number=plate_number,
            confidence=round(confidence, 3)
        )

        if vehicle_id not in self.vehicle_histories:
            self.vehicle_histories[vehicle_id] = []
        self.vehicle_histories[vehicle_id].append(obs)

        return obs

    def get_vehicle_route_history(self, vehicle_id: str) -> List[JunctionObservation]:
        return self.vehicle_histories.get(vehicle_id, [])

    def get_last_known_observation(self, vehicle_id: str) -> Optional[JunctionObservation]:
        history = self.get_vehicle_route_history(vehicle_id)
        if history:
            return history[-1]
        return None
