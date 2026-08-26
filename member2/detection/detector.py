from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import numpy as np

@dataclass
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    @property
    def width(self) -> float:
        return abs(self.x2 - self.x1)

    @property
    def height(self) -> float:
        return abs(self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    def to_list(self) -> List[float]:
        return [self.x1, self.y1, self.x2, self.y2]

@dataclass
class DetectionResult:
    camera_id: str
    junction_id: str
    frame_id: int
    timestamp_sim: float
    class_name: str
    confidence: float
    bbox: BoundingBox
    plate_crop: Optional[np.ndarray] = None

class BaseVehicleDetector:
    """Abstract base class for vehicle detection models."""
    def detect_vehicles(self, image: np.ndarray, camera_id: str, junction_id: str,
                        frame_id: int, timestamp_sim: float) -> List[DetectionResult]:
        raise NotImplementedError
