"""Spawn a detached local backend for smoke testing (dev helper).

Usage: python tools/_spawn_backend.py <port> [logfile]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "8012"
    log = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"/tmp/rfid_backend_{port}.log")
    log.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
         "--port", str(port), "--lifespan", "off", "--log-level",
         os.environ.get("SPAWN_LOG_LEVEL", "info")],
        cwd=str(BACKEND), stdout=handle, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
    )
    print(f"spawned backend pid={proc.pid} on port {port} (log: {log})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
