"""
Unit Tests for Member 1 and Member 2 Integration Adapters.
"""

import pytest
from member3.integration.member1_adapter import Member1Adapter
from member3.integration.member2_adapter import Member2Adapter


def test_member1_adapter_valid_event():
    adapter = Member1Adapter()
    raw = {
        "event_id": "evt_crash_999",
        "event_type": "CRASH_DETECTED",
        "timestamp_sim": 102.43,
        "source": "member1",
        "junction_id": "J02",
        "vehicle_id": "V001",
        "confidence": 0.94,
        "telemetry_summary": {"max_g_force": 6.8}
    }
    norm = adapter.normalize_crash_event(raw)
    assert norm is not None
    assert norm["event_id"] == "evt_crash_999"
    assert norm["event_type"] == "CRASH_DETECTED"
    assert norm["vehicle_id"] == "V001"
    assert norm["telemetry_summary"]["max_g_force"] == 6.8


def test_member1_adapter_invalid_event():
    adapter = Member1Adapter()
    invalid_raw = {"event_id": "bad_evt"}
    norm = adapter.normalize_crash_event(invalid_raw)
    assert norm is None


def test_member2_adapter_collision_pair():
    adapter = Member2Adapter()
    raw = {
        "event_id": "evt_col_999",
        "event_type": "COLLISION_PAIR_IDENTIFIED",
        "timestamp_sim": 102.45,
        "source": "member2",
        "junction_id": "J02",
        "vehicle_ids": ["V001", "V002"],
        "confidence": 0.92
    }
    norm = adapter.normalize_event(raw)
    assert norm is not None
    assert norm["event_type"] == "COLLISION_PAIR_IDENTIFIED"
    assert norm["vehicle_ids"] == ["V001", "V002"]


def test_member2_adapter_anpr():
    adapter = Member2Adapter()
    raw = {
        "event_id": "evt_anpr_999",
        "event_type": "ANPR_IDENTIFIED",
        "timestamp_sim": 102.50,
        "source": "member2",
        "junction_id": "J02",
        "camera_id": "CAM_J02_01",
        "vehicle_id": "V002",
        "plate_number": "ka05xy5678 ",
        "confidence": 0.97
    }
    norm = adapter.normalize_event(raw)
    assert norm is not None
    assert norm["plate_number"] == "KA05XY5678"
    assert norm["vehicle_id"] == "V002"
