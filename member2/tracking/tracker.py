from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np
from member2.detection.detector import DetectionResult, BoundingBox

@dataclass
class TrackState:
    track_id: str
    camera_id: str
    junction_id: str
    class_name: str
    last_bbox: BoundingBox
    last_timestamp: float
    last_frame_id: int
    confidence: float
    age: int = 1
    hits: int = 1
    velocity: Tuple[float, float] = (0.0, 0.0)

def compute_iou(boxA: BoundingBox, boxB: BoundingBox) -> float:
    xA = max(boxA.x1, boxB.x1)
    yA = max(boxA.y1, boxB.y1)
    xB = min(boxA.x2, boxB.x2)
    yB = min(boxA.y2, boxB.y2)

    interArea = max(0, xB - xA) * max(0, yB - yA)
    boxAArea = boxA.area
    boxBArea = boxB.area

    denom = float(boxAArea + boxBArea - interArea)
    if denom <= 0:
        return 0.0
    return interArea / denom

class MultiObjectTracker:
    """Multi-Object Tracker maintaining stable per-camera track IDs (e.g. TRACK_01, TRACK_02)."""

    def __init__(self, camera_id: str, junction_id: str, iou_threshold: float = 0.15, max_age: int = 15):
        self.camera_id = camera_id
        self.junction_id = junction_id
        self.iou_threshold = iou_threshold
        self.max_age = max_age
        self.tracks: Dict[str, TrackState] = {}
        self.track_counter = 0

    def update(self, detections: List[DetectionResult], timestamp_sim: float, frame_id: int) -> List[TrackState]:
        cam_dets = [d for d in detections if d.camera_id == self.camera_id]

        active_track_ids = list(self.tracks.keys())
        matched_tracks = set()
        matched_dets = set()

        if active_track_ids and cam_dets:
            # Build cost matrix considering predicted position based on velocity
            cost_matrix = np.zeros((len(active_track_ids), len(cam_dets)), dtype=np.float32)
            for i, tid in enumerate(active_track_ids):
                trk = self.tracks[tid]
                dt = max(0.01, timestamp_sim - trk.last_timestamp)
                pred_x1 = trk.last_bbox.x1 + trk.velocity[0] * dt
                pred_y1 = trk.last_bbox.y1 + trk.velocity[1] * dt
                pred_x2 = trk.last_bbox.x2 + trk.velocity[0] * dt
                pred_y2 = trk.last_bbox.y2 + trk.velocity[1] * dt
                pred_box = BoundingBox(pred_x1, pred_y1, pred_x2, pred_y2)

                for j, det in enumerate(cam_dets):
                    iou_curr = compute_iou(trk.last_bbox, det.bbox)
                    iou_pred = compute_iou(pred_box, det.bbox)
                    cost_matrix[i, j] = max(iou_curr, iou_pred)

            # Match greedily
            for _ in range(min(len(active_track_ids), len(cam_dets))):
                idx = np.unravel_index(np.argmax(cost_matrix), cost_matrix.shape)
                max_score = cost_matrix[idx]
                if max_score < 0.05: # Allow low IoU during heavy overlap if distance close
                    break

                t_idx, d_idx = idx[0], idx[1]
                if t_idx in matched_tracks or d_idx in matched_dets:
                    cost_matrix[t_idx, d_idx] = -1.0
                    continue

                matched_tracks.add(t_idx)
                matched_dets.add(d_idx)

                tid = active_track_ids[t_idx]
                det = cam_dets[d_idx]

                prev_track = self.tracks[tid]
                dt = max(0.01, timestamp_sim - prev_track.last_timestamp)
                prev_c = prev_track.last_bbox.center
                curr_c = det.bbox.center
                vx = (curr_c[0] - prev_c[0]) / dt
                vy = (curr_c[1] - prev_c[1]) / dt

                prev_track.last_bbox = det.bbox
                prev_track.last_timestamp = timestamp_sim
                prev_track.last_frame_id = frame_id
                prev_track.confidence = det.confidence
                prev_track.hits += 1
                prev_track.velocity = (vx, vy)
                prev_track.age = 0

                cost_matrix[t_idx, :] = -1.0
                cost_matrix[:, d_idx] = -1.0

        # Age unmatched tracks
        for i, tid in enumerate(active_track_ids):
            if i not in matched_tracks:
                self.tracks[tid].age += 1

        # Delete expired tracks
        expired = [tid for tid, trk in self.tracks.items() if trk.age > self.max_age]
        for tid in expired:
            del self.tracks[tid]

        # Create new tracks for unmatched detections
        for j, det in enumerate(cam_dets):
            if j not in matched_dets:
                self.track_counter += 1
                new_tid = f"TRACK_{self.track_counter:02d}"
                self.tracks[new_tid] = TrackState(
                    track_id=new_tid,
                    camera_id=self.camera_id,
                    junction_id=self.junction_id,
                    class_name=det.class_name,
                    last_bbox=det.bbox,
                    last_timestamp=timestamp_sim,
                    last_frame_id=frame_id,
                    confidence=det.confidence
                )

        return list(self.tracks.values())
