"""NETRA shadow assessment on the A-H acceptance scenario.

For every RFID pass of every tag at every junction, runs ``NetraShadow.assess``
with the windows the service uses (reads +/- netra_reads_margin_s, frames
over [first - vision_window_before_s, last + vision_window_after_s]) and
compares NETRA's answer with the ground truth (the tag's own vehicle).

Usage:
    python tools/netra_scenario_eval.py [--calibration PATH] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import netra_sim as ns  # noqa: E402

from app.services.rfid.config import DEFAULT_CONFIG  # noqa: E402
from app.services.rfid.netra.shadow import NetraShadow  # noqa: E402

DEFAULT_CAL = Path(DEFAULT_CONFIG.netra_calibration).with_name("netra_calibration_synthetic.json")  # synthetic scenario


def evaluate(shadow: NetraShadow, data: dict | None = None, cfg=DEFAULT_CONFIG) -> list[dict]:
    data = data or ns.acceptance_scenario()
    rows = []
    for jid, jd in data.items():
        if not jd.reports:
            continue
        for epc, t0, t1 in sorted(_passes(jd.reports), key=lambda p: p[1]):
            start, end = t0 - cfg.vision_window_before_s, t1 + cfg.vision_window_after_s
            m = cfg.netra_reads_margin_s
            reports = [r for r in jd.reports
                       if r.last_seen_ts >= start - m and r.first_seen_ts <= end + m]
            frames = [f for f in jd.frames if start <= f.timestamp_sim <= end]
            res = shadow.assess(epc, jid, t0, t1, reports, frames)
            truth = jd.truth.get(epc)
            visible = any(v["vehicle_id"] == truth for f in frames for v in (f.vehicles or []))
            rows.append({"junction": jid, "epc": epc, "vehicle": truth, "t0": round(t0, 2),
                         "t1": round(t1, 2), "visible": visible, **{k: res.get(k) for k in (
                             "status", "proposed_track", "track_id", "confidence", "null_kind",
                             "n_reads", "n_tracks")}})
    return rows


def _passes(reports, gap: float = 20.0):
    """(epc, first, last) per tag pass: reads further apart than gap split."""
    by_epc = {}
    for r in sorted(reports, key=lambda r: r.first_seen_ts):
        by_epc.setdefault(r.epc, []).append(r)
    out = []
    for epc, items in by_epc.items():
        t0, t1 = items[0].first_seen_ts, items[0].last_seen_ts
        for r in items[1:]:
            if r.first_seen_ts - t1 > gap or r.last_seen_ts - t0 > 30.0:
                out.append((epc, t0, t1))
                t0 = r.first_seen_ts
            t1 = max(t1, r.last_seen_ts)
        out.append((epc, t0, t1))
    return out


def summarize(rows: list[dict]) -> dict:
    proposed = [r for r in rows if r["proposed_track"] is not None]
    confirmed = [r for r in rows if r["track_id"] is not None]
    return {
        "passes": len(rows),
        "visible_passes": sum(r["visible"] for r in rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "proposed": len(proposed),
        "proposed_correct": sum(r["proposed_track"] == r["vehicle"] for r in proposed),
        "confirmed": len(confirmed),
        "confirmed_correct": sum(r["track_id"] == r["vehicle"] for r in confirmed),
        "visible_but_not_proposed": sum(r["visible"] and r["proposed_track"] is None for r in rows),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", type=Path, default=DEFAULT_CAL)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    shadow = NetraShadow.from_file(args.calibration)
    rows = evaluate(shadow)
    print(f"calibrated={shadow.calibrated} threshold={shadow.threshold}")
    print(f"{'jn':4} {'veh':3} {'t0':>7} {'t1':>7} {'vis':3} {'status':24} {'proposed':8} {'conf':>6} reads")
    for r in rows:
        print(f"{r['junction']:4} {r['vehicle'] or '-':3} {r['t0']:7.2f} {r['t1']:7.2f} "
              f"{'y' if r['visible'] else 'n':3} {r['status']:24} {str(r['proposed_track']):8} "
              f"{(r['confidence'] if r['confidence'] is not None else float('nan')):6.3f} {r['n_reads']}")
    summary = summarize(rows)
    print(json.dumps(summary, indent=2))
    if args.json:
        args.json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
