"""
Routine violation pipeline: one record per MOTORCYCLE (a group of tracker
fragments), a SET of violation types per vehicle, plate OCR only after
duplicates are merged, one evidence image per vehicle.

  decode thread   Media Foundation (hardware) decode; skipped frames are only
                  grab()bed, processed frames are retrieve()d and downscaled to
                  work_width immediately
        |  (small frame + the full frame, kept only until its crops are cut)
  main thread     COCO YOLO11n person+motorcycle on the iGPU (OpenVINO, static
  (serial)        batch of 4), camera-motion compensation (optical flow),
                  member2 tracker for motorcycles and persons, rider <-> bike
                  association, full-res crops cut right away (rider heads for
                  the helmet check, vehicle crops for plates), then the full
                  frame is dropped. Helmet mosaics run after each batch; a
                  rider is no longer checked once settled (K verdicts).
        v
  finalize        riderless / parked filter (logged per track), fragment merge
                  (spatio-temporal + appearance, union-find; merge.py) BEFORE
                  plate OCR, plate detection on pooled vehicle crops, staged
                  recognition-only OCR on the top-N sharpest crops with early
                  stop, character voting + regional prior, confident-plate
                  merge, evidence images, merge report + contact sheets,
                  summary.json/csv, plate_debug.log, stage timing table
"""

from __future__ import annotations

import csv
import json
import math
import queue
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np

from app.services.evidence_render import (  # noqa: F401  (colours re-exported)
    BLACK,
    BLUE,
    GREEN,
    RED,
    WHITE,
    YELLOW,
    draw_plate_evidence,
    scale_unit,
)
from app.services.plate_validation import (
    format_plate,
    parse_plate,
    regional_prior,
    validate_plate,
    vote_characters,
)
from app.services.anpr_partial import analyze_reads as analyze_partial_plate
from app.services.routine_violation_video import models, plate_ocr
from app.services.routine_violation_video.config import DEFAULT_CONFIG, RoutineConfig
from app.services.routine_violation_video.merge import (  # noqa: F401  (re-exported for tests)
    VehicleTrack,
    chain_affine,
    co_visible_conflict,
    combine,
    compose,
    merge_by_plate,
    merge_into,
    merge_tracks,
    pair_score,
    plates_near_equal,
    warp_box,
)

# Reuse the project's existing tracker (member2/tracking/tracker.py).
_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.append(str(_PROJECT_ROOT))
from member2.detection.detector import BoundingBox, DetectionResult  # noqa: E402
from member2.tracking.tracker import MultiObjectTracker  # noqa: E402

COCO_PERSON, COCO_MOTORCYCLE = 0, 3
VIOLATION_NO_HELMET = "NO HELMET"
VIOLATION_TRIPLE_RIDING = "TRIPLE RIDING"
HELMET_RIDER, HELMET_WITH, HELMET_WITHOUT = 1, 2, 3


# ============================================================
# TIMING
# ============================================================

class StageTimer:
    ORDER = ("video decode", "vehicle detection", "helmet detection", "tracking",
             "merge", "plate detection", "OCR", "evidence rendering")

    def __init__(self):
        self.seconds: dict[str, float] = defaultdict(float)
        self.calls: dict[str, int] = defaultdict(int)
        self.lock = threading.Lock()

    def add(self, stage, seconds, calls=1):
        with self.lock:
            self.seconds[stage] += seconds
            self.calls[stage] += calls

    def table(self, wall):
        lines = [f"{'stage':22s} {'seconds':>8s} {'calls':>6s}"]
        for stage in self.ORDER:
            lines.append(f"{stage:22s} {self.seconds.get(stage, 0.0):8.1f} {self.calls.get(stage, 0):6d}")
        lines.append(f"{'TOTAL (wall clock)':22s} {wall:8.1f}")
        stream = getattr(self, "phase_stream", None)
        if stream is not None:
            lines.append(f"  = streaming {stream:.1f}s (decode | detect+track+helmet in parallel)"
                         f" + finalize {wall - stream:.1f}s (merge, plates, OCR, evidence)")
        lines.append("video decode runs in its own thread, in parallel with the other stages;"
                     " OCR runs several vehicles in parallel, so its seconds are summed across threads")
        return "\n".join(lines)

    def as_dict(self):
        return {s: {"seconds": round(self.seconds.get(s, 0.0), 2), "calls": self.calls.get(s, 0)}
                for s in self.ORDER}


# ============================================================
# GEOMETRY
# ============================================================

def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def _intersection(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _touches_edge(b, width, height, margin):
    return b[0] <= margin or b[1] <= margin or b[2] >= width - margin or b[3] >= height - margin


def rider_on_motorcycle(person, moto) -> float:
    """Score (0 = not riding) that a person sits on this motorcycle: body over
    the bike, horizontally inside it, overlapping it substantially. A person
    standing beside a bike fails the horizontal/overlap tests."""
    px1, py1, px2, py2 = person
    mx1, my1, mx2, my2 = moto
    mw, mh = mx2 - mx1, my2 - my1
    cx = (px1 + px2) / 2.0
    if not (mx1 - 0.10 * mw <= cx <= mx2 + 0.10 * mw):
        return 0.0
    if py1 > my1 + 0.35 * mh:            # head must be above the bike's upper part
        return 0.0
    if py2 < my1 + 0.15 * mh:            # body must reach down onto the bike
        return 0.0
    overlap = _intersection(person, moto) / max(1.0, _area(person))
    if overlap < 0.25:
        return 0.0
    return overlap


def warp_point(point, affine):
    if affine is None:
        return point
    out = cv2.transform(np.array([[point]], dtype=np.float32), affine)[0][0]
    return float(out[0]), float(out[1])


class CameraMotion:
    """Camera motion between processed frames from sparse optical flow on
    background features (detected objects are masked out): a global affine
    for tracking compensation, plus the flow vectors so a vehicle's motion
    can be compared with the background right around it."""

    def __init__(self, width):
        self.prev = None
        self.scale = 320.0 / width
        self.points = np.zeros((0, 2), np.float32)
        self.flow = np.zeros((0, 2), np.float32)

    def local_motion(self, box, affine):
        x1, y1, x2, y2 = box
        w, h = x2 - x1, y2 - y1
        if len(self.points):
            px, py = self.points[:, 0], self.points[:, 1]
            inside = (px > x1) & (px < x2) & (py > y1) & (py < y2)
            near = ((px > x1 - 1.0 * w) & (px < x2 + 1.0 * w)
                    & (py > y2 - 0.25 * h) & (py < y2 + 0.5 * h) & ~inside)
            if near.sum() < 5:
                near = ((px > x1 - 1.0 * w) & (px < x2 + 1.0 * w) & (py > y1 - 0.5 * h)
                        & (py < y2 + 0.5 * h) & ~inside)
            if near.sum() >= 5:
                dx, dy = np.median(self.flow[near], axis=0)
                return float(dx), float(dy)
        cx, cy = _center(box)
        wx, wy = warp_point((cx, cy), affine)
        return wx - cx, wy - cy

    def update(self, small, boxes):
        gray = cv2.cvtColor(cv2.resize(small, None, fx=self.scale, fy=self.scale), cv2.COLOR_BGR2GRAY)
        affine = None
        self.points = np.zeros((0, 2), np.float32)
        self.flow = np.zeros((0, 2), np.float32)
        if self.prev is not None:
            mask = np.full(self.prev.shape, 255, np.uint8)
            for b in boxes:
                x1, y1, x2, y2 = [int(v * self.scale) for v in b]
                mask[max(0, y1):y2, max(0, x1):x2] = 0
            pts = cv2.goodFeaturesToTrack(self.prev, 150, 0.01, 7, mask=mask)
            if pts is not None and len(pts) >= 12:
                nxt, status, _ = cv2.calcOpticalFlowPyrLK(self.prev, gray, pts, None)
                good = status.reshape(-1) == 1
                self.points = pts[good].reshape(-1, 2) / self.scale
                self.flow = (nxt[good] - pts[good]).reshape(-1, 2) / self.scale
                if good.sum() >= 10:
                    m, _ = cv2.estimateAffinePartial2D(pts[good], nxt[good], method=cv2.RANSAC,
                                                       ransacReprojThreshold=2.0)
                    if m is not None:
                        m = m.astype(np.float64)
                        m[:, 2] /= self.scale
                        affine = m
        self.prev = gray
        return affine


# ============================================================
# RIDERS / HELMET
# ============================================================

@dataclass
class RiderStats:
    helmet: int = 0
    no_helmet: int = 0
    unknown: int = 0
    checks: int = 0
    per_frame: dict = field(default_factory=dict)   # frame -> "helmet"|"no_helmet"|"unknown"
    motos: Counter = field(default_factory=Counter)

    @property
    def judged(self):
        return self.helmet + self.no_helmet

    def settled(self, cfg: RoutineConfig) -> bool:
        """Enough verdicts either way: stop re-checking this rider."""
        return (self.no_helmet >= cfg.helmet_settle_k or self.helmet >= cfg.helmet_settle_k
                or self.checks >= cfg.helmet_max_checks)


def rider_is_violator(stats: RiderStats, cfg: RoutineConfig) -> bool:
    """Temporal rule: K no-helmet frames, or >= ratio of judged frames with at
    least ratio_min_frames of them. One-frame flickers never qualify."""
    if stats.no_helmet >= cfg.no_helmet_min_frames:
        return True
    return (stats.judged >= cfg.no_helmet_ratio_min_frames
            and stats.no_helmet >= cfg.no_helmet_ratio_min_frames
            and stats.no_helmet / stats.judged >= cfg.no_helmet_min_ratio)


def violation_types(vehicle: VehicleTrack, riders: dict, cfg: RoutineConfig) -> dict[str, list[int]]:
    """The SET of violations of one vehicle -> event frames per type. Rider
    tracks can fragment while the bike's group is stable, so helmet checks
    are also pooled over the bike's riders."""
    found: dict[str, list[int]] = {}
    stats = [riders[pid] for pid in vehicle.riders if pid in riders]
    no_helmet_frames = sorted({f for s in stats for f, v in s.per_frame.items() if v == "no_helmet"})
    pooled = RiderStats(helmet=sum(s.helmet for s in stats), no_helmet=sum(s.no_helmet for s in stats))
    if any(rider_is_violator(s, cfg) for s in stats) or rider_is_violator(pooled, cfg):
        found[VIOLATION_NO_HELMET] = no_helmet_frames
    if cfg.triple_riding:
        accepted = set(vehicle.riders)
        crowded = sorted(f for f, pids in vehicle.frame_riders.items() if len(set(pids) & accepted) >= 3)
        if len(crowded) >= cfg.triple_riding_min_frames:
            found[VIOLATION_TRIPLE_RIDING] = crowded
    return found


def judge_head(dets, region):
    """Helmet state of the head in one mosaic tile: the most confident
    head-type detection whose centre lies in the tile's upper-middle part."""
    x1, y1, x2, y2 = region
    w, h = x2 - x1, y2 - y1
    best = None
    for cls, conf, (bx1, by1, bx2, by2) in dets:
        if cls not in (HELMET_RIDER, HELMET_WITH, HELMET_WITHOUT):
            continue
        cx, cy = (bx1 + bx2) / 2, (by1 + by2) / 2
        if not (x1 + 0.10 * w <= cx <= x2 - 0.10 * w and y1 <= cy <= y1 + 0.80 * h):
            continue
        if best is None or conf > best[1]:
            best = (cls, conf)
    if best is None:
        return "unknown"
    return "helmet" if best[0] == HELMET_WITH else "no_helmet"


def _head_box(pbox):
    x1, y1, x2, y2 = pbox
    w, h = x2 - x1, y2 - y1
    return (x1 + 0.2 * w, y1, x2 - 0.2 * w, y1 + 0.3 * h)


def _head_crop(frame, pbox, scale):
    x1, y1, x2, y2 = pbox
    w, h = x2 - x1, y2 - y1
    region = [int(v * scale) for v in (x1 - 0.10 * w, y1 - 0.08 * h, x2 + 0.10 * w, y1 + 0.42 * h)]
    H, W = frame.shape[:2]
    region = [max(0, region[0]), max(0, region[1]), min(W, region[2]), min(H, region[3])]
    if region[2] - region[0] < 16 or region[3] - region[1] < 16:
        return None
    return frame[region[1]:region[3], region[0]:region[2]].copy()


def run_helmet_mosaics(requests, helmet_model, riders, cfg, timer):
    """Pack head crops into mosaics (tiles_per_side^2 per model call)."""
    tile, side = cfg.helmet_tile, cfg.helmet_tiles_per_side
    per_call = side * side
    for start in range(0, len(requests), per_call):
        chunk = requests[start:start + per_call]
        mosaic = np.full((tile * side, tile * side, 3), 114, np.uint8)
        placed = []
        for slot, (frame_index, pid, crop) in enumerate(chunk):
            r, c = divmod(slot, side)
            sc = tile / max(crop.shape[:2])
            resized = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)), max(1, int(crop.shape[0] * sc))))
            y0, x0 = r * tile, c * tile
            mosaic[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
            placed.append((frame_index, pid, (x0, y0, x0 + resized.shape[1], y0 + resized.shape[0])))
        t0 = time.perf_counter()
        result = helmet_model.predict(mosaic, imgsz=tile * side, conf=cfg.helmet_conf)[0]
        timer.add("helmet detection", time.perf_counter() - t0)
        dets = [(int(b.cls), float(b.conf), b.xyxy[0].tolist()) for b in result.boxes]
        for frame_index, pid, region in placed:
            state = judge_head(dets, region)
            stats = riders[pid]
            stats.per_frame[frame_index] = state
            setattr(stats, state, getattr(stats, state) + 1)


def _offset_spread(offsets):
    if len(offsets) < 3:
        return 0.0
    return float(max(np.std([o[0] for o in offsets]), np.std([o[1] for o in offsets])))


def _hist(image):
    if image is None or image.size < 64:
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 8], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def _blend(old, new):
    if new is None:
        return old
    return new if old is None else 0.8 * old + 0.2 * new


def _thumb(small, box):
    x1, y1, x2, y2 = [int(v) for v in box]
    region = small[max(0, y1):max(0, y2), max(0, x1):max(0, x2)]
    return region.copy() if region.size else None


def _resize_thumb(image, h=110):
    return cv2.resize(image, (max(1, int(image.shape[1] * h / max(1, image.shape[0]))), h))


# ============================================================
# PLATE CANDIDATES
# ============================================================

@dataclass
class Candidate:
    frame_index: int
    frame_small: np.ndarray    # the work-resolution frame (shared, not copied)
    moto_box: tuple            # work-resolution coords
    riders: list               # [(person_track_id, box)]
    crop: np.ndarray           # full-resolution vehicle crop (plate region)
    crop_origin: tuple         # (x, y) of crop in full-resolution frame
    scale: float               # full-res px per work px
    area: float
    cut_off: bool
    track_id: str = ""         # raw tracker id the crop came from (partial ANPR never mixes ids)


def _maybe_keep_candidate(vehicle, index, frame, small, mbox, rider_list, scale, work_w, work_h, cfg):
    """Keep the best vehicle crops (largest, not cut off) cut from the FULL
    resolution frame right away; the plate is later searched only inside
    these, so evidence image, vehicle box and plate crop share one frame."""
    cut_off = _touches_edge(mbox, work_w, work_h, 2)
    area = _area(mbox) * (0.4 if cut_off else 1.0)
    kept = vehicle.candidates
    if len(kept) >= cfg.plate_candidates_kept and area <= min(c.area for c in kept):
        return
    x1, y1, x2, y2 = mbox
    w, h = x2 - x1, y2 - y1
    region = [int(v * scale) for v in (x1 - 0.05 * w, y1 + 0.20 * h, x2 + 0.05 * w, y2 + 0.05 * h)]
    H, W = frame.shape[:2]
    region = [max(0, region[0]), max(0, region[1]), min(W, region[2]), min(H, region[3])]
    if region[2] - region[0] < 32 or region[3] - region[1] < 32:
        return
    # the downscaled frame is referenced, not re-encoded: several candidates
    # of one frame share it, and it is freed when no candidate keeps it
    kept.append(Candidate(index, small, tuple(mbox), list(rider_list),
                          frame[region[1]:region[3], region[0]:region[2]].copy(),
                          (region[0], region[1]), scale, area, cut_off, track_id=vehicle.track_id))
    if len(kept) > cfg.plate_candidates_kept:
        kept.remove(min(kept, key=lambda c: c.area))


PLATE_ASPECT_RANGE = (1.2, 6.5)


def pick_plate_box(boxes, crop_shape, origin, moto_box_full, reasons=None):
    """Plate on THIS vehicle: centre inside the vehicle box, in its lower /
    front part, plausible size and aspect ratio."""
    mx1, my1, mx2, my2 = moto_box_full
    mw, mh = mx2 - mx1, my2 - my1
    best = None
    for (bx1, by1, bx2, by2), conf in boxes:
        fx1, fy1, fx2, fy2 = bx1 + origin[0], by1 + origin[1], bx2 + origin[0], by2 + origin[1]
        w, h = fx2 - fx1, fy2 - fy1
        cx, cy = (fx1 + fx2) / 2, (fy1 + fy2) / 2
        aspect = w / max(1, h)
        why = None
        if not (PLATE_ASPECT_RANGE[0] <= aspect <= PLATE_ASPECT_RANGE[1]):
            why = f"aspect {aspect:.2f}"
        elif not (mx1 <= cx <= mx2):
            why = f"centre x outside vehicle ({(cx - mx1) / max(1, mw):.2f})"
        elif not (my1 + 0.20 * mh <= cy <= my2 + 0.05 * mh):
            why = f"centre y not in lower part ({(cy - my1) / max(1, mh):.2f})"
        elif not (0.05 * mw <= w <= 0.80 * mw):
            why = f"width {w / max(1, mw):.2f} of vehicle"
        if why:
            if reasons is not None:
                reasons.append(why)
            continue
        if best is None or conf > best[1]:
            best = ((int(bx1), int(by1), int(bx2), int(by2)), conf)
    return best


def detect_vehicle_plates(vehicle: VehicleTrack, plate_model, cfg, timer, log):
    """Plate detection on the vehicle's pooled crops (all merged fragments).
    Returns the quality-ranked plate crops."""
    candidates = sorted(vehicle.candidates, key=lambda c: -c.area)[:max(cfg.plate_candidates_kept, 8)]
    scored = []
    for candidate in candidates:
        t0 = time.perf_counter()
        result = plate_model.predict(candidate.crop, imgsz=cfg.plate_imgsz, conf=cfg.plate_conf)[0]
        timer.add("plate detection", time.perf_counter() - t0)
        boxes = [(tuple(b.xyxy[0].tolist()), float(b.conf)) for b in result.boxes]
        moto_full = tuple(v * candidate.scale for v in candidate.moto_box)
        reasons = []
        picked = pick_plate_box(boxes, candidate.crop.shape, candidate.crop_origin, moto_full, reasons)
        if picked is None:
            log.append(f"  frame {candidate.frame_index}: no plate on this vehicle "
                       f"({len(boxes)} detections, rejected: {reasons or 'none detected'})")
            continue
        (x1, y1, x2, y2), conf = picked
        w, h = x2 - x1, y2 - y1
        two_line = w / max(1, h) < plate_ocr.TWO_LINE_ASPECT
        pad = (int(0.05 * w), int((0.12 if two_line else 0.08) * h))
        crop = candidate.crop[max(0, y1 - pad[1]):y2 + pad[1], max(0, x1 - pad[0]):x2 + pad[0]]
        ok, sharp, why = plate_ocr.passes_quality(candidate.crop[y1:y2, x1:x2])
        if not ok:
            log.append(f"  frame {candidate.frame_index}: plate skipped - {why}")
            continue
        quality = (1 - math.exp(-sharp / 300.0)) * min(1.0, math.sqrt(w * h / 12000.0)) * (0.5 + conf / 2)
        scored.append((quality, candidate, (x1, y1, x2, y2), crop, sharp))
    scored.sort(key=lambda s: -s[0])
    return scored


def ocr_vehicle_plates(vehicle: VehicleTrack, scored, cfg, timer, log):
    """Staged recognition-only OCR on the top-N sharpest plate crops, early
    stop once the read is stable and confident."""
    def good_enough(read):
        parsed = parse_plate(read.text, read.confidences)
        return parsed is not None and parsed.cost < 0.35 and read.mean_conf >= cfg.ocr_accept_conf

    reads = []
    for quality, candidate, box, crop, sharp in scored[:cfg.ocr_top_n]:
        t1 = time.perf_counter()
        options = plate_ocr.read_plate(crop, good_enough)
        timer.add("OCR", time.perf_counter() - t1)
        best = None
        for read in options:
            parsed = parse_plate(read.text, read.confidences)
            key = (parsed is not None, -(parsed.cost if parsed else 9), read.mean_conf)
            if best is None or key > best[0]:
                best = (key, read, parsed)
        _, read, parsed = best if best else (None, None, None)
        log.append(f"  frame {candidate.frame_index}: plate {box} sharp={sharp:.0f} quality={quality:.2f} "
                   f"reads={[(o.variant, o.text, round(o.mean_conf, 2)) for o in options]} "
                   f"-> {parsed.chars if parsed else 'no plate structure'}")
        reads.append({"candidate": candidate, "box": box, "crop": crop, "read": read,
                      "parsed": parsed, "weight": quality, "sharpness": sharp})
        stable = [r["parsed"].chars for r in reads if r["parsed"] and r["read"].mean_conf >= cfg.ocr_stable_conf]
        if stable and Counter(stable).most_common(1)[0][1] >= cfg.ocr_stable_reads:
            log.append("  stable read reached - early stop")
            break
    vehicle.plate_reads.extend(reads)


# ============================================================
# PIPELINE
# ============================================================

def _track(tracker, detections, index, ts, kind):
    dets = [DetectionResult(tracker.camera_id, "", index, ts, kind, conf, BoundingBox(*box))
            for box, conf in detections]
    tracks = tracker.update(dets, ts, index)
    ids = []
    for det in dets:
        match = next((t for t in tracks if t.last_bbox is det.bbox), None)
        ids.append(f"{kind[0].upper()}{match.track_id[6:]}" if match else None)
    return ids


def run_dual_pipeline(pipeline, input_path, evidence_path, run_dir=None, video_name=None,
                      progress: Callable[[dict], None] | None = None,
                      config: RoutineConfig | None = None):
    """Process a routine-violation video.

    ``pipeline`` is unused (kept for API compatibility): models come from the
    shared registry in models.py, loaded once and reused across jobs.
    ``run_dir`` receives one evidence image per violating vehicle, summary.json,
    summary.csv, plate_debug.log, merge_report.txt and merge_review/*.jpg.
    """
    cfg = config or DEFAULT_CONFIG
    input_path, evidence_path = Path(input_path), Path(evidence_path)
    run_dir = Path(run_dir) if run_dir else evidence_path.parent / f"run_{evidence_path.stem}"
    run_dir.mkdir(parents=True, exist_ok=True)
    timer = StageTimer()
    start = time.perf_counter()
    report = progress or (lambda update: None)

    report({"percent": 1, "stage": "loading models", "vehicles_found": 0})
    vehicle_model = models.get_model("vehicle")
    helmet_model = models.get_model("helmet")
    plate_model = models.get_model("plate")

    capture = cv2.VideoCapture(str(input_path), cv2.CAP_MSMF)
    decoder_api = "Media Foundation (hardware)"
    if not capture.isOpened():
        capture = cv2.VideoCapture(str(input_path))
        decoder_api = "FFmpeg (software)"
    if not capture.isOpened():
        raise ValueError("Unable to open the uploaded video.")
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:          # Media Foundation does not report it
        probe = cv2.VideoCapture(str(input_path))
        total_frames = int(probe.get(cv2.CAP_PROP_FRAME_COUNT))
        probe.release()
    total_frames = max(1, total_frames)
    fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
    full_w = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    full_h = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    work_w = min(cfg.work_width, full_w)
    work_h = int(round(full_h * work_w / full_w))
    scale = full_w / work_w
    backends = models.describe()
    backends["ocr"] = plate_ocr.get_recognizer().backend
    print(f"[ROUTINE] {input_path.name}: {full_w}x{full_h} @ {fps:.1f} fps, {total_frames} frames | "
          f"stride {cfg.frame_stride} | decoder {decoder_api} | models {backends}", flush=True)

    previous_cv_threads = cv2.getNumThreads()
    cv2.setNumThreads(cfg.cv_threads)
    stop = threading.Event()
    errors: list[BaseException] = []

    # ---------------- decode thread ----------------
    # Small queue: at most a few full-resolution frames exist at any time.
    frame_q: queue.Queue = queue.Queue(maxsize=cfg.detect_batch)

    def decode():
        try:
            index = -1
            while not stop.is_set():
                t0 = time.perf_counter()
                if not capture.grab():
                    break
                index += 1
                if index % cfg.frame_stride:
                    timer.add("video decode", time.perf_counter() - t0, 0)
                    continue
                ok, frame = capture.retrieve()
                if not ok:
                    break
                small = cv2.resize(frame, (work_w, work_h), interpolation=cv2.INTER_LINEAR)
                timer.add("video decode", time.perf_counter() - t0)
                while not stop.is_set():
                    try:
                        frame_q.put((index, frame, small), timeout=0.2)
                        break
                    except queue.Full:
                        continue
        except BaseException as exc:
            errors.append(exc)
        finally:
            capture.release()
            while True:
                try:
                    frame_q.put(None, timeout=0.5)
                    break
                except queue.Full:
                    if stop.is_set():
                        break

    decoder = threading.Thread(target=decode, name="routine-decode", daemon=True)
    decoder.start()

    # ---------------- main thread ----------------
    moto_tracker = MultiObjectTracker("moto", "", max_age=cfg.track_max_age)
    person_tracker = MultiObjectTracker("person", "", max_age=cfg.track_max_age)
    motion = CameraMotion(work_w)
    vehicles: dict[str, VehicleTrack] = {}
    riders: dict[str, RiderStats] = defaultdict(RiderStats)
    affines: dict[int, Any] = {}
    processed = 0
    done = False
    try:
        while not done:
            batch = []
            while len(batch) < cfg.detect_batch:
                item = frame_q.get()
                if item is None:
                    done = True
                    break
                batch.append(item)
            if not batch:
                break
            smalls = [b[2] for b in batch]
            padded = smalls + [smalls[-1]] * (cfg.detect_batch - len(smalls))   # static batch
            t0 = time.perf_counter()
            results = vehicle_model.predict(padded, imgsz=list(cfg.detect_imgsz), conf=cfg.detect_conf,
                                            classes=[COCO_PERSON, COCO_MOTORCYCLE])[:len(batch)]
            timer.add("vehicle detection", time.perf_counter() - t0, len(batch))

            head_requests = []
            for (index, frame, small), result in zip(batch, results):
                t1 = time.perf_counter()
                persons, motos = [], []
                for box in result.boxes:
                    xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
                    (persons if int(box.cls) == COCO_PERSON else motos).append((xyxy, float(box.conf)))
                affine = motion.update(small, [b for b, _ in persons + motos])
                affines[index] = affine
                ts = index / fps
                for tracker in (moto_tracker, person_tracker):
                    for track in tracker.tracks.values():   # camera-motion compensation
                        b = warp_box((track.last_bbox.x1, track.last_bbox.y1,
                                      track.last_bbox.x2, track.last_bbox.y2), affine)
                        track.last_bbox = BoundingBox(*b)
                moto_ids = _track(moto_tracker, motos, index, ts, "moto")
                person_ids = _track(person_tracker, persons, index, ts, "person")

                on_bike: dict[str, list] = defaultdict(list)
                for (pbox, _), pid in zip(persons, person_ids):
                    best, best_score = None, 0.0
                    for (mbox, _), mid in zip(motos, moto_ids):
                        score = rider_on_motorcycle(pbox, mbox)
                        if score > best_score:
                            best, best_score = mid, score
                    if best is not None:
                        on_bike[best].append((pid, pbox))

                for (mbox, _), mid in zip(motos, moto_ids):
                    vehicle = vehicles.get(mid)
                    if vehicle is None:
                        vehicle = vehicles[mid] = VehicleTrack(mid, index, index, fps=fps)
                        vehicle.members = [mid]
                    prev_frame = vehicle.last_frame
                    if (prev_frame in vehicle.boxes and index - prev_frame == cfg.frame_stride
                            and not _touches_edge(mbox, work_w, work_h, cfg.edge_margin)
                            and not _touches_edge(vehicle.boxes[prev_frame], work_w, work_h, cfg.edge_margin)):
                        prev_box = vehicle.boxes[prev_frame]
                        dx, dy = motion.local_motion(prev_box, affine)
                        cx, cy = _center(prev_box)
                        ncx, ncy = _center(mbox)
                        width = max(1.0, mbox[2] - mbox[0])
                        bg_scale = math.sqrt(abs(np.linalg.det(affine[:, :2]))) if affine is not None else 1.0
                        growth = (math.log(width / max(1.0, prev_box[2] - prev_box[0]))
                                  - math.log(max(1e-3, bg_scale)))
                        vehicle.rel_motion.append((index, ((ncx - cx - dx) / width, (ncy - cy - dy) / width, growth)))
                    vehicle.boxes[index] = mbox
                    vehicle.last_frame = index
                    if "first" not in vehicle.thumbs:
                        vehicle.thumbs["first"] = (index, _thumb(small, mbox))
                    vehicle.last_thumb_box = (index, mbox, small)   # cropped when the track ends
                    rider_list = on_bike.get(mid, [])
                    vehicle.frame_riders[index] = [pid for pid, _ in rider_list]
                    mw, mh = max(1.0, mbox[2] - mbox[0]), max(1.0, mbox[3] - mbox[1])
                    for pid, pbox in rider_list:
                        vehicle.riders[pid] += 1
                        riders[pid].motos[mid] += 1
                        pcx, pcy = _center(pbox)
                        vehicle.rider_offsets[pid].append(((pcx - mbox[0]) / mw, (pcy - mbox[1]) / mh))
                        px1, py1, px2, py2 = [int(v) for v in pbox]
                        pw, ph = px2 - px1, py2 - py1
                        torso = small[max(0, py1 + int(0.2 * ph)):max(0, py1 + int(0.6 * ph)),
                                      max(0, px1 + int(0.2 * pw)):max(0, px2 - int(0.2 * pw))]
                        vehicle.rider_hist = _blend(vehicle.rider_hist, _hist(torso))
                    if rider_list:
                        x1, y1, x2, y2 = [int(v) for v in mbox]
                        vehicle.hist = _blend(vehicle.hist, _hist(small[max(0, y1):y2, max(0, x1):x2]))
                        _maybe_keep_candidate(vehicle, index, frame, small, mbox, rider_list,
                                              scale, work_w, work_h, cfg)
                    # helmet checks: every Nth sighting, not once settled, head
                    # fully in frame and large enough, bike mostly in frame
                    bike_cx = (mbox[0] + mbox[2]) / 2
                    bike_in_frame = 0.03 * work_w < bike_cx < 0.97 * work_w
                    for pid, pbox in rider_list:
                        stats = riders[pid]
                        if (not bike_in_frame or stats.settled(cfg)
                                or (vehicle.riders[pid] - 1) % cfg.helmet_every != 0
                                or pbox[3] - pbox[1] < cfg.min_person_height
                                or _touches_edge(_head_box(pbox), work_w, work_h, cfg.edge_margin)):
                            continue
                        head = _head_crop(frame, pbox, scale)
                        if head is not None:
                            stats.checks += 1
                            head_requests.append((index, pid, head))
                timer.add("tracking", time.perf_counter() - t1)
                processed += 1
            # finish the "last" thumbnail of tracks not seen in this batch (keeps
            # no reference to old frames)
            batch_frames = {b[0] for b in batch}
            for vehicle in vehicles.values():
                pending = getattr(vehicle, "last_thumb_box", None)
                if pending is not None and pending[0] not in batch_frames:
                    vehicle.thumbs["last"] = (pending[0], _thumb(pending[2], pending[1]))
                    vehicle.last_thumb_box = None
            # full-resolution frames of this batch are no longer referenced
            batch = None
            run_helmet_mosaics(head_requests, helmet_model, riders, cfg, timer)
            if processed % 8 == 0:
                last_index = max(affines)
                found = sum(1 for v in vehicles.values() if violation_types(v, riders, cfg))
                report({"percent": min(85, int(2 + 83 * last_index / total_frames)),
                        "stage": f"detecting & tracking (frame {last_index}/{total_frames})",
                        "vehicles_found": found})
    except BaseException as exc:
        errors.append(exc)
    finally:
        stop.set()
        decoder.join(timeout=5)
        cv2.setNumThreads(previous_cv_threads)
    if errors:
        raise errors[0]

    for vehicle in vehicles.values():
        pending = getattr(vehicle, "last_thumb_box", None)
        if pending is not None:
            vehicle.thumbs["last"] = (pending[0], _thumb(pending[2], pending[1]))
            vehicle.last_thumb_box = None
    timer.phase_stream = time.perf_counter() - start
    report({"percent": 87, "stage": "merging duplicates, then reading number plates", "vehicles_found": None})
    return _finalize(cfg, timer, start, input_path, evidence_path, run_dir,
                     video_name or input_path.name, vehicles, riders, affines, fps, total_frames,
                     processed, decoder_api, backends, report, plate_model)


# ============================================================
# FINALIZE
# ============================================================

def _vote(vehicle: VehicleTrack, prior: str | None, cfg):
    usable = [(r["parsed"], r["weight"]) for r in vehicle.plate_reads if r["parsed"] is not None]
    usable = sorted(usable, key=lambda x: -x[1])[: max(cfg.ocr_top_n, 8)]
    voted = vote_characters(usable)
    if voted is None:
        return None, None
    validation = validate_plate(voted.chars, voted.confidences, log=False,
                                state_prior=prior, alternatives=voted.alternatives)
    return voted, validation


def filter_riders(vehicles: dict, riders: dict, cfg, log: list) -> tuple[list, list]:
    """Accept riders per bike, then drop riderless and parked bikes. Every
    motorcycle track is logged with the reason it was kept or excluded."""
    for pid, stats in riders.items():                      # a person rides one bike
        if stats.motos:
            best = stats.motos.most_common(1)[0][0]
            for mid in list(stats.motos):
                if mid != best and mid in vehicles:
                    vehicles[mid].riders.pop(pid, None)
    ridden, parked, riderless = [], [], 0
    log.append("=== PARKED / RIDERLESS FILTER ===")
    for vehicle in vehicles.values():
        top = max(vehicle.riders.values(), default=0)
        accepted, rejected = Counter(), {}
        for pid, n in vehicle.riders.items():
            spread = _offset_spread(vehicle.rider_offsets.get(pid, []))
            if n < cfg.rider_min_frames:
                rejected[pid] = f"on bike only {n} frame(s)"
            elif n < cfg.rider_min_share * top:
                rejected[pid] = f"{n} frames < {cfg.rider_min_share:.0%} of main rider's {top}"
            elif spread > cfg.rider_max_offset_std:
                rejected[pid] = f"drifts across the bike (spread {spread:.2f}) - passer-by"
            else:
                accepted[pid] = n
        vehicle.riders = accepted
        speed = vehicle.speed()
        head = f"{vehicle.track_id}: frames {vehicle.first_frame}-{vehicle.last_frame} ({len(vehicle.boxes)} seen)"
        if not accepted:
            riderless += 1
            log.append(f"{head} -> EXCLUDED riderless"
                       + (f" (candidates rejected: {rejected})" if rejected else " (no person on it)"))
            continue
        if cfg.exclude_static_vehicles and speed is not None and speed < cfg.parked_max_speed:
            parked.append(vehicle)
            log.append(f"{head} -> EXCLUDED parked (net motion {speed:.2f} widths/s < "
                       f"{cfg.parked_max_speed}); riders {dict(accepted)}")
            continue
        log.append(f"{head} -> kept: riders {dict(accepted)}, net motion "
                   f"{'n/a' if speed is None else f'{speed:.2f} widths/s'}"
                   + (f"; rejected {rejected}" if rejected else ""))
        ridden.append(vehicle)
    log.append(f"parked filter: evaluated {len(vehicles)} motorcycle tracks: {riderless} riderless, "
               f"{len(parked)} parked/static, {len(ridden)} kept")
    return ridden, parked


def _save_contact_sheet(path: Path, columns: list[tuple[str, list]]):
    """columns: [(label, [(frame, thumb), ...])] -> one image, one column each."""
    tiles = []
    for label, thumbs in columns:
        thumbs = [(f, _resize_thumb(t)) for f, t in thumbs if t is not None]
        cells = [t for _, t in thumbs]
        if not cells:
            continue
        width = max(c.shape[1] for c in cells + [np.zeros((1, 160, 3), np.uint8)])
        column = [np.zeros((30, width, 3), np.uint8)]
        cv2.putText(column[0], label[:40], (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        for frame, t in thumbs:
            if t is None:
                continue
            cell = np.zeros((t.shape[0] + 18, width, 3), np.uint8)
            cell[:t.shape[0], :t.shape[1]] = t
            cv2.putText(cell, f"frame {frame}", (4, t.shape[0] + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (255, 255, 255), 1)
            column.append(cell)
        tiles.append(np.vstack(column))
    if not tiles:
        return
    height = max(t.shape[0] for t in tiles)
    tiles = [np.vstack([t, np.zeros((height - t.shape[0], t.shape[1], 3), np.uint8)]) for t in tiles]
    sheet = np.hstack([np.hstack([t, np.full((height, 6, 3), 80, np.uint8)]) for t in tiles])
    cv2.imwrite(str(path), sheet)


def _finalize(cfg, timer, start, input_path, evidence_path, run_dir, video_name, vehicles, riders,
              affines, fps, total_frames, processed, decoder_api, backends, report, plate_model):
    log = [f"video={video_name} frames={total_frames} processed={processed} stride={cfg.frame_stride}",
           f"models={backends}"]
    ridden, parked = filter_riders(vehicles, riders, cfg, log)

    # ---- merge fragments BEFORE any plate work ----
    t0 = time.perf_counter()
    groups, pairs = merge_tracks(ridden, affines, fps, cfg)
    review_dir = run_dir / "merge_review"
    review_dir.mkdir(exist_ok=True)
    pair_by_ids = {frozenset((p.a, p.b)): p for p in pairs}
    by_id = {t.track_id: t for t in ridden}
    snapshots = {t.track_id: [t.thumbs.get("first", (None, None)), t.thumbs.get("last", (None, None))]
                 for t in ridden}
    frames_of = {t.track_id: (t.first_frame, t.last_frame) for t in ridden}
    for number, group in enumerate(groups, start=1):
        if len(group) > 1:
            _save_contact_sheet(review_dir / f"merged_group_{number:02d}_{'+'.join(t.track_id for t in group)}.jpg",
                                [(f"{t.track_id} f{t.first_frame}-{t.last_frame}", snapshots[t.track_id]) for t in group])
    near_misses = [p for p in pairs if p.score is not None
                   and cfg.merge_threshold - cfg.merge_near_miss <= p.score < cfg.merge_threshold]
    for pair in near_misses:
        _save_contact_sheet(review_dir / f"near_miss_{pair.a}_{pair.b}_score{pair.score:.2f}.jpg",
                            [(f"{pair.a} f{frames_of[pair.a][0]}-{frames_of[pair.a][1]}", snapshots[pair.a]),
                             (f"{pair.b} f{frames_of[pair.b][0]}-{frames_of[pair.b][1]}", snapshots[pair.b])])
    combined = [combine(group) for group in groups]
    timer.add("merge", time.perf_counter() - t0)

    # ---- violations per vehicle (set of types) ----
    violators = []
    for vehicle in combined:
        found = violation_types(vehicle, riders, cfg)
        if found:
            violators.append((vehicle, found))

    # ---- plates only for merged violating vehicles ----
    plate_log = ["=== PLATE READS (per merged vehicle) ==="]
    per_vehicle_logs = {id(v): [f"--- vehicle {'+'.join(v.members)} ---"] for v, _ in violators}
    detected = [(v, detect_vehicle_plates(v, plate_model, cfg, timer, per_vehicle_logs[id(v)]))
                for v, _ in violators]                        # iGPU, serial
    with ThreadPoolExecutor(max_workers=cfg.ocr_workers) as pool:  # CPU, parallel per vehicle
        list(pool.map(lambda item: ocr_vehicle_plates(item[0], item[1], cfg, timer,
                                                      per_vehicle_logs[id(item[0])]), detected))
    for v, _ in violators:
        plate_log.extend(per_vehicle_logs[id(v)])

    first_pass = [(v, found, *_vote(v, None, cfg)) for v, found in violators]
    prior = None
    if cfg.regional_prior:
        confident = [(val.state_code, 1.0) for _, _, voted, val in first_pass
                     if val is not None and val.valid
                     and not any("state '" in c and "->" in c for c in val.changes)]
        prior = regional_prior(confident, min_plates=cfg.prior_min_plates, min_share=cfg.prior_min_share)
        log.append(f"regional prior: {prior or 'none'} from {confident}")
    entries = []
    for vehicle, found, voted, validation in first_pass:
        if prior:
            voted2, validation2 = _vote(vehicle, prior, cfg)
            if validation2 is not None and validation is not None and validation2.plate != validation.plate:
                log.append(f"{vehicle.members}: regional prior changed {validation.plate} -> {validation2.plate}")
            voted, validation = voted2, validation2
        confident_plate = (validation.plate if validation and validation.valid
                           and not validation.low_confidence else None)
        entries.append({"vehicle": vehicle, "found": found, "types": sorted(found), "voted": voted,
                        "validation": validation, "plate": confident_plate})
    before = len(entries)
    entries = merge_by_plate(entries, cfg)
    for entry in entries:
        if entry.get("merged"):
            entry["found"] = violation_types(entry["vehicle"], riders, cfg) or entry["found"]
            entry["types"] = sorted(entry["found"])
            entry["voted"], entry["validation"] = _vote(entry["vehicle"], prior, cfg)
    if before != len(entries):
        log.append(f"confident-plate merge: {before} -> {len(entries)} vehicles")

    def first_violation(entry):
        frames = [f for fs in entry["found"].values() for f in fs]
        return min(frames) if frames else entry["vehicle"].first_frame
    entries.sort(key=first_violation)

    # ---- evidence ----
    t0 = time.perf_counter()
    jobs = [(number, entry, _evidence_choice(entry)) for number, entry in enumerate(entries, start=1)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(lambda job: _render_and_save(job, riders, run_dir, fps), jobs))
    timer.add("evidence rendering", time.perf_counter() - t0, len(jobs))

    records = []
    for (number, entry, choice), (filename, image) in zip(jobs, images):
        vehicle, validation, voted = entry["vehicle"], entry["validation"], entry["voted"]
        support = 0
        if validation and validation.valid:
            support = len({r["candidate"].frame_index for r in vehicle.plate_reads
                           if r["parsed"] and plates_near_equal(r["parsed"].chars, voted.chars, 2)})
            status = ("confirmed" if validation.number_digits == 4 and not validation.low_confidence
                      and support >= 2 else "low_confidence")
        elif any(r["read"] for r in vehicle.plate_reads):
            status = "low_confidence"
        else:
            status = "unreadable"
        fv = first_violation(entry)
        evidence_frame = choice["candidate"].frame_index if choice else fv
        records.append({
            "vehicle_id": number,
            "track_id": "+".join(vehicle.members),
            "violations": entry["types"],
            "plate_number": format_plate(validation.plate) if validation and validation.valid else "",
            "plate_compact": validation.plate if validation and validation.valid else "",
            "plate_raw": voted.chars if voted else "",
            "plate_status": status,
            "state_code": validation.state_code if validation and validation.valid else None,
            "state_name": validation.state_name if validation and validation.valid else None,
            "plate_confidence": validation.confidence if validation and validation.valid else None,
            "plate_votes": {"reads": voted.reads if voted else 0,
                            "per_position": voted.alternatives if voted else []},
            "plate_support_frames": support,
            "first_violation_frame": fv,
            "first_violation_time_s": round(fv / fps, 2),
            "evidence_frame": evidence_frame,
            "evidence_time_s": round(evidence_frame / fps, 2),
            "frames_seen": len(vehicle.boxes),
            "riders": len(vehicle.riders),
            "violation_frames": {k: v for k, v in entry["found"].items()},
            "plate_reads": len(vehicle.plate_reads),
            "evidence_plate_sharpness": round(choice["sharpness"], 1) if choice and choice.get("sharpness") else None,
            "evidence_plate_area": (choice["box"][2] - choice["box"][0]) * (choice["box"][3] - choice["box"][1])
            if choice and choice.get("box") else None,
            "evidence_file": filename,
        })

    # ---- rule-based partial plate (strict: unread characters stay unknown) ----
    # Additive only: the plate, status and evidence above are unchanged. The
    # fine flow uses partial_plate for vehicles without a confirmed plate.
    for record, entry in zip(records, entries):
        vehicle = entry["vehicle"]
        reads = [{"text": r["read"].text, "confidences": list(r["read"].confidences),
                  "frame": r["candidate"].frame_index,
                  "track_id": getattr(r["candidate"], "track_id", "") or vehicle.track_id}
                 for r in vehicle.plate_reads if r.get("read") is not None]
        try:
            record["partial_plate"] = analyze_partial_plate(reads)
            log.append(f"PARTIAL vehicle {record['vehicle_id']}: {record['partial_plate']['partial_pattern']} "
                       f"(complete={record['partial_plate']['is_complete']}, "
                       f"track {record['partial_plate']['track_id']}, frames {record['partial_plate']['frames_used']})")
        except Exception as error:    # never let the partial analysis break detection
            record["partial_plate"] = None
            log.append(f"PARTIAL vehicle {record['vehicle_id']}: analysis failed: {error}")

    # ---- per-vehicle debug + merge report ----
    for record, entry in zip(records, entries):
        vehicle = entry["vehicle"]
        trajectory = [(f, tuple(int(round(v)) for v in (_center(b)[0], _center(b)[1], b[2] - b[0], b[3] - b[1])))
                      for f, b in sorted(vehicle.boxes.items())][::6]
        plate_strings = [(r["candidate"].frame_index, r["read"].text if r["read"] else "",
                          r["parsed"].chars if r["parsed"] else "-") for r in vehicle.plate_reads]
        log.append(f"FINAL vehicle {record['vehicle_id']}: raw tracks {vehicle.members} | frames "
                   f"{vehicle.first_frame}-{vehicle.last_frame} ({len(vehicle.boxes)} seen) | riders "
                   f"{dict(vehicle.riders)} | violations {entry['found']} | plate "
                   f"{record['plate_number'] or record['plate_status']} (raw vote {record['plate_raw'] or '-'})")
        log.append(f"    box trajectory (frame, (cx, cy, w, h)) every 6th: {trajectory}")
        log.append(f"    per-frame plate strings (frame, raw OCR, parsed): {plate_strings}")

    track_to_vehicle = {m: r["vehicle_id"] for r, e in zip(records, entries) for m in e["vehicle"].members}
    merge_report = ["MERGE REPORT", f"threshold {cfg.merge_threshold}, near-miss band "
                    f"{cfg.merge_threshold - cfg.merge_near_miss:.2f}-{cfg.merge_threshold}", "",
                    "== merged groups (raw tracker ids -> one vehicle) =="]
    for group in groups:
        ids = [t.track_id for t in group]
        if len(ids) > 1:
            edges = [pair_by_ids[frozenset((x, y))] for i, x in enumerate(ids) for y in ids[i + 1:]]
            merge_report.append(f"{'+'.join(ids)} -> vehicle {track_to_vehicle.get(ids[0], '(no violation)')}: "
                                + "; ".join(f"{e.a}-{e.b} {e.score if e.score is not None else 'blocked'} "
                                            f"({e.reason}) {e.parts}" for e in edges))
    merge_report += ["", "== every pair of FINAL vehicles (best score between their tracks) =="]
    final_ids = [(r["vehicle_id"], e["vehicle"].members) for r, e in zip(records, entries)]
    for i, (va, ma) in enumerate(final_ids):
        for vb, mb in final_ids[i + 1:]:
            scored = [pair_by_ids[frozenset((x, y))] for x in ma for y in mb if frozenset((x, y)) in pair_by_ids]
            best = max((p for p in scored if p.score is not None), key=lambda p: p.score, default=None)
            if best:
                merge_report.append(f"vehicle {va} vs {vb}: score {best.score:.2f} ({best.a}-{best.b}) {best.parts}")
            else:
                reasons = sorted({p.reason for p in scored}) or ["no tracks compared"]
                merge_report.append(f"vehicle {va} vs {vb}: blocked - {reasons[0]}")
    merge_report += ["", "== near misses (saved as merge_review/near_miss_*.jpg) =="]
    merge_report += [f"{p.a}-{p.b}: {p.score:.2f} {p.parts}" for p in near_misses] or ["none"]
    (run_dir / "merge_report.txt").write_text("\n".join(merge_report) + "\n", encoding="utf-8")

    if images and images[0][1] is not None:
        cv2.imwrite(str(evidence_path), images[0][1])

    wall = time.perf_counter() - start
    table = timer.table(wall)
    primary = next((r for r in records if r["plate_number"]), records[0] if records else None)
    summary = {
        "video": video_name,
        "run_dir": str(run_dir),
        "fps": round(fps, 2),
        "total_video_frames": total_frames,
        "processed_frames": processed,
        "vehicles_tracked": len(vehicles),
        "parked_excluded": len(parked),
        "violating_vehicles": len(records),
        "violations": len(records),
        "status": "VIOLATION DETECTED" if records else "NO VIOLATION DETECTED",
        "regional_prior": prior,
        "vehicles": records,
        "violation_records": [{
            "violation": ", ".join(r["violations"]),
            "plate_number": r["plate_number"],
            "state_name": r["state_name"],
            "plate_confirmed": r["plate_status"] == "confirmed",
            "plate_confidence": r["plate_confidence"],
            "plate_frames": r["plate_support_frames"],
        } for r in ([primary] if primary else [])],
        "timing": {"total_seconds": round(wall, 2), "stages": timer.as_dict(),
                   "decoder": decoder_api, "models": backends,
                   "device": ", ".join(sorted({b.split(" (")[0] for b in backends.values()})),
                   "gpu_used": any("iGPU" in b or "CUDA" in b for b in backends.values())},
        "config": cfg.as_dict(),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    summary["result_json"] = str(run_dir / "summary.json")
    with open(run_dir / "summary.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vehicle_id", "violations", "plate_number", "state_code", "state_name",
                         "plate_status", "first_violation_frame", "first_violation_time_s",
                         "evidence_frame", "evidence_time_s", "evidence_file"])
        for r in records:
            writer.writerow([r["vehicle_id"], "; ".join(r["violations"]), r["plate_number"],
                             r["state_code"] or "", r["state_name"] or "", r["plate_status"],
                             r["first_violation_frame"], r["first_violation_time_s"],
                             r["evidence_frame"], r["evidence_time_s"], r["evidence_file"]])
    (run_dir / "plate_debug.log").write_text("\n".join(plate_log + [""] + log + ["", table]), encoding="utf-8")
    print(f"[ROUTINE] {len(records)} violating vehicle(s): "
          f"{[(r['vehicle_id'], r['plate_number'] or r['plate_status'], r['violations']) for r in records]} "
          f"| {log[[i for i, l in enumerate(log) if l.startswith('parked filter:')][0]] if any(l.startswith('parked filter:') for l in log) else ''} "
          f"| output {run_dir}\n{table}", flush=True)
    report({"percent": 100, "stage": "done", "vehicles_found": len(records)})
    return summary


def _evidence_choice(entry):
    """Best evidence: the frame whose plate read agrees with the final plate
    and is sharpest; else the largest kept frame of the vehicle."""
    vehicle, validation = entry["vehicle"], entry["validation"]
    final = validation.plate if validation and validation.valid else None
    best, best_key = None, None
    for r in vehicle.plate_reads:
        agrees = False
        if r["parsed"] is not None and final:
            check = validate_plate(r["parsed"].chars, r["parsed"].confidences, log=False)
            agrees = check.valid and plates_near_equal(check.plate, final, 1)
        key = (agrees, r["weight"])
        if best_key is None or key > best_key:
            best, best_key = r, key
    if best is not None:
        return best
    if vehicle.candidates:
        return {"candidate": max(vehicle.candidates, key=lambda c: c.area), "box": None, "crop": None}
    return None


def _render_and_save(job, riders, run_dir, fps):
    number, entry, choice = job
    validation = entry["validation"]
    plate = validation.plate if validation and validation.valid else None
    filename = f"vehicle_{number:02d}_{plate or 'UNREADABLE'}.jpg"
    if choice is None:
        return filename, None
    candidate = choice["candidate"]
    image = candidate.frame_small.copy()
    _unit, thick = scale_unit(image)

    x1, y1, x2, y2 = [int(v) for v in candidate.moto_box]
    for pid, pbox in candidate.riders:
        state = riders[pid].per_frame.get(candidate.frame_index) if pid in riders else None
        violator = pid in entry["vehicle"].riders and riders[pid].no_helmet > 0
        color = GREEN if state == "helmet" else RED if (state == "no_helmet" or violator) else YELLOW
        px1, py1, px2, py2 = [int(v) for v in pbox]
        cv2.rectangle(image, (px1, py1), (px2, py2), color, thick)
        x1, y1, x2, y2 = min(x1, px1), min(y1, py1), max(x2, px2), max(y2, py2)

    plate_box = plate_crop = None
    crop = choice.get("crop")
    # A crop is only shown when OCR found a plate structure in it.
    if choice.get("box") is not None and crop is not None and crop.size and choice.get("parsed") is not None:
        bx1, by1, bx2, by2 = choice["box"]
        ox, oy = candidate.crop_origin
        s = candidate.scale
        plate_box = ((bx1 + ox) / s, (by1 + oy) / s, (bx2 + ox) / s, (by2 + oy) / s)
        plate_crop = crop
    draw_plate_evidence(
        image,
        vehicle_box=(x1, y1, x2, y2),
        vehicle_label=f"V{number}: {' + '.join(entry['types'])}",
        plate_box=plate_box,
        plate_crop=plate_crop,
        plate_label=format_plate(plate) if plate else None,
        second_line=validation.state_name if plate else "state unknown",
        footer=f"Vehicle {number} | frame {candidate.frame_index} | t={candidate.frame_index / fps:.2f}s",
    )
    cv2.imwrite(str(run_dir / filename), image, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    return filename, image
