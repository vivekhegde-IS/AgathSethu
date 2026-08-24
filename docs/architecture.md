# System Architecture Documentation

## Overview

The **AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System** is a distributed, event-driven multi-agent architecture designed for real-time vehicular incident detection, suspect identification, and tracking across urban traffic junctions.

```
 CARLA / Simulation Telemetry
              │
    ┌─────────┴─────────┐
    ▼                   ▼
MEMBER 1            MEMBER 2
Crash Detection     Vision Pipeline
(IMU Sensor)        (ANPR, Collision Pair, Visual Tracking)
    │                   │
    └─────────┬─────────┘
              ▼
           MEMBER 3
   (Virtual RFID, Event Ingestion, Evidence Fusion Engine,
    Database Storage, FastAPI, Police Dashboard UI)
```

---

## Member Ownership Boundaries

| Component | Responsibility | Outputs |
| :--- | :--- | :--- |
| **Member 1** | IMU Telemetry, Crash Signal Processing, $g$-force Thresholding | `CRASH_DETECTED` |
| **Member 2** | Camera Object Tracking, Collision Pair Association, ANPR | `COLLISION_PAIR_IDENTIFIED`, `ANPR_IDENTIFIED`, `VEHICLE_OBSERVED` |
| **Member 3** | Virtual RFID Checkpoints, REST Ingestion, Database, Fusion Engine, Police Dashboard | `RFID_DETECTED`, Incident Dossier (`INC-000001`), Police UI |

---

## Shared Contracts & Event Bus

All communication occurs via strict JSON event schemas located in `shared/schemas/`.

1. `CRASH_DETECTED`: IMU impact alert from Member 1.
2. `COLLISION_PAIR_IDENTIFIED`: Correlated vehicle collision pair from Member 2.
3. `ANPR_IDENTIFIED`: License plate OCR reading from Member 2.
4. `RFID_DETECTED`: Checkpoint RFID tag scan from Member 3.
5. `VEHICLE_OBSERVED`: Visual camera observation at downstream junction from Member 2.
