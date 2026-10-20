"""Replay backend recordings through the LIVE NETRA path (netra/live.py).

Every message of a recording is fed, in arrival order, to ``NetraLive`` exactly
as the service does (rfid_reading -> ingest_report, vehicle_boxes /
camera_frame boxes -> ingest_boxes). Each tag pass (reads of one EPC at one
junction, split by a 20 s gap or a 30 s cap - the engine's own pass rule) is
assessed once sim time has moved ``--delay`` seconds past its last read, with
only the data received up to then. Clock offsets are therefore estimated
online, from past traffic only.

Ground truth: EPC -> vehicle from the registry; the box id is the vehicle name.
A proposal is wrong unless it is the tag's own vehicle and that vehicle was in
view during the pass (+- 2 s), as in the offline analysis.

--detector-mask (claude try/detector_masks.py output, one file per junction of
ONE run - so pass one recording) keeps a ground-truth box only where the real
detector found that car on the nearest sampled video frame; camera_frame boxes
are then dropped. "In view" for the truth still uses all ground-truth boxes.
--fragment-gap S additionally gives a car a new track id after S seconds
without a kept box (a tracker that loses the identity; NETRA itself already
splits tracks after 2 s).

    python tools/netra_live_replay.py --recordings "<dir or jsonl>" ... \
        --runs-dir "<Member 1 session folder>" ... \
        [--calibration member3/backend/data/netra_calibration.json] [--delay 20] [--json out.json]
        [--detector-mask "claude try/detector_masks/run_34_J0*.json"] [--fragment-gap 0.5]
"""

from __future__ import annotations

import argparse
import bisect
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "member3" / "backend"))

from scipy.stats import beta as beta_dist  # noqa: E402

from app.services.rfid.config import DEFAULT_CONFIG  # noqa: E402
from app.services.rfid.netra.adapter import track_vehicle  # noqa: E402
from app.services.rfid.netra.live import NetraLive  # noqa: E402
from app.services.rfid.netra.shadow import STATUS_CONFIRMED, NetraShadow  # noqa: E402
from app.services.rfid.normalize import parse_message  # noqa: E402
from app.services.rfid.registry import VehicleRegistry  # noqa: E402
from app.services.rfid.vision import parse_vehicle_boxes  # noqa: E402

PASS_GAP_S, PASS_MAX_S, VIS_PAD_S, BACKJUMP_S = 20.0, 30.0, 2.0, 5.0


def cp_upper(k: int, n: int, level: float = 0.9) -> float | None:
    if n == 0:
        return None
    return 1.0 if k >= n else float(beta_dist.ppf(level, k + 1, n - k))


def run_index(run_dirs: list[Path]) -> dict:
    """run_id -> (session folder, run name) from Member 1's rfid_reader_positions.json."""
    out = {}
    for d in run_dirs:
        for p in sorted(d.rglob("rfid_reader_positions.json")):
            try:
                rid = json.loads(p.read_text(encoding="utf-8-sig")).get("run_id")
            except (OSError, ValueError):
                continue
            if rid:
                out[rid] = (d.name, p.parent.name)
    return out


def recording_files(paths: list[Path]) -> list[Path]:
    files = []
    for p in paths:
        files += sorted(p.rglob("carla_stream_*.jsonl")) if p.is_dir() else [p]
    return [f for f in files if f.stat().st_size > 0]


class DetectorMask:
    """Per junction: sampled CARLA frames -> vehicle ids the detector found."""

    def __init__(self, files, fragment_gap=None):
        self.frames, self.found, self.every = {}, {}, {}
        for f in files:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            items = sorted((int(k), set(v)) for k, v in d["frames"].items())
            self.frames[d["junction"]] = [k for k, _ in items]
            self.found[d["junction"]] = [v for _, v in items]
            self.every[d["junction"]] = int(d["every"])
        self.fragment_gap = fragment_gap
        self.last_kept, self.fragment = {}, defaultdict(int)
        self.counters = defaultdict(int)

    def reset(self):
        self.last_kept.clear()
        self.fragment.clear()

    def apply(self, jid, frame, t, vehicles):
        fr = self.frames.get(jid)
        self.counters["gt_boxes"] += len(vehicles)
        if not fr or frame is None:
            self.counters["unsampled_boxes"] += len(vehicles)
            return []
        k = bisect.bisect_left(fr, frame)
        best = min((i for i in (k - 1, k) if 0 <= i < len(fr)), key=lambda i: abs(fr[i] - frame))
        if abs(fr[best] - frame) > self.every[jid]:
            self.counters["unsampled_boxes"] += len(vehicles)
            return []
        found, kept = self.found[jid][best], []
        for v in vehicles:
            vid = v["vehicle_id"]
            if vid not in found:
                continue
            if self.fragment_gap is not None:
                key = (jid, vid)
                last = self.last_kept.get(key)
                if last is not None and t - last > self.fragment_gap:
                    self.fragment[key] += 1
                self.last_kept[key] = t
                if self.fragment[key]:
                    v = dict(v, vehicle_id=f"{vid}#t{self.fragment[key]}")
            kept.append(v)
        self.counters["kept_boxes"] += len(kept)
        return kept


class Segment:
    """One CARLA run inside a recording: a fresh NetraLive, pass bookkeeping, truth."""

    def __init__(self, shadow, delay):
        self.live = NetraLive(shadow, history_s=DEFAULT_CONFIG.netra_history_s,
                              reads_margin_s=DEFAULT_CONFIG.netra_reads_margin_s)
        self.delay = delay
        self.open = {}                     # (jid, epc) -> [t0, t1]
        self.due = []                      # closed passes waiting for the delay
        self.box_t = defaultdict(list)     # jid -> timestamps (visibility check)
        self.box_ids = defaultdict(list)
        self.run_ids = set()
        self.now = None
        self.seen = set()
        self.rows = []

    def add_read(self, read):
        key = (read.run_id, read.reader_id, read.seq)
        if read.seq is not None and key in self.seen:
            return                          # duplicate re-send, as the buffer drops it
        self.seen.add(key)
        if read.run_id:
            self.run_ids.add(read.run_id)
        self.live.ingest_report(read)
        k = (read.junction_id, read.epc)
        a, b = sorted((float(read.first_seen_ts), float(read.last_seen_ts)))
        cur = self.open.get(k)
        if cur is not None and (a - cur[1] > PASS_GAP_S or b - cur[0] > PASS_MAX_S):
            self.due.append((k, cur[0], cur[1]))
            cur = None
        self.open[k] = [a, b] if cur is None else [cur[0], max(cur[1], b)]

    def add_boxes(self, jid, t, vehicles, source, frame=None):
        if MASK is None:
            self.live.ingest_boxes(jid, t, vehicles, source)
        elif source == "vehicle_boxes":
            self.live.ingest_boxes(jid, t, MASK.apply(jid, frame, t, vehicles), source)
        ts = self.box_t[jid]
        k = bisect.bisect_left(ts, t)
        if k < len(ts) and ts[k] == t:
            return
        ts.insert(k, t)
        self.box_ids[jid].insert(k, {str(v["vehicle_id"]) for v in vehicles})

    def tick(self, now, final=False):
        self.now = now if self.now is None else max(self.now, now)
        for k, (t0, t1) in list(self.open.items()):
            if final or self.now - t1 > PASS_GAP_S:
                self.due.append((k, t0, t1))
                del self.open[k]
        ready = [d for d in self.due if final or self.now >= d[2] + self.delay]
        self.due = [d for d in self.due if d not in ready]
        for (jid, epc), t0, t1 in sorted(ready, key=lambda d: d[2]):
            self.assess(jid, epc, t0, t1)

    def visible(self, jid, vehicle, t0, t1):
        ts = self.box_t[jid]
        a, b = bisect.bisect_left(ts, t0 - VIS_PAD_S), bisect.bisect_right(ts, t1 + VIS_PAD_S)
        return any(vehicle in self.box_ids[jid][i] for i in range(a, b))

    def assess(self, jid, epc, t0, t1):
        res = self.live.assess(epc, jid, t0, t1)
        entry = REGISTRY.lookup_epc(epc)
        truth = entry.sim_vehicle_id if entry is not None else None
        vis = bool(truth) and self.visible(jid, truth, t0, t1)
        prop = track_vehicle(res.get("proposed_track"))
        wrong = prop is not None and not (vis and prop == truth)
        self.rows.append(dict(
            junction=jid, epc=epc, vehicle=truth, t0=round(t0, 2), t1=round(t1, 2), visible=vis,
            status=res["status"], proposed=res.get("proposed_track"), confidence=res.get("confidence"),
            confirmed=res["status"] == STATUS_CONFIRMED, wrong=wrong, hard=res.get("hard"),
            contested=res.get("contested"), short=res.get("short"), threshold=res.get("threshold"),
            clock_source=res.get("clock_source"), clock_offsets_s=res.get("clock_offsets_s")))


def replay_file(path, shadow, delay, runs):
    segments, seg, last, last_rfid = [], None, None, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                msg = json.loads(line)["msg"]
            except (ValueError, KeyError, TypeError):
                continue
            kind = msg.get("type")
            if kind not in ("rfid_reading", "vehicle_boxes", "camera_frame"):
                continue
            try:
                ts = float(msg.get("timestamp_sim"))
            except (TypeError, ValueError):
                continue
            # a new CARLA run = a new RFID run_id, or the RFID clock going back
            # (late camera / box messages are normal and never split a run)
            new_run = kind == "rfid_reading" and seg is not None and bool(
                (msg.get("run_id") and seg.run_ids and msg.get("run_id") not in seg.run_ids)
                or (last_rfid is not None and ts < last_rfid - BACKJUMP_S))
            if seg is None or new_run:
                if seg is not None:
                    seg.tick(last, final=True)
                seg = Segment(shadow, delay)
                if MASK is not None:
                    MASK.reset()
                segments.append(seg)
                last, last_rfid = ts, None
            last = max(last, ts)
            if kind == "rfid_reading":
                last_rfid = ts if last_rfid is None else max(last_rfid, ts)
            if kind == "rfid_reading":
                read = parse_message(msg)
                if read is not None:
                    seg.add_read(read)
            else:
                vehicles = parse_vehicle_boxes(msg.get("vehicles"))
                if vehicles is not None:
                    seg.add_boxes(str(msg.get("junction_id")), ts, vehicles, kind, msg.get("frame"))
            seg.tick(ts)
    if seg is not None:
        seg.tick(last, final=True)
    out = []
    for s in segments:
        if not s.run_ids:
            continue
        rid = sorted(s.run_ids)[0]
        session, run = runs.get(rid, ("unknown", rid[:8]))
        for r in s.rows:
            r.update(session=session, run=run, run_id=rid, recording=path.name)
        out += s.rows
        print(f"  {path.name}: {session}/{run}: {len(s.rows)} passes, "
              f"clock estimates {s.live.counters['clock_estimates']}, "
              f"box frames {s.live.counters['box_frames']}", flush=True)
    return out


def summarize(rows):
    conf = [r for r in rows if r["confirmed"]]
    k = sum(r["wrong"] for r in conf)
    prop = [r for r in rows if r["proposed"] is not None]
    return dict(passes=len(rows), proposed=len(prop), proposed_wrong=sum(r["wrong"] for r in prop),
                confirmed=len(conf), wrong=k, coverage=len(conf) / max(len(rows), 1),
                error=(k / len(conf)) if conf else None, cp90_upper=cp_upper(k, len(conf)),
                hard_confirmed=sum(1 for r in conf if r["hard"]),
                clock_estimated_share=(sum(1 for r in rows if r["clock_source"] == "estimated")
                                       / max(len(rows), 1)),
                wrong_list=[{x: r[x] for x in ("run", "junction", "vehicle", "proposed", "confidence",
                                               "hard", "t0", "t1")} for r in conf if r["wrong"]])


REGISTRY = VehicleRegistry.from_seed()
MASK = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recordings", type=Path, nargs="+", required=True)
    ap.add_argument("--runs-dir", type=Path, nargs="*", default=[])
    ap.add_argument("--calibration", type=Path, default=Path(DEFAULT_CONFIG.netra_calibration))
    ap.add_argument("--delay", type=float, default=20.0)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--detector-mask", type=Path, nargs="+")
    ap.add_argument("--fragment-gap", type=float)
    args = ap.parse_args(argv)
    global MASK
    if args.detector_mask:
        MASK = DetectorMask(args.detector_mask, args.fragment_gap)
    shadow = NetraShadow.from_file(args.calibration)
    print(f"calibration {args.calibration.name}: calibrated={shadow.calibrated} per_group={shadow.per_group} "
          f"easy={shadow.thr_easy} hard={shadow.thr_hard} single={shadow.threshold}", flush=True)
    runs = run_index(args.runs_dir)
    rows = []
    for f in recording_files(args.recordings):
        rows += replay_file(f, shadow, args.delay, runs)
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    summary = {s: summarize(rr) for s, rr in sorted(by_session.items())}
    summary["all"] = summarize(rows)
    for s, v in summary.items():
        cp = "-" if v["cp90_upper"] is None else f"{100 * v['cp90_upper']:.2f}%"
        print(f"{s:28s} passes {v['passes']:5d}  confirmed {v['confirmed']:5d}  wrong {v['wrong']:3d}  "
              f"coverage {100 * v['coverage']:.1f}%  cp90 {cp}")
    mask = None
    if MASK is not None:
        mask = dict(files=[str(f) for f in args.detector_mask], fragment_gap=args.fragment_gap,
                    **MASK.counters)
        print(f"detector mask: kept {MASK.counters['kept_boxes']} of {MASK.counters['gt_boxes']} "
              f"ground-truth boxes ({MASK.counters['unsampled_boxes']} on unsampled frames)")
    if args.json:
        args.json.write_text(json.dumps({"calibration": str(args.calibration), "delay_s": args.delay,
                                         "detector_mask": mask,
                                         "summary": summary, "rows": rows}, indent=2, default=str),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
