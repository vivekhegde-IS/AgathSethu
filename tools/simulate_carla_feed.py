"""Replay the CARLA demo feed against a local backend + Postgres.

Sends the EXACT message schemas Member 1's script sends, in sim-time order:

  * rfid_reading - v2 tag reports (default) or the legacy per-read format
  * crash_alert  - the physics alert, then one IMU+GPS alert per involved car
  * camera_frame - ~5 fps per junction camera

RFID comes from the shared ``rfid_reader_model.py`` driven by the trajectories in
``tools/scenario.py`` (or a recorded ``gps_raw_readings.csv``).

Camera frames: the repo has a REAL recorded CARLA junction video, which is used
for J01. J02 and J03 have no recording, so frames there are SYNTHETIC (the plate
rendered onto a road-coloured canvas). Synthetic frames look nothing like the
real overlay pipeline, so ANPR results on them must NOT be read as real-world
accuracy - only the J01 results are meaningful.

Scenarios (for the Part 2 acceptance):
  normal        A and B collide at J01; A stops, B escapes via J02 then J03
  tag_swap      B's tag is read but the camera shows a different plate
  missed_pass   the J02 reader is made to miss B entirely
  unregistered  an extra tag whose EPC is not in the registry

Run (backend on 8001):
    python tools/simulate_carla_feed.py --url ws://127.0.0.1:8001/ws/carla/cameras
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

import scenario  # noqa: E402
from rfid_reader_model import CsvSink, RfidConfig, RfidReaderModel  # noqa: E402

OUT_DIR = ROOT / "runtime" / "simulated_feed"
JUNCTION_VIDEO = ROOT / "member3" / "media" / "videos" / \
    "camera_junction_1_v22_final_visible_anpr_recording.mp4"

CAMERA_FPS = 5.0
JPEG_QUALITY = 82

# The plate the simulated camera shows for each vehicle. The tag_swap scenario
# overrides one of them so the RFID EPC and the picture disagree.
SWAP_PLATE = {"B": "KL 07 DL 9182"}       # B's tag, someone else's plate


# ============================================================
# SYNTHETIC CAMERA FRAMES (J02/J03 have no recording)
# ============================================================

def synthetic_plate_rect(index: int) -> tuple[int, int, int, int]:
    """(left, top, width, height) of the index-th plate of a synthetic frame."""
    return 420, 300 + index * 150, 300, 78


def synthetic_vehicle_boxes(names: list[str], depths: list[float]) -> list[dict]:
    """The camera_frame ``vehicles`` metadata matching synthetic_frame(): a box
    around each drawn plate; cars beyond the second have no drawn plate and get
    a box on the right of the frame."""
    boxes = []
    for index, (name, depth) in enumerate(zip(names, depths)):
        if index < 2:
            left, top, plate_w, plate_h = synthetic_plate_rect(index)
            bbox = [left - 60, top - 100, left + plate_w + 60, top + plate_h + 12]
        else:
            bbox = [900, 200 + 60 * (index - 2), 1180, 300 + 60 * (index - 2)]
        boxes.append({"vehicle_id": name, "bbox": bbox, "depth_m": round(depth, 2)})
    return boxes


def synthetic_frame(plates: list[str], width: int = 1280, height: int = 720,
                    caption: str = "SYNTHETIC FRAME") -> np.ndarray:
    """A deliberately simple frame: a plate, big enough for the ANPR to read.

    NOT a representation of the CARLA overlay pipeline. Plates here are much
    cleaner than the real ones, so accuracy measured on them is optimistic.
    """
    frame = np.full((height, width, 3), 90, np.uint8)
    cv2.rectangle(frame, (0, int(height * 0.62)), (width, height), (60, 60, 65), -1)
    cv2.putText(frame, caption, (16, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2)

    for index, plate in enumerate(plates[:2]):
        left, top, plate_w, plate_h = synthetic_plate_rect(index)
        cv2.rectangle(frame, (left - 8, top - 8), (left + plate_w + 8, top + plate_h + 8),
                      (20, 20, 20), 3)
        cv2.rectangle(frame, (left, top), (left + plate_w, top + plate_h), (245, 245, 245), -1)
        text = plate.replace(" ", "")
        scale = 1.5 if len(text) <= 10 else 1.2
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 3)
        cv2.putText(frame, text, (left + max(4, (plate_w - tw) // 2), top + (plate_h + th) // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, scale, (10, 10, 10), 3, cv2.LINE_AA)
    return frame


def encode(frame: np.ndarray, quality: int = JPEG_QUALITY) -> str:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    return base64.b64encode(buffer.tobytes()).decode("ascii")


class CameraSource:
    """Real recorded frames for J01, synthetic frames elsewhere."""

    def __init__(self, video: Path | None = JUNCTION_VIDEO, loop: bool = True):
        self.loop = loop
        self.capture = cv2.VideoCapture(str(video)) if video and video.is_file() else None
        if self.capture is not None and not self.capture.isOpened():
            self.capture = None
        self.real_frames = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT)) if self.capture else 0
        self.index = 0

    @property
    def using_real_frames(self) -> bool:
        return self.capture is not None and self.real_frames > 0

    def next_real(self) -> np.ndarray | None:
        if self.capture is None:
            return None
        ok, frame = self.capture.read()
        if not ok:
            if not self.loop:
                return None
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
            if not ok:
                return None
        self.index += 1
        return frame

    def frame_for(self, junction_id: str, plates: list[str]) -> np.ndarray:
        if junction_id == "J01":
            frame = self.next_real()
            if frame is not None:
                return frame
        return synthetic_frame(plates, caption=f"SYNTHETIC {junction_id}")


# ============================================================
# MESSAGE BUILDING
# ============================================================

def rfid_messages(cfg: RfidConfig, times: list[float], fmt: str, seed: int,
                  scenario_name: str, writer: CsvSink | None = None,
                  run_id: str | None = None):
    """The RF stream, as (sim_ts, message) pairs sorted by sim time.

    ``run_id`` overrides the seed-derived one (CARLA mints a fresh id per start).
    """
    model = RfidReaderModel(cfg=cfg, seed=seed)
    if run_id:
        model.run_id = run_id
    legacy_rng_index = {"n": 0}
    import random

    rng = random.Random(seed)
    last_read: dict = {}
    out: list[tuple[float, dict]] = []

    # A missed pass: the J02 reader decodes nothing from B's tag, entry to exit.
    legacy_missed = {("J02", "B")} if scenario_name == "missed_pass" else set()
    if scenario_name == "missed_pass":
        model.miss_next_pass("J02", scenario.EPCS["B"])

    for index, timestamp in enumerate(times):
        vehicles = scenario.vehicles_at(timestamp)
        if scenario_name == "unregistered":
            vehicles = vehicles + [{
                "vehicle_id": "Z", "epc": "E200001722110199A0FF",
                "x": scenario.JUNCTION_WORLD["J02"][0] + 2.0,
                "y": scenario.JUNCTION_WORLD["J02"][1] - 2.0,
                "speed_kmh": 25.0,
            }]

        if fmt == "v2":
            reports, truth = model.step(timestamp, index, vehicles)
            for report in reports:
                out.append((report["timestamp_sim"], report))
                if writer is not None:
                    writer.write(report)
        else:
            # legacy: flat 98%, 0.25 s, 18 m, one message per read
            for junction_id, (jx, jy) in scenario.JUNCTION_WORLD.items():
                reader_id = f"RFID_J{int(junction_id[1:]):02d}_01"
                for vehicle in vehicles:
                    distance = ((vehicle["x"] - jx) ** 2 + (vehicle["y"] - jy) ** 2) ** 0.5
                    if distance > 18.0:
                        continue
                    if (junction_id, vehicle["vehicle_id"]) in legacy_missed:
                        continue
                    key = (vehicle["vehicle_id"], junction_id)
                    previous = last_read.get(key)
                    if previous is not None and timestamp - previous < 0.25:
                        continue
                    last_read[key] = timestamp
                    if rng.random() > 0.98:
                        continue
                    legacy_rng_index["n"] += 1
                    plate = scenario.PLATE_NUMBERS.get(vehicle["vehicle_id"],
                                                       vehicle["epc"])
                    out.append((timestamp, {
                        "type": "rfid_reading",
                        "timestamp_sim": round(timestamp, 6),
                        "frame": index,
                        "event_id": f"MM-{legacy_rng_index['n']:09d}",
                        "junction_id": junction_id,
                        "reader_id": reader_id,
                        "vehicle_id": vehicle["vehicle_id"],
                        "plate_number": plate,
                        "epc": vehicle["epc"],
                        "distance_m": round(distance, 6),
                        "speed_kmh": round(vehicle["speed_kmh"], 6),
                        "confidence": round(max(0.50, 1.0 - (distance / 18.0) * 0.25), 6),
                        "status": "READ",
                    }))
    out.sort(key=lambda item: item[0])
    return out


def alert_messages(cfg_unused=None) -> list[tuple[float, dict]]:
    """The physics alert, then IMU+GPS alerts for A and B."""
    crash_ts = scenario.CRASH_TIME_S
    frame = scenario.CRASH_FRAME
    jx, jy = scenario.JUNCTION_WORLD[scenario.CRASH_JUNCTION]

    def plate(name: str) -> str:
        return scenario.PLATE_NUMBERS[name]

    physics = {
        "type": "crash_alert",
        "alert_id": f"PHY-{frame}",
        "status": "COLLISION_EVENT_CONFIRMED_CARLA_PHYSICS",
        "timestamp_sim": crash_ts,
        "frame": frame,
        "vehicle_id": "A",
        "plate_number": plate("A"),
        "collision_partner": "B",
        "collision_partner_plate": plate("B"),
        "world_location": {"x": jx, "y": jy, "z": 0.0},
    }
    out = [(crash_ts, physics)]
    for offset, (vehicle, partner) in enumerate((("A", "B"), ("B", "A"))):
        out.append((crash_ts + 0.2 + offset * 0.2, {
            "type": "crash_alert",
            "alert_id": f"MM-{int(frame + offset):09d}",
            "status": "COLLISION_EVENT_CONFIRMED_IMU_GPS",
            "timestamp_sim": round(crash_ts + 0.2 + offset * 0.2, 6),
            "frame": frame + offset,
            "vehicle_id": vehicle,
            "plate_number": plate(vehicle),
            "epc": scenario.EPCS[vehicle],
            "collision_partner": partner,
            "collision_partner_plate": plate(partner),
            "world_location": {"x": jx, "y": jy, "z": 0.0},
            "gps": {"lat": 12.9352, "lon": 77.6245},
        }))
    out += escape_messages(crash_ts, frame)
    return out


def escape_messages(crash_ts: float, crash_frame: int) -> list[tuple[float, dict]]:
    """Member 1's escape detection (vivek_fb.py _post_crash_gps), replayed from
    the scenario trajectories: an involved vehicle moving >= 5 km/h and >= 8 m
    from where it was at the crash gets ONE vehicle_state escape_confirmed."""
    involved = ("A", "B")
    at_crash = {v["vehicle_id"]: v for v in scenario.vehicles_at(crash_ts) if v["vehicle_id"] in involved}
    out, done = [], set()
    step = 0.05
    t = crash_ts
    while t < crash_ts + 30.0 and len(done) < len(at_crash):
        t += step
        for vehicle in scenario.vehicles_at(t):
            name = vehicle["vehicle_id"]
            if name not in at_crash or name in done:
                continue
            start = at_crash[name]
            distance = ((vehicle["x"] - start["x"]) ** 2 + (vehicle["y"] - start["y"]) ** 2) ** 0.5
            if vehicle.get("speed_kmh", 0.0) >= 5.0 and distance >= 8.0:
                done.add(name)
                out.append((t, {
                    "type": "vehicle_state", "timestamp_sim": round(t, 6),
                    "frame": crash_frame + int(round((t - crash_ts) / 0.05)),
                    "vehicle_id": name, "plate_number": scenario.PLATE_NUMBERS[name],
                    "epc": scenario.EPCS[name], "state": "POST_CRASH_MOVING",
                    "speed_kmh": round(vehicle.get("speed_kmh", 0.0), 2),
                    "distance_from_crash_m": round(distance, 2), "escape_confirmed": True,
                }))
    return out


def camera_messages(times: list[float], source: CameraSource, scenario_name: str,
                    max_frames_per_junction: int | None = None, vehicle_boxes: bool = True):
    """~5 fps per junction, in sim time order.

    ``vehicle_boxes``: add the optional per-vehicle image boxes (what the
    patched CARLA script sends) to SYNTHETIC frames. The real recorded J01 clip
    has no such metadata, so its frames never carry it.
    """
    out: list[tuple[float, dict]] = []
    step = 1.0 / CAMERA_FPS
    plates_for = dict(SWAP_PLATE) if scenario_name == "tag_swap" else {}
    per_junction: dict = {}
    next_at = {junction: 0.0 for junction in scenario.JUNCTION_WORLD}
    for timestamp in times:
        for junction_id in scenario.JUNCTION_WORLD:
            if timestamp < next_at[junction_id]:
                continue
            next_at[junction_id] = timestamp + step
            if max_frames_per_junction is not None and \
                    per_junction.get(junction_id, 0) >= max_frames_per_junction:
                continue
            per_junction[junction_id] = per_junction.get(junction_id, 0) + 1

            # Which cars are near this camera right now?
            plates, names, depths = [], [], []
            for vehicle in scenario.vehicles_at(timestamp):
                jx, jy = scenario.JUNCTION_WORLD[junction_id]
                distance = ((vehicle["x"] - jx) ** 2 + (vehicle["y"] - jy) ** 2) ** 0.5
                if distance < 14.0:
                    name = vehicle["vehicle_id"]
                    plates.append(plates_for.get(name, scenario.PLATE_NUMBERS.get(name, "")))
                    names.append(name)
                    depths.append(25.0 + distance)
            # An empty junction shows no plate (never a filler plate: it would
            # end up in all_plates_seen).

            frame = source.frame_for(junction_id, plates)
            message = {
                "type": "camera_frame",
                "timestamp_sim": round(timestamp, 6),
                "frame": int(timestamp / 0.05),
                "camera_id": f"CAM_{junction_id}_01",
                "junction_id": junction_id,
                "encoding": "jpeg",
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
                "has_number_plate_overlay": True,
                "image": encode(frame),
            }
            real = junction_id == "J01" and source.using_real_frames
            if vehicle_boxes and not real:
                message["vehicles"] = synthetic_vehicle_boxes(names, depths)
            out.append((timestamp, message))
    return out


# ============================================================
# REPLAY
# ============================================================

def replay(url: str, messages: list[tuple[float, dict]], speed: float,
           verbose: bool = True) -> int:
    try:
        import websocket
    except ImportError as exc:
        raise SystemExit("pip install websocket-client to run the simulator") from exc

    connection = websocket.create_connection(url, timeout=15)
    sent = 0
    started = time.monotonic()
    try:
        for sim_ts, message in messages:
            if speed > 0:
                target = started + (sim_ts / speed)
                delay = target - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
            try:
                connection.send(json.dumps(message, separators=(",", ":")))
            except Exception:
                connection = websocket.create_connection(url, timeout=15)
                connection.send(json.dumps(message, separators=(",", ":")))
            sent += 1
            if message.get("type") == "crash_alert":
                try:
                    connection.settimeout(3)
                    reply = connection.recv()
                    if verbose:
                        print(f"[sim] ack: {reply[:120]}")
                except Exception as exc:
                    print(f"[sim] no ack for {message.get('alert_id')}: {exc}")
                finally:
                    connection.settimeout(15)
            if verbose and sent % 500 == 0:
                print(f"[sim] sent {sent}/{len(messages)} (sim t={sim_ts:.1f}s)")
    finally:
        connection.close()
    return sent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="ws://127.0.0.1:8001/ws/carla/cameras")
    parser.add_argument("--format", choices=("v2", "legacy"), default="v2")
    parser.add_argument("--scenario", choices=("normal", "tag_swap", "missed_pass",
                                               "unregistered"), default="normal")
    parser.add_argument("--speed", type=float, default=0.0,
                        help="sim seconds per real second (0 = as fast as possible)")
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=RfidConfig.seed)
    parser.add_argument("--gps-csv", type=Path, default=None,
                        help="drive RFID from a recorded gps_raw_readings.csv instead")
    parser.add_argument("--camera-frames", type=int, default=None,
                        help="cap frames sent per junction (keeps a run short)")
    parser.add_argument("--no-cameras", action="store_true")
    parser.add_argument("--no-vehicle-boxes", action="store_true",
                        help="omit the optional camera_frame vehicles field "
                             "(emulates the older CARLA script)")
    parser.add_argument("--run-id", default=None,
                        help="v2 run_id (default: a fresh uuid per invocation, like a CARLA "
                             "start; 'seed' = the seed-derived, reproducible id)")
    args = parser.parse_args(argv)
    run_id = None if args.run_id == "seed" else (args.run_id or str(uuid.uuid4()))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    times = scenario.timeline(args.duration)
    cfg = RfidConfig(seed=args.seed)

    rfid_csv = CsvSink(OUT_DIR / f"rfid_{args.format}_{args.scenario}.csv",
                       ["run_id", "seq", "reader_id", "junction_id", "antenna_id", "epc",
                        "rssi_dbm", "tag_seen_count", "first_seen_ts", "last_seen_ts",
                        "timestamp_sim", "frame"])
    if args.gps_csv:
        from rfid_reader_model import replay_gps_csv

        reports, _truth = replay_gps_csv(args.gps_csv, cfg=cfg, seed=args.seed)
        rfid = [(report["timestamp_sim"], report) for report in reports]
    else:
        rfid = rfid_messages(cfg, times, args.format, args.seed, args.scenario, rfid_csv,
                             run_id=run_id)
    rfid_csv.close()

    source = CameraSource()
    messages = list(rfid) + alert_messages()
    if not args.no_cameras:
        messages += camera_messages(times, source, args.scenario, args.camera_frames,
                                    vehicle_boxes=not args.no_vehicle_boxes)
    messages.sort(key=lambda item: item[0])
    # Feeder header: the backend files these incidents as synthetic / replay,
    # never as live CARLA runs.
    feed_source = "replay" if args.gps_csv else "synthetic"
    for _, message in messages:
        message["feed_source"] = feed_source

    cameras_real = source.using_real_frames
    print(f"[sim] scenario      : {args.scenario}")
    print(f"[sim] rfid format   : {args.format} ({len(rfid)} reports, run_id "
          f"{run_id or 'seed-derived'})")
    print(f"[sim] alerts        : 3 (1 physics + 2 IMU/GPS)")
    print(f"[sim] camera frames : {sum(1 for _, m in messages if m['type'] == 'camera_frame')}")
    print(f"[sim] J01 frames    : {'REAL recorded CARLA video' if cameras_real else 'SYNTHETIC'}")
    if cameras_real:
        print("[sim] J02/J03 frames: SYNTHETIC (no recording exists) - ANPR accuracy on "
              "these is optimistic and must not be quoted as real accuracy")
    print(f"[sim] feed_source   : {feed_source}")
    print(f"[sim] target        : {args.url}")

    sent = replay(args.url, messages, args.speed)
    print(f"[sim] done: {sent} messages sent")
    print(f"[sim] note: an incident is created at t={scenario.CRASH_TIME_S:.0f}s "
          f"({scenario.CRASH_JUNCTION}); B should be confirmed at J02 then J03, "
          f"A should get no next-junction sighting once the run completes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
