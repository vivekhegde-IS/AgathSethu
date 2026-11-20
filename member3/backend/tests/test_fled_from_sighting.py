"""A crashed car that drives off is shown as fled even when Member 1's escape
report (vehicle_state, escape_confirmed) never arrives: its RFID tag read at
another junction after the crash is enough.

The service test needs no database; the board test needs a *_test database."""

from types import SimpleNamespace

import pytest

from app.services.rfid import service as rfid_service
from app.services.rfid.incidents import IncidentVehicleDraft


def _incident():
    return SimpleNamespace(
        incident_id="inc-1", fled={},
        vehicles=[IncidentVehicleDraft("KA01AT4521", "KA 01 AT 4521", "E200A", sim_vehicle_id="A"),
                  IncidentVehicleDraft("MH12BR7814", "MH 12 BR 7814", "E200B", sim_vehicle_id="B")])


def _sighting(epc, junction="J01"):
    return SimpleNamespace(epc=epc, junction_id=junction, first_seen_ts=104.2)


def test_sighting_marks_the_crashed_car_fled_and_raises_review(monkeypatch):
    announced, notified = [], []
    fake = SimpleNamespace(_announce_suspect=lambda inc, v, esc: announced.append((v.plate_norm, esc["basis"])))
    monkeypatch.setattr(rfid_service, "_notify_escape", lambda message: notified.append(message))
    monkeypatch.setattr(rfid_service.threading, "Thread",
                        lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
    incident = _incident()

    rfid_service.RfidCrossVerification._escape_from_sighting(fake, incident, _sighting("E200A"))
    assert "KA01AT4521" in incident.fled and announced == [("KA01AT4521", "rfid_sighting")]
    assert notified[0]["escape_confirmed"] is True and notified[0]["plate_number"] == "KA01AT4521"
    assert notified[0]["basis"] == "rfid_sighting" and notified[0]["junction_id"] == "J01"

    # a second sighting of the same car (another junction) does not repeat it
    rfid_service.RfidCrossVerification._escape_from_sighting(fake, incident, _sighting("E200A", "J02"))
    assert len(announced) == 1 and len(notified) == 1


def test_unknown_tag_or_already_fled_is_ignored(monkeypatch):
    announced = []
    fake = SimpleNamespace(_announce_suspect=lambda *a: announced.append(a))
    monkeypatch.setattr(rfid_service, "_notify_escape", lambda m: None)
    incident = _incident()
    rfid_service.RfidCrossVerification._escape_from_sighting(fake, incident, _sighting("E200ZZZ"))
    incident.fled["MH12BR7814"] = {"basis": "escape_confirmed"}           # Member 1's report came first
    rfid_service.RfidCrossVerification._escape_from_sighting(fake, incident, _sighting("E200B"))
    assert announced == []


# ── board badge (database) ───────────────────────────────────────────────────────
from conftest import DB_OK, bearer, login  # noqa: E402


@pytest.mark.skipif(not DB_OK, reason="set DATABASE_URL to a *_test database")
def test_board_shows_hit_and_run_from_sighting_without_escape_report(client, fleet):
    from app.core.database import SessionLocal
    from app.models.models import Incident, IncidentVehicle, RfidSighting

    db = SessionLocal()
    try:
        incident = Incident(incident_type="crash", severity="high", status="detected", crash_junction="J03",
                            crash_ts_sim=77.8, source="synthetic", dedupe_key="test-fled-sighting-1")
        db.add(incident)
        db.flush()
        db.add_all([
            IncidentVehicle(incident_id=incident.id, plate_norm="KA01AT4521", epc="E200A", role="involved"),
            IncidentVehicle(incident_id=incident.id, plate_norm="MH12BR7814", epc="E200B", role="involved"),
            RfidSighting(incident_id=incident.id, epc="E200A", plate_norm="KA01AT4521", junction_id="J01",
                         first_seen_ts=104.2, last_seen_ts=106.0, report_count=3, tag_seen_count=3),
        ])
        db.commit()
        incident_id = str(incident.id)
    finally:
        db.close()
    try:
        token = login(client, "authority.admin")
        item = client.get(f"/api/incidents/{incident_id}", headers=bearer(token)).json()["incident"]
        assert item["crash_type"] == "two_car"
        assert item["hit_and_run"] is True and item["left_scene_plates"] == ["KA01AT4521"]
    finally:
        db = SessionLocal()
        try:
            db.query(Incident).filter(Incident.id == incident_id).delete()
            db.commit()
        finally:
            db.close()
