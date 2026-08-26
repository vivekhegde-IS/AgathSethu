import os
import json
import pytest
import numpy as np

from member2.camera.camera_config import CameraConfig, CameraSpec
from member2.camera.carla_camera import CarlaCameraManager
from member2.detection.detector import BoundingBox, DetectionResult
from member2.tracking.tracker import MultiObjectTracker
from member2.tracking.trajectory import TrajectoryRecorder, VehicleTrajectory, TrajectoryPoint
from member2.integration.member1_event_reader import Member1EventReader, CrashDetectedEvent
from member2.collision.candidate_generation import CollisionCandidateGenerator
from member2.collision.collision_scorer import CollisionScorer
from member2.anpr.plate_detector import PlateDetector
from member2.anpr.ocr import OCREngine, OCRResult
from member2.anpr.plate_aggregator import MultiFramePlateAggregator
from member2.identity.vehicle_identity import VehicleIdentityManager
from member2.identity.cross_camera import CrossCameraTracker
from member2.events.event_publisher import EventPublisher

def test_camera_config_loading():
    config = CameraConfig()
    cam_j02 = config.get_camera("CAM_J02_01")
    assert cam_j02 is not None
    assert cam_j02.junction_id == "J02"

def test_tracker_assignment():
    tracker = MultiObjectTracker(camera_id="CAM_J02_01", junction_id="J02")
    det = DetectionResult(
        camera_id="CAM_J02_01",
        junction_id="J02",
        frame_id=1,
        timestamp_sim=100.0,
        class_name="car",
        confidence=0.90,
        bbox=BoundingBox(100, 100, 200, 160)
    )
    tracks = tracker.update([det], timestamp_sim=100.0, frame_id=1)
    assert len(tracks) == 1
    assert tracks[0].track_id == "TRACK_01"

def test_collision_pair_scoring():
    scorer = CollisionScorer()
    t_crash = 102.43

    traj_a = VehicleTrajectory(track_id="TRACK_17", camera_id="CAM_J02_01", junction_id="J02")
    traj_a.add_point(TrajectoryPoint(timestamp_sim=t_crash, frame_id=10, x=100.0, y=100.0, bbox=[80, 80, 120, 120], vx=-5.0, vy=0.0))

    traj_b = VehicleTrajectory(track_id="TRACK_23", camera_id="CAM_J02_01", junction_id="J02")
    traj_b.add_point(TrajectoryPoint(timestamp_sim=t_crash, frame_id=10, x=105.0, y=100.0, bbox=[85, 80, 125, 120], vx=10.0, vy=0.0))

    rec = TrajectoryRecorder()
    rec.trajectories[("CAM_J02_01", "TRACK_17")] = traj_a
    rec.trajectories[("CAM_J02_01", "TRACK_23")] = traj_b

    gen = CollisionCandidateGenerator(rec)
    crash_event = CrashDetectedEvent(
        event_id="evt_001", event_type="CRASH_DETECTED", timestamp_sim=t_crash,
        source="member1", junction_id="J02", vehicle_id="V001", confidence=0.90
    )
    candidates = gen.generate_candidate_pairs(crash_event)
    assert len(candidates) == 1

    top_score = scorer.select_top_collision_pair(candidates)
    assert top_score is not None
    assert top_score.total_score >= 0.55
    assert top_score.impact_severity in ["HIGH", "MEDIUM"]

def test_anpr_aggregation():
    agg = MultiFramePlateAggregator()
    agg.add_observation("CAM_J02_01", "J02", "TRACK_23", OCRResult("KA05XY5678", "KA05XY5678", 0.95))
    agg.add_observation("CAM_J02_01", "J02", "TRACK_23", OCRResult("KA05XY5678", "KA05XY5678", 0.97))
    res = agg.get_aggregated_plate("CAM_J02_01", "TRACK_23")

    assert res is not None
    assert res.best_plate_number == "KA05XY5678"

def test_event_publisher(tmp_path):
    output_file = tmp_path / "events.jsonl"
    pub = EventPublisher(output_path=str(output_file))

    success = pub.publish_anpr(
        event_id="evt_anpr_test",
        timestamp_sim=102.50,
        junction_id="J02",
        camera_id="CAM_J02_01",
        vehicle_id="V002",
        plate_number="KA05XY5678",
        confidence=0.96
    )
    assert success is True
    assert output_file.exists()

    with open(output_file, "r") as f:
        data = json.loads(f.readline())
        assert data["event_type"] == "ANPR_IDENTIFIED"
        assert data["plate_number"] == "KA05XY5678"
