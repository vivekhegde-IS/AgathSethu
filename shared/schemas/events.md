# Shared Event Schemas & Specification

This directory defines the **FIXED** event schemas and contracts shared across Member 1, Member 2, and Member 3 for the **AI-Based Hit-and-Run Accident Detection, Vehicle Identification and Multi-Junction Tracking System**.

---

## 1. Common Header Fields

Every event transmitted across the system MUST include the following standard fields:

| Field Name | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `event_id` | `string` | Unique identifier for the event | `"evt_crash_1024"` |
| `event_type` | `string` | Fixed event type name | `"CRASH_DETECTED"` |
| `timestamp_sim` | `number` | Simulation timestamp in seconds | `102.43` |
| `source` | `string` | Source member identifier (`member1`, `member2`, `member3`) | `"member1"` |

---

## 2. Fixed Event Types & Specs

### 2.1 `CRASH_DETECTED` (Member 1)
Emitted by Member 1 when IMU/telemetry sensors detect an impact exceeding threshold $g$-force.

```json
{
  "event_id": "evt_crash_001",
  "event_type": "CRASH_DETECTED",
  "timestamp_sim": 102.43,
  "source": "member1",
  "junction_id": "J02",
  "vehicle_id": "V001",
  "confidence": 0.94,
  "telemetry_summary": {
    "max_g_force": 6.8,
    "delta_v_mph": 24.5
  }
}
```

### 2.2 `COLLISION_PAIR_IDENTIFIED` (Member 2)
Emitted by Member 2 when visual multi-object tracking detects spatial collision proximity at the crash junction.

```json
{
  "event_id": "evt_col_001",
  "event_type": "COLLISION_PAIR_IDENTIFIED",
  "timestamp_sim": 102.45,
  "source": "member2",
  "junction_id": "J02",
  "vehicle_ids": ["V001", "V002"],
  "confidence": 0.91,
  "impact_severity": "HIGH"
}
```

### 2.3 `ANPR_IDENTIFIED` (Member 2)
Emitted by Member 2 when license plate recognition reads a plate at a junction camera.

```json
{
  "event_id": "evt_anpr_001",
  "event_type": "ANPR_IDENTIFIED",
  "timestamp_sim": 102.50,
  "source": "member2",
  "junction_id": "J02",
  "camera_id": "CAM_J02_MAIN",
  "vehicle_id": "V002",
  "plate_number": "KA05XY5678",
  "confidence": 0.96
}
```

### 2.4 `VEHICLE_OBSERVED` (Member 2)
Emitted by Member 2 when visual camera tracking observes a vehicle moving across a junction.

```json
{
  "event_id": "evt_cam_001",
  "event_type": "VEHICLE_OBSERVED",
  "timestamp_sim": 145.20,
  "source": "member2",
  "junction_id": "J04",
  "camera_id": "CAM_J04_HWY",
  "vehicle_id": "V002",
  "plate_number": "KA05XY5678",
  "confidence": 0.92
}
```

### 2.5 `RFID_DETECTED` (Member 3)
Emitted by Member 3 virtual RFID reader when an RFID tag passes a checkpoint.

```json
{
  "event_id": "evt_rfid_001",
  "event_type": "RFID_DETECTED",
  "timestamp_sim": 125.10,
  "source": "member3",
  "junction_id": "J03",
  "reader_id": "RFID_J03_R01",
  "vehicle_id": "V002",
  "tag_id": "TAG_V002_99B",
  "plate_number": "KA05XY5678"
}
```
