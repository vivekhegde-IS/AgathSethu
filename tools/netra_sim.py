"""Synthetic junction data for NETRA calibration and tests.

RFID comes from the project's own reader model (``rfid_reader_model.py``,
v2 TAG_REPORTs, unchanged), camera boxes from Member 1's camera placement
projected with ``netra.geometry`` (box + depth, exactly the camera_frame
``vehicles`` fields). NETRA's own read-rate model is NOT used to generate data.

Two sources:

* ``random_traffic(seed)``: Poisson traffic through J01-J03 from four
  approaches, two lanes each way, with untagged vehicles, vehicles the camera
  never tracks, and parked roadside tags. Used for calibration / held-out tests.
* ``acceptance_scenario()``: the A-H crash scenario of ``tools/scenario.py``.

Everything is illustrative, not calibrated against real hardware.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "member3" / "backend", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rfid_reader_model import RfidConfig, RfidReaderModel  # noqa: E402

from app.services.rfid.netra.geometry import camera_for  # noqa: E402
from app.services.rfid.normalize import parse_message  # noqa: E402
from app.services.rfid.vision import FrameRef  # noqa: E402

JUNCTIONS = ("J01", "J02", "J03")
DT = 0.05                      # world tick (20 Hz, one inventory round)
JUNCTION_SPACING = 1000.0      # junctions are simulated far apart on one x axis


@dataclass
class JunctionData:
    junction_id: str
    reports: list = field(default_factory=list)     # RfidRead
    frames: list = field(default_factory=list)      # FrameRef (jpeg empty)
    truth: dict = field(default_factory=dict)       # epc -> track id or None


@dataclass
class _Vehicle:
    vid: str
    junction_id: str
    epc: str | None
    tracked: bool
    t_start: float
    p0: tuple            # local (forward, lateral) at t_start
    heading: float       # local, radians
    speed: float         # m/s (0 = parked)
    length_m: float = 120.0

    def local(self, t: float):
        if t < self.t_start:
            return None
        d = self.speed * (t - self.t_start)
        if self.speed > 0 and d > self.length_m:
            return None
        return (self.p0[0] + d * math.cos(self.heading), self.p0[1] + d * math.sin(self.heading))


def _run(vehicles, duration, seed, camera_hz, box_noise_px, depth_noise_m, frame_drop,
         reader_cfg=None):
    """Drive the RFID model and the cameras; returns {junction: JunctionData}."""
    rng = np.random.default_rng(seed + 7)
    origins = {jid: (k * JUNCTION_SPACING, 0.0) for k, jid in enumerate(JUNCTIONS)}
    readers = {jid: (origins[jid][0] + camera_for(jid).back_m, camera_for(jid).lateral_m)
               for jid in JUNCTIONS}
    model = RfidReaderModel(cfg=reader_cfg or RfidConfig(), seed=seed,
                            junction_locations=readers, run_id=f"netra-sim-{seed}")
    data = {jid: JunctionData(jid) for jid in JUNCTIONS}
    for v in vehicles:
        if v.epc:
            data[v.junction_id].truth[v.epc] = v.vid if v.tracked else None

    cam_every = max(1, int(round(1.0 / (camera_hz * DT))))
    steps = int(round(duration / DT))
    for i in range(steps + 1):
        t = i * DT
        world = []
        for v in vehicles:
            pos = v.local(t)
            if pos is None or not v.epc:
                continue
            ox, oy = origins[v.junction_id]
            world.append({"vehicle_id": v.vid, "epc": v.epc, "x": ox + pos[0], "y": oy + pos[1],
                          "speed_kmh": v.speed * 3.6})
        reports, _ = model.step(t, i, world)
        for message in reports:
            read = parse_message(message)
            if read is not None:
                data[read.junction_id].reports.append(read)
        if i % cam_every:
            continue
        for jid in JUNCTIONS:
            if rng.random() < frame_drop:
                continue
            geometry = camera_for(jid)
            boxes = []
            for v in vehicles:
                if v.junction_id != jid or not v.tracked:
                    continue
                pos = v.local(t)
                if pos is None:
                    continue
                proj = geometry.project_vehicle(pos[0], pos[1], v.heading)
                if proj is None:
                    continue
                bbox, depth = proj
                noise = rng.normal(0, box_noise_px, 4)
                bbox = [int(round(b + n)) for b, n in zip(bbox, noise)]
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                boxes.append({"vehicle_id": v.vid, "bbox": bbox,
                              "depth_m": round(depth + rng.normal(0, depth_noise_m), 2)})
            data[jid].frames.append(FrameRef(f"CAM_{jid}_01", jid, round(t, 6), b"", i, boxes))
    return data


def random_traffic(seed: int, duration: float = 300.0, arrival_rate: float = 0.25,
                   speed_range=(6.0, 14.0), tag_rate: float = 0.9, detect_rate: float = 0.9,
                   parked_tags: int = 1, camera_hz: float = 5.0, box_noise_px: float = 3.0,
                   depth_noise_m: float = 0.5, frame_drop: float = 0.05,
                   reader_cfg: RfidConfig | None = None) -> dict:
    """Poisson traffic at every junction. Each vehicle drives straight through
    the junction centre's area from one of four approaches, in one of two lanes
    (lane centres 1.75 m and 5.25 m right of the road axis)."""
    rng = np.random.default_rng(seed)
    vehicles = []
    n = 0
    for jid in JUNCTIONS:
        geometry = camera_for(jid)
        cx, cy = geometry.reader_xy
        t = rng.uniform(0, 3)
        while t < duration - 15:
            approach = rng.integers(4) * (math.pi / 2) + rng.normal(0, 0.05)
            lane = rng.choice([1.75, 5.25]) + rng.normal(0, 0.3)
            # start 60 m before the centre, offset to the right of travel
            back = 60.0
            sx = cx - back * math.cos(approach) - lane * math.sin(approach)
            sy = cy - back * math.sin(approach) + lane * math.cos(approach)
            tagged = rng.random() < tag_rate
            tracked = rng.random() < detect_rate
            vid = f"S{seed}_{jid}_V{n:04d}"
            vehicles.append(_Vehicle(vid, jid, f"EPC{seed:03d}{n:05d}" if tagged else None, tracked,
                                     t, (sx, sy), approach, float(rng.uniform(*speed_range))))
            n += 1
            t += rng.exponential(1.0 / arrival_rate)
        for g in range(parked_tags):
            ang, r = rng.uniform(0, 2 * math.pi), rng.uniform(6.0, 11.0)
            vehicles.append(_Vehicle(f"S{seed}_{jid}_P{g}", jid, f"PARK{seed:03d}{jid}{g}", False, 0.0,
                                     (cx + r * math.cos(ang), cy + r * math.sin(ang)), 0.0, 0.0))
    return _run(vehicles, duration, seed, camera_hz, box_noise_px, depth_noise_m, frame_drop,
                reader_cfg)


def acceptance_scenario(seed: int = 20240930, camera_hz: float = 5.0, box_noise_px: float = 3.0,
                        depth_noise_m: float = 0.5) -> dict:
    """The A-H crash scenario (tools/scenario.py) seen through the junction
    cameras. Each camera looks along the direction the fleeing B enters that
    junction (an assumption: the scenario has no road map)."""
    import scenario as sc

    times = sc.timeline()
    world = {name: [v.position(t) for t in times] for name, v in
             ((v.vehicle_id, v) for v in sc.VEHICLES)}

    def yaw_for(jid):
        b = next(v for v in sc.VEHICLES if v.vehicle_id == "B")
        jx, jy = sc.JUNCTION_WORLD[jid]
        pts = [(x, y) for (_, x, y) in b.keypoints]
        k = min(range(len(pts)), key=lambda i: math.hypot(pts[i][0] - jx, pts[i][1] - jy))
        px, py = pts[max(0, k - 1)]
        return math.atan2(jy - py, jx - px)

    rng = np.random.default_rng(seed)
    model = RfidReaderModel(seed=seed, junction_locations=sc.JUNCTION_WORLD,
                            run_id=f"netra-scenario-{seed}")
    data = {jid: JunctionData(jid) for jid in JUNCTIONS}
    for jid in JUNCTIONS:
        data[jid].truth = {sc.EPCS[name]: name for name in sc.VEHICLE_IDS}

    cams = {}
    for jid in JUNCTIONS:
        g = camera_for(jid)
        yaw = yaw_for(jid)
        f = (math.cos(yaw), math.sin(yaw))
        r = (-math.sin(yaw), math.cos(yaw))
        jx, jy = sc.JUNCTION_WORLD[jid]
        cam = (jx - f[0] * g.back_m - r[0] * g.lateral_m, jy - f[1] * g.back_m - r[1] * g.lateral_m)
        cams[jid] = (g, cam, f, r, yaw)

    cam_every = max(1, int(round(1.0 / (camera_hz * DT))))
    speeds = sc.speeds_by_vehicle(times)
    for i, t in enumerate(times):
        reports, _ = model.step(t, i, sc.vehicles_at(t))
        for message in reports:
            read = parse_message(message)
            if read is not None:
                data[read.junction_id].reports.append(read)
        if i % cam_every:
            continue
        for jid, (g, cam, f, r, yaw) in cams.items():
            boxes = []
            for name in sc.VEHICLE_IDS:
                x, y = world[name][i]
                px, py = world[name][max(0, i - 1)]
                if speeds[name][i] > 0 and (x, y) != (px, py):
                    heading_w = math.atan2(y - py, x - px)
                else:
                    heading_w = yaw
                dx, dy = x - cam[0], y - cam[1]
                fwd, lat = dx * f[0] + dy * f[1], dx * r[0] + dy * r[1]
                proj = g.project_vehicle(fwd, lat, heading_w - yaw)
                if proj is None:
                    continue
                bbox, depth = proj
                noise = rng.normal(0, box_noise_px, 4)
                boxes.append({"vehicle_id": name,
                              "bbox": [int(round(b + n)) for b, n in zip(bbox, noise)],
                              "depth_m": round(depth + rng.normal(0, depth_noise_m), 2)})
            data[jid].frames.append(FrameRef(f"CAM_{jid}_01", jid, round(t, 6), b"", i, boxes))
    return data


def offset_run(data: dict, dt: float) -> dict:
    """Shift a run's event times by dt (to pool several runs in one stream)."""
    import copy as _copy
    out = {}
    for jid, jd in data.items():
        nd = JunctionData(jid, truth=dict(jd.truth))
        for r in jd.reports:
            r2 = _copy.copy(r)
            r2.first_seen_ts += dt
            r2.last_seen_ts += dt
            nd.reports.append(r2)
        nd.frames = [FrameRef(f.camera_id, f.junction_id, f.timestamp_sim + dt, f.jpeg,
                              f.frame_no, f.vehicles) for f in jd.frames]
        out[jid] = nd
    return out
