"""
Member 3 Integration Adapter for Member 1 (IMU Crash Detection).
Translates external Member 1 events into Member 3 internal format.
Performs schema validation, field normalization, and safe fallback logging.
DOES NOT MODIFY MEMBER 1 CODE.
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("Member3.Member1Adapter")


class Member1Adapter:
    """Adapter for Member 1 CRASH_DETECTED events."""

    REQUIRED_HEADER_FIELDS = ["event_id", "event_type", "timestamp_sim", "source"]

    def __init__(self, events_jsonl_path: Optional[str] = None):
        if not events_jsonl_path:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            events_jsonl_path = os.path.join(root_dir, "member1", "outputs", "events.jsonl")
        self.events_jsonl_path = events_jsonl_path

    def normalize_crash_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Validates and normalizes a CRASH_DETECTED event from Member 1.
        Returns normalized event dictionary or None if invalid.
        """
        if not isinstance(raw_event, dict):
            logger.warning("[Member 1 Adapter] Invalid event type received (expected dict)")
            return None

        # Check required fields
        for field in self.REQUIRED_HEADER_FIELDS:
            if field not in raw_event:
                logger.warning(f"[Member 1 Adapter] Missing header field '{field}' in event: {raw_event}")
                return None

        event_type = raw_event.get("event_type")
        if event_type != "CRASH_DETECTED":
            logger.warning(f"[Member 1 Adapter] Unexpected event type '{event_type}', expected 'CRASH_DETECTED'")
            return None

        # Normalize required crash fields
        normalized = {
            "event_id": str(raw_event.get("event_id")),
            "event_type": "CRASH_DETECTED",
            "timestamp_sim": float(raw_event.get("timestamp_sim", 0.0)),
            "source": str(raw_event.get("source", "member1")),
            "junction_id": str(raw_event.get("junction_id", "J02")),
            "vehicle_id": str(raw_event.get("vehicle_id", "V001")),
            "confidence": float(raw_event.get("confidence", 1.0)),
            "location": raw_event.get("location", {}),
            "telemetry_summary": raw_event.get("telemetry_summary", {})
        }

        # Normalize optional telemetry summary defaults if missing
        tel = normalized["telemetry_summary"]
        if isinstance(tel, dict):
            tel.setdefault("max_g_force", 5.0)
            tel.setdefault("delta_v_mph", 25.0)

        logger.info(f"[Member 1 Adapter] Successfully normalized CRASH_DETECTED event '{normalized['event_id']}' for {normalized['vehicle_id']} at {normalized['junction_id']}")
        return normalized

    def read_latest_events(self) -> List[Dict[str, Any]]:
        """Reads and normalizes all CRASH_DETECTED events from Member 1 output file."""
        normalized_events = []
        if not os.path.exists(self.events_jsonl_path):
            logger.info(f"[Member 1 Adapter] No events file found at {self.events_jsonl_path}")
            return normalized_events

        try:
            with open(self.events_jsonl_path, "r", encoding="utf-8") as f:
                for line_idx, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        raw_evt = json.loads(line)
                        norm_evt = self.normalize_crash_event(raw_evt)
                        if norm_evt:
                            normalized_events.append(norm_evt)
                    except json.JSONDecodeError as err:
                        logger.warning(f"[Member 1 Adapter] Line {line_idx} is invalid JSON: {err}")
        except Exception as ex:
            logger.error(f"[Member 1 Adapter] Failed to read events from {self.events_jsonl_path}: {ex}")

        return normalized_events
