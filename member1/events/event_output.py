"""
Event Exporter and Publisher for Member 1.
Supports local JSON Lines file output and optional HTTP POST publishing to Member 3 backend.
"""

import json
import os
import logging
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger("Member1.EventPublisher")


class EventOutput:
    """Manages output storage and network transmission of CRASH_DETECTED events."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        out_cfg = config.get("output", {})
        self.events_jsonl_path = out_cfg.get("events_jsonl_path", "member1/outputs/events.jsonl")
        self.shared_jsonl_path = out_cfg.get("shared_events_jsonl_path", "shared/outputs/events.jsonl")
        self.api_endpoint = out_cfg.get("api_endpoint", "http://127.0.0.1:8000/events/crash")
        self.publish_to_api_flag = out_cfg.get("publish_to_api", True)

        # Ensure directories exist
        os.makedirs(os.path.dirname(self.events_jsonl_path), exist_ok=True)
        if os.path.exists(os.path.dirname(self.shared_jsonl_path)):
            os.makedirs(os.path.dirname(self.shared_jsonl_path), exist_ok=True)

    def write_to_jsonl(self, event: Dict[str, Any]) -> str:
        """Appends event JSON payload to local JSON Lines file(s)."""
        line = json.dumps(event) + "\n"
        
        # Write to primary output
        with open(self.events_jsonl_path, "a", encoding="utf-8") as f:
            f.write(line)

        # Write to shared output if directory exists
        shared_dir = os.path.dirname(self.shared_jsonl_path)
        if os.path.exists(shared_dir) or shared_dir == "shared/outputs":
            try:
                os.makedirs(shared_dir, exist_ok=True)
                with open(self.shared_jsonl_path, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                logger.warning(f"Could not write to shared output file: {e}")

        logger.info(f"Written CRASH_DETECTED event ({event['event_id']}) to {self.events_jsonl_path}")
        return self.events_jsonl_path

    def send_to_api(self, event: Dict[str, Any]) -> bool:
        """
        Sends event HTTP POST request to Member 3's backend.
        Handles offline/connection errors gracefully without crashing.
        """
        if not self.publish_to_api_flag:
            return False

        try:
            response = requests.post(
                self.api_endpoint,
                json=event,
                headers={"Content-Type": "application/json"},
                timeout=2.0
            )
            if response.status_code in (200, 201):
                logger.info(f"Successfully published event {event['event_id']} to API endpoint {self.api_endpoint}")
                return True
            else:
                logger.warning(f"API endpoint returned status code {response.status_code}: {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            logger.info(f"[OFFLINE MODE] Member 3 API backend not reachable at {self.api_endpoint} ({e.__class__.__name__}). Event stored locally in JSONL.")
            return False

    def publish_event(self, event: Dict[str, Any]) -> Tuple[str, bool]:
        """Convenience method to write locally and attempt API publication."""
        filepath = self.write_to_jsonl(event)
        api_success = self.send_to_api(event)
        return filepath, api_success
