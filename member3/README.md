# Member 3: Evidence Fusion, Backend API & Police Dashboard

This directory contains the **Member 3** module for the **AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System**.

---

## 1. Responsibilities & Features

Member 3 acts as the central integration, storage, decision-making, and command UI layer:

- **Integration Adapters** (`member1_adapter.py`, `member2_adapter.py`): Ingests and normalizes external events (`CRASH_DETECTED`, `COLLISION_PAIR_IDENTIFIED`, `ANPR_IDENTIFIED`, `VEHICLE_OBSERVED`) without modifying upstream Member 1 or Member 2 code.
- **Virtual RFID Simulator** (`rfid/simulator.py`): Simulates RFID reader checkpoints (`RFID_J03_R01` at `J03`), tag detection radius, cooldowns, duplicate suppression, and generates `RFID_DETECTED` events.
- **Database Engine & Persistence** (`database/`): SQLAlchemy ORM models and DAO repository supporting PostgreSQL with transparent SQLite fallback (`hit_and_run.db`).
- **Evidence Fusion Engine** (`fusion_engine.py`):
  - Correlates multi-sensor evidence across junctions.
  - Performs evidence-based suspect identification (`V002` fleeing post-crash).
  - Reconstructs chronological route history (`J02 -> J03 -> J04`).
  - Calculates last-known location (`J04`) sorted by simulation timestamp `timestamp_sim`.
- **FastAPI Backend REST API** (`backend/`): RESTful endpoints for event ingestion, incident management, RFID scan triggers, and fusion workflows.
- **Police Command Dashboard UI** (`dashboard/`): High-aesthetic glassmorphism web interface providing real-time hit-and-run alerts, multi-junction timeline maps, suspect details, evidence tables, and live event logs.

---

## 2. Directory Structure

```text
member3/
├── backend/
│   ├── app.py           # FastAPI application
│   ├── models.py        # Pydantic API schemas
│   └── routes.py        # REST API endpoints
├── config/
│   └── config.py        # Member 3 config loader
├── dashboard/
│   ├── index.html       # Police Command Center Web UI
│   └── static/
│       ├── app.js       # Client script & REST API integration
│       └── styles.css   # Modern dark-mode glassmorphic CSS
├── database/
│   ├── db.py            # SQLAlchemy engine & session lifecycle
│   ├── models.py        # ORM models (Event, Incident, Evidence, VehicleHistory)
│   └── repository.py    # Data Access Layer (DAO)
├── integration/
│   ├── event_ingestion.py # Ingestion pipeline manager
│   ├── member1_adapter.py # Member 1 crash event adapter
│   └── member2_adapter.py # Member 2 vision & ANPR event adapter
├── rfid/
│   └── simulator.py     # Virtual RFID checkpoint simulator
├── scripts/
│   └── seed_demo_data.py # Seeder script (EXPLICITLY LABELED DEMO DATA)
├── tests/
│   ├── test_adapters.py # Adapter validation tests
│   ├── test_api.py      # FastAPI endpoints tests
│   ├── test_database.py # Database ORM tests
│   └── test_fusion.py   # Fusion engine tests
├── database.py          # Database shim re-export
├── fusion_engine.py     # Evidence Fusion Engine
├── rfid_simulator.py    # RFID simulator shim re-export
├── run_member3.py       # Main CLI entry point runner
├── requirements.txt
└── README.md
```

---

## 3. How to Run

### Setup Environment
```bash
pip install -r member3/requirements.txt
```

### Run Member 3 Pipeline & Web Server
```bash
python member3/run_member3.py --mode DEMO
```

Access the Police Dashboard UI in browser:
```text
http://127.0.0.1:8000
```

Access API Documentation:
```text
http://127.0.0.1:8000/docs
```

### Run Unit Tests
```bash
pytest member3/tests
```
