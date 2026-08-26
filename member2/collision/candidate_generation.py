from dataclasses import dataclass
from typing import List, Tuple
from member2.tracking.trajectory import TrajectoryRecorder, VehicleTrajectory
from member2.integration.member1_event_reader import CrashDetectedEvent

@dataclass
class CollisionCandidatePair:
    traj_a: VehicleTrajectory
    traj_b: VehicleTrajectory
    junction_id: str
    crash_timestamp: float

class CollisionCandidateGenerator:
    """Generates candidate vehicle pairs around the crash timestamp without ground-truth leakage."""

    def __init__(self, trajectory_recorder: TrajectoryRecorder, time_window_seconds: float = 2.0):
        self.trajectory_recorder = trajectory_recorder
        self.time_window_seconds = time_window_seconds

    def generate_candidate_pairs(self, crash_event: CrashDetectedEvent) -> List[CollisionCandidatePair]:
        junction_id = crash_event.junction_id
        t_crash = crash_event.timestamp_sim

        # Active trajectories near crash junction around crash timestamp
        active_trajectories = self.trajectory_recorder.get_active_trajectories_at(
            junction_id=junction_id,
            timestamp_sim=t_crash,
            time_window=self.time_window_seconds
        )

        candidate_pairs: List[CollisionCandidatePair] = []
        n = len(active_trajectories)

        for i in range(n):
            for j in range(i + 1, n):
                pair = CollisionCandidatePair(
                    traj_a=active_trajectories[i],
                    traj_b=active_trajectories[j],
                    junction_id=junction_id,
                    crash_timestamp=t_crash
                )
                candidate_pairs.append(pair)

        return candidate_pairs
