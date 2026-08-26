import os
import yaml
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass
class CameraSpec:
    camera_id: str
    junction_id: str
    width: int = 1280
    height: int = 720
    fps: int = 15
    location: Optional[List[float]] = None

class CameraConfig:
    """Loads and manages camera configurations across junctions."""
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config", "cameras.yaml")
        self.cameras: Dict[str, CameraSpec] = {}
        self._load_config(config_path)

    def _load_config(self, path: str):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                for cam in data.get("cameras", []):
                    res = cam.get("resolution", {})
                    spec = CameraSpec(
                        camera_id=cam["camera_id"],
                        junction_id=cam["junction_id"],
                        width=res.get("width", 1280),
                        height=res.get("height", 720),
                        fps=cam.get("fps", 15),
                        location=cam.get("location")
                    )
                    self.cameras[spec.camera_id] = spec
        else:
            # Default fallback setup
            self.cameras["CAM_J01_01"] = CameraSpec("CAM_J01_01", "J01")
            self.cameras["CAM_J02_01"] = CameraSpec("CAM_J02_01", "J02")
            self.cameras["CAM_J03_01"] = CameraSpec("CAM_J03_01", "J03")
            self.cameras["CAM_J04_01"] = CameraSpec("CAM_J04_01", "J04")

    def get_camera(self, camera_id: str) -> Optional[CameraSpec]:
        return self.cameras.get(camera_id)

    def get_cameras_for_junction(self, junction_id: str) -> List[CameraSpec]:
        return [cam for cam in self.cameras.values() if cam.junction_id == junction_id]
