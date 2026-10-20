"""Evidence selection and storage.

Frames are chosen by what makes a plate readable - plate sharpness (variance of
Laplacian), plate size and OCR confidence - and written as JPEG files under
``runtime/incident_evidence/<incident_id>/<junction>/``. Only the PATH and the
sha256 go into Postgres; image bytes never do.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.services.rfid.config import DEFAULT_CONFIG, RfidFeatureConfig

KIND_FRAME = "annotated_frame"
KIND_PLATE = "plate_crop"
KIND_CRASH = "crash_frame"
KIND_HERO = "hero_frame"            # the large annotated card image
KIND_STRIP = "strip_frame"          # up to N distinct best frames
KIND_CONTEXT = "context_frame"      # nearest frame at a non-crash junction at t_crash
# ONE primary evidence item per (incident, suspect vehicle, junction): the
# best-scoring frame so far. A better frame later adds a new primary row with a
# higher score (older files are kept, never deleted); the API shows the best.
KIND_PRIMARY = "primary_frame"      # annotated: suspect box, plate box, inset, read text
KIND_PRIMARY_RAW = "primary_raw"    # the same frame, unannotated
KIND_PRIMARY_PLATE = "primary_plate"  # the plate crop of that frame
PRIMARY_KINDS = (KIND_PRIMARY, KIND_PRIMARY_RAW, KIND_PRIMARY_PLATE)

# Weights of the primary-evidence score (sum to 1.0).
PRIMARY_WEIGHTS = {
    "quality": 0.30,      # routine-violation crop quality: sharpness x area x detector conf
    "ocr": 0.20,          # mean OCR character confidence
    "valid": 0.15,        # OCR text passes the plate rules (plate_validation)
    "association": 0.15,  # plate inside the suspect's projected box
    "aspect": 0.10,       # plate-shaped box
    "exposure": 0.10,     # brightness / contrast of the crop
}
PLATE_ASPECT_TARGET = 4.0           # single-line overlay plate, width / height


def _safe(text: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(text or "x")).strip("_") or "x"


def plate_sharpness(crop: np.ndarray) -> float:
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def score_candidate(ocr_confidence: float, plate_area: float, sharpness: float) -> float:
    """Higher is better. Weighted so a sharp, confident, large plate wins."""
    return (0.5 * float(ocr_confidence or 0.0)
            + 0.3 * min(1.0, float(plate_area or 0.0) / 12000.0)
            + 0.2 * min(1.0, float(sharpness or 0.0) / 20000.0))


def plate_quality(sharpness: float, width: float, height: float, det_confidence: float) -> float:
    """The routine-violation crop quality (dual_pipeline.detect_vehicle_plates):
    saturating sharpness x plate size x detector confidence, 0..1."""
    return ((1.0 - math.exp(-max(0.0, sharpness) / 300.0))
            * min(1.0, math.sqrt(max(0.0, width * height) / 12000.0))
            * (0.5 + max(0.0, min(1.0, det_confidence)) / 2.0))


def exposure_score(crop: np.ndarray | None) -> float:
    """1.0 for a mid-grey, high-contrast crop; low for black/blown-out/flat ones."""
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    brightness = 1.0 - min(1.0, abs(float(gray.mean()) - 128.0) / 128.0)
    contrast = min(1.0, float(gray.std()) / 64.0)
    return 0.5 * brightness + 0.5 * contrast


def aspect_score(width: float, height: float, cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> float:
    """1.0 at the expected plate aspect, falling to 0 at the gate's limits."""
    aspect = width / max(1.0, height)
    if aspect < cfg.gate_aspect_min or aspect > cfg.gate_aspect_max:
        return 0.0
    limit = cfg.gate_aspect_max if aspect >= PLATE_ASPECT_TARGET else cfg.gate_aspect_min
    span = abs(math.log(limit / PLATE_ASPECT_TARGET)) or 1.0
    return max(0.0, 1.0 - abs(math.log(aspect / PLATE_ASPECT_TARGET)) / span)


def primary_score(rule, crop: np.ndarray | None, association: float | None,
                  cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> tuple[float, dict]:
    """Score one suspect candidate frame for the junction's primary evidence.

    ``rule`` is a plate_rules.RuleRead (box, det_confidence, mean_conf, valid,
    sharpness); ``association`` the plate-in-suspect-box fraction (None when
    the frame had no vehicle metadata: the single-plate fallback, scored 0.5).
    Returns (score 0..1, components) so the choice is explainable.
    """
    width, height = float(rule.width_px), float(rule.height_px)
    parts = {
        "quality": plate_quality(rule.sharpness, width, height, rule.det_confidence),
        "ocr": max(0.0, min(1.0, float(rule.mean_conf or 0.0))),
        "valid": 1.0 if rule.valid else 0.0,
        "association": 0.5 if association is None else max(0.0, min(1.0, float(association))),
        "aspect": aspect_score(width, height, cfg),
        "exposure": exposure_score(crop),
    }
    score = sum(PRIMARY_WEIGHTS[name] * value for name, value in parts.items())
    return round(score, 4), {name: round(value, 4) for name, value in parts.items()}


def crop_box(frame: np.ndarray, box, pad: int = 4) -> np.ndarray:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in box]
    return frame[max(0, y1 - pad):min(height, y2 + pad), max(0, x1 - pad):min(width, x2 + pad)]


def annotate(frame: np.ndarray, box, banner: str,
             colour: tuple = (0, 255, 0)) -> np.ndarray:
    """Draw the plate box and a banner strip on a copy of the frame."""
    image = frame.copy()
    if box is not None:
        x1, y1, x2, y2 = [int(v) for v in box]
        cv2.rectangle(image, (x1, y1), (x2, y2), colour, 2)
    height, width = image.shape[:2]
    strip = max(28, height // 22)
    header = np.zeros((strip, width, 3), np.uint8)
    scale = max(0.4, min(1.0, width / 1400.0))
    cv2.putText(header, banner[:160], (8, int(strip * 0.7)),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([header, image])


def banner_text(epc: str | None, rfid_plate: str | None, anpr_plate: str | None,
                status: str, junction_id: str | None, timestamp_sim: float | None) -> str:
    epc_tail = (epc or "")[-6:]
    when = "?" if timestamp_sim is None else f"{timestamp_sim:.2f}s"
    return (f"RFID EPC ...{epc_tail} -> {rfid_plate or 'UNKNOWN'} | "
            f"ANPR {anpr_plate or 'none'} | {status} | {junction_id or '?'} | t={when}")


def dhash(image: np.ndarray, size: int = 8) -> int:
    """Perceptual difference hash: near-identical frames give near-identical hashes."""
    if image is None or image.size == 0:
        return 0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def vehicle_box_around_plate(plate_box, frame_shape) -> tuple:
    """A vehicle-sized box around a plate (no vehicle detector on this feed).

    A front plate sits low and centred on the car; a car is roughly 3.5 plate
    widths wide and 3 tall. Used only to frame the evidence image.
    """
    x1, y1, x2, y2 = [float(v) for v in plate_box]
    width = max(1.0, x2 - x1)
    cx = (x1 + x2) / 2.0
    height, frame_w = frame_shape[:2]
    return (max(0.0, cx - 1.8 * width), max(0.0, y1 - 2.6 * width),
            min(frame_w - 1.0, cx + 1.8 * width), min(height - 1.0, y2 + 0.5 * width))


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class SavedEvidence:
    kind: str
    path: str
    sha256: str
    width: int
    height: int
    score: float


class EvidenceStore:
    """Writes evidence files and returns (path, sha256) records."""

    def __init__(self, root: str | Path | None = None,
                 cfg: RfidFeatureConfig = DEFAULT_CONFIG):
        self.cfg = cfg
        self.root = Path(root or cfg.evidence_dir)
        self.written = 0
        self.bytes_written = 0

    def directory(self, incident_id: str, junction_id: str | None) -> Path:
        path = self.root / _safe(incident_id) / _safe(junction_id or "unknown")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_jpeg(self, incident_id: str, junction_id: str | None, kind: str,
                  name: str, image: np.ndarray, score: float = 0.0) -> SavedEvidence | None:
        if image is None or image.size == 0:
            return None
        ok, encoded = cv2.imencode(".jpg", image,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), self.cfg.evidence_jpeg_quality])
        if not ok:
            return None
        payload = encoded.tobytes()
        target = self.directory(incident_id, junction_id) / f"{_safe(name)}.jpg"
        # Never overwrite: an evidence row's sha256 must keep matching its file.
        suffix = 1
        while target.exists():
            target = target.with_name(f"{_safe(name)}_{suffix}.jpg")
            suffix += 1
        target.write_bytes(payload)
        self.written += 1
        self.bytes_written += len(payload)
        return SavedEvidence(kind=kind, path=str(target), sha256=sha256_of(payload),
                             width=int(image.shape[1]), height=int(image.shape[0]), score=score)

    def counters(self) -> dict:
        return {"files_written": self.written, "bytes_written": self.bytes_written}
