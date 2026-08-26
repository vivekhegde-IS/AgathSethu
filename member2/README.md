# Member 2: Computer Vision Pipeline & Collision Identification

This module implements **Member 2** of the **AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System**.

---

## 1. Responsibilities & Scope

Member 2 is strictly responsible for:
1. **Multi-Junction Camera Stream Management**: Standardized junction camera configurations (`CAM_J01_01`, `CAM_J02_01`, `CAM_J03_01`, `CAM_J04_01`).
2. **Vehicle Detection**: Pretrained YOLOv8 vehicle detection (`ultralytics`) with bounding-box extraction.
3. **Multi-Object Tracking**: Stable camera-local track IDs (`TRACK_01`, `TRACK_02`, etc.) via IoU/Kalman association.
4. **Trajectory Recording**: Time-series spatial-temporal trajectory tracking.
5. **Member 1 Integration**: Consuming `CRASH_DETECTED` events from `member1/outputs/events.jsonl`.
6. **Crash-Time Alignment & Explainable Collision Scoring**: Transparent multi-factor collision scoring without ground-truth leakage:
   $$\text{score} = w_1 \cdot \text{proximity} + w_2 \cdot \text{temporal} + w_3 \cdot \text{convergence} + w_4 \cdot \text{velocity\_change} + w_5 \cdot \text{overlap}$$
7. **Automatic Number Plate Recognition (ANPR)**: Plate ROI extraction, preprocessing, EasyOCR recognition, and multi-frame voting aggregation.
8. **Cross-Junction Observation Tracking**: Cross-junction identity association (`J01` → `J02` → `J03` → `J04`).
9. **Event Publishing**: Publishing standardized events (`COLLISION_PAIR_IDENTIFIED`, `ANPR_IDENTIFIED`, `VEHICLE_OBSERVED`) to `member2/outputs/events.jsonl`.

---

## 2. Directory Structure

```text
member2/
├── camera/
│   ├── camera_config.py
│   └── carla_camera.py
├── detection/
│   ├── detector.py
│   └── vehicle_detector.py
├── tracking/
│   ├── tracker.py
│   └── trajectory.py
├── collision/
│   ├── candidate_generation.py
│   └── collision_scorer.py
├── anpr/
│   ├── plate_detector.py
│   ├── ocr.py
│   └── plate_aggregator.py
├── identity/
│   ├── vehicle_identity.py
│   └── cross_camera.py
├── integration/
│   └── member1_event_reader.py
├── events/
│   └── event_publisher.py
├── visualization/
│   └── visualize_tracks.py
├── evaluation/
│   └── evaluate.py
├── config/
│   ├── cameras.yaml
│   └── collision.yaml
├── outputs/
│   └── events.jsonl
├── tests/
│   └── test_member2_pipeline.py
├── run_member2.py
├── requirements.txt
└── README.md
```

---

## 3. How to Run

### Run Full Vision Demo Pipeline
```powershell
python member2/run_member2.py --mode DEMO
```

### Run Automated Unit Tests
```powershell
python -m pytest member2/tests/
```

### Run Evaluation Report
```powershell
python member2/evaluation/evaluate.py
```

---

## 4. Verification & Output Events

Outputs are stored in `member2/outputs/events.jsonl`:
- `COLLISION_PAIR_IDENTIFIED`: Emitted when spatial-temporal multi-factor scoring identifies the crash pair (`V001` ↔ `V002`).
- `ANPR_IDENTIFIED`: Emitted when license plate OCR confirms vehicle plate (`KA01AB1234`, `KA05XY5678`).
- `VEHICLE_OBSERVED`: Emitted when visual tracking observes vehicle at downstream junctions (`J03`, `J04`).
