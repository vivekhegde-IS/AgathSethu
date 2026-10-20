"""Part 1 acceptance for the realistic RFID stream.

Runs the shared reader model over the demo scenario and prints:

  * a per-junction table: reports, distinct EPCs, report rate, RSSI range
  * a comparison against the legacy per-read stream (same trajectories)
  * confirmation that every car passing a junction produces at least one report
  * determinism of the v2 stream for a fixed seed

It also writes the artefacts an offline reviewer can inspect:
  runtime/rfid_acceptance/rfid_reports_v2.jsonl
  runtime/rfid_acceptance/rfid_readings.csv         (v2 rows, backend-shaped)
  runtime/rfid_acceptance/rfid_ground_truth.csv
  runtime/rfid_acceptance/rfid_readings_legacy.jsonl

Run from the repository root:
    python tools/rfid_acceptance.py
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import scenario  # noqa: E402
from rfid_reader_model import (  # noqa: E402
    RfidConfig,
    RfidReaderModel,
    nominal_range_m,
)

OUT_DIR = ROOT / "runtime" / "rfid_acceptance"

# Legacy constants copied from vivek_fb.py so the comparison is apples-to-apples.
LEGACY_READ_RADIUS_M = 18.0
LEGACY_MIN_INTERVAL_S = 0.25
LEGACY_READ_PROBABILITY = 0.98


def run_v2(cfg: RfidConfig, seed: int, times: list[float]):
    model = RfidReaderModel(cfg=cfg, seed=seed)
    reports, truth = [], []
    for index, timestamp in enumerate(times):
        step_reports, step_truth = model.step(timestamp, index, scenario.vehicles_at(timestamp))
        reports.extend(step_reports)
        truth.extend(step_truth)
    return reports, truth


def run_legacy(times: list[float], seed: int):
    """The pre-existing simulation: flat 98% per-read, 0.25 s, 18 m."""
    rng = random.Random(seed)
    last: dict[tuple[str, str], float] = {}
    messages = []
    seen_pairs = set()
    for index, timestamp in enumerate(times):
        for junction_id, (jx, jy) in scenario.JUNCTION_WORLD.items():
            reader_id = f"RFID_J{int(junction_id[1:]):02d}_01"
            for vehicle in scenario.vehicles_at(timestamp):
                distance = math.hypot(vehicle["x"] - jx, vehicle["y"] - jy)
                if distance > LEGACY_READ_RADIUS_M:
                    continue
                key = (vehicle["vehicle_id"], junction_id)
                previous = last.get(key)
                if previous is not None and timestamp - previous < LEGACY_MIN_INTERVAL_S:
                    continue
                last[key] = timestamp
                if rng.random() > LEGACY_READ_PROBABILITY:
                    continue
                confidence = max(0.50, 1.0 - (distance / LEGACY_READ_RADIUS_M) * 0.25)
                seen_pairs.add((vehicle["vehicle_id"], junction_id))
                messages.append({
                    "type": "rfid_reading",
                    "timestamp_sim": round(timestamp, 6),
                    "frame": index,
                    "event_id": f"MM-{len(messages) + 1:09d}",
                    "junction_id": junction_id,
                    "reader_id": reader_id,
                    "vehicle_id": vehicle["vehicle_id"],
                    "plate_number": scenario.PLATE_NUMBERS[vehicle["vehicle_id"]],
                    "epc": vehicle["epc"],
                    "distance_m": round(distance, 6),
                    "speed_kmh": round(vehicle["speed_kmh"], 6),
                    "confidence": round(confidence, 6),
                    "status": "READ",
                })
    return messages, seen_pairs


def per_junction_table(reports: list[dict], duration_s: float) -> list[dict]:
    buckets = defaultdict(lambda: {"reports": 0, "epcs": Counter(), "rssi": []})
    for report in reports:
        bucket = buckets[report["junction_id"]]
        bucket["reports"] += 1
        bucket["epcs"][report["epc"]] += 1
        bucket["rssi"].append(report["rssi_dbm"])
    rows = []
    for junction_id in sorted(buckets):
        bucket = buckets[junction_id]
        rows.append({
            "junction_id": junction_id,
            "reports": bucket["reports"],
            "distinct_epcs": len(bucket["epcs"]),
            "reports_per_s": round(bucket["reports"] / duration_s, 3),
            "rssi_min": min(bucket["rssi"]),
            "rssi_max": max(bucket["rssi"]),
            "rssi_mean": round(sum(bucket["rssi"]) / len(bucket["rssi"]), 2),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--duration", type=float, default=120.0)
    parser.add_argument("--seed", type=int, default=RfidConfig.seed)
    args = parser.parse_args(argv)

    times = scenario.timeline(args.duration)
    cfg = RfidConfig(seed=args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    reports, truth = run_v2(cfg, args.seed, times)
    legacy, _legacy_pairs = run_legacy(times, args.seed)

    # ---- determinism ----
    repeat, repeat_truth = run_v2(cfg, args.seed, times)
    identical = repeat == reports and repeat_truth == truth
    different_seed, _ = run_v2(RfidConfig(seed=args.seed + 1), args.seed + 1, times)
    seed_sensitive = different_seed != reports

    # ---- every car passing a junction must be reported ----
    v2_junctions = defaultdict(set)
    for report in reports:
        v2_junctions[report["epc"]].add(report["junction_id"])
    legacy_junctions = defaultdict(set)
    for message in legacy:
        legacy_junctions[message["epc"]].add(message["junction_id"])

    expected = defaultdict(set)
    for junction_id, (jx, jy) in scenario.JUNCTION_WORLD.items():
        for timestamp in times:
            for vehicle in scenario.vehicles_at(timestamp):
                if math.hypot(vehicle["x"] - jx, vehicle["y"] - jy) <= nominal_range_m(cfg):
                    expected[vehicle["epc"]].add(junction_id)

    missing = {
        scenario.VEHICLE_IDS[[scenario.EPCS[v] for v in scenario.VEHICLE_IDS].index(epc)]: sorted(
            junction for junction in junctions if junction not in v2_junctions.get(epc, set())
        )
        for epc, junctions in expected.items()
    }
    missing = {name: junctions for name, junctions in missing.items() if junctions}

    # ---- artefacts ----
    (OUT_DIR / "rfid_reports_v2.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in reports), encoding="utf-8")
    (OUT_DIR / "rfid_readings_legacy.jsonl").write_text(
        "".join(json.dumps(m) + "\n" for m in legacy), encoding="utf-8")
    with (OUT_DIR / "rfid_readings.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["run_id", "seq", "reader_id", "junction_id", "antenna_id", "epc",
                  "rssi_dbm", "tag_seen_count", "first_seen_ts", "last_seen_ts",
                  "timestamp_sim", "frame"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            writer.writerow({key: report.get(key) for key in fields})
    with (OUT_DIR / "rfid_ground_truth.csv").open("w", newline="", encoding="utf-8") as handle:
        fields = ["reader_id", "seq", "epc", "vehicle_id", "true_distance_m",
                  "speed_kmh", "peak_rssi_dbm", "tag_seen_count", "nearby_cross_read"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(truth)

    # ---- report ----
    print("=" * 78)
    print("PART 1 ACCEPTANCE — realistic RFID stream (v2 tag reports)")
    print("=" * 78)
    print(f"scenario      : 8 vehicles, A+B collide at {scenario.CRASH_JUNCTION} "
          f"t={scenario.CRASH_TIME_S:.0f}s, B escapes via J02/J03")
    print(f"duration      : {args.duration:.0f}s sim time, {len(times)} ticks at 20 Hz")
    print(f"config        : inventory {cfg.inventory_hz:.0f} Hz, report every "
          f"{cfg.report_interval_s}s, nominal range {nominal_range_m(cfg):.1f} m, "
          f"sensitivity {cfg.sensitivity_dbm:.0f} dBm, seed {args.seed}")
    print()
    print("per-junction (v2):")
    print(f"  {'junction':9s} {'reports':>8s} {'EPCs':>5s} {'reports/s':>10s} "
          f"{'RSSI min':>9s} {'RSSI max':>9s} {'RSSI mean':>10s}")
    for row in per_junction_table(reports, args.duration):
        print(f"  {row['junction_id']:9s} {row['reports']:>8d} {row['distinct_epcs']:>5d} "
              f"{row['reports_per_s']:>10.3f} {row['rssi_min']:>9.2f} {row['rssi_max']:>9.2f} "
              f"{row['rssi_mean']:>10.2f}")
    print()
    print("legacy vs v2 (same trajectories):")
    print(f"  {'':16s} {'messages':>9s} {'distinct EPCs':>14s} {'per pass':>9s}")
    for label, messages in (("legacy per-read", legacy), ("v2 tag reports", reports)):
        epcs = {m["epc"] for m in messages}
        passes = len({(m["junction_id"], m["epc"]) for m in messages})
        per_pass = (len(messages) / passes) if passes else 0.0
        print(f"  {label:16s} {len(messages):>9d} {len(epcs):>14d} {per_pass:>9.1f}")
    print(f"  legacy carries plate/vehicle/distance: "
          f"{'plate_number' in (legacy[0] if legacy else {})}")
    print(f"  v2 carries plate/vehicle/distance    : "
          f"{bool({'plate_number', 'vehicle_id', 'distance_m'} & set(reports[0] if reports else {}))}")
    print()
    print("every car inside a junction read zone has at least one v2 report:")
    print(f"  cars expected at a junction : {len(expected)}")
    print(f"  cars with a v2 report       : {len(v2_junctions)}")
    print(f"  cars with a LEGACY read     : {len(legacy_junctions)}")
    if missing:
        for name, junctions in sorted(missing.items()):
            print(f"  MISSING: {name} at {junctions}")
    else:
        print("  result                      : PASS (no car missed)")
    print()
    print("determinism:")
    print(f"  same seed -> identical stream : {identical}")
    print(f"  different seed -> different   : {seed_sensitive}")
    print()
    print(f"artefacts in {OUT_DIR}")
    print("=" * 78)

    return 0 if (identical and seed_sensitive and not missing) else 1


if __name__ == "__main__":
    sys.exit(main())
