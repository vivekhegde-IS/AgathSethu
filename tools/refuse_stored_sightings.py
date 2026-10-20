"""Regression: re-run the NEW fusion over every stored sighting (read-only).

The camera ring is not persisted, so the re-run uses what the old pipeline
saved per sighting: its plate crop(s) and annotated frame(s). The crop is
OCR'd as one read (single-line, unpadded); the annotated frame goes through the
full adapter (detect + OCR) after its banner strip is removed. Everything then
goes through the Task 2 plate rules and the new per-vehicle fusion, and the
result is printed next to the status that is stored in Postgres.

Nothing is written to the database.

    python tools/refuse_stored_sightings.py [--source live|synthetic|all]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="all")
    args = parser.parse_args(argv)

    from sqlalchemy import create_engine, text

    from app.services.anpr_adapter import get_anpr_adapter
    from app.services.rfid.config import RfidFeatureConfig
    from app.services.rfid.plate_rules import apply_rules, check_text
    from app.services.rfid.vision import FrameReads, FrameRef, fuse
    from app.services.routine_violation_video import plate_ocr

    cfg = RfidFeatureConfig.from_env()
    adapter = get_anpr_adapter()
    adapter.load()
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        sightings = [dict(r) for r in conn.execute(text("""
            SELECT s.id, s.junction_id, s.first_seen_ts, i.run_id, i.source,
                   v.id AS match_id, v.status, v.anpr_plate, v.rfid_plate, v.edit_distance
            FROM rfid_sightings s
            JOIN incidents i ON i.id = s.incident_id
            LEFT JOIN vision_matches v ON v.sighting_id = s.id
            ORDER BY i.created_at, s.first_seen_ts""")).mappings().all()]
        files = [dict(r) for r in conn.execute(text(
            "SELECT vision_match_id, kind, path FROM evidence_files "
            "WHERE vision_match_id IS NOT NULL")).mappings().all()]

    by_match = {}
    for row in files:
        by_match.setdefault(str(row["vision_match_id"]), []).append(row)

    print(f"{'run':26s} {'src':9s} {'J':3s} | {'BEFORE':16s} {'anpr':12s} ed | "
          f"{'AFTER':16s} {'anpr':12s} ed  assisted  frames  rejected")
    changes = 0
    for s in sightings:
        if args.source != "all" and s["source"] != args.source:
            continue
        rows = by_match.get(str(s["match_id"]), [])
        seen, frame_reads = set(), []
        for index, row in enumerate(rows):
            path = Path(row["path"])
            if not path.is_file():
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen:                      # the old pipeline overwrote files
                continue
            seen.add(digest)
            image = cv2.imread(str(path))
            if image is None:
                continue
            ref = FrameRef(f"CAM_{s['junction_id']}_01", s["junction_id"],
                           (s["first_seen_ts"] or 0.0) + 0.2 * index, b"", None)
            if row["kind"] == "plate_crop":
                crop = image[4:-4, 4:-4] if image.shape[0] > 12 and image.shape[1] > 16 else image
                reads = plate_ocr.read_plate(crop, two_line_aspect=cfg.ocr_two_line_aspect)
                variants = [{"text": r.text, "confidences": r.confidences, "variant": r.variant}
                            for r in reads]
                h, w = crop.shape[:2]
                frame_reads.append(FrameReads(ref, [apply_rules(
                    {"box": (0, 0, w, h), "det_confidence": 1.0, "ocr_variants": variants}, cfg)]))
            elif row["kind"] in ("annotated_frame", "hero_frame", "strip_frame"):
                if image.shape[0] > 720:
                    image = image[image.shape[0] - 720:]
                rules = [apply_rules(read, cfg) for read in
                         adapter.detect_and_read(image, two_line_aspect=cfg.ocr_two_line_aspect)]
                frame_reads.append(FrameReads(ref, rules))
        after = fuse(frame_reads, s["rfid_plate"], cfg, reference_ts=s["first_seen_ts"])
        if (after["status"], after["anpr_plate"]) != (s["status"], s["anpr_plate"]):
            changes += 1
        print(f"{(s['run_id'] or '-')[:26]:26s} {s['source'] or '-':9s} {s['junction_id']:3s} | "
              f"{(s['status'] or '-'):16s} {(s['anpr_plate'] or '-'):12s} "
              f"{s['edit_distance'] if s['edit_distance'] is not None else '-':>2} | "
              f"{after['status']:16s} {(after['anpr_plate'] or '-'):12s} "
              f"{after['edit_distance'] if after['edit_distance'] is not None else '-':>2}  "
              f"{'yes' if after['rule_assisted'] else 'no':8s}  {len(frame_reads):6d}  "
              f"{len(after['rejected_reads']):8d}")
        if after["rule_assisted"] or after["status"] in ("PLATE_TOO_SMALL", "NO_PLATE_VISIBLE"):
            detail = after["match_reason"] or ""
            if after["status"] in ("PLATE_TOO_SMALL", "NO_PLATE_VISIBLE"):
                detail = f"max plate width {after['max_plate_px']} px"
            print(f"{'':42s}-> {detail}")
    print(f"\n{changes} sighting(s) change status or plate under the new fusion "
          "(re-run on the saved evidence only; the original 8-12 ring frames are not stored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
