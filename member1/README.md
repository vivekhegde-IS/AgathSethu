# Member 1 — Crash Detection & IMU Sensor Simulation Engine

Part of the **AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System**.

---

## 📌 Responsibilities & Architecture

Member 1 is responsible for the upstream simulation and crash detection pipeline:

```text
CARLA / Kinematic Vehicle Dynamics
               │
               ▼
      6-Axis Simulated IMU
               │
               ▼
 Signal Processing & Feature Calculation
               │
               ▼
 Hybrid Explainable Crash Detector Engine
               │
               ▼
      CRASH_DETECTED Event
  (JSONL Output & FastAPI POST)
```

### Key Output
Emits standard `CRASH_DETECTED` events consumable by **Member 2** (Vision/Tracking) and **Member 3** (Backend/Dashboard).

---

## ⚡ Dual-Mode Simulator Architecture

1. **Live CARLA Engine Mode**: Connects to active CARLA server instance on `localhost:2000` via Python API if available.
2. **Kinematic Physics & Offline Simulator Mode**: High-fidelity kinematic physics fallback that simulates 6-axis IMU streams ($a_x, a_y, a_z$ and $g_x, g_y, g_z$) at 50 Hz / 200 Hz with Gaussian noise for vehicles `V001` (KA01AB1234) and `V002` (KA05XY5678) approaching crash junction `J02`.

---

## 🧮 Sensor Signals & Feature Equations

1. **Acceleration Magnitude ($m/s^2$)**:
   $$a_{\text{mag}} = \sqrt{a_x^2 + a_y^2 + a_z^2}$$

2. **G-Force Magnitude ($g$)**:
   $$G = \frac{a_{\text{mag}}}{9.81}$$

3. **Jerk ($g/s$)**:
   $$\text{Jerk} = \frac{\Delta G}{\Delta t}$$

4. **Angular Velocity Magnitude ($rad/s$)**:
   $$\text{gyro}_{\text{mag}} = \sqrt{g_x^2 + g_y^2 + g_z^2}$$

---

## 🛡️ Ground Truth Separation Rule

- **CARLA collision ground truth** is recorded strictly in `member1/outputs/ground_truth.json` for benchmarking.
- The **Crash Detector MUST NOT access ground truth** during inference; decisions are made 100% from simulated IMU telemetry.

---

## 📋 Shared Event Contract (`CRASH_DETECTED`)

Events strictly comply with `shared/schemas/crash_event.json`:

```json
{
  "event_id": "evt_crash_001",
  "event_type": "CRASH_DETECTED",
  "timestamp_sim": 102.43,
  "source": "member1",
  "junction_id": "J02",
  "vehicle_id": "V001",
  "confidence": 0.94,
  "location": {
    "x": 104.2,
    "y": 52.7,
    "z": 0.3
  },
  "telemetry_summary": {
    "max_g_force": 5.8,
    "jerk": 42.1,
    "gyro_magnitude": 3.7,
    "scores": {
      "accel_score": 1.0,
      "jerk_score": 1.0,
      "gyro_score": 0.91
    }
  }
}
```

---

## 🚀 Quickstart Commands

### 1. Run Complete Member 1 Pipeline
Executes vehicle simulation, IMU sensor simulation, crash detection, metric evaluation, and generates telemetry plot:
```bash
python member1/run_member1.py
```

### 2. Run Scenario Demo Script
```bash
python member1/simulation/run_demo.py
```

### 3. Run Benchmark Evaluation
```bash
python member1/evaluation/evaluate.py
```

### 4. Run Unit Tests
```bash
pytest member1/tests/
```

---

## 📁 Output Artifacts

- **Events JSONL**: `member1/outputs/events.jsonl`
- **Ground Truth**: `member1/outputs/ground_truth.json`
- **Telemetry Plot**: `member1/outputs/crash_sensor_plot.png`
