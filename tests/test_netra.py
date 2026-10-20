"""NETRA shadow association: geometry, adapter, shadow decisions, service hook.

Run:  pytest tests/test_netra.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "member3" / "backend"))

pytest.importorskip("scipy")

import netra_sim as ns  # noqa: E402
import netra_scenario_eval as nse  # noqa: E402

from app.services.rfid.config import RfidFeatureConfig  # noqa: E402
from app.services.rfid.netra.adapter import (  # noqa: E402
    nominal_reader,
    reader_from_dict,
    reader_to_dict,
    reads_from_reports,
    tracks_from_frames,
)
from app.services.rfid.netra.geometry import JUNCTION_CAMERAS, camera_for  # noqa: E402
from app.services.rfid.netra.shadow import (  # noqa: E402
    STATUS_CONFIRMED,
    STATUS_NO_DATA,
    STATUS_UNCERTAIN,
    NetraShadow,
)
from app.services.rfid.normalize import RfidRead  # noqa: E402
from app.services.rfid.sightings import SightingDraft  # noqa: E402
from app.services.rfid.vision import FrameRef, Suspect  # noqa: E402

# the acceptance scenario is synthetic (tools/netra_sim.py): it is checked against the
# synthetic calibration; the real-CARLA one (netra_calibration.json) has another layout
CALIBRATION = Path(RfidFeatureConfig().netra_calibration).with_name("netra_calibration_synthetic.json")


@pytest.fixture(scope="module")
def scenario():
    return ns.acceptance_scenario()


@pytest.fixture(scope="module")
def calibrated():
    if not CALIBRATION.is_file():
        pytest.skip("run tools/netra_calibrate.py first")
    shadow = NetraShadow.from_file(CALIBRATION)
    assert shadow.calibrated
    return shadow


# ---------------------------------------------------------------- geometry

@pytest.mark.parametrize("jid", sorted(JUNCTION_CAMERAS))
def test_box_depth_round_trip_lands_near_the_true_ground_point(jid):
    g = camera_for(jid)
    for fwd, lat, heading in [(g.back_m, g.lateral_m, 0.0), (g.back_m + 8, g.lateral_m - 5, 1.6),
                              (g.back_m - 7, g.lateral_m + 4, 3.1), (20.0, 0.0, 0.7)]:
        proj = g.project_vehicle(fwd, lat, heading)
        assert proj is not None, (fwd, lat)
        bbox, depth = proj
        f2, l2 = g.ground_from_box(bbox, depth)
        assert math.hypot(f2 - fwd, l2 - lat) < 1.5


def test_vehicle_behind_the_camera_is_not_in_view():
    assert camera_for("J02").project_vehicle(-5.0, 0.0, 0.0) is None
    assert camera_for("J02").ground_from_box([0, 0, 10, 10], None) is None


# ---------------------------------------------------------------- adapter

def _read(epc, first, last, rid="RFID_J02_01", jid="J02"):
    return RfidRead(epc=epc, reader_id=rid, junction_id=jid, first_seen_ts=first, last_seen_ts=last)


def test_v2_report_becomes_one_read_per_covered_slot():
    reads = reads_from_reports([_read("E1", 10.0, 11.2)], slot=0.5)
    assert [round(r.t, 2) for r in reads] == [10.0, 10.5, 11.0, 11.2]
    assert reads_from_reports([_read("E1", 5.0, 5.0)], slot=0.5)[0].t == 5.0
    swapped = reads_from_reports([_read("E1", 6.0, 5.0)], slot=0.5)
    assert [r.t for r in swapped] == [5.0, 5.5, 6.0]


def test_tracks_group_by_vehicle_and_ignore_frames_without_metadata():
    g = camera_for("J02")
    frames = []
    for i in range(15):
        t = 10 + 0.2 * i
        bbox, depth = g.project_vehicle(10 + 2 * i, 6.0, 0.0)
        frames.append(FrameRef("CAM_J02_01", "J02", t, b"", None,
                               [{"vehicle_id": "B", "bbox": bbox, "depth_m": depth}]))
    frames.append(FrameRef("CAM_J02_01", "J02", 13.1, b"", None, None))
    frames.append(FrameRef("CAM_J02_01", "J02", 13.3, b"", None,
                           [{"vehicle_id": "X", "bbox": [600, 300, 700, 380], "depth_m": 30.0}]))
    tracks = tracks_from_frames(frames, g)
    assert [tr.track_id for tr in tracks] == ["B"]          # X has a single point
    assert len(tracks[0].t) == 15
    # 2 m per 0.2 s; the core's 5-tap smoothing biases only the track ends
    assert abs(float(np.median(tracks[0].speed[3:-3])) - 10.0) < 1.0


def test_reader_serialisation_round_trip():
    reader = nominal_reader("RFID_J03_01", camera_for("J03"))
    again = reader_from_dict(reader_to_dict(reader))
    assert again.reader_id == reader.reader_id and np.allclose(again.w, reader.w)
    assert (again.cx, again.cy) == (25.0, -8.0)


# ---------------------------------------------------------------- simulator

def test_simulator_is_deterministic():
    a, b = ns.random_traffic(7, duration=40), ns.random_traffic(7, duration=40)
    c = ns.random_traffic(8, duration=40)
    key = lambda d: [(r.epc, r.first_seen_ts, r.last_seen_ts) for jd in d.values() for r in jd.reports]  # noqa: E731
    assert key(a) == key(b) and key(a) != key(c)


# ---------------------------------------------------------------- shadow decisions

def test_uncalibrated_never_confirms_but_still_proposes(scenario):
    shadow = NetraShadow(None)
    jd = scenario["J02"]
    b_epc = _epc("B")
    rows = [r for r in nse.evaluate(shadow, {"J02": jd}) if r["epc"] == b_epc]
    assert rows and rows[0]["proposed_track"] == "B"
    assert rows[0]["status"] == STATUS_UNCERTAIN and rows[0]["track_id"] is None


def test_no_reads_or_no_camera_metadata_is_no_data(scenario):
    shadow = NetraShadow(None)
    jd = scenario["J02"]
    assert shadow.assess("NOT_A_TAG", "J02", 50, 60, jd.reports, jd.frames)["status"] == STATUS_NO_DATA
    bare = [FrameRef(f.camera_id, f.junction_id, f.timestamp_sim, b"", None, None) for f in jd.frames]
    res = shadow.assess(_epc("B"), "J02", 53.85, 58.05, jd.reports, bare)
    assert res["status"] == STATUS_NO_DATA and res["n_tracks"] == 0


def test_fleeing_b_is_confirmed_at_j02_and_j03_next_to_f_and_g(scenario, calibrated):
    rows = nse.evaluate(calibrated, scenario)
    for jid in ("J02", "J03"):
        b = [r for r in rows if r["junction"] == jid and r["vehicle"] == "B"]
        assert len(b) == 1, jid
        assert b[0]["status"] == STATUS_CONFIRMED and b[0]["track_id"] == "B", b[0]


def test_no_wrong_identity_on_the_acceptance_scenario(scenario, calibrated):
    rows = nse.evaluate(calibrated, scenario)
    proposed = [r for r in rows if r["proposed_track"] is not None]
    assert proposed
    assert all(r["proposed_track"] == r["vehicle"] for r in proposed), \
        [r for r in proposed if r["proposed_track"] != r["vehicle"]]


def _epc(name):
    import scenario as sc
    return sc.EPCS[name]


# ---------------------------------------------------------------- service hook

def _service(tmp_path, **overrides):
    from app.services.rfid.evidence import EvidenceStore
    from app.services.rfid.registry import VehicleRegistry
    from app.services.rfid.service import RfidCrossVerification

    cfg = RfidFeatureConfig(**{**RfidFeatureConfig().as_dict(),
                               "evidence_dir": str(tmp_path / "ev"), **overrides})

    class _Store:
        def submit(self, kind, payload):
            return True

    class _Inline:
        def submit(self, fn, *a, **k):
            fn(*a, **k)

        def shutdown(self, wait=False):
            pass

    return RfidCrossVerification(cfg=cfg, registry=VehicleRegistry.from_seed(), persistence=_Store(),
                                 broadcaster=lambda *_: None,
                                 evidence=EvidenceStore(root=tmp_path / "ev", cfg=cfg),
                                 executor=_Inline())


def _b_sighting():
    return SightingDraft(incident_key="k", epc=_epc("B"), plate_norm="MH12BR7814", junction_id="J02",
                         reader_id="RFID_J02_01", first_seen_ts=53.85, last_seen_ts=58.05)


def test_service_default_is_off(tmp_path):
    service = _service(tmp_path)
    assert service.netra is None
    sighting = _b_sighting()
    service._netra_shadow(sighting, Suspect(vehicle_id="B"))
    assert sighting.netra is None


def test_service_shadow_agrees_with_registry_and_lands_in_payload(tmp_path, scenario):
    service = _service(tmp_path, netra_enabled=True, netra_calibration=str(CALIBRATION))
    jd = scenario["J02"]
    for read in jd.reports:
        service.buffer.add(read)
    for f in jd.frames:
        service.frames.add(f.camera_id, f.junction_id, f.timestamp_sim, f.jpeg, f.frame_no, f.vehicles)
    sighting = _b_sighting()
    service._netra_shadow(sighting, Suspect(epc=sighting.epc, vehicle_id="B"))
    assert sighting.netra["proposed_track"] == "B"
    assert sighting.netra["agrees"] is True
    assert sighting.netra["registry_vehicle_id"] == "B"
    assert service.counters["netra_assessments"] == 1 and service.counters["netra_errors"] == 0
    incident = SimpleNamespace(vehicles=[], incident_id="i1", run_id="r", crash_junction="J01",
                               crash_ts_sim=40.0)
    service._sighting_header = lambda inc, s: {}
    service._suspect_for = lambda inc, s: Suspect(vehicle_id="B")
    payload = service._result_payload(incident, sighting, {"status": "NOT_CONFIRMED"}, final=False)
    assert payload["netra"] is sighting.netra


# ---------------------------------------------------------------- real-run tooling

def test_geometry_from_a_carla_pose_matches_the_code_constants():
    from app.services.rfid.netra.geometry import geometry_from_pose
    # Member 1's camera_transform: camera = centre - forward*back - right*lateral
    for jid, yaw_deg in (("J01", 37.0), ("J02", -120.0), ("J03", 200.0)):
        g0 = camera_for(jid)
        yaw = math.radians(yaw_deg)
        f, r = (math.cos(yaw), math.sin(yaw)), (-math.sin(yaw), math.cos(yaw))
        centre = (-41.6, 82.6)
        cam = (centre[0] - f[0] * g0.back_m - r[0] * g0.lateral_m,
               centre[1] - f[1] * g0.back_m - r[1] * g0.lateral_m)
        pose = {"x": cam[0], "y": cam[1], "z": 5.0, "pitch": -15.0, "yaw": yaw_deg,
                "fov": 65.0, "width": 1280, "height": 720}
        g = geometry_from_pose(pose, centre)
        assert abs(g.back_m - g0.back_m) < 1e-6 and abs(g.lateral_m - g0.lateral_m) < 1e-6
        assert g.pitch_down_deg == 15.0 and g.height_m == 5.0


def _messages_from(data):
    """Rebuild the wire messages of a simulated run (what the recorder sees)."""
    out = []
    for jd in data.values():
        for r in jd.reports:
            out.append((r.last_seen_ts, {
                "type": "rfid_reading", "schema": "rfid_tag_report_v2", "run_id": r.run_id,
                "seq": r.seq, "reader_id": r.reader_id, "junction_id": r.junction_id,
                "antenna_id": "A1", "epc": r.epc, "rssi_dbm": r.peak_rssi,
                "tag_seen_count": r.count, "first_seen_ts": r.first_seen_ts,
                "last_seen_ts": r.last_seen_ts, "timestamp_sim": r.last_seen_ts, "frame": 0}))
        for f in jd.frames:
            out.append((f.timestamp_sim, {
                "type": "camera_frame", "timestamp_sim": f.timestamp_sim, "frame": f.frame_no,
                "camera_id": f.camera_id, "junction_id": f.junction_id, "encoding": "jpeg",
                "width": 1280, "height": 720, "has_number_plate_overlay": True,
                "image": "QUJD" * 50, "vehicles": f.vehicles}))
    return [m for _, m in sorted(out, key=lambda item: item[0])]


def test_recorder_strips_images_and_replay_rebuilds_the_run(tmp_path, scenario):
    import netra_replay as nr
    from app.services.stream_recorder import StreamRecorder

    rec = StreamRecorder(tmp_path / "rec.jsonl")
    messages = _messages_from(scenario)
    for m in messages:
        rec.record(m)
    rec.record({"type": "imu_reading", "timestamp_sim": 1.0})       # skipped by default
    rec.close()
    lines = (tmp_path / "rec.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(messages)
    assert '"image":' not in "".join(lines) and '"image_bytes":200' in lines[-1] + "".join(lines)

    segments = nr.load_segments(tmp_path / "rec.jsonl")
    assert len(segments) == 1
    for jid in ns.JUNCTIONS:
        assert len(segments[0][jid].reports) == len(scenario[jid].reports)
        assert len(segments[0][jid].frames) == len(scenario[jid].frames)
    assert segments[0]["J02"].truth[_epc("B")] == "B"            # registry: EPC -> vehicle
    rows = nse.evaluate(NetraShadow(None), segments[0])
    b = [r for r in rows if r["junction"] == "J02" and r["vehicle"] == "B"]
    assert b and b[0]["proposed_track"] == "B"


def test_replay_splits_runs_on_sim_time_backjump(tmp_path):
    import netra_replay as nr
    path = tmp_path / "two.jsonl"
    rows = []
    for ts in (10.0, 11.0, 12.0, 1.0, 2.0):
        rows.append({"rx": "", "msg": {"type": "camera_frame", "timestamp_sim": ts, "frame": 0,
                                       "camera_id": "CAM_J02_01", "junction_id": "J02",
                                       "vehicles": []}})
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    segments = nr.load_segments(path)
    assert [len(s["J02"].frames) for s in segments] == [3, 2]
