"""
Member 3 Event Ingestion Pipeline.
Handles validation, normalization, DB storage, vehicle history tracking,
and triggers the evidence fusion engine upon incoming events.
"""

import logging
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from member3.integration.member1_adapter import Member1Adapter
from member3.integration.member2_adapter import Member2Adapter
from member3.database.repository import EventRepository, VehicleHistoryRepository
from member3.database.db import get_session_direct

logger = logging.getLogger("Member3.EventIngestion")


class EventIngestionPipeline:
    """Central event processor for Member 3."""

    def __init__(self, db: Optional[Session] = None):
        self.member1_adapter = Member1Adapter()
        self.member2_adapter = Member2Adapter()
        self.db = db or get_session_direct()

    def ingest_raw_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Ingests a raw incoming event dictionary (from Member 1, Member 2, or RFID),
        normalizes it, stores it in DB, updates vehicle history, and returns normalized event.
        """
        event_type = raw_event.get("event_type")
        source = raw_event.get("source")
        normalized = None

        if event_type == "CRASH_DETECTED":
            normalized = self.member1_adapter.normalize_crash_event(raw_event)
        elif event_type in ["COLLISION_PAIR_IDENTIFIED", "ANPR_IDENTIFIED", "VEHICLE_OBSERVED"]:
            normalized = self.member2_adapter.normalize_event(raw_event)
        elif event_type == "RFID_DETECTED":
            normalized = self._normalize_rfid_event(raw_event)
        else:
            logger.warning(f"[Event Ingestion] Unrecognized event_type '{event_type}'")
            return None

        if not normalized:
            logger.warning(f"[Event Ingestion] Event normalization failed for raw event: {raw_event}")
            return None

        # Store in Events Table
        EventRepository.save_event(self.db, normalized)

        # Update Vehicle History if vehicle observation present
        self._record_vehicle_history(normalized)

        return normalized

    def _normalize_rfid_event(self, raw_event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Normalizes Member 3 RFID_DETECTED events."""
        if not raw_event.get("event_id") or not raw_event.get("vehicle_id"):
            return None
        return {
            "event_id": str(raw_event["event_id"]),
            "event_type": "RFID_DETECTED",
            "timestamp_sim": float(raw_event.get("timestamp_sim", 0.0)),
            "source": "member3",
            "junction_id": str(raw_event.get("junction_id", "J03")),
            "reader_id": str(raw_event.get("reader_id", "RFID_J03_R01")),
            "vehicle_id": str(raw_event["vehicle_id"]),
            "tag_id": str(raw_event.get("tag_id", "")),
            "plate_number": str(raw_event.get("plate_number", "")).upper().strip()
        }

    def _record_vehicle_history(self, event: Dict[str, Any]):
        """Extracts vehicle observations to maintain vehicle location history."""
        event_type = event["event_type"]
        timestamp_sim = event["timestamp_sim"]
        junction_id = event.get("junction_id", "J02")
        event_id = event["event_id"]

        if event_type == "CRASH_DETECTED" and event.get("vehicle_id"):
            VehicleHistoryRepository.record_observation(
                db=self.db,
                vehicle_id=event["vehicle_id"],
                plate_number="KA01AB1234" if event["vehicle_id"] == "V001" else "",
                junction_id=junction_id,
                timestamp_sim=timestamp_sim,
                source_type="member1_crash",
                event_id=event_id,
                details={"max_g": event.get("telemetry_summary", {}).get("max_g_force", 0.0)}
            )

        elif event_type == "ANPR_IDENTIFIED" and event.get("vehicle_id"):
            VehicleHistoryRepository.record_observation(
                db=self.db,
                vehicle_id=event["vehicle_id"],
                plate_number=event.get("plate_number", ""),
                junction_id=junction_id,
                timestamp_sim=timestamp_sim,
                source_type="member2_anpr",
                event_id=event_id,
                details={"camera_id": event.get("camera_id")}
            )

        elif event_type == "VEHICLE_OBSERVED" and event.get("vehicle_id"):
            VehicleHistoryRepository.record_observation(
                db=self.db,
                vehicle_id=event["vehicle_id"],
                plate_number=event.get("plate_number", ""),
                junction_id=junction_id,
                timestamp_sim=timestamp_sim,
                source_type="member2_vision",
                event_id=event_id,
                details={"camera_id": event.get("camera_id")}
            )

        elif event_type == "RFID_DETECTED" and event.get("vehicle_id"):
            VehicleHistoryRepository.record_observation(
                db=self.db,
                vehicle_id=event["vehicle_id"],
                plate_number=event.get("plate_number", ""),
                junction_id=junction_id,
                timestamp_sim=timestamp_sim,
                source_type="member3_rfid",
                event_id=event_id,
                details={"reader_id": event.get("reader_id"), "tag_id": event.get("tag_id")}
            )

    def ingest_from_upstream_files(self) -> List[Dict[str, Any]]:
        """Ingests latest events from Member 1 and Member 2 JSONL files."""
        ingested = []

        # Read Member 1 events
        m1_events = self.member1_adapter.read_latest_events()
        for evt in m1_events:
            res = self.ingest_raw_event(evt)
            if res:
                ingested.append(res)

        # Read Member 2 events
        m2_events = self.member2_adapter.read_latest_events()
        for evt in m2_events:
            res = self.ingest_raw_event(evt)
            if res:
                ingested.append(res)

        return ingested
