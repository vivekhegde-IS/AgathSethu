"""NETRA data-collection upgrades for the CARLA script (Member 1 side).

Drop this file next to netra_full_run.py and add the few calls described in
NETRA_MEMBER1_GUIDE.md. Nothing here changes driving, physics, crash detection or
the existing messages; every feature is switched by an environment variable and
is OFF unless set.

    NETRA_BOX_LOG=1          per-tick vehicle box log  -> vehicle_boxes.csv (lossless)
                             + one "vehicle_boxes" message per camera per tick
                               (20 Hz, separate from the throttled camera_frame JPEGs)
    NETRA_FRAME_INDEX=1      camera_frames_index.csv: which CARLA frame / sim time is
                             each frame written to the MP4 recordings
    NETRA_VISIBILITY=1       visible fraction per box from an instance-segmentation
                             camera co-located with each junction camera (occlusion labels)
    NETRA_WEATHER=<preset>   CARLA weather preset, e.g. ClearNoon, HardRainNoon,
                             ClearNight, WetCloudySunset (logged in netra_conditions.json)

Pure Python except where a function receives CARLA objects; importing this module
does not import carla.
"""
from __future__ import annotations

import csv
import json
import os
import threading

import numpy as np


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


BOX_LOG = _flag("NETRA_BOX_LOG")
FRAME_INDEX = _flag("NETRA_FRAME_INDEX")
VISIBILITY = _flag("NETRA_VISIBILITY")
WEATHER = os.environ.get("NETRA_WEATHER", "").strip()


# ---------------------------------------------------------------------------
# 1. Box log + 20 Hz box messages
# ---------------------------------------------------------------------------
class BoxLogger:
    """Call ``log(timestamp, frame, junction_number, boxes)`` once per world tick per
    junction camera, with the list ``visible_vehicle_boxes(...)`` already returns
    ([{vehicle_id, bbox, depth_m}, ...]; an optional "visible_fraction" is kept).

    Writes every box to vehicle_boxes.csv (never dropped) and, if a publisher is
    given, sends {"type": "vehicle_boxes", ...} through ``publisher.publish``.
    Make sure publish() routes "vehicle_boxes" to the reliable queue (see guide).
    """

    FIELDS = ["timestamp_sim", "frame", "junction_id", "camera_id", "vehicle_id",
              "x1", "y1", "x2", "y2", "depth_m", "visible_fraction"]

    def __init__(self, out_dir: str, publisher=None):
        self.enabled = BOX_LOG
        self.publisher = publisher
        self._lock = threading.Lock()
        self._fh = None
        if self.enabled:
            os.makedirs(out_dir, exist_ok=True)
            self._fh = open(os.path.join(out_dir, "vehicle_boxes.csv"), "w", newline="", encoding="utf-8")
            self._w = csv.DictWriter(self._fh, fieldnames=self.FIELDS)
            self._w.writeheader()
            print("[NETRA] box log ON: vehicle_boxes.csv + 20 Hz vehicle_boxes messages", flush=True)

    def log(self, timestamp_sim: float, frame: int, junction_number: int, boxes: list) -> None:
        if not self.enabled:
            return
        jid, cam = f"J{int(junction_number):02d}", f"CAM_J{int(junction_number):02d}_01"
        with self._lock:
            for b in boxes or []:
                x1, y1, x2, y2 = b["bbox"]
                self._w.writerow({"timestamp_sim": f"{timestamp_sim:.6f}", "frame": int(frame), "junction_id": jid,
                                  "camera_id": cam, "vehicle_id": b["vehicle_id"], "x1": x1, "y1": y1,
                                  "x2": x2, "y2": y2, "depth_m": b.get("depth_m"),
                                  "visible_fraction": b.get("visible_fraction")})
            self._fh.flush()
        if self.publisher is not None:
            self.publisher.publish({"type": "vehicle_boxes", "timestamp_sim": float(timestamp_sim),
                                    "frame": int(frame), "junction_id": jid, "camera_id": cam,
                                    "vehicles": boxes or []})

    def close(self) -> None:
        if self._fh:
            self._fh.close()


# ---------------------------------------------------------------------------
# 2. Frame index for the MP4 recordings
# ---------------------------------------------------------------------------
class FrameIndex:
    """Call ``log(junction_number, carla_frame, timestamp_sim)`` right where a frame is
    handed to the junction's MP4 writer. Row k of a junction = video frame k."""

    def __init__(self, out_dir: str):
        self.enabled = FRAME_INDEX
        self._n = {}
        self._fh = None
        if self.enabled:
            os.makedirs(out_dir, exist_ok=True)
            self._fh = open(os.path.join(out_dir, "camera_frames_index.csv"), "w", newline="", encoding="utf-8")
            self._w = csv.writer(self._fh)
            self._w.writerow(["junction_id", "video_frame_index", "carla_frame", "timestamp_sim"])
            print("[NETRA] frame index ON: camera_frames_index.csv", flush=True)

    def log(self, junction_number: int, carla_frame: int, timestamp_sim: float) -> None:
        if not self.enabled:
            return
        k = self._n.get(junction_number, 0)
        self._n[junction_number] = k + 1
        self._w.writerow([f"J{int(junction_number):02d}", k, int(carla_frame), f"{timestamp_sim:.6f}"])
        self._fh.flush()

    def close(self) -> None:
        if self._fh:
            self._fh.close()


# ---------------------------------------------------------------------------
# 3. Occlusion labels from an instance-segmentation camera
# ---------------------------------------------------------------------------
def spawn_instance_camera(world, rgb_transform, width=1280, height=720, fov=65.0, sensor_tick=None):
    """Instance-segmentation camera at the SAME transform as a junction RGB camera.
    Needs CARLA >= 0.9.14 ("sensor.camera.instance_segmentation"). Returns the actor,
    or None (with a message) if the blueprint does not exist."""
    lib = world.get_blueprint_library()
    try:
        bp = lib.find("sensor.camera.instance_segmentation")
    except (IndexError, RuntimeError):
        print("[NETRA] instance segmentation camera not available in this CARLA version", flush=True)
        return None
    bp.set_attribute("image_size_x", str(width))
    bp.set_attribute("image_size_y", str(height))
    bp.set_attribute("fov", str(fov))
    if sensor_tick is not None:
        bp.set_attribute("sensor_tick", str(sensor_tick))
    return world.spawn_actor(bp, rgb_transform)


def instance_ids(image) -> np.ndarray:
    """CARLA instance image -> per-pixel actor id (16 bits from G and B; R is the
    semantic tag). image: carla.Image from the instance camera."""
    a = np.frombuffer(image.raw_data, dtype=np.uint8).reshape((image.height, image.width, 4))
    # BGRA layout: B = a[...,0], G = a[...,1]
    return a[..., 1].astype(np.int32) + (a[..., 0].astype(np.int32) << 8)


def add_visible_fraction(boxes: list, ids: np.ndarray, actor_id_of: dict) -> list:
    """Adds "visible_fraction" to each box: share of the box's pixels that belong to
    that vehicle (0 = fully hidden, ~0.6-0.9 = unoccluded; the box also covers road).
    Also adds "visible_pixels". actor_id_of: vehicle name -> carla actor id."""
    out = []
    for b in boxes:
        x1, y1, x2, y2 = (int(v) for v in b["bbox"])
        patch = ids[max(0, y1):y2 + 1, max(0, x1):x2 + 1]
        aid = actor_id_of.get(b["vehicle_id"])
        mine = int((patch == (aid & 0xFFFF)).sum()) if aid is not None and patch.size else 0
        out.append(dict(b, visible_fraction=round(mine / max(patch.size, 1), 4), visible_pixels=mine))
    return out


# ---------------------------------------------------------------------------
# 4. Weather + condition log
# ---------------------------------------------------------------------------
def apply_weather(world, carla_module) -> str | None:
    """Set NETRA_WEATHER (a carla.WeatherParameters preset name). Returns the name used."""
    if not WEATHER:
        return None
    preset = getattr(carla_module.WeatherParameters, WEATHER, None)
    if preset is None:
        print(f"[NETRA] unknown weather preset {WEATHER!r}; weather unchanged", flush=True)
        return None
    world.set_weather(preset)
    print(f"[NETRA] weather = {WEATHER}", flush=True)
    return WEATHER


def write_conditions(out_dir: str, extra: dict | None = None) -> None:
    """netra_conditions.json: every NETRA_* / RFID_* variable and anything in extra."""
    os.makedirs(out_dir, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k.startswith(("NETRA_", "RFID_", "STREAM_"))}
    with open(os.path.join(out_dir, "netra_conditions.json"), "w", encoding="utf-8") as fh:
        json.dump({"env": env, **(extra or {})}, fh, indent=2, default=str)
