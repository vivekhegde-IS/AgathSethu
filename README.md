# AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System

[![System Status](https://img.shields.io/badge/System-Ready-success.svg)]()
[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)]()
[![Architecture](https://img.shields.io/badge/Architecture-Event--Driven-orange.svg)]()

A multi-agent, end-to-end incident detection and vehicle tracking system combining IMU crash detection, camera multi-object visual tracking, ANPR plate recognition, virtual RFID checkpoints, real-time evidence fusion, and an interactive Police Dashboard UI.

---

## 📁 Repository Structure & Ownership

```
hit-and-run-detection/
│
├── member1/               # Member 1: IMU Sensor Telemetry & Crash Detection
├── member2/               # Member 2: Vision Pipeline, ANPR & Camera Tracking
├── member3/               # Member 3: RFID Simulator, Evidence Fusion, Backend & Police UI
│   ├── backend/           # FastAPI Backend Server
│   └── dashboard/         # Web-based Police Dashboard UI
│
├── shared/                # Shared Contracts & Configurations
│   ├── config/            # Central demo configuration (demo_config.yaml)
│   ├── schemas/           # Standard JSON Event Schemas
│   ├── examples/          # Sample JSON Payload Examples
│   └── utils/             # Schema validation utilities
│
├── docs/                  # Architecture & Demo Flow Documentation
├── run_demo.py            # Master 1-click demonstration runner
└── README.md
```

---

## 🚀 Quick Start Instructions

### 1. Run Master Demonstration (CLI Mode)
To run the full 7-step multi-junction demo scenario in CLI mode:

```bash
python run_demo.py
```

### 2. Run Police Dashboard & FastAPI Backend Server
To launch the FastAPI backend and web interface:

```bash
python member3/run_member3.py
```

Then open your browser to:
- **Police Dashboard UI**: `http://127.0.0.1:8000/dashboard`
- **FastAPI OpenAPI Docs**: `http://127.0.0.1:8000/docs`

---

## 🧪 Member Independent Verification Commands

### Member 1: Crash Detection
```bash
python member1/run_member1.py --demo
```

### Member 2: Vision Pipeline
```bash
python member2/run_member2.py
```

### Member 3: Virtual RFID & Evidence Fusion
```bash
python member3/rfid_simulator.py
```

### Shared Event Schema Validation
```bash
python shared/utils/event_validator.py
```

---

## 📋 Fixed Demo Results

```
INCIDENT ID          : INC-000001
INCIDENT TYPE        : HIT-AND-RUN
CRASH LOCATION       : J02 (Crash Junction)
INVOLVED VEHICLES    : V001 (KA01AB1234), V002 (KA05XY5678)
SUSPECT VEHICLE      : V002 - Plate: KA05XY5678
VEHICLE ROUTE        : J02 -> J03 -> J04
LAST KNOWN LOCATION  : J04 (Highway Exit)
```
