"""NETRA shadow assessment for one sighting.

Answers, from RFID reads + camera boxes alone: which visible vehicle carries
this EPC at this junction, or is it on no visible vehicle? The current
decision path (registry -> CARLA actor id) is NOT changed; the service only
attaches this result to the vision payload so the two can be compared.

Calibration (read fields + confirmation threshold) is loaded from the JSON
written by ``tools/netra_calibrate.py`` (synthetic, version 1) or by
``claude try/export_backend_calibration.py`` (real CARLA runs, version 2).
Without it the installer-guess fields are used and the threshold is +inf:
NETRA still proposes a track but never confirms one (an uncertified threshold
would be a guess).

Version 2 adds, all optional:
  thresholds  {"easy", "hard", "single"}: per-group confirmation thresholds. A
              pass is HARD when it is contested (>= 2 camera vehicles within
              hard_rule.zone_m of a reader during the pass +- pad_s) or short
              (<= short_reads_max reads); each group was certified at delta/2.
  hard_rule   {"zone_m", "pad_s", "short_reads_max"}
  antennas    {junction: {reader_id: [forward, lateral]}} camera-local antenna
              positions when a junction has several antennas
  clock       default / online reader clock offsets (used by live.py)
"""

from __future__ import annotations

import copy
import json
import logging
import math
from pathlib import Path

import numpy as np

from app.services.rfid.netra.adapter import (
    DEFAULT_SLOT_S,
    nominal_reader,
    reader_from_dict,
    reads_from_reports,
    track_vehicle,
    tracks_from_frames,
)
from app.services.rfid.netra.core import NETRA
from app.services.rfid.netra.geometry import CameraGeometry, camera_for

log = logging.getLogger("rfid.netra")

# Engine settings shared by the runtime and the calibration tool. A junction
# pass is ~2-4 s (10 m read range at 8-12 m/s); a stopped vehicle keeps being
# read, so passes are capped at max_pass.
ENGINE_DEFAULTS = dict(
    slot=DEFAULT_SLOT_S, rho0=1e-3, pass_gap=20.0, max_pass=30.0, window=20.0, pad=2.0,
    p_undetected=0.05, p_static=0.01,
    phantom_speeds=tuple(np.arange(3.0, 27.0, 2.5)),
    phantom_shifts=tuple(np.arange(-1.0, 1.01, 0.5)),
)

STATUS_CONFIRMED = "CONFIRMED"            # proposed track, confidence >= certified threshold
STATUS_UNCERTAIN = "UNCERTAIN"            # proposed track, below the threshold (or uncalibrated)
STATUS_NO_VISIBLE = "NOT_ON_VISIBLE_VEHICLE"
STATUS_NO_DATA = "NO_DATA"                # no reads of this EPC / no camera metadata

# HARD pass definition (claude try/verify_fixes.py): fixed before the blind
# S7 / S8 sessions, so these values must not be tuned on deployment data.
DEFAULT_HARD_RULE = {"zone_m": 10.0, "pad_s": 0.5, "short_reads_max": 3}


def _finite_or_none(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def make_engine(readers: dict) -> NETRA:
    kw = dict(ENGINE_DEFAULTS)
    kw["phantom_speeds"] = np.asarray(kw["phantom_speeds"], float)
    kw["phantom_shifts"] = np.asarray(kw["phantom_shifts"], float)
    return NETRA(readers, **kw)


class NetraShadow:
    def __init__(self, calibration: dict | None = None):
        calibration = calibration or {}
        self.readers = {jid: reader_from_dict(data)
                        for jid, data in (calibration.get("readers") or {}).items()}
        thr = calibration.get("threshold")
        self.threshold = float(thr) if thr is not None and math.isfinite(float(thr)) else math.inf
        # Exact camera geometry from a real run (camera_poses.json), when the
        # calibration was made from one; otherwise Member 1's code constants.
        self.cameras = {jid: CameraGeometry(**data)
                        for jid, data in (calibration.get("cameras") or {}).items()}
        self.alpha = calibration.get("alpha")
        self.delta = calibration.get("delta")
        groups = calibration.get("thresholds") or {}
        self.thr_easy = _finite_or_none(groups.get("easy"))
        self.thr_hard = _finite_or_none(groups.get("hard"))
        self.per_group = self.thr_easy is not None and self.thr_hard is not None
        rule = dict(DEFAULT_HARD_RULE, **(calibration.get("hard_rule") or {}))
        self.hard_zone_m = float(rule["zone_m"])
        self.hard_pad_s = float(rule["pad_s"])
        self.short_reads_max = int(rule["short_reads_max"])
        self.antennas = {jid: {rid: (float(xy[0]), float(xy[1])) for rid, xy in ants.items()}
                         for jid, ants in (calibration.get("antennas") or {}).items()}
        self.clock = dict(calibration.get("clock") or {})
        self.calibrated = bool(self.readers) and (math.isfinite(self.threshold) or self.per_group)

    @classmethod
    def from_file(cls, path: str | Path | None) -> "NetraShadow":
        if path:
            p = Path(path)
            if p.is_file():
                try:
                    return cls(json.loads(p.read_text(encoding="utf-8")))
                except (OSError, ValueError) as exc:
                    log.warning("[NETRA] calibration %s unreadable (%s): uncalibrated", p, exc)
            else:
                log.warning("[NETRA] calibration %s not found: uncalibrated (never confirms)", p)
        return cls(None)

    def reader_position(self, junction_id: str, reader_id: str) -> tuple[float, float]:
        """Camera-local (forward, lateral) of one antenna: its own entry in
        ``antennas`` when the junction has several, else the junction reader."""
        ants = self.antennas.get(junction_id) or {}
        if reader_id in ants:
            return ants[reader_id]
        base = self.readers.get(junction_id)
        if base is not None:
            return (base.cx, base.cy)
        return camera_for(junction_id, self.cameras).reader_xy

    def _readers_for(self, junction_id: str, reader_ids: set[str], taus: dict | None = None,
                     nominal: bool = False) -> dict:
        """One engine reader per antenna seen. The fitted field shape is shared by
        the junction's antennas (same hardware); each sits at its own position.
        nominal=True gives the installer guess (used to estimate clock offsets)."""
        base = None if nominal else self.readers.get(junction_id)
        geometry = camera_for(junction_id, self.cameras)
        out = {}
        for rid in sorted(reader_ids):
            reader = copy.deepcopy(base) if base is not None else nominal_reader(rid, geometry)
            reader.reader_id = rid
            reader.cx, reader.cy = self.reader_position(junction_id, rid)
            if taus and rid in taus:
                reader.tau = float(taus[rid])
            out[rid] = reader
        return out

    def is_hard(self, pass_, tracks, engine) -> tuple[bool, bool]:
        """(contested, short) for one decided pass: >= 2 camera vehicles within
        zone_m of any antenna during the pass +- pad_s, or <= short_reads_max reads."""
        lo, hi = pass_.t0 - self.hard_pad_s, pass_.t1 + self.hard_pad_s
        near = set()
        for tr in tracks:
            sel = (tr.t >= lo) & (tr.t <= hi)
            if not sel.any():
                continue
            xy = tr.xy[sel]
            if any(np.min(np.hypot(xy[:, 0] - rd.cx, xy[:, 1] - rd.cy)) <= self.hard_zone_m
                   for rd in engine.readers.values()):
                near.add(track_vehicle(tr.track_id))
        return len(near) >= 2, len(pass_.raw) <= self.short_reads_max

    def assess(self, epc: str, junction_id: str, t0: float, t1: float,
               reports: list, frames: list, taus: dict | None = None) -> dict:
        """reports: RfidRead of ALL tags at this junction around [t0, t1]
        (other tags compete for the same tracks). frames: FrameRef of this
        junction's camera(s) over the same span. taus: {reader_id: clock
        offset s} (reader clock minus camera clock), e.g. from live.py."""
        base = {"status": STATUS_NO_DATA, "track_id": None, "proposed_track": None,
                "confidence": None, "threshold": None if math.isinf(self.threshold) else self.threshold,
                "thresholds": ({"easy": self.thr_easy, "hard": self.thr_hard} if self.per_group else None),
                "alpha": self.alpha, "delta": self.delta, "calibrated": self.calibrated,
                "null_kind": None, "candidates": [], "n_tags": 0, "n_tracks": 0, "n_reads": 0,
                "hard": None, "contested": None, "short": None,
                "clock_offsets_s": {k: round(float(v), 3) for k, v in (taus or {}).items()} or None}
        reports = [r for r in reports if r.junction_id == junction_id]
        if not any(r.epc == epc for r in reports):
            base["reason"] = "no reads of this EPC in the window"
            return base
        tracks = tracks_from_frames(frames, camera_for(junction_id, self.cameras))
        base["n_tracks"] = len(tracks)
        if not tracks:
            base["reason"] = "no camera vehicle metadata in the window"
            return base
        engine = make_engine(self._readers_for(junction_id, {r.reader_id for r in reports}, taus))
        reads = reads_from_reports(reports, engine.slot)
        base["n_tags"] = len({r.tag_id for r in reads})

        mid = 0.5 * (t0 + t1)
        best = None
        for rec in engine.evidence(reads, tracks):
            for k, p in zip(rec["decide"], rec["decide_src"]):
                if p.tag_id == epc and (best is None or abs(p.mid - mid) < abs(best[2].mid - mid)):
                    best = (rec, k, p)
        if best is None:
            base["reason"] = "the EPC's pass was not decided in any window"
            return base
        rec, k, p = best
        decision = next(d for d, (kk, pp) in zip(engine.decode([rec]), zip(rec["decide"], rec["decide_src"]))
                        if kk == k and pp is p)
        lam = rec["lam_full"][k]
        order = np.argsort(-lam)[:3]
        ph = float(rec["phantom_full"][k]) + engine.log_prior_undetected
        st = float(rec["static_full"][k]) + engine.log_prior_static
        base.update(
            proposed_track=decision["proposed_track"],
            confidence=round(decision["confidence"], 4),
            n_reads=len(p.raw), pass_t0=round(p.t0, 3), pass_t1=round(p.t1, 3),
            candidates=[{"track_id": rec["track_ids"][j], "llr": round(float(lam[j]), 2)}
                        for j in order],
            null_llr={"missed_vehicle": round(ph, 2), "stationary_tag": round(st, 2)},
        )
        contested, short = self.is_hard(p, tracks, engine)
        hard = contested or short
        base.update(hard=hard, contested=contested, short=short)
        if self.per_group:
            threshold = self.thr_hard if hard else self.thr_easy
            base["threshold"] = threshold
        else:
            threshold = self.threshold
        if decision["proposed_track"] is None:
            base["status"] = STATUS_NO_VISIBLE
            base["null_kind"] = "missed_vehicle" if ph >= st else "stationary_tag"
        elif decision["confidence"] >= threshold:
            base["status"] = STATUS_CONFIRMED
            base["track_id"] = decision["proposed_track"]
        else:
            base["status"] = STATUS_UNCERTAIN
        base.pop("reason", None)
        return base
