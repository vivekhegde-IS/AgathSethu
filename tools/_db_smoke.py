"""Print the Part 2 cross-verification rows from Postgres (smoke-test helper).

Usage: python tools/_db_smoke.py [limit]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "member3" / "backend"
sys.path.insert(0, str(BACKEND))

# Load .env so DATABASE_URL is available without exporting it.
env_file = BACKEND / ".env"
if env_file.is_file():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from sqlalchemy import create_engine, text  # noqa: E402


def reset(engine) -> None:
    """Delete ONLY the cross-verification rows (keeps unrelated incidents)."""
    order = ("evidence_files", "vision_matches", "rfid_sightings", "crash_zone_rfid",
             "incident_alerts", "incident_vehicles", "rfid_reports")
    with engine.begin() as conn:
        for table in order:
            conn.execute(text(f"delete from {table}"))
        conn.execute(text("delete from incidents where dedupe_key is not null"))
    print("reset: cross-verification rows cleared")


def main() -> int:
    if "--reset" in sys.argv:
        engine = create_engine(os.environ["DATABASE_URL"])
        reset(engine)
        return 0
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        for table in ("incidents", "incident_alerts", "incident_vehicles",
                      "crash_zone_rfid", "rfid_sightings", "vision_matches",
                      "evidence_files", "rfid_reports", "vehicle_registry"):
            count = conn.execute(text(f"select count(*) from {table}")).scalar()
            print(f"{table:20s} {count}")

        print("\n-- latest incidents --")
        for row in conn.execute(text(
                "select id, run_id, crash_junction, crash_ts_sim, dedupe_key "
                "from incidents order by created_at desc limit :n"), {"n": limit}):
            print(" ", dict(row._mapping))

        print("\n-- incident vehicles --")
        for row in conn.execute(text(
                "select incident_id, plate_norm, epc, role from incident_vehicles "
                "order by created_at desc limit :n"), {"n": limit * 3}):
            print(" ", dict(row._mapping))

        print("\n-- crash zone --")
        for row in conn.execute(text(
                "select incident_id, epc, plate_norm, junction_id, report_count, "
                "tag_seen_count, role, peak_rssi_dbm from crash_zone_rfid "
                "order by first_seen_ts limit :n"), {"n": limit * 4}):
            print(" ", dict(row._mapping))

        print("\n-- sightings --")
        for row in conn.execute(text(
                "select id, epc, plate_norm, junction_id, report_count, closed "
                "from rfid_sightings order by first_seen_ts limit :n"), {"n": limit * 4}):
            print(" ", dict(row._mapping))

        print("\n-- vision matches --")
        for row in conn.execute(text(
                "select sighting_id, status, rfid_plate, anpr_plate, anpr_confidence, "
                "edit_distance, frames_used, all_plates_seen, camera_id "
                "from vision_matches order by created_at desc limit :n"), {"n": limit * 4}):
            print(" ", dict(row._mapping))

        print("\n-- evidence --")
        for row in conn.execute(text(
                "select kind, vision_match_id, path, score from evidence_files "
                "order by created_at desc limit :n"), {"n": limit * 4}):
            mapping = dict(row._mapping)
            mapping["path"] = Path(mapping["path"]).name
            print(" ", mapping)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
