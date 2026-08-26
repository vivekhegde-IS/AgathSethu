import cv2
import numpy as np
from typing import List, Optional
from member2.camera.carla_camera import CameraFrame
from member2.tracking.tracker import TrackState

class VisionPipelineVisualizer:
    """Visualizes tracking bounding boxes, track IDs, vehicle identities, ANPR overlays, and collision alerts."""

    def render_frame(self, frame: CameraFrame, tracks: List[TrackState],
                     identities: Optional[dict] = None,
                     plates: Optional[dict] = None,
                     collision_pair: Optional[tuple] = None) -> np.ndarray:

        img = frame.image.copy()

        # Render collision banner if crash junction & pair present
        if collision_pair:
            t1, t2 = collision_pair
            banner_text = f"*** COLLISION PAIR IDENTIFIED: {t1} <-> {t2} ***"
            cv2.rectangle(img, (0, 45), (frame.image.shape[1], 85), (0, 0, 200), -1)
            cv2.putText(img, banner_text, (20, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

        # Draw tracked objects
        for trk in tracks:
            bbox = trk.last_bbox
            x1, y1, x2, y2 = int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)

            is_in_collision = collision_pair and (trk.track_id in collision_pair)
            box_color = (0, 0, 255) if is_in_collision else (0, 255, 0) # Red for collision pair, Green for normal

            cv2.rectangle(img, (x1, y1), (x2, y2), box_color, 2)

            # Label box text
            vid = identities.get(trk.track_id, trk.track_id) if identities else trk.track_id
            plate = plates.get(trk.track_id, "") if plates else ""

            label_parts = [f"{trk.class_name.upper()}", f"ID: {trk.track_id}"]
            if vid != trk.track_id:
                label_parts.append(f"VEH: {vid}")
            if plate:
                label_parts.append(f"PLATE: {plate}")

            label = " | ".join(label_parts)

            # Draw background text box
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(img, (x1, max(0, y1 - 22)), (x1 + tw + 10, max(22, y1)), box_color, -1)
            cv2.putText(img, label, (x1 + 5, max(15, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        return img
