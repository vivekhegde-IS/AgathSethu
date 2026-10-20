"""Backend data -> NETRA inputs.

* RFID: a v2 TAG_REPORT aggregates every inventory round of one tag in one
  reporting interval into ``[first_seen_ts, last_seen_ts]`` + a count. NETRA
  works on read slots, so a report becomes one read in every slot its window
  covers (``_hits`` de-duplicates per (reader, slot)). Slots inside an interval
  where the tag was NOT decoded are not recoverable from v2 and count as hits;
  the slot length is chosen equal to the reporting interval to keep that small.
  Legacy per-read messages are a degenerate window and work unchanged.
* Camera: ``camera_frame.vehicles`` boxes (+ depth) are lifted to the
  camera-local ground plane (``geometry.py``) and grouped into one track per
  box id. In CARLA the id is the actor name; with a real camera it is the
  tracker id. NETRA never sees the registry, the EPC or the plate.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from app.services.rfid.netra.core import Read, Reader, Track
from app.services.rfid.netra.geometry import CameraGeometry

DEFAULT_SLOT_S = 0.5


def reads_from_reports(reports, slot: float = DEFAULT_SLOT_S) -> list[Read]:
    """RfidRead (v2 or legacy) -> NETRA reads, one per covered slot."""
    out = []
    for report in reports:
        t0, t1 = float(report.first_seen_ts), float(report.last_seen_ts)
        if t1 < t0:
            t0, t1 = t1, t0
        n = int(np.floor((t1 - t0) / slot))
        for k in range(n + 1):
            out.append(Read(report.epc, report.reader_id, t0 + k * slot))
        if t0 + n * slot < t1:
            out.append(Read(report.epc, report.reader_id, t1))
    out.sort(key=lambda read: read.t)
    return out


def tracks_from_frames(frames, geometry: CameraGeometry, smooth_half: int = 2,
                       min_points: int = 2, max_gap_s: float = 2.0) -> list[Track]:
    """FrameRef list (one junction) -> ground-plane Tracks, one per vehicle id and
    continuous visit: a vehicle unseen for more than ``max_gap_s`` starts a new
    track (first visit = vehicle id, later ones vehicle#k), as a real tracker
    would. Without the split, a car that leaves the view and returns is
    interpolated straight across the gap, placing a phantom car at the reader.

    Frames without ``vehicles`` metadata contribute nothing. Duplicate
    timestamps (two cameras) keep the first box.
    """
    points: dict[str, dict[float, tuple[float, float]]] = defaultdict(dict)
    for frame in sorted(frames, key=lambda item: item.timestamp_sim):
        for vehicle in frame.vehicles or []:
            ground = geometry.ground_from_box(vehicle["bbox"], vehicle.get("depth_m"))
            if ground is None:
                continue
            points[str(vehicle["vehicle_id"])].setdefault(float(frame.timestamp_sim), ground)
    tracks = []
    for vehicle_id, by_t in points.items():
        ts = np.array(sorted(by_t))
        xy = np.array([by_t[t] for t in ts])
        for k, idx in enumerate(np.split(np.arange(len(ts)), np.where(np.diff(ts) > max_gap_s)[0] + 1)):
            if len(idx) >= min_points:
                tracks.append(Track(vehicle_id if k == 0 else f"{vehicle_id}#{k}", ts[idx], xy[idx],
                                    smooth_half=smooth_half))
    tracks.sort(key=lambda tr: tr.t[0])
    return tracks


def track_vehicle(track_id) -> str | None:
    """The box id behind a (possibly split) track id: "B#2" -> "B"."""
    return None if track_id is None else str(track_id).split("#")[0]


def nominal_reader(reader_id: str, geometry: CameraGeometry, slot: float = DEFAULT_SLOT_S,
                   range_m: float = 10.0, p_peak: float = 0.9) -> Reader:
    """Installer guess for one junction reader: a round footprint whose 1-sigma
    radius is ~0.6 x the nominal read range, centred on the junction."""
    cx, cy = geometry.reader_xy
    sigma = 0.6 * range_m
    return Reader.nominal(reader_id, cx, cy, sx=sigma, sy=sigma, p_peak=p_peak,
                          link="rate", dt=slot)


def reader_to_dict(reader: Reader) -> dict:
    return {"reader_id": reader.reader_id, "cx": reader.cx, "cy": reader.cy,
            "w": [float(v) for v in reader.w], "tau": float(reader.tau), "link": reader.link}


def reader_from_dict(data: dict) -> Reader:
    return Reader(str(data["reader_id"]), float(data["cx"]), float(data["cy"]),
                  np.asarray(data["w"], float), float(data.get("tau", 0.0)),
                  str(data.get("link", "rate")))
