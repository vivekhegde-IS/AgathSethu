"""Seed the demo data only when the database has no users yet.

Used by the hosted start-ups (render_start.sh, deploy/aws/setup_server.sh):
seed.py replaces the demo users on every run, which must not happen on a
deployment that already has data.

Usage:
    cd backend
    python seed_if_empty.py
"""

from app.core.database import SessionLocal
from app.models.models import User

db = SessionLocal()
try:
    empty = db.query(User).count() == 0
finally:
    db.close()

if empty:
    import seed

    seed.seed_db()
else:
    print("[seed] users already present - skipping demo seed", flush=True)
