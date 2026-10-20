#!/usr/bin/env bash
# Starts the AGHAT SETHU backend reliably (Git Bash / macOS / Linux).
#
#   bash start_backend.sh          # port 8000
#   PORT=8001 bash start_backend.sh
#
# Fixes the usual "backend won't load" causes:
#   1. frees the port from a stale/hung uvicorn ([WinError 10048]),
#   2. uses the project's .venv Python (the system Python lacks the deps),
#   3. starts uvicorn against app.main:app.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8000}"

# 1) Free the port from any stale listener.
if command -v netstat >/dev/null 2>&1; then
    stale=$(netstat -ano 2>/dev/null | grep -E "[:.]$PORT[[:space:]]+.*LISTENING" | awk '{print $NF}' | sort -u || true)
    for pid in $stale; do
        [ -n "$pid" ] || continue
        echo "Port $PORT in use by PID $pid - stopping it"
        taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" >/dev/null 2>&1 || true
    done
fi
if [ -n "${stale:-}" ]; then sleep 1; fi

# 2) Pick the venv Python.
if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"      # Windows venv (Git Bash)
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"              # POSIX venv
else
    echo "ERROR: virtualenv not found. Create it: python -m venv .venv && pip install -r requirements.txt" >&2
    exit 1
fi

# 3) Run.
echo "Starting backend on http://127.0.0.1:$PORT (python: $PY)"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
