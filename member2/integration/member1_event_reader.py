import os
import json
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

@dataclass
class CrashDetectedEvent:
    event_id: str
    event_type: str
    timestamp_sim: float
    source: str
    junction_id: str
    vehicle_id: str
    confidence: float
    location: Optional[Dict[str, float]] = None
    telemetry_summary: Optional[Dict[str, Any]] = None

class Member1EventReader:
    """Read-only adapter for consuming Member 1's CRASH_DETECTED events from outputs or streams."""

    def __init__(self, events_file_path: Optional[str] = None):
        if events_file_path is None:
            events_file_path = os.path.join(os.path.dirname(__file__), "..", "..", "member1", "outputs", "events.jsonl")
        self.events_file_path = os.path.abspath(events_file_path)

    def read_latest_crash_events(self) -> List[CrashDetectedEvent]:
        events: List[CrashDetectedEvent] = []
        if not os.path.exists(self.events_file_path):
            print(f"[Member 2 Integration] Member 1 events file not found at: {self.events_file_path}")
            return events

        try:
            with open(self.events_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("event_type") == "CRASH_DETECTED":
                        evt = CrashDetectedEvent(
                            event_id=data.get("event_id", ""),
                            event_type=data.get("event_type", "CRASH_DETECTED"),
                            timestamp_sim=float(data.get("timestamp_sim", 0.0)),
                            source=data.get("source", "member1"),
                            junction_id=data.get("junction_id", "J02"),
                            vehicle_id=data.get("vehicle_id", "V001"),
                            confidence=float(data.get("confidence", 0.90)),
                            location=data.get("location"),
                            telemetry_summary=data.get("telemetry_summary")
                        )
                        events.append(evt)
        except Exception as e:
            print(f"[Member 2 Integration] Error parsing Member 1 events: {e}")

        return events
