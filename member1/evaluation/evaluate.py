"""
Evaluation & Benchmark Metric Engine for Member 1.
Compares detected CRASH_DETECTED events against Ground Truth to calculate:
- Detection Success / Recall
- Vehicle Identification Accuracy
- Detection Delay / Latency (ms)
- False Positive / Negative Counts
"""

import json
import os
from typing import Dict, Any, List, Optional
from member1.evaluation.ground_truth import GroundTruthLogger


class MetricEvaluator:
    """Evaluates crash detector performance against ground-truth simulation data."""

    def __init__(self, gt_path: str = "member1/outputs/ground_truth.json", events_path: str = "member1/outputs/events.jsonl"):
        self.gt_path = gt_path
        self.events_path = events_path

    def load_ground_truth(self) -> Dict[str, Any]:
        """Loads ground-truth collision record."""
        if not os.path.exists(self.gt_path):
            gt_logger = GroundTruthLogger(self.gt_path)
            return gt_logger.generate_ground_truth()
        
        with open(self.gt_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_detected_events(self) -> List[Dict[str, Any]]:
        """Loads detected CRASH_DETECTED events from JSONL file."""
        events = []
        if not os.path.exists(self.events_path):
            return events

        with open(self.events_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        data = json.loads(line)
                        if data.get("event_type") == "CRASH_DETECTED":
                            events.append(data)
                    except json.JSONDecodeError:
                        continue
        return events

    def evaluate(self) -> Dict[str, Any]:
        """Runs evaluation comparison and returns evaluation metrics dict."""
        gt = self.load_ground_truth()
        detected_events = self.load_detected_events()

        gt_time = gt["crash_timestamp_sim"]
        gt_vehicles = set(gt["involved_vehicles"])

        detected_vehicles = set()
        delays = []
        true_positives = 0
        false_positives = 0

        for evt in detected_events:
            v_id = evt["vehicle_id"]
            t_det = evt["timestamp_sim"]
            
            if v_id in gt_vehicles and abs(t_det - gt_time) <= 1.0:
                true_positives += 1
                detected_vehicles.add(v_id)
                delay_ms = (t_det - gt_time) * 1000.0
                delays.append(delay_ms)
            else:
                false_positives += 1

        fn_vehicles = gt_vehicles - detected_vehicles
        false_negatives = len(fn_vehicles)

        avg_delay_ms = sum(delays) / len(delays) if delays else 0.0
        vehicle_accuracy = (len(detected_vehicles) / len(gt_vehicles)) * 100.0 if gt_vehicles else 0.0

        results = {
            "ground_truth_time": gt_time,
            "ground_truth_vehicles": list(gt_vehicles),
            "detected_event_count": len(detected_events),
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives,
            "detected_vehicles": list(detected_vehicles),
            "missed_vehicles": list(fn_vehicles),
            "vehicle_identification_accuracy_pct": round(vehicle_accuracy, 1),
            "mean_detection_delay_ms": round(avg_delay_ms, 2),
            "crash_detected_success": true_positives > 0
        }

        return results

    def print_summary(self):
        """Prints a clean, structured terminal summary of evaluation metrics."""
        res = self.evaluate()
        print("\n" + "=" * 50)
        print("MEMBER 1: CRASH DETECTION EVALUATION METRICS")
        print("=" * 50)
        print(f"Ground Truth Crash Time:    {res['ground_truth_time']:.2f} s")
        print(f"Ground Truth Vehicles:      {', '.join(res['ground_truth_vehicles'])}")
        print(f"Detected Event Count:       {res['detected_event_count']}")
        print(f"True Positives:             {res['true_positives']}")
        print(f"False Positives:            {res['false_positives']}")
        print(f"False Negatives:            {res['false_negatives']}")
        print(f"Vehicle Identification Acc: {res['vehicle_identification_accuracy_pct']:.1f}%")
        print(f"Mean Detection Delay:       {res['mean_detection_delay_ms']:.2f} ms")
        print("-" * 50)
        if res["crash_detected_success"]:
            print("OVERALL RESULT: [PASSED] Crash successfully detected from IMU sensor data!")
        else:
            print("OVERALL RESULT: [FAILED] Crash was not detected.")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    evaluator = MetricEvaluator()
    evaluator.print_summary()
