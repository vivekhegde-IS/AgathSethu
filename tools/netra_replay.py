"""Replay real CARLA recordings through NETRA: evaluate, or (re)calibrate.

Input: JSONL files written by the backend recorder (RFID_RECORD_PATH, see
app/services/stream_recorder.py), optionally with Member 1's run folder
(multimodal_evidence/) for the exact camera poses and reader positions.

Ground truth: in CARLA the camera box id IS the vehicle name (A-H) and every
EPC maps to one vehicle through the registry, so the correct track for a tag
is known without any extra file. NETRA itself never sees that mapping.

    # how does the current calibration do on real runs?
    python tools/netra_replay.py evaluate runtime/recordings/*.jsonl \
        --run-dir "<member1 OUT_DIR>/multimodal_evidence"

    # calibrate from real runs (calibration and held-out test recordings)
    python tools/netra_replay.py calibrate --cal rec1.jsonl rec2.jsonl rec3.jsonl \
        --test rec4.jsonl --run-dir "<...>/multimodal_evidence" \
        --out member3/backend/data/netra_calibration.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import netra_scenario_eval as nse  # noqa: E402
import netra_sim as ns  # noqa: E402

from app.services.rfid.netra.adapter import (  # noqa: E402
    nominal_reader,
    reader_to_dict,
    reads_from_reports,
    tracks_from_frames,
)
from app.services.rfid.netra.core import conf_vector, score, selective_risk_threshold, wrong_flags  # noqa: E402
from app.services.rfid.netra.geometry import (  # noqa: E402
    camera_for,
    geometry_from_pose,
    geometry_to_dict,
)
from app.services.rfid.netra.shadow import ENGINE_DEFAULTS, NetraShadow, make_engine  # noqa: E402
from app.services.rfid.normalize import parse_message  # noqa: E402
from app.services.rfid.registry import VehicleRegistry  # noqa: E402
from app.services.rfid.vision import FrameRef, parse_vehicle_boxes  # noqa: E402

RUN_SPACING_S = 100_000.0
BACKJUMP_S = 5.0


# ---------------------------------------------------------------- loading

def load_segments(path: Path) -> list[dict]:
    """One recording -> one {junction: JunctionData} per CARLA run inside it
    (a run ends when sim time jumps back by more than BACKJUMP_S)."""
    registry = VehicleRegistry.from_seed()
    segments, current, last_ts = [], None, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                msg = json.loads(line)["msg"]
            except (ValueError, KeyError, TypeError):
                continue
            kind = msg.get("type")
            if kind not in ("rfid_reading", "camera_frame"):
                continue
            ts = msg.get("timestamp_sim")
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            if current is None or ts < last_ts - BACKJUMP_S:
                current = {jid: ns.JunctionData(jid) for jid in ns.JUNCTIONS}
                segments.append(current)
                last_ts = ts
            last_ts = max(last_ts, ts)
            if kind == "rfid_reading":
                read = parse_message(msg)
                if read is None or read.junction_id not in current:
                    continue
                current[read.junction_id].reports.append(read)
                entry = registry.lookup_epc(read.epc)
                current[read.junction_id].truth[read.epc] = (
                    entry.sim_vehicle_id if entry is not None else None)
            else:
                jid = msg.get("junction_id")
                if jid not in current:
                    continue
                current[jid].frames.append(FrameRef(
                    str(msg.get("camera_id")), jid, ts, b"", msg.get("frame"),
                    parse_vehicle_boxes(msg.get("vehicles"))))
    return segments


def pooled(paths: list[Path]) -> dict:
    """Every run of every recording on one time axis (runs far apart)."""
    out = {jid: ns.JunctionData(jid) for jid in ns.JUNCTIONS}
    n = 0
    for path in paths:
        for segment in load_segments(path):
            shifted = ns.offset_run(segment, n * RUN_SPACING_S)
            n += 1
            for jid, jd in shifted.items():
                out[jid].reports.extend(jd.reports)
                out[jid].frames.extend(jd.frames)
                out[jid].truth.update(jd.truth)
    print(f"loaded {n} run(s) from {len(paths)} recording(s): " + ", ".join(
        f"{jid} {len(jd.reports)} reports / {len(jd.frames)} frames "
        f"({sum(1 for f in jd.frames if f.vehicles)} with boxes)" for jid, jd in out.items()))
    return out


def cameras_from_run_dir(run_dir: Path | None) -> dict:
    if run_dir is None:
        return {}
    poses = json.loads((run_dir / "camera_poses.json").read_text(encoding="utf-8"))
    readers = json.loads((run_dir / "rfid_reader_positions.json").read_text(encoding="utf-8"))["readers"]
    cams = {jid: geometry_from_pose(poses[jid], (readers[jid]["x"], readers[jid]["y"]))
            for jid in poses if jid in readers}
    for jid, g in sorted(cams.items()):
        default = camera_for(jid)
        print(f"{jid}: reader {g.back_m:.1f} m ahead / {g.lateral_m:+.1f} m right of the camera, "
              f"height {g.height_m:.1f} m, pitch {g.pitch_down_deg:.1f} deg down "
              f"(code constants: {default.back_m:.0f} / {default.lateral_m:+.0f})")
    return cams


# ---------------------------------------------------------------- modes

def _decisions(engine, jd, geometry):
    return engine.run(reads_from_reports(jd.reports, engine.slot), tracks_from_frames(jd.frames, geometry))


def _fmt(name, s):
    return (f"  {name:30s} n={s['n']:4d}  acc={s['accuracy']:.3f}  cov={s['coverage']:.3f}  "
            f"sel_err={s['sel_error']:.4f}  ({s['wrong']} wrong / {s['confirmed']} confirmed)")


def cmd_evaluate(args) -> int:
    shadow = NetraShadow.from_file(args.calibration)
    cams = cameras_from_run_dir(args.run_dir)
    if cams:
        shadow.cameras = cams
    data = pooled(args.recordings)
    rows = nse.evaluate(shadow, data)
    summary = nse.summarize(rows)
    print(f"\ncalibrated={shadow.calibrated} threshold={shadow.threshold}")
    print(json.dumps(summary, indent=2))
    by_j = Counter((r["junction"], r["status"]) for r in rows)
    for (jid, status), n in sorted(by_j.items()):
        print(f"  {jid} {status:24s} {n}")
    wrong = [r for r in rows if r["proposed_track"] is not None and r["proposed_track"] != r["vehicle"]]
    for r in wrong[:20]:
        print(f"  WRONG {r['junction']} t={r['t0']:.1f}-{r['t1']:.1f} tag of {r['vehicle']} -> "
              f"{r['proposed_track']} ({r['status']}, conf {r['confidence']})")
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return 0


def cmd_calibrate(args) -> int:
    cams = cameras_from_run_dir(args.run_dir)
    cal = pooled(args.cal)
    test = pooled(args.test) if args.test else None
    readers, cal_dec, cal_truth, test_dec, test_truth = {}, [], {}, [], {}
    for jid in ns.JUNCTIONS:
        jd = cal[jid]
        if not jd.reports or not any(f.vehicles for f in jd.frames):
            print(f"{jid}: no RFID reports or no camera boxes - skipped")
            continue
        geometry = camera_for(jid, cams)
        rid = jd.reports[0].reader_id
        engine = make_engine({rid: nominal_reader(rid, geometry)})
        engine.self_calibrate(reads_from_reports(jd.reports, engine.slot),
                              tracks_from_frames(jd.frames, geometry),
                              iters=args.em_iters, update_tau=False)
        readers[jid] = reader_to_dict(engine.readers[rid])
        cal_dec += _decisions(engine, jd, geometry)
        cal_truth.update(jd.truth)
        if test is not None and test[jid].reports:
            test_dec += _decisions(engine, test[jid], geometry)
            test_truth.update(test[jid].truth)
    thr = selective_risk_threshold(conf_vector(cal_dec), wrong_flags(cal_dec, cal_truth),
                                   alpha=args.alpha, delta=args.delta)
    report = {"calibration_accept_all": score(cal_dec, cal_truth, 0.0),
              "calibration_certified": score(cal_dec, cal_truth, thr)}
    if test_dec:
        report["test_accept_all"] = score(test_dec, test_truth, 0.0)
        report["test_certified"] = score(test_dec, test_truth, thr)
    print(f"\nthreshold (alpha={args.alpha}, delta={args.delta}): "
          f"{'none certifiable (need more confirmed passes)' if thr == float('inf') else round(thr, 4)}")
    for name, s in report.items():
        print(_fmt(name, s))
    out = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "real CARLA recordings: " + ", ".join(p.name for p in args.cal),
        "alpha": args.alpha, "delta": args.delta,
        "threshold": thr if thr != float("inf") else None,
        "engine": {k: (list(map(float, v)) if isinstance(v, tuple) else v)
                   for k, v in ENGINE_DEFAULTS.items()},
        "readers": readers,
        "cameras": {jid: geometry_to_dict(g) for jid, g in cams.items()},
        "report": {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                   for k, v in report.items()},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("recordings", type=Path, nargs="+")
    ev.add_argument("--calibration", type=Path, default=Path(nse.DEFAULT_CONFIG.netra_calibration))
    ev.add_argument("--run-dir", type=Path)
    ev.add_argument("--json", type=Path)
    ca = sub.add_parser("calibrate")
    ca.add_argument("--cal", type=Path, nargs="+", required=True)
    ca.add_argument("--test", type=Path, nargs="*")
    ca.add_argument("--run-dir", type=Path)
    ca.add_argument("--alpha", type=float, default=0.02)
    ca.add_argument("--delta", type=float, default=0.1)
    ca.add_argument("--em-iters", type=int, default=4)
    ca.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    return cmd_evaluate(args) if args.cmd == "evaluate" else cmd_calibrate(args)


if __name__ == "__main__":
    raise SystemExit(main())
