"""
Main Entry Point Runner for Member 3.
Orchestrates event ingestion from Member 1 & Member 2, Virtual RFID simulator,
Evidence Fusion Engine, database persistence, and optional FastAPI/Dashboard server.
"""

import sys
import os
import argparse
import logging
import uvicorn

# Ensure project root is in python path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from member3.config.config import load_member3_config
from member3.database.db import init_db, get_session_direct
from member3.integration.event_ingestion import EventIngestionPipeline
from member3.rfid.simulator import RFIDReaderSimulator
from member3.fusion_engine import EvidenceFusionEngine
from member3.scripts.seed_demo_data import seed_demo_data

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("Member3.Main")


def run_member3_pipeline(mode: str = "DEMO", server: bool = True) -> bool:
    """Executes Member 3 pipeline and optionally launches Police Dashboard server."""
    cfg = load_member3_config()
    db_url = cfg["system"].get("database_url")
    db = init_db(db_url)

    print("\n" + "=" * 60)
    print(f" MEMBER 3 EVIDENCE FUSION & DASHBOARD INITIALIZING (MODE: {mode})")
    print("=" * 60)

    pipeline = EventIngestionPipeline(db=db)
    rfid_sim = RFIDReaderSimulator(reader_id="RFID_J03_R01", junction_id="J03")

    if mode == "DEMO":
        logger.info("[Member 3] Ingesting demo scenario data...")
        seed_demo_data()
    else:
        logger.info("[Member 3] Ingesting live events from Member 1 and Member 2 output files...")
        ingested = pipeline.ingest_from_upstream_files()

        # Trigger RFID scan for suspect V002 at J03
        rfid_evt = rfid_sim.detect_tag("V002", "TAG_V002_99B", "KA05XY5678", 125.10)
        if rfid_evt:
            pipeline.ingest_raw_event(rfid_evt)

        fusion = EvidenceFusionEngine(db=db)
        fusion.run_fusion_pipeline("INC-000001")

    # Retrieve final incident report
    fusion = EvidenceFusionEngine(db=db)
    report = fusion.run_fusion_pipeline("INC-000001")

    print("\n" + "=" * 60)
    print(" FINAL INCIDENT ANALYSIS SUMMARY")
    print("=" * 60)
    print(f" INCIDENT ID:          {report.get('incident_id')}")
    print(f" TYPE:                 {report.get('incident_type')}")
    print(f" CRASH LOCATION:       {report.get('crash_junction')} (t={report.get('crash_timestamp')}s)")
    print(f" INVOLVED VEHICLES:    {report.get('involved_vehicles')}")
    print(f" IDENTIFIED SUSPECT:   {report.get('suspect', {}).get('vehicle_id')} ({report.get('suspect', {}).get('plate_number')})")
    print(f" ROUTE HISTORY:        {' -> '.join(report.get('route_history', []))}")
    print(f" LAST KNOWN LOCATION:  {report.get('last_known_location')} (at t={report.get('last_seen_timestamp_sim')}s)")
    print("=" * 60 + "\n")

    if server:
        host = cfg["system"].get("api_host", "127.0.0.1")
        port = int(cfg["system"].get("api_port", 8000))
        print(f"Starting Police Command Dashboard UI server at: http://{host}:{port}")
        print("Press Ctrl+C to stop the server.\n")
        uvicorn.run("member3.backend.app:app", host=host, port=port, reload=False)

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Member 3 Runner")
    parser.add_argument("--mode", type=str, default="DEMO", choices=["DEMO", "INTEGRATION"], help="Execution mode")
    parser.add_argument("--no-server", action="store_true", help="Do not start Uvicorn web server")
    args = parser.parse_args()

    run_member3_pipeline(mode=args.mode, server=not args.no_server)
