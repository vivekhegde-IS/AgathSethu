"""Per-plate ANPR accuracy on REAL CARLA plate crops saved by live runs.

Sources (whatever exists on this machine):
  member3/backend/runtime/live_anpr/<session>/*_plate.jpg      live-panel crops
  member3/backend/runtime/incident_evidence/<incident>/<J>/*plate*.jpg

Engines compared on the same crops:
  rules   PP-OCR (plate_ocr.read_plate) + plate_validation.validate_plate
  strict  PP-OCR + plate_validation.strict_plate  (positional fixes only)
  rapid   RapidOCR (processor.ocr_plate_crop) + processor.normalize_plate

Ground truth: there are no hand labels. A crop is attributed to one of the 8
known demo plates when the closest known plate to ANY engine's raw OCR text is
within edit distance 4 and unambiguous (same rule as eval_anpr_on_saved_frames).
"correct" = exact plate; "wrong" = a VALID plate that is not the truth (the
dangerous case); "none" = no valid plate produced.

    python tools/eval_live_plate_crops.py [--sessions S1,S2] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402

KNOWN = ["KA01AT4521", "MH12BR7814", "TN09CK2365", "KL07DL9182",
         "DL03EN6047", "GJ05FP3419", "AP16GQ8273", "TG08HR5196"]


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def attribute(texts: list[str]) -> str | None:
    best = None
    for text in texts:
        text = "".join(ch for ch in (text or "").upper() if ch.isalnum())
        if not text:
            continue
        ranked = sorted((edit_distance(text, k), k) for k in KNOWN)
        if ranked[0][0] <= 4 and (len(ranked) < 2 or ranked[0][0] < ranked[1][0]):
            if best is None or ranked[0][0] < best[0]:
                best = ranked[0]
    return best[1] if best else None


def crops(sessions: list[str] | None) -> list[Path]:
    out = []
    live = BACKEND / "runtime" / "live_anpr"
    for session in sorted(live.glob("*")) if live.is_dir() else []:
        if sessions and session.name not in sessions:
            continue
        out += sorted(session.glob("*_plate.jpg"))
    evidence = BACKEND / "runtime" / "incident_evidence"
    for path in sorted(evidence.glob("*/*/*.jpg")) if evidence.is_dir() else []:
        if "plate" in path.name:
            out.append(path)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", default=None)
    parser.add_argument("--json", default=None)
    parser.add_argument("--engines", default="rules,strict,rapid")
    args = parser.parse_args(argv)

    from app.services.plate_validation import parse_plate, validate_plate
    from app.services.routine_violation_video import plate_ocr
    engines = args.engines.split(",")
    strict_plate = None
    if "strict" in engines:
        from app.services.plate_validation import strict_plate
    if "rapid" in engines:
        from app.services.routine_violation_video.processor import normalize_plate, ocr_plate_crop

    def pp_reads(crop):
        return plate_ocr.read_plate(crop, None, two_line_aspect=0)

    def best_by(reads, judge):
        best = None
        for read in reads:
            result = judge(read)
            key = (result is not None, sum(read.confidences) / max(1, len(read.confidences)))
            if best is None or key > best[0]:
                best = (key, result, read.text)
        return (best[1], best[2]) if best else (None, None)

    rows = []
    paths = crops(args.sessions.split(",") if args.sessions else None)
    for path in paths:
        crop = cv2.imread(str(path))
        if crop is None:
            continue
        row = {"path": str(path.relative_to(ROOT)), "raw": {}, "plate": {}}
        reads = pp_reads(crop)
        if "rules" in engines:
            def rules(read):
                parsed = parse_plate(read.text, read.confidences)
                if parsed is None:
                    return None
                checked = validate_plate(parsed.chars, parsed.confidences, log=False)
                return checked.plate if checked.valid else None
            row["plate"]["rules"], row["raw"]["rules"] = best_by(reads, rules)
        if "strict" in engines:
            def strict(read):
                return strict_plate(read.text).plate
            row["plate"]["strict"], row["raw"]["strict"] = best_by(reads, strict)
        if "rapid" in engines:
            results = ocr_plate_crop(crop)
            plate = raw = None
            for result in results:
                normalized = normalize_plate(result["text"])
                raw = raw or result["text"]
                if normalized:
                    plate, raw = normalized, result["text"]
                    break
            row["plate"]["rapid"], row["raw"]["rapid"] = plate, raw
        row["truth"] = attribute([t for t in row["raw"].values() if t] +
                                 [p for p in row["plate"].values() if p])
        rows.append(row)

    print(f"{len(rows)} real CARLA crops, {sum(1 for r in rows if r['truth'])} attributed")
    summary = {}
    for engine in engines:
        counts = Counter()
        per_plate = defaultdict(Counter)
        confusions = Counter()
        for row in rows:
            if not row["truth"]:
                counts["unattributed"] += 1
                continue
            got = row["plate"].get(engine)
            verdict = "correct" if got == row["truth"] else ("wrong" if got else "none")
            counts[verdict] += 1
            per_plate[row["truth"]][verdict] += 1
            if got and got != row["truth"] and len(got) == len(row["truth"]):
                for a, b in zip(row["truth"], got):
                    if a != b:
                        confusions[f"{a}->{b}"] += 1
        attributed = sum(counts[k] for k in ("correct", "wrong", "none"))
        summary[engine] = {"counts": dict(counts), "per_plate": {k: dict(v) for k, v in per_plate.items()},
                           "confusions": dict(confusions.most_common())}
        print(f"\n[{engine}] correct {counts['correct']}/{attributed}  "
              f"WRONG valid plate {counts['wrong']}  no plate {counts['none']}")
        for plate in KNOWN:
            if per_plate[plate]:
                c = per_plate[plate]
                print(f"   {plate}: correct {c['correct']}  wrong {c['wrong']}  none {c['none']}")
        if confusions:
            print("   char confusions (truth->read):", dict(confusions.most_common(10)))
    if args.json:
        Path(args.json).write_text(json.dumps({"rows": rows, "summary": summary}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
