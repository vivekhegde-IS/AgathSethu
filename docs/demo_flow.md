# Demo Flow & Fixed Scenario Specification

## Overview

The 1-Day Demonstration follows a fixed urban traffic scenario across 4 junctions (`J01`, `J02`, `J03`, `J04`) and 2 target vehicles (`V001`, `V002`).

---

## Scenario Timeline

1. **At Junction J02 (Crash Junction)**:
   - Vehicles `V001` (`KA01AB1234`) and `V002` (`KA05XY5678`) collide at $t_{\text{sim}} = 102.43\text{s}$.
   - **Member 1** detects $g$-force spike (> 4.5g) on `V001` IMU sensor and emits `CRASH_DETECTED`.
   - **Member 2** processes bounding box trajectories, detects spatial proximity, and emits `COLLISION_PAIR_IDENTIFIED` (`["V001", "V002"]`).
   - **Member 2** ANPR engine reads suspect plate and emits `ANPR_IDENTIFIED` (`V002` -> `KA05XY5678`).
   - `V001` remains stationary at J02. `V002` flees the scene.

2. **At Junction J03 (East Bypass Checkpoint)**:
   - **Member 3** Virtual RFID reader detects tag `TAG_V002_99B` at $t_{\text{sim}} = 125.10\text{s}$ and emits `RFID_DETECTED`.

3. **At Junction J04 (Highway Exit)**:
   - **Member 2** camera detects vehicle `V002` at $t_{\text{sim}} = 145.20\text{s}$ and emits `VEHICLE_OBSERVED`.

4. **Police Command Center**:
   - Evidence Fusion Engine aggregates evidence.
   - Designates `V002` (`KA05XY5678`) as **SUSPECT**.
   - Traces complete route history: `J02 -> J03 -> J04`.
   - Displays **LAST KNOWN LOCATION**: `J04`.
