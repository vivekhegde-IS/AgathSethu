import os
import json
from dataclasses import asdict
from typing import Dict, Any, Optional

REQUIRED_EVENT_FIELDS = {"event_id", "event_type", "timestamp_sim", "source"}

class EventPublisher:
    """Publishes standardized Member 2 JSONL events to member2/outputs/events.jsonl."""

    def __init__(self, output_path: Optional[str] = None):
        if output_path is None:
            output_path = os.path.join(os.path.dirname(__file__), "..", "outputs", "events.jsonl")
        self.output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def publish_event(self, event_data: Dict[str, Any]) -> bool:
        """Validates standard fields and appends JSON event to member2/outputs/events.jsonl."""
        # Ensure mandatory header fields exist
        missing = REQUIRED_EVENT_FIELDS - set(event_data.keys())
        if missing:
            print(f"[Member 2 Publisher Error] Event missing required fields: {missing}")
            return False

        # Ensure source is member2
        event_data["source"] = "member2"

        try:
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event_data) + "\n")
            return True
        except Exception as e:
            print(f"[Member 2 Publisher Error] Failed to write event: {e}")
            return False

    def publish_collision_pair(self, event_id: str, timestamp_sim: float, junction_id: str,
                               vehicle_ids: list, confidence: float = 0.91,
                               impact_severity: str = "HIGH", evidence: Optional[dict] = None) -> bool:
        payload = {
            "event_id": event_id,
            "event_type": "COLLISION_PAIR_IDENTIFIED",
            "timestamp_sim": timestamp_sim,
            "source": "member2",
            "junction_id": junction_id,
            "vehicle_ids": vehicle_ids,
            "confidence": round(confidence, 3),
            "impact_severity": impact_severity
        }
        if evidence:
            payload["evidence"] = evidence
        return self.publish_event(payload)

    def publish_anpr(self, event_id: str, timestamp_sim: float, junction_id: str,
                     camera_id: str, vehicle_id: str, plate_number: str,
                     confidence: float = 0.96) -> bool:
        payload = {
            "event_id": event_id,
            "event_type": "ANPR_IDENTIFIED",
            "timestamp_sim": timestamp_sim,
            "source": "member2",
            "junction_id": junction_id,
            "camera_id": camera_id,
            "vehicle_id": vehicle_id,
            "plate_number": plate_number,
            "confidence": round(confidence, 3)
        }
        return self.publish_event(payload)

    def publish_vehicle_observed(self, event_id: str, timestamp_sim: float, junction_id: str,
                                 camera_id: str, vehicle_id: str, plate_number: Optional[str] = None,
                                 confidence: float = 0.92) -> bool:
        payload = {
            "event_id": event_id,
            "event_type": "VEHICLE_OBSERVED",
            "timestamp_sim": timestamp_sim,
            "source": "member2",
            "junction_id": junction_id,
            "camera_id": camera_id,
            "vehicle_id": vehicle_id,
            "confidence": round(confidence, 3)
        }
        if plate_number:
            payload["plate_number"] = plate_number
        return self.publish_event(payload)
