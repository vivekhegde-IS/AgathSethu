"""
AGHAT SETHU — Fine generation for routine-violation videos

Called once per processed video by run_pipeline_job() with the summary returned
by run_dual_pipeline(). Each entry of summary["vehicles"] is already one
violating vehicle (tracker fragments merged, same-plate vehicles merged), so it
is one violation event: consecutive frames never produce extra fines.

The plate is looked up in the existing `vehicles` table; the fine goes to the
citizen account (`users`) that owns that vehicle and shows up in the citizen
portal. Per run: one fine per (plate, violation type). Across runs nothing is
de-duplicated: processing the same video again issues new fines.

Evidence files live under static/violations/ and the DB stores paths RELATIVE
to static/ ("violations/<file>"), never absolute OS paths.
"""

from __future__ import annotations

import re
import traceback
from datetime import datetime, timezone
from pathlib import Path

import cv2

from app.core.config import data_dir
from app.core.database import SessionLocal
from app.models.citizen_fines import Fine, UnmatchedViolation, Video
from app.services.anpr_partial import known_char_count, match_pattern
from app.models.models import User, Vehicle
from app.services.notification_service import notify_fine_issued

BACKEND_DIR = Path(__file__).resolve().parents[2]
STATIC_DIR = data_dir() / "static"      # fine snapshots and clips (DATA_DIR)
SNAPSHOT_DIR = STATIC_DIR / "violations"
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
# Folders whose videos are registered by `seed_citizen_plates.py register-videos`;
# an upload with the same filename is linked to that row.
VIDEO_DIRS = [BACKEND_DIR.parent / "media" / "videos", BACKEND_DIR.parent.parent]

FINE_AMOUNTS = {"NO HELMET": 1000.0, "TRIPLE RIDING": 1000.0}
DEFAULT_FINE_AMOUNT = 500.0
# A pipeline-CONFIRMED plate is fined as before. When True, it is fined only if
# the strict partial ANPR (app/services/anpr_partial.py) read the same complete
# plate with no frame conflicts; otherwise it is recorded as an unreadable plate.
# Off by default so the existing fine flow is unchanged; disagreements are logged.
REQUIRE_STRICT_AGREEMENT = False
CLIP_SECONDS_BEFORE = 2.0
CLIP_SECONDS_AFTER = 2.0
CLIP_MAX_WIDTH = 480
CLIP_FPS = 12.0     # source videos can be 4K60; encoding every frame cost ~30 s and ~15 MB per clip


def _log(job_id: str, message: str) -> None:
    print(f"[FINES] job {job_id[:8]} {message}", flush=True)


def normalize_plate(text: str | None) -> str:
    """Uppercase, letters and digits only: 'hp 02.zh-5581' -> 'HP02ZH5581'."""
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def fine_amount_for(violation_type: str) -> float:
    return FINE_AMOUNTS.get(violation_type.upper(), DEFAULT_FINE_AMOUNT)


def static_file(relative: str | None) -> Path | None:
    """Resolve a DB path ("violations/x.jpg") to the file, only inside static/violations/."""
    if not relative:
        return None
    path = (STATIC_DIR / relative).resolve()
    return path if path.parent == SNAPSHOT_DIR.resolve() and path.is_file() else None


def get_or_create_video(db, filename: str, path: str | None = None) -> Video:
    video = db.query(Video).filter(Video.filename == filename).order_by(Video.id).first()
    if video is None:
        if path is None:
            path = next((str(d / filename) for d in VIDEO_DIRS if (d / filename).is_file()), None)
        video = Video(filename=filename, path=path)
        db.add(video)
        db.flush()
    return video


def _file_stem(plate: str, video_id: int, when: datetime) -> str:
    local = when.astimezone()
    return f"{plate or 'UNREADABLE'}_{video_id}_{local:%Y%m%d_%H%M%S}_{local.microsecond // 1000:03d}"


def _save_snapshot(job_id, evidence_jpg: Path, plate, video: Video, record: dict, when: datetime,
                   label: str | None = None) -> str | None:
    """Save the real violation frame with an evidence overlay.

    The source is the frame the pipeline picked from the uploaded video for this
    vehicle (record["evidence_frame"], its sharpest plate read), with the
    pipeline's own vehicle box, plate box and plate crop already drawn by
    _render_and_save(). Added here: a banner with plate, violation, video name,
    video position and detection timestamp.
    """
    frame = cv2.imread(str(evidence_jpg)) if evidence_jpg.is_file() else None
    if frame is None:
        _log(job_id, f"no evidence frame for vehicle {record.get('vehicle_id')} at {evidence_jpg}")
        return None
    height, width = frame.shape[:2]
    scale = max(0.5, width / 1600)
    thickness = max(1, round(2 * scale))
    lines = [
        f"{label or 'PLATE: ' + (plate or 'UNREADABLE')}   VIOLATION: {', '.join(record.get('violations') or [])}",
        f"VIDEO: {video.filename}   frame {record.get('evidence_frame')} @ {record.get('evidence_time_s')}s",
        f"DETECTED: {when.astimezone():%Y-%m-%d %H:%M:%S}",
    ]
    line_h = int(34 * scale)
    banner_h = line_h * len(lines) + int(14 * scale)
    # The banner goes on a strip ABOVE the frame, never over it: the pipeline's
    # plate crop sits in the top-left corner and must stay fully visible.
    frame = cv2.copyMakeBorder(frame, banner_h, 0, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (int(12 * scale), line_h * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.8 * scale, (0, 0, 255) if i == 0 else (255, 255, 255), thickness, cv2.LINE_AA)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    target = SNAPSHOT_DIR / f"{_file_stem('PARTIAL' if label else plate, video.id, when)}.jpg"
    written = cv2.imwrite(str(target), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    size = target.stat().st_size if target.is_file() else 0
    if not written or size == 0:
        _log(job_id, f"ERROR image NOT saved (imwrite={written}, size={size}) at {target}")
        return None
    _log(job_id, f"image saved at {target} ({size} bytes, {width}x{height}, video frame "
                 f"{record.get('evidence_frame')})")
    return f"violations/{target.name}"


def _save_clip(job_id, video_path: Path | None, plate, video: Video, at_seconds, when: datetime) -> str | None:
    """Cut a few seconds around the violation from the uploaded video.

    VP8/WebM because this OpenCV build has no H.264 encoder, and browsers
    cannot play OpenCV's mp4v output.
    """
    if video_path is None or at_seconds is None or not Path(video_path).is_file():
        return None
    capture = cv2.VideoCapture(str(video_path))
    writer = None
    target = SNAPSHOT_DIR / f"{_file_stem(plate, video.id, when)}.webm"
    try:
        fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
        step = max(1, round(fps / CLIP_FPS))
        start = max(0, int((at_seconds - CLIP_SECONDS_BEFORE) * fps))
        count = int((CLIP_SECONDS_BEFORE + CLIP_SECONDS_AFTER) * fps)
        capture.set(cv2.CAP_PROP_POS_FRAMES, start)
        for index in range(count):
            if index % step:                     # skipped frames: advance without converting
                if not capture.grab():
                    break
                continue
            ok, frame = capture.read()
            if not ok:
                break
            height, width = frame.shape[:2]
            if width > CLIP_MAX_WIDTH:
                frame = cv2.resize(frame, (CLIP_MAX_WIDTH, int(height * CLIP_MAX_WIDTH / width)))
            if writer is None:
                SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
                writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"VP80"), fps / step,
                                         (frame.shape[1], frame.shape[0]))
                if not writer.isOpened():
                    return None
            writer.write(frame)
    finally:
        capture.release()
        if writer is not None:
            writer.release()
    size = target.stat().st_size if target.is_file() else 0
    if size == 0:
        _log(job_id, f"clip NOT saved at {target}")
        return None
    _log(job_id, f"clip saved at {target} ({size} bytes)")
    return f"violations/{target.name}"


def registry_candidates(db, partial: dict) -> list[dict]:
    """Registered plates (vehicles table) that fit a strict partial pattern or any
    of its alternative layouts, matched in Postgres with the pattern's regex."""
    patterns = [partial["partial_pattern"]] + list(partial.get("alternative_patterns") or [])
    rows = (db.query(Vehicle.id, Vehicle.plate_number)
            .filter(Vehicle.is_active.is_(True), Vehicle.plate_number.op("~")(partial["regex"])).all())
    return sorted(({"plate": plate, "vehicle_id": str(vid),
                    "score": max(match_pattern(p, plate) for p in patterns)} for vid, plate in rows),
                  key=lambda c: (-c["score"], c["plate"]))


def rfid_registry_candidates(db, partial: dict) -> list[dict]:
    """RFID registry entries (vehicle_registry: EPC -> plate) whose plate fits a
    strict partial pattern - the pattern-to-EPC hand-off RFID fusion will use."""
    from app.models.models import VehicleRegistry

    patterns = [partial["partial_pattern"]] + list(partial.get("alternative_patterns") or [])
    rows = (db.query(VehicleRegistry.epc, VehicleRegistry.plate_norm)
            .filter(VehicleRegistry.plate_norm.op("~")(partial["regex"])).all())
    return sorted(({"plate": plate, "epc": epc, "source": "rfid_registry",
                    "score": max(match_pattern(p, plate) for p in patterns)} for epc, plate in rows),
                  key=lambda c: (-c["score"], c["plate"]))


def record_fines_for_run(summary: dict, run_dir: Path, video_name: str | None, job_id: str,
                         video_path: Path | None = None) -> dict:
    """Create fines / unmatched-violation rows for one processed video.

    Runs in the routine-violation worker thread with its OWN session and
    commits. Never raises: errors are logged with a traceback and returned in
    the dict, and the detection result is unaffected.
    """
    result = {"fines_created": 0, "unmatched": 0, "fines": [], "error": None}
    records = summary.get("vehicles") or []
    _log(job_id, f"video={video_name}: {len(records)} violating vehicle(s) from the pipeline")
    if not records:
        return result

    db = SessionLocal()
    try:
        video = get_or_create_video(db, video_name or "uploaded_video")
        issued: set[tuple[str, str]] = set()
        for record in records:
            violations = record.get("violations") or ["UNKNOWN"]
            plate = normalize_plate(record.get("plate_compact") or record.get("plate_number"))
            _log(job_id, f"violation detected: vehicle {record.get('vehicle_id')} {violations} "
                         f"at {record.get('evidence_time_s')}s")
            _log(job_id, f"plate={plate or 'UNREADABLE'} (status {record.get('plate_status')})")
            when = datetime.now(timezone.utc)
            # Only a CONFIRMED plate is fined automatically (existing flow below).
            # Anything else is never fined and is recorded as an unreadable plate.
            # Partial plates are a Level 2 (crash) tool only, where RFID can
            # resolve them; an uploaded routine video has no RFID.
            partial = record.get("partial_plate") or {}
            confirmed = record.get("plate_status") == "confirmed" and bool(plate)
            if confirmed and partial:
                strict_ok = (partial.get("is_complete") and partial.get("plate") == plate
                             and not partial.get("conflicts"))
                if not strict_ok:
                    _log(job_id, f"strict check: partial ANPR read {partial.get('partial_pattern')!r} "
                                 f"({len(partial.get('conflicts') or [])} frame conflict(s)) vs confirmed {plate} - "
                                 + ("recorded as unreadable" if REQUIRE_STRICT_AGREEMENT
                                    else "fined per existing flow (REQUIRE_STRICT_AGREEMENT off)"))
                    confirmed = confirmed and not REQUIRE_STRICT_AGREEMENT
            if not confirmed:
                pattern = partial.get("partial_pattern")
                if pattern and known_char_count(pattern) > 0:
                    # keep what was read as the raw plate; the violation stays unmatched
                    record = {**record, "plate_raw": pattern}
                    _log(job_id, f"plate PARTIAL {pattern!r}: recorded as unreadable - NOT fined")
                else:
                    _log(job_id, f"plate not confirmed and no character read (pattern {pattern!r})")
                plate = ""          # never use a low-confidence guess
            vehicle = (db.query(Vehicle).filter(Vehicle.plate_number == plate, Vehicle.is_active.is_(True)).first()
                       if plate else None)
            snapshot = _save_snapshot(job_id, Path(run_dir) / record.get("evidence_file", ""), plate, video,
                                      record, when)
            pending = [t for t in violations if (plate, t) not in issued]
            if vehicle is None:
                reason = "not_registered" if plate else "unreadable_plate"
                _log(job_id, f"unmatched ({reason})")
                for violation_type in pending:
                    db.add(UnmatchedViolation(
                        video_id=video.id, job_id=job_id, number_plate=plate or None,
                        plate_raw=record.get("plate_raw") or None, plate_status=record.get("plate_status"),
                        violation_type=violation_type, reason=reason,
                        snapshot_image_path=snapshot, evidence_time_s=record.get("evidence_time_s"),
                        detected_at=when,
                    ))
                    result["unmatched"] += 1
                continue
            owner = db.get(User, vehicle.owner_id)
            _log(job_id, f"matched user_id={vehicle.owner_id} ({owner.email if owner else '?'})")
            if not pending:
                _log(job_id, f"already fined {plate} for {violations} in this run - skipped")
                continue
            clip = _save_clip(job_id, video_path, plate, video, record.get("evidence_time_s"), when)
            for violation_type in pending:
                issued.add((plate, violation_type))
                fine = Fine(
                    user_id=vehicle.owner_id, vehicle_id=vehicle.id, video_id=video.id, job_id=job_id,
                    number_plate=plate, violation_type=violation_type,
                    fine_amount=fine_amount_for(violation_type), snapshot_image_path=snapshot,
                    clip_path=clip, plate_status=record.get("plate_status"),
                    evidence_time_s=record.get("evidence_time_s"), detected_at=when, status="Unpaid",
                )
                db.add(fine)
                db.flush()
                notify_fine_issued(db, fine)
                _log(job_id, f"fine id={fine.id} inserted: {plate} {violation_type} Rs{fine.fine_amount:.0f} "
                             f"image={snapshot}")
                result["fines"].append({"fine_id": fine.id, "number_plate": plate, "user_id": str(vehicle.owner_id),
                                        "violation_type": violation_type, "fine_amount": fine.fine_amount,
                                        "snapshot": snapshot, "has_clip": clip is not None})
        db.commit()
        result["fines_created"] = len(result["fines"])
        _log(job_id, f"COMMITTED {result['fines_created']} fine(s), {result['unmatched']} unmatched")
    except Exception as error:
        db.rollback()
        result["error"] = f"{type(error).__name__}: {error}"
        _log(job_id, f"ERROR - nothing was saved (rolled back): {result['error']}")
        traceback.print_exc()
    finally:
        db.close()
    return result


def check_tables() -> str:
    """Startup self-check, so a missing migration is visible immediately
    instead of silently losing every fine."""
    db = SessionLocal()
    try:
        fines = db.query(Fine).count()
        db.query(UnmatchedViolation).count()
        return f"ready (fines table has {fines} row(s))"
    except Exception as error:
        return f"NOT READY - run `alembic upgrade head`: {type(error).__name__}: {error}"
    finally:
        db.close()
