"""Realistic number plates for the camera recordings (S9). Pure numpy / OpenCV, no CARLA.

The run script paints each plate onto the rendered frame (draw_projected_plate):
1.20 x 0.30 m, pure white, black outline, drawn on top of everything. That makes
plate reading look perfect in every weather. With NETRA_PLATE_REAL=1 the hooks
below make the painted plate behave like a real one:

  * size      plate_size_m()       -> 0.52 x 0.12 m (Indian standard car plate)
  * light     match_scene()        -> plate brightness follows the car body around it
                                      (dark at night unless lit, dimmer in rain), plus
                                      blur and sensor noise that grow in the dark / rain
  * occlusion visible_alpha()      -> plate pixels only where the vehicle itself is
                                      visible (instance segmentation), not over other cars
  * no outline draw_outline()      -> False (the extra black frame helped the detector)

Everything is off unless NETRA_PLATE_REAL=1, so old runs are reproduced unchanged.
Env: NETRA_PLATE_REAL=1, NETRA_PLATE_SEED (noise seed, default 0).
"""
from __future__ import annotations

import os

import cv2
import numpy as np

ENABLED = os.environ.get("NETRA_PLATE_REAL", "0") == "1"
REAL_W_M, REAL_H_M = 0.52, 0.12
_rng = np.random.default_rng(int(os.environ.get("NETRA_PLATE_SEED", "0")))


def plate_size_m(default_w: float, default_h: float) -> tuple[float, float]:
    """Plate width / height in metres used for the 3-D plate geometry."""
    return (REAL_W_M, REAL_H_M) if ENABLED else (default_w, default_h)


def draw_outline() -> bool:
    return not ENABLED


def _ring(mask: np.ndarray, px: int) -> np.ndarray:
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return (cv2.dilate(mask, k) > 0) & ~(mask > 0)


def match_scene(frame: np.ndarray, warped: np.ndarray, mask: np.ndarray,
                rain: float = 0.0) -> np.ndarray:
    """Return the warped plate image re-lit and degraded to match the frame.

    frame  : the rendered camera frame BEFORE the plate is pasted (H x W x 3, uint8)
    warped : the perspective-warped plate (same size as frame)
    mask   : the warped plate mask (H x W, 0..255)
    rain   : 0..1, e.g. the CARLA weather precipitation / 100
    """
    if not ENABLED:
        return warped
    m = mask > 0
    if not m.any():
        return warped
    ys, xs = np.nonzero(m)
    plate_h = max(1, int(ys.max() - ys.min() + 1))
    ring = _ring(mask, max(3, plate_h))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    around = gray[ring] if ring.any() else gray[m]
    # A white, retro-reflective plate is brighter than the car body around it,
    # but it cannot be brighter than the light falling on that part of the car.
    lum = float(np.percentile(around, 75)) / 255.0
    gain = float(np.clip(1.8 * lum, 0.06, 1.0)) * (1.0 - 0.25 * float(np.clip(rain, 0, 1)))
    out = warped.astype(np.float32) * gain
    # Blur: optics + motion, more in rain; small plates lose detail first.
    sigma = 0.6 + 1.2 * float(np.clip(rain, 0, 1))
    out = cv2.GaussianBlur(out, (0, 0), sigma)
    # Sensor noise grows when the scene is dark.
    noise_sd = 2.0 + 10.0 * (1.0 - gain)
    out = out + _rng.normal(0.0, noise_sd, out.shape).astype(np.float32)
    return np.clip(out, 0, 255).astype(np.uint8)


def visible_alpha(mask: np.ndarray, instance_ids: np.ndarray | None, actor_id: int | None) -> np.ndarray:
    """Plate alpha (H x W x 1, 0..1) restricted to pixels where this vehicle is visible.

    instance_ids : per-pixel actor id from the instance-segmentation camera
                   (netra_sensor_upgrades.instance_ids), or None to skip the check
    """
    alpha = mask.astype(np.float32) / 255.0
    if ENABLED and instance_ids is not None and actor_id is not None:
        alpha = alpha * (instance_ids == int(actor_id))
    return alpha[..., None]
