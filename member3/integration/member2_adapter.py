"""
Member 3 Integration Adapter for Member 2 (Vision Pipeline).
Translates external Member 2 events into Member 3 internal format.
Performs schema validation, field normalization, and safe fallback logging.
DOES NOT MODIFY MEMBER 2 CODE.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("Member3.Member2Adapter")


class Member2Adapter:
    """Adapter for Member 2 events (COLLISION_PAIR_IDENTIFIED, ANPR_IDENTIFIED, VEHICLE_OBSERVED)."""

    VALID_EVENT_TYPES = ["COLLISION_PAIR_IDENTIFIED", "ANPR_IDENTIFIED", "VEHICLE_OBSERVED"]
    REQUIRED_HEADER_FIELDS = ["event_id", "event_type", "timestamp_sim", "source"]

    def __init__(self, events_jsonl_path: Optional[str] = None):
        if not events_jsonl_path:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            events_jsonl_path = os.path.join(root_dir, "member2", "outputs", "events.jsonl")
        self.events_jsonl_path = events_jsonl_path

    def normalize_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validates and normalizes an event from Member 2.
        Returns normalized event dictionary or None if invalid.
        """
        if not isinstance(raw_event, dict):
            logger.warning("[Member 2 Adapter] Invalid event structure received (expected dict)")
            return None

        # Validate header fields
        for field in self.REQUIRED_HEADER_FIELDS:
            if field not in raw_event:
                logger.warning(f"[Member 2 Adapter] Missing header field '{field}' in event: {raw_event}")
                return None

        event_type = raw_event.get("event_type")
        if event_type not in self.VALID_EVENT_TYPES:
            logger.warning(f"[Member 2 Adapter] Unrecognized event_type '{event_type}'")
            return None

        if event_type == "COLLISION_PAIR_IDENTIFIED":
            return self._normalize_collision_pair(raw_event)
        elif event_type == "ANPR_IDENTIFIED":
            return self._normalize_anpr(raw_event)
        elif event_type == "VEHICLE_OBSERVED":
            return self._normalize_vehicle_observed(raw_event)

        return None

    def _normalize_collision_pair(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        vehicle_ids = raw_event.get("vehicle_ids", [])
        if isinstance(vehicle_ids, list):
            vehicle_ids = [str(v) for v in vehicle_ids]
        else:
            vehicle_ids = []

        # Track ID to Project Vehicle ID normalization
        track_map = {
            "TRACK_03": "V001",
            "TRACK_04": "V002",
            "V_TRACK_03": "V001",
            "V_TRACK_04": "V002"
        }
        normalized_vids = [track_map.get(v, v) for v in vehicle_ids]

        return {
            "event_id": str(raw_event.get("event_id")),
            "event_type": "COLLISION_PAIR_IDENTIFIED",
            "timestamp_sim": float(raw_event.get("timestamp_sim", 0.0)),
            "source": str(raw_event.get("source", "member2")),
            "junction_id": str(raw_event.get("junction_id", "J02")),
            "vehicle_ids": normalized_vids,
            "confidence": float(raw_event.get("confidence", 0.9)),
            "impact_severity": str(raw_event.get("impact_severity", "HIGH")),
            "evidence": raw_event.get("evidence", {})
        }

    def _normalize_anpr(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "event_id": str(raw_event.get("event_id")),
            "event_type": "ANPR_IDENTIFIED",
            "timestamp_sim": float(raw_event.get("timestamp_sim", 0.0)),
            "source": str(raw_event.get("source", "member2")),
            "junction_id": str(raw_event.get("junction_id", "J02")),
            "camera_id": str(raw_event.get("camera_id", "CAM_J02_MAIN")),
            "vehicle_id": str(raw_event.get("vehicle_id", "")),
            "plate_number": str(raw_event.get("plate_number", "")).upper().strip(),
            "confidence": float(raw_event.get("confidence", 0.95))
        }

    def _normalize_vehicle_observed(self, raw_event: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "event_id": str(raw_event.get("event_id")),
            "event_type": "VEHICLE_OBSERVED",
            "timestamp_sim": float(raw_event.get("timestamp_sim", 0.0)),
            "source": str(raw_event.get("source", "member2")),
            "junction_id": str(raw_event.get("junction_id", "J04")),
            "camera_id": str(raw_event.get("camera_id", "CAM_J04_HWY")),
            "vehicle_id": str(raw_event.get("vehicle_id", "")),
            "plate_number": str(raw_event.get("plate_number", "")).upper().strip(),
            "confidence": float(raw_event.get("confidence", 0.90))
        }

    def read_latest_events(self) -> List[Dict[str, Any]]:
        """Reads and normalizes all events from Member 2 output JSONL file."""
        normalized_events = []
        if not os.path.exists(self.events_jsonl_path):
            logger.info(f"[Member 2 Adapter] No events file found at {self.events_jsonl_path}")
            return normalized_events

        try:
            with open(self.events_jsonl_path, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_evt = json.loads(line)
                        norm_evt = self.normalize_event(raw_evt)
                        if norm_evt:
                            normalized_events.append(norm_evt)
                    except json.JSONDecodeError as err:
                        logger.warning(f"[Member 2 Adapter] Line {line_idx} is invalid JSON: {err}")
        except Exception as ex:
            logger.error(f"[Member 2 Adapter] Failed to read events from {self.events_jsonl_path}: {ex}")

        return normalized_events
