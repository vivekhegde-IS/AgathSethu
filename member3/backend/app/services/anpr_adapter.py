"""The ONE adapter for Member 3's ANPR plate model.

Everything that needs plate text in the RFID cross-verification feature goes
through this module. No other code loads the plate detector or the OCR.

Model
-----
``member3/backend/models/number_plate/number_plate_detector.pt`` - Member 3's
own trained plate detector (Ultralytics YOLO). It returns plate BOXES only, so
the box is cropped and read with the OCR already used by the routine-violation
pipeline (``routine_violation_video.plate_ocr``, recognition-only PP-OCRv3 with
per-character confidences). The model files are never modified.

The OpenVINO export next to the ``.pt`` is preferred (same model, ~faster on
CPU/iGPU); the ``.pt`` is the fallback. Device, thresholds and the detection
mode all come from the environment.

Key rule for this feature
-------------------------
The adapter is BLIND: it never receives, and never uses, the RFID plate. The
caller compares the returned plate with the registry *afterwards*. It also
never applies a regional / majority-state prior: the simulated plates span
eight different states, so a majority-state prior would be actively harmful.
Structure fixes (position-aware letter/digit repair) are still applied.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_MODEL_PATH = BACKEND_DIR / "models" / "number_plate" / "number_plate_detector.pt"
# A tile box this close to an interior tile seam is a cut-off plate fragment.
TILE_SEAM_PX = 4
DEFAULT_OPENVINO_DIR = BACKEND_DIR / "models" / "number_plate" / "number_plate_detector_openvino_model"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _openvino_available() -> bool:
    """True only when the OpenVINO runtime can actually be imported.

    An OpenVINO *export* directory on disk is not enough: loading it through
    Ultralytics triggers a runtime ``pip install openvino`` when the package is
    missing, which blocks/hangs startup. Falling back to the ``.pt`` model keeps
    the backend booting immediately.
    """
    try:
        import openvino  # noqa: F401
        return True
    except Exception:
        return False


@dataclass
class AnprConfig:
    """Model path, device and thresholds. Everything overridable via ANPR_*."""

    model_path: str = str(DEFAULT_MODEL_PATH)
    openvino_dir: str = str(DEFAULT_OPENVINO_DIR)
    prefer_openvino: bool = True
    device: str = ""                 # "" = auto (intel:gpu if available, else cpu)
    # Plate detection
    det_conf: float = 0.25
    iou: float = 0.45
    # 512 is the plate model's trained/exported input. An OpenVINO export with
    # dynamic: false REJECTS any other size at inference time, so the adapter
    # overrides this with the size recorded in the export's metadata.
    imgsz: int = 512
    max_det: int = 20
    # Detection mode on a live 1280x720 junction frame. Measured on the
    # recorded CARLA junction video (12 frames, plates ~50 px wide):
    #   "full"     one pass over the whole frame -> reads "HA4521"
    #   "tiled"    overlapping tiles -> reads "KAAA4521" (closest to the truth,
    #              "KA01AT4521"), same latency  
    #   "upscaled" 2x frame first -> reads "HA4521", no better than full
    # "tiled" is therefore the default for live frames.
    mode: str = "tiled"
    tile_size: int = 640
    tile_overlap: float = 0.2
    upscale: float = 2.0
    # OCR
    ocr_accept_conf: float = 0.60    # early-stop threshold for a valid read
    min_plate_px: int = 12           # smaller boxes are not worth OCR
    # Two-line split threshold for the OCR (crop width/height below this is
    # read as a two-line plate). None = the OCR module default; 0 = never split
    # (single-line plates, e.g. the CARLA overlay plates).
    two_line_aspect: float | None = None
    # Housekeeping
    warm_up: bool = True
    latency_window: int = 50

    @classmethod
    def from_env(cls, prefix: str = "ANPR_") -> "AnprConfig":
        return cls(
            model_path=_env(prefix + "MODEL_PATH", cls.model_path),
            openvino_dir=_env(prefix + "OPENVINO_DIR", cls.openvino_dir),
            prefer_openvino=_env_bool(prefix + "PREFER_OPENVINO", cls.prefer_openvino),
            device=_env(prefix + "DEVICE", cls.device),
            det_conf=_env_float(prefix + "DET_CONF", cls.det_conf),
            iou=_env_float(prefix + "IOU", cls.iou),
            imgsz=_env_int(prefix + "IMGSZ", cls.imgsz),
            max_det=_env_int(prefix + "MAX_DET", cls.max_det),
            mode=_env(prefix + "MODE", cls.mode),
            tile_size=_env_int(prefix + "TILE_SIZE", cls.tile_size),
            tile_overlap=_env_float(prefix + "TILE_OVERLAP", cls.tile_overlap),
            upscale=_env_float(prefix + "UPSCALE", cls.upscale),
            ocr_accept_conf=_env_float(prefix + "OCR_ACCEPT_CONF", cls.ocr_accept_conf),
            min_plate_px=_env_int(prefix + "MIN_PLATE_PX", cls.min_plate_px),
            two_line_aspect=(_env_float(prefix + "TWO_LINE_ASPECT", 0.0)
                             if prefix + "TWO_LINE_ASPECT" in os.environ else cls.two_line_aspect),
            warm_up=_env_bool(prefix + "WARM_UP", cls.warm_up),
            latency_window=_env_int(prefix + "LATENCY_WINDOW", cls.latency_window),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_CONFIG = AnprConfig()


@dataclass
class PlateRead:
    """One plate found in a frame."""

    box: tuple                # (x1, y1, x2, y2) in the ORIGINAL frame's pixels
    plate_text: str | None    # display form, e.g. "MP 04 ZJ 5434"
    plate_norm: str | None    # "MP04ZJ5434"
    raw_ocr: str | None
    det_confidence: float
    ocr_confidence: float
    valid: bool
    per_char: list = field(default_factory=list)
    # Every OCR reading of this crop [{text, confidences, variant}], so a caller
    # can apply its own plate rules to each one (the adapter stays blind).
    ocr_variants: list = field(default_factory=list)
    # Detected but not OCR'd ("below_min_plate_px"); the box still counts as a
    # plate that was SEEN, e.g. to report PLATE_TOO_SMALL.
    skipped: str | None = None

    @property
    def width_px(self) -> float:
        return float(self.box[2] - self.box[0])

    @property
    def height_px(self) -> float:
        return float(self.box[3] - self.box[1])

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AnprAdapter:
    """Loads the plate detector once and reads plates on demand."""

    def __init__(self, config: AnprConfig | None = None):
        self.config = config or AnprConfig.from_env()
        self._model = None
        self._backend = "not loaded"
        self._lock = threading.Lock()
        self._infer_lock = threading.Lock()
        self.latencies_ms: deque = deque(maxlen=self.config.latency_window)
        self.frames = 0
        self.detections = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def _resolve_path(self) -> tuple[str, bool]:
        """(path, is_openvino)."""
        openvino_dir = Path(self.config.openvino_dir)
        pt_path = Path(self.config.model_path)
        if self.config.prefer_openvino and openvino_dir.is_dir() and _openvino_available():
            return str(openvino_dir), True
        if pt_path.is_file():
            return str(pt_path), False
        if openvino_dir.is_dir() and _openvino_available():
            return str(openvino_dir), True
        raise FileNotFoundError(
            f"ANPR model not found: neither {pt_path} nor {openvino_dir}"
        )

    def _pick_device(self, is_openvino: bool) -> str:
        if self.config.device:
            return self.config.device
        if not is_openvino:
            return "cpu"
        try:
            import openvino as ov
            devices = list(ov.Core().available_devices)
        except Exception:
            devices = []
        return "intel:gpu" if "GPU" in devices else "cpu"

    def load(self) -> "AnprAdapter":
        """Load the model (idempotent)."""
        with self._lock:
            if self._model is not None:
                return self
            from ultralytics import YOLO

            path, is_openvino = self._resolve_path()
            self._model = YOLO(path, task="detect") if is_openvino else YOLO(path)
            self._device = self._pick_device(is_openvino)
            self._imgsz = self.config.imgsz
            if is_openvino:
                static = _static_export_imgsz(Path(path))
                if static is not None:
                    self._imgsz = static
            self._backend = (
                f"Ultralytics YOLO {'OpenVINO' if is_openvino else 'PyTorch'} "
                f"({Path(path).name}) on {self._device}, imgsz={self._imgsz}"
            )
            return self

    def warm_up(self) -> dict[str, Any]:
        """Load once and run one dummy inference so the first real frame is fast."""
        self.load()
        dummy = np.zeros((720, 1280, 3), np.uint8)
        started = time.perf_counter()
        self.detect(dummy)
        return {
            "backend": self._backend,
            "device": self._device,
            "mode": self.config.mode,
            "imgsz": self.config.imgsz,
            "warm_up_ms": round((time.perf_counter() - started) * 1000, 1),
        }

    # ------------------------------------------------------------------
    # detection
    # ------------------------------------------------------------------
    def _predict(self, frame: np.ndarray) -> list[tuple[tuple, float]]:
        kwargs = dict(conf=self.config.det_conf, iou=self.config.iou,
                      imgsz=getattr(self, "_imgsz", self.config.imgsz),
                      max_det=self.config.max_det,
                      verbose=False, device=self._device)
        results = self._model.predict(source=frame, **kwargs)
        boxes = []
        for result in results:
            for box in result.boxes:
                xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
                boxes.append((xyxy, float(box.conf)))
        return boxes

    def detect(self, frame_bgr: np.ndarray) -> list[tuple[tuple, float]]:
        """Plate boxes in the ORIGINAL frame's coordinates."""
        self.load()
        mode = self.config.mode
        height, width = frame_bgr.shape[:2]
        with self._infer_lock:
            if mode == "upscaled" and self.config.upscale > 1.0:
                scaled = _resize(frame_bgr, self.config.upscale)
                raw = self._predict(scaled)
                return [(_unscale(box, self.config.upscale), conf) for box, conf in raw]
            if mode == "tiled":
                return self._detect_tiled(frame_bgr)
            return self._predict(frame_bgr)

    def _detect_tiled(self, frame_bgr: np.ndarray) -> list[tuple[tuple, float]]:
        """Full-frame pass + overlapping tiles, merged (SAHI-style).

        Tiles find small, distant plates the full pass misses. But a plate that
        crosses a tile seam comes back as a FRAGMENT, and OCR on half a plate
        yields a confident wrong mark, so tile boxes touching an interior seam
        are dropped (the overlapping neighbour or the full pass covers them),
        and the full-frame pass always runs for plates wider than the overlap.
        """
        height, width = frame_bgr.shape[:2]
        tile = max(64, self.config.tile_size)
        stride = max(1, int(tile * (1.0 - self.config.tile_overlap)))
        edge = TILE_SEAM_PX
        found: list[tuple[tuple, float]] = list(self._predict(frame_bgr))
        for top in range(0, max(1, height - tile + stride), stride):
            for left in range(0, max(1, width - tile + stride), stride):
                bottom, right = min(height, top + tile), min(width, left + tile)
                crop = frame_bgr[top:bottom, left:right]
                if crop.size == 0:
                    continue
                for (x1, y1, x2, y2), conf in self._predict(crop):
                    cut = ((left > 0 and x1 <= edge) or (right < width and x2 >= (right - left) - edge)
                           or (top > 0 and y1 <= edge) or (bottom < height and y2 >= (bottom - top) - edge))
                    if cut:
                        continue
                    found.append(((x1 + left, y1 + top, x2 + left, y2 + top), conf))
        return _suppress_overlaps(found, self.config.iou)

    # ------------------------------------------------------------------
    # detection + recognition (the public entry point)
    # ------------------------------------------------------------------
    def detect_and_read(self, frame_bgr: np.ndarray,
                        two_line_aspect: float | None = None) -> list[PlateRead]:
        """Find plate boxes in a frame and read the text inside them.

        Blind: the returned text is never compared with any RFID plate here.
        ``two_line_aspect`` overrides the OCR's two-line split threshold for
        this call (0 = the feed's plates are single-line; never split).
        """
        from app.services.plate_validation import format_plate, parse_plate
        from app.services.routine_violation_video import plate_ocr

        started = time.perf_counter()
        found: list[PlateRead] = []
        if two_line_aspect is None:
            two_line_aspect = self.config.two_line_aspect
        try:
            # Detection errors are NOT swallowed: a bad device or an input-size
            # mismatch must fail loudly at warm-up, not return an empty list.
            for (x1, y1, x2, y2), det_conf in self.detect(frame_bgr):
                if x2 - x1 < self.config.min_plate_px or y2 - y1 < self.config.min_plate_px:
                    found.append(PlateRead((x1, y1, x2, y2), None, None, None,
                                           round(det_conf, 4), 0.0, False,
                                           skipped="below_min_plate_px"))
                    continue
                left, top = max(0, int(x1)), max(0, int(y1))
                right, bottom = min(frame_bgr.shape[1], int(x2)), min(frame_bgr.shape[0], int(y2))
                crop = frame_bgr[top:bottom, left:right]
                if crop.size == 0:
                    continue

                try:
                    reads = plate_ocr.read_plate(crop, good_enough=_good_enough(self.config),
                                                 two_line_aspect=two_line_aspect)
                except Exception as exc:             # one bad crop never kills the batch
                    self.last_error = f"OCR {type(exc).__name__}: {exc}"
                    reads = []
                variants = [{"text": read.text, "confidences": [round(c, 4) for c in read.confidences],
                             "variant": read.variant} for read in reads]

                # A partially legible plate still carries evidence (the vision
                # layer stores every plate it sees), so the raw OCR text is kept
                # even when it does NOT form a structurally valid mark.
                best = None
                for read in reads:
                    parsed = parse_plate(read.text, read.confidences)
                    key = (parsed is not None,
                           -(parsed.cost if parsed else 0.0),
                           read.mean_conf)
                    if best is None or key > best[0]:
                        best = (key, read, parsed)

                if best is None:
                    found.append(PlateRead((x1, y1, x2, y2), None, None, None,
                                           round(det_conf, 4), 0.0, False,
                                           ocr_variants=variants))
                    continue

                _, read, parsed = best
                text = "".join(parsed.chars) if parsed else None
                found.append(PlateRead(
                    box=(x1, y1, x2, y2),
                    plate_text=format_plate(text) if text else None,
                    plate_norm=text,
                    raw_ocr=read.text,
                    det_confidence=round(det_conf, 4),
                    ocr_confidence=round(read.mean_conf, 4),
                    valid=parsed is not None,
                    per_char=[[ch, round(conf, 4)] for ch, conf in
                              zip(parsed.chars, parsed.confidences or [])] if parsed else [],
                    ocr_variants=variants,
                ))
        finally:
            self.frames += 1
            self.detections += len(found)
            self.latencies_ms.append((time.perf_counter() - started) * 1000.0)
        return found

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        from statistics import median
        latencies = list(self.latencies_ms)
        return {
            "backend": self._backend,
            "device": getattr(self, "_device", None),
            "imgsz": getattr(self, "_imgsz", None),
            "config": self.config.as_dict(),
            "frames": self.frames,
            "detections": self.detections,
            "last_error": self.last_error,
            "latency_ms": {
                "samples": len(latencies),
                "mean": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "p50": round(median(latencies), 1) if latencies else None,
                "max": round(max(latencies), 1) if latencies else None,
            },
        }


def _static_export_imgsz(export_dir: Path) -> int | None:
    """Read the fixed input size from an Ultralytics OpenVINO export's metadata.

    Returns None when the export is dynamic (any size accepted).
    """
    metadata = export_dir / "metadata.yaml"
    if not metadata.is_file():
        return None
    text = metadata.read_text(encoding="utf-8", errors="ignore")
    if "dynamic: true" in text:
        return None
    size = None
    collecting = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("imgsz:"):
            collecting = True
            continue
        if collecting:
            if stripped.startswith("-"):
                try:
                    size = int(stripped.lstrip("- ").strip())
                except ValueError:
                    pass
            else:
                break
    return size


def _good_enough(config: AnprConfig):
    from app.services.plate_validation import parse_plate

    def check(read) -> bool:
        parsed = parse_plate(read.text, read.confidences)
        return parsed is not None and parsed.cost < 0.35 and read.mean_conf >= config.ocr_accept_conf

    return check


def _resize(image: np.ndarray, factor: float) -> np.ndarray:
    import cv2

    return cv2.resize(image, (max(1, int(image.shape[1] * factor)),
                             max(1, int(image.shape[0] * factor))),
                      interpolation=cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA)


def _unscale(box: tuple, factor: float) -> tuple:
    return tuple(value / factor for value in box)


def _iou(a: tuple, b: tuple) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _containment(inner: tuple, outer: tuple) -> float:
    """Fraction of ``inner``'s area that lies inside ``outer``."""
    inter = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0])) * \
        max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    return inter / area if area > 0 else 0.0


def _suppress_overlaps(found: list[tuple[tuple, float]], threshold: float,
                       contained: float = 0.6) -> list[tuple[tuple, float]]:
    """Class-agnostic NMS for the tiled mode (a plate can land in two tiles).

    Besides IoU, a box mostly inside another is the same plate seen partially:
    the LARGER (whole-plate) box is kept, whichever scored higher.
    """
    def area(b: tuple) -> float:
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    def fragment_of(small: tuple, large: tuple) -> bool:
        return area(small) < area(large) and _containment(small, large) > contained

    ordered = sorted(found, key=lambda item: -item[1])
    kept: list[tuple[tuple, float]] = []
    for box, conf in ordered:
        # a whole plate replaces EVERY fragment of itself already kept (checked
        # first: a big fragment also overlaps the whole plate by IoU)
        fragments = [(other, other_conf) for other, other_conf in kept
                     if fragment_of(other, box)]
        if fragments:
            conf = max([conf] + [other_conf for _, other_conf in fragments])
            kept = [item for item in kept if item not in fragments]
        elif any(_iou(box, other) > threshold or fragment_of(box, other) for other, _ in kept):
            continue
        kept.append((box, conf))
    return kept


# ----------------------------------------------------------------------
# process-wide singleton
# ----------------------------------------------------------------------

_adapter: AnprAdapter | None = None
_adapter_lock = threading.Lock()


def get_anpr_adapter() -> AnprAdapter:
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = AnprAdapter(AnprConfig.from_env())
        return _adapter


def detect_and_read(frame_bgr: np.ndarray) -> list[dict]:
    """Module-level convenience: the adapter's documented public interface."""
    return [read.as_dict() for read in get_anpr_adapter().detect_and_read(frame_bgr)]


def reset_anpr_adapter() -> None:
    """Test helper: drop the singleton so config changes take effect."""
    global _adapter
    with _adapter_lock:
        _adapter = None


def main() -> int:
    """Latency / throughput report for the configured model."""
    import json

    adapter = get_anpr_adapter()
    print(json.dumps(adapter.warm_up(), indent=2))
    frame = (np.random.default_rng(0).random((720, 1280, 3)) * 255).astype(np.uint8)
    for _ in range(5):
        adapter.detect_and_read(frame)
    print(json.dumps(adapter.status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
