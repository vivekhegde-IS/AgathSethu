"""
===================================================================
DEMO DATA SEEDER FOR MEMBER 3
===================================================================
THIS FILE CONTAINS DEMO DATA FOR ISOLATED TESTING AND FALLBACK PRESENTATION.
THIS DATA IS EXPLICITLY LABELED AS DEMO DATA AND IS NOT PRESENTED AS LIVE
MEMBER 1 OR MEMBER 2 OUTPUT.
===================================================================
"""

import sys
import os
import logging

# Ensure parent directory is in path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from member3.database.db import get_session_direct, init_db
from member3.integration.event_ingestion import EventIngestionPipeline
from member3.fusion_engine import EvidenceFusionEngine

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("Member3.DemoSeeder")

# DEMO DATA SET
DEMO_EVENTS = [
    {
        "event_id": "demo_evt_crash_001",
        "event_type": "CRASH_DETECTED",
        "timestamp_sim": 102.43,
        "source": "member1",
        "junction_id": "J02",
        "vehicle_id": "V001",
        "confidence": 0.94,
        "location": {"x": 104.2, "y": 52.7, "z": 0.3},
        "telemetry_summary": {"max_g_force": 6.8, "delta_v_mph": 24.5}
    },
    {
        "event_id": "demo_evt_col_001",
        "event_type": "COLLISION_PAIR_IDENTIFIED",
        "timestamp_sim": 102.45,
        "source": "member2",
        "junction_id": "J02",
        "vehicle_ids": ["V001", "V002"],
        "confidence": 0.91,
        "impact_severity": "HIGH"
    },
    {
        "event_id": "demo_evt_anpr_001",
        "event_type": "ANPR_IDENTIFIED",
        "timestamp_sim": 102.48,
        "source": "member2",
        "junction_id": "J02",
        "camera_id": "CAM_J02_01",
        "vehicle_id": "V001",
        "plate_number": "KA01AB1234",
        "confidence": 0.96
    },
    {
        "event_id": "demo_evt_anpr_002",
        "event_type": "ANPR_IDENTIFIED",
        "timestamp_sim": 102.50,
        "source": "member2",
        "junction_id": "J02",
        "camera_id": "CAM_J02_01",
        "vehicle_id": "V002",
        "plate_number": "KA05XY5678",
        "confidence": 0.97
    },
    {
        "event_id": "demo_evt_rfid_001",
        "event_type": "RFID_DETECTED",
        "timestamp_sim": 125.10,
        "source": "member3",
        "junction_id": "J03",
        "reader_id": "RFID_J03_R01",
        "vehicle_id": "V002",
        "tag_id": "TAG_V002_99B",
        "plate_number": "KA05XY5678"
    },
    {
        "event_id": "demo_evt_cam_001",
        "event_type": "VEHICLE_OBSERVED",
        "timestamp_sim": 145.20,
        "source": "member2",
        "junction_id": "J04",
        "camera_id": "CAM_J04_01",
        "vehicle_id": "V002",
        "plate_number": "KA05XY5678",
        "confidence": 0.92
    }
]


def seed_demo_data() -> bool:
    """Seeds DEMO DATA into Member 3 database and executes fusion engine."""
    print("\n" + "=" * 60)
    print("MEMBER 3 DEMO DATA SEEDER")
    print("==================================================")
    print("Notice: Seeding explicit DEMO DATA into database...\n")

    db = get_session_direct()
    pipeline = EventIngestionPipeline(db=db)

    for raw_evt in DEMO_EVENTS:
        pipeline.ingest_raw_event(raw_evt)

    logger.info(f"[Demo Seeder] Ingested {len(DEMO_EVENTS)} demo events into database.")

    fusion = EvidenceFusionEngine(db=db)
    report = fusion.run_fusion_pipeline("INC-000001")

    print("\n--------------------------------------------------")
    print("DEMO FUSION ANALYSIS RESULT:")
    print("--------------------------------------------------")
    print(f"Incident ID:          {report['incident_id']}")
    print(f"Incident Type:        {report['incident_type']}")
    print(f"Crash Junction:       {report['crash_junction']} (t={report['crash_timestamp']}s)")
    print(f"Involved Vehicles:    {report['involved_vehicles']}")
    print(f"Identified Suspect:   {report['suspect']['vehicle_id']} ({report['suspect']['plate_number']})")
    print(f"Selection Reason:     {report['suspect']['selection_reason']}")
    print(f"Suspect Route:        {' -> '.join(report['route_history'])}")
    print(f"Last Known Location:  {report['last_known_location']} (at t={report['last_seen_timestamp_sim']}s)")
    print("--------------------------------------------------\n")

    return True


if __name__ == "__main__":
    seed_demo_data()
