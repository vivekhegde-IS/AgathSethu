"""
Unit Tests for Database Engine & Repositories.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from member3.database.db import Base
from member3.database.repository import EventRepository, IncidentRepository, VehicleHistoryRepository


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_save_and_retrieve_event(db_session):
    evt_data = {
        "event_id": "test_evt_001",
        "event_type": "CRASH_DETECTED",
        "timestamp_sim": 102.43,
        "source": "member1",
        "junction_id": "J02",
        "vehicle_id": "V001"
    }
    saved = EventRepository.save_event(db_session, evt_data)
    assert saved.id is not None
    assert saved.event_id == "test_evt_001"

    all_evts = EventRepository.get_all_events(db_session)
    assert len(all_evts) == 1
    assert all_evts[0].event_id == "test_evt_001"


def test_incident_repository(db_session):
    inc = IncidentRepository.save_or_update_incident(
        db=db_session,
        incident_id="INC-999",
        crash_junction="J02",
        crash_timestamp=102.43,
        involved_vehicles=["V001", "V002"],
        suspect_vehicle_id="V002",
        suspect_plate="KA05XY5678",
        last_known_location="J04",
        route_history=["J02", "J03", "J04"]
    )
    assert inc.incident_id == "INC-999"
    assert inc.suspect_vehicle_id == "V002"
    assert inc.last_known_location == "J04"

    fetched = IncidentRepository.get_incident(db_session, "INC-999")
    assert fetched is not None
    assert fetched.suspect_plate == "KA05XY5678"
