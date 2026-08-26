"""
Unit Tests for Evidence Fusion Engine & Suspect Selection Logic.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from member3.database.db import Base
from member3.integration.event_ingestion import EventIngestionPipeline
from member3.fusion_engine import EvidenceFusionEngine


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_fusion_engine_end_to_end(db_session):
    pipeline = EventIngestionPipeline(db=db_session)

    # Ingest Crash
    pipeline.ingest_raw_event({
        "event_id": "test_crash",
        "event_type": "CRASH_DETECTED",
        "timestamp_sim": 102.43,
        "source": "member1",
        "junction_id": "J02",
        "vehicle_id": "V001"
    })

    # Ingest Collision Pair
    pipeline.ingest_raw_event({
        "event_id": "test_col",
        "event_type": "COLLISION_PAIR_IDENTIFIED",
        "timestamp_sim": 102.45,
        "source": "member2",
        "junction_id": "J02",
        "vehicle_ids": ["V001", "V002"]
    })

    # Ingest ANPR
    pipeline.ingest_raw_event({
        "event_id": "test_anpr",
        "event_type": "ANPR_IDENTIFIED",
        "timestamp_sim": 102.50,
        "source": "member2",
        "junction_id": "J02",
        "vehicle_id": "V002",
        "plate_number": "KA05XY5678"
    })

    # Ingest RFID at J03
    pipeline.ingest_raw_event({
        "event_id": "test_rfid",
        "event_type": "RFID_DETECTED",
        "timestamp_sim": 125.10,
        "source": "member3",
        "junction_id": "J03",
        "vehicle_id": "V002",
        "plate_number": "KA05XY5678"
    })

    # Ingest Vision at J04
    pipeline.ingest_raw_event({
        "event_id": "test_obs",
        "event_type": "VEHICLE_OBSERVED",
        "timestamp_sim": 145.20,
        "source": "member2",
        "junction_id": "J04",
        "vehicle_id": "V002",
        "plate_number": "KA05XY5678"
    })

    fusion = EvidenceFusionEngine(db=db_session)
    report = fusion.run_fusion_pipeline("INC-TEST-01")

    assert report["incident_id"] == "INC-TEST-01"
    assert report["suspect"]["vehicle_id"] == "V002"
    assert report["suspect"]["plate_number"] == "KA05XY5678"
    assert report["route_history"] == ["J02", "J03", "J04"]
    assert report["last_known_location"] == "J04"
