"""Evaluate the ANPR adapter + the Task 2 plate rules on the saved evidence.

Runs over every saved plate crop and annotated/hero/strip frame in
``evidence_files`` (Postgres) and reports plate-level and character-level
accuracy against the 8 known demo plates, split by feed source (live CARLA vs
synthetic simulator frames - synthetic plates are clean renders and are NOT a
measure of real accuracy).

Ground truth: there are no hand labels, so a sample is ATTRIBUTED to one of the
8 known plates only when the closest known plate to its OCR outputs (any
variant, any preprocessing, or the stored ANPR plate) is within edit distance 4
and unambiguous. Unattributable samples are counted separately; that is the
honest "could not be read at all" bucket.

Preprocessing options compared on the crops (each through the same OCR +
rules):
  base          as saved (the OCR itself upscales to a fixed height + allowlist)
  trim          remove the 3-4 px padding the evidence crop carries
  two_line      the OCR module's default two-line split (aspect < 2.5)
  pad           6 px replicated border
  clahe         CLAHE on the L channel
  sharpen       unsharp mask
  invert        polarity inverted
The character allowlist (A-Z, 0-9) is always on inside the OCR decoder.

    python tools/eval_anpr_on_saved_frames.py [--limit N] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"
sys.path.insert(0, str(BACKEND))

env_file = BACKEND / ".env"
if env_file.is_file():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

import cv2  # noqa: E402
import numpy as np  # noqa: E402

KNOWN = {
    "A": "KA01AT4521", "B": "MH12BR7814", "C": "TN09CK2365", "D": "KL07DL9182",
    "E": "DL03EN6047", "F": "GJ05FP3419", "G": "AP16GQ8273", "H": "TG08HR5196",
}


def edit_distance(a: str | None, b: str | None) -> int:
    from app.services.rfid.vision import edit_distance as ed

    return ed(a, b)


# ---------------------------------------------------------------- preprocessing

def _trim(crop, px=4):
    h, w = crop.shape[:2]
    return crop[px:h - px, px:w - px] if h > 2 * px + 4 and w > 2 * px + 8 else crop


def _pad(crop, px=6):
    return cv2.copyMakeBorder(crop, px, px, px, px, cv2.BORDER_REPLICATE)


def _clahe(crop):
    lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _sharpen(crop):
    blur = cv2.GaussianBlur(crop, (0, 0), 1.2)
    return cv2.addWeighted(crop, 1.6, blur, -0.6, 0)


def _invert(crop):
    return 255 - crop


OPTIONS = {
    "base": (lambda c: c, 0.0),
    "trim": (_trim, 0.0),
    "two_line": (_trim, None),                    # module default split threshold
    "pad": (lambda c: _pad(_trim(c)), 0.0),
    "clahe": (lambda c: _clahe(_trim(c)), 0.0),
    "sharpen": (lambda c: _sharpen(_trim(c)), 0.0),
    "invert": (lambda c: _invert(_trim(c)), 0.0),
}


def read_crop(crop, option: str, cfg):
    """OCR one crop with a preprocessing option -> (best rule check, all texts)."""
    from app.services.rfid.plate_rules import check_text
    from app.services.routine_violation_video import plate_ocr

    transform, two_line = OPTIONS[option]
    image = transform(crop)
    reads = plate_ocr.read_plate(image, two_line_aspect=two_line)
    best, texts = None, []
    for read in reads:
        texts.append(read.text)
        checked = check_text(read.text, read.confidences, cfg)
        key = (checked["valid"], checked["mean_conf"])
        if best is None or key > best[0]:
            best = (key, checked)
    return (best[1] if best else None), texts


def attribute(candidates: list[str]) -> tuple[str | None, int | None]:
    """Nearest known plate to ANY candidate string, if unambiguous and ED <= 4."""
    best = {}
    for text in candidates:
        if not text:
            continue
        for name, plate in KNOWN.items():
            distance = edit_distance(text, plate)
            best[plate] = min(best.get(plate, 99), distance)
    if not best:
        return None, None
    ranked = sorted(best.items(), key=lambda kv: kv[1])
    if ranked[0][1] > 4 or (len(ranked) > 1 and ranked[1][1] == ranked[0][1]):
        return None, ranked[0][1]
    return ranked[0][0], ranked[0][1]


def char_accuracy(predicted: str | None, truth: str) -> float:
    if not predicted:
        return 0.0
    return max(0.0, 1.0 - edit_distance(predicted, truth) / len(truth))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine, text

    from app.services.anpr_adapter import get_anpr_adapter
    from app.services.rfid.config import RfidFeatureConfig
    from app.services.rfid.plate_rules import apply_rules

    cfg = RfidFeatureConfig.from_env()
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(text("""
            SELECT e.kind, e.path, e.sha256, i.source, i.run_id, v.anpr_plate, v.rfid_plate
            FROM evidence_files e
            JOIN incidents i ON i.id = e.incident_id
            LEFT JOIN vision_matches v ON v.id = e.vision_match_id
            WHERE e.kind IN ('plate_crop', 'annotated_frame', 'hero_frame', 'strip_frame')
            ORDER BY e.created_at""")).mappings().all()]
    # one sample per distinct file content (the old pipeline re-saved files)
    seen, samples = set(), []
    for row in rows:
        path = Path(row["path"])
        if not path.is_file():
            continue
        digest = __import__("hashlib").sha256(path.read_bytes()).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        samples.append(row)
    if args.limit:
        samples = samples[:args.limit]

    crops = [s for s in samples if s["kind"] == "plate_crop"]
    frames = [s for s in samples if s["kind"] != "plate_crop"]
    print(f"[eval] {len(samples)} distinct evidence images ({len(crops)} plate crops, "
          f"{len(frames)} frames; sources: "
          f"{dict(sorted(defaultdict(int, {k: sum(1 for s in samples if s['source'] == k) for k in {s['source'] for s in samples}}).items()))})")

    # ---------------- crops: preprocessing comparison
    results = defaultdict(lambda: defaultdict(list))     # option -> source -> [(pred, truth)]
    attribution = []
    for sample in crops:
        crop = cv2.imread(sample["path"])
        if crop is None:
            continue
        per_option, candidates = {}, [sample.get("anpr_plate")]
        for option in OPTIONS:
            checked, texts = read_crop(crop, option, cfg)
            per_option[option] = checked
            candidates += texts + ([checked["corrected"]] if checked and checked["corrected"] else [])
        truth, distance = attribute(candidates)
        attribution.append((sample, truth, distance, crop.shape[1]))
        if truth is None:
            continue
        for option, checked in per_option.items():
            predicted = checked["corrected"] if (checked and checked["valid"]) else None
            results[option][sample["source"]].append((predicted, truth))

    # ---------------- frames: full adapter (detect + OCR) + rules
    adapter = get_anpr_adapter()
    adapter.load()
    frame_stats = defaultdict(lambda: {"frames": 0, "detections": 0, "valid": 0, "latency": [],
                                       "widths": [], "too_small": 0})
    for sample in frames:
        image = cv2.imread(sample["path"])
        if image is None:
            continue
        # annotated images carry a banner strip on top: drop it
        if image.shape[0] > 720:
            image = image[image.shape[0] - 720:]
        started = time.perf_counter()
        reads = adapter.detect_and_read(image, two_line_aspect=cfg.ocr_two_line_aspect)
        elapsed = (time.perf_counter() - started) * 1000.0
        stats = frame_stats[sample["source"]]
        stats["frames"] += 1
        stats["latency"].append(elapsed)
        for read in reads:
            rule = apply_rules(read, cfg)
            stats["detections"] += 1
            stats["widths"].append(rule.width_px)
            stats["valid"] += int(rule.valid)
            stats["too_small"] += int(rule.gated == "PLATE_TOO_SMALL")

    # ---------------- report
    report = {"crops": {}, "frames": {}, "attribution": {}}
    print("\n[eval] plate crops: attribution (nearest known plate, ED<=4, unambiguous)")
    by_source = defaultdict(lambda: [0, 0])
    for sample, truth, distance, width in attribution:
        by_source[sample["source"]][0] += 1
        by_source[sample["source"]][1] += int(truth is not None)
    for source, (total, attributed) in sorted(by_source.items()):
        print(f"  {source:9s} {attributed}/{total} attributable")
        report["attribution"][source] = {"total": total, "attributed": attributed}

    print("\n[eval] plate crops: accuracy per preprocessing option (OCR + Task 2 rules)")
    print(f"  {'option':9s} {'source':9s} {'n':>3s} {'plate acc':>9s} {'char acc':>8s} {'valid':>6s}")
    for option in OPTIONS:
        for source, pairs in sorted(results[option].items()):
            n = len(pairs)
            plate_acc = sum(1 for p, t in pairs if p == t) / n
            char_acc = sum(char_accuracy(p, t) for p, t in pairs) / n
            valid = sum(1 for p, _ in pairs if p) / n
            print(f"  {option:9s} {source:9s} {n:3d} {plate_acc:9.2f} {char_acc:8.2f} {valid:6.2f}")
            report["crops"].setdefault(option, {})[source] = {
                "n": n, "plate_accuracy": round(plate_acc, 3), "char_accuracy": round(char_acc, 3),
                "valid_rate": round(valid, 3)}

    print("\n[eval] frames: adapter detect+read + rules (banner removed; older annotated frames "
          "still carry the drawn plate box, which hurts OCR)")
    for source, stats in sorted(frame_stats.items()):
        widths = stats["widths"]
        line = {
            "frames": stats["frames"], "detections": stats["detections"],
            "valid_reads": stats["valid"], "too_small": stats["too_small"],
            "plate_px_median": round(statistics.median(widths), 1) if widths else None,
            "plate_px_min": round(min(widths), 1) if widths else None,
            "latency_ms_mean": round(sum(stats["latency"]) / len(stats["latency"]), 1)
            if stats["latency"] else None,
        }
        report["frames"][source] = line
        print(f"  {source:9s} {line}")

    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\n[eval] wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
