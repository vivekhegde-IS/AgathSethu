"""Calibrate NETRA for the junction readers and certify its confirmation threshold.

1. Self-calibration (EM, unlabelled): per junction, the read-rate field is
   learned from the calibration runs, starting from the installer guess.
   Reader clocks equal the sim clock in CARLA, so clock offsets are not fitted.
2. Selection-conditioned risk control (labelled calibration runs): the lowest
   confidence threshold whose Clopper-Pearson upper bound on the error among
   confirmed identities is <= alpha (prob. >= 1 - delta, i.i.d. passes).
3. Held-out test runs: coverage / error at that threshold, reported as is.

Data is synthetic (tools/netra_sim.py): the guarantee holds for deployment
traffic only insofar as it resembles the calibration traffic.

Usage:
    python tools/netra_calibrate.py                      # writes member3/backend/data/netra_calibration_synthetic.json
    python tools/netra_calibrate.py --alpha 0.05 --out other.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import netra_sim as ns  # noqa: E402

from app.services.rfid.netra.adapter import (  # noqa: E402
    nominal_reader,
    reader_to_dict,
    reads_from_reports,
    tracks_from_frames,
)
from app.services.rfid.netra.core import (  # noqa: E402
    conf_vector,
    score,
    selective_risk_threshold,
    wrong_flags,
)
from app.services.rfid.netra.geometry import camera_for  # noqa: E402
from app.services.rfid.netra.shadow import ENGINE_DEFAULTS, make_engine  # noqa: E402

# The backend default (netra_calibration.json) is the real-CARLA calibration from
# claude try/export_backend_calibration.py; this synthetic one must not overwrite it.
DEFAULT_OUT = ROOT / "member3" / "backend" / "data" / "netra_calibration_synthetic.json"
RUN_SPACING_S = 10_000.0


def pooled(seeds, duration):
    """{junction: (reports, frames, truth)} for several runs on one time axis."""
    out = {jid: ([], [], {}) for jid in ns.JUNCTIONS}
    for n, seed in enumerate(seeds):
        run = ns.offset_run(ns.random_traffic(seed, duration=duration), n * RUN_SPACING_S)
        for jid, jd in run.items():
            out[jid][0].extend(jd.reports)
            out[jid][1].extend(jd.frames)
            out[jid][2].update(jd.truth)
    return out


def decisions(engine, reports, frames, jid):
    return engine.run(reads_from_reports(reports, engine.slot),
                      tracks_from_frames(frames, camera_for(jid)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha", type=float, default=0.02)
    ap.add_argument("--delta", type=float, default=0.1)
    ap.add_argument("--cal-seeds", type=int, nargs="+", default=[101, 102, 103, 104, 105, 106])
    ap.add_argument("--test-seeds", type=int, nargs="+", default=[201, 202, 203])
    ap.add_argument("--duration", type=float, default=300.0)
    ap.add_argument("--em-iters", type=int, default=4)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    t_start = time.time()
    cal = pooled(args.cal_seeds, args.duration)
    test = pooled(args.test_seeds, args.duration)
    print(f"simulated {len(args.cal_seeds)} calibration + {len(args.test_seeds)} test runs "
          f"of {args.duration:.0f} s ({time.time() - t_start:.0f} s)")

    readers, cal_dec, cal_truth, test_dec, test_truth = {}, [], {}, {}, {}
    nominal_dec = {}
    for jid in ns.JUNCTIONS:
        reports, frames, truth = cal[jid]
        rid = reports[0].reader_id
        geometry = camera_for(jid)
        nominal = make_engine({rid: nominal_reader(rid, geometry)})
        engine = make_engine({rid: nominal_reader(rid, geometry)})
        t0 = time.time()
        engine.self_calibrate(reads_from_reports(reports, engine.slot),
                              tracks_from_frames(frames, geometry),
                              iters=args.em_iters, update_tau=False)
        readers[jid] = reader_to_dict(engine.readers[rid])
        print(f"{jid}: EM done ({time.time() - t0:.0f} s), field w = "
              f"{[round(float(v), 2) for v in engine.readers[rid].w]}")
        cal_dec += decisions(engine, reports, frames, jid)
        cal_truth.update(truth)
        t_reports, t_frames, t_truth = test[jid]
        test_dec[jid] = decisions(engine, t_reports, t_frames, jid)
        nominal_dec[jid] = decisions(nominal, t_reports, t_frames, jid)
        test_truth.update(t_truth)

    thr = selective_risk_threshold(conf_vector(cal_dec), wrong_flags(cal_dec, cal_truth),
                                   alpha=args.alpha, delta=args.delta)
    all_test = [d for jid in ns.JUNCTIONS for d in test_dec[jid]]
    all_nominal = [d for jid in ns.JUNCTIONS for d in nominal_dec[jid]]
    rnd = lambda s: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()}  # noqa: E731
    report = {
        "calibration_accept_all": rnd(score(cal_dec, cal_truth, 0.0)),
        "calibration_certified": rnd(score(cal_dec, cal_truth, thr)),
        "test_accept_all": rnd(score(all_test, test_truth, 0.0)),
        "test_certified": rnd(score(all_test, test_truth, thr)),
        "test_installer_guess_accept_all": rnd(score(all_nominal, test_truth, 0.0)),
        "test_certified_by_junction": {jid: rnd(score(test_dec[jid], test_truth, thr))
                                       for jid in ns.JUNCTIONS},
    }
    out = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "synthetic: tools/netra_sim.py random_traffic (rfid_reader_model v2 + projected "
                  "camera boxes); not real hardware",
        "alpha": args.alpha, "delta": args.delta,
        "threshold": thr if thr != float("inf") else None,
        "engine": {k: (list(map(float, v)) if isinstance(v, tuple) else v)
                   for k, v in ENGINE_DEFAULTS.items()},
        "readers": readers,
        "cal_seeds": args.cal_seeds, "test_seeds": args.test_seeds, "duration_s": args.duration,
        "report": report,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(f"\nthreshold (alpha={args.alpha}, delta={args.delta}): "
          f"{'none certifiable' if thr == float('inf') else round(thr, 4)}")
    for name, s in report.items():
        if name != "test_certified_by_junction":
            print(f"  {name:32s} n={s['n']:4d}  acc={s['accuracy']:.3f}  cov={s['coverage']:.3f}  "
                  f"sel_err={s['sel_error']:.4f}  ({s['wrong']} wrong / {s['confirmed']} confirmed)")
    for jid, s in report["test_certified_by_junction"].items():
        print(f"  test certified {jid:17s} n={s['n']:4d}  cov={s['coverage']:.3f}  "
              f"sel_err={s['sel_error']:.4f}")
    print(f"\nwrote {args.out} ({time.time() - t_start:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
