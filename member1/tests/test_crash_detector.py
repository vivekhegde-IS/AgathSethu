"""
Unit Test Suite for Member 1 Crash Detection Module.
Run with: pytest member1/tests/
"""

import unittest
import os
import json
import yaml
from member1.imu.simulator import IMUSimulator
from member1.imu.filters import SignalFilter
from member1.imu.features import FeatureExtractor
from member1.imu.crash_detector import CrashDetector
from member1.events.schema import CrashDetectedEvent
from member1.events.event_output import EventOutput
from member1.evaluation.ground_truth import GroundTruthLogger
from member1.evaluation.evaluate import MetricEvaluator


class TestMember1CrashDetector(unittest.TestCase):

    def setUp(self):
        self.config = {
            "simulation": {"junction_id": "J02", "location": {"x": 104.2, "y": 52.7, "z": 0.3}},
            "imu": {"sampling_rate_hz": 50.0, "accel_noise_std": 0.05, "gyro_noise_std": 0.02, "gravity_m_s2": 9.81},
            "crash_detection": {
                "acceleration_threshold_g": 4.5,
                "jerk_threshold": 25.0,
                "gyro_threshold": 2.5,
                "confidence_threshold": 0.70,
                "window_seconds": 0.5,
                "weights": {"acceleration": 0.50, "jerk": 0.30, "gyro": 0.20}
            },
            "output": {
                "events_jsonl_path": "member1/outputs/test_events.jsonl",
                "publish_to_api": False
            }
        }

    def tearDown(self):
        test_file = "member1/outputs/test_events.jsonl"
        if os.path.exists(test_file):
            os.remove(test_file)

    def test_imu_simulator_generation(self):
        sim = IMUSimulator(sampling_rate_hz=50.0)
        sample = sim.generate_sample(
            timestamp_sim=100.0,
            vehicle_id="V001",
            clean_accel=(0.0, 0.0, 9.81),
            clean_gyro=(0.0, 0.0, 0.0)
        )
        self.assertEqual(sample["vehicle_id"], "V001")
        self.assertEqual(sample["timestamp_sim"], 100.0)
        self.assertIn("ax", sample["accelerometer"])
        self.assertIn("gx", sample["gyroscope"])

    def test_feature_extractor(self):
        extractor = FeatureExtractor(gravity=9.81, sampling_rate_hz=50.0)
        sample1 = {
            "timestamp_sim": 100.0,
            "vehicle_id": "V001",
            "accelerometer": {"ax": 0.0, "ay": 0.0, "az": 9.81},
            "gyroscope": {"gx": 0.0, "gy": 0.0, "gz": 0.0}
        }
        features1 = extractor.extract_features(sample1)
        self.assertAlmostEqual(features1["g_force"], 1.0, delta=0.05)

        # High G sample
        sample2 = {
            "timestamp_sim": 100.02,
            "vehicle_id": "V001",
            "accelerometer": {"ax": -50.0, "ay": 20.0, "az": 9.81},
            "gyroscope": {"gx": 3.0, "gy": 1.0, "gz": 2.0}
        }
        features2 = extractor.extract_features(sample2)
        self.assertGreater(features2["g_force"], 5.0)
        self.assertGreater(features2["jerk"], 10.0)
        self.assertGreater(features2["gyro_mag"], 3.0)

    def test_crash_detector_normal_driving(self):
        detector = CrashDetector(self.config)
        normal_sample = {
            "timestamp_sim": 100.0,
            "vehicle_id": "V001",
            "accelerometer": {"ax": 0.1, "ay": 0.05, "az": 9.81},
            "gyroscope": {"gx": 0.01, "gy": 0.01, "gz": 0.02}
        }
        event = detector.process_imu_sample(normal_sample)
        self.assertIsNone(event, "Normal driving should NOT trigger a crash event.")

    def test_crash_detector_high_g_impact(self):
        detector = CrashDetector(self.config)
        
        # Warm up with normal sample
        s1 = {
            "timestamp_sim": 102.40,
            "vehicle_id": "V001",
            "accelerometer": {"ax": 0.0, "ay": 0.0, "az": 9.81},
            "gyroscope": {"gx": 0.0, "gy": 0.0, "gz": 0.0}
        }
        detector.process_imu_sample(s1)

        # Impact sample: 5.8g acceleration spike, high jerk, high gyro
        s2 = {
            "timestamp_sim": 102.43,
            "vehicle_id": "V001",
            "accelerometer": {"ax": -56.8, "ay": 23.2, "az": 12.5},
            "gyroscope": {"gx": 3.7, "gy": -2.5, "gz": 4.4}
        }
        event = detector.process_imu_sample(s2)
        self.assertIsNotNone(event, "High-G impact MUST trigger a CRASH_DETECTED event.")
        self.assertEqual(event["event_type"], "CRASH_DETECTED")
        self.assertEqual(event["vehicle_id"], "V001")
        self.assertGreaterEqual(event["confidence"], 0.70)

    def test_event_schema_validation(self):
        event_dict = {
            "event_id": "evt_crash_001",
            "event_type": "CRASH_DETECTED",
            "timestamp_sim": 102.43,
            "source": "member1",
            "junction_id": "J02",
            "vehicle_id": "V001",
            "confidence": 0.94,
            "location": {"x": 104.2, "y": 52.7, "z": 0.3},
            "telemetry_summary": {"max_g_force": 5.8, "jerk": 42.1, "gyro_magnitude": 3.7}
        }
        validated = CrashDetectedEvent(**event_dict)
        self.assertEqual(validated.event_type, "CRASH_DETECTED")
        self.assertEqual(validated.vehicle_id, "V001")

    def test_evaluator(self):
        gt_logger = GroundTruthLogger("member1/outputs/test_gt.json")
        gt_logger.generate_ground_truth(crash_timestamp_sim=102.43, involved_vehicles=["V001", "V002"])

        event_output = EventOutput(self.config)
        event_output.write_to_jsonl({
            "event_id": "evt_crash_001",
            "event_type": "CRASH_DETECTED",
            "timestamp_sim": 102.43,
            "source": "member1",
            "junction_id": "J02",
            "vehicle_id": "V001",
            "confidence": 0.94
        })

        evaluator = MetricEvaluator(gt_path="member1/outputs/test_gt.json", events_path="member1/outputs/test_events.jsonl")
        metrics = evaluator.evaluate()
        self.assertTrue(metrics["crash_detected_success"])
        self.assertEqual(metrics["true_positives"], 1)

        # Cleanup
        if os.path.exists("member1/outputs/test_gt.json"):
            os.remove("member1/outputs/test_gt.json")


if __name__ == "__main__":
    unittest.main()
