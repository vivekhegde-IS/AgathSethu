"""
Unit Tests for FastAPI REST Backend Endpoints.
"""

from fastapi.testclient import TestClient
from member3.backend.app import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "UP"


def test_run_demo_endpoint():
    response = client.post("/api/demo/run")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DEMO_COMPLETED"
    assert "incident_report" in data
    assert data["incident_report"]["suspect"]["vehicle_id"] == "V002"
    assert data["incident_report"]["last_known_location"] == "J04"


def test_get_incidents_endpoint():
    # First trigger demo to populate DB
    client.post("/api/demo/run")

    response = client.get("/api/incidents")
    assert response.status_code == 200
    incidents = response.json()
    assert len(incidents) >= 1
    assert incidents[0]["incident_id"] == "INC-000001"
    assert incidents[0]["last_known_location"] == "J04"
