"""
Model registry for the routine-violation pipeline: loaded and warmed up ONCE
(at server startup via warm_up()), reused by every job.

Backend choice (measured on the i7-1355U + Iris Xe test machine):
  * YOLO detectors run as OpenVINO IR (exported next to each .pt file). On
    the Intel iGPU they take the load off the CPU, which is busy decoding
    4K video and running OCR; OpenVINO CPU is the fallback, then PyTorch.
  * FP16 / `half` is only ever requested on a CUDA GPU. On CPU it is never
    passed (newer Ultralytics warns "'half' is deprecated" on every call).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[3]
MODEL_FILES = {
    # name: (pytorch weights, OpenVINO export dir)
    "vehicle": (BACKEND_DIR / "models" / "vehicle" / "yolo11n.pt",
                BACKEND_DIR / "models" / "vehicle" / "yolo11n_openvino_model"),
    "helmet": (BACKEND_DIR.parent / "HelmetAI" / "models" / "helmet_v4_final_best.pt",
               BACKEND_DIR / "models" / "helmet" / "helmet_v4_final_best_openvino_model"),
    "plate": (BACKEND_DIR / "models" / "number_plate" / "number_plate_detector.pt",
              BACKEND_DIR / "models" / "number_plate" / "number_plate_detector_openvino_model"),
}
# The OpenVINO exports have STATIC input shapes (a dynamic model makes the
# iGPU recompile kernels for every new shape): the vehicle detector takes a
# batch of exactly 4 letterboxed 16:9 frames at 256x416, helmet mosaics 576,
# plate crops 512.
STATIC_SHAPES = {"vehicle": ([256, 416], 4), "helmet": (576, 1), "plate": (512, 1)}
# Compiled iGPU kernels are cached on disk, so only the very first start pays
# the compile time (~2.5 min on the test machine); later starts take seconds.
OPENVINO_CACHE_DIR = BACKEND_DIR / "models" / "openvino_cache"
# Environment override: ROUTINE_DETECTOR_DEVICE=intel:cpu | intel:gpu | cpu
DEFAULT_DEVICE = os.environ.get("ROUTINE_DETECTOR_DEVICE", "auto")


def _enable_openvino_cache():
    """Ultralytics creates its own openvino.Core without a cache directory;
    make every Core it creates use the on-disk kernel cache."""
    import openvino as ov

    if getattr(ov.Core, "_routine_cached", False):
        return
    original = ov.Core
    OPENVINO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    class CachedCore(original):
        _routine_cached = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.set_property({"CACHE_DIR": str(OPENVINO_CACHE_DIR)})

    ov.Core = CachedCore


@dataclass
class LoadedModel:
    name: str
    model: object
    device: str          # value passed to predict(device=...)
    backend: str         # human readable: "OpenVINO iGPU", "PyTorch CPU", ...
    path: str
    half: bool = False   # FP16 only on CUDA

    def predict(self, source, **kwargs):
        kwargs.setdefault("verbose", False)
        kwargs["device"] = self.device
        if self.half:
            kwargs["half"] = True
        return self.model.predict(source=source, **kwargs)


_models: dict[str, LoadedModel] = {}
_lock = threading.Lock()


def _openvino_devices() -> list[str]:
    try:
        import openvino as ov
        return list(ov.Core().available_devices)
    except Exception:
        return []


def _choose(name: str, preference: str) -> LoadedModel:
    from ultralytics import YOLO

    pt_path, ov_path = MODEL_FILES[name]
    try:
        import torch
        cuda = torch.cuda.is_available()
    except Exception:
        cuda = False
    if cuda and preference in ("auto", "cuda"):
        return LoadedModel(name, YOLO(str(pt_path)), "cuda:0", "PyTorch CUDA FP16", str(pt_path), half=True)
    devices = _openvino_devices()
    if ov_path.is_dir() and devices:
        _enable_openvino_cache()
        if preference in ("auto", "intel:gpu") and "GPU" in devices:
            return LoadedModel(name, YOLO(str(ov_path), task="detect"), "intel:gpu",
                               "OpenVINO iGPU FP32", str(ov_path))
        if preference in ("auto", "intel:cpu", "intel:gpu"):
            return LoadedModel(name, YOLO(str(ov_path), task="detect"), "intel:cpu",
                               "OpenVINO CPU FP32", str(ov_path))
    return LoadedModel(name, YOLO(str(pt_path)), "cpu", "PyTorch CPU FP32", str(pt_path))


def get_model(name: str, preference: str | None = None) -> LoadedModel:
    with _lock:
        if name not in _models:
            _models[name] = _choose(name, preference or DEFAULT_DEVICE)
        return _models[name]


def warm_up() -> dict[str, str]:
    """Load every model once and run a dummy inference so the first job does
    not pay compile/load time. Safe to call repeatedly."""
    from app.services.routine_violation_video import plate_ocr

    report = {}
    for name, (imgsz, batch) in STATIC_SHAPES.items():
        loaded = get_model(name)
        dummy = np.zeros((720, 1280, 3), np.uint8)
        loaded.predict([dummy] * batch if batch > 1 else dummy, imgsz=imgsz)
        report[name] = f"{loaded.backend} ({Path(loaded.path).name})"
    recognizer = plate_ocr.get_recognizer()
    recognizer([np.full((48, 160, 3), 255, np.uint8)])
    report["ocr"] = recognizer.backend
    return report


def describe() -> dict[str, str]:
    return {name: f"{m.backend} ({Path(m.path).name})" for name, m in _models.items()}
