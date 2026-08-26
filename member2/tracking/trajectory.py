from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import math

@dataclass
class TrajectoryPoint:
    timestamp_sim: float
    frame_id: int
    x: float
    y: float
    bbox: List[float]
    vx: float = 0.0
    vy: float = 0.0

    @property
    def speed(self) -> float:
        return math.sqrt(self.vx ** 2 + self.vy ** 2)

@dataclass
class VehicleTrajectory:
    track_id: str
    camera_id: str
    junction_id: str
    points: List[TrajectoryPoint] = field(default_factory=list)

    def add_point(self, point: TrajectoryPoint):
        self.points.append(point)

    def get_points_in_window(self, start_time: float, end_time: float) -> List[TrajectoryPoint]:
        return [pt for pt in self.points if start_time <= pt.timestamp_sim <= end_time]

    def get_velocity_delta(self, t_crash: float, window: float = 1.5) -> float:
        """Calculates velocity change magnitude around a specific timestamp."""
        pre_pts = self.get_points_in_window(t_crash - window, t_crash)
        post_pts = self.get_points_in_window(t_crash, t_crash + window)

        if not pre_pts or not post_pts:
            return 0.0

        v_pre = sum(p.speed for p in pre_pts) / len(pre_pts)
        v_post = sum(p.speed for p in post_pts) / len(post_pts)

        return abs(v_pre - v_post)

class TrajectoryRecorder:
    """Stores spatial-temporal trajectories for all tracked vehicles across cameras."""

    def __init__(self):
        self.trajectories: Dict[Tuple[str, str], VehicleTrajectory] = {} # Key: (camera_id, track_id)

    def record_track_state(self, track_state):
        key = (track_state.camera_id, track_state.track_id)
        if key not in self.trajectories:
            self.trajectories[key] = VehicleTrajectory(
                track_id=track_state.track_id,
                camera_id=track_state.camera_id,
                junction_id=track_state.junction_id
            )

        center_x, center_y = track_state.last_bbox.center
        vx, vy = track_state.velocity

        pt = TrajectoryPoint(
            timestamp_sim=track_state.last_timestamp,
            frame_id=track_state.last_frame_id,
            x=center_x,
            y=center_y,
            bbox=track_state.last_bbox.to_list(),
            vx=vx,
            vy=vy
        )
        self.trajectories[key].add_point(pt)

    def get_trajectory(self, camera_id: str, track_id: str) -> Optional[VehicleTrajectory]:
        return self.trajectories.get((camera_id, track_id))

    def get_active_trajectories_at(self, junction_id: str, timestamp_sim: float,
                                    time_window: float = 2.0) -> List[VehicleTrajectory]:
        results = []
        for (cam_id, trk_id), traj in self.trajectories.items():
            if traj.junction_id == junction_id:
                pts = traj.get_points_in_window(timestamp_sim - time_window, timestamp_sim + time_window)
                if pts:
                    results.append(traj)
        return results
