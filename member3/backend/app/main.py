"""
AGHAT SETHU — Backend Application

FastAPI + SQLAlchemy + Alembic + JWT Authentication
+ CARLA Live Camera WebSocket Integration
"""

import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.dependencies.deps import require_authority
from app.routers import auth
from app.routers import authority_ops
from app.routers import citizen_account
from app.routers import carla_ws
from app.routers import incidents
from app.routers import citizen_fines
from app.routers import routine_violation
from app.routers import webrtc_streams


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown events."""

    print(
        f"[STARTUP] AGHAT SETHU Backend starting — "
        f"env: {settings.APP_ENV}"
    )

    # Load + warm up, once and in the background, the routine-violation models
    # (so the first upload does not pay model load / iGPU kernel compile time)
    # and the ANPR plate adapter used by RFID cross-verification (every
    # detect_and_read() call then reuses the session). ONE thread, one after
    # the other: two OpenVINO warm-ups running at the same time deadlocked the
    # whole process (each held the GIL or an OpenVINO lock the other needed),
    # and the backend stopped answering every request.
    # Never fatal - a missing model must not stop the backend from starting.
    def _warm_models():
        routine_violation.warm_models()
        try:
            from app.services.anpr_adapter import get_anpr_adapter

            print(f"[ANPR] warmed up: {get_anpr_adapter().warm_up()}", flush=True)
        except Exception as error:
            print(f"[ANPR] warm-up failed: {error}", flush=True)

    threading.Thread(target=_warm_models, name="model-warm-up", daemon=True).start()

    # RFID cross-verification: build the service (loads the EPC registry from
    # Postgres) and start its ticker before the first CARLA message arrives.
    def _start_rfid():
        try:
            from app.services.rfid.service import get_service

            service = get_service()
            print(f"[RFID] service ready: registry={len(service.registry)} epcs, "
                  f"crash-junction window {service.cfg.snapshot_before_s:.0f}s", flush=True)
        except Exception as error:
            print(f"[RFID] startup failed: {error}", flush=True)

    threading.Thread(target=_start_rfid, name="rfid-startup", daemon=True).start()

    # Citizen fines: confirm the fines tables exist, so a missing migration
    # shows up at startup instead of as silently lost fines.
    def _check_fines():
        from app.services.fine_service import check_tables

        print(f"[FINES] citizen fines {check_tables()}", flush=True)

    threading.Thread(target=_check_fines, name="fines-check", daemon=True).start()

    yield

    try:
        from app.services.rfid.store import get_persistence

        get_persistence().stop()
    except Exception:
        pass

    await webrtc_streams.close_client()

    print("[SHUTDOWN] AGHAT SETHU Backend shutting down")


app = FastAPI(
    title="AGHAT SETHU API",
    description=(
        "AI-powered Traffic Safety and Incident Response Platform "
        "— Backend API"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────────────────────────
# CORS
# ──────────────────────────────────────────────────────────────────────────────

origins = [
    origin.strip()
    for origin in settings.CORS_ORIGINS.split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # WHEP: the browser must read the session URL (Location) of a WebRTC stream
    expose_headers=["Location", "ETag", "Accept-Patch"],
)


# ──────────────────────────────────────────────────────────────────────────────
# Routers
# ──────────────────────────────────────────────────────────────────────────────

# Existing authentication routes
app.include_router(
    auth.router,
    prefix="/api/auth",
    tags=["Authentication"],
)

# CARLA live camera WebSocket routes
app.include_router(
    carla_ws.router,
    tags=["CARLA WebSocket"],
)

app.include_router(routine_violation.router)

# Citizen fines issued from routine-violation videos (existing citizen login)
app.include_router(citizen_fines.router)

# WebRTC camera streams: WHEP signalling proxy to MediaMTX (authority only)
app.include_router(webrtc_streams.router)

# RFID incident evidence (crash -> crash-zone RFID -> sightings -> ANPR matches)
app.include_router(incidents.router)
app.include_router(incidents.health_router)

# Citizen payments / notifications / crash reports, and authority dashboards
app.include_router(citizen_account.router)
app.include_router(authority_ops.router)


# ──────────────────────────────────────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────────────────────────────────────

# Live ANPR status — verifies real CARLA frames reach the existing
# number-plate detection pipeline (steps.txt Task 8).
@app.get("/api/anpr/live/status", tags=["ANPR"], dependencies=[Depends(require_authority)])
async def live_anpr_status():
    from app.services.live_anpr import get_live_anpr_worker

    return get_live_anpr_worker().status()


# Rule-based plate cards of the live feed (newest first). The Live page loads
# these on open; new/updated cards then arrive as live_plate_detection events.
@app.get("/api/anpr/live/detections", tags=["ANPR"], dependencies=[Depends(require_authority)])
async def live_anpr_detections(junction_id: str | None = None):
    from app.services.live_anpr import get_live_anpr_worker

    return {"detections": get_live_anpr_worker().recent_detections(junction_id)}


@app.get("/api/anpr/live/evidence/{session}/{filename}", tags=["ANPR"], dependencies=[Depends(require_authority)])
async def live_anpr_evidence(session: str, filename: str):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    from app.services.live_anpr import evidence_path

    path = evidence_path(session, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="Live ANPR evidence not found.")
    return FileResponse(path, media_type="image/jpeg")


# ANPR adapter status - the model, device, detection mode and measured latency
# of the single plate adapter used by RFID cross-verification.
@app.get("/api/anpr/adapter/status", tags=["ANPR"], dependencies=[Depends(require_authority)])
async def anpr_adapter_status():
    from app.services.anpr_adapter import get_anpr_adapter

    return get_anpr_adapter().status()


@app.get("/api/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""

    return {
        "status": "ok",
        "service": "AGHAT SETHU API",
        "env": settings.APP_ENV,
    }