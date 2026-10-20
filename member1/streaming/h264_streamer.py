"""
H.264 camera streaming for the CARLA junction cameras (WebRTC via MediaMTX).

    full_run.py main loop
        |  submit(junction, frame, sim_time, frame_id)   <- O(1): swaps a slot
        v
    one CameraStream per camera (own thread + own FFmpeg process)
        |  constant-rate pacer at STREAM_FPS (30) > sim rate (20 Hz): every sim
        |  frame gets a tick; the last frame is repeated in between and while
        |  the sim is paused/restarting, so the WebRTC stream never stalls
        v
    FFmpeg: bgr24 -> I420 -> H.264 (NVENC if present, else x264 zerolatency)
        |  constrained baseline, no B-frames, 1 s GOP, CBR / VBV-limited
        v
    RTSP (TCP) push  ->  MediaMTX  (rtsp://<host>:8554/cam1..cam3)
        v
    WebRTC (WHEP) to browsers, signalled through the website backend

Design rules
- The simulation thread never blocks and never waits: submit() replaces a
  1-slot buffer (newest frame wins; an old frame is dropped, never queued).
- No frame copy on the hot path: the frame array is handed over by reference
  and written to FFmpeg's stdin through a memoryview. full_run.py never
  mutates a frame after it has been published.
- Pacing: one frame per 1/STREAM_FPS tick, newest frame wins. STREAM_FPS must
  be ABOVE the sim's camera rate (default 30 for CARLA's 20 Hz): at an equal
  rate the two clocks alias and drop one frame / repeat the next. Repeated
  frames cost almost no bits in H.264 and add at most one tick (33 ms).
- Timestamps: constant frame rate (frame n = n/STREAM_FPS), kept on the wall
  clock by the pacer (a hiccup is caught up, a >1 s stall restarts the
  schedule). Measured: FFmpeg's own wall-clock stamping
  (use_wallclock_as_timestamps) reads the pipe in bursts and produces
  duplicate timestamps, so it is not used. Sim time is NOT used as media time
  either: it stops on pause and jumps back on a CARLA restart, which would
  freeze or break every viewer's jitter buffer. Sim time and frame id are
  carried in the picture when STREAM_DEBUG_OVERLAY=1 (used to measure
  glass-to-glass latency).
- A dead or failing FFmpeg / unreachable MediaMTX is restarted with backoff;
  it never affects the simulation, the MP4 recording or the JPEG WebSocket
  feed used by the backend's ANPR / RFID pipeline.

Configuration (environment variables, all optional)
    STREAM_ENABLED          1                 0 disables the module entirely
    STREAM_RTSP_BASE        rtsp://127.0.0.1:8554   MediaMTX RTSP address
    STREAM_PUBLISH_USER     (empty)           MediaMTX publisher credentials
    STREAM_PUBLISH_PASS     (empty)
    STREAM_CAMERAS          1:cam1,2:cam2,3:cam3    junction:path pairs
    STREAM_FPS              30                output rate; keep above the 20 Hz sim
    STREAM_WIDTH            0                 0 = native (1280); else scaled
    STREAM_HEIGHT           0
    STREAM_BITRATE_KBPS     3000              per camera
    STREAM_ENCODER          auto              auto | nvenc | x264
    STREAM_X264_PRESET      veryfast          ultrafast | superfast | veryfast
    STREAM_FFMPEG           ffmpeg            path to the ffmpeg binary
    STREAM_DEBUG_OVERLAY    0                 1 = burn sim time / frame / wall ms
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote

import numpy as np

try:  # cv2 is only needed for scaling / the debug overlay / the idle card
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


@dataclass
class StreamConfig:
    enabled: bool = True
    rtsp_base: str = "rtsp://127.0.0.1:8554"
    publish_user: str = ""
    publish_pass: str = ""
    cameras: dict = field(default_factory=lambda: {1: "cam1", 2: "cam2", 3: "cam3"})
    fps: int = 30
    width: int = 0
    height: int = 0
    bitrate_kbps: int = 3000
    encoder: str = "auto"
    x264_preset: str = "veryfast"
    ffmpeg: str = "ffmpeg"
    debug_overlay: bool = False

    @classmethod
    def from_env(cls) -> "StreamConfig":
        cameras = {}
        for pair in _env("STREAM_CAMERAS", "1:cam1,2:cam2,3:cam3").split(","):
            if ":" in pair:
                junction, path = pair.split(":", 1)
                cameras[int(junction)] = path.strip()
        return cls(
            enabled=_env("STREAM_ENABLED", "1").lower() in {"1", "true", "yes", "on"},
            rtsp_base=_env("STREAM_RTSP_BASE", "rtsp://127.0.0.1:8554").rstrip("/"),
            publish_user=_env("STREAM_PUBLISH_USER", ""),
            publish_pass=_env("STREAM_PUBLISH_PASS", ""),
            cameras=cameras or {1: "cam1", 2: "cam2", 3: "cam3"},
            fps=max(1, _env_int("STREAM_FPS", 30)),
            width=max(0, _env_int("STREAM_WIDTH", 0)),
            height=max(0, _env_int("STREAM_HEIGHT", 0)),
            bitrate_kbps=max(200, _env_int("STREAM_BITRATE_KBPS", 3000)),
            encoder=_env("STREAM_ENCODER", "auto").lower(),
            x264_preset=_env("STREAM_X264_PRESET", "veryfast"),
            ffmpeg=_env("STREAM_FFMPEG", "ffmpeg"),
            debug_overlay=_env("STREAM_DEBUG_OVERLAY", "0").lower() in {"1", "true", "yes", "on"},
        )

    def url(self, path: str) -> str:
        """rtsp://user:pass@host:port/path (credentials URL-encoded)."""
        if not self.publish_user:
            return f"{self.rtsp_base}/{path}"
        scheme, rest = self.rtsp_base.split("://", 1)
        auth = f"{quote(self.publish_user, safe='')}:{quote(self.publish_pass, safe='')}@"
        return f"{scheme}://{auth}{rest}/{path}"


# ---------------------------------------------------------------------------
# Encoder selection
# ---------------------------------------------------------------------------

def _nvenc_works(ffmpeg: str) -> bool:
    """h264_nvenc is often compiled in without a usable NVIDIA GPU: encode one
    real frame to be sure."""
    try:
        listed = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True,
                                text=True, timeout=15).stdout
        if "h264_nvenc" not in listed:
            return False
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=black:s=256x144:r=20", "-frames:v", "3", "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30)
        return probe.returncode == 0
    except Exception:
        return False


def choose_encoder(config: StreamConfig) -> str:
    if config.encoder in {"nvenc", "x264"}:
        return config.encoder
    return "nvenc" if _nvenc_works(config.ffmpeg) else "x264"


def ffmpeg_command(config: StreamConfig, encoder: str, in_w: int, in_h: int, path: str) -> list[str]:
    """Raw BGR frames on stdin -> low-latency H.264 -> RTSP push."""
    fps = config.fps
    kbps = config.bitrate_kbps
    out_w = config.width or in_w
    out_h = config.height or in_h
    command = [
        config.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostats",
        # input: raw frames at a constant rate (see module docstring)
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{in_w}x{in_h}",
        "-framerate", str(fps), "-fflags", "nobuffer", "-flags", "low_delay",
        "-probesize", "32", "-analyzeduration", "0", "-i", "pipe:0",
        "-an",
    ]
    # BGR -> I420 (x264) / NV12 (NVENC), scaling in the same swscale pass
    scale = f"scale={out_w}:{out_h}:flags=fast_bilinear," if (out_w, out_h) != (in_w, in_h) else ""
    if encoder == "nvenc":
        command += ["-vf", f"{scale}format=nv12",
                    "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ull",
                    "-profile:v", "baseline", "-rc", "cbr", "-zerolatency", "1", "-delay", "0",
                    "-forced-idr", "1"]
    else:
        command += ["-vf", f"{scale}format=yuv420p",
                    "-c:v", "libx264", "-preset", config.x264_preset, "-tune", "zerolatency",
                    "-profile:v", "baseline",                     # = constrained baseline in x264
                    "-x264-params", "nal-hrd=cbr:repeat-headers=1"]
    command += [
        "-g", str(fps), "-keyint_min", str(fps), "-sc_threshold", "0", "-bf", "0",   # 1 s GOP, no B
        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{max(kbps // 2, 100)}k",
        "-bsf:v", "dump_extra=freq=keyframe",           # SPS/PPS before every IDR
        "-f", "rtsp", "-rtsp_transport", "tcp", config.url(path),
    ]
    return command


# ---------------------------------------------------------------------------
# One camera
# ---------------------------------------------------------------------------

class CameraStream:
    """Paced encoder thread for one camera: newest frame wins, never queues."""

    RESTART_MIN_S = 1.0
    RESTART_MAX_S = 15.0

    def __init__(self, junction: int, path: str, config: StreamConfig, encoder: str):
        self.junction = junction
        self.path = path
        self.config = config
        self.encoder = encoder
        self._slot_lock = threading.Lock()
        self._latest: Optional[tuple] = None          # (frame, sim_time, frame_id)
        self._stop = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        self._size: Optional[tuple] = None
        self._last_sent: Optional[np.ndarray] = None
        self._last_sim: Optional[tuple] = None
        self.frames_in = 0
        self.frames_dropped = 0
        self.frames_sent = 0
        self.frames_repeated = 0
        self.restarts = 0                              # re-spawns after a failure
        self._spawns = 0
        self.last_error: Optional[str] = None
        self.connected_since: Optional[float] = None
        self._thread = threading.Thread(target=self._run, name=f"h264-{path}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    # called from the simulation thread: must be O(1)
    def submit(self, frame: np.ndarray, sim_time: float, frame_id: int) -> None:
        with self._slot_lock:
            if self._latest is not None:
                self.frames_dropped += 1
            self._latest = (frame, sim_time, frame_id)
            self.frames_in += 1

    def _take(self) -> Optional[tuple]:
        with self._slot_lock:
            item, self._latest = self._latest, None
            return item

    # -- FFmpeg process ---------------------------------------------------
    def _spawn(self, width: int, height: int) -> None:
        command = ffmpeg_command(self.config, self.encoder, width, height, self.path)
        self._proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._size = (width, height)
        self.connected_since = time.monotonic()
        threading.Thread(target=self._drain_stderr, args=(self._proc,), daemon=True,
                         name=f"h264-{self.path}-log").start()
        print(f"[STREAM {self.path}] encoding {width}x{height}@{self.config.fps} "
              f"{self.encoder} {self.config.bitrate_kbps} kbps -> {self.config.rtsp_base}/{self.path}",
              flush=True)

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stderr.readline, b""):
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.last_error = line
                print(f"[STREAM {self.path}] ffmpeg: {line}", flush=True)

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        self.connected_since = None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()

    # -- frames -------------------------------------------------------------
    def _idle_card(self, width: int, height: int) -> np.ndarray:
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        if cv2 is not None:
            cv2.putText(frame, f"J{self.junction:02d}  waiting for simulation", (40, height // 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (180, 180, 180), 2, cv2.LINE_AA)
        return frame

    def _with_overlay(self, frame: np.ndarray, sim: Optional[tuple]) -> np.ndarray:
        if not self.config.debug_overlay or cv2 is None:
            return frame
        out = frame.copy()
        sim_text = f"sim {sim[0]:.2f}s  frame {sim[1]}" if sim else "sim -"
        wall_ms = int(time.time() * 1000) % 100000
        cv2.rectangle(out, (0, 0), (560, 44), (0, 0, 0), -1)
        cv2.putText(out, f"{self.path}  {sim_text}  wall {wall_ms:05d}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
        return out

    def _run(self) -> None:
        period = 1.0 / self.config.fps
        backoff = self.RESTART_MIN_S
        next_restart = 0.0
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                self._stop.wait(next_tick - now)
                continue
            # one frame per tick keeps CFR timestamps on the wall clock; a short
            # hiccup is caught up, a long stall (>1 s) restarts the schedule
            next_tick += period
            if now - next_tick > 1.0:
                next_tick = now + period

            item = self._take()
            if item is not None:
                frame, sim_time, frame_id = item
                self._last_sim = (sim_time, frame_id)
            elif self._last_sent is not None:
                frame = self._last_sent                     # between sim frames / paused: repeat
                self.frames_repeated += 1
            else:
                size = self._size or (1280, 720)
                frame = self._idle_card(*size)               # nothing yet: idle card

            frame = np.ascontiguousarray(frame)
            if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
                self.last_error = f"unsupported frame {frame.shape} {frame.dtype}"
                continue
            height, width = frame.shape[:2]

            if self._proc is not None and (self._proc.poll() is not None or self._size != (width, height)):
                if self._proc.poll() is not None:
                    self.last_error = f"ffmpeg exited with {self._proc.returncode}"
                self._kill()
                next_restart = time.monotonic() + backoff
                backoff = min(backoff * 2, self.RESTART_MAX_S)
            if self._proc is None:
                if time.monotonic() < next_restart:
                    self._last_sent = frame
                    continue
                try:
                    self._spawn(width, height)
                    self.restarts += self._spawns > 0
                    self._spawns += 1
                except Exception as exc:                     # ffmpeg missing, bad path...
                    self.last_error = f"{type(exc).__name__}: {exc}"
                    next_restart = time.monotonic() + backoff
                    backoff = min(backoff * 2, self.RESTART_MAX_S)
                    self._last_sent = frame
                    continue

            try:
                self._proc.stdin.write(memoryview(self._with_overlay(frame, self._last_sim)))
                self.frames_sent += 1
                self._last_sent = frame
                if self.connected_since and time.monotonic() - self.connected_since > 10:
                    backoff = self.RESTART_MIN_S             # healthy for 10 s: reset backoff
            except (BrokenPipeError, OSError, ValueError) as exc:
                self.last_error = f"write failed: {exc}"
                self._kill()
                next_restart = time.monotonic() + backoff
                backoff = min(backoff * 2, self.RESTART_MAX_S)
        self._kill()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def status(self) -> dict:
        return {"path": self.path, "junction": self.junction, "encoder": self.encoder,
                "running": self._proc is not None and self._proc.poll() is None,
                "frames_in": self.frames_in, "frames_sent": self.frames_sent,
                "frames_dropped": self.frames_dropped, "frames_repeated": self.frames_repeated,
                "restarts": self.restarts, "last_error": self.last_error}


# ---------------------------------------------------------------------------
# All cameras
# ---------------------------------------------------------------------------

class MultiCameraStreamer:
    """The single object full_run.py talks to."""

    def __init__(self, config: Optional[StreamConfig] = None):
        self.config = config or StreamConfig.from_env()
        self.streams: dict[int, CameraStream] = {}
        self.encoder: Optional[str] = None
        if not self.config.enabled:
            print("[STREAM] disabled (STREAM_ENABLED=0)", flush=True)
            return
        if shutil.which(self.config.ffmpeg) is None and not os.path.isfile(self.config.ffmpeg):
            print(f"[STREAM] disabled: ffmpeg not found ({self.config.ffmpeg}); "
                  f"set STREAM_FFMPEG or install FFmpeg", flush=True)
            return
        self.encoder = choose_encoder(self.config)
        print(f"[STREAM] H.264 encoder: {self.encoder} | {len(self.config.cameras)} camera(s) "
              f"@ {self.config.fps} fps, {self.config.bitrate_kbps} kbps each -> {self.config.rtsp_base}",
              flush=True)
        for junction, path in sorted(self.config.cameras.items()):
            stream = CameraStream(junction, path, self.config, self.encoder)
            stream.start()
            self.streams[junction] = stream

    @property
    def active(self) -> bool:
        return bool(self.streams)

    def submit(self, junction: int, frame: np.ndarray, sim_time: float, frame_id: int) -> None:
        """Non-blocking hand-off from the simulation thread."""
        stream = self.streams.get(int(junction))
        if stream is not None:
            stream.submit(frame, float(sim_time), int(frame_id))

    def status(self) -> dict:
        return {path: s.status() for path, s in ((s.path, s) for s in self.streams.values())}

    def close(self) -> None:
        for stream in self.streams.values():
            stream.stop()
        if self.streams:
            print(f"[STREAM] stopped: {self.status()}", flush=True)
        self.streams.clear()
