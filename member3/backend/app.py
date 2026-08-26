"""
Member 3 FastAPI Backend Application Entrypoint.
Serves API routes and static Police Dashboard UI.
"""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from member3.config.config import load_member3_config
from member3.database.db import init_db
from member3.backend.routes import router

cfg = load_member3_config()

app = FastAPI(
    title="Hit-and-Run Detection & Tracking API",
    description="Member 3 FastAPI Backend, Evidence Fusion Engine, and Police Dashboard UI Server",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Router
app.include_router(router)

# Mount Dashboard Static Files
dashboard_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
static_dir = os.path.join(dashboard_dir, "static")

if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.on_event("startup")
def startup_event():
    db_url = cfg.get("system", {}).get("database_url")
    init_db(db_url)


@app.get("/", include_in_schema=False)
def serve_dashboard():
    index_path = os.path.join(dashboard_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "message": "Police Dashboard HTML not found. Use API endpoints at /api/incidents or /docs."
    }
