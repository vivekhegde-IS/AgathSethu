"""
Live ANPR - rule-based number plate detection on the REAL CARLA camera feed,
using the same plate stages as the routine-violation pipeline.

    CARLA camera (full_run.py, Member 1)
          |
          v
    carla_ws.py  /ws/carla/cameras   (camera_frame messages)
          |
          v  non-blocking submit (latest-frame buffer, 1 slot per junction)
    LIVE ANPR WORKER  (this file, one background thread)
          |-- detection + OCR : anpr_adapter.detect_and_read()
          |                     (number_plate_detector + routine plate_ocr)
          |-- gating          : rfid.plate_rules.gate()  (size / aspect / conf)
          |-- per read        : parse_plate() picks the best OCR variant
          |                     (same selection as dual_pipeline.ocr_vehicle_plates)
          |-- per plate track : one physical plate followed across frames
          |                     (box continuity, else near-equal text)
          |-- per track       : vote_characters() + validate_plate()
          |                     (same as dual_pipeline._vote, no regional prior)
          |-- status          : confirmed / low_confidence / unreadable
          |                     (same rule as the routine-violation records)
          |-- strict partial  : anpr_partial.analyze_reads() on the track's reads
          |                     (unread characters stay "_" / "*" / "+", never
          |                     guessed; per-character merge within the track)
          |-- candidates      : registered plates matching the strict pattern
          v
    evidence card (draw_plate_evidence: vehicle box, plate box, plate inset,
    plate text banner, footer)  ->  runtime/live_anpr/<session>/
          |
          v
    "live_plate_detection" event -> /ws/live-cameras -> Live page plate cards
    GET /api/anpr/live/detections, GET /api/anpr/live/evidence/{session}/{file}

Guarantees:
- ANPR never blocks the live stream: submit() only swaps a dict entry.
- ANPR never accumulates stale frames: one slot per junction, newest wins.
- No fake video, no synthetic plates: real CARLA frames only. A plate that
  cannot be read is reported as unreadable, never guessed.
"""

from __future__ import annotations

import base64
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from app.core.config import data_dir
from app.services.anpr_partial import analyze_reads as analyze_partial_plate
from app.services.anpr_partial import known_char_count
from app.services.evidence_render import draw_plate_evidence
from app.services.plate_validation import (
    ParsedRead,
    STATE_CODES,
    format_plate,
    parse_plate,
    validate_plate,
    vote_characters,
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
EVIDENCE_ROOT = data_dir() / "runtime" / "live_anpr"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# Minimum wall seconds between two ANPR passes on the SAME junction. One pass
# (detector + OCR) measures ~0.2-0.4 s on the iGPU, so three junctions at 1 s
# keep the worker busy well under half the time and leave room for RFID vision.
JUNCTION_INTERVAL_S = _env_float("LIVE_ANPR_JUNCTION_INTERVAL_S", 1.0)

# Plate tracking (simulation seconds / original frame pixels).
TRACK_BOX_PX = 140.0         # a box this close in a nearby frame is the same plate
TRACK_BOX_DT_S = 2.5
TRACK_TEXT_MAX_DIFF = 2      # ...or the text differs in at most this many characters
TRACK_EXPIRE_S = 8.0         # no sighting for this long: the vehicle has left
NEW_RUN_BACKSTEP_S = 5.0     # sim time jumping back this far = a new CARLA run

# Routine-violation voting / confirmation rules (RoutineConfig defaults).
VOTE_TOP_N = 8
# Strict partial plate: reads merged per track (each read's analysis is cached).
STRICT_MAX_READS = 60
CONFIRM_SUPPORT_FRAMES = 2
SUPPORT_MAX_DIFF = 2

# A track is shown only once it was seen in this many frames: a single frame
# can produce a structurally valid but wrong plate from OCR noise.
MIN_FRAMES_TO_SHOW = 2
# A card image is re-rendered at most this often per track (wall seconds).
RENDER_MIN_INTERVAL_S = 2.0

RECENT_DETECTIONS_MAX = 60

STATUS_CONFIRMED = "confirmed"
STATUS_LOW_CONFIDENCE = "low_confidence"
STATUS_UNREADABLE = "unreadable"
STATUS_LABEL = {
    STATUS_CONFIRMED: "Plate confirmed (multi-frame)",
    STATUS_LOW_CONFIDENCE: "Plate low confidence",
    STATUS_UNREADABLE: "Plate unreadable",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _center(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def _near_equal(a: Optional[str], b: Optional[str], max_diff: int) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b)) <= max_diff


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_") or "x"


@dataclass
class PlateObservation:
    """One plate detection in one frame, after gating and variant selection."""

    timestamp_sim: float
    frame_number: int
    box: tuple
    det_confidence: float
    sharpness: float
    raw: Optional[str]                 # best OCR string as read
    parsed: Optional[ParsedRead]       # plate window inside it (None: no plate structure)
    ocr_confidence: float
    weight: float                      # routine quality score
    confidences: list = field(default_factory=list)   # per character of `raw`

    @property
    def width_px(self) -> float:
        return float(self.box[2] - self.box[0])


@dataclass
class PlateTrack:
    """One physical plate followed across frames of one junction camera."""

    track_id: int
    junction_id: str
    camera_id: Optional[str]
    observations: list = field(default_factory=list)
    # Evidence: the frame of the best observation (largest, sharpest plate).
    best: Optional[PlateObservation] = None
    best_jpeg: Optional[bytes] = None
    # Result of the last vote.
    plate: Optional[str] = None
    plate_raw: Optional[str] = None
    status: str = STATUS_UNREADABLE
    state_code: Optional[str] = None
    state_name: Optional[str] = None
    confidence: Optional[float] = None
    support_frames: int = 0
    # Strict rule-based partial plate of this track (anpr_partial) + registry matches.
    partial: Optional[dict] = None
    candidates: list = field(default_factory=list)
    # Publication bookkeeping.
    published_key: Optional[tuple] = None
    published_best: Optional[int] = None
    rendered_at: float = 0.0
    version: int = 0
    image_url: Optional[str] = None
    crop_url: Optional[str] = None

    @property
    def first_seen(self) -> float:
        return self.observations[0].timestamp_sim

    @property
    def last_seen(self) -> float:
        return self.observations[-1].timestamp_sim

    @property
    def frames_seen(self) -> int:
        return len({obs.frame_number for obs in self.observations})

    def text_key(self) -> Optional[str]:
        if self.plate:
            return self.plate
        texts = [obs.parsed.chars for obs in self.observations if obs.parsed is not None]
        return texts[-1] if texts else None


def observation_rank(obs: PlateObservation) -> tuple:
    """Evidence choice: biggest plate first, then sharpest, then most confident."""
    return round(obs.width_px / 4.0), obs.sharpness, obs.ocr_confidence


def vote_track(track: PlateTrack) -> None:
    """Routine-violation plate decision for one track (dual_pipeline._vote +
    the record status rule), with no regional prior: the feed spans states."""
    usable = sorted(((obs.parsed, obs.weight) for obs in track.observations
                     if obs.parsed is not None), key=lambda item: -item[1])[:VOTE_TOP_N]
    voted = vote_characters(usable)
    validation = None
    if voted is not None:
        validation = validate_plate(voted.chars, voted.confidences, log=False,
                                    state_prior=None, alternatives=voted.alternatives)

    track.plate_raw = voted.chars if voted else None
    if validation is not None and validation.valid:
        track.plate = validation.plate
        track.state_code = validation.state_code
        track.state_name = validation.state_name
        track.confidence = validation.confidence
        track.support_frames = len({
            obs.frame_number for obs in track.observations
            if obs.parsed is not None
            and _near_equal(obs.parsed.chars, voted.chars, SUPPORT_MAX_DIFF)
        })
        confirmed = (validation.number_digits == 4 and not validation.low_confidence
                     and track.support_frames >= CONFIRM_SUPPORT_FRAMES)
        track.status = STATUS_CONFIRMED if confirmed else STATUS_LOW_CONFIDENCE
    else:
        track.plate = None
        track.state_code = track.state_name = track.confidence = None
        track.support_frames = 0
        any_text = any(obs.raw for obs in track.observations)
        track.status = STATUS_LOW_CONFIDENCE if any_text else STATUS_UNREADABLE


def strict_partial(track: PlateTrack) -> None:
    """Strict partial plate of one track: its best reads (by quality) merged per
    character. A track is one tracker id, so reads are never mixed across
    vehicles. Never raises: on failure the track simply has no partial."""
    reads = sorted((obs for obs in track.observations if obs.raw and obs.confidences),
                   key=lambda obs: -obs.weight)[:STRICT_MAX_READS]
    try:
        track.partial = analyze_partial_plate([
            {"text": obs.raw, "confidences": obs.confidences, "frame": obs.frame_number,
             "track_id": f"{track.junction_id}-{track.track_id}"} for obs in reads])
    except Exception as exc:
        track.partial = None
        print(f"[LIVE ANPR] strict partial failed for {track.junction_id} track {track.track_id}: {exc}",
              flush=True)


def registry_matches(partial: Optional[dict]) -> list:
    """Plates that fit the strict pattern in the citizen vehicle registry and in
    the RFID registry (with EPC). Empty when nothing was read."""
    if not partial or known_char_count(partial.get("partial_pattern") or "") == 0:
        return []
    try:
        from app.core.database import SessionLocal
        from app.services.fine_service import registry_candidates, rfid_registry_candidates

        db = SessionLocal()
        try:
            citizens = [{**c, "source": "vehicles"} for c in registry_candidates(db, partial)]
            return sorted(rfid_registry_candidates(db, partial) + citizens,
                          key=lambda c: (-c["score"], c["plate"]))
        finally:
            db.close()
    except Exception as exc:   # the registry is optional; ANPR keeps running
        print(f"[LIVE ANPR] registry match failed: {exc}", flush=True)
        return []


def partial_summary(partial: Optional[dict]) -> Optional[dict]:
    if not partial:
        return None
    keys = ("format", "partial_pattern", "alternative_patterns", "regex", "is_complete", "plate",
            "confidence", "segments", "conflicts", "corrections", "track_id", "frames_used",
            "raw_ocr_text", "char_confidences")
    return {key: partial.get(key) for key in keys}


def strict_label(track: PlateTrack) -> Optional[str]:
    pattern = (track.partial or {}).get("partial_pattern")
    return pattern if pattern and known_char_count(pattern) else None


def strict_second_line(track: PlateTrack) -> str:
    partial = track.partial or {}
    state = ((partial.get("segments") or {}).get("state") or {}).get("value")
    kind = ("Plate complete (strict)" if partial.get("is_complete")
            else "Partial plate - unread characters marked" if strict_label(track) else "Plate unreadable")
    return f"{STATE_CODES.get(state, 'State unknown')} | {kind}"


class LiveAnprWorker:
    """Latest-frame, rule-based ANPR worker for the live CARLA camera feeds."""

    def __init__(self, adapter=None, broadcaster=None,
                 evidence_root: Path = EVIDENCE_ROOT) -> None:
        self._lock = threading.Lock()
        self._pending: dict[str, dict[str, Any]] = {}
        self._new_frame = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_pass: dict[str, float] = {}

        self._adapter = adapter
        self._broadcaster = broadcaster
        self._cfg = None
        self.session = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.evidence_dir = Path(evidence_root) / self.session

        self._tracks: dict[str, list[PlateTrack]] = {}
        self._last_ts: dict[str, float] = {}
        self._next_track_id = 1
        self.detections_by_id: dict[str, dict[str, Any]] = {}
        self._detection_order: deque = deque()

        self.submitted = 0
        self.processed = 0
        self.plates_detected = 0
        self.plates_gated = 0
        self.published = 0
        self.last_error: Optional[str] = None
        self.last_processed_at: Optional[str] = None
        self.last_pass_ms: Optional[float] = None
        self.per_junction: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # dependencies (lazy so importing this module never loads a model)
    # ------------------------------------------------------------------
    @property
    def adapter(self):
        if self._adapter is None:
            from app.services.anpr_adapter import get_anpr_adapter

            self._adapter = get_anpr_adapter()
        return self._adapter

    @property
    def cfg(self):
        if self._cfg is None:
            from app.services.rfid.config import RfidFeatureConfig

            self._cfg = RfidFeatureConfig.from_env()
        return self._cfg

    def _broadcast(self, message: dict) -> None:
        try:
            if self._broadcaster is not None:
                self._broadcaster(message)
                return
            from app.routers.carla_ws import broadcast_live_message

            broadcast_live_message(message)
        except Exception as exc:  # the portal is optional; ANPR keeps running
            self.last_error = f"broadcast {type(exc).__name__}: {exc}"

    def _junction_stats(self, junction_id: str) -> dict[str, Any]:
        return self.per_junction.setdefault(junction_id, {
            "submitted": 0, "processed": 0, "plates_detected": 0,
            "confirmed_plates": 0, "last_plate": None, "last_seen": None,
        })

    # ------------------------------------------------------------------
    # Submission (called from the async websocket handler - must be cheap)
    # ------------------------------------------------------------------
    def submit(self, junction_id: str, image_base64: str, timestamp_sim: float,
               frame_number: int, camera_id: Optional[str] = None) -> bool:
        """Hand the newest frame of a junction to ANPR. Never blocks."""
        if self._stop.is_set() or not image_base64:
            return False

        payload = {
            "junction_id": junction_id,
            "camera_id": camera_id,
            "image_base64": image_base64,
            "timestamp_sim": timestamp_sim,
            "frame_number": frame_number,
            "queued_at": time.monotonic(),
        }
        with self._lock:
            # Latest-frame buffer: a frame ANPR did not reach in time is dropped.
            self._pending[junction_id] = payload
            self.submitted += 1
            self._junction_stats(junction_id)["submitted"] += 1

        self._new_frame.set()
        self._ensure_thread()
        return True

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="live-anpr-worker",
                                            daemon=True)
            self._thread.start()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _take_due(self) -> tuple[Optional[dict[str, Any]], float]:
        """The pending frame of the junction waited on longest, if its
        interval has passed; else (None, seconds until one is due)."""
        now = time.monotonic()
        with self._lock:
            if not self._pending:
                return None, 1.0
            due = sorted(self._pending, key=lambda j: self._last_pass.get(j, 0.0))
            junction_id = due[0]
            wait = JUNCTION_INTERVAL_S - (now - self._last_pass.get(junction_id, 0.0))
            if wait > 0:
                return None, wait
            self._last_pass[junction_id] = now
            return self._pending.pop(junction_id), 0.0

    def _run(self) -> None:
        while not self._stop.is_set():
            payload, wait = self._take_due()
            if payload is None:
                self._new_frame.wait(timeout=max(0.05, min(wait, 1.0)))
                self._new_frame.clear()
                continue
            self.process_payload(payload)

    def process_payload(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """ANPR one frame, update the junction's plate tracks, publish changes.
        Returns the detection events published for this frame."""
        junction_id = payload["junction_id"]
        started = time.perf_counter()
        published: list[dict[str, Any]] = []
        try:
            jpeg = base64.b64decode(payload["image_base64"])
            frame = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                self.last_error = f"{junction_id}: undecodable frame"
                return published

            observations = self._observe(frame, payload)
            published = self._update_tracks(junction_id, payload, observations, jpeg, frame.shape)

            self.processed += 1
            stats = self._junction_stats(junction_id)
            stats["processed"] += 1
            stats["plates_detected"] += len(observations)
            self.last_processed_at = _utc_now()
        except Exception as exc:  # never kill the worker
            self.last_error = f"{type(exc).__name__}: {exc}"
        finally:
            self.last_pass_ms = round((time.perf_counter() - started) * 1000.0, 1)
        return published

    # ------------------------------------------------------------------
    # per frame: detection + OCR + rules
    # ------------------------------------------------------------------
    def _observe(self, frame: np.ndarray, payload: dict[str, Any]) -> list[PlateObservation]:
        from app.services.rfid.evidence import crop_box, plate_sharpness
        from app.services.rfid.plate_rules import gate

        cfg = self.cfg
        reads = self.adapter.detect_and_read(frame, two_line_aspect=cfg.ocr_two_line_aspect)
        observations = []
        for read in reads:
            box = tuple(float(v) for v in read.box)
            det_conf = float(read.det_confidence or 0.0)
            if read.skipped or gate(box, det_conf, cfg) is not None:
                self.plates_gated += 1
                continue

            # Same variant selection as dual_pipeline.ocr_vehicle_plates:
            # structurally valid first, then lowest structural cost, then conf.
            best = None
            for variant in read.ocr_variants or []:
                text = variant.get("text")
                confs = variant.get("confidences") or []
                parsed = parse_plate(text, confs)
                mean_conf = sum(confs) / len(confs) if confs else 0.0
                key = (parsed is not None, -(parsed.cost if parsed else 9.0), mean_conf)
                if best is None or key > best[0]:
                    best = (key, text, parsed, mean_conf, list(confs))
            raw, parsed, ocr_conf, char_confs = best[1:] if best else (None, None, 0.0, [])

            crop = crop_box(frame, box, pad=0)
            sharp = plate_sharpness(crop) if crop.size else 0.0
            width, height = box[2] - box[0], box[3] - box[1]
            # Routine-violation plate quality score.
            weight = ((1 - math.exp(-sharp / 300.0)) * min(1.0, math.sqrt(width * height / 12000.0))
                      * (0.5 + det_conf / 2))
            observations.append(PlateObservation(
                timestamp_sim=float(payload["timestamp_sim"]),
                frame_number=int(payload["frame_number"]),
                box=box, det_confidence=det_conf, sharpness=sharp, raw=raw,
                parsed=parsed, ocr_confidence=ocr_conf, weight=max(weight, 1e-4),
                confidences=char_confs))
            self.plates_detected += 1
        return observations

    # ------------------------------------------------------------------
    # per junction: tracking + voting + publication
    # ------------------------------------------------------------------
    def _update_tracks(self, junction_id: str, payload: dict[str, Any],
                       observations: list[PlateObservation], jpeg: bytes,
                       frame_shape) -> list[dict[str, Any]]:
        ts = float(payload["timestamp_sim"])
        last_ts = self._last_ts.get(junction_id)
        if last_ts is not None and ts < last_ts - NEW_RUN_BACKSTEP_S:
            # Sim time went backwards: a new CARLA run. Old tracks are history.
            self._tracks[junction_id] = []
        self._last_ts[junction_id] = ts

        tracks = [t for t in self._tracks.get(junction_id, []) if ts - t.last_seen <= TRACK_EXPIRE_S]
        self._tracks[junction_id] = tracks

        touched: list[PlateTrack] = []
        for obs in sorted(observations, key=lambda o: -o.weight):
            track = self._match(tracks, touched, obs)
            if track is None:
                track = PlateTrack(self._next_track_id, junction_id, payload.get("camera_id"))
                self._next_track_id += 1
                tracks.append(track)
            track.observations.append(obs)
            if track.best is None or observation_rank(obs) > observation_rank(track.best):
                track.best = obs
                track.best_jpeg = jpeg
            touched.append(track)

        published = []
        for track in touched:
            vote_track(track)
            strict_partial(track)
            event = self._maybe_publish(track, frame_shape)
            if event is not None:
                published.append(event)
        return published

    @staticmethod
    def _match(tracks: list[PlateTrack], taken: list[PlateTrack],
               obs: PlateObservation) -> Optional[PlateTrack]:
        """Box continuity first, else near-equal text; one read per track per frame."""
        cx, cy = _center(obs.box)
        best, best_key = None, None
        for track in tracks:
            if track in taken:
                continue
            last = track.observations[-1]
            lx, ly = _center(last.box)
            distance = math.hypot(cx - lx, cy - ly)
            near = (obs.timestamp_sim - last.timestamp_sim) <= TRACK_BOX_DT_S and distance <= TRACK_BOX_PX
            same_text = obs.parsed is not None and _near_equal(
                obs.parsed.chars, track.text_key(), TRACK_TEXT_MAX_DIFF)
            if not near and not same_text:
                continue
            key = (0 if near else 1, distance)
            if best_key is None or key < best_key:
                best, best_key = track, key
        return best

    def _maybe_publish(self, track: PlateTrack, frame_shape) -> Optional[dict[str, Any]]:
        if track.frames_seen < MIN_FRAMES_TO_SHOW:
            return None
        key = (track.status, track.plate, (track.partial or {}).get("partial_pattern"))
        best_id = id(track.best)
        changed = key != track.published_key
        better_frame = best_id != track.published_best
        now = time.monotonic()
        if not changed and not (better_frame and now - track.rendered_at >= RENDER_MIN_INTERVAL_S):
            return None

        if key != track.published_key:
            track.candidates = registry_matches(track.partial)
        self._render(track)
        track.published_key = key
        track.published_best = best_id
        track.rendered_at = now

        event = self.detection_event(track)
        detection_id = event["detection_id"]
        if detection_id not in self.detections_by_id:
            self._detection_order.append(detection_id)
            while len(self._detection_order) > RECENT_DETECTIONS_MAX:
                self.detections_by_id.pop(self._detection_order.popleft(), None)
        self.detections_by_id[detection_id] = event

        stats = self._junction_stats(track.junction_id)
        if track.status == STATUS_CONFIRMED and changed:
            stats["confirmed_plates"] += 1
        if track.plate:
            stats["last_plate"] = format_plate(track.plate)
            stats["last_seen"] = event["updated_at"]
        if track.plate or event["partial_pattern"]:
            print(f"[LIVE ANPR] {track.junction_id} track {track.track_id}: "
                  f"strict {event['partial_pattern']!r} "
                  f"({'complete' if (track.partial or {}).get('is_complete') else 'partial'}, "
                  f"{len(track.candidates)} registry match(es)) | vote "
                  f"{format_plate(track.plate) if track.plate else '-'} ({track.status}, "
                  f"{track.support_frames} frames)", flush=True)

        self.published += 1
        self._broadcast(event)
        return event

    def _render(self, track: PlateTrack) -> None:
        """Routine-style evidence card + the plate crop, saved under the session."""
        from app.services.rfid.evidence import crop_box, vehicle_box_around_plate

        best = track.best
        if best is None or track.best_jpeg is None:
            return
        frame = cv2.imdecode(np.frombuffer(track.best_jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return
        crop = crop_box(frame, best.box, pad=3).copy()
        image = frame.copy()
        draw_plate_evidence(
            image,
            vehicle_box=vehicle_box_around_plate(best.box, frame.shape),
            vehicle_label=f"{track.junction_id} | vehicle {track.track_id}",
            plate_box=best.box,
            plate_crop=crop,
            # Strict reading only: unread characters stay marked, never guessed.
            plate_label=strict_label(track),
            second_line=strict_second_line(track),
            footer=f"{track.junction_id} | frame {best.frame_number} | t={best.timestamp_sim:.2f}s",
            extra_lines=([f"raw OCR {best.raw}"] if best.raw else []),
        )

        track.version += 1
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        stem = _safe(f"{track.junction_id}_vehicle{track.track_id}_v{track.version}")
        image_path = self.evidence_dir / f"{stem}.jpg"
        crop_path = self.evidence_dir / f"{stem}_plate.jpg"
        cv2.imwrite(str(image_path), image, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if crop.size:
            scale = max(1.0, 160.0 / max(1, crop.shape[0]))
            big = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(str(crop_path), big, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            track.crop_url = f"/api/anpr/live/evidence/{self.session}/{crop_path.name}"
        track.image_url = f"/api/anpr/live/evidence/{self.session}/{image_path.name}"

    def detection_event(self, track: PlateTrack) -> dict[str, Any]:
        best = track.best
        return {
            "type": "live_plate_detection",
            "detection_id": f"{self.session}-{track.junction_id}-{track.track_id}",
            "vehicle_id": track.track_id,
            "junction_id": track.junction_id,
            "camera_id": track.camera_id,
            "plate_number": format_plate(track.plate) if track.plate else "",
            "plate_compact": track.plate or "",
            "plate_raw": track.plate_raw or (best.raw if best else "") or "",
            "plate_status": track.status,
            "state_code": track.state_code,
            "state_name": track.state_name,
            "plate_confidence": round(track.confidence, 4) if track.confidence is not None else None,
            "support_frames": track.support_frames,
            "frames_seen": track.frames_seen,
            "plate_reads": sum(1 for obs in track.observations if obs.parsed is not None),
            "first_seen_ts": round(track.first_seen, 3),
            "last_seen_ts": round(track.last_seen, 3),
            "evidence_frame": best.frame_number if best else None,
            "evidence_time_s": round(best.timestamp_sim, 3) if best else None,
            "plate_width_px": round(best.width_px, 1) if best else None,
            "image": track.image_url,
            "plate_image": track.crop_url,
            # strict rule-based partial plate (same format as uploads and RFID)
            "partial_pattern": (track.partial or {}).get("partial_pattern"),
            "partial_plate": partial_summary(track.partial),
            "candidates": track.candidates[:50],
            "updated_at": _utc_now(),
        }

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def recent_detections(self, junction_id: Optional[str] = None) -> list[dict[str, Any]]:
        items = [self.detections_by_id[d] for d in self._detection_order if d in self.detections_by_id]
        if junction_id:
            items = [item for item in items if item["junction_id"] == junction_id]
        return sorted(items, key=lambda item: item["updated_at"], reverse=True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            pending = sorted(self._pending.keys())
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "pipeline": "rule-based (anpr_adapter + routine plate rules)",
            "junction_interval_s": JUNCTION_INTERVAL_S,
            "session": self.session,
            "submitted": self.submitted,
            "processed": self.processed,
            "plate_detections": self.plates_detected,
            "plates_gated": self.plates_gated,
            "published": self.published,
            "last_pass_ms": self.last_pass_ms,
            "pending_junctions": pending,
            "active_tracks": {j: len(t) for j, t in self._tracks.items()},
            "last_error": self.last_error,
            "last_processed_at": self.last_processed_at,
            "per_junction": {k: dict(v) for k, v in self.per_junction.items()},
            "recent_detections": self.recent_detections()[:10],
        }


_worker: Optional[LiveAnprWorker] = None
_worker_lock = threading.Lock()


def get_live_anpr_worker() -> LiveAnprWorker:
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = LiveAnprWorker()
        return _worker


def submit_camera_frame_to_anpr(junction_id: str, image_base64: str, timestamp_sim: float,
                                frame_number: int, camera_id: Optional[str] = None) -> bool:
    """Fire-and-forget submission for the websocket ingest path."""
    try:
        return get_live_anpr_worker().submit(junction_id, image_base64, timestamp_sim,
                                              frame_number, camera_id)
    except Exception:
        # ANPR must never break the live stream.
        return False


def evidence_path(session: str, filename: str) -> Optional[Path]:
    """Resolve a served evidence file, refusing anything outside the root."""
    path = (EVIDENCE_ROOT / session / filename).resolve()
    if path.parent.parent != EVIDENCE_ROOT.resolve() or path.suffix != ".jpg" or not path.is_file():
        return None
    return path
