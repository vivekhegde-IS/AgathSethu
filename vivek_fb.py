#!/usr/bin/env python3
"""
CARLA 0.9.16 - 3-junction multimodal live evidence pipeline with plate overlays.

V22 changes: fitted high-resolution borderless ANPR text and non-blocking J2/J3 post-crash B motion; secondary traffic C-H is controlled by CARLA Traffic Manager with fixed paths, collision avoidance, and lane-change disabled. A/B remain manual for the intended collision.
Plate geometry and projection remain free of per-frame CARLA bounding-box calls.

This version keeps the validated scenario/physics and focuses only on live evidence acquisition and delivery.

Goals
-----
1. A and B must physically collide at Junction 1 using normal CARLA vehicle physics.
2. A is stopped only after the collision is reported by sensor.other.collision.
3. B then follows a topology-validated route through Junction 2 and Junction 3,
   and continues beyond Junction 3.
4. C crosses J1 after the A/B incident clears.
5. D/E/F cross J2 sequentially.
6. G/H cross J3 sequentially.
7. Cameras use the exact road-relative placement from the user's working script and all three junction feeds are continuously acquired.
8. Each vehicle receives a fixed simulated Indian-style registration plate with a different state code,
   rendered as a camera-space overlay using the actor's projected 3D bounding box.
9. No hard-coded vehicle model IDs; only blueprints actually present in the
   connected CARLA server are used.
10. This module does not implement camera vehicle detection, tracking, trajectory generation, or ANPR inference; those are owned by other project members.
11. No Traffic Manager is used for A/B or the remaining vehicles. This prevents
   TM collision avoidance from fighting the intended collision and keeps all
   motion under this script's control.

The script validates the road topology before the scenario starts and prints
explicit route diagnostics. If a required topology chain cannot be found, the
script fails before the vehicles begin moving instead of running a broken scene.
"""

import math
import os
import random
import sys
import threading
import time

import threading
import queue
import cv2
import numpy as np
import faulthandler
import traceback
import csv
import json
import joblib
from collections import deque

# CARLA API basis: CARLA 0.9.16 documentation.
# See: https://carla.readthedocs.io/en/0.9.16/tuto_G_bounding_boxes/
# and https://carla.readthedocs.io/en/0.9.16/core_sensors/

sys.path.insert(0, r"d:\FINAL_PROJECT\PythonAPI\carla")
import carla
from agents.navigation.global_route_planner import GlobalRoutePlanner

faulthandler.enable()

HOST = "127.0.0.1"
PORT = 2000
MAP_NAME = "Town10HD_Opt"
OUT_DIR = r"d:\FINAL_PROJECT\debug_frames"
DT = 0.05
FPS = 20.0
TIMEOUT = 180.0

# ---------------------------------------------------------------------------
# MULTIMODAL LIVE EVIDENCE
# ---------------------------------------------------------------------------
# Sensor/model rates are independent of the 20 Hz CARLA world tick.
IMU_SAMPLING_RATE = 200
IMU_SENSOR_TICK = 0.005
GNSS_SENSOR_TICK = 0.05

# IMU startup stabilization. Raw samples are still logged, but model inference
# is disabled until the sensor has produced a stable stream. This prevents the
# large first-buffer transients seen in the previous recordings from becoming
# crash candidates.
IMU_WARMUP_SECONDS = 1.5

# Inference-only plausibility guard. Raw IMU is never modified or discarded
# from the evidence logs. Windows containing physically implausible transient
# spikes are rejected before ML inference.
IMU_MAX_PLAUSIBLE_G = 50.0
IMU_MAX_PLAUSIBLE_GYRO_DEG_S = 2000.0

# GPS collision-association configuration. GPS is supporting evidence, not
# ground truth. Pair confirmation requires proximity and relative motion.
# Final-validation association policy. IMU is the first gate; GPS is only corroboration.
# A vehicle pair is never confirmed from proximity alone.
GPS_PAIR_MAX_DISTANCE_M = 4.5
GPS_PAIR_NEAR_DISTANCE_M = 3.5
GPS_PAIR_TIME_TOLERANCE_S = 0.60
GPS_APPROACH_LOOKBACK_S = 1.25
GPS_POST_IMPACT_LOOKAHEAD_S = 0.60
GPS_MIN_RELATIVE_SPEED_KMH = 12.0
GPS_MIN_APPROACH_CLOSING_M = 1.25
GPS_MIN_POST_SEPARATION_M = 0.75
GPS_MIN_PRE_EVENT_SPEED_KMH = 6.0
GPS_PAIR_CONFIRMATION_SCORE = 5
GPS_PAIR_EVENT_COOLDOWN_S = 1.5
CRASH_CANDIDATE_MIN_PROB = 0.35
CRASH_CANDIDATE_HIGH_PROB = 0.50
CRASH_CONFIRMATION_COOLDOWN_S = 3.0

# Refined multimodal collision fusion.
# A collision candidate must originate from IMU.  GPS then finds a physically
# compatible partner.  For normal-confidence candidates, the partner must
# also show crash-like IMU dynamics in the same short temporal neighborhood.
# This rejects the previous false B-F/D-F style associations where the
# "partner" was stationary and had no impact-like IMU evidence.
IMU_PARTNER_LOOKBACK_S = 0.75
IMU_PARTNER_LOOKAHEAD_S = 0.75
IMU_PARTNER_MIN_PROB = 0.20
IMU_IMPACT_G_MIN = 1.50
IMU_IMPACT_JERK_MIN = 1.00
IMU_IMPACT_ROTATIONAL_MIN = 10.0
IMU_IMPACT_SPEED_CHANGE_MIN_KMH = 5.0
GPS_COLLISION_DISTANCE_M = 3.5
GPS_PRIMARY_PRE_SPEED_MIN_KMH = 6.0
GPS_PARTNER_PRE_SPEED_MIN_KMH = 1.0
GPS_RELATIVE_SPEED_COLLISION_MIN_KMH = 8.0
GPS_CLOSING_COLLISION_MIN_M = 0.50
# A single-IMU fallback is intentionally much stricter.  It is useful when a
# real collision is only visible in one IMU, but ordinary proximity cannot
# satisfy it.
SINGLE_IMU_HIGH_PROB = 0.60
SINGLE_IMU_MAX_DISTANCE_M = 2.75
SINGLE_IMU_MIN_RELATIVE_SPEED_KMH = 15.0
SINGLE_IMU_MIN_CLOSING_M = 1.0

# Simulated RFID readers at the three monitored junctions.
RFID_READ_RADIUS_M = 18.0
RFID_MIN_READ_INTERVAL_S = 0.25
RFID_READ_PROBABILITY = 0.98

# Live backend:
# Set this to your Member-3 FastAPI WebSocket endpoint when ready.
# Example:
#   ws://127.0.0.1:8000/ws/evidence
LIVE_WS_URL = os.environ.get(
    "CARLA_EVIDENCE_WS",
    "ws://100.118.103.8:8001/ws/carla/cameras",
).strip()
LIVE_JPEG_QUALITY = 82
LIVE_WS_QUEUE_MAX = 80

# Crash alert delivery. Alerts travel on their OWN WebSocket connection and
# thread, so they never wait behind 1280x720 camera frames and never share a
# drop-oldest queue with high-rate IMU/GPS evidence. Each alert is resent
# until the backend replies {"type": "crash_alert_ack"} for its alert_id.
ALERT_ACK_TIMEOUT_S = 2.0
ALERT_RETRY_MIN_S = 0.25
ALERT_RETRY_MAX_S = 5.0
# How long close() keeps retrying undelivered alerts before giving up.
ALERT_CLOSE_GRACE_S = 15.0

# Live streaming bandwidth tuning.
#
# ANPR PRESERVATION: the number-plate detection model runs on the SAME
# frames that are streamed live (draw_all_number_plates output). Plates are
# ~0.95 m wide seen from 25-35 m at 65 deg FOV -> only ~32 px of plate width
# at native 1280. Any downscale directly shrinks the glyphs the ANPR model
# must read, and low JPEG quality adds blocking artifacts on small text.
# Therefore the live stream is NOT downscaled (native 1280x720) and JPEG
# quality stays high; smoothness is bought with framerate instead.
#
# The saved MP4s are always FULL-resolution and were never touched.
LIVE_STREAM_TARGET_WIDTH = 0        # 0 = keep native 1280x720 (no resize)
LIVE_STREAM_JPEG_QUALITY = 75       # high enough for small plate glyphs
LIVE_STREAM_MIN_INTERVAL_S = 0.20   # 5 FPS/cam, 15 FPS total ~= 1.6 MB/s (13 Mbps)


# Files are written continuously so every sensor observation can be verified.
MULTIMODAL_OUT_DIR = os.path.join(OUT_DIR, "multimodal_evidence")

# User-validated camera geometry.
CAMERA_HEIGHT = 5.0
CAMERA_DISTANCE = 25.0
LATERAL_OFFSET = {1: 6.0, 2: 6.0, 3: -8.0}
CAMERA_FOV = 65.0

# ACTUAL CAMERA OFFSETS:
# J1 previous 39 m back, moved 4 m forward = 35 m back.
# J3 previous 10 m right, moved 2 m left = 8 m right from original.
# These move ONLY the cameras; junctions, vehicles, routes, and physics
# remain unchanged.
J1_CAMERA_BACK_OFFSET_M = 10.0

# ANPR plate tuning: moderate physical enlargement, not a screen-sized label.
# ---------------------------------------------------------------------------
# Visible/ANPR plate tuning
# ---------------------------------------------------------------------------
# The plate is intentionally enlarged relative to a physically exact
# registration plate so that it remains readable in the 1280x720 camera
# images at the existing ~25 m camera distance.
#
# This changes ONLY the visual overlay. It does NOT change the CARLA vehicle,
# collision, route, junction, or physics model.
ANPR_PLATE_CANVAS_HEIGHT = 600
ANPR_PLATE_CANVAS_WIDTH = 2400
ANPR_PLATE_BORDER = 0
ANPR_PLATE_WIDTH_M = 0.95
ANPR_PLATE_HEIGHT_M = 0.24
ANPR_TEXT_WIDTH_FRACTION = 0.90
ANPR_TEXT_HEIGHT_FRACTION = 0.78
ANPR_TEXT_RENDER_SCALE = 4.0

# Minimum projected footprint at which an overlay is rendered.  Keeping this
# threshold modest prevents tiny, distorted plates from being pasted into
# distant pixels while allowing useful ANPR-sized plates to remain visible.
ANPR_MIN_PLATE_PIXEL_WIDTH = 18.0
ANPR_MIN_PLATE_PIXEL_HEIGHT = 6.0

JUNCTIONS = {
    1: {"id": 189, "location": carla.Location(x=-28.7, y=28.1, z=0.0)},
    2: {"id": 895, "location": carla.Location(x=-41.6, y=82.6, z=0.0)},
    3: {"id": 468, "location": carla.Location(x=-71.3, y=132.3, z=0.0)},
}

VEHICLE_IDS = tuple("ABCDEFGH")

# Fixed simulated registration numbers. These are visual overlays for the
# project demonstration; they are not intended to represent real vehicles.
# Diverse simulated Indian registration marks. State/RTO/series/number are
# intentionally synthetic for the simulation; they are not assigned to real vehicles.
# State codes follow official MoRTH registration-mark conventions.
PLATE_NUMBERS = {
    "A": "KA 01 AT 4521",  # Karnataka
    "B": "MH 12 BR 7814",  # Maharashtra
    "C": "TN 09 CK 2365",  # Tamil Nadu
    "D": "KL 07 DL 9182",  # Kerala
    "E": "DL 03 EN 6047",  # Delhi
    "F": "GJ 05 FP 3419",  # Gujarat
    "G": "AP 16 GQ 8273",  # Andhra Pradesh
    "H": "TG 08 HR 5196",  # Telangana (TG; changed from TS in 2024)
}






PLATE_STATE_NAMES = {
    "A": "KARNATAKA",
    "B": "MAHARASHTRA",
    "C": "TAMIL NADU",
    "D": "KERALA",
    "E": "DELHI",
    "F": "GUJARAT",
    "G": "ANDHRA PRADESH",
    "H": "TELANGANA",
}

PREFERRED_VEHICLE_KEYWORDS = (
    "tesla", "audi", "bmw", "chevrolet", "mercedes", "lincoln",
    "volkswagen", "nissan", "ford", "jeep", "mini", "seat",
)
EXCLUDED_VEHICLE_KEYWORDS = (
    "truck", "bus", "van", "ambulance", "firetruck", "police",
    "motorcycle", "bike", "quad", "cybertruck",
)


def hdist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def speed_mps(vehicle):
    v = vehicle.get_velocity()
    return math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


def speed_kmh(vehicle):
    return speed_mps(vehicle) * 3.6


def wrap_angle(deg):
    return (deg + 180.0) % 360.0 - 180.0


def waypoint_key(wp):
    return (wp.road_id, wp.section_id, wp.lane_id, round(wp.s, 1))


def unique_locations(points, min_distance=0.8):
    result = []
    for p in points:
        if not result or hdist(result[-1].location, p.location) > min_distance:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def camera_transform(world, junction_num, junction_location):
    """Exact camera placement from the user's validated camera script."""
    waypoint = world.get_map().get_waypoint(junction_location, project_to_road=True)
    if waypoint is None:
        road_center = junction_location
        forward = carla.Vector3D(x=1.0, y=0.0, z=0.0)
        right = carla.Vector3D(x=0.0, y=1.0, z=0.0)
    else:
        road_center = waypoint.transform.location
        forward = waypoint.transform.get_forward_vector()
        right = waypoint.transform.get_right_vector()

    lateral = LATERAL_OFFSET[junction_num]

    # Physical camera placement:
    # J1 = 25 m + 10 m = 35 m back.
    # J2 = unchanged at 25 m.
    # J3 uses the configured -8 m right-vector lateral offset.
    # The road/junction geometry itself is untouched.
    back_distance = CAMERA_DISTANCE
    if junction_num == 1:
        back_distance += J1_CAMERA_BACK_OFFSET_M

    camera_x = road_center.x - forward.x * back_distance - right.x * lateral
    camera_y = road_center.y - forward.y * back_distance - right.y * lateral
    yaw = math.degrees(math.atan2(forward.y, forward.x))
    return carla.Transform(
        carla.Location(x=camera_x, y=camera_y, z=CAMERA_HEIGHT),
        carla.Rotation(pitch=-15.0, yaw=yaw, roll=0.0),
    )


# ---------------------------------------------------------------------------
# Number-plate overlays
# ---------------------------------------------------------------------------

def rotation_matrix_from_values(pitch_deg, yaw_deg, roll_deg):
    """Pure-Python/NumPy equivalent of CARLA/Unreal transform rotation."""
    p = math.radians(pitch_deg)
    y = math.radians(yaw_deg)
    r = math.radians(roll_deg)
    c_y, s_y = math.cos(y), math.sin(y)
    c_p, s_p = math.cos(p), math.sin(p)
    c_r, s_r = math.cos(r), math.sin(r)
    return np.array([
        [c_y * c_p, c_y * s_p * s_r - s_y * c_r, -c_y * s_p * c_r - s_y * s_r],
        [s_y * c_p, s_y * s_p * s_r + c_y * c_r, -s_y * s_p * c_r + c_y * s_r],
        [s_p,        -c_p * s_r,                       c_p * c_r],
    ], dtype=np.float64)


def rigid_matrix(location_xyz, rotation_pyr):
    """Build a 4x4 local->world rigid transform without calling libcarla."""
    m = np.eye(4, dtype=np.float64)
    m[:3, :3] = rotation_matrix_from_values(*rotation_pyr)
    m[:3, 3] = np.asarray(location_xyz, dtype=np.float64)
    return m


def inverse_rigid_matrix(m):
    """Inverse for a rigid transform."""
    r = m[:3, :3]
    t = m[:3, 3]
    inv = np.eye(4, dtype=np.float64)
    rt = r.T
    inv[:3, :3] = rt
    inv[:3, 3] = -rt.dot(t)
    return inv


def build_camera_model(camera_transform, width=1280, height=720, fov=65.0):
    """Precompute fixed camera matrices once; no CARLA calls are needed per frame."""
    focal = width / (2.0 * math.tan(math.radians(fov) / 2.0))
    K = np.array([
        [focal, 0.0, width / 2.0],
        [0.0, focal, height / 2.0],
        [0.0, 0.0, 1.0],
    ], dtype=np.float64)
    t = camera_transform
    M = rigid_matrix(
        (t.location.x, t.location.y, t.location.z),
        (t.rotation.pitch, t.rotation.yaw, t.rotation.roll),
    )
    return {"K": K, "world_to_camera": inverse_rigid_matrix(M), "width": width, "height": height}


def cache_vehicle_bbox_geometry(vehicle):
    """Read bbox scalars ONCE at spawn time, then never query vehicle.bounding_box again."""
    bb = vehicle.bounding_box
    center = (float(bb.location.x), float(bb.location.y), float(bb.location.z))
    extent = (float(bb.extent.x), float(bb.extent.y), float(bb.extent.z))
    rotation = (float(bb.rotation.pitch), float(bb.rotation.yaw), float(bb.rotation.roll))

    # 8 bbox corners in bbox-local coordinates.
    corners = []
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                corners.append([sx * extent[0], sy * extent[1], sz * extent[2], 1.0])
    local_bbox_transform = rigid_matrix(center, rotation)
    local_corners = np.asarray(corners, dtype=np.float64).T
    return {
        "local_vertices": local_bbox_transform.dot(local_corners),
        "center": center,
        "extent": extent,
    }


def transform_tuple(transform):
    """Copy a CARLA transform into plain Python scalars."""
    return (
        float(transform.location.x),
        float(transform.location.y),
        float(transform.location.z),
        float(transform.rotation.pitch),
        float(transform.rotation.yaw),
        float(transform.rotation.roll),
    )


def project_world_xyz(world_xyz, camera_model):
    """Project a plain XYZ world point using precomputed matrices."""
    x, y, z = world_xyz
    world_h = np.array([x, y, z, 1.0], dtype=np.float64)
    cam = camera_model["world_to_camera"].dot(world_h)

    # CARLA/Unreal camera coordinates -> standard camera coordinates.
    point = np.array([cam[1], -cam[2], cam[0]], dtype=np.float64)
    depth = float(point[2])
    if depth <= 0.10:
        return None
    img = camera_model["K"].dot(point)
    px = float(img[0] / depth)
    py = float(img[1] / depth)
    if not (math.isfinite(px) and math.isfinite(py)):
        return None
    return px, py, depth


def vehicle_image_bbox_from_snapshot(transform_values, bbox_geometry, camera_model):
    """Pure NumPy 3-D bbox projection; does not call any CARLA bbox API."""
    x, y, z, pitch, yaw, roll = transform_values
    actor_m = rigid_matrix((x, y, z), (pitch, yaw, roll))
    world_vertices = actor_m.dot(bbox_geometry["local_vertices"])

    projected = []
    for i in range(world_vertices.shape[1]):
        p = project_world_xyz(world_vertices[:3, i], camera_model)
        if p is not None:
            projected.append(p)

    if len(projected) < 2:
        return None

    width = camera_model["width"]
    height = camera_model["height"]
    xs = [p[0] for p in projected]
    ys = [p[1] for p in projected]
    min_x = max(0, int(math.floor(min(xs))))
    max_x = min(width - 1, int(math.ceil(max(xs))))
    min_y = max(0, int(math.floor(min(ys))))
    max_y = min(height - 1, int(math.ceil(max(ys))))

    if max_x < 0 or min_x >= width or max_y < 0 or min_y >= height:
        return None
    if max_x - min_x < 8 or max_y - min_y < 8:
        return None
    return min_x, min_y, max_x, max_y


def project_local_points(actor_transform_values, local_points, camera_model):
    """Project vehicle-local 3-D points using cached actor transform values."""
    x, y, z, pitch, yaw, roll = actor_transform_values
    actor_m = rigid_matrix((x, y, z), (pitch, yaw, roll))
    local_h = np.asarray(local_points, dtype=np.float64)
    if local_h.ndim == 1:
        local_h = local_h.reshape(1, -1)
    world_h = actor_m.dot(local_h.T)
    projected = []
    for i in range(world_h.shape[1]):
        p = project_world_xyz(world_h[:3, i], camera_model)
        if p is None:
            return None
        projected.append(p)
    return projected


def polygon_area(points):
    """Absolute area of a 2-D polygon."""
    if len(points) < 3:
        return 0.0
    area = 0.0
    for i in range(len(points)):
        x1, y1 = points[i][:2]
        x2, y2 = points[(i + 1) % len(points)][:2]
        area += x1 * y2 - x2 * y1
    return abs(area) * 0.5


def make_3d_plate_candidates(bbox_geometry):
    """Create enlarged front/rear plate planes in vehicle-local space.

    CARLA BoundingBox geometry is read once at spawn time. The plate is then
    projected from cached vehicle-local coordinates into the camera image.
    This follows the CARLA 0.9.16 actor/bounding-box coordinate model while
    keeping the expensive geometry lookup out of the per-frame path.
    """
    local_vertices = bbox_geometry["local_vertices"][:3, :]
    x_min, x_max = float(local_vertices[0].min()), float(local_vertices[0].max())
    y_min, y_max = float(local_vertices[1].min()), float(local_vertices[1].max())
    z_min, z_max = float(local_vertices[2].min()), float(local_vertices[2].max())

    vehicle_width = max(0.8, y_max - y_min)

    # Enlarged visual plate. It is capped relative to vehicle width so it
    # remains attached to the vehicle instead of becoming a screen label.
    plate_width = min(ANPR_PLATE_WIDTH_M, vehicle_width * 0.62)
    plate_height = min(
        ANPR_PLATE_HEIGHT_M,
        plate_width * (ANPR_PLATE_HEIGHT_M / ANPR_PLATE_WIDTH_M),
    )

    # Place the plate on the lower front/rear body area.
    plate_z = z_min + (z_max - z_min) * 0.34
    plate_y = (y_min + y_max) * 0.5

    half_w = plate_width * 0.5
    half_h = plate_height * 0.5

    # Small outward offset prevents the overlay from being buried inside the
    # cached bounding-box surface.
    inset = max(0.012, min(0.035, 0.012 * max(1.0, x_max - x_min)))

    def plane(x_value):
        return [
            [x_value, plate_y - half_w, plate_z - half_h, 1.0],
            [x_value, plate_y + half_w, plate_z - half_h, 1.0],
            [x_value, plate_y + half_w, plate_z + half_h, 1.0],
            [x_value, plate_y - half_w, plate_z + half_h, 1.0],
        ]

    return {
        "front": np.asarray(plane(x_max + inset), dtype=np.float64),
        "rear": np.asarray(plane(x_min - inset), dtype=np.float64),
        "width_m": plate_width,
        "height_m": plate_height,
    }


def _order_quad_points(points):
    """Return image-space quadrilateral corners as TL, TR, BR, BL."""
    pts = np.asarray(points, dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)

    ordered = np.zeros((4, 2), dtype=np.float32)
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(d)]
    ordered[3] = pts[np.argmax(d)]
    return ordered


def _render_fitted_plate_text(text, canvas_w, canvas_h):
    """Render plate characters large enough to occupy the plate face.

    The previous renderer constrained the glyphs mostly by width, leaving too
    much unused vertical space. This version renders the text to its own
    high-resolution layer and fits that layer to both width and height targets.
    A small horizontal compression is allowed so all characters remain inside
    the plate without overflowing.
    """
    font = cv2.FONT_HERSHEY_DUPLEX

    # Target occupancy inside the white plate.
    target_w = int(round(canvas_w * 0.91))
    target_h = int(round(canvas_h * 0.78))

    # Start large, then scale the rendered glyph image to the target footprint.
    # The glyph layer is deliberately larger than the final target so the
    # downsampling remains clean after the plate is perspective-warped.
    render_scale = 12.0
    thickness = max(16, int(round(canvas_h * 0.095)))

    (tw, th), baseline = cv2.getTextSize(
        text, font, render_scale, thickness
    )

    # Safety fallback for unexpected OpenCV font metrics.
    if tw <= 0 or th <= 0:
        return None

    # Fit the original glyphs inside the target box while retaining their
    # proportions as much as possible.
    uniform_scale = min(
        target_w / float(tw),
        target_h / float(th + baseline),
    )

    # OpenCV's font scale can be directly adjusted before rendering.
    final_scale = render_scale * uniform_scale

    (tw, th), baseline = cv2.getTextSize(
        text, font, final_scale, thickness
    )

    # If width fitting made the characters shorter than desired, render first
    # and then apply only a limited vertical expansion. This makes the plate
    # text visually fill the plate rather than appearing tiny.
    text_w = max(1, tw)
    text_h = max(1, th + baseline)

    pad_x = max(4, int(round(target_w * 0.015)))
    pad_y = max(4, int(round(target_h * 0.08)))

    layer_w = text_w + 2 * pad_x
    layer_h = text_h + 2 * pad_y
    layer = np.zeros((layer_h, layer_w, 3), dtype=np.uint8)

    x = pad_x
    y = pad_y + th

    cv2.putText(
        layer,
        text,
        (x, y),
        font,
        final_scale,
        (0, 0, 0),
        thickness,
        cv2.LINE_AA,
    )

    # Determine the actual non-black glyph bounds. The background is black here,
    # while the glyphs are white, so thresholding is straightforward.
    gray = cv2.cvtColor(layer, cv2.COLOR_BGR2GRAY)
    _, glyph_mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)

    # The rendered text itself is black in the final plate, therefore create
    # a mask from the inverse of the layer's black background.
    # We instead render a white glyph mask separately for robust bounds.
    mask_layer = np.zeros((layer_h, layer_w), dtype=np.uint8)
    cv2.putText(
        mask_layer,
        text,
        (x, y),
        font,
        final_scale,
        255,
        thickness,
        cv2.LINE_AA,
    )

    ys, xs = np.where(mask_layer > 8)
    if len(xs) == 0 or len(ys) == 0:
        return None

    crop = layer[
        max(0, ys.min() - 2):min(layer_h, ys.max() + 3),
        max(0, xs.min() - 2):min(layer_w, xs.max() + 3),
    ]

    # Render black text on a white target layer.
    crop_mask = mask_layer[
        max(0, ys.min() - 2):min(layer_h, ys.max() + 3),
        max(0, xs.min() - 2):min(layer_w, xs.max() + 3),
    ]

    actual_h, actual_w = crop_mask.shape

    # Fit the glyphs to 91% width and 78% height of the plate. This is the
    # critical change from the previous version.
    desired_w = target_w
    desired_h = target_h

    resized_mask = cv2.resize(
        crop_mask,
        (desired_w, desired_h),
        interpolation=cv2.INTER_AREA,
    )

    text_layer = np.full(
        (canvas_h, canvas_w, 3),
        250,
        dtype=np.uint8,
    )

    # Center the fitted text.
    x0 = max(0, (canvas_w - desired_w) // 2)
    y0 = max(0, (canvas_h - desired_h) // 2)

    # Black glyphs, with anti-aliased edges.
    roi = text_layer[y0:y0 + desired_h, x0:x0 + desired_w]
    roi[resized_mask > 8] = (0, 0, 0)

    return text_layer


def draw_projected_plate(frame, projected, plate_text):
    """Render a high-contrast, enlarged perspective plate for human/ANPR visibility."""
    if projected is None or len(projected) != 4:
        return 0.0

    quad = _order_quad_points([[p[0], p[1]] for p in projected])
    if np.any(~np.isfinite(quad)):
        return 0.0

    area = polygon_area([(float(x), float(y)) for x, y in quad])
    if area < 12.0:
        return area

    h, w = frame.shape[:2]

    min_x, max_x = float(quad[:, 0].min()), float(quad[:, 0].max())
    min_y, max_y = float(quad[:, 1].min()), float(quad[:, 1].max())
    pixel_w = max_x - min_x
    pixel_h = max_y - min_y

    if pixel_w < ANPR_MIN_PLATE_PIXEL_WIDTH:
        return area
    if pixel_h < ANPR_MIN_PLATE_PIXEL_HEIGHT:
        return area

    if max_x < 0 or min_x >= w or max_y < 0 or min_y >= h:
        return area

    # Large source canvas preserves character edges after perspective warp.
    canvas_w = 3200
    canvas_h = int(round(canvas_w * ANPR_PLATE_HEIGHT_M / ANPR_PLATE_WIDTH_M))
    plate = np.full((canvas_h, canvas_w, 3), 250, dtype=np.uint8)

    # Strong black border.
    border = max(12, int(round(canvas_h * 0.045)))
    cv2.rectangle(
        plate,
        (border, border),
        (canvas_w - border - 1, canvas_h - border - 1),
        (8, 8, 8),
        border,
        cv2.LINE_AA,
    )

    # Render contiguous alphanumeric text for OCR while retaining the normal
    # human-readable spaced registration string in metadata.
    rendered_text = "".join(ch for ch in plate_text.upper() if ch.isalnum())

    # The fitted text now deliberately occupies most of the plate face instead
    # of being limited to a short, thin line of glyphs.
    fitted_plate = _render_fitted_plate_text(
        rendered_text,
        canvas_w,
        canvas_h,
    )
    if fitted_plate is None:
        return area

    plate = fitted_plate

    # Restore the strong plate border after fitting the text layer.
    # The border is deliberately kept outside the glyph region.
    border = max(12, int(round(canvas_h * 0.045)))
    cv2.rectangle(
        plate,
        (border, border),
        (canvas_w - border - 1, canvas_h - border - 1),
        (8, 8, 8),
        border,
        cv2.LINE_AA,
    )

    # Add a subtle inner whitespace margin around the glyphs without changing
    # the black/white visual contrast used by ANPR.
    src_quad = np.array(
        [
            [0.0, 0.0],
            [canvas_w - 1.0, 0.0],
            [canvas_w - 1.0, canvas_h - 1.0],
            [0.0, canvas_h - 1.0],
        ],
        dtype=np.float32,
    )

    H = cv2.getPerspectiveTransform(src_quad, quad.astype(np.float32))

    warped = cv2.warpPerspective(
        plate,
        H,
        (w, h),
        flags=cv2.INTER_AREA,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )

    mask_src = np.full((canvas_h, canvas_w), 255, dtype=np.uint8)
    mask = cv2.warpPerspective(
        mask_src,
        H,
        (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    frame[:] = (
        warped.astype(np.float32) * alpha
        + frame.astype(np.float32) * (1.0 - alpha)
    ).astype(np.uint8)

    # Crisp projected boundary makes the plate easier for both humans and
    # downstream CV to localize.
    quad_i = np.round(quad).astype(np.int32)
    cv2.polylines(
        frame,
        [quad_i],
        True,
        (8, 8, 8),
        max(2, int(round(pixel_h * 0.10))),
        cv2.LINE_AA,
    )

    return area


def draw_number_plate_overlay(
    frame,
    camera_model,
    vehicle_name,
    transform_values,
    bbox_geometry,
):
    """Draw the most visible 3-D projected plate face."""
    plate_geometry = bbox_geometry.get("plate_geometry")
    if plate_geometry is None:
        plate_geometry = make_3d_plate_candidates(bbox_geometry)
        bbox_geometry["plate_geometry"] = plate_geometry

    plate_text = PLATE_NUMBERS.get(vehicle_name, vehicle_name)

    candidates = []

    for side in ("front", "rear"):
        projected = project_local_points(
            transform_values,
            plate_geometry[side],
            camera_model,
        )

        if projected is None:
            continue

        depth = sum(p[2] for p in projected) / len(projected)
        area = polygon_area([(p[0], p[1]) for p in projected])

        if depth > 0.10 and area >= 4.0:
            candidates.append((area, -depth, projected))

    if not candidates:
        return

    # The face with the largest projected area is normally the visible face.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    draw_projected_plate(frame, candidates[0][2], plate_text)


def draw_all_number_plates(
    frame,
    camera_model,
    transform_states,
    bbox_geometries,
):
    """Overlay plates using cached geometry and per-frame actor transforms."""
    for vehicle_name, transform_values in transform_states.items():
        bbox_geometry = bbox_geometries.get(vehicle_name)
        if bbox_geometry is None:
            continue

        try:
            draw_number_plate_overlay(
                frame,
                camera_model,
                vehicle_name,
                transform_values,
                bbox_geometry,
            )
        except Exception as exc:
            print(
                f"[PLATE RENDER WARNING] {vehicle_name}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )


# ---------------------------------------------------------------------------
# Map / planner helpers
# ---------------------------------------------------------------------------

def find_junction(map_obj, junction_id, fallback):
    exact = []
    for wp in map_obj.generate_waypoints(4.0):
        if wp.is_junction and wp.junction_id == junction_id:
            exact.append(wp.get_junction())
    if exact:
        return min(exact, key=lambda j: hdist(j.bounding_box.location, fallback))

    candidates = [wp.get_junction() for wp in map_obj.generate_waypoints(4.0) if wp.is_junction]
    if not candidates:
        return None
    best = min(candidates, key=lambda j: hdist(j.bounding_box.location, fallback))
    d = hdist(best.bounding_box.location, fallback)
    if d <= 40.0:
        print(f"[WARN] Junction {junction_id} exact ID not found; nearest={d:.1f}m")
        return best
    return None


def planner_route(planner, start, destination):
    """Return planner transforms with duplicates removed."""
    segment = planner.trace_route(start, destination)
    if not segment:
        return []
    return unique_locations([wp.transform for wp, _ in segment], 0.8)


def route_min_distance(route, location):
    if not route:
        return float("inf")
    return min(hdist(t.location, location) for t in route)


def route_length(route):
    total = 0.0
    for a, b in zip(route, route[1:]):
        total += hdist(a.location, b.location)
    return total


def route_from_waypoint_successors(start_wp, steps=30, same_lane_preferred=True):
    """Continue forward in OpenDRIVE waypoint topology."""
    route = [start_wp.transform]
    current = start_wp
    visited = set()

    for _ in range(steps):
        key = waypoint_key(current)
        if key in visited:
            break
        visited.add(key)
        nxt = current.next(2.0)
        if not nxt:
            break
        if same_lane_preferred:
            same = [w for w in nxt if w.road_id == current.road_id and w.lane_id == current.lane_id]
            choices = same or nxt
        else:
            choices = nxt
        current = choices[0]
        if hdist(route[-1].location, current.transform.location) > 0.8:
            route.append(current.transform)
    return route


def extend_forward(map_obj, route, steps=25):
    if not route:
        return route
    wp = map_obj.get_waypoint(
        route[-1].location,
        project_to_road=True,
        lane_type=carla.LaneType.Driving,
    )
    if wp is None:
        return route
    extra = route_from_waypoint_successors(wp, steps)
    return append_route(route, extra)


def append_route(first, second):
    if not second:
        return list(first)
    if not first:
        return list(second)
    start = 1 if hdist(first[-1].location, second[0].location) < 4.0 else 0
    return list(first) + list(second[start:])


def backtrack_lane(entry_wp, wanted_distance=45.0):
    """Walk backward on the same OpenDRIVE lane before the junction."""
    current = entry_wp
    travelled = 0.0
    while travelled < wanted_distance:
        previous = current.previous(2.0)
        if not previous:
            break
        same = [p for p in previous if p.road_id == current.road_id and p.lane_id == current.lane_id]
        if not same:
            same = previous
        current = same[0]
        travelled += 2.0
    return current, travelled


def choose_junction_entry_exit(junction, prefer_heading=None):
    """Return driving entry/exit pairs from the real junction topology."""
    pairs = []
    for entry, exit_wp in junction.get_waypoints(carla.LaneType.Driving):
        if entry is None or exit_wp is None:
            continue
        if prefer_heading is not None:
            yaw = exit_wp.transform.rotation.yaw
            d = abs(wrap_angle(yaw - prefer_heading))
        else:
            d = 0.0
        pairs.append((d, entry, exit_wp))
    pairs.sort(key=lambda x: x[0])
    return [(a, b) for _, a, b in pairs]


def route_passes_junction(route, junction, threshold=22.0):
    return route_min_distance(route, junction.bounding_box.location) <= threshold


def find_reachable_junction_chain(planner, j2, j3, start_location):
    """
    Search real J2/J3 entry/exit topology.

    A candidate is accepted only when:
      start -> J2 exit route passes J2,
      J2 exit -> J3 exit route passes J3.

    This avoids assuming that a junction's bounding-box center is a valid road
    destination.
    """
    j2_pairs = choose_junction_entry_exit(j2)
    j3_pairs = choose_junction_entry_exit(j3)
    candidates = []

    # Limit duplicates by (road,lane) rather than testing many 2m-identical points.
    seen2 = set()
    seen3 = set()
    j2_exits = []
    for entry, exit_wp in j2_pairs:
        key = (exit_wp.road_id, exit_wp.lane_id)
        if key not in seen2:
            seen2.add(key)
            j2_exits.append(exit_wp)
    j3_exits = []
    for entry, exit_wp in j3_pairs:
        key = (exit_wp.road_id, exit_wp.lane_id)
        if key not in seen3:
            seen3.add(key)
            j3_exits.append(exit_wp)

    for e2 in j2_exits:
        r2 = planner_route(planner, start_location, e2.transform.location)
        if len(r2) < 5 or not route_passes_junction(r2, j2):
            continue
        for e3 in j3_exits:
            r3 = planner_route(planner, e2.transform.location, e3.transform.location)
            if len(r3) < 5 or not route_passes_junction(r3, j3):
                continue
            total = route_length(r2) + route_length(r3)
            j2d = route_min_distance(r2, j2.bounding_box.location)
            j3d = route_min_distance(r3, j3.bounding_box.location)
            candidates.append((total, j2d, j3d, r2, r3, e2, e3))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1] + x[2]))
    total, j2d, j3d, r2, r3, e2, e3 = candidates[0]
    return {
        "route_to_j2": r2,
        "route_to_j3": r3,
        "j2_exit": e2,
        "j3_exit": e3,
        "total_length": total,
        "j2_min_distance": j2d,
        "j3_min_distance": j3d,
    }


def select_crossing_with_b_corridor(j1, planner, j2, j3):
    """
    Select A/B crossing lanes with an additional requirement:
    B's J1 exit must have a real planner route to J2 and then J3.

    This is the key correction versus the earlier versions. We do not choose
    an arbitrary perpendicular collision and hope the selected B exit happens
    to point toward the next junctions.
    """
    pairs = choose_junction_entry_exit(j1)
    prepared = []

    for entry, exit_wp in pairs:
        # Build a local topology route through the junction.
        spawn_wp, upstream = backtrack_lane(entry, 45.0)
        route = planner_route(planner, spawn_wp.transform.location, exit_wp.transform.location)
        if len(route) < 8:
            continue
        prepared.append({
            "entry": entry,
            "exit": exit_wp,
            "spawn": spawn_wp,
            "upstream": upstream,
            "route": route,
        })

    if len(prepared) < 2:
        raise RuntimeError("J1 does not provide two usable crossing routes")

    best = None
    for i in range(len(prepared)):
        for j in range(i + 1, len(prepared)):
            p1 = prepared[i]
            p2 = prepared[j]
            h1 = p1["entry"].transform.rotation.yaw
            h2 = p2["entry"].transform.rotation.yaw
            sep = abs(wrap_angle(h1 - h2))
            if sep < 75.0:
                continue

            # Find closest route points inside/near J1.
            closest = None
            for i1, t1 in enumerate(p1["route"]):
                if hdist(t1.location, j1.bounding_box.location) > 25.0:
                    continue
                for i2, t2 in enumerate(p2["route"]):
                    if hdist(t2.location, j1.bounding_box.location) > 25.0:
                        continue
                    d = hdist(t1.location, t2.location)
                    if closest is None or d < closest[0]:
                        closest = (d, i1, i2)
            if closest is None or closest[0] > 4.0:
                continue

            d, i1, i2 = closest
            a_pt = p1["route"][i1].location
            b_pt = p2["route"][i2].location
            collision_point = carla.Location(
                x=(a_pt.x + b_pt.x) * 0.5,
                y=(a_pt.y + b_pt.y) * 0.5,
                z=max(a_pt.z, b_pt.z, 0.6),
            )

            # Critical requirement: B's selected exit can actually reach J2 -> J3.
            corridor = find_reachable_junction_chain(
                planner,
                j2,
                j3,
                p2["exit"].transform.location,
            )
            if corridor is None:
                continue

            score = (
                d * 20.0
                + abs(sep - 90.0) * 0.15
                + hdist(collision_point, j1.bounding_box.location) * 0.10
                + corridor["total_length"] * 0.001
            )
            if best is None or score < best[0]:
                best = (score, p1, p2, i1, i2, collision_point, d, sep, corridor)

    if best is None:
        raise RuntimeError(
            "Could not find a J1 perpendicular crossing whose B exit can also reach J2 and J3."
        )

    _, a, b, ai, bi, collision_point, gap, sep, corridor = best

    print("========== TOPOLOGY VALIDATION ==========")
    print(f"A entry       : {a['entry'].transform.location} yaw={a['entry'].transform.rotation.yaw:.1f}")
    print(f"B entry       : {b['entry'].transform.location} yaw={b['entry'].transform.rotation.yaw:.1f}")
    print(f"Collision pt  : {collision_point}")
    print(f"Lane gap      : {gap:.2f}m")
    print(f"Heading sep   : {sep:.1f} deg")
    print(f"A upstream    : {a['upstream']:.1f}m")
    print(f"B upstream    : {b['upstream']:.1f}m")
    print(f"B->J2 length  : {route_length(corridor['route_to_j2']):.1f}m")
    print(f"B->J2 minimum : {corridor['j2_min_distance']:.1f}m")
    print(f"J2->J3 length : {route_length(corridor['route_to_j3']):.1f}m")
    print(f"J2->J3 minimum: {corridor['j3_min_distance']:.1f}m")

    return {
        "a": a,
        "b": b,
        "a_collision_idx": ai,
        "b_collision_idx": bi,
        "collision_point": collision_point,
        "gap": gap,
        "heading_sep": sep,
        "corridor": corridor,
    }


# ---------------------------------------------------------------------------
# Vehicle blueprints / spawning
# ---------------------------------------------------------------------------

def build_vehicle_pool(world):
    library = world.get_blueprint_library()
    candidates = []
    for bp in library.filter("vehicle.*"):
        try:
            wheels = int(bp.get_attribute("number_of_wheels").as_int())
        except Exception:
            wheels = 4
        if wheels != 4:
            continue
        low = bp.id.lower()
        if any(k in low for k in EXCLUDED_VEHICLE_KEYWORDS):
            continue
        candidates.append(bp)

    if not candidates:
        raise RuntimeError("No 4-wheel vehicle blueprints exist in this CARLA installation.")

    preferred = [bp for bp in candidates if any(k in bp.id.lower() for k in PREFERRED_VEHICLE_KEYWORDS)]
    pool = sorted(preferred or candidates, key=lambda bp: bp.id)
    print(f"[BLUEPRINTS] {len(pool)} runtime-available 4-wheel vehicles")
    print("[BLUEPRINTS] " + ", ".join(bp.id for bp in pool[:20]))
    return pool


def spawn_vehicle(world, blueprint, wp):
    t = carla.Transform(
        carla.Location(
            x=wp.transform.location.x,
            y=wp.transform.location.y,
            z=max(wp.transform.location.z + 0.4, 0.6),
        ),
        carla.Rotation(
            pitch=wp.transform.rotation.pitch,
            yaw=wp.transform.rotation.yaw,
            roll=wp.transform.rotation.roll,
        ),
    )
    vehicle = world.try_spawn_actor(blueprint, t)
    if vehicle is not None:
        return vehicle

    fw = t.get_forward_vector()
    for offset in (1.0, -1.0, 2.0, -2.0):
        retry = carla.Transform(
            carla.Location(
                x=t.location.x + fw.x * offset,
                y=t.location.y + fw.y * offset,
                z=t.location.z,
            ),
            t.rotation,
        )
        vehicle = world.try_spawn_actor(blueprint, retry)
        if vehicle is not None:
            return vehicle
    return None


# ---------------------------------------------------------------------------
# Route control
# ---------------------------------------------------------------------------

POST_CRASH_LOOKAHEAD = 4
POST_CRASH_TARGET_SPEED = 6.5


# ---------------------------------------------------------------------------
# B POST-IMPACT ROAD RECOVERY
# ---------------------------------------------------------------------------
# After the A/B collision, CARLA physics can push B sideways. In the previous
# versions B's route was rebuilt from its physically displaced position, which
# could project onto a sidewalk/curb area. This recovery instead reconnects
# B to the already validated B driving-lane corridor.
B_RECOVERY_SPEED = 2.5
B_RECOVERY_MAX_STEER = 0.55
B_RECOVERY_LATERAL_LIMIT = 2.0
B_RECOVERY_HEADING_LIMIT_DEG = 32.0
B_RECOVERY_MAX_FRAMES = 80


def _angle_deg(a, b):
    return abs(math.degrees(math.atan2(math.sin(a - b), math.cos(a - b))))


def b_recover_to_validated_lane(vehicle, route, index_hint=0):
    """
    Steer B back to the validated driving-lane route after the collision.

    This is a temporary recovery controller. It never teleports B and never
    disables collision/physics. It only changes steering/throttle while B is
    being brought back onto the road lane.
    """
    if not route or not vehicle.is_alive:
        return False, index_hint, float("inf"), 180.0

    loc = vehicle.get_location()
    start = max(0, min(index_hint, len(route) - 1))

    # Find the nearest point on the VALIDATED ROAD ROUTE, not the sidewalk.
    nearest = min(
        range(start, len(route)),
        key=lambda i: hdist(loc, route[i].location)
    )

    # Do not drive toward a route point behind the vehicle. Select a short
    # forward target from the nearest lane-center point.
    target_index = min(nearest + 2, len(route) - 1)
    target = route[target_index].location

    tr = vehicle.get_transform()
    forward = tr.get_forward_vector()
    right = tr.get_right_vector()

    dx = target.x - loc.x
    dy = target.y - loc.y

    longitudinal = forward.x * dx + forward.y * dy
    lateral = right.x * dx + right.y * dy

    route_yaw = math.radians(route[target_index].rotation.yaw)
    vehicle_yaw = math.radians(tr.rotation.yaw)
    heading_error = math.degrees(
        math.atan2(
            math.sin(route_yaw - vehicle_yaw),
            math.cos(route_yaw - vehicle_yaw)
        )
    )

    # Strong enough to return from the footpath, but deliberately limited so
    # B cannot make a violent steering cut across the junction.
    steer = (
        0.045 * lateral
        + 0.010 * heading_error
    )
    steer = max(-B_RECOVERY_MAX_STEER, min(B_RECOVERY_MAX_STEER, steer))

    speed = speed_mps(vehicle)
    control = carla.VehicleControl(
        throttle=0.0,
        brake=0.0,
        steer=steer,
        hand_brake=False,
        reverse=False,
    )

    if speed < B_RECOVERY_SPEED - 0.25:
        control.throttle = 0.38
    elif speed > B_RECOVERY_SPEED + 0.55:
        control.brake = 0.25
    else:
        control.throttle = 0.16

    vehicle.apply_control(control)

    lateral_error = abs(hdist(loc, route[nearest].location))
    aligned = (
        lateral_error <= B_RECOVERY_LATERAL_LIMIT
        and abs(heading_error) <= B_RECOVERY_HEADING_LIMIT_DEG
    )

    return aligned, nearest, lateral_error, abs(heading_error)


class RouteController:
    """Simple deterministic waypoint follower using VehicleControl."""

    def __init__(self, vehicle, route, cruise_mps=6.5):
        self.vehicle = vehicle
        self.route = route
        self.index = 0
        self.enabled = False
        self.finished = False
        self.cruise_mps = cruise_mps

    def set_route(self, route):
        self.route = route
        self.index = 0
        self.finished = False

    def stop(self):
        self.enabled = False
        self.finished = True
        self.vehicle.apply_control(
            carla.VehicleControl(throttle=0.0, brake=1.0, hand_brake=True)
        )

    def remaining_route_distance(self, target_location=None):
        if not self.route:
            return 0.0
        loc = self.vehicle.get_location()
        best_index = self.index
        best_dist = float("inf")
        max_i = len(self.route)
        for i in range(self.index, max_i):
            d = hdist(loc, self.route[i].location)
            if d < best_dist:
                best_dist = d
                best_index = i
        self.index = max(self.index, best_index)

        end_index = len(self.route) - 1
        if target_location is not None:
            target_i = min(
                range(self.index, len(self.route)),
                key=lambda i: hdist(self.route[i].location, target_location),
            )
            end_index = target_i

        total = best_dist
        for a, b in zip(self.route[self.index:end_index], self.route[self.index + 1:end_index + 1]):
            total += hdist(a.location, b.location)
        return total

    def distance_to_location_along_route(self, target_location):
        if not self.route:
            return float("inf")
        loc = self.vehicle.get_location()
        nearest = min(
            range(self.index, len(self.route)),
            key=lambda i: hdist(loc, self.route[i].location),
        )
        target = min(
            range(nearest, len(self.route)),
            key=lambda i: hdist(self.route[i].location, target_location),
        )
        total = hdist(loc, self.route[nearest].location)
        for a, b in zip(self.route[nearest:target], self.route[nearest + 1:target + 1]):
            total += hdist(a.location, b.location)
        total += hdist(self.route[target].location, target_location)
        return total

    def update(self, target_speed=None, allow_stop=True, lookahead=6):
        if not self.enabled or self.finished or not self.vehicle.is_alive or not self.route:
            return

        loc = self.vehicle.get_location()
        # Monotonic nearest-point update.
        nearest = min(
            range(self.index, len(self.route)),
            key=lambda i: hdist(loc, self.route[i].location),
        )
        self.index = max(self.index, nearest)

        if self.index >= len(self.route) - 1:
            if allow_stop and hdist(loc, self.route[-1].location) < 5.0:
                self.stop()
                return
            target = self.route[-1].location
        else:
            target = self.route[min(self.index + lookahead, len(self.route) - 1)].location

        transform = self.vehicle.get_transform()
        forward = transform.get_forward_vector()
        right = transform.get_right_vector()
        delta = target - loc
        local_x = forward.x * delta.x + forward.y * delta.y
        local_y = right.x * delta.x + right.y * delta.y
        heading_error = math.atan2(local_y, max(local_x, 0.5))

        # Moderate pure-pursuit-like steering. Do not request reverse.
        steer = max(-0.85, min(0.85, heading_error * 1.35))
        speed = speed_mps(self.vehicle)
        desired = self.cruise_mps if target_speed is None else max(0.0, target_speed)

        control = carla.VehicleControl(
            steer=steer,
            throttle=0.0,
            brake=0.0,
            hand_brake=False,
            reverse=False,
        )
        if speed < desired - 0.25:
            control.throttle = min(0.75, 0.45 + 0.04 * (desired - speed))
        elif speed > desired + 0.60:
            control.brake = min(0.55, 0.20 + 0.04 * (speed - desired))
        else:
            control.throttle = 0.18
        self.vehicle.apply_control(control)


# ---------------------------------------------------------------------------
# Approach/exit routes for C-H
# ---------------------------------------------------------------------------

def find_safe_approach_spawn(map_obj, junction, used_locations, preferred=50.0):
    center = junction.bounding_box.location
    candidates = []
    for wp in map_obj.generate_waypoints(3.0):
        if wp.lane_type != carla.LaneType.Driving or wp.is_junction:
            continue
        d = hdist(wp.transform.location, center)
        if not 35.0 <= d <= 90.0:
            continue
        if any(hdist(wp.transform.location, u) < 16.0 for u in used_locations):
            continue

        # Walk forward and require that this lane really enters the junction.
        cur = wp
        reaches = False
        for _ in range(45):
            if cur.is_junction:
                reaches = True
                break
            nxt = cur.next(3.0)
            if not nxt:
                break
            # Prefer the continuation that reduces distance to the junction.
            cur = min(nxt, key=lambda x: hdist(x.transform.location, center))
        if reaches:
            candidates.append((abs(d - preferred), wp))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def build_single_junction_route(planner, map_obj, junction, spawn_wp, extension_points=45):
    """Find a connected route from spawn through junction to a genuine exit road."""
    pairs = choose_junction_entry_exit(junction)
    candidates = []
    for entry, exit_wp in pairs:
        route = planner_route(planner, spawn_wp.transform.location, exit_wp.transform.location)
        if len(route) < 6:
            continue
        if not route_passes_junction(route, junction, 22.0):
            continue
        # Ensure route continues beyond the exit.
        extended = extend_forward(map_obj, route, extension_points)
        candidates.append((route_min_distance(route, junction.bounding_box.location), -route_length(extended), extended))
    if not candidates:
        raise RuntimeError(f"No connected route through junction {junction.bounding_box.location}")
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def moving_vehicles_near_junction(vehicles, names, junction, radius=30.0, min_speed_mps=0.8):
    """Return vehicles that are both physically near the junction and moving."""
    result = []
    center = junction.bounding_box.location
    for name in names:
        v = vehicles.get(name)
        if v is None or not v.is_alive:
            continue
        if hdist(v.get_location(), center) <= radius and speed_mps(v) >= min_speed_mps:
            result.append(name)
    return result


def stage_traffic_for_junction(controllers, release_names, release_flags, flag_key):
    """Legacy helper retained for compatibility; v19 main uses Traffic Manager."""

    """Enable a prepared traffic pair together at the requested junction."""
    if release_flags[flag_key]:
        return
    release_flags[flag_key] = True
    for name in release_names:
        controllers[name].enabled = True
    print(f"[TRAFFIC STAGE] {flag_key}: released {', '.join(release_names)}")



# ---------------------------------------------------------------------------
# Collision handling
# ---------------------------------------------------------------------------

def attach_ab_collision_sensor(world, vehicle, collision_state):
    bp = world.get_blueprint_library().find("sensor.other.collision")
    sensor = world.spawn_actor(bp, carla.Transform(), attach_to=vehicle)

    def callback(event):
        if collision_state["seen"]:
            return
        other = event.other_actor
        if other is None:
            return
        ids = {vehicle.id, other.id}
        if ids == {collision_state["a_id"], collision_state["b_id"]}:
            collision_state["seen"] = True
            collision_state["event"] = event
            collision_state["location"] = event.transform.location
            collision_state["impulse"] = event.normal_impulse
            print("\n" + "=" * 70)
            print("[COLLISION] REAL CARLA PHYSICS COLLISION A <-> B")
            print(f"[COLLISION] frame={event.frame} location={event.transform.location}")
            print(f"[COLLISION] normal_impulse={event.normal_impulse}")
            print("=" * 70)

            # Publish the guaranteed physics-confirmed crash alert IMMEDIATELY            # so the authority portal popup appears at the exact crash moment.
            # The IMU+GPS pair confirmation path is slower and may never fire.
            publisher = collision_state.get("publisher")
            if publisher is not None:
                try:
                    publisher.publish({
                        "type": "crash_alert",
                        "timestamp_sim": float(event.timestamp),
                        "frame": int(event.frame),
                        "alert_id": f"PHY-{event.frame:09d}",
                        "vehicle_id": collision_state.get("actor_name", "A"),
                        "plate_number": collision_state.get("actor_plate", "N/A"),
                        "collision_partner": collision_state.get("partner_name", "B"),
                        "collision_partner_plate": collision_state.get("partner_plate", "N/A"),
                        "status": "COLLISION_EVENT_CONFIRMED_CARLA_PHYSICS",
                        "crash_probability": 1.0,
                        "physics_confirmed": True,
                        "world_location": {
                            "x": float(event.transform.location.x),
                            "y": float(event.transform.location.y),
                            "z": float(event.transform.location.z),
                        },
                    })
                    print("[COLLISION] physics crash_alert published to live backend")
                except Exception as exc:
                    print(f"[COLLISION] physics alert publish failed: {exc}")

    sensor.listen(callback)
    return sensor




class CSVWriter:
    def __init__(self, path, fields):
        self.path = path
        self.file = open(path, "w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(
            self.file,
            fieldnames=fields,
            extrasaction="ignore",
        )
        self.writer.writeheader()
        self.lock = threading.Lock()

    def write(self, row):
        with self.lock:
            self.writer.writerow(row)
            self.file.flush()

    def close(self):
        with self.lock:
            self.file.flush()
            self.file.close()


# ===========================================================================
# MULTIMODAL EVIDENCE PIPELINE
# ===========================================================================

class IMUCrashDetectorV2:
    """Exact PHASE 3 v2 3-stage IMU crash detector."""

    def __init__(self, model_path, sampling_rate=200):
        package = joblib.load(model_path)

        if isinstance(package, dict):
            self.model = package["model"]
            self.threshold = package.get("threshold", 0.1)
            self.feature_names = package.get("feature_names", [])
            self.physics_config = package.get("physics_gate", {})
            self.version = package.get("version", "2.0")
        else:
            self.model = package
            self.threshold = 0.1
            self.feature_names = []
            self.physics_config = {}
            self.version = "unknown"

        self.sampling_rate = sampling_rate
        self.window_size = int(0.5 * sampling_rate)
        self.stride_size = int(0.1 * sampling_rate)

        self.ax_buffer = deque(maxlen=self.window_size)
        self.ay_buffer = deque(maxlen=self.window_size)
        self.az_buffer = deque(maxlen=self.window_size)
        self.gx_buffer = deque(maxlen=self.window_size)
        self.gy_buffer = deque(maxlen=self.window_size)
        self.gz_buffer = deque(maxlen=self.window_size)

        self.sample_count = 0
        self.current_speed_kmh = 0.0

        self.min_g_for_crash = self.physics_config.get("min_g_for_crash", 1.0)
        self.min_jerk_for_crash = self.physics_config.get("min_jerk_for_crash", 15.0)
        self.braking_longitudinal_ratio_max = self.physics_config.get(
            "braking_longitudinal_ratio_max", 5.0
        )

        self.recent_detections = deque(maxlen=3)
        self.confirmation_window = 3

        self.expected_features = [
            "ax_mean", "ax_std", "ax_ptp",
            "ay_mean", "ay_std", "ay_ptp",
            "az_mean", "az_std", "az_ptp",
            "gx_mean", "gx_std", "gx_ptp",
            "gy_mean", "gy_std", "gy_ptp",
            "gz_mean", "gz_std", "gz_ptp",
            "g_force_peak", "g_force_std",
            "jerk_peak", "jerk_mag_std",
            "speed_kmh",
            "longitudinal_ratio", "multi_axis_energy",
            "rotational_shock", "shock_brake_ratio",
        ]

    def set_speed(self, speed_kmh):
        self.current_speed_kmh = max(0.0, float(speed_kmh))

    def add_sample(self, ax, ay, az, gx, gy, gz):
        self.ax_buffer.append(float(ax))
        self.ay_buffer.append(float(ay))
        self.az_buffer.append(float(az))
        self.gx_buffer.append(float(gx))
        self.gy_buffer.append(float(gy))
        self.gz_buffer.append(float(gz))
        self.sample_count += 1

        if (
            self.sample_count % self.stride_size == 0
            and len(self.ax_buffer) == self.window_size
        ):
            return self._run_detection()
        return None

    def _compute_features(self):
        ax = np.asarray(self.ax_buffer, dtype=np.float64)
        ay = np.asarray(self.ay_buffer, dtype=np.float64)
        az = np.asarray(self.az_buffer, dtype=np.float64)
        gx = np.asarray(self.gx_buffer, dtype=np.float64)
        gy = np.asarray(self.gy_buffer, dtype=np.float64)
        gz = np.asarray(self.gz_buffer, dtype=np.float64)

        ax_mean, ax_std, ax_ptp = np.mean(ax), np.std(ax), np.ptp(ax)
        ay_mean, ay_std, ay_ptp = np.mean(ay), np.std(ay), np.ptp(ay)
        az_mean, az_std, az_ptp = np.mean(az), np.std(az), np.ptp(az)

        gx_mean, gx_std, gx_ptp = np.mean(gx), np.std(gx), np.ptp(gx)
        gy_mean, gy_std, gy_ptp = np.mean(gy), np.std(gy), np.ptp(gy)
        gz_mean, gz_std, gz_ptp = np.mean(gz), np.std(gz), np.ptp(gz)

        g_force = np.sqrt(ax**2 + ay**2 + az**2)
        g_force_peak = np.max(g_force)
        g_force_std = np.std(g_force)

        # Deliberately matches training: np.diff() is NOT divided by dt.
        jerk_x = np.diff(ax)
        jerk_y = np.diff(ay)
        jerk_z = np.diff(az)
        jerk_peak = max(
            np.max(np.abs(jerk_x)) if len(jerk_x) else 0.0,
            np.max(np.abs(jerk_y)) if len(jerk_y) else 0.0,
            np.max(np.abs(jerk_z)) if len(jerk_z) else 0.0,
        )
        jerk_mag = np.sqrt(jerk_x**2 + jerk_y**2 + jerk_z**2)
        jerk_mag_std = np.std(jerk_mag) if len(jerk_mag) else 0.0

        eps = 1e-6
        longitudinal_ratio = abs(ax_mean) / (abs(ay_mean) + abs(az_mean) + eps)
        multi_axis_energy = (ay_std + az_std) / (ax_std + eps)
        rotational_shock = gx_std + gy_std + gz_std
        shock_brake_ratio = jerk_peak / (abs(ax_mean) + 0.1)

        features_array = np.array([
            ax_mean, ax_std, ax_ptp,
            ay_mean, ay_std, ay_ptp,
            az_mean, az_std, az_ptp,
            gx_mean, gx_std, gx_ptp,
            gy_mean, gy_std, gy_ptp,
            gz_mean, gz_std, gz_ptp,
            g_force_peak, g_force_std,
            jerk_peak, jerk_mag_std,
            self.current_speed_kmh,
            longitudinal_ratio, multi_axis_energy,
            rotational_shock, shock_brake_ratio,
        ], dtype=np.float64)

        features_dict = {
            name: float(val)
            for name, val in zip(self.expected_features, features_array)
        }
        return features_array, features_dict

    def _physics_gate(self, features_dict):
        g_force = features_dict.get("g_force_peak", 0.0)
        jerk = features_dict.get("jerk_peak", 0.0)

        if g_force < self.min_g_for_crash and jerk < self.min_jerk_for_crash:
            return False, "GATE_1: Below minimum impact threshold"

        ax_mean = features_dict.get("ax_mean", 0.0)
        long_ratio = features_dict.get("longitudinal_ratio", 0.0)
        multi_axis = features_dict.get("multi_axis_energy", 0.0)
        rot_shock = features_dict.get("rotational_shock", 0.0)
        shock_brake = features_dict.get("shock_brake_ratio", 0.0)

        is_probable_brake = (
            ax_mean < -0.3
            and long_ratio > 2.0
            and multi_axis < 1.5
            and rot_shock < 8.0
            and shock_brake < 10.0
        )

        if is_probable_brake:
            return False, "GATE_2: Probable hard braking (uni-axial deceleration)"

        return True, "PASS"

    def _confidence_gate(self, crash_prob):
        # IMPORTANT: the ML model no longer has authority to confirm a crash.
        # Its probability is an evidence signal. Final confirmation is performed
        # by MultimodalEvidence using temporal consistency + GPS proximity +
        # relative motion to another vehicle.
        candidate_threshold = max(float(self.threshold), 0.10)
        if crash_prob >= 0.80:
            return False, crash_prob, "IMU_HIGH_CANDIDATE"
        if crash_prob >= 0.35:
            return False, crash_prob, "IMU_IMPACT_CANDIDATE"
        if crash_prob >= candidate_threshold:
            return False, crash_prob, "IMU_SUSPICIOUS"
        return False, crash_prob, "NORMAL"

    def reset(self):
        """Reset the detector buffers after IMU warm-up."""
        self.ax_buffer.clear()
        self.ay_buffer.clear()
        self.az_buffer.clear()
        self.gx_buffer.clear()
        self.gy_buffer.clear()
        self.gz_buffer.clear()
        self.sample_count = 0
        self.recent_detections.clear()

    def _run_detection(self):
        t_start = time.time()
        features_array, features_dict = self._compute_features()

        gate_pass, gate_reason = self._physics_gate(features_dict)
        if not gate_pass:
            return {
                "is_crash": False,
                "crash_probability": 0.0,
                "confidence": 0.0,
                "status": gate_reason,
                "stage_reached": 1,
                "latency_ms": (time.time() - t_start) * 1000.0,
                "features": features_dict,
            }

        proba = self.model.predict_proba(features_array.reshape(1, -1))[0]
        crash_prob = float(proba[1] if len(proba) > 1 else proba[0])
        is_crash, confidence, status = self._confidence_gate(crash_prob)

        return {
            "is_crash": bool(is_crash),
            "crash_probability": crash_prob,
            "confidence": float(confidence),
            "status": status,
            "stage_reached": 3,
            "latency_ms": (time.time() - t_start) * 1000.0,
            "features": features_dict,
        }





class LiveEvidencePublisher:
    """
    Non-blocking publisher for the Member-3 backend.

    Camera transport is deliberately separated into one bounded queue per
    junction. This prevents a burst/backlog from J1 from consuming the queue
    capacity needed by J2 or J3. All three camera queues are serviced
    round-robin by the publisher worker while IMU/GPS/RFID/alert messages use
    a separate evidence queue.

    The publisher never blocks the CARLA simulation thread.
    """

    def __init__(self, url="", queue_max=LIVE_WS_QUEUE_MAX):
        self.url = url
        self.q = queue.Queue(maxsize=queue_max)
        # Camera queues are tiny on purpose: they hold RAW frames (~2.7 MB
        # each). A deep queue here would add seconds of stream latency and
        # hog RAM. Overflow drops the OLDEST frame, keeping the stream live.
        self.camera_queues = {
            1: queue.Queue(maxsize=2),
            2: queue.Queue(maxsize=2),
            3: queue.Queue(maxsize=2),
        }
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            name="live-evidence-publisher",
            daemon=False,
        )
        self.connected = False
        self.ws = None
        self.error = None
        self._camera_round_robin = 1
        self._last_evidence_time = {}

        # Dedicated, unbounded, acknowledged crash-alert channel.
        self.alert_q = queue.Queue()
        self.alert_stop_event = threading.Event()
        self.alert_connected = False
        self.alert_error = None
        self.alert_thread = threading.Thread(
            target=self._run_alerts,
            name="live-crash-alert-publisher",
            daemon=False,
        )

        self.thread.start()
        self.alert_thread.start()

    @staticmethod
    def _put_latest(q, message):
        try:
            q.put_nowait(message)
        except queue.Full:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                pass
            try:
                q.put_nowait(message)
            except queue.Full:
                pass

    # Minimum seconds between two published messages of the same evidence
    # type for the same vehicle. Raw IMU arrives at 200 Hz per vehicle
    # (1600 msg/s across 8 vehicles), which saturates the WebSocket and the    # authority UI. The full-resolution data is still written to CSV/JSONL;
    # only the live stream is rate limited.
    EVIDENCE_MIN_INTERVAL_S = {
        "imu_reading": 0.10,       # 200 Hz -> max 10 Hz per vehicle
        "imu_detection": 0.10,     # model output, keep in step with IMU
        "gps_reading": 0.10,       # 20 Hz  -> max 10 Hz per vehicle
        "vehicle_state": 0.10,
    }
    ALWAYS_PASS_TYPES = {
        "crash_alert",   # never delayed, never dropped
        "rfid_reading",  # rare and event-like
    }

    def _evidence_allowed(self, message):
        message_type = message.get("type")
        if message_type in self.ALWAYS_PASS_TYPES:
            return True
        min_interval = self.EVIDENCE_MIN_INTERVAL_S.get(message_type)
        if min_interval is None:
            return True

        key = (message_type, message.get("vehicle_id"))
        now = time.monotonic()
        last = self._last_evidence_time.get(key)
        if last is not None and (now - last) < min_interval:
            return False
        self._last_evidence_time[key] = now
        return True

    def publish(self, message):
        """Publish non-camera evidence without blocking CARLA."""
        if message.get("type") == "crash_alert":
            # Accepted even during shutdown: close() drains this queue.
            self.alert_q.put(message)
            return
        if self.stop_event.is_set():
            return
        if not self._evidence_allowed(message):
            return
        self._put_latest(self.q, message)

    def publish_camera(self, junction_number, message):
        """Publish a camera frame into that junction's independent queue."""
        if self.stop_event.is_set():
            return
        if junction_number not in self.camera_queues:
            return
        self._put_latest(self.camera_queues[junction_number], message)

    def _next_message(self):
        """Fairly select one camera frame or one evidence message."""
        # Always give each junction an independent opportunity before moving
        # on to the next one. This is the key guarantee for 3-way streaming.
        for _ in range(3):
            junction = self._camera_round_robin
            self._camera_round_robin = 1 + (self._camera_round_robin % 3)
            try:
                return self.camera_queues[junction].get_nowait(), self.camera_queues[junction]
            except queue.Empty:
                pass

        try:
            return self.q.get(timeout=0.05), self.q
        except queue.Empty:
            return None, None

    @staticmethod
    def _encode_camera_message(message):
        """Resize + JPEG-encode + base64 a raw camera frame message.
        Runs on the publisher worker thread so the CARLA main loop never pays
        the encoding cost. Returns None if the frame cannot be encoded.
        """
        raw = message.pop("_raw_frame", None)
        if raw is None:
            return message

        try:
            import base64

            stream_frame = raw
            target_width = LIVE_STREAM_TARGET_WIDTH
            if target_width and raw.shape[1] > target_width:
                scale = target_width / float(raw.shape[1])
                stream_frame = cv2.resize(
                    raw,
                    (
                        target_width,
                        max(1, int(round(raw.shape[0] * scale))),
                    ),
                    interpolation=cv2.INTER_AREA,
                )

            ok, encoded = cv2.imencode(
                ".jpg",
                stream_frame,
                [
                    int(cv2.IMWRITE_JPEG_QUALITY),
                    LIVE_STREAM_JPEG_QUALITY,
                ],
            )
            if not ok:
                return None

            message["image"] = base64.b64encode(
                encoded.tobytes()
            ).decode("ascii")
            message["width"] = int(stream_frame.shape[1])
            message["height"] = int(stream_frame.shape[0])
            return message
        except Exception:
            return None

    def _has_pending(self):
        return (not self.q.empty()) or any(
            not q.empty() for q in self.camera_queues.values()
        )

    def _run(self):
        ws_module = None
        if self.url:
            try:
                import websocket as ws_module
            except Exception as exc:
                self.error = (
                    "websocket-client unavailable: "
                    f"{type(exc).__name__}: {exc}"
                )

        while not self.stop_event.is_set() or self._has_pending():
            msg, source_q = self._next_message()
            if msg is None:
                continue

            # Camera frames carry a raw BGR frame and must be JPEG-encoded
            # here (worker thread) before they can be sent. Evidence messages
            # pass through unchanged.
            if isinstance(msg, dict) and "_raw_frame" in msg:
                encoded_msg = self._encode_camera_message(msg)
                if encoded_msg is None:
                    if source_q is not None:
                        source_q.task_done()
                    continue
                msg = encoded_msg

            try:
                if self.url and ws_module is not None:
                    if self.ws is None:
                        self.ws = ws_module.create_connection(
                            self.url,
                            timeout=2.0,
                        )
                        self.connected = True

                    self.ws.send(json.dumps(msg, separators=(",", ":")))
            except Exception as exc:
                self.connected = False
                self.error = f"{type(exc).__name__}: {exc}"
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.ws = None
            finally:
                source_q.task_done()

        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass

    @staticmethod
    def _wait_for_alert_ack(ws, alert_id):
        """Block until the backend acks alert_id; raise TimeoutError if not."""
        deadline = time.monotonic() + ALERT_ACK_TIMEOUT_S
        while time.monotonic() < deadline:
            # recv() is bounded by the connection timeout and raises on expiry.
            raw = ws.recv()
            try:
                reply = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if (
                isinstance(reply, dict)
                and reply.get("type") == "crash_alert_ack"
                and reply.get("alert_id") == alert_id
            ):
                return reply
        raise TimeoutError(f"no crash_alert_ack for {alert_id}")

    def _run_alerts(self):
        """Deliver crash alerts one at a time, retrying until acknowledged."""
        ws_module = None
        if self.url:
            try:
                import websocket as ws_module
            except Exception as exc:
                self.alert_error = (
                    "websocket-client unavailable: "
                    f"{type(exc).__name__}: {exc}"
                )

        ws = None
        pending = None
        backoff = ALERT_RETRY_MIN_S

        while True:
            if pending is None:
                if self.alert_stop_event.is_set():
                    while True:
                        try:
                            lost = self.alert_q.get_nowait()
                        except queue.Empty:
                            break
                        print(
                            f"[LIVE] crash_alert {lost.get('alert_id')} "
                            "NOT delivered (shutdown)"
                        )
                        self.alert_q.task_done()
                    break
                try:
                    pending = self.alert_q.get(timeout=0.1)
                except queue.Empty:
                    continue

            if not self.url or ws_module is None:
                # No live backend configured: nothing to deliver to.
                self.alert_q.task_done()
                pending = None
                continue

            alert_id = pending.get("alert_id")
            try:
                if ws is None:
                    ws = ws_module.create_connection(
                        self.url,
                        timeout=ALERT_ACK_TIMEOUT_S,
                    )
                    self.alert_connected = True

                ws.send(json.dumps(pending, separators=(",", ":")))
                reply = self._wait_for_alert_ack(ws, alert_id)
                print(
                    f"[LIVE] crash_alert {alert_id} acknowledged by backend"
                    + (" (duplicate)" if reply.get("duplicate") else "")
                )
                self.alert_q.task_done()
                pending = None
                backoff = ALERT_RETRY_MIN_S
            except Exception as exc:
                self.alert_connected = False
                self.alert_error = f"{type(exc).__name__}: {exc}"
                try:
                    if ws is not None:
                        ws.close()
                except Exception:
                    pass
                ws = None

                if self.alert_stop_event.is_set():
                    # Shutdown grace period expired; report what is lost.
                    print(
                        f"[LIVE] crash_alert {alert_id} NOT delivered "
                        f"({self.alert_error})"
                    )
                    self.alert_q.task_done()
                    pending = None
                    continue

                print(
                    f"[LIVE] crash_alert {alert_id} not acknowledged "
                    f"({self.alert_error}); retrying in {backoff:.2f}s"
                )
                self.alert_stop_event.wait(backoff)
                backoff = min(backoff * 2, ALERT_RETRY_MAX_S)

        try:
            if ws is not None:
                ws.close()
        except Exception:
            pass

    def close(self):
        # Give undelivered crash alerts a bounded window to reach the backend
        # before anything else shuts down.
        deadline = time.monotonic() + ALERT_CLOSE_GRACE_S
        while self.alert_q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.05)
        self.alert_stop_event.set()
        self.alert_thread.join(timeout=ALERT_ACK_TIMEOUT_S * 2 + 1.0)

        # Drain everything that was already accepted by the transport queues,
        # then stop the worker. No camera queue is allowed to be abandoned.
        try:
            self.q.join()
            for q in self.camera_queues.values():
                q.join()
        except Exception:
            pass
        self.stop_event.set()
        self.thread.join(timeout=10.0)
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:
            pass


class MultimodalEvidence:
    """
    Integrated GPS + IMU/Gyroscope + RFID + ANPR/video evidence manager.

    This class does not control vehicles and does not change vehicle physics.
    It attaches observation sensors, logs raw observations, invokes the
    existing IMU crash model, generates simulated RFID reads, and publishes
    synchronized live evidence.
    """

    def __init__(self, world, vehicles, junctions, model_path):
        self.world = world
        self.vehicles = vehicles
        self.junctions = junctions
        self.model_path = model_path

        os.makedirs(MULTIMODAL_OUT_DIR, exist_ok=True)

        self.states = {}
        self.sensors = []
        self.lock = threading.Lock()
        self.event_seq = 0

        self.imu_queue = queue.Queue(maxsize=100000)
        self.imu_stop = False
        self.imu_worker = threading.Thread(
            target=self._imu_worker,
            name="imu-model-worker",
            daemon=False,
        )

        self.publisher = LiveEvidencePublisher(LIVE_WS_URL)

        # Per-junction live-stream throttle state (see publish_camera_frame).
        self._last_camera_publish = {1: None, 2: None, 3: None}

        self.rfid_last = {}
        self.rfid_seen = {}

        self.crash_alerted = set()
        self.crash_reference = {}
        self.pending_pair_candidates = deque(maxlen=256)
        self.confirmed_collision_pairs = set()

        self.imu_csv = self._csv(
            "imu_raw_readings.csv",
            [
                "timestamp_sim", "frame", "vehicle_id", "plate_number", "epc",
                "ax_g", "ay_g", "az_g",
                "gx_deg_s", "gy_deg_s", "gz_deg_s",
                "speed_kmh"
            ],
        )

        # Complete raw IMU archive for every A-H vehicle.
        # Observation-only: does not change detection/control/physics.
        self.all_vehicle_imu_csv = self._csv(
            "imu_all_vehicles_raw_readings.csv",
            [
                "timestamp_sim", "frame", "vehicle_id", "plate_number", "epc",
                "ax_g", "ay_g", "az_g",
                "gx_deg_s", "gy_deg_s", "gz_deg_s",
                "speed_kmh"
            ],
        )

        self.gps_csv = self._csv(
            "gps_raw_readings.csv",
            [
                "timestamp_sim", "frame", "vehicle_id", "plate_number", "epc",
                "latitude", "longitude", "altitude",
                "speed_kmh", "heading_deg",
                "world_x", "world_y", "world_z"
            ],
        )

        self.rfid_csv = self._csv(
            "rfid_readings.csv",
            [
                "timestamp_sim", "event_id", "junction_id", "reader_id",
                "vehicle_id", "plate_number", "epc",
                "timestamp_reader", "distance_m", "speed_kmh",
                "confidence", "status"
            ],
        )

        self.detection_csv = self._csv(
            "imu_detection_results.csv",
            [
                "timestamp_sim", "frame", "vehicle_id", "plate_number", "epc",
                "crash_probability", "status", "is_crash",
                "speed_kmh", "latency_ms",
                "g_force_peak", "jerk_peak", "rotational_shock"
            ],
        )

        self.alert_csv = self._csv(
            "crash_alerts.csv",
            [
                "timestamp_sim", "frame", "alert_id", "vehicle_id",
                "plate_number", "epc", "status", "crash_probability",
                "gps_latitude", "gps_longitude", "gps_altitude",
                "world_x", "world_y", "world_z",
                "nearest_vehicle_id", "nearest_plate", "pair_distance_m",
                "relative_speed_kmh", "peak_relative_speed_kmh",
                "closing_distance_m", "post_separation_m", "association_score",
                "collision_confirmed"
            ],
        )

        self.pair_csv = self._csv(
            "collision_pair_associations.csv",
            [
                "timestamp_sim", "frame", "event_id", "candidate_vehicle_id",
                "candidate_plate", "partner_vehicle_id", "partner_plate",
                "candidate_probability", "candidate_status", "distance_m",
                "relative_speed_kmh", "peak_relative_speed_kmh",
                "peak_relative_speed_timestamp", "past_distance_m", "future_distance_m",
                "closing_distance_m", "post_separation_m", "approaching",
                "continued_separation", "candidate_pre_speed_kmh", "partner_pre_speed_kmh",
                "both_moving_before_event", "near_contact", "high_relative_motion",
                "hard_gate", "score", "decision", "event_timestamp",
                "gps_timestamp_candidate", "gps_timestamp_partner"
            ],
        )

        self.timeline_csv = self._csv(
            "multimodal_timeline.csv",
            [
                "timestamp_sim", "frame", "event_id", "event_type",
                "vehicle_id", "plate_number", "epc", "junction_id",
                "source", "confidence", "speed_kmh", "details_json"
            ],
        )

        self.timeline_jsonl = open(
            os.path.join(
                MULTIMODAL_OUT_DIR,
                "live_evidence_stream.jsonl",
            ),
            "a",
            encoding="utf-8",
        )

        for name, vehicle in vehicles.items():
            epc = self._epc_for(name)
            self.states[name] = {
                "vehicle": vehicle,
                "plate": PLATE_NUMBERS.get(name, name),
                "epc": epc,
                "detector": IMUCrashDetectorV2(
                    model_path,
                    sampling_rate=IMU_SAMPLING_RATE,
                ),
                "imu_samples": 0,
                "gps_samples": 0,
                "rfid_reads": 0,
                "max_crash_probability": 0.0,
                "crash_confirmed": False,
                "collision_involved": False,
                "first_crash_timestamp": None,
                "last_gps": None,
                "crash_gps": None,
                "post_crash_distance_m": 0.0,
                "post_crash_speed_kmh": 0.0,
                "escape_confirmed": False,
                "imu_inference_enabled_at": None,
                "imu_warmup_complete": False,
                "gps_history": deque(maxlen=240),
                # Recent model outputs are retained for temporal cross-vehicle
                # IMU corroboration.  This is evidence only; it never controls
                # CARLA vehicle physics.
                "imu_evidence_history": deque(maxlen=32),
                "last_imu_candidate": None,
                "last_pair_check_timestamp": None,
                "last_pair_confirmed_timestamp": None,
                "collision_partner": None,
            }

    def _csv(self, filename, fields):
        return CSVWriter(
            os.path.join(MULTIMODAL_OUT_DIR, filename),
            fields,
        )

    def _epc_for(self, name):
        # Stable EPC per simulated vehicle, independent of the plate.
        index = VEHICLE_IDS.index(name) + 1
        return f"E2000017221101{index:02X}{(0xA0B0 + index):04X}"

    def _event_id(self):
        with self.lock:
            self.event_seq += 1
            return f"MM-{self.event_seq:09d}"

    def start(self):
        bp_lib = self.world.get_blueprint_library()

        imu_bp = bp_lib.find("sensor.other.imu")
        imu_bp.set_attribute(
            "sensor_tick",
            str(IMU_SENSOR_TICK),
        )

        gnss_bp = bp_lib.find("sensor.other.gnss")
        gnss_bp.set_attribute(
            "sensor_tick",
            str(GNSS_SENSOR_TICK),
        )

        self.imu_worker.start()

        for name, state in self.states.items():
            vehicle = state["vehicle"]

            imu = self.world.spawn_actor(
                imu_bp,
                carla.Transform(),
                attach_to=vehicle,
                attachment_type=carla.AttachmentType.Rigid,
            )
            state["imu_sensor"] = imu
            self.sensors.append(imu)
            imu.listen(self._make_imu_callback(name))

            gnss = self.world.spawn_actor(
                gnss_bp,
                carla.Transform(),
                attach_to=vehicle,
                attachment_type=carla.AttachmentType.Rigid,
            )
            state["gnss_sensor"] = gnss
            self.sensors.append(gnss)
            gnss.listen(self._make_gnss_callback(name))

        print(
            f"[MULTIMODAL] GPS + IMU/GYRO attached to "
            f"{len(self.states)} vehicles at the same time"
        )
        print(
            f"[MULTIMODAL] IMU={IMU_SAMPLING_RATE}Hz "
            f"GNSS={1.0/GNSS_SENSOR_TICK:.0f}Hz"
        )
        print(
            "[MULTIMODAL] RFID readers: "
            + ", ".join(
                f"J{j}:RFID_J{j:02d}_01"
                for j in sorted(self.junctions)
            )
        )

        if LIVE_WS_URL:
            print(
                f"[LIVE WS] endpoint configured: {LIVE_WS_URL}"
            )
        else:
            print(
                "[LIVE WS] no endpoint configured; "
                "complete live evidence is still written to JSONL/CSV"
            )

    def _speed(self, vehicle):
        v = vehicle.get_velocity()
        return math.sqrt(
            v.x * v.x + v.y * v.y + v.z * v.z
        ) * 3.6

    def _make_imu_callback(self, name):
        def callback(measurement):
            state = self.states[name]
            vehicle = state["vehicle"]

            try:
                ax = measurement.accelerometer.x / 9.80665
                ay = measurement.accelerometer.y / 9.80665
                az = measurement.accelerometer.z / 9.80665

                gx = math.degrees(measurement.gyroscope.x)
                gy = math.degrees(measurement.gyroscope.y)
                gz = math.degrees(measurement.gyroscope.z)

                speed = self._speed(vehicle)
                timestamp = float(measurement.timestamp)
                frame = int(measurement.frame)

                state["imu_samples"] += 1

                self.imu_csv.write({
                    "timestamp_sim": f"{timestamp:.6f}",
                    "frame": frame,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "ax_g": f"{ax:.8f}",
                    "ay_g": f"{ay:.8f}",
                    "az_g": f"{az:.8f}",
                    "gx_deg_s": f"{gx:.6f}",
                    "gy_deg_s": f"{gy:.6f}",
                    "gz_deg_s": f"{gz:.6f}",
                    "speed_kmh": f"{speed:.6f}",
                })

                # Store the same raw sample in the explicit A-H archive.
                self.all_vehicle_imu_csv.write({
                    "timestamp_sim": f"{timestamp:.6f}",
                    "frame": frame,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "ax_g": f"{ax:.8f}",
                    "ay_g": f"{ay:.8f}",
                    "az_g": f"{az:.8f}",
                    "gx_deg_s": f"{gx:.6f}",
                    "gy_deg_s": f"{gy:.6f}",
                    "gz_deg_s": f"{gz:.6f}",
                    "speed_kmh": f"{speed:.6f}",
                })

                self.publisher.publish({
                    "type": "imu_reading",
                    "timestamp_sim": timestamp,
                    "frame": frame,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "accelerometer_g": {
                        "x": ax, "y": ay, "z": az
                    },
                    "gyroscope_deg_s": {
                        "x": gx, "y": gy, "z": gz
                    },
                    "speed_kmh": speed,
                })

                try:
                    self.imu_queue.put_nowait(
                        (
                            name,
                            ax, ay, az,
                            gx, gy, gz,
                            speed,
                            timestamp,
                            frame,
                        )
                    )
                except queue.Full:
                    pass

            except Exception as exc:
                self._error(
                    "IMU_CALLBACK",
                    name,
                    exc,
                )

        return callback

    def _gps_sample_near(self, vehicle_name, timestamp, tolerance=GPS_PAIR_TIME_TOLERANCE_S):
        history = self.states[vehicle_name]["gps_history"]
        if not history:
            return None
        best = min(history, key=lambda g: abs(g["timestamp"] - timestamp))
        if abs(best["timestamp"] - timestamp) > tolerance:
            return None
        return best

    @staticmethod
    def _gps_distance_m(a, b):
        # CARLA world coordinates are the authoritative simulated geometry for
        # association. Latitude/longitude are retained in the evidence record.
        return math.hypot(a["x"] - b["x"], a["y"] - b["y"])

    @staticmethod
    def _velocity_xy(gps):
        # CARLA yaw: 0 deg points +X; 90 deg points +Y.
        speed_mps = float(gps["speed_kmh"]) / 3.6
        heading = math.radians(float(gps["heading_deg"]))
        return speed_mps * math.cos(heading), speed_mps * math.sin(heading)

    def _relative_speed_kmh(self, a, b):
        avx, avy = self._velocity_xy(a)
        bvx, bvy = self._velocity_xy(b)
        return math.hypot(avx - bvx, avy - bvy) * 3.6

    @staticmethod
    def _speed_at(gps):
        return float(gps.get("speed_kmh", 0.0))

    def _pre_event_sample(self, vehicle_name, event_t):
        return self._gps_sample_near(
            vehicle_name,
            event_t - GPS_APPROACH_LOOKBACK_S,
            tolerance=0.45,
        )

    def _closing_distance_m(self, candidate_name, partner_name, timestamp):
        a_now = self._gps_sample_near(candidate_name, timestamp)
        b_now = self._gps_sample_near(partner_name, timestamp)
        if a_now is None or b_now is None:
            return None, None
        now_d = self._gps_distance_m(a_now, b_now)

        past_t = timestamp - GPS_APPROACH_LOOKBACK_S
        a_past = self._gps_sample_near(candidate_name, past_t, tolerance=0.45)
        b_past = self._gps_sample_near(partner_name, past_t, tolerance=0.45)
        if a_past is None or b_past is None:
            return now_d, None
        past_d = self._gps_distance_m(a_past, b_past)
        return now_d, past_d - now_d

    def _impact_signature(self, features, state, timestamp, name):
        """Return True only for a physically meaningful IMU shock.

        The ML probability alone is not enough.  This prevents a stationary
        nearby vehicle from becoming a collision partner merely because another
        vehicle received a moderate classifier score.
        """
        g_peak = float(features.get("g_force_peak", 0.0))
        jerk_peak = float(features.get("jerk_peak", 0.0))
        rotational = float(features.get("rotational_shock", 0.0))

        # Any two strong shock channels are sufficient.
        strong_channels = sum([
            g_peak >= IMU_IMPACT_G_MIN,
            jerk_peak >= IMU_IMPACT_JERK_MIN,
            rotational >= IMU_IMPACT_ROTATIONAL_MIN,
        ])
        if strong_channels >= 2:
            return True

        # A large speed discontinuity around the model event is an additional
        # impact signature.  Use GPS history rather than changing sensor data.
        history = state.get("gps_history")
        if history:
            past = self._gps_sample_near(
                name,
                timestamp - 0.75,
                tolerance=0.20,
            )
            current = self._gps_sample_near(
                name,
                timestamp,
                tolerance=0.20,
            )
            if past is not None and current is not None:
                if abs(float(past.get("speed_kmh", 0.0)) -
                       float(current.get("speed_kmh", 0.0))) >= IMU_IMPACT_SPEED_CHANGE_MIN_KMH:
                    return True

        return False

    def _recent_partner_imu_evidence(self, partner_name, timestamp):
        """Return strongest crash-like partner IMU evidence near an event."""
        history = self.states[partner_name].get("imu_evidence_history")
        if not history:
            return None

        best = None
        best_score = -1.0
        for e in history:
            dt = abs(float(e["timestamp"]) - float(timestamp))
            if dt > max(IMU_PARTNER_LOOKBACK_S, IMU_PARTNER_LOOKAHEAD_S):
                continue
            p = float(e["probability"])
            g = float(e["g_force_peak"])
            j = float(e["jerk_peak"])
            r = float(e["rotational_shock"])

            channels = int(g >= IMU_IMPACT_G_MIN) + int(
                j >= IMU_IMPACT_JERK_MIN
            ) + int(r >= IMU_IMPACT_ROTATIONAL_MIN)

            # Partner evidence must itself be meaningful.  Probability is
            # combined with physical shock channels.
            if p < IMU_PARTNER_MIN_PROB or channels < 2:
                continue

            score = channels * 2.0 + p - dt
            if score > best_score:
                best_score = score
                best = dict(e)

        return best

    def _find_collision_partner(self, candidate_name, timestamp, probability, status, frame):
        """IMU-first, temporally synchronized multimodal collision association.

        Primary rule:
          IMU candidate -> synchronized partner IMU evidence -> GPS contact.

        GPS alone can never create a collision event.  A high-confidence
        single-IMU fallback exists only for unusually strong primary IMU
        evidence with very tight geometry.
        """
        if probability < CRASH_CANDIDATE_MIN_PROB:
            return None
        if status not in ("IMU_IMPACT_CANDIDATE", "IMU_HIGH_CANDIDATE"):
            return None

        candidate_history = self.states[candidate_name]["gps_history"]
        if not candidate_history:
            return None

        window_start = timestamp - GPS_APPROACH_LOOKBACK_S
        window_end = timestamp + GPS_PAIR_TIME_TOLERANCE_S
        candidate_samples = [
            g for g in candidate_history
            if window_start <= g["timestamp"] <= window_end
        ]
        if not candidate_samples:
            return None

        ranked = []
        for partner_name in self.states:
            if partner_name == candidate_name:
                continue
            partner_history = self.states[partner_name]["gps_history"]
            if not partner_history:
                continue

            best = None
            max_relative_speed = 0.0
            max_relative_speed_timestamp = None

            for c in candidate_samples:
                p = self._gps_sample_near(
                    partner_name,
                    c["timestamp"],
                    tolerance=GPS_PAIR_TIME_TOLERANCE_S,
                )
                if p is None:
                    continue

                distance = self._gps_distance_m(c, p)
                relative_speed = self._relative_speed_kmh(c, p)

                if relative_speed > max_relative_speed:
                    max_relative_speed = relative_speed
                    max_relative_speed_timestamp = c["timestamp"]

                if distance > GPS_PAIR_MAX_DISTANCE_M:
                    continue

                if best is None or distance < best["distance_m"]:
                    best = {
                        "candidate_gps": c,
                        "partner_gps": p,
                        "distance_m": distance,
                        "relative_speed_kmh": relative_speed,
                    }

            if best is None:
                continue

            event_t = best["candidate_gps"]["timestamp"]
            past_t = event_t - GPS_APPROACH_LOOKBACK_S
            future_t = event_t + GPS_POST_IMPACT_LOOKAHEAD_S

            c_past = self._gps_sample_near(candidate_name, past_t, tolerance=0.45)
            p_past = self._gps_sample_near(partner_name, past_t, tolerance=0.45)
            c_future = self._gps_sample_near(candidate_name, future_t, tolerance=0.55)
            p_future = self._gps_sample_near(partner_name, future_t, tolerance=0.55)

            if c_past is None or p_past is None:
                continue

            past_distance = self._gps_distance_m(c_past, p_past)
            future_distance = (
                self._gps_distance_m(c_future, p_future)
                if c_future is not None and p_future is not None else None
            )

            closing = past_distance - best["distance_m"]
            post_separation = (
                future_distance - best["distance_m"]
                if future_distance is not None else None
            )

            candidate_pre_speed = self._speed_at(c_past)
            partner_pre_speed = self._speed_at(p_past)

            # The partner may already be braking/stopping because of the
            # collision.  Requiring both vehicles to exceed 6 km/h was the
            # reason the real A-B event was rejected.  The primary candidate
            # must be moving; the partner only needs demonstrable pre-event
            # motion.
            primary_moving = candidate_pre_speed >= GPS_PRIMARY_PRE_SPEED_MIN_KMH
            partner_was_moving = partner_pre_speed >= GPS_PARTNER_PRE_SPEED_MIN_KMH

            approaching = closing >= GPS_CLOSING_COLLISION_MIN_M
            continued_separation = (
                post_separation is not None
                and post_separation >= GPS_MIN_POST_SEPARATION_M
            )
            near_contact = best["distance_m"] <= GPS_COLLISION_DISTANCE_M
            high_relative_motion = max_relative_speed >= GPS_RELATIVE_SPEED_COLLISION_MIN_KMH
            strong_imu = probability >= CRASH_CANDIDATE_HIGH_PROB

            partner_imu = self._recent_partner_imu_evidence(
                partner_name, event_t
            )
            dual_imu = partner_imu is not None

            # Normal-confidence collision:
            #   1) primary IMU candidate
            #   2) partner also has crash-like IMU evidence in the same window
            #   3) tight GPS contact
            #   4) both vehicles had motion immediately before the event
            #   5) meaningful relative motion OR measurable closing
            dual_imu_gate = (
                dual_imu
                and near_contact
                and primary_moving
                and partner_was_moving
                and (high_relative_motion or approaching)
            )

            # Very high-confidence single-IMU fallback.
            single_imu_gate = (
                probability >= SINGLE_IMU_HIGH_PROB
                and best["distance_m"] <= SINGLE_IMU_MAX_DISTANCE_M
                and primary_moving
                and partner_was_moving
                and max_relative_speed >= SINGLE_IMU_MIN_RELATIVE_SPEED_KMH
                and closing >= SINGLE_IMU_MIN_CLOSING_M
            )

            hard_gate = dual_imu_gate or single_imu_gate

            score = 0
            score += 2 if dual_imu else 0
            score += 2 if near_contact else 0
            score += 1 if primary_moving else 0
            score += 1 if partner_was_moving else 0
            score += 1 if approaching else 0
            score += 1 if high_relative_motion else 0
            score += 1 if continued_separation else 0
            score += 1 if strong_imu else 0
            score += 2 if single_imu_gate else 0

            ranked.append({
                "partner": partner_name,
                "candidate_gps": best["candidate_gps"],
                "partner_gps": best["partner_gps"],
                "event_timestamp": event_t,
                "distance_m": best["distance_m"],
                "relative_speed_kmh": best["relative_speed_kmh"],
                "peak_relative_speed_kmh": max_relative_speed,
                "peak_relative_speed_timestamp": max_relative_speed_timestamp,
                "past_distance_m": past_distance,
                "future_distance_m": future_distance,
                "closing_distance_m": closing,
                "post_separation_m": post_separation,
                "approaching": approaching,
                "continued_separation": continued_separation,
                "candidate_pre_speed_kmh": candidate_pre_speed,
                "partner_pre_speed_kmh": partner_pre_speed,
                "both_moving_before_event": (
                    primary_moving and partner_was_moving
                ),
                "near_contact": near_contact,
                "high_relative_motion": high_relative_motion,
                "strong_imu": strong_imu,
                "partner_imu_evidence": partner_imu,
                "dual_imu": dual_imu,
                "primary_moving": primary_moving,
                "partner_was_moving": partner_was_moving,
                "single_imu_gate": single_imu_gate,
                "hard_gate": hard_gate,
                "score": score,
            })

        if not ranked:
            return None

        ranked.sort(key=lambda x: (-x["hard_gate"], -x["score"], x["distance_m"]))
        best = ranked[0]
        best["confirmed"] = bool(
            best["hard_gate"]
            and best["score"] >= GPS_PAIR_CONFIRMATION_SCORE
        )
        return best

    def _record_pair_association(self, candidate_name, timestamp, frame, probability, status, pair):
        partner = pair["partner"]
        event_id = self._event_id()
        decision = "COLLISION_CONFIRMED" if pair["confirmed"] else "PAIR_CANDIDATE"
        self.pair_csv.write({
            "timestamp_sim": f"{timestamp:.6f}",
            "frame": frame,
            "event_id": event_id,
            "candidate_vehicle_id": candidate_name,
            "candidate_plate": self.states[candidate_name]["plate"],
            "partner_vehicle_id": partner,
            "partner_plate": self.states[partner]["plate"],
            "candidate_probability": f"{probability:.8f}",
            "candidate_status": status,
            "distance_m": f"{pair['distance_m']:.4f}",
            "relative_speed_kmh": f"{pair['relative_speed_kmh']:.4f}",
            "peak_relative_speed_kmh": f"{pair.get('peak_relative_speed_kmh', pair['relative_speed_kmh']):.4f}",
            "peak_relative_speed_timestamp": "" if pair.get("peak_relative_speed_timestamp") is None else f"{pair['peak_relative_speed_timestamp']:.6f}",
            "past_distance_m": "" if pair.get("past_distance_m") is None else f"{pair['past_distance_m']:.4f}",
            "future_distance_m": "" if pair.get("future_distance_m") is None else f"{pair['future_distance_m']:.4f}",
            "closing_distance_m": "" if pair["closing_distance_m"] is None else f"{pair['closing_distance_m']:.4f}",
            "post_separation_m": "" if pair.get("post_separation_m") is None else f"{pair['post_separation_m']:.4f}",
            "approaching": int(pair["approaching"]),
            "continued_separation": int(pair.get("continued_separation", False)),
            "candidate_pre_speed_kmh": f"{pair.get('candidate_pre_speed_kmh', 0.0):.4f}",
            "partner_pre_speed_kmh": f"{pair.get('partner_pre_speed_kmh', 0.0):.4f}",
            "both_moving_before_event": int(pair.get("both_moving_before_event", False)),
            "near_contact": int(pair.get("near_contact", False)),
            "high_relative_motion": int(pair.get("high_relative_motion", False)),
            "hard_gate": int(pair.get("hard_gate", False)),
            "score": pair["score"],
            "decision": decision,
            "event_timestamp": f"{pair['event_timestamp']:.6f}",
            "gps_timestamp_candidate": f"{pair['candidate_gps']['timestamp']:.6f}",
            "gps_timestamp_partner": f"{pair['partner_gps']['timestamp']:.6f}",
        })
        self._timeline(
            timestamp, frame, "COLLISION_PAIR_ASSOCIATION", candidate_name,
            "IMU+GPS", min(1.0, pair["score"] / 5.0),
            candidate_gps_speed := pair["candidate_gps"]["speed_kmh"],
            {
                "partner_vehicle_id": partner,
                "partner_plate": self.states[partner]["plate"],
                "candidate_probability": probability,
                "candidate_status": status,
                "distance_m": pair["distance_m"],
                "relative_speed_kmh": pair["relative_speed_kmh"],
                "peak_relative_speed_kmh": pair.get("peak_relative_speed_kmh"),
                "peak_relative_speed_timestamp": pair.get("peak_relative_speed_timestamp"),
                "past_distance_m": pair.get("past_distance_m"),
                "future_distance_m": pair.get("future_distance_m"),
                "closing_distance_m": pair["closing_distance_m"],
                "post_separation_m": pair.get("post_separation_m"),
                "approaching": pair["approaching"],
                "continued_separation": pair.get("continued_separation", False),
                "candidate_pre_speed_kmh": pair.get("candidate_pre_speed_kmh"),
                "partner_pre_speed_kmh": pair.get("partner_pre_speed_kmh"),
                "both_moving_before_event": pair.get("both_moving_before_event", False),
                "near_contact": pair.get("near_contact", False),
                "high_relative_motion": pair.get("high_relative_motion", False),
                "hard_gate": pair.get("hard_gate", False),
                "score": pair["score"],
                "decision": decision,
                "event_timestamp": pair["event_timestamp"],
            },
        )
        return event_id

    def _imu_worker(self):
        while True:
            if self.imu_stop and self.imu_queue.empty():
                break

            try:
                item = self.imu_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            (
                name,
                ax, ay, az,
                gx, gy, gz,
                speed,
                timestamp,
                frame,
            ) = item

            state = self.states[name]

            try:
                detector = state["detector"]
                detector.set_speed(speed)

                # Sensor warm-up: preserve raw data, but do not populate the ML
                # feature window until the IMU stream has stabilized.
                if state["imu_inference_enabled_at"] is None:
                    state["imu_inference_enabled_at"] = timestamp + IMU_WARMUP_SECONDS
                    state["imu_warmup_complete"] = False
                    result = None
                elif timestamp < state["imu_inference_enabled_at"]:
                    result = None
                else:
                    if not state["imu_warmup_complete"]:
                        detector.reset()
                        state["imu_warmup_complete"] = True
                        self._timeline(
                            timestamp, frame, "IMU_WARMUP_COMPLETE", name,
                            "IMU", 1.0, speed,
                            {"warmup_seconds": IMU_WARMUP_SECONDS}
                        )

                    # Reject only inference windows with implausible sensor spikes.
                    # Raw values remain untouched in imu_raw_readings.csv.
                    if (
                        max(abs(ax), abs(ay), abs(az)) > IMU_MAX_PLAUSIBLE_G
                        or max(abs(gx), abs(gy), abs(gz)) > IMU_MAX_PLAUSIBLE_GYRO_DEG_S
                    ):
                        result = {
                            "crash_probability": 0.0,
                            "status": "GATE_SENSOR_TRANSIENT",
                            "is_crash": False,
                            "latency_ms": 0.0,
                            "features": {
                                "g_force_peak": math.sqrt(ax*ax + ay*ay + az*az),
                                "jerk_peak": 0.0,
                                "rotational_shock": abs(gx)+abs(gy)+abs(gz),
                            },
                        }
                    else:
                        result = detector.add_sample(
                            ax, ay, az,
                            gx, gy, gz,
                        )

                if result is not None:
                    probability = float(
                        result.get(
                            "crash_probability",
                            0.0,
                        )
                    )
                    status = str(
                        result.get(
                            "status",
                            "UNKNOWN",
                        )
                    )
                    is_crash = bool(
                        result.get(
                            "is_crash",
                            False,
                        )
                    )
                    features = result.get(
                        "features",
                        {},
                    )

                    state["max_crash_probability"] = max(
                        state["max_crash_probability"],
                        probability,
                    )

                    # Retain the complete recent IMU model evidence.  This is
                    # later used to determine whether another vehicle experienced
                    # a synchronized crash-like shock.
                    state["imu_evidence_history"].append({
                        "timestamp": timestamp,
                        "frame": frame,
                        "probability": probability,
                        "status": status,
                        "speed_kmh": float(speed),
                        "g_force_peak": float(features.get("g_force_peak", 0.0)),
                        "jerk_peak": float(features.get("jerk_peak", 0.0)),
                        "rotational_shock": float(features.get("rotational_shock", 0.0)),
                    })

                    # IMU is the FIRST gate.  Do not queue every moderate ML
                    # fluctuation.  A candidate must have both sufficient model
                    # probability and an impact-like physical signature.
                    impact_signature = self._impact_signature(features, state, timestamp, name)

                    if (
                        probability >= CRASH_CANDIDATE_MIN_PROB
                        and status in ("IMU_IMPACT_CANDIDATE", "IMU_HIGH_CANDIDATE")
                        and impact_signature
                    ):
                        last_pair_check = state.get("last_pair_check_timestamp")
                        if (
                            last_pair_check is None
                            or (timestamp - last_pair_check) >= GPS_PAIR_EVENT_COOLDOWN_S
                        ):
                            self.pending_pair_candidates.append({
                                "vehicle": name,
                                "timestamp": timestamp,
                                "frame": frame,
                                "probability": probability,
                                "status": status,
                                "features": dict(features),
                            })
                            state["last_imu_candidate"] = {
                                "timestamp": timestamp,
                                "probability": probability,
                                "status": status,
                                "features": dict(features),
                            }
                            state["last_pair_check_timestamp"] = timestamp

                    self.detection_csv.write({
                        "timestamp_sim": f"{timestamp:.6f}",
                        "frame": frame,
                        "vehicle_id": name,
                        "plate_number": state["plate"],
                        "epc": state["epc"],
                        "crash_probability": f"{probability:.8f}",
                        "status": status,
                        "is_crash": int(is_crash),
                        "speed_kmh": f"{speed:.6f}",
                        "latency_ms": f"{float(result.get('latency_ms', 0.0)):.3f}",
                        "g_force_peak": f"{float(features.get('g_force_peak', 0.0)):.8f}",
                        "jerk_peak": f"{float(features.get('jerk_peak', 0.0)):.8f}",
                        "rotational_shock": f"{float(features.get('rotational_shock', 0.0)):.8f}",
                    })

                    self._timeline(
                        timestamp,
                        frame,
                        "IMU_DETECTION",
                        name,
                        "IMU_MODEL",
                        probability,
                        speed,
                        {
                            "status": status,
                            "is_crash": is_crash,
                            "crash_probability": probability,
                            "g_force_peak": features.get(
                                "g_force_peak",
                                0.0,
                            ),
                            "jerk_peak": features.get(
                                "jerk_peak",
                                0.0,
                            ),
                            "rotational_shock": features.get(
                                "rotational_shock",
                                0.0,
                            ),
                        },
                    )

                    self.publisher.publish({
                        "type": "imu_detection",
                        "timestamp_sim": timestamp,
                        "frame": frame,
                        "vehicle_id": name,
                        "plate_number": state["plate"],
                        "epc": state["epc"],
                        "crash_probability": probability,
                        "status": status,
                        "is_crash": is_crash,
                        "speed_kmh": speed,
                        "features": {
                            "g_force_peak": features.get(
                                "g_force_peak",
                                0.0,
                            ),
                            "jerk_peak": features.get(
                                "jerk_peak",
                                0.0,
                            ),
                            "rotational_shock": features.get(
                                "rotational_shock",
                                0.0,
                            ),
                        },
                    })

            except Exception as exc:
                self._error(
                    "IMU_WORKER",
                    name,
                    exc,
                )

            finally:
                self.imu_queue.task_done()

    def process_pending_associations(self, current_timestamp=None):
        """Resolve IMU candidates after GPS has caught up to the event window."""
        if current_timestamp is None:
            current_timestamp = float(
                self.world.get_snapshot().timestamp.elapsed_seconds
            )

        if not self.pending_pair_candidates:
            return

        remaining = deque(maxlen=self.pending_pair_candidates.maxlen)

        while self.pending_pair_candidates:
            c = self.pending_pair_candidates.popleft()
            name = c["vehicle"]
            timestamp = c["timestamp"]
            frame = c["frame"]
            probability = c["probability"]
            status = c["status"]
            state = self.states[name]

            if state["crash_confirmed"]:
                continue

            # Wait for future GPS samples needed to evaluate post-impact separation.
            if current_timestamp < timestamp + GPS_PAIR_TIME_TOLERANCE_S:
                remaining.append(c)
                continue

            pair = self._find_collision_partner(
                name, timestamp, probability, status, frame
            )

            if pair is None:
                if current_timestamp < timestamp + 1.50:
                    remaining.append(c)
                continue

            self._record_pair_association(
                name, timestamp, frame, probability, status, pair
            )

            if not pair["confirmed"]:
                if current_timestamp < timestamp + 1.50:
                    remaining.append(c)
                continue

            pair_key = tuple(sorted((name, pair["partner"])))
            if pair_key in self.confirmed_collision_pairs:
                continue
            self.confirmed_collision_pairs.add(pair_key)

            event_timestamp = pair["event_timestamp"]

            state["crash_confirmed"] = True
            state["first_crash_timestamp"] = event_timestamp
            state["collision_partner"] = pair["partner"]
            state["last_pair_confirmed_timestamp"] = event_timestamp
            state["crash_gps"] = dict(pair["candidate_gps"])

            self._emit_crash_alert(
                name, timestamp, frame, probability,
                "COLLISION_EVENT_CONFIRMED_IMU_GPS", pair=pair
            )

            # Event-level partner association. This does NOT claim that the
            # partner's own IMU classifier independently fired.
            partner_name = pair["partner"]
            partner_state = self.states[partner_name]
            partner_state["crash_confirmed"] = True
            partner_state["first_crash_timestamp"] = event_timestamp
            partner_state["collision_partner"] = name
            partner_state["last_pair_confirmed_timestamp"] = event_timestamp
            partner_state["crash_gps"] = dict(pair["partner_gps"])

            reverse_pair = {
                **pair,
                "partner": name,
                "candidate_gps": pair["partner_gps"],
                "partner_gps": pair["candidate_gps"],
            }
            self._emit_crash_alert(
                partner_name, timestamp, frame, probability,
                "COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION",
                pair=reverse_pair,
            )

        self.pending_pair_candidates = remaining

    def _emit_crash_alert(
        self,
        name,
        timestamp,
        frame,
        probability,
        status,
        pair=None,
    ):
        state = self.states[name]
        # For a fused pair alert, use the GPS sample aligned to the inferred
        # collision event rather than the vehicle's later/current position.
        if pair is not None and pair.get("candidate_gps") is not None:
            gps = dict(pair["candidate_gps"])
            loc = carla.Location(
                x=float(gps.get("x", state["vehicle"].get_location().x)),
                y=float(gps.get("y", state["vehicle"].get_location().y)),
                z=float(gps.get("z", state["vehicle"].get_location().z)),
            )
        else:
            gps = state["last_gps"]
            loc = state["vehicle"].get_location()

        alert_id = self._event_id()

        self.alert_csv.write({
            "timestamp_sim": f"{timestamp:.6f}",
            "frame": frame,
            "alert_id": alert_id,
            "vehicle_id": name,
            "plate_number": state["plate"],
            "epc": state["epc"],
            "status": status,
            "crash_probability": f"{probability:.8f}",
            "gps_latitude": (
                "" if gps is None else f"{gps['latitude']:.10f}"
            ),
            "gps_longitude": (
                "" if gps is None else f"{gps['longitude']:.10f}"
            ),
            "gps_altitude": (
                "" if gps is None else f"{gps['altitude']:.4f}"
            ),
            "world_x": f"{loc.x:.6f}",
            "world_y": f"{loc.y:.6f}",
            "world_z": f"{loc.z:.6f}",
            "nearest_vehicle_id": "" if pair is None else pair.get("partner", ""),
            "nearest_plate": "" if pair is None else self.states[pair.get("partner")]["plate"],
            "pair_distance_m": "" if pair is None else f"{pair.get('distance_m', 0.0):.4f}",
            "relative_speed_kmh": "" if pair is None else f"{pair.get('relative_speed_kmh', 0.0):.4f}",
            "peak_relative_speed_kmh": "" if pair is None else f"{pair.get('peak_relative_speed_kmh', pair.get('relative_speed_kmh', 0.0)):.4f}",
            "closing_distance_m": "" if pair is None or pair.get("closing_distance_m") is None else f"{pair.get('closing_distance_m'):.4f}",
            "post_separation_m": "" if pair is None or pair.get("post_separation_m") is None else f"{pair.get('post_separation_m'):.4f}",
            "association_score": "" if pair is None else pair.get("score", 0),
            "collision_confirmed": 1,
        })

        self._timeline(
            timestamp,
            frame,
            "CRASH_ALERT",
            name,
            "IMU_ALERT",
            probability,
            self._speed(state["vehicle"]),
            {
                "alert_id": alert_id,
                "status": status,
                "crash_probability": probability,
                "gps": gps,
                "world_location": {
                    "x": loc.x,
                    "y": loc.y,
                    "z": loc.z,
                },
                "collision_partner": None if pair is None else pair.get("partner"),
                "pair_distance_m": None if pair is None else pair.get("distance_m"),
                "relative_speed_kmh": None if pair is None else pair.get("relative_speed_kmh"),
                "closing_distance_m": None if pair is None else pair.get("closing_distance_m"),
                "association_score": None if pair is None else pair.get("score"),
            },
        )

        self.publisher.publish({
            "type": "crash_alert",
            "timestamp_sim": timestamp,
            "frame": frame,
            "alert_id": alert_id,
            "vehicle_id": name,
            "plate_number": state["plate"],
            "epc": state["epc"],
            "status": status,
            "crash_probability": probability,
            "gps": gps,
            "world_location": {
                "x": loc.x,
                "y": loc.y,
                "z": loc.z,
            },
            "collision_partner": None if pair is None else pair.get("partner"),
            "pair_distance_m": None if pair is None else pair.get("distance_m"),
            "relative_speed_kmh": None if pair is None else pair.get("relative_speed_kmh"),
            "closing_distance_m": None if pair is None else pair.get("closing_distance_m"),
            "association_score": None if pair is None else pair.get("score"),
        })

        print(
            "\n"
            + "=" * 72
            + "\n"
            + f"[LIVE CRASH ALERT] vehicle={name} "
              f"plate={state['plate']} "
              f"EPC={state['epc']}\n"
            + f"[LIVE CRASH ALERT] timestamp={timestamp:.6f} "
              f"P(crash)={probability:.4f} "
              f"status={status}\n"
            + "=" * 72,
            flush=True,
        )

    def _make_gnss_callback(self, name):
        def callback(measurement):
            state = self.states[name]
            vehicle = state["vehicle"]

            try:
                timestamp = float(measurement.timestamp)
                frame = int(measurement.frame)

                loc = vehicle.get_location()
                speed = self._speed(vehicle)
                heading = (
                    vehicle.get_transform().rotation.yaw
                    % 360.0
                )

                gps = {
                    "timestamp": timestamp,
                    "frame": frame,
                    "latitude": float(measurement.latitude),
                    "longitude": float(measurement.longitude),
                    "altitude": float(measurement.altitude),
                    "speed_kmh": speed,
                    "heading_deg": heading,
                    "x": float(loc.x),
                    "y": float(loc.y),
                    "z": float(loc.z),
                }

                state["last_gps"] = gps
                state["gps_history"].append(gps)
                state["gps_samples"] += 1

                self.gps_csv.write({
                    "timestamp_sim": f"{timestamp:.6f}",
                    "frame": frame,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "latitude": f"{gps['latitude']:.10f}",
                    "longitude": f"{gps['longitude']:.10f}",
                    "altitude": f"{gps['altitude']:.4f}",
                    "speed_kmh": f"{speed:.6f}",
                    "heading_deg": f"{heading:.6f}",
                    "world_x": f"{loc.x:.6f}",
                    "world_y": f"{loc.y:.6f}",
                    "world_z": f"{loc.z:.6f}",
                })

                self.publisher.publish({
                    "type": "gps_reading",
                    "timestamp_sim": timestamp,
                    "frame": frame,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "latitude": gps["latitude"],
                    "longitude": gps["longitude"],
                    "altitude": gps["altitude"],
                    "speed_kmh": speed,
                    "heading_deg": heading,
                    "world_location": {
                        "x": loc.x,
                        "y": loc.y,
                        "z": loc.z,
                    },
                })

                self._post_crash_gps(name, gps)

            except Exception as exc:
                self._error(
                    "GNSS_CALLBACK",
                    name,
                    exc,
                )

        return callback

    def _post_crash_gps(self, name, gps):
        state = self.states[name]
        reference = state["crash_gps"]

        if reference is None:
            return

        dx = gps["x"] - reference["x"]
        dy = gps["y"] - reference["y"]
        distance = math.hypot(dx, dy)

        state["post_crash_distance_m"] = max(
            state["post_crash_distance_m"],
            distance,
        )
        state["post_crash_speed_kmh"] = gps["speed_kmh"]

        moving = gps["speed_kmh"] >= 5.0
        escaped = (
            moving
            and state["post_crash_distance_m"] >= 8.0
        )

        if escaped and not state["escape_confirmed"]:
            state["escape_confirmed"] = True

            self._timeline(
                gps["timestamp"],
                gps["frame"],
                "POST_CRASH_ESCAPE",
                name,
                "GPS",
                1.0,
                gps["speed_kmh"],
                {
                    "distance_from_crash_m": distance,
                    "speed_kmh": gps["speed_kmh"],
                    "moving_after_crash": True,
                    "escape_confirmed": True,
                },
            )

            self.publisher.publish({
                "type": "vehicle_state",
                "timestamp_sim": gps["timestamp"],
                "frame": gps["frame"],
                "vehicle_id": name,
                "plate_number": state["plate"],
                "epc": state["epc"],
                "state": "POST_CRASH_MOVING",
                "speed_kmh": gps["speed_kmh"],
                "distance_from_crash_m": distance,
                "escape_confirmed": True,
            })

            print(
                f"[GPS ESCAPE] vehicle={name} "
                f"speed={gps['speed_kmh']:.1f}km/h "
                f"distance_from_crash={distance:.1f}m",
                flush=True,
            )

    def update_rfid(self):
        """
        Synchronous simulated RFID reader update.

        RFID is a separate evidence stream. It does not identify a vehicle
        from camera ground truth and does not affect the crash detector.
        """

        snapshot = self.world.get_snapshot()
        timestamp = float(snapshot.timestamp.elapsed_seconds)
        frame = int(snapshot.frame)

        for junction_id, junction in self.junctions.items():

            center = junction.bounding_box.location
            reader_id = f"RFID_J{junction_id:02d}_01"

            for name, state in self.states.items():

                vehicle = state["vehicle"]

                if not vehicle.is_alive:
                    continue

                loc = vehicle.get_location()

                distance = hdist(loc, center)

                if distance > RFID_READ_RADIUS_M:
                    self.rfid_seen[(name, junction_id)] = False
                    continue

                key = (name, junction_id)

                previous = self.rfid_last.get(key)

                if (
                    previous is not None
                    and timestamp - previous
                    < RFID_MIN_READ_INTERVAL_S
                ):
                    continue

                self.rfid_last[key] = timestamp

                if (
                    self.random_read()
                    > RFID_READ_PROBABILITY
                ):
                    continue

                confidence = max(
                    0.50,
                    1.0 - (
                        distance
                        / RFID_READ_RADIUS_M
                    ) * 0.25,
                )

                event_id = self._event_id()
                speed = self._speed(vehicle)

                self.rfid_csv.write({
                    "timestamp_sim": f"{timestamp:.6f}",
                    "event_id": event_id,
                    "junction_id": f"J{junction_id:02d}",
                    "reader_id": reader_id,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "timestamp_reader": f"{timestamp:.6f}",
                    "distance_m": f"{distance:.6f}",
                    "speed_kmh": f"{speed:.6f}",
                    "confidence": f"{confidence:.6f}",
                    "status": "READ",
                })

                state["rfid_reads"] += 1

                details = {
                    "distance_m": distance,
                    "reader_range_m": RFID_READ_RADIUS_M,
                    "simulated": True,
                    "status": "READ",
                }

                self._timeline(
                    timestamp,
                    frame,
                    "RFID_READ",
                    name,
                    "RFID",
                    confidence,
                    speed,
                    details,
                    junction_id=f"J{junction_id:02d}",
                )

                self.publisher.publish({
                    "type": "rfid_reading",
                    "timestamp_sim": timestamp,
                    "frame": frame,
                    "event_id": event_id,
                    "junction_id": f"J{junction_id:02d}",
                    "reader_id": reader_id,
                    "vehicle_id": name,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "distance_m": distance,
                    "speed_kmh": speed,
                    "confidence": confidence,
                    "status": "READ",
                })

                print(
                    f"[LIVE RFID] J{junction_id} "
                    f"reader={reader_id} "
                    f"vehicle={name} "
                    f"plate={state['plate']} "
                    f"EPC={state['epc']} "
                    f"t={timestamp:.3f}",
                    flush=True,
                )

    def random_read(self):
        # Local deterministic RNG; avoids global random state changes.
        return random.random()

    def _timeline(
        self,
        timestamp,
        frame,
        event_type,
        vehicle_id,
        source,
        confidence,
        speed,
        details,
        junction_id="",
    ):
        state = self.states[vehicle_id]
        event_id = self._event_id()

        row = {
            "timestamp_sim": f"{timestamp:.6f}",
            "frame": frame,
            "event_id": event_id,
            "event_type": event_type,
            "vehicle_id": vehicle_id,
            "plate_number": state["plate"],
            "epc": state["epc"],
            "junction_id": junction_id,
            "source": source,
            "confidence": f"{float(confidence):.8f}",
            "speed_kmh": f"{float(speed):.6f}",
            "details_json": json.dumps(
                details,
                separators=(",", ":"),
            ),
        }

        self.timeline_csv.write(row)

        self.timeline_jsonl.write(
            json.dumps(
                {
                    "timestamp_sim": timestamp,
                    "frame": frame,
                    "event_id": event_id,
                    "event_type": event_type,
                    "vehicle_id": vehicle_id,
                    "plate_number": state["plate"],
                    "epc": state["epc"],
                    "junction_id": junction_id,
                    "source": source,
                    "confidence": float(confidence),
                    "speed_kmh": float(speed),
                    "details": details,
                },
                separators=(",", ":"),
            )
            + "\n"
        )
        self.timeline_jsonl.flush()

        return event_id

    def publish_camera_frame(
        self,
        junction_number,
        frame,
        frame_id,
        timestamp_sim,
    ):
        """
        Publish the SAME processed frame used for MP4 recording.
        Therefore the live camera stream and saved MP4 both contain the
        number-plate overlay generated by draw_all_number_plates().
        All expensive work (resize, JPEG encode, base64) happens later on the
        publisher worker thread — this call only throttles and hands off the
        raw frame, so the CARLA main loop is never blocked by encoding.
        """

        try:
            # Throttle BEFORE any expensive work. The saved MP4 keeps ~20 FPS;
            # the live stream is capped at LIVE_STREAM_MIN_INTERVAL_S per frame.
            now = time.monotonic()
            last = self._last_camera_publish.get(junction_number)
            if last is not None and (now - last) < LIVE_STREAM_MIN_INTERVAL_S:
                return
            self._last_camera_publish[junction_number] = now

            message = {
                "type": "camera_frame",
                "timestamp_sim": float(timestamp_sim),
                "frame": int(frame_id),
                "camera_id": f"CAM_J{junction_number:02d}_01",
                "junction_id": f"J{junction_number:02d}",
                "encoding": "jpeg_base64",
                "has_number_plate_overlay": True,
                # Raw BGR frame; encoded on the publisher worker thread.
                "_raw_frame": frame,
            }

            self.publisher.publish_camera(int(junction_number), message)

        except Exception as exc:
            self._error(
                "CAMERA_PUBLISH",
                f"J{junction_number}",
                exc,
            )

    def status(self):
        result = {}

        for name, state in self.states.items():
            result[name] = {
                "imu_samples": state["imu_samples"],
                "gps_samples": state["gps_samples"],
                "rfid_reads": state["rfid_reads"],
                "max_crash_probability": state[
                    "max_crash_probability"
                ],
                "crash_confirmed": state[
                    "crash_confirmed"
                ],
                "post_crash_distance_m": state[
                    "post_crash_distance_m"
                ],
                "post_crash_speed_kmh": state[
                    "post_crash_speed_kmh"
                ],
                "escape_confirmed": state[
                    "escape_confirmed"
                ],
                "imu_warmup_complete": state["imu_warmup_complete"],
                "collision_partner": state["collision_partner"],
                "last_pair_confirmed_timestamp": state["last_pair_confirmed_timestamp"],
            }

        return result

    def _error(self, component, vehicle_id, exc):
        try:
            path = os.path.join(
                MULTIMODAL_OUT_DIR,
                "multimodal_errors.log",
            )
            with open(
                path,
                "a",
                encoding="utf-8",
            ) as f:
                f.write(
                    f"{time.time():.6f} "
                    f"{component} "
                    f"{vehicle_id} "
                    f"{type(exc).__name__}: {exc}\n"
                )
        except Exception:
            pass

    def close(self):
        print(
            "[MULTIMODAL] stopping IMU/GNSS sensors...",
            flush=True,
        )

        for sensor in self.sensors:
            try:
                sensor.stop()
            except Exception:
                pass

        # Stop accepting new IMU work after sensor callbacks have been stopped.
        time.sleep(0.25)

        # Drain the detector queue before destroying actors.
        try:
            self.imu_queue.join()
        except Exception:
            pass

        self.imu_stop = True

        if self.imu_worker.is_alive():
            self.imu_worker.join(timeout=20.0)

        if self.imu_worker.is_alive():
            print(
                "[MULTIMODAL] WARNING: IMU worker did not stop cleanly",
                flush=True,
            )

        for sensor in reversed(self.sensors):
            try:
                if sensor.is_alive:
                    sensor.destroy()
            except Exception:
                pass

        self.publisher.close()

        try:
            self.timeline_jsonl.flush()
            self.timeline_jsonl.close()
        except Exception:
            pass

        for writer in (
            self.imu_csv,
            self.all_vehicle_imu_csv,
            self.gps_csv,
            self.rfid_csv,
            self.detection_csv,
            self.alert_csv,
            self.pair_csv,
            self.timeline_csv,
        ):
            try:
                writer.close()
            except Exception:
                pass

        print(
            "[MULTIMODAL] complete. Raw GPS/IMU/RFID + model alerts saved.",
            flush=True,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# ASYNC VIDEO ENCODING
# Keeps MP4 encoding off the CARLA simulation/control thread.
# ---------------------------------------------------------------------------
VIDEO_QUEUE_MAX = 12

class AsyncVideoWriter:
    """One asynchronous queue for independent J1/J2/J3 MP4 writers."""
    def __init__(self, writers):
        self.writers = dict(writers)
        self.q = queue.Queue(maxsize=VIDEO_QUEUE_MAX)
        self.stop = False
        self.thread = threading.Thread(target=self._run, name="mp4-writer", daemon=False)
        self.thread.start()

    def _run(self):
        while not self.stop or not self.q.empty():
            try:
                item = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is None:
                self.q.task_done()
                break
            try:
                junction, frame = item
                writer = self.writers.get(int(junction))
                if writer is not None:
                    writer.write(frame)
            except Exception as exc:
                print(f"[ASYNC VIDEO ERROR] {type(exc).__name__}: {exc}", flush=True)
            finally:
                self.q.task_done()

    def write(self, junction, frame):
        item = (int(junction), frame.copy())
        try:
            self.q.put_nowait(item)
        except queue.Full:
            # Video is the only lossy channel. Sensor/evidence records are never
            # dropped because of encoder pressure.
            try:
                old = self.q.get_nowait()
                self.q.task_done()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(item)
            except queue.Full:
                pass

    def close(self):
        try:
            self.q.join()
        finally:
            self.stop = True
            self.thread.join(timeout=10.0)
            for writer in self.writers.values():
                try:
                    writer.release()
                except Exception:
                    pass



def get_camera_location_for_junction(
    junction_id,
    road_point,
    forward,
    right,
):
    """
    Camera placement:
      J1 = 35 m farther back on the same road-relative axis.
      J2 = existing placement.
      J3 = existing placement shifted 6 m to camera-right.
    """
    if junction_id == 1:
        distance = CAMERA_DISTANCE + J1_CAMERA_BACK_OFFSET_M
        return road_point - forward * distance

    if junction_id == 3:
        distance = CAMERA_DISTANCE
        return (
            road_point
            - forward * distance
            + right * LATERAL_OFFSET[3]
        )

    return road_point - forward * CAMERA_DISTANCE


def main():
    print("[SCRIPT] RUNNING:", os.path.abspath(__file__))
    print("[SCRIPT] VERSION: V27_REFINED_IMU_DUAL_EVIDENCE")

    client = carla.Client(HOST, PORT)
    client.set_timeout(20.0)
    world = client.get_world()

    if world.get_map().name.split("/")[-1] != MAP_NAME:
        print(f"[MAP] Loading {MAP_NAME}...")
        world = client.load_world(MAP_NAME)
        time.sleep(2.0)

    map_obj = world.get_map()
    planner = GlobalRoutePlanner(map_obj, 2.0)
    print("[ROUTER] GlobalRoutePlanner ready")

    # Traffic Manager is used ONLY for secondary traffic C-H. A/B stay under
    # direct VehicleControl so TM collision avoidance cannot suppress the real
    # A/B impact.
    tm = client.get_trafficmanager(8000)
    tm.set_synchronous_mode(True)
    try:
        tm.set_random_device_seed(19)
    except Exception:
        pass

    # Fresh actor set: do not allow previous test vehicles to affect this run.
    for actor in world.get_actors().filter("vehicle.*"):
        try:
            actor.destroy()
        except Exception:
            pass

    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = DT
    settings.no_rendering_mode = False
    # Physics substeps consistent with 0.05s fixed simulation step.
    try:
        settings.substepping = True
        settings.max_substep_delta_time = 0.01
        settings.max_substeps = 5
    except Exception:
        pass
    world.apply_settings(settings)

    vehicle_pool = build_vehicle_pool(world)
    vehicles = {}
    controllers = {}
    secondary_routes = {}
    secondary_tm_released = set()
    cameras = {}
    writers = {}
    sensors = []
    frame_counts = {1: 0, 2: 0, 3: 0}
    writer_errors = set()
    lock = threading.Lock()
    camera_models = {}
    vehicle_bbox_geometries = {}
    vehicle_transform_history = {}
    history_limit = 180

    # Camera callbacks MUST NOT run OpenCV drawing or MP4 encoding. CARLA
    # invokes sensor callbacks from asynchronous sensor threads. We only copy
    # the newest raw frame here; the synchronous main loop renders/writes it.
    latest_camera_frames = {1: None, 2: None, 3: None}
    latest_camera_frame_ids = {1: -1, 2: -1, 3: -1}
    last_written_frame_ids = {1: -1, 2: -1, 3: -1}
    last_camera_report = time.time()

    collision = {
        "seen": False,
        "event": None,
        "location": None,
        "impulse": None,
        "a_id": None,
        "b_id": None,
        # Live-backend publisher + actor identity for the instant physics        # crash_alert. Filled in after the multimodal system is created.
        "publisher": None,
        "actor_name": None,
        "actor_plate": None,
        "partner_name": None,
        "partner_plate": None,
    }

    # Integrated multimodal evidence system.
    multimodal = None

    try:
        # ---------------------------------------------------------------
        # Junctions
        # ---------------------------------------------------------------
        j1 = find_junction(map_obj, JUNCTIONS[1]["id"], JUNCTIONS[1]["location"])
        j2 = find_junction(map_obj, JUNCTIONS[2]["id"], JUNCTIONS[2]["location"])
        j3 = find_junction(map_obj, JUNCTIONS[3]["id"], JUNCTIONS[3]["location"])
        if not all((j1, j2, j3)):
            raise RuntimeError("Could not locate J1, J2 and J3 on the active map.")

        print(f"[J1] center={j1.bounding_box.location}")
        print(f"[J2] center={j2.bounding_box.location}")
        print(f"[J3] center={j3.bounding_box.location}")

        # ---------------------------------------------------------------
        # Cameras - exact user geometry
        # ---------------------------------------------------------------
        # Sensor callbacks only copy raw frames. All OpenCV rendering/encoding
        # happens later in the main synchronous simulation thread.
        print("========== CAMERAS ==========")
        os.makedirs(OUT_DIR, exist_ok=True)
        for n in (1, 2, 3):
            bp = world.get_blueprint_library().find("sensor.camera.rgb")
            bp.set_attribute("image_size_x", "1280")
            bp.set_attribute("image_size_y", "720")
            bp.set_attribute("fov", str(CAMERA_FOV))
            bp.set_attribute("sensor_tick", str(DT))
            tf = camera_transform(world, n, JUNCTIONS[n]["location"])
            cam = world.spawn_actor(bp, tf)
            camera_models[n] = build_camera_model(tf, 1280, 720, CAMERA_FOV)
            # Recording is preserved: the processed frame (including the
            # improved plate overlay) is written to MP4 after rendering.
            path = os.path.join(
                OUT_DIR,
                f"camera_junction_{n}_v22_final_visible_anpr_recording.mp4"
            )
            writer = cv2.VideoWriter(
                path,
                cv2.VideoWriter_fourcc(*"mp4v"),
                FPS, (1280, 720),
            )
            if not writer.isOpened():
                raise RuntimeError(f"Could not open video writer for camera {n}: {path}")

            def callback(image, junction_number=n):
                try:
                    frame = np.frombuffer(
                        image.raw_data, dtype=np.uint8
                    ).reshape((image.height, image.width, 4))[:, :, :3].copy()
                    with lock:
                        latest_camera_frames[junction_number] = frame
                        latest_camera_frame_ids[junction_number] = image.frame
                except Exception as exc:
                    # Do not silently swallow callback failures. Record them so
                    # the main thread can report them during shutdown.
                    writer_errors.add(junction_number)
                    print(
                        f"[CAMERA CALLBACK ERROR J{junction_number}] "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )

            cam.listen(callback)
            cameras[n] = cam
            writers[n] = writer
            if n == 1:
                print(
                    f"[CAMERA J1] moved {J1_CAMERA_BACK_OFFSET_M:.1f}m farther back "
                    f"(total road-relative distance={CAMERA_DISTANCE + J1_CAMERA_BACK_OFFSET_M:.1f}m)"
                )
            print(f"[CAMERA J{n}] {cam.get_transform()}")
            print(
                f"[CAMERA J{n} RECORDING] "
                f"1280x720 -> {path}",
                flush=True
            )


        # MP4 encoding is asynchronous so it cannot stall the CARLA tick or
        # starve any of the three live camera publishers.
        async_video = AsyncVideoWriter(writers)

        def transform_state_for_frame(frame_id):
            """Return actor transform snapshots matching the camera frame when possible."""
            if frame_id in vehicle_transform_history:
                return dict(vehicle_transform_history[frame_id])
            if not vehicle_transform_history:
                return {}
            nearest = min(vehicle_transform_history.keys(), key=lambda f: abs(f - frame_id))
            return dict(vehicle_transform_history[nearest])

        def record_latest_camera_frames():
            """Render/write each newest camera frame on the main thread."""
            for n in (1, 2, 3):
                with lock:
                    frame = latest_camera_frames[n]
                    frame_id = latest_camera_frame_ids[n]
                    last_id = last_written_frame_ids[n]
                if frame is None:
                    continue
                if frame_id <= last_id:
                    continue
                try:
                    # Copy before releasing the lock so the callback can safely
                    # replace the latest frame while drawing/encoding occurs.
                    frame = frame.copy()
                    frame_state = transform_state_for_frame(frame_id)
                    draw_all_number_plates(
                        frame,
                        camera_models[n],
                        frame_state,
                        vehicle_bbox_geometries
                    )
                    # Each writer belongs to exactly one junction:
                    # writers[1] -> J1, writers[2] -> J2, writers[3] -> J3.
                    async_video.write(n, frame)
                    if multimodal is not None:
                        try:
                            multimodal.publish_camera_frame(
                                n,
                                frame,
                                frame_id,
                                float(
                                    world.get_snapshot().timestamp.elapsed_seconds
                                ),
                            )
                        except Exception as _exc:
                            print(
                                f"[LIVE CAMERA PUBLISH ERROR J{n}] "
                                f"{type(_exc).__name__}: {_exc}",
                                flush=True,
                            )
                    frame_counts[n] += 1
                    last_written_frame_ids[n] = frame_id
                except Exception as exc:
                    writer_errors.add(n)
                    print(
                        f"[CAMERA RECORD ERROR J{n} frame={frame_id}] "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )

        # ---------------------------------------------------------------
        # A/B topology selection with J2/J3 feasibility check
        # ---------------------------------------------------------------
        selected = select_crossing_with_b_corridor(j1, planner, j2, j3)
        A = selected["a"]
        B = selected["b"]
        collision_point = selected["collision_point"]
        corridor_from_j1_exit = selected["corridor"]

        # Use the same 45m upstream selection that was validated above.
        a_spawn_wp, a_upstream = backtrack_lane(A["entry"], 45.0)
        b_spawn_wp, b_upstream = backtrack_lane(B["entry"], 45.0)
        print(f"[A/B SPAWN] upstream A={a_upstream:.1f}m B={b_upstream:.1f}m")

        # Spawn A/B on their actual approach lanes.
        for idx, (name, wp) in enumerate((("A", a_spawn_wp), ("B", b_spawn_wp))):
            v = spawn_vehicle(world, vehicle_pool[idx], wp)
            if v is None:
                raise RuntimeError(f"Could not spawn {name} on selected J1 lane")
            v.set_autopilot(False)
            vehicles[name] = v
            vehicle_bbox_geometries[name] = cache_vehicle_bbox_geometry(v)
            vehicle_bbox_geometries[name]["plate_geometry"] = make_3d_plate_candidates(vehicle_bbox_geometries[name])
            print(f"[SPAWN] {name}: {v.get_location()} yaw={v.get_transform().rotation.yaw:.1f} | PLATE={PLATE_NUMBERS[name]}")

        collision["a_id"] = vehicles["A"].id
        collision["b_id"] = vehicles["B"].id
        # The multimodal evidence system owns the live WS publisher. It is        # created later, so the collision sensors are attached first with a        # placeholder and the publisher is injected right after creation.
        sensors.append(attach_ab_collision_sensor(world, vehicles["A"], collision))
        sensors.append(attach_ab_collision_sensor(world, vehicles["B"], collision))

        # Build exact lane-following routes from actual spawned positions to the paired exits.
        route_a = planner_route(planner, vehicles["A"].get_location(), A["exit"].transform.location)
        route_b = planner_route(planner, vehicles["B"].get_location(), B["exit"].transform.location)
        if len(route_a) < 10 or len(route_b) < 10:
            raise RuntimeError("A/B approach routes are unexpectedly short; refusing to start scenario.")

        route_a = extend_forward(map_obj, route_a, 10)
        route_b = extend_forward(map_obj, route_b, 10)
        controllers["A"] = RouteController(vehicles["A"], route_a, 7.0)
        controllers["B"] = RouteController(vehicles["B"], route_b, 7.0)
        controllers["A"].enabled = True
        controllers["B"].enabled = True

        # ---------------------------------------------------------------
        # Other vehicles: one connected route through their assigned junction.
        # They remain disabled until the scene is safe to release them.
        # ---------------------------------------------------------------
        used = [vehicles["A"].get_location(), vehicles["B"].get_location()]
        # Secondary traffic is placed farther upstream so it has enough road
        # distance to arrive at J2/J3 while B is approaching. D/E are the
        # guaranteed J2 pair; G/H are the guaranteed J3 pair. F is an extra
        # J2 vehicle that can be released after D has crossed.
        assignments = (
            ("C", j1, 50.0),
            ("D", j2, 72.0),
            ("E", j2, 86.0),
            ("F", j2, 90.0),
            ("G", j3, 72.0),
            ("H", j3, 86.0),
        )
        for idx, (name, junction, preferred) in enumerate(assignments, start=2):
            wp = find_safe_approach_spawn(map_obj, junction, used, preferred)
            if wp is None:
                raise RuntimeError(f"Could not find a safe approach lane for {name}")
            v = spawn_vehicle(world, vehicle_pool[idx % len(vehicle_pool)], wp)
            if v is None:
                raise RuntimeError(f"Could not spawn {name}")
            v.set_autopilot(False)
            used.append(v.get_location())
            vehicles[name] = v
            vehicle_bbox_geometries[name] = cache_vehicle_bbox_geometry(v)
            vehicle_bbox_geometries[name]["plate_geometry"] = make_3d_plate_candidates(vehicle_bbox_geometries[name])

            route = build_single_junction_route(planner, map_obj, junction, wp, extension_points=45)
            secondary_routes[name] = [t.location for t in route]
            controllers[name] = RouteController(v, route, 6.2)
            controllers[name].enabled = False
            print(f"[SPAWN] {name}: {v.get_location()} -> J{1 if name == 'C' else 2 if name in 'DEF' else 3} | PLATE={PLATE_NUMBERS[name]}")

        # ---------------------------------------------------------------
        # MULTIMODAL LIVE SENSOR START
        # ---------------------------------------------------------------
        # All A-H vehicles receive IMU/GNSS observation sensors.
        # RFID is simulated at J1/J2/J3 in update_rfid() after each world tick.
        # This does not alter vehicle control or physics.
        crash_model_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "crash_detector_v2.pkl",
        )
        if not os.path.exists(crash_model_path):
            # Also support the common project model location.
            candidates = (
                r"d:\FINAL_PROJECT\crash_detector_v2.pkl",
                r"d:\FINAL_PROJECT\models\crash_detector_v2.pkl",
            )
            for candidate in candidates:
                if os.path.exists(candidate):
                    crash_model_path = candidate
                    break

        if not os.path.exists(crash_model_path):
            raise FileNotFoundError(
                "crash_detector_v2.pkl not found. "
                "Put it beside this script or set the path in the code."
            )

        multimodal = MultimodalEvidence(
            world=world,
            vehicles=vehicles,
            junctions={
                1: j1,
                2: j2,
                3: j3,
            },
            model_path=crash_model_path,
        )
        multimodal.start()

        # Wire the live publisher into the collision state so the physics        # collision sensor can emit the crash alert the instant it fires.
        collision["publisher"] = multimodal.publisher
        collision["actor_name"] = "A"
        collision["actor_plate"] = PLATE_NUMBERS.get("A", "N/A")
        collision["partner_name"] = "B"
        collision["partner_plate"] = PLATE_NUMBERS.get("B", "N/A")

        # ---------------------------------------------------------------
        # Validate B corridor before the simulation starts.
        # ---------------------------------------------------------------
        b_j2_exit = corridor_from_j1_exit["j2_exit"]
        b_j3_exit = corridor_from_j1_exit["j3_exit"]
        print("========== B CORRIDOR PRECHECK ==========")
        print(f"J2 exit waypoint={b_j2_exit.transform.location} yaw={b_j2_exit.transform.rotation.yaw:.1f}")
        print(f"J3 exit waypoint={b_j3_exit.transform.location} yaw={b_j3_exit.transform.rotation.yaw:.1f}")
        print("[PASS] J1 B exit can reach J2 and J3 using the GlobalRoutePlanner")

        # Milestones are set when a vehicle actually enters a junction radius.
        milestones = {k: False for k in (
            "C_J1", "D_J2", "E_J2", "F_J2", "G_J3", "H_J3", "B_J2", "B_J3"
        )}
        releases = {k: False for k in ("C", "D", "E", "F", "G", "H", "J2", "J3")}
        live_encounter = {"J2": False, "J3": False}
        collision_handled = False
        
        b_post_route = False
        b_recovery_active = False
        b_recovery_index = 0
        b_recovery_frames = 0
        a_stop_confirmed = False
        b_continue_confirmed = False
        impact_reference = None

        def release_secondary_tm(name):
            """Hand a secondary vehicle to CARLA Traffic Manager on its fixed route."""
            if name in secondary_tm_released:
                return
            vehicle = vehicles[name]
            path = secondary_routes.get(name, [])
            if not path:
                raise RuntimeError(f"No prepared TM path for secondary vehicle {name}")

            vehicle.set_autopilot(True, tm.get_port())
            tm.set_path(vehicle, path)
            try:
                tm.auto_lane_change(vehicle, False)
            except Exception:
                pass
            try:
                tm.distance_to_leading_vehicle(vehicle, 8.0)
                tm.vehicle_percentage_speed_difference(vehicle, -8.0)
                tm.ignore_vehicles_percentage(vehicle, 0.0)
                tm.ignore_walkers_percentage(vehicle, 0.0)
                # Keep the staged traffic flowing through the monitored junctions.
                tm.ignore_lights_percentage(vehicle, 100.0)
            except Exception:
                pass
            secondary_tm_released.add(name)
            controllers[name].enabled = True
            print(f"[TM RELEASE] {name}: fixed path enabled ({len(path)} points)")

        # ---------------------------------------------------------------
        # Synchronous scenario
        # ---------------------------------------------------------------
        print("========== SCENARIO START ==========")
        start_wall = time.time()
        last_status = 0.0

        while time.time() - start_wall < TIMEOUT:
            # ---------- A/B pre-impact timing controller ----------
            if not collision["seen"]:
                da = controllers["A"].distance_to_location_along_route(collision_point)
                db = controllers["B"].distance_to_location_along_route(collision_point)

                # Common target impact time based on the farther vehicle.
                # Speeds remain in normal vehicle-control range.
                common_time = max(1.0, max(da, db) / 7.0)
                desired_a = max(4.5, min(9.0, da / common_time if common_time > 0 else 7.0))
                desired_b = max(4.5, min(9.0, db / common_time if common_time > 0 else 7.0))

                # Final approach: do not brake merely because one car is a few
                # metres closer. Instead match their estimated impact times.
                controllers["A"].update(target_speed=desired_a, allow_stop=False, lookahead=5)
                controllers["B"].update(target_speed=desired_b, allow_stop=False, lookahead=5)

                # Hard safety gate only if one vehicle gets excessively far ahead.
                if da < 5.0 and db > 9.0:
                    controllers["A"].update(target_speed=2.5, allow_stop=False, lookahead=4)
                elif db < 5.0 and da > 9.0:
                    controllers["B"].update(target_speed=2.5, allow_stop=False, lookahead=4)

            # ---------- After real collision ----------
            if collision["seen"] and not collision_handled:
                collision_handled = True
                impact_reference = collision["location"]

                # A stops only now, after the sensor event.
                controllers["A"].stop()
                a_stop_confirmed = speed_mps(vehicles["A"]) < 0.8

                # IMPORTANT:
                # Do NOT build B's post-crash route from its displaced physics
                # position. The collision can push B onto the footpath/curb.
                # Instead, continue from the prevalidated B driving-lane
                # corridor and temporarily recover B to that lane.
                r_to_j2 = corridor_from_j1_exit["route_to_j2"]
                r_j2_to_j3 = corridor_from_j1_exit["route_to_j3"]
                r_tail = extend_forward(map_obj, r_j2_to_j3, 35)

                full = append_route(route_b, r_to_j2)
                full = append_route(full, r_j2_to_j3)
                full = append_route(full, r_tail)

                if len(full) < 25:
                    raise RuntimeError(
                        "B's validated J1->J2->J3 road route is unexpectedly short."
                    )

                controllers["B"].set_route(full)
                controllers["B"].enabled = True
                b_post_route = True

                # Start the temporary lane-recovery phase. The normal route
                # controller is NOT updated during this phase, so two steering
                # controllers never fight each other.
                b_recovery_active = True
                b_recovery_index = 0
                b_recovery_frames = 0

                print(
                    f"[HIT-AND-RUN] B validated ROAD route installed: "
                    f"{len(full)} points"
                )
                print(
                    f"[HIT-AND-RUN] B J2 min distance="
                    f"{route_min_distance(r_to_j2, j2.bounding_box.location):.1f}m"
                )
                print(
                    f"[HIT-AND-RUN] B J3 min distance="
                    f"{route_min_distance(r_j2_to_j3, j3.bounding_box.location):.1f}m"
                )

            # B continues after impact.
            if collision_handled and b_post_route:
                if b_recovery_active:
                    (
                        aligned,
                        b_recovery_index,
                        lateral_error,
                        heading_error,
                    ) = b_recover_to_validated_lane(
                        vehicles["B"],
                        controllers["B"].route,
                        b_recovery_index,
                    )

                    b_recovery_frames += 1

                    if aligned or b_recovery_frames >= B_RECOVERY_MAX_FRAMES:
                        b_recovery_active = False
                        # Resume the existing road-route controller only after
                        # recovery. Use short lookahead to avoid cutting the
                        # J2/J3 corners.
                        controllers["B"].index = max(
                            controllers["B"].index,
                            b_recovery_index,
                        )
                        print(
                            f"[B ROAD RECOVERY] complete: "
                            f"lateral={lateral_error:.2f}m "
                            f"heading={heading_error:.1f}deg "
                            f"frames={b_recovery_frames}"
                        )
                    elif b_recovery_frames % 10 == 0:
                        print(
                            f"[B ROAD RECOVERY] lateral={lateral_error:.2f}m "
                            f"heading={heading_error:.1f}deg "
                            f"frame={b_recovery_frames}"
                        )

                if not b_recovery_active:
                    controllers["B"].update(
                        target_speed=6.5,
                        allow_stop=False,
                        lookahead=4
                    )

                if (
                    impact_reference is not None
                    and hdist(
                        vehicles["B"].get_location(),
                        impact_reference
                    ) > 12.0
                ):
                    b_continue_confirmed = True

            # ---------- Stage visible traffic before B arrives ----------
            # B is allowed to run toward the next junction normally until it
            # enters a staging gate. The required secondary vehicles are then
            # started early enough to reach the junction, while B waits just
            # outside if necessary. This guarantees that B meets live traffic
            # rather than an empty junction.
            b_loc = vehicles["B"].get_location()

            if collision_handled and not releases["C"] and hdist(b_loc, j1.bounding_box.location) > 28.0:
                releases["C"] = True
                release_secondary_tm("C")
                print("[RELEASE] C -> J1")

            # Start the J2 pair when B is still well upstream.
            b_j2_dist = hdist(b_loc, j2.bounding_box.location)
            if collision_handled and b_j2_dist <= 100.0:
                if not releases["J2"]:
                    releases["J2"] = True
                    release_secondary_tm("D")
                    release_secondary_tm("E")
                    print("[RELEASE] D/E -> J2 (Traffic Manager collision avoidance)")

            # Start the J3 pair while B is still far enough away for them to
            # enter the junction before B reaches it.
            b_j3_dist = hdist(b_loc, j3.bounding_box.location)
            if collision_handled and b_j3_dist <= 105.0:
                if not releases["J3"]:
                    releases["J3"] = True
                    release_secondary_tm("G")
                    release_secondary_tm("H")
                    print("[RELEASE] G/H -> J3 (Traffic Manager collision avoidance)")

            # J2/J3 live-traffic observation.
            #
            # IMPORTANT:
            # Do not artificially slow B to 1.0 m/s at these junctions.
            # That previous gate made the post-crash vehicle crawl even when
            # the road was physically clear. B already receives its normal
            # post-crash target speed above.
            #
            # We still measure nearby moving traffic so the experiment records
            # whether B encountered live traffic, but traffic presence does not
            # change B's speed here.
            j2_moving = moving_vehicles_near_junction(
                vehicles, ("D", "E"), j2, radius=32.0, min_speed_mps=0.8
            )

            j3_moving = moving_vehicles_near_junction(
                vehicles, ("G", "H"), j3, radius=32.0, min_speed_mps=0.8
            )

            if collision_handled and b_j2_dist <= 36.0:
                print(
                    f"[J2 TRAFFIC] B speed preserved at normal post-crash speed; "
                    f"moving={j2_moving or 'none'}"
                )

            if collision_handled and b_j3_dist <= 36.0:
                print(
                    f"[J3 TRAFFIC] B speed preserved at normal post-crash speed; "
                    f"moving={j3_moving or 'none'}"
                )

            # F is an additional J2 vehicle. Release it after D has entered
            # J2, keeping three vehicles available around this junction without
            # forcing a simultaneous spawn rush.
            if milestones["D_J2"] and not releases["F"]:
                releases["F"] = True
                release_secondary_tm("F")
                print("[RELEASE] F -> J2 (Traffic Manager collision avoidance)")

            # Exactly one world tick per simulation step.
            try:
                current_frame = int(world.tick())
                frame_state = {}
                for vehicle_name, vehicle in vehicles.items():
                    try:
                        frame_state[vehicle_name] = transform_tuple(vehicle.get_transform())
                    except Exception as exc:
                        print(
                            f"[TRANSFORM SNAPSHOT WARNING] {vehicle_name}: "
                            f"{type(exc).__name__}: {exc}", flush=True
                        )
                vehicle_transform_history[current_frame] = frame_state
                while len(vehicle_transform_history) > history_limit:
                    oldest = next(iter(vehicle_transform_history))
                    del vehicle_transform_history[oldest]
            except Exception as exc:
                print(
                    f"[WORLD TICK ERROR] type={type(exc).__name__} "
                    f"message={exc}",
                    flush=True,
                )
                raise

            # Camera sensor callbacks have now produced the newest images.
            # Perform overlay rendering and video encoding only on this main
            # synchronous thread.
            record_latest_camera_frames()

            if multimodal is not None:
                multimodal.update_rfid()
                multimodal.process_pending_associations(
                    float(world.get_snapshot().timestamp.elapsed_seconds)
                )

            # ---------- Milestones after physics tick ----------
            milestone_checks = (
                ("C", j1, "C_J1"),
                ("D", j2, "D_J2"),
                ("E", j2, "E_J2"),
                ("F", j2, "F_J2"),
                ("G", j3, "G_J3"),
                ("H", j3, "H_J3"),
                ("B", j2, "B_J2"),
                ("B", j3, "B_J3"),
            )
            for name, junction, key in milestone_checks:
                if hdist(vehicles[name].get_location(), junction.bounding_box.location) <= 18.0:
                    milestones[key] = True

            # Permanent record of the actual B/traffic encounters.
            if collision_handled:
                if (
                    hdist(vehicles["B"].get_location(), j2.bounding_box.location) <= 36.0
                    and len(moving_vehicles_near_junction(vehicles, ("D", "E"), j2, 32.0, 0.8)) >= 2
                ):
                    live_encounter["J2"] = True
                if (
                    hdist(vehicles["B"].get_location(), j3.bounding_box.location) <= 36.0
                    and len(moving_vehicles_near_junction(vehicles, ("G", "H"), j3, 32.0, 0.8)) >= 2
                ):
                    live_encounter["J3"] = True

            if collision_handled:
                a_stop_confirmed = a_stop_confirmed or speed_mps(vehicles["A"]) < 0.8

            if time.time() - last_status >= 2.5:
                last_status = time.time()
                print("\n[STATUS]")
                for name in VEHICLE_IDS:
                    v = vehicles[name]
                    print(
                        f" {name}: ({v.get_location().x:7.1f},{v.get_location().y:7.1f}) "
                        f"speed={speed_kmh(v):5.1f} km/h "
                        f"enabled={controllers[name].enabled} "
                        f"TM={name in secondary_tm_released} "
                        f"route={controllers[name].index}/{len(controllers[name].route)}"
                    )
                print(
                    f" [A/B] collision={collision['seen']} "
                    f"impact_dist_A={hdist(vehicles['A'].get_location(), collision_point):.1f} "
                    f"impact_dist_B={hdist(vehicles['B'].get_location(), collision_point):.1f}"
                )
                print(
                    " [MILESTONES] " + ", ".join(
                        f"{k}={v}" for k, v in milestones.items()
                    )
                )
                live_j2_now = moving_vehicles_near_junction(vehicles, ("D", "E"), j2, 32.0, 0.8)
                live_j3_now = moving_vehicles_near_junction(vehicles, ("G", "H"), j3, 32.0, 0.8)
                print(f" [LIVE J2 NOW] {live_j2_now}")
                print(f" [LIVE J3 NOW] {live_j3_now}")
                print(f" [ENCOUNTER] J2={live_encounter['J2']} J3={live_encounter['J3']}")
                print(
                    f" [LIVE CAMERAS] J1={frame_counts[1]} frames, "
                    f"J2={frame_counts[2]} frames, J3={frame_counts[3]} frames "
                    f"(all three streams active)"
                )

                if multimodal is not None:
                    _mm = multimodal.status()
                    for _vn in VEHICLE_IDS:
                        if _vn in _mm:
                            _s = _mm[_vn]
                            print(
                                f" [MM {_vn}] "
                                f"IMU={_s['imu_samples']} "
                                f"GPS={_s['gps_samples']} "
                                f"RFID={_s['rfid_reads']} "
                                f"maxP={_s['max_crash_probability']:.4f} "
                                f"crash={_s['crash_confirmed']} "
                                f"escape={_s['escape_confirmed']}"
                            )

            # Finish only after collision + B reaches J3 + all secondary traffic.
            if collision["seen"] and b_continue_confirmed and milestones["B_J3"]:
                secondary_done = all(milestones[k] for k in (
                    "C_J1", "D_J2", "E_J2", "F_J2", "G_J3", "H_J3"
                ))
                j2_encounter_ok = live_encounter["J2"]
                j3_encounter_ok = live_encounter["J3"]
                if secondary_done and j2_encounter_ok and j3_encounter_ok:
                    print("[SCENARIO] ALL REQUESTED MILESTONES + LIVE-TRAFFIC ENCOUNTERS COMPLETED")
                    break

        # Finalize any queued IMU/GPS associations before reporting results.
        if multimodal is not None:
            try:
                for _ in range(20):
                    now_sim = float(world.get_snapshot().timestamp.elapsed_seconds)
                    multimodal.process_pending_associations(now_sim)
                    if not multimodal.pending_pair_candidates:
                        break
                    world.tick()
            except Exception as exc:
                print(
                    f"[PENDING ASSOCIATION FINALIZATION] "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        # ---------------------------------------------------------------
        # Validation
        # ---------------------------------------------------------------
        print("\n========== FINAL VALIDATION ==========")
        print(f"Vehicles spawned: {len(vehicles)}/8")
        print(f"A/B REAL PHYSICS COLLISION: {'PASS' if collision['seen'] else 'FAIL'}")
        print(f"A stopped after collision: {'PASS' if a_stop_confirmed else 'FAIL'}")
        print(f"B continued after collision: {'PASS' if b_continue_confirmed else 'FAIL'}")
        for key, label in (
            ("B_J2", "B passed J2"),
            ("B_J3", "B passed J3"),
            ("C_J1", "C passed J1"),
            ("D_J2", "D passed J2"),
            ("E_J2", "E passed J2"),
            ("F_J2", "F passed J2"),
            ("G_J3", "G passed J3"),
            ("H_J3", "H passed J3"),
        ):
            print(f"{label}: {'PASS' if milestones[key] else 'FAIL'}")
        print(f"J2 had >=2 moving vehicles when B entered: {'PASS' if live_encounter['J2'] else 'FAIL'}")
        print(f"J3 had >=2 moving vehicles when B entered: {'PASS' if live_encounter['J3'] else 'FAIL'}")
        print(f"Video recording: {'PASS' if not writer_errors and all(frame_counts.values()) else 'FAIL'}")
        print(f"Camera frames: {frame_counts}")
        print("========================================")

        # Machine-readable final validation contract for the website/paper.
        try:
            mm_status = multimodal.status() if multimodal is not None else {}
            confirmed_pairs = sorted([list(p) for p in (multimodal.confirmed_collision_pairs if multimodal is not None else set())])
            summary = {
                "version": "V27_REFINED_IMU_DUAL_EVIDENCE",
                "ground_truth": {"physical_collision_pairs": [["A", "B"]]},
                "camera_frames": frame_counts,
                "video_recording_ok": bool(not writer_errors and all(frame_counts.values())),
                "confirmed_collision_pairs": confirmed_pairs,
                "confirmed_collision_event_count": len(confirmed_pairs),
                "vehicle_status": mm_status,
                "association_policy": {
                    "imu_candidate_probability_min": CRASH_CANDIDATE_MIN_PROB,
                    "gps_max_distance_m": GPS_PAIR_MAX_DISTANCE_M,
                    "gps_near_distance_m": GPS_PAIR_NEAR_DISTANCE_M,
                    "min_relative_speed_kmh": GPS_MIN_RELATIVE_SPEED_KMH,
                    "min_pre_event_speed_kmh": GPS_MIN_PRE_EVENT_SPEED_KMH,
                    "min_closing_m": GPS_MIN_APPROACH_CLOSING_M,
                    "min_post_separation_m": GPS_MIN_POST_SEPARATION_M,
                    "required_score": GPS_PAIR_CONFIRMATION_SCORE,
                    "partner_imu_required_for_normal_confidence": True,
                    "partner_imu_min_probability": IMU_PARTNER_MIN_PROB,
                    "impact_signature": {
                        "g_force_min": IMU_IMPACT_G_MIN,
                        "jerk_min": IMU_IMPACT_JERK_MIN,
                        "rotational_min": IMU_IMPACT_ROTATIONAL_MIN,
                    },
                },
                "live_stream_contract": {
                    "junctions": ["J1", "J2", "J3"],
                    "websocket_endpoint_configured": bool(LIVE_WS_URL),
                    "camera_message_type": "camera_frame",
                    "evidence_message_types": ["imu_reading", "imu_detection", "gps_reading", "rfid_reading", "crash_alert", "vehicle_state"],
                },
            }
            with open(os.path.join(MULTIMODAL_OUT_DIR, "final_validation_summary.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
        except Exception as exc:
            print(f"[FINAL SUMMARY ERROR] {type(exc).__name__}: {exc}", flush=True)

    finally:

        if multimodal is not None:
            try:
                multimodal.close()
            except Exception as exc:
                print(
                    f"[MULTIMODAL CLEANUP ERROR] "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        print("[CLEANUP] Destroying actors...")
        for sensor in sensors:
            try:
                if sensor.is_alive:
                    sensor.stop()
                    sensor.destroy()
            except Exception:
                pass
        for camera in cameras.values():
            try:
                if camera.is_alive:
                    camera.stop()
                    camera.destroy()
            except Exception:
                pass
        try:
            if 'async_video' in locals() and async_video is not None:
                async_video.close()
            else:
                for writer in writers.values():
                    try:
                        writer.release()
                    except Exception:
                        pass
        except Exception as exc:
            print(f"[ASYNC VIDEO CLEANUP ERROR] {type(exc).__name__}: {exc}", flush=True)
        for vehicle in vehicles.values():
            try:
                if vehicle.is_alive:
                    vehicle.destroy()
            except Exception:
                pass
        try:
            tm.set_synchronous_mode(False)
        except Exception:
            pass
        try:
            world.apply_settings(original_settings)
        except Exception:
            pass
        print("[CLEANUP] Done.")


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        # Never lose the actual exception when launched from an IDE/task runner.
        print("[FATAL]", type(exc).__name__, str(exc), flush=True)
        traceback.print_exc()
        try:
            log_path = os.path.join("d:\\FINAL_PROJECT\\debug_frames", "run_scenario_last_error.log")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as log:
                traceback.print_exc(file=log)
        except Exception:
            pass
        raise
