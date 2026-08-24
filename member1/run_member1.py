"""
Main Entrypoint Runner for Member 1.
Orchestrates vehicle simulation, IMU sensor simulation, signal feature processing,
hybrid crash detection, event emission, evaluation, and telemetry plotting.
"""

import os
import sys
import yaml
import logging
from typing import Dict, Any, List

# Ensure project root is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from member1.simulation.scenario import ScenarioManager
from member1.imu.simulator import IMUSimulator
from member1.imu.crash_detector import CrashDetector
from member1.events.schema import CrashDetectedEvent
from member1.events.event_output import EventOutput
from member1.evaluation.ground_truth import GroundTruthLogger
from member1.evaluation.evaluate import MetricEvaluator
from member1.visualization.plot_sensor_data import plot_telemetry_and_events

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("Member1.Main")


def load_config() -> Dict[str, Any]:
    """Loads configuration merging shared config and member1 config."""
    member1_cfg_path = os.path.join(ROOT_DIR, "member1", "config", "config.yaml")
    shared_cfg_path = os.path.join(ROOT_DIR, "shared", "config", "demo_config.yaml")

    config = {}
    if os.path.exists(member1_cfg_path):
        with open(member1_cfg_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    if os.path.exists(shared_cfg_path):
        with open(shared_cfg_path, "r", encoding="utf-8") as f:
            shared_cfg = yaml.safe_load(f) or {}
            # Integrate vehicles and junctions from shared config if available
            if "vehicles" in shared_cfg:
                config.setdefault("shared_vehicles", shared_cfg["vehicles"])

    return config


def run_member1_pipeline() -> bool:
    """Runs the complete Member 1 crash detection simulation pipeline."""
    config = load_config()
    
    # 1. Clean previous outputs
    out_dir = os.path.join(ROOT_DIR, "member1", "outputs")
    os.makedirs(out_dir, exist_ok=True)
    events_path = os.path.join(out_dir, "events.jsonl")
    if os.path.exists(events_path):
        os.remove(events_path)

    # 2. Initialize Ground Truth
    gt_path = os.path.join(out_dir, "ground_truth.json")
    gt_logger = GroundTruthLogger(output_path=gt_path)
    gt_logger.generate_ground_truth(
        crash_timestamp_sim=config.get("simulation", {}).get("crash_timestamp_sim", 102.43),
        involved_vehicles=["V001", "V002"],
        junction_id=config.get("simulation", {}).get("junction_id", "J02"),
        location=config.get("simulation", {}).get("location", {"x": 104.2, "y": 52.7, "z": 0.3})
    )

    # 3. Initialize simulation components
    scenario_mgr = ScenarioManager(config)
    imu_sim = IMUSimulator(
        sampling_rate_hz=config.get("imu", {}).get("sampling_rate_hz", 50.0),
        accel_noise_std=config.get("imu", {}).get("accel_noise_std", 0.05),
        gyro_noise_std=config.get("imu", {}).get("gyro_noise_std", 0.02)
    )
    detector = CrashDetector(config)
    event_output = EventOutput(config)

    # 4. Generate scenario telemetry
    timestamps, raw_telemetry = scenario_mgr.generate_kinematic_telemetry()

    print("\n" + "=" * 60)
    print("MEMBER 1 CRASH DETECTION DEMO")
    print("=" * 60)
    print("Vehicles: V001 (Victim), V002 (Suspect)")
    print("Simulation started at Junction J02...\n")

    detected_events: List[Dict[str, Any]] = []

    # 5. Process timestep sensor stream
    for idx, t in enumerate(timestamps):
        for v_id, frames in raw_telemetry.items():
            frame = frames[idx]
            
            # Create noisy IMU reading
            imu_sample = imu_sim.generate_sample(
                timestamp_sim=t,
                vehicle_id=v_id,
                clean_accel=frame["accel"],
                clean_gyro=frame["gyro"]
            )

            # Pass IMU sample through crash detector (INFERENCE MODE ONLY)
            event_payload = detector.process_imu_sample(
                imu_sample=imu_sample,
                vehicle_location=frame["position"]
            )

            if event_payload:
                # Validate with Pydantic Schema
                validated_event = CrashDetectedEvent(**event_payload)
                event_dict = validated_event.to_dict()
                
                # Output to JSONL & try API
                event_output.publish_event(event_dict)
                detected_events.append(event_dict)

                ev_summary = event_dict.get("telemetry_summary", {})
                print("----------------------------------------")
                print("ABNORMAL SENSOR EVENT DETECTED!")
                print(f"Vehicle:           {event_dict['vehicle_id']}")
                print(f"Acceleration:      {ev_summary.get('max_g_force', 0.0):.2f} g")
                print(f"Jerk:              {ev_summary.get('jerk', 0.0):.1f} g/s")
                print(f"Angular velocity:  {ev_summary.get('gyro_magnitude', 0.0):.2f} rad/s")
                print(f"CRASH DETECTED")
                print(f"Event ID:          {event_dict['event_id']}")
                print(f"Timestamp:         {event_dict['timestamp_sim']:.2f} s")
                print(f"Location:          Junction {event_dict['junction_id']} ({event_dict['location']})")
                print(f"Confidence:        {event_dict['confidence']:.2f}")
                print(f"Event written to:  {events_path}")
                print("----------------------------------------\n")

    # 6. Run Evaluation
    evaluator = MetricEvaluator(gt_path=gt_path, events_path=events_path)
    evaluator.print_summary()

    # 7. Generate Telemetry Plot
    plot_path = os.path.join(out_dir, "crash_sensor_plot.png")
    plot_telemetry_and_events(timestamps, raw_telemetry, detected_events, output_path=plot_path)

    return len(detected_events) > 0


if __name__ == "__main__":
    run_member1_pipeline()
