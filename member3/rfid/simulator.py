"""
Member 3 Virtual RFID Checkpoint Simulator.
Simulates RFID readers at junctions (e.g. J03), detection zones, tag read cooldowns,
duplicate suppression, and generates RFID_DETECTED events.
"""

import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("Member3.RFIDSimulator")


class RFIDReaderSimulator:
    """Virtual RFID Reader Checkpoint."""

    def __init__(
        self,
        reader_id: str = "RFID_J03_R01",
        junction_id: str = "J03",
        read_range_m: float = 15.0,
        cooldown_seconds: float = 5.0
    ):
        self.reader_id = reader_id
        self.junction_id = junction_id
        self.read_range_m = read_range_m
        self.cooldown_seconds = cooldown_seconds
        self._last_read_times: Dict[str, float] = {}
        self._event_counter = 1

    def detect_tag(
        self,
        vehicle_id: str,
        tag_id: str,
        plate_number: str,
        timestamp_sim: float,
        distance_m: float = 5.0
    ) -> Optional[Dict[str, Any]]:
        """
        Simulates scanning an RFID tag passing through the checkpoint.
        Applies range check and duplicate suppression / cooldown.
        """
        # Range check
        if distance_m > self.read_range_m:
            logger.debug(f"[RFID {self.reader_id}] Tag {tag_id} out of range ({distance_m}m > {self.read_range_m}m)")
            return None

        # Cooldown / Duplicate suppression check
        last_time = self._last_read_times.get(tag_id, -1.0)
        if last_time >= 0 and (timestamp_sim - last_time) < self.cooldown_seconds:
            logger.info(f"[RFID {self.reader_id}] Suppressing duplicate read for tag {tag_id} (cooldown active)")
            return None

        # Update last read timestamp
        self._last_read_times[tag_id] = timestamp_sim

        event_id = f"evt_rfid_{self._event_counter:03d}"
        self._event_counter += 1

        event = {
            "event_id": event_id,
            "event_type": "RFID_DETECTED",
            "timestamp_sim": float(timestamp_sim),
            "source": "member3",
            "junction_id": self.junction_id,
            "reader_id": self.reader_id,
            "vehicle_id": str(vehicle_id),
            "tag_id": str(tag_id),
            "plate_number": str(plate_number).upper().strip()
        }

        logger.info(
            f"[RFID {self.reader_id}] RFID DETECTED: Vehicle {vehicle_id} (Plate: {plate_number}) "
            f"at {self.junction_id} at t={timestamp_sim:.2f}s"
        )
        return event

    def reset(self):
        """Resets reader memory and event counter."""
        self._last_read_times.clear()
        self._event_counter = 1
