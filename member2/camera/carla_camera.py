import time
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Optional, Dict, Any, Generator
from member2.camera.camera_config import CameraSpec

@dataclass
class CameraFrame:
    camera_id: str
    junction_id: str
    frame_id: int
    timestamp_sim: float
    image: np.ndarray  # BGR numpy image array

class CarlaCameraManager:
    """Manages multi-junction cameras for CARLA simulation or DEMO mode stream generation."""

    def __init__(self, camera_spec: CameraSpec, is_demo_mode: bool = True):
        self.spec = camera_spec
        self.is_demo_mode = is_demo_mode
        self.frame_count = 0
        self.carla_sensor = None
        self.latest_frame: Optional[CameraFrame] = None

    def attach_carla_sensor(self, world, vehicle_actor):
        """Attaches a CARLA RGB camera sensor to a vehicle or map location if CARLA is running."""
        try:
            import carla
            bp_lib = world.get_blueprint_library()
            cam_bp = bp_lib.find('sensor.camera.rgb')
            cam_bp.set_attribute('image_size_x', str(self.spec.width))
            cam_bp.set_attribute('image_size_y', str(self.spec.height))
            cam_bp.set_attribute('fov', '90')

            transform = carla.Transform(carla.Location(x=0, y=0, z=2.5))
            self.carla_sensor = world.spawn_actor(cam_bp, transform, attach_to=vehicle_actor)

            def _on_carla_image(image):
                array = np.frombuffer(image.raw_data, dtype=np.dtype("uint8"))
                array = np.reshape(array, (image.height, image.width, 4))
                bgr = array[:, :, :3]
                self.frame_count += 1
                self.latest_frame = CameraFrame(
                    camera_id=self.spec.camera_id,
                    junction_id=self.spec.junction_id,
                    frame_id=self.frame_count,
                    timestamp_sim=image.timestamp,
                    image=bgr
                )

            self.carla_sensor.listen(_on_carla_image)
        except Exception as e:
            print(f"[Member2 Camera] CARLA sensor attach fallback (Demo mode enabled): {e}")
            self.is_demo_mode = True

    def generate_synthetic_frame(self, timestamp_sim: float, vehicles: Optional[list] = None) -> CameraFrame:
        """Generates a high-quality synthetic camera frame with rendered vehicles for DEMO MODE."""
        self.frame_count += 1
        img = np.zeros((self.spec.height, self.spec.width, 3), dtype=np.uint8)

        # Draw junction environment
        # Road asphalt background
        cv2.rectangle(img, (0, 0), (self.spec.width, self.spec.height), (40, 40, 40), -1)
        # Road lane markings
        cv2.line(img, (0, self.spec.height // 2), (self.spec.width, self.spec.height // 2), (255, 255, 255), 3)
        cv2.line(img, (self.spec.width // 2, 0), (self.spec.width // 2, self.spec.height), (255, 255, 255), 3)

        # Header overlay
        cv2.rectangle(img, (0, 0), (self.spec.width, 40), (20, 20, 20), -1)
        cv2.putText(img, f"CAM: {self.spec.camera_id} | JUNCTION: {self.spec.junction_id} | SIM TIME: {timestamp_sim:.2f}s | FRAME: {self.frame_count}",
                    (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Draw vehicle bounding representations if provided
        if vehicles:
            for v in vehicles:
                x1, y1, x2, y2 = v.get("bbox", [100, 100, 200, 160])
                color = v.get("color", (0, 165, 255))  # Orange/Blue default
                label = v.get("label", "CAR")
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                cv2.rectangle(img, (x1, y1 - 20), (x1 + 100, y1), color, -1)
                cv2.putText(img, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        self.latest_frame = CameraFrame(
            camera_id=self.spec.camera_id,
            junction_id=self.spec.junction_id,
            frame_id=self.frame_count,
            timestamp_sim=timestamp_sim,
            image=img
        )
        return self.latest_frame
