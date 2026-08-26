import math
import yaml
import os
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from member2.collision.candidate_generation import CollisionCandidatePair
from member2.tracking.tracker import compute_iou
from member2.detection.detector import BoundingBox

@dataclass
class ScoredCollisionPair:
    track_id_a: str
    track_id_b: str
    junction_id: str
    crash_timestamp: float
    total_score: float
    impact_severity: str
    evidence_breakdown: Dict[str, float]

class CollisionScorer:
    """Multi-factor explainable collision pair scoring engine."""

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config", "collision.yaml")
        
        self.weights = {
            "spatial_proximity": 0.25,
            "temporal_alignment": 0.20,
            "trajectory_convergence": 0.25,
            "velocity_change": 0.20,
            "overlap": 0.10
        }
        self.severity_thresholds = {"HIGH": 0.80, "MEDIUM": 0.60, "LOW": 0.40}
        self._load_config(config_path)

    def _load_config(self, path: str):
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if "weights" in cfg:
                        self.weights = cfg["weights"]
                    if "severity_thresholds" in cfg:
                        self.severity_thresholds = cfg["severity_thresholds"]
            except Exception as e:
                print(f"[Member 2 Collision] Config load fallback: {e}")

    def score_candidate_pair(self, pair: CollisionCandidatePair) -> ScoredCollisionPair:
        t_crash = pair.crash_timestamp
        pts_a = pair.traj_a.get_points_in_window(t_crash - 1.5, t_crash + 1.5)
        pts_b = pair.traj_b.get_points_in_window(t_crash - 1.5, t_crash + 1.5)

        if not pts_a or not pts_b:
            return ScoredCollisionPair(
                track_id_a=pair.traj_a.track_id,
                track_id_b=pair.traj_b.track_id,
                junction_id=pair.junction_id,
                crash_timestamp=t_crash,
                total_score=0.0,
                impact_severity="LOW",
                evidence_breakdown={"spatial_proximity": 0, "temporal_alignment": 0,
                                    "trajectory_convergence": 0, "velocity_change": 0, "overlap": 0}
            )

        # 1. Spatial Proximity: min distance between vehicle centers at crash time
        min_dist = float('inf')
        max_iou = 0.0
        for pa in pts_a:
            box_a = BoundingBox(*pa.bbox)
            for pb in pts_b:
                dist = math.sqrt((pa.x - pb.x)**2 + (pa.y - pb.y)**2)
                if dist < min_dist:
                    min_dist = dist
                box_b = BoundingBox(*pb.bbox)
                iou = compute_iou(box_a, box_b)
                if iou > max_iou:
                    max_iou = iou

        spatial_score = max(0.0, min(1.0, 1.0 - (min_dist / 150.0)))

        # 2. Temporal Alignment: closeness of points to crash timestamp
        dt_a = min(abs(pa.timestamp_sim - t_crash) for pa in pts_a)
        dt_b = min(abs(pb.timestamp_sim - t_crash) for pb in pts_b)
        temporal_score = max(0.0, min(1.0, 1.0 - ((dt_a + dt_b) / 4.0)))

        # 3. Trajectory Convergence: moving towards each other
        conv_score = 0.85 if min_dist < 100.0 else 0.40

        # 4. Velocity Change / Deceleration
        v_delta_a = pair.traj_a.get_velocity_delta(t_crash)
        v_delta_b = pair.traj_b.get_velocity_delta(t_crash)
        v_score = max(0.0, min(1.0, (v_delta_a + v_delta_b) / 50.0))

        # 5. Overlap Score
        overlap_score = min(1.0, max_iou * 2.0)

        # Weighted Total Score
        total_score = (
            self.weights.get("spatial_proximity", 0.25) * spatial_score +
            self.weights.get("temporal_alignment", 0.20) * temporal_score +
            self.weights.get("trajectory_convergence", 0.25) * conv_score +
            self.weights.get("velocity_change", 0.20) * v_score +
            self.weights.get("overlap", 0.10) * overlap_score
        )

        total_score = round(min(1.0, max(0.0, total_score)), 3)

        if total_score >= self.severity_thresholds.get("HIGH", 0.80):
            severity = "HIGH"
        elif total_score >= self.severity_thresholds.get("MEDIUM", 0.60):
            severity = "MEDIUM"
        else:
            severity = "LOW"

        return ScoredCollisionPair(
            track_id_a=pair.traj_a.track_id,
            track_id_b=pair.traj_b.track_id,
            junction_id=pair.junction_id,
            crash_timestamp=t_crash,
            total_score=total_score,
            impact_severity=severity,
            evidence_breakdown={
                "spatial_proximity": round(spatial_score, 3),
                "temporal_alignment": round(temporal_score, 3),
                "trajectory_convergence": round(conv_score, 3),
                "velocity_change": round(v_score, 3),
                "overlap": round(overlap_score, 3)
            }
        )

    def select_top_collision_pair(self, candidate_pairs: List[CollisionCandidatePair]) -> Optional[ScoredCollisionPair]:
        scored_pairs = [self.score_candidate_pair(cp) for cp in candidate_pairs]
        if not scored_pairs:
            return None

        # Sort descending by score
        scored_pairs.sort(key=lambda sp: sp.total_score, reverse=True)
        top_pair = scored_pairs[0]
        if top_pair.total_score >= 0.40:
            return top_pair
        return None
