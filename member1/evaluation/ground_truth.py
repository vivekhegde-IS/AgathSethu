"""
Ground-Truth Collision Logger for Member 1 Evaluation.
Records actual CARLA / simulation collision metadata strictly for evaluation purposes.
MUST NOT be leaked to the Crash Detector during inference.
"""

import json
import os
from typing import Dict, Any, List


class GroundTruthLogger:
    """Manages ground-truth collision event logging and persistence."""

    def __init__(self, output_path: str = "member1/outputs/ground_truth.json"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def generate_ground_truth(
        self,
        crash_timestamp_sim: float = 102.43,
        involved_vehicles: List[str] = None,
        junction_id: str = "J02",
        location: Dict[str, float] = None
    ) -> Dict[str, Any]:
        """Generates ground-truth record dict."""
        if involved_vehicles is None:
            involved_vehicles = ["V001", "V002"]
        if location is None:
            location = {"x": 104.2, "y": 52.7, "z": 0.3}

        gt_record = {
            "ground_truth_id": "gt_col_001",
            "event_type": "GROUND_TRUTH_COLLISION",
            "crash_timestamp_sim": crash_timestamp_sim,
            "junction_id": junction_id,
            "involved_vehicles": involved_vehicles,
            "location": location,
            "simulation": True
        }

        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(gt_record, f, indent=2)

        return gt_record
