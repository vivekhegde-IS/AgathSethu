"""
AGHAT SETHU — Backend Application
FastAPI + SQLAlchemy + Alembic + JWT Authentication
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown events."""
    print(f"[STARTUP] AGHAT SETHU Backend starting — env: {settings.APP_ENV}")
    yield
    print("[SHUTDOWN] AGHAT SETHU Backend shutting down")


app = FastAPI(
    title="AGHAT SETHU API",
    description="AI-powered Traffic Safety and Incident Response Platform — Backend API",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ────────────────────────────────────────────────────────────────────────
origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])


@app.get("/api/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "AGHAT SETHU API", "env": settings.APP_ENV}
