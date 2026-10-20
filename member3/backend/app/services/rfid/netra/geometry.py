"""Junction camera geometry: image box + depth -> ground position.

NETRA scores camera tracks on the ground plane. The backend does not know a
junction camera's world yaw, and does not need it: everything is expressed in
the CAMERA-LOCAL ground frame

    forward = metres along the camera heading (level, not pitched)
    lateral = metres to the camera's right

with the origin on the ground under the camera. The RFID reader sits at the
junction centre, which Member 1's ``camera_transform`` places ``back_m`` ahead
and ``lateral_m`` to the right of the camera (camera = centre - forward * back
- right * lateral). The read zone is radially symmetric, so the frame's
rotation is irrelevant to the association.

Inverse used at runtime: the ``depth_m`` CARLA sends is the camera-z of the
vehicle's transform location (on the ground under the vehicle centre); the box's
horizontal centre gives the bearing. With the ground constraint (height 0) that
fixes the point. Errors of ~0.5-1 m at 30 m are expected (box centre vs
projected vehicle centre) and absorbed by the learned read field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CameraGeometry:
    back_m: float                 # reader (junction centre) distance ahead of the camera
    lateral_m: float              # reader offset to the camera's right
    height_m: float = 5.0
    pitch_down_deg: float = 15.0
    fov_deg: float = 65.0
    width_px: int = 1280
    height_px: int = 720

    @property
    def focal(self) -> float:
        return self.width_px / (2.0 * math.tan(math.radians(self.fov_deg) / 2.0))

    @property
    def reader_xy(self) -> tuple[float, float]:
        return (self.back_m, self.lateral_m)

    # ---------------- runtime inverse ----------------

    def ground_from_box(self, bbox, depth_m: float) -> tuple[float, float] | None:
        """(forward, lateral) of the vehicle's ground point, or None."""
        if depth_m is None or not math.isfinite(depth_m) or depth_m <= 0.5:
            return None
        x1, _, x2, _ = (float(v) for v in bbox)
        px = 0.5 * (x1 + x2)
        theta = math.radians(self.pitch_down_deg)
        xc = (px - self.width_px / 2.0) * depth_m / self.focal
        # point on the ground: up = -z sin(theta) - y cos(theta) = -height
        yc = (self.height_m - depth_m * math.sin(theta)) / math.cos(theta)
        forward = depth_m * math.cos(theta) - yc * math.sin(theta)
        return (forward, xc)

    def ground_from_box_bottom(self, bbox) -> tuple[float, float] | None:
        """Image-only mapping (no depth): the ray through the box's bottom-centre
        pixel intersected with the ground. This is what a real camera with known
        intrinsics + extrinsics (or a road homography) gives. The bottom edge is
        the vehicle's nearest ground contact, so the point is biased towards the
        camera by up to about half a vehicle length."""
        x1, _, x2, y2 = (float(v) for v in bbox)
        theta = math.radians(self.pitch_down_deg)
        xc = (0.5 * (x1 + x2) - self.width_px / 2.0) / self.focal
        yc = (y2 - self.height_px / 2.0) / self.focal
        down = math.sin(theta) + yc * math.cos(theta)      # downward component of the ray
        if down <= 1e-6:
            return None                                    # at or above the horizon
        t = self.height_m / down
        return (t * (math.cos(theta) - yc * math.sin(theta)), t * xc)

    # ---------------- forward model (simulators / tests) ----------------

    def to_camera(self, forward, lateral, up=0.0) -> np.ndarray:
        """Camera coordinates (x right, y down, z optical axis) of ground-frame
        points; arrays broadcast. Returns (..., 3)."""
        theta = math.radians(self.pitch_down_deg)
        f = np.asarray(forward, float)
        l_ = np.asarray(lateral, float)
        u = np.asarray(up, float) - self.height_m
        z = f * math.cos(theta) - u * math.sin(theta)
        y = -f * math.sin(theta) - u * math.cos(theta)
        return np.stack(np.broadcast_arrays(l_, y, z), -1)

    def project_vehicle(self, forward: float, lateral: float, heading_rad: float,
                        length: float = 4.6, width: float = 1.9, height: float = 1.5,
                        min_box_px: int = 8, max_depth_m: float = 90.0):
        """Image box and depth of a vehicle centred at (forward, lateral), as
        Member 1's ``visible_vehicle_boxes`` would report it, or None when it is
        not in view. heading_rad is in the camera-local ground frame."""
        c, s = math.cos(heading_rad), math.sin(heading_rad)
        corners = []
        for dl in (-length / 2, length / 2):
            for dw in (-width / 2, width / 2):
                for dz in (0.0, height):
                    corners.append((forward + dl * c - dw * s, lateral + dl * s + dw * c, dz))
        pts = self.to_camera(*np.array(corners).T)
        centre = self.to_camera(forward, lateral, 0.0)
        depth = float(centre[2])
        if depth <= 0.5 or depth > max_depth_m or np.any(pts[:, 2] <= 0.1):
            return None
        px = self.focal * pts[:, 0] / pts[:, 2] + self.width_px / 2.0
        py = self.focal * pts[:, 1] / pts[:, 2] + self.height_px / 2.0
        x1, x2 = max(0, int(math.floor(px.min()))), min(self.width_px - 1, int(math.ceil(px.max())))
        y1, y2 = max(0, int(math.floor(py.min()))), min(self.height_px - 1, int(math.ceil(py.max())))
        if x2 - x1 < min_box_px or y2 - y1 < min_box_px:
            return None
        # mostly outside the frame: the projected centre must be in view
        cx = self.focal * float(centre[0]) / depth + self.width_px / 2.0
        cy = self.focal * float(centre[1]) / depth + self.height_px / 2.0
        if not (0 <= cx < self.width_px and 0 <= cy < self.height_px):
            return None
        return [x1, y1, x2, y2], depth


# Member 1's placement (full_run.py camera_transform): CAMERA_DISTANCE 25 m,
# J1 +10 m back, LATERAL_OFFSET {1: 6, 2: 6, 3: -8}, 5 m up, pitch -15, 65 deg.
JUNCTION_CAMERAS = {
    "J01": CameraGeometry(back_m=35.0, lateral_m=6.0),
    "J02": CameraGeometry(back_m=25.0, lateral_m=6.0),
    "J03": CameraGeometry(back_m=25.0, lateral_m=-8.0),
}


def camera_for(junction_id: str, overrides: dict | None = None) -> CameraGeometry:
    if overrides and junction_id in overrides:
        return overrides[junction_id]
    return JUNCTION_CAMERAS.get(junction_id, CameraGeometry(back_m=25.0, lateral_m=6.0))


def geometry_from_pose(pose: dict, reader_xy, ground_z: float = 0.0) -> CameraGeometry:
    """Exact geometry from a run's camera_poses.json entry (CARLA transform:
    x, y, z, pitch, yaw, fov, width, height) and the reader's world (x, y)
    from rfid_reader_positions.json. CARLA is left-handed: with yaw the
    forward vector is (cos, sin) and the right vector (-sin, cos)."""
    yaw = math.radians(float(pose["yaw"]))
    dx = float(reader_xy[0]) - float(pose["x"])
    dy = float(reader_xy[1]) - float(pose["y"])
    return CameraGeometry(
        back_m=dx * math.cos(yaw) + dy * math.sin(yaw),
        lateral_m=-dx * math.sin(yaw) + dy * math.cos(yaw),
        height_m=float(pose["z"]) - ground_z,
        pitch_down_deg=-float(pose.get("pitch", -15.0)),
        fov_deg=float(pose.get("fov", 65.0)),
        width_px=int(pose.get("width", 1280)),
        height_px=int(pose.get("height", 720)),
    )


def geometry_to_dict(geometry: CameraGeometry) -> dict:
    return {k: getattr(geometry, k) for k in CameraGeometry.__dataclass_fields__}
