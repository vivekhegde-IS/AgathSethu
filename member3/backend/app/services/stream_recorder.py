"""Opt-in recorder for the CARLA -> backend stream (offline replay / NETRA calibration).

Off unless ``RFID_RECORD_PATH`` is set. Every message received on
``/ws/carla/cameras`` is appended to a JSONL file as
``{"rx": <wall-clock ISO>, "msg": <message>}`` by a background thread, so the
WebSocket loop never waits on the disk.

Environment:
  RFID_RECORD_PATH         file path (with an extension), or a directory -
                           created if missing (a file
                           carla_stream_<UTC time>.jsonl is created in it)
  RFID_RECORD_IMAGES       0 (default): camera_frame JPEGs are replaced by
                           "image_bytes": <len> - every other field (vehicle
                           boxes, timestamps) is kept. 1: keep the JPEG.
  RFID_RECORD_IMAGE_EVERY  with images on, keep the JPEG of every Nth frame
                           per camera (default 1 = all).
  RFID_RECORD_SKIP         message types not recorded (comma separated,
                           default "imu_reading,imu_detection").
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("stream_recorder")

DEFAULT_SKIP = "imu_reading,imu_detection"


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class StreamRecorder:
    def __init__(self, path: str | Path, keep_images: bool = False, image_every: int = 1,
                 skip_types: set[str] | None = None):
        path = Path(path)
        if not path.exists() and not path.suffix:
            path.mkdir(parents=True, exist_ok=True)     # "runtime/recordings" = a folder
        if path.is_dir():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = path / f"carla_stream_{stamp}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.keep_images = keep_images
        self.image_every = max(1, int(image_every))
        self.skip_types = (set(skip_types) if skip_types is not None
                           else set(DEFAULT_SKIP.split(",")))
        self.counts: dict[str, int] = {}
        self.dropped = 0
        self._frame_n: dict[str, int] = {}
        self._q: queue.Queue = queue.Queue(maxsize=200_000)
        self._fh = open(path, "a", encoding="utf-8")
        self._thread = threading.Thread(target=self._run, name="stream-recorder", daemon=True)
        self._thread.start()
        log.warning("[RECORD] recording the CARLA stream to %s (images=%s)", path,
                    "on" if keep_images else "off")
        print(f"[RECORD] recording the CARLA stream to {path}", flush=True)

    @classmethod
    def from_env(cls) -> "StreamRecorder | None":
        target = os.environ.get("RFID_RECORD_PATH", "").strip()
        if not target:
            return None
        if not Path(target).is_absolute():
            # relative paths (e.g. "runtime/recordings") live under DATA_DIR
            from app.core.config import data_dir

            target = str(data_dir() / target)
        try:
            every = int(os.environ.get("RFID_RECORD_IMAGE_EVERY", "1"))
        except ValueError:
            every = 1
        skip = os.environ.get("RFID_RECORD_SKIP", DEFAULT_SKIP)
        try:
            return cls(target, keep_images=_flag("RFID_RECORD_IMAGES", False), image_every=every,
                       skip_types={s.strip() for s in skip.split(",") if s.strip()})
        except OSError as exc:
            log.error("[RECORD] cannot record to %s: %s", target, exc)
            return None

    def record(self, message: dict) -> None:
        """Called on the RX path: a shallow copy and a queue put, nothing else."""
        if not isinstance(message, dict):
            return
        message_type = str(message.get("type"))
        if message_type in self.skip_types:
            return
        item = dict(message)
        if message_type == "camera_frame" and "image" in item:
            camera = str(item.get("camera_id"))
            n = self._frame_n.get(camera, 0)
            self._frame_n[camera] = n + 1
            if not self.keep_images or n % self.image_every:
                image = item.pop("image")
                item["image_bytes"] = len(image) if isinstance(image, (str, bytes)) else None
        try:
            self._q.put_nowait({"rx": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                                "msg": item})
            self.counts[message_type] = self.counts.get(message_type, 0) + 1
        except queue.Full:
            self.dropped += 1

    def _run(self) -> None:
        pending = 0
        while True:
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                if pending:
                    self._fh.flush()
                    pending = 0
                continue
            if item is None:
                break
            try:
                self._fh.write(json.dumps(item, separators=(",", ":"), default=str) + "\n")
                pending += 1
                if pending >= 200:
                    self._fh.flush()
                    pending = 0
            except Exception as exc:                 # pragma: no cover - disk full etc.
                log.error("[RECORD] write failed: %s", exc)
        self._fh.flush()

    def close(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=10.0)
        self._fh.close()

    def status(self) -> dict:
        return {"path": str(self.path), "counts": dict(self.counts), "dropped": self.dropped,
                "queued": self._q.qsize()}


_RECORDER: StreamRecorder | None = None
_RECORDER_INIT = False
_LOCK = threading.Lock()


def get_recorder() -> StreamRecorder | None:
    global _RECORDER, _RECORDER_INIT
    if not _RECORDER_INIT:
        with _LOCK:
            if not _RECORDER_INIT:
                _RECORDER = StreamRecorder.from_env()
                _RECORDER_INIT = True
    return _RECORDER
