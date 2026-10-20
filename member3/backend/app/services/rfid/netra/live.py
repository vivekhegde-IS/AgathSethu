"""NETRA live inputs: its own history of RFID reports and camera boxes, and
online reader clock offsets.

The service's vision buffers keep only a few seconds of camera boxes around a
sighting (JPEG ring), but NETRA scores a tag against every track in a 20 s
window and estimates clock offsets from minutes of traffic. ``NetraLive`` keeps

* every RFID report per junction (``ingest_report``),
* every camera box per junction, preferring Member 1's 20 Hz ``vehicle_boxes``
  messages; ``camera_frame`` boxes are used only while no ``vehicle_boxes``
  arrive for that junction (older CARLA script),

for ``history_s`` sim seconds, and answers ``assess(epc, junction, t0, t1)``
with ``NetraShadow.assess`` on those windows.

Clock offsets (reader clock minus camera clock): until enough traffic has been
seen, the calibration's default per junction; then, every ``every_s`` sim
seconds, re-estimated from the last ``window_s`` seconds of this junction's
reads and tracks (EM over the clock offset only, installer-guess read fields;
the same estimator as the offline analysis). Only past data is used.
"""

from __future__ import annotations

import bisect
import logging
import threading
from collections import defaultdict

from app.services.rfid.netra.adapter import reads_from_reports, tracks_from_frames
from app.services.rfid.netra.geometry import camera_for
from app.services.rfid.netra.shadow import NetraShadow, make_engine
from app.services.rfid.vision import FrameRef

log = logging.getLogger("rfid.netra")

DEFAULT_CLOCK = {
    "online": True,
    "window_s": 600.0,       # traffic used per estimate
    "every_s": 60.0,         # re-estimate cadence (sim time)
    "min_passes": 8,         # fewer tag passes in the window: keep the previous value
    "iters": 3,
    "default_tau": {},       # {junction: offset s} before the first estimate
}
BOX_SOURCE_HOLD_S = 5.0      # vehicle_boxes seen this recently: ignore camera_frame boxes


class NetraLive:
    def __init__(self, shadow: NetraShadow, history_s: float = 660.0,
                 reads_margin_s: float = 20.0, track_pad_s: float = 22.0):
        self.shadow = shadow
        self.history_s = float(history_s)
        self.reads_margin_s = float(reads_margin_s)
        self.track_pad_s = float(track_pad_s)
        self.clock_cfg = dict(DEFAULT_CLOCK, **(shadow.clock or {}))
        self._lock = threading.Lock()
        self.counters = defaultdict(int)
        self.reset("init")

    # ------------------------------------------------------------ history
    def reset(self, reason: str = "") -> None:
        with self._lock:
            self._reset_locked(reason)

    def _reset_locked(self, reason: str) -> None:
        self._reports = defaultdict(list)          # jid -> [RfidRead] by arrival
        self._box_t = defaultdict(list)            # jid -> sorted timestamps
        self._box_v = defaultdict(list)            # jid -> vehicles, parallel to _box_t
        self._last_vb = {}                         # jid -> last vehicle_boxes timestamp
        self._now = None
        self._tau = {}                             # jid -> {reader_id: offset}
        self._tau_at = {}                          # jid -> sim time of the last estimate
        self._tau_source = {}                      # jid -> "default" / "estimated"
        if reason and reason != "init":
            self.counters["resets"] += 1
            log.info("[NETRA] live history reset: %s", reason)

    def _advance(self, t: float) -> None:
        """Caller holds the lock. Late messages (a lagging camera, the reliable
        queue re-sending after a reconnect) are stored in time order; a new CARLA
        run is decided by the service (run_id / per-camera backjump), which calls
        reset()."""
        self._now = t if self._now is None else max(self._now, t)

    def _trim(self, jid: str) -> None:
        cut = (self._now or 0.0) - self.history_s
        reps = self._reports[jid]
        if reps and reps[0].last_seen_ts < cut:
            self._reports[jid] = [r for r in reps if r.last_seen_ts >= cut]
        ts = self._box_t[jid]
        k = bisect.bisect_left(ts, cut)
        if k:
            del ts[:k]
            del self._box_v[jid][:k]

    def ingest_report(self, read) -> None:
        with self._lock:
            self._advance(float(read.last_seen_ts))
            self._reports[read.junction_id].append(read)
            self.counters["reports"] += 1
            self._trim(read.junction_id)

    def ingest_boxes(self, junction_id: str, timestamp: float, vehicles,
                     source: str = "vehicle_boxes") -> None:
        if not junction_id or vehicles is None:
            return
        t = float(timestamp)
        with self._lock:
            self._advance(t)
            if source == "vehicle_boxes":
                self._last_vb[junction_id] = t
            elif (junction_id in self._last_vb
                  and t - self._last_vb[junction_id] <= BOX_SOURCE_HOLD_S):
                self.counters["camera_frame_boxes_skipped"] += 1
                return
            ts, vs = self._box_t[junction_id], self._box_v[junction_id]
            k = bisect.bisect_left(ts, t)
            if k < len(ts) and ts[k] == t:
                return                             # same instant already stored
            ts.insert(k, t)
            vs.insert(k, vehicles)
            self.counters["box_frames"] += 1
            self._trim(junction_id)

    def _snapshot(self, jid: str, r_lo: float, r_hi: float, b_lo: float, b_hi: float):
        """Caller holds the lock: reports overlapping [r_lo, r_hi] and box frames in [b_lo, b_hi]."""
        reps = [r for r in self._reports.get(jid, ()) if r.last_seen_ts >= r_lo and r.first_seen_ts <= r_hi]
        ts, vs = self._box_t.get(jid, []), self._box_v.get(jid, [])
        a, b = bisect.bisect_left(ts, b_lo), bisect.bisect_right(ts, b_hi)
        frames = [FrameRef(jid, jid, ts[i], b"", None, vs[i]) for i in range(a, b)]
        return reps, frames

    # ------------------------------------------------------------ clock offsets
    def clock(self, jid: str) -> tuple[dict, str]:
        """({reader_id: offset}, source) for this junction, re-estimating when due."""
        cfg = self.clock_cfg
        default = float((cfg.get("default_tau") or {}).get(jid, 0.0))
        with self._lock:
            now = self._now
            due = (cfg.get("online", True) and now is not None
                   and now - self._tau_at.get(jid, -1e18) >= float(cfg["every_s"]))
            if due:
                self._tau_at[jid] = now
                reps, frames = self._snapshot(jid, now - float(cfg["window_s"]), now,
                                              now - float(cfg["window_s"]), now)
        if due:
            est = self._estimate(jid, reps, frames)
            if est is not None:
                with self._lock:
                    self._tau[jid] = est
                    self._tau_source[jid] = "estimated"
                self.counters["clock_estimates"] += 1
        with self._lock:
            taus = dict(self._tau.get(jid) or {})
            source = self._tau_source.get(jid, "default")
            reader_ids = {r.reader_id for r in self._reports.get(jid, ())}
        for rid in reader_ids:
            taus.setdefault(rid, default)
        return taus, source

    def _estimate(self, jid: str, reports: list, frames: list) -> dict | None:
        if not reports or not frames:
            return None
        sh = self.shadow
        tracks = tracks_from_frames(frames, camera_for(jid, sh.cameras))
        if not tracks:
            return None
        engine = make_engine(sh._readers_for(jid, {r.reader_id for r in reports}, nominal=True))
        reads = reads_from_reports(reports, engine.slot)
        if len(engine.build_passes(reads)) < int(self.clock_cfg["min_passes"]):
            return None
        try:
            engine.self_calibrate(reads, tracks, iters=int(self.clock_cfg["iters"]),
                                  update_tau=True, update_fields=False)
        except Exception as exc:                   # pragma: no cover - defensive
            log.warning("[NETRA] clock estimate failed at %s: %s", jid, exc)
            return None
        return {rid: float(rd.tau) for rid, rd in engine.readers.items()}

    # ------------------------------------------------------------ assessment
    def assess(self, epc: str, junction_id: str, t0: float, t1: float) -> dict:
        taus, source = self.clock(junction_id)
        m = self.reads_margin_s
        with self._lock:
            reps, frames = self._snapshot(junction_id, t0 - m, t1 + m,
                                          t0 - self.track_pad_s, t1 + self.track_pad_s)
        result = self.shadow.assess(epc, junction_id, t0, t1, reps, frames, taus=taus)
        result["clock_source"] = source
        result["inputs"] = "netra_history"
        self.counters["assessments"] += 1
        return result

    def has_data(self, junction_id: str) -> bool:
        with self._lock:
            return bool(self._reports.get(junction_id)) and bool(self._box_t.get(junction_id))
