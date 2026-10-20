"""Archive or purge feature incidents (RFID cross-verification) - DRY RUN by default.

Selects incidents by source and/or run, shows exactly what would be touched
(incident rows, child rows, evidence files on disk), and changes NOTHING unless
an action AND --yes are given:

    python tools/purge_incidents.py --source synthetic                  # dry run (default)
    python tools/purge_incidents.py --source synthetic --archive --yes  # set archived=true
    python tools/purge_incidents.py --run run-0001 --purge --yes        # delete rows + files

--archive only flips incidents.archived (reversible with --unarchive --yes).
--purge deletes the incident and its child rows (ON DELETE CASCADE) and the
evidence files under runtime/incident_evidence/<incident_id>/. Rows not created
by this feature (no dedupe_key) are never selected.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "member3" / "backend"
EVIDENCE_ROOT = BACKEND / "runtime" / "incident_evidence"
env_file = BACKEND / ".env"
if env_file.is_file():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

CHILD_TABLES = (
    ("evidence_files", "incident_id = :id"),
    ("vision_matches", "sighting_id IN (SELECT id FROM rfid_sightings WHERE incident_id = :id)"),
    ("rfid_sightings", "incident_id = :id"),
    ("crash_zone_rfid", "incident_id = :id"),
    ("incident_alerts", "incident_id = :id"),
    ("incident_vehicles", "incident_id = :id"),
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=("live", "replay", "synthetic"), default=None)
    parser.add_argument("--run", action="append", default=[], help="run_id (repeatable)")
    parser.add_argument("--include-archived", action="store_true")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--archive", action="store_true")
    action.add_argument("--unarchive", action="store_true")
    action.add_argument("--purge", action="store_true")
    parser.add_argument("--yes", action="store_true", help="actually do it (otherwise dry run)")
    args = parser.parse_args(argv)
    if not args.source and not args.run:
        parser.error("select something: --source and/or --run")

    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ["DATABASE_URL"])
    where = ["dedupe_key IS NOT NULL"]
    params: dict = {}
    if args.source:
        where.append("source = :source")
        params["source"] = args.source
    if args.run:
        where.append("run_id = ANY(:runs)")
        params["runs"] = list(args.run)
    if not args.include_archived and not args.unarchive:
        where.append("archived = false")
    sql = (f"SELECT id, run_id, source, crash_junction, crash_ts_sim, archived, created_at "
           f"FROM incidents WHERE {' AND '.join(where)} ORDER BY created_at")

    with engine.connect() as conn:
        incidents = [dict(r) for r in conn.execute(text(sql), params).mappings().all()]
        if not incidents:
            print("nothing selected")
            return 0
        totals = {table: 0 for table, _ in CHILD_TABLES}
        files = 0
        for incident in incidents:
            for table, condition in CHILD_TABLES:
                totals[table] += conn.execute(
                    text(f"SELECT count(*) FROM {table} WHERE {condition}"),
                    {"id": incident["id"]}).scalar()
            folder = EVIDENCE_ROOT / str(incident["id"])
            if folder.is_dir():
                files += sum(1 for p in folder.rglob("*") if p.is_file())
            print(f"  {incident['id']}  {incident['run_id']}  {incident['source']}  "
                  f"{incident['crash_junction']} t={incident['crash_ts_sim']}  "
                  f"archived={incident['archived']}  created={str(incident['created_at'])[:19]}")

    mode = "archive" if args.archive else "unarchive" if args.unarchive else \
        "PURGE" if args.purge else "dry run"
    print(f"\n{len(incidents)} incident(s) selected; child rows: {totals}; "
          f"evidence files on disk: {files}")
    if not (args.archive or args.unarchive or args.purge) or not args.yes:
        print(f"[{mode}] nothing changed (add --archive / --unarchive / --purge AND --yes to act)")
        return 0

    with engine.begin() as conn:
        ids = [incident["id"] for incident in incidents]
        if args.archive or args.unarchive:
            conn.execute(text("UPDATE incidents SET archived = :flag WHERE id = ANY(:ids)"),
                         {"flag": bool(args.archive), "ids": ids})
            print(f"[{mode}] {len(ids)} incident(s) updated")
            return 0
        for incident_id in ids:
            for table, condition in CHILD_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE {condition}"), {"id": incident_id})
            conn.execute(text("DELETE FROM incidents WHERE id = :id"), {"id": incident_id})
    for incident_id in ids:
        folder = EVIDENCE_ROOT / str(incident_id)
        if folder.is_dir():
            shutil.rmtree(folder)
    print(f"[PURGE] {len(ids)} incident(s) and their evidence deleted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
