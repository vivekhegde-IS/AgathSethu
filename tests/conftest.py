"""Shared pytest config.

The repo's other suites contain dev-only smoke scripts under
``member3/backend/.../test_*.py`` that require assets removed from this
working copy; they are not part of this feature's suite and must not abort
the collection of the Part 2 tests.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"
sys.path.insert(0, str(BACKEND))

# Silence noisy loggers from the dev smoke suites.
logging.getLogger("routine_violation_video").setLevel(logging.ERROR)
logging.getLogger("app.routers.carla_ws").setLevel(logging.ERROR)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("openvino").setLevel(logging.WARNING)
logging.getLogger("ultralytics").setLevel(logging.ERROR)
