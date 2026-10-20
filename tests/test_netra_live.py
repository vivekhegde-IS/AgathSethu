"""NETRA live path: real-CARLA calibration (v2), HARD-pass rule with per-group
thresholds, NETRA's own history, online clock offsets, service wiring."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "member3" / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

import netra_scenario_eval as nse  # noqa: E402
import netra_sim as ns  # noqa: E402

from app.services.rfid.config import RfidFeatureConfig  # noqa: E402
from app.services.rfid.netra.adapter import nominal_reader, reader_to_dict  # noqa: E402
from app.services.rfid.netra.core import Pass, Track  # noqa: E402
from app.services.rfid.netra.geometry import camera_for  # noqa: E402
from app.services.rfid.netra.live import NetraLive  # noqa: E402
from app.services.rfid.netra.shadow import (  # noqa: E402
    STATUS_CONFIRMED,
    STATUS_UNCERTAIN,
    NetraShadow,
    make_engine,
)
from app.services.rfid.vision import Suspect  # noqa: E402

REAL = Path(RfidFeatureConfig().netra_calibration)
SYNTHETIC = REAL.with_name("netra_calibration_synthetic.json")
FOUR_ANTENNAS = REAL.with_name("netra_calibration_layout_4_antennas.json")


def _synthetic():
    return json.loads(SYNTHETIC.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- calibration v2

def test_real_calibration_is_the_frozen_s1_s3_one():
    sh = NetraShadow.from_file(REAL)
    assert sh.calibrated and sh.per_group
    assert sh.thr_easy == pytest.approx(0.4593, abs=1e-3)
    assert sh.thr_hard == pytest.approx(0.8159, abs=1e-3)
    assert sh.threshold == pytest.approx(0.5656, abs=1e-3)
    assert set(sh.cameras) == {"J01", "J02", "J03"}
    # positions-file layout: J01's reader 20 m ahead / 4 m right of its camera
    assert sh.reader_position("J01", "RFID_J01_01") == pytest.approx((20.0, 4.0), abs=0.5)
    assert sh.clock["default_tau"]["J02"] == pytest.approx(0.15, abs=0.1)


def test_four_antenna_layout_places_each_antenna_with_the_shared_field():
    sh = NetraShadow.from_file(FOUR_ANTENNAS)
    ants = sh.antennas["J01"]
    assert len(ants) == 4
    readers = sh._readers_for("J01", set(ants))
    assert {(round(r.cx, 3), round(r.cy, 3)) for r in readers.values()} == \
        {(round(x, 3), round(y, 3)) for x, y in ants.values()}
    assert len({tuple(r.w) for r in readers.values()}) == 1


def test_v1_calibration_still_loads_with_one_threshold():
    sh = NetraShadow(_synthetic())
    assert sh.calibrated and not sh.per_group and np.isfinite(sh.threshold)


# ---------------------------------------------------------------- HARD rule

def _line_track(tid, x0, y, ts):
    ts = np.asarray(ts, float)
    return Track(tid, ts, np.column_stack([np.full(len(ts), x0), np.full(len(ts), y)]), smooth_half=0)


def test_hard_rule_contested_short_and_split_tracks():
    rid = "RFID_J01_01"
    sh = NetraShadow({"readers": {"J01": reader_to_dict(nominal_reader(rid, camera_for("J01")))},
                      "thresholds": {"easy": 0.4, "hard": 0.8}})
    eng = make_engine(sh._readers_for("J01", {rid}))
    cx, cy = eng.readers[rid].cx, eng.readers[rid].cy
    ts = np.arange(9.0, 14.0, 0.25)
    p = Pass("E1", [(rid, 10.0 + 0.5 * i) for i in range(6)], 10.0, 12.5)
    a = _line_track("A", cx + 2.0, cy, ts)
    b = _line_track("B", cx - 3.0, cy + 2.0, ts)
    far = _line_track("C", cx + 40.0, cy, ts)
    a_again = _line_track("A#1", cx + 1.0, cy, ts)
    assert sh.is_hard(p, [a, far], eng) == (False, False)
    assert sh.is_hard(p, [a, b], eng) == (True, False)
    assert sh.is_hard(p, [a, a_again], eng) == (False, False)        # one vehicle, two tracks
    assert sh.is_hard(Pass("E1", p.raw[:3], 10.0, 11.0), [a], eng) == (False, True)
    late = _line_track("B", cx, cy, np.arange(20.0, 22.0, 0.25))     # near the reader, but later
    assert sh.is_hard(p, [a, late], eng) == (False, False)


def test_per_group_threshold_is_applied(scenario_j02):
    cal = _synthetic()
    cal["thresholds"] = {"easy": 0.0, "hard": 1.01}     # easy always confirms, hard never
    sh = NetraShadow(cal)
    seen = set()
    reports, frames = scenario_j02
    for epc, t0, t1 in nse._passes(reports):
        res = sh.assess(epc, "J02", t0, t1, reports, frames)
        if res["proposed_track"] is None:
            continue
        expected = (STATUS_UNCERTAIN, 1.01) if res["hard"] else (STATUS_CONFIRMED, 0.0)
        assert (res["status"], res["threshold"]) == expected
        seen.add(res["hard"])
    assert seen, "no proposal at all"


@pytest.fixture(scope="module")
def scenario_j02():
    jd = ns.acceptance_scenario()["J02"]
    return jd.reports, jd.frames


# ---------------------------------------------------------------- NetraLive

BOX = [{"vehicle_id": "A", "bbox": [600, 300, 660, 350], "depth_m": 25.0}]


def test_camera_frame_boxes_only_without_a_vehicle_boxes_stream():
    live = NetraLive(NetraShadow(_synthetic()))
    live.ingest_boxes("J01", 1.00, BOX, "vehicle_boxes")
    live.ingest_boxes("J01", 1.05, BOX, "camera_frame")
    assert live.counters["camera_frame_boxes_skipped"] == 1
    live.ingest_boxes("J02", 1.00, BOX, "camera_frame")       # no vehicle_boxes for J02
    live.ingest_boxes("J01", 1.00, BOX, "vehicle_boxes")      # same instant: not stored twice
    assert live.counters["box_frames"] == 2


def test_late_boxes_are_stored_in_order_without_a_reset():
    live = NetraLive(NetraShadow(_synthetic()))
    live.ingest_boxes("J01", 100.0, BOX)
    live.ingest_boxes("J01", 92.0, BOX)          # a lagging / re-sent message
    assert live.counters["resets"] == 0
    assert live._box_t["J01"] == [92.0, 100.0]
    live.reset("new run")                         # runs are reset by the service
    assert live._box_t["J01"] == [] and live.counters["resets"] == 1


def test_lagging_camera_frames_do_not_reset_the_run(tmp_path):
    import base64

    from test_netra import _service

    service = _service(tmp_path)
    jpeg = base64.b64encode(b"x").decode()
    service._sim_now = 100.0                      # RFID / boxes already at t=100
    for t in (92.0, 92.5):                        # the JPEG stream lags by 8 s
        service.on_camera_frame({"camera_id": "CAM_J01_01", "junction_id": "J01",
                                 "timestamp_sim": t, "image": jpeg})
    assert service.counters["run_resets"] == 0
    service.on_camera_frame({"camera_id": "CAM_J01_01", "junction_id": "J01",
                             "timestamp_sim": 3.0, "image": jpeg})   # this camera's clock restarted
    assert service.counters["run_resets"] == 1


def test_history_is_trimmed_to_history_s():
    live = NetraLive(NetraShadow(_synthetic()), history_s=30.0)
    for t in np.arange(0.0, 100.0, 0.5):
        live.ingest_boxes("J01", float(t), BOX)
    assert min(live._box_t["J01"]) >= 69.5


def _feed(live, jd, shift):
    events = []
    for r in jd.reports:
        r2 = copy.copy(r)
        r2.first_seen_ts += shift
        r2.last_seen_ts += shift
        events.append((r2.last_seen_ts, 0, r2))
    for f in jd.frames:
        if f.vehicles is not None:
            events.append((f.timestamp_sim, 1, f))
    for _, kind, item in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            live.ingest_report(item)
        else:
            live.ingest_boxes(item.junction_id, item.timestamp_sim, item.vehicles)


def test_clock_offset_starts_at_the_default_then_is_estimated_online():
    cal = _synthetic()
    cal["clock"] = {"default_tau": {"J02": 0.15}}
    live = NetraLive(NetraShadow(cal))
    jd = ns.random_traffic(11, duration=300.0)["J02"]
    first = jd.reports[0]
    live.ingest_report(first)
    taus, source = live.clock("J02")
    assert source == "default" and taus == {first.reader_id: 0.15}
    live = NetraLive(NetraShadow(cal))
    _feed(live, jd, shift=0.4)              # reader clock 0.4 s ahead of the camera
    taus, source = live.clock("J02")
    assert source == "estimated"
    assert list(taus.values())[0] == pytest.approx(0.4, abs=0.15)


def test_live_assess_uses_netra_history_and_reports_its_inputs(scenario_j02):
    live = NetraLive(NetraShadow(_synthetic()))
    reports, frames = scenario_j02
    jd = type("JD", (), {"reports": reports, "frames": frames})
    _feed(live, jd, shift=0.0)
    b = next(p for p in nse._passes(reports) if p[0] == ns.acceptance_scenario()["J02"].reports[0].epc)
    res = live.assess(b[0], "J02", b[1], b[2])
    assert res["inputs"] == "netra_history"
    assert res["clock_source"] in ("default", "estimated")
    assert res["status"] != "NO_DATA"


# ---------------------------------------------------------------- service wiring

def test_service_feeds_netra_history_from_vehicle_boxes_and_reports(tmp_path, scenario_j02):
    from test_netra import _b_sighting, _service

    service = _service(tmp_path, netra_enabled=True, netra_calibration=str(SYNTHETIC))
    assert service.netra_live is not None
    reports, frames = scenario_j02
    events = [(r.last_seen_ts, 0, r) for r in reports] + [(f.timestamp_sim, 1, f) for f in frames]
    for _, kind, item in sorted(events, key=lambda e: (e[0], e[1])):      # arrival order, as live
        if kind == 0:
            service.netra_live.ingest_report(item)
        else:
            service.on_vehicle_boxes({"type": "vehicle_boxes", "junction_id": item.junction_id,
                                      "timestamp_sim": item.timestamp_sim, "vehicles": item.vehicles or []})
    assert service.netra_live.counters["box_frames"] > 0
    assert service.netra_live.counters["resets"] == 0
    sighting = _b_sighting()
    service._netra_shadow(sighting, Suspect(epc=sighting.epc, vehicle_id="B"))
    assert sighting.netra["inputs"] == "netra_history"
    assert sighting.netra["proposed_track"] == "B" and sighting.netra["agrees"] is True


def test_vehicle_boxes_are_ignored_when_netra_is_off(tmp_path):
    from test_netra import _service

    service = _service(tmp_path)
    assert service.netra_live is None
    service.on_vehicle_boxes({"type": "vehicle_boxes", "junction_id": "J01", "timestamp_sim": 1.0,
                              "vehicles": BOX})
    assert service.counters["errors"] == 0
