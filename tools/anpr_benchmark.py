"""Benchmark Member 3's ANPR model on recorded junction frames.

The live feed renders plates about 30 px wide at about 30 m, so the adapter can
run the detector on the full frame, on overlapping tiles, or on an upscaled
frame. This tool measures all three on real CARLA frames and reports detection
rate, readable plates (against the 8 known demo plates) and per-frame latency.

Run from the repository root:
    python tools/anpr_benchmark.py member3/media/videos/<junction>.mp4 --frames 12
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(BACKEND))

import cv2  # noqa: E402

import scenario  # noqa: E402
from app.services.anpr_adapter import AnprAdapter, AnprConfig  # noqa: E402


def sample_frames(video: Path, count: int) -> list[tuple[int, "cv2.Mat"]]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"cannot open {video}")
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, total // max(1, count))
    frames = []
    index = 0
    while len(frames) < count:
        ok, frame = capture.read()
        if not ok:
            break
        if index % step == 0:
            frames.append((index, frame))
        index += 1
    capture.release()
    return frames


def run_mode(mode: str, frames: list, config: AnprConfig) -> dict:
    adapter = AnprAdapter(AnprConfig(**{**config.as_dict(), "mode": mode}))
    adapter.warm_up()
    latencies = []
    detections = 0
    reads = []
    valid_reads = []
    per_frame = []
    for index, frame in frames:
        started = time.perf_counter()
        found = adapter.detect_and_read(frame)
        latencies.append((time.perf_counter() - started) * 1000.0)
        detections += len(found)
        # A partial read still counts as "text recovered"; a structurally valid
        # mark is tracked separately.
        texts = [read.plate_norm or read.raw_ocr for read in found if (read.plate_norm or read.raw_ocr)]
        reads.extend(texts)
        valid_reads.extend(read.plate_norm for read in found if read.plate_norm)
        per_frame.append((index, len(found), texts))
    return {
        "mode": mode,
        "frames": len(frames),
        "detections": detections,
        "frames_with_detection": sum(1 for _, n, _ in per_frame if n),
        "frames_with_text": sum(1 for _, _, texts in per_frame if texts),
        "distinct_plates": sorted(set(reads)),
        "valid_plates": sorted(set(valid_reads)),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 1) if latencies else None,
            "p50": round(statistics.median(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "per_frame": per_frame,
        "backend": adapter.status()["backend"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path)
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--modes", default="full,tiled,upscaled")
    args = parser.parse_args(argv)

    if not args.video.is_file():
        raise SystemExit(f"video not found: {args.video}")

    frames = sample_frames(args.video, args.frames)
    print(f"video      : {args.video}")
    print(f"sampled    : {len(frames)} frames (indices {[i for i, _ in frames]})")
    print(f"known plates: {sorted(scenario.PLATE_NORM.values())}")
    print()

    results = []
    for mode in [m.strip() for m in args.modes.split(",") if m.strip()]:
        result = run_mode(mode, frames, AnprConfig())
        results.append(result)

    print(f"{'mode':<10} {'detections':>10} {'frames w/det':>13} {'frames w/text':>14} "
          f"{'mean ms':>8} {'p50 ms':>7} {'max ms':>7}")
    for result in results:
        latency = result["latency_ms"]
        print(f"{result['mode']:<10} {result['detections']:>10} "
              f"{result['frames_with_detection']:>13} {result['frames_with_text']:>14} "
              f"{latency['mean']:>8} "
              f"{latency['p50']:>7} {latency['max']:>7}")
    print()
    known = set(scenario.PLATE_NORM.values())
    for result in results:
        print(f"[{result['mode']}] backend: {result['backend']}")
        print(f"[{result['mode']}] OCR strings: {result['distinct_plates']}")
        matches = [p for p in result["distinct_plates"] if p in known]
        print(f"[{result['mode']}] full-plate matches: {matches}")
        print(f"[{result['mode']}] structurally valid marks: {result['valid_plates']}")
        for index, count, texts in result["per_frame"]:
            print(f"    frame {index:>5}: {count} plate(s) {texts}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
