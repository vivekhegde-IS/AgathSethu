from __future__ import annotations

import importlib.util
import logging
import re
import sys
import threading
import uuid
import cv2
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import data_dir
from app.dependencies.deps import require_authority
from app.services.fine_service import record_fines_for_run
from app.services.routine_violation_video import models as routine_models
from app.services.routine_violation_video.dual_pipeline import run_dual_pipeline


class _QuietJobPolling(logging.Filter):
    """The UI polls GET /jobs/{id} every second; keep those out of the
    access log so real requests stay visible."""

    def filter(self, record):
        return "/api/routine-violations/jobs/" not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_QuietJobPolling())


def start_model_warm_up():
    def warm():
        try:
            print(f"[ROUTINE] models warmed up: {routine_models.warm_up()}", flush=True)
        except Exception as error:  # jobs will load lazily instead
            print(f"[ROUTINE] model warm-up failed: {error}", flush=True)

    threading.Thread(target=warm, name="routine-warm-up", daemon=True).start()


# Authority only: uploading a video issues fines.
router = APIRouter(prefix="/api/routine-violations", tags=["Routine Violations"],
                   dependencies=[Depends(require_authority)])

BACKEND_DIR = Path(__file__).resolve().parents[2]
HELMET_AI_DIR = BACKEND_DIR.parent / "HelmetAI"
OUTPUT_DIR = data_dir() / "runtime" / "routine_violations"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
# One folder per processed video: <video_name>_<job>/vehicle_<id>_<plate>.jpg
RUNS_DIR = OUTPUT_DIR / "outputs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)
PIPELINE_LOCK = threading.Lock()
JOB_EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
PIPELINE = None


def load_helmet_pipeline():
    global PIPELINE
    if PIPELINE is not None:
        return PIPELINE
    module_name = "agath_sethu_helmetai_pipeline"
    module = sys.modules.get(module_name)
    if module is None:
        module_path = HELMET_AI_DIR / "app.py"
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load the HelmetAI pipeline.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    PIPELINE = module
    return PIPELINE


def run_pipeline_job(job_id, input_path, output_path, evidence_path, video_name=None):
    print(f"[ROUTINE DEBUG] BACKGROUND WORKER STARTED: {job_id}", flush=True)
    print(f"[ROUTINE DEBUG] VIDEO PATH: {input_path}", flush=True)
    print(f"[ROUTINE DEBUG] VIDEO EXISTS: {input_path.exists()}", flush=True)
    print(f"[ROUTINE DEBUG] VIDEO SIZE: {input_path.stat().st_size if input_path.exists() else 0}", flush=True)
    try:
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "processing"}
        print("[ROUTINE DEBUG] OPENING VIDEO", flush=True)
        capture = cv2.VideoCapture(str(input_path))
        print(f"[ROUTINE DEBUG] VIDEO OPENED: {capture.isOpened()}", flush=True)
        print(f"[ROUTINE DEBUG] FPS: {capture.get(cv2.CAP_PROP_FPS)}", flush=True)
        print(f"[ROUTINE DEBUG] TOTAL FRAMES: {int(capture.get(cv2.CAP_PROP_FRAME_COUNT))}", flush=True)
        capture.release()
        print("[ROUTINE DEBUG] STARTING HELMETAI + ANPR (side by side)", flush=True)
        # Models live in a shared registry, loaded once (warm_up at startup).
        pipeline = None
        stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(video_name or input_path.name).stem).strip("_") or "video"
        run_dir = RUNS_DIR / f"{stem}_{job_id[:8]}"
        def report_progress(update):
            # Polled by the UI via GET /jobs/{job_id}: percent, stage, vehicles found.
            with JOBS_LOCK:
                job = JOBS.setdefault(job_id, {"status": "processing"})
                previous = job.get("progress") or {}
                job["progress"] = {
                    "percent": update.get("percent", previous.get("percent", 0)),
                    "stage": update.get("stage", previous.get("stage", "")),
                    "vehicles_found": (update["vehicles_found"] if update.get("vehicles_found") is not None
                                       else previous.get("vehicles_found", 0)),
                }

        report_progress({"percent": 0, "stage": "queued for processing", "vehicles_found": 0})
        with PIPELINE_LOCK:
            summary = run_dual_pipeline(pipeline, input_path, evidence_path,
                                        run_dir=run_dir, video_name=video_name,
                                        progress=report_progress)
        print("[ROUTINE DEBUG] HELMETAI + ANPR RETURNED", flush=True)
        print("[ROUTINE DEBUG] RESULT RECEIVED", flush=True)
        # Citizen fines for the plates of this run (never raises). Runs before
        # the finally below deletes the upload, so a proof clip can be cut.
        fines = record_fines_for_run(summary, run_dir, video_name or input_path.name, job_id,
                                     video_path=input_path)
        violation =(summary.get("violation_records") or [None])[0]
        vehicles = [
            {**vehicle, "image": f"/api/routine-violations/runs/{run_dir.name}/{vehicle['evidence_file']}"}
            for vehicle in summary.get("vehicles", [])
        ]
        plate_details = {
            "plate_confirmed": bool(violation and violation.get("plate_confirmed")),
            "plate_confidence": violation.get("plate_confidence") if violation else None,
            "plate_frames": violation.get("plate_frames") if violation else 0,
            "state_name": violation.get("state_name") if violation else None,
            "vehicles": vehicles,
            "run_folder": str(run_dir),
            "summary_json": f"/api/routine-violations/runs/{run_dir.name}/summary.json",
            "summary_csv": f"/api/routine-violations/runs/{run_dir.name}/summary.csv",
            "timing": summary.get("timing"),
        }
        print(f"[ROUTINE DEBUG] EVIDENCE GENERATED: {evidence_path if evidence_path.is_file() else 'NONE'}", flush=True)
        with JOBS_LOCK:
            JOBS[job_id] = {
                "status": "completed",
                "result": {
                    "violation_detected": bool(summary.get("violations")),
                    "violation_type": violation.get("violation") if violation else None,
                    "number_plate": violation.get("plate_number") if violation else None,
                    "violation_image": (
                        f"/api/routine-violations/evidence/{evidence_path.name}"
                        if evidence_path.is_file()
                        else None
                    ),
                    **plate_details,
                },
                **plate_details,
                "violation_detected": bool(summary.get("violations")),
                "violation_type": violation.get("violation") if violation else None,
                "number_plate": violation.get("plate_number") if violation else None,
                "violation_image": (
                    f"/api/routine-violations/evidence/{evidence_path.name}"
                    if evidence_path.is_file()
                    else None
                ),
                "violation": violation,
                "summary": summary,
                "fines": fines,
            }
        print("[ROUTINE DEBUG] JOB RESULT STORED", flush=True)
        print("[ROUTINE DEBUG] JOB STATUS = COMPLETED", flush=True)
    except Exception as error:
        print(f"[ROUTINE DEBUG] JOB FAILED: {job_id}", flush=True)
        print(f"[ROUTINE DEBUG] ERROR: {error}", flush=True)
        with JOBS_LOCK:
            JOBS[job_id] = {"status": "failed", "detail": str(error)}
    finally:
        input_path.unlink(missing_ok=True)


@router.post("/detect")
async def detect_routine_violation(video: UploadFile = File(...)):
    extension = Path(video.filename or "").suffix.lower()
    if extension not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Upload a supported video file.")

    job_id = uuid.uuid4().hex
    input_path = OUTPUT_DIR / f"input_{job_id}{extension}"
    output_path = OUTPUT_DIR / f"processed_{job_id}.mp4"
    evidence_path = OUTPUT_DIR / f"violation_{job_id}.jpg"

    try:
        with input_path.open("wb") as destination:
            while chunk := await video.read(1024 * 1024):
                destination.write(chunk)

        with JOBS_LOCK:
            JOBS[job_id] = {"status": "queued"}
        print(f"[ROUTINE DEBUG] JOB CREATED: {job_id}", flush=True)
        JOB_EXECUTOR.submit(
            run_pipeline_job,
            job_id,
            input_path,
            output_path,
            evidence_path,
            video.filename,
        )
        return {"job_id": job_id, "status": "queued"}
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Routine violation processing failed: {error}") from error


@router.get("/jobs/{job_id}")
async def get_routine_violation_job(job_id: str):
    with JOBS_LOCK:
        result = JOBS.get(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Routine violation job not found.")
    if result.get("status") == "failed":
        raise HTTPException(status_code=500, detail=result["detail"])
    return {"job_id": job_id, **result}


@router.get("/runs/{run_name}/{filename}")
async def get_run_file(run_name: str, filename: str):
    path = (RUNS_DIR / run_name / filename).resolve()
    if path.parent.parent != RUNS_DIR.resolve() or not path.is_file() or path.suffix not in {".jpg", ".json", ".csv"}:
        raise HTTPException(status_code=404, detail="Run output not found.")
    media = {".jpg": "image/jpeg", ".json": "application/json", ".csv": "text/csv"}[path.suffix]
    return FileResponse(path, media_type=media, filename=filename if path.suffix != ".jpg" else None)


@router.get("/evidence/{filename}")
async def get_routine_evidence(filename: str):
    evidence_path = OUTPUT_DIR / filename
    if evidence_path.parent != OUTPUT_DIR or not evidence_path.is_file():
        raise HTTPException(status_code=404, detail="Evidence image not found.")
    return FileResponse(evidence_path, media_type="image/jpeg")
