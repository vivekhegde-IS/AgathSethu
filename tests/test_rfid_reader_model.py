"""Unit tests for rfid_reader_model.py (no CARLA, no backend needed).

Run from the repository root:  python -m pytest tests/ -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rfid_reader_model import (  # noqa: E402
    RfidConfig,
    RfidReaderModel,
    camera_coverage_fraction,
    mean_rssi_dbm,
    nominal_range_m,
    read_probability,
    replay_trajectories,
    sample_rssi_dbm,
)


def _crossing(distance_scale: float = 1.0, speed_kmh: float = 20.0, steps: int = 400):
    """One vehicle driving straight through J01 at 8 m/s."""
    timestamps = [index * 0.05 for index in range(steps)]
    positions = {"A": [(-28.7 + index * 0.05 * 8 * distance_scale, 28.1) for index in range(steps)]}
    speeds = {"A": [speed_kmh] * steps}
    epcs = {"A": "E200001722110101A0B1"}
    return timestamps, positions, speeds, epcs


# ---------------- signal model ----------------

def test_mean_rssi_falls_with_distance():
    cfg = RfidConfig()
    values = [mean_rssi_dbm(d, cfg) for d in (1, 2, 5, 10, 20, 40)]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_rssi_is_bounded_at_the_reference_points():
    cfg = RfidConfig()
    assert mean_rssi_dbm(0.0, cfg) == cfg.reference_rssi_dbm       # floored at 1 m
    assert mean_rssi_dbm(1.0, cfg) == cfg.reference_rssi_dbm
    # mean RSSI equals the sensitivity floor at the nominal range
    assert mean_rssi_dbm(nominal_range_m(cfg), cfg) == pytest.approx(cfg.sensitivity_dbm, abs=1e-6)


def test_nominal_range_is_about_ten_metres():
    assert nominal_range_m(RfidConfig()) == pytest.approx(10.0, abs=0.1)


def test_read_probability_is_zero_below_the_sensitivity_floor():
    cfg = RfidConfig()
    assert read_probability(cfg.sensitivity_dbm - 0.1, 0.0, 1, cfg) == 0.0
    assert read_probability(cfg.sensitivity_dbm + 20.0, 0.0, 1, cfg) > 0.5


def test_sample_rssi_is_deterministic_for_a_seed():
    import random

    first = [sample_rssi_dbm(5.0, random.Random(3)) for _ in range(5)]
    second = [sample_rssi_dbm(5.0, random.Random(3)) for _ in range(5)]
    assert first == second
    assert first != [sample_rssi_dbm(5.0, random.Random(4)) for _ in range(5)]


def test_camera_sees_the_whole_read_zone():
    # The vision verification needs the junction camera to see a car anywhere
    # inside the ~10 m RFID read zone.
    assert camera_coverage_fraction(10.0) > 0.99


# ---------------- inventory model ----------------

def test_faster_vehicles_are_read_less():
    cfg = RfidConfig()
    rssi = mean_rssi_dbm(4.0, cfg)
    slow = read_probability(rssi, 10.0, 1, cfg)
    fast = read_probability(rssi, 90.0, 1, cfg)
    assert slow > fast


def test_anticollision_lowers_the_per_tag_read_rate():
    cfg = RfidConfig()
    rssi = mean_rssi_dbm(3.0, cfg)
    alone = read_probability(rssi, 0.0, 1, cfg)
    crowded = read_probability(rssi, 0.0, 4, cfg)
    assert crowded < alone


def test_no_reads_beyond_the_read_zone():
    # Far beyond the nominal range and with cross-reads off: never read.
    timestamps = [index * 0.05 for index in range(400)]
    positions = {"A": [(100.0, 28.1)] * 400}          # ~130 m from J01/J02/J03
    epcs = {"A": "E200001722110101A0B1"}
    reports, _ = replay_trajectories(timestamps, positions, epcs=epcs, seed=5)
    assert reports == []


def test_a_passing_vehicle_is_reported():
    timestamps, positions, speeds, epcs = _crossing()
    reports, truth = replay_trajectories(timestamps, positions, speeds=speeds,
                                        epcs=epcs, seed=11)
    assert reports, "a vehicle driving through the reader must be reported"
    assert {r["junction_id"] for r in reports} == {"J01"}
    assert all(r["type"] == "rfid_reading" for r in reports)
    assert all(r["schema"] == "rfid_tag_report_v2" for r in reports)
    assert all(r["epc"] == "E200001722110101A0B1" for r in reports)
    assert len(truth) == len(reports)


def test_v2_reports_do_not_leak_ground_truth():
    timestamps, positions, speeds, epcs = _crossing()
    reports, _ = replay_trajectories(timestamps, positions, speeds=speeds,
                                    epcs=epcs, seed=11)
    forbidden = {"plate_number", "vehicle_id", "distance_m", "speed_kmh", "confidence"}
    for report in reports:
        assert not (forbidden & set(report)), "a real reader cannot know these"


def test_sequence_is_monotonic_per_reader():
    timestamps, positions, speeds, epcs = _crossing()
    reports, _ = replay_trajectories(timestamps, positions, speeds=speeds,
                                    epcs=epcs, seed=11)
    per_reader: dict[str, list[int]] = {}
    for report in reports:
        per_reader.setdefault(report["reader_id"], []).append(report["seq"])
    for sequences in per_reader.values():
        assert sequences == sorted(sequences)
        assert len(set(sequences)) == len(sequences)


def test_report_interval_is_respected():
    cfg = RfidConfig()
    timestamps, positions, speeds, epcs = _crossing()
    reports, _ = replay_trajectories(timestamps, positions, speeds=speeds,
                                    epcs=epcs, seed=11, cfg=cfg)
    # Emission times are multiples of the interval (plus the first tick).
    for report in reports:
        assert report["timestamp_sim"] % cfg.report_interval_s == pytest.approx(0.0, abs=1e-6)
    # And never more often than one report per tag per interval per reader.
    keys = [(r["reader_id"], r["epc"], r["timestamp_sim"]) for r in reports]
    assert len(keys) == len(set(keys))


def test_reports_are_deterministic_for_a_fixed_seed():
    timestamps, positions, speeds, epcs = _crossing()
    first, truth_first = replay_trajectories(timestamps, positions, speeds=speeds,
                                            epcs=epcs, seed=1234)
    second, truth_second = replay_trajectories(timestamps, positions, speeds=speeds,
                                              epcs=epcs, seed=1234)
    third, _ = replay_trajectories(timestamps, positions, speeds=speeds,
                                  epcs=epcs, seed=4321)
    assert first == second and truth_first == truth_second
    assert first != third


def test_rssi_decreases_with_distance_along_the_track():
    timestamps, positions, speeds, epcs = _crossing()
    reports, truth = replay_trajectories(timestamps, positions, speeds=speeds,
                                        epcs=epcs, seed=11)
    distances = [row["true_distance_m"] for row in truth]
    rssis = [row["peak_rssi_dbm"] for row in truth]
    # only the reports while approaching the centre are expected to rise
    approaching = [i for i, d in enumerate(distances) if d < nominal_range_m(RfidConfig())]
    assert approaching, "the vehicle should be inside the zone at least once"
    paired = sorted(zip(distances, rssis))
    assert paired[0][1] >= paired[-1][1]


def test_missed_pass_suppresses_the_whole_pass_only():
    cfg = RfidConfig()
    timestamps, positions, speeds, _epcs = _crossing()
    # drive through the junction, then back again: two separate passes
    path = positions["A"] + positions["A"][::-1]
    speed = speeds["A"] + speeds["A"][::-1]
    step = timestamps[1] - timestamps[0]
    times = [index * step for index in range(len(path))]
    half = times[len(timestamps)]

    def run(miss: bool):
        model = RfidReaderModel(cfg=cfg, seed=11)
        if miss:
            model.miss_next_pass("J01", "E200001722110101A0B1")
        reports = []
        for index, timestamp in enumerate(times):
            step_reports, _ = model.step(timestamp, index, [{
                "vehicle_id": "A", "epc": "E200001722110101A0B1",
                "x": path[index][0], "y": path[index][1], "speed_kmh": speed[index]}])
            reports.extend(step_reports)
        return reports

    baseline = run(miss=False)
    assert any(r["last_seen_ts"] < half for r in baseline), "sanity: first pass is read"
    missed = run(miss=True)
    # nothing at all from the first pass (entry to exit) ...
    assert not any(r["last_seen_ts"] < half for r in missed)
    # ... and the next pass is read normally again
    assert any(r["last_seen_ts"] >= half for r in missed)


def test_pass_miss_probability_is_all_or_nothing_per_pass():
    timestamps, positions, speeds, epcs = _crossing()
    never, _ = replay_trajectories(timestamps, positions, speeds=speeds, epcs=epcs, seed=3,
                                   cfg=RfidConfig(pass_miss_prob=1.0))
    assert never == []
    always, _ = replay_trajectories(timestamps, positions, speeds=speeds, epcs=epcs, seed=3,
                                    cfg=RfidConfig(pass_miss_prob=0.0))
    assert always


def test_cross_reads_are_off_by_default_and_annotated_when_on():
    # A tag parked just outside the nominal zone: never read by default.
    timestamps = [index * 0.05 for index in range(200)]
    positions = {"A": [(-28.7 + 12.0, 28.1)] * 200}       # 12 m from J01
    epcs = {"A": "E200001722110101A0B1"}
    off, _ = replay_trajectories(timestamps, positions, epcs=epcs, seed=9)
    assert off == []

    cfg = RfidConfig(cross_read_enabled=True, cross_read_probability=1.0)
    on, truth = replay_trajectories(timestamps, positions, epcs=epcs, seed=9, cfg=cfg)
    assert on, "with cross-reads on and probability 1 a distant tag should appear"
    assert all(row["nearby_cross_read"] == 1 for row in truth)
