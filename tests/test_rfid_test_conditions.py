"""Optional RFID test conditions in rfid_reader_model.py (all default-off)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import scenario as sc  # noqa: E402
from rfid_reader_model import RfidConfig, RfidReaderModel, antenna_layout  # noqa: E402


def _run(cfg, seed=3, until=120.0):
    model = RfidReaderModel(cfg=cfg, seed=seed)
    reports, truth = [], []
    for i, t in enumerate(sc.timeline(until)):
        r, g = model.step(t, i, sc.vehicles_at(t))
        reports += r
        truth += g
    return model, reports, truth


def test_defaults_have_one_antenna_and_no_extras():
    model, reports, truth = _run(RfidConfig())
    assert {r["reader_id"] for r in reports} <= {"RFID_J01_01", "RFID_J02_01", "RFID_J03_01"}
    assert all(r["antenna_id"] == "A1" for r in reports)
    assert not any(g["vehicle_id"].startswith("GHOST") for g in truth)
    assert len(model.antennas) == 3


def test_antennas_per_junction_are_separate_readers_on_a_circle():
    cfg = RfidConfig(antennas_per_junction=4, antenna_radius_m=6.0)
    layout = antenna_layout(sc.JUNCTION_WORLD, cfg)
    j2 = [a for a in layout if a["junction"] == "J02"]
    assert [a["reader_id"] for a in j2] == [f"RFID_J02_0{i}" for i in range(1, 5)]
    cx, cy = sc.JUNCTION_WORLD["J02"]
    assert all(abs(math.hypot(a["x"] - cx, a["y"] - cy) - 6.0) < 1e-9 for a in j2)
    _, reports, _ = _run(cfg)
    assert len({r["reader_id"] for r in reports if r["junction_id"] == "J02"}) >= 2
    seqs = {}
    for r in reports:                                     # seq is per antenna
        assert r["seq"] == seqs.get(r["reader_id"], 0) + 1
        seqs[r["reader_id"]] = r["seq"]


def test_ghost_tags_are_read_and_labelled():
    _, reports, truth = _run(RfidConfig(ghost_tags_per_junction=2, ghost_distance_m=6.0), until=60.0)
    ghosts = {g["epc"]: g["vehicle_id"] for g in truth if g["vehicle_id"].startswith("GHOST")}
    assert ghosts and all(epc.startswith("E20000172211EE") and len(epc) == 20 for epc in ghosts)
    assert {v.split("_")[1] for v in ghosts.values()} <= {"J01", "J02", "J03"}
    assert any(r["epc"] in ghosts for r in reports)


def test_clock_offsets_shift_report_times_only():
    base = _run(RfidConfig())[1]
    shifted = _run(RfidConfig(clock_offsets_s=json.dumps({"J02": 0.4})))[1]
    assert len(base) == len(shifted)
    for a, b in zip(base, shifted):
        off = 0.4 if a["junction_id"] == "J02" else 0.0
        assert abs(b["first_seen_ts"] - a["first_seen_ts"] - off) < 1e-6
        assert abs(b["timestamp_sim"] - a["timestamp_sim"] - off) < 1e-6
        assert b["epc"] == a["epc"]


def test_positions_file_moves_readers_and_is_logged(tmp_path, monkeypatch):
    path = tmp_path / "pos.json"
    path.write_text(json.dumps({"readers": {"J01": {"x": -20.0, "y": 30.0}}}), encoding="utf-8")
    monkeypatch.setenv("RFID_READER_POSITIONS_FILE", str(path))
    monkeypatch.setenv("RFID_ANTENNAS_PER_JUNCTION", "2")
    monkeypatch.setenv("RFID_GHOST_TAGS_PER_JUNCTION", "1")
    cfg = RfidConfig.from_env()
    assert json.loads(cfg.reader_positions) == {"J01": {"x": -20.0, "y": 30.0}}
    assert cfg.antennas_per_junction == 2 and cfg.ghost_tags_per_junction == 1
    model = RfidReaderModel(cfg=cfg, seed=1)
    assert model.reader_position("J01") == (-20.0, 30.0)
    assert model.reader_position("J02") == sc.JUNCTION_WORLD["J02"]
    assert "reader_positions" in cfg.as_dict()
