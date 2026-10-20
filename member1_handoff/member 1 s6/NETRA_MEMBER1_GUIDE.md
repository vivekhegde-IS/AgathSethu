# NETRA data collection — Member 1 guide

Goal: recordings that test every part of NETRA (RFID + camera fusion) in enough
volume to certify the error rate. Nothing here changes driving, physics, crash
detection or the existing messages. Every new feature is OFF unless you switch it on.

## 1. Files you receive

| File | Put it | Replaces |
|---|---|---|
| `rfid_reader_model.py` | next to `netra_full_run.py`, **as `rfid_reader_model.py`** | your `rfid_reader_model_netra.py` copy. Same default stream: verified byte-identical on the test scenario. |
| `netra_reader_positions.json` | next to the script | — (new) |
| `netra_sensor_upgrades.py` | next to the script | — (new) |
| `NETRA_MEMBER1_GUIDE.md` | — | this guide |

## 2. RFID test conditions: no script change needed

Set these before starting the script (PowerShell: `$env:NAME = "value"`):

| Variable | Value | Effect |
|---|---|---|
| `RFID_READER_POSITIONS_FILE` | `netra_reader_positions.json` | readers moved into the camera view (J03's read zone was only 29 % visible) and away from queueing spots |
| `RFID_ANTENNAS_PER_JUNCTION` | `4` | four antennas per junction (6 m around the reader); each is its own reader `RFID_Jnn_01..04` |
| `RFID_ANTENNA_RADIUS_M` | `6` | antenna circle radius |
| `RFID_GHOST_TAGS_PER_JUNCTION` | `2` | stationary roadside tags (EPC `E20000172211EE…`, ground truth `GHOST_Jnn_g`) |
| `RFID_GHOST_DISTANCE_M` | `7` | their distance from the reader |
| `RFID_REPORT_INTERVAL_S` | `0.2` | shorter tag reports (default 0.5) |
| `RFID_CLOCK_OFFSETS_S` | `{"J01":0.3,"J02":-0.2,"J03":0.6}` | reader clocks offset from sim time (tests clock calibration) |
| `RFID_RNG_SEED` | a new number per run | reproducible reads |

The values in effect are written to `rfid_reader_positions.json` → `config` (as before), so every run documents itself.

## 3. Script changes: 5 small insertions in `netra_full_run.py`

Line numbers refer to our copy `member1/full_run.py`; yours is the V31 version, so search
for the quoted code. **If you prefer, send your `netra_full_run.py` and we make an exact
patch instead.**

**3.1 Import and set-up** (top of the file, after the other imports):
```python
import netra_sensor_upgrades as NSU
```
After `world = client.get_world()`:
```python
NSU.apply_weather(world, carla)          # only acts if NETRA_WEATHER is set
```
After the cameras are spawned (right after `camera_poses.json` is written):
```python
box_logger = NSU.BoxLogger(MULTIMODAL_OUT_DIR)      # publisher is attached below
frame_index = NSU.FrameIndex(MULTIMODAL_OUT_DIR)
NSU.write_conditions(MULTIMODAL_OUT_DIR)
```
After `multimodal = MultimodalEvidence(...)` and `multimodal.start()`:
```python
box_logger.publisher = multimodal.publisher
```

**3.2 Box log at the full rate**: in `record_latest_camera_frames()`, right after
`frame_vehicles = visible_vehicle_boxes(...)` (inside its `try`):
```python
box_logger.log(float(world.get_snapshot().timestamp.elapsed_seconds), frame_id, n, frame_vehicles)
```
This writes **every** box to `vehicle_boxes.csv` (lossless) and sends a small
`vehicle_boxes` message per camera per frame. The JPEG `camera_frame` stays throttled as before.

**3.3 Route box messages through the reliable queue**: in the publisher's `publish()`, change
```python
if message.get("type") == "rfid_reading" or message.get("escape_confirmed"):
```
to
```python
if message.get("type") in ("rfid_reading", "vehicle_boxes") or message.get("escape_confirmed"):
```

**3.4 Frame index for the MP4s**: in `record_latest_camera_frames()`, right after
`async_video.write(n, frame)`:
```python
frame_index.log(n, frame_id, float(world.get_snapshot().timestamp.elapsed_seconds))
```

**3.5 Close**: next to `multimodal.close()`:
```python
box_logger.close(); frame_index.close()
```

**Optional 3.6 Occlusion labels** (`NETRA_VISIBILITY=1`, CARLA ≥ 0.9.14): for each junction
camera spawn `NSU.spawn_instance_camera(world, tf, sensor_tick=DT)` with the same `tf`, keep
its newest image per junction in a callback (`NSU.instance_ids(image)` plus `image.frame`),
and before `box_logger.log(...)` call
`frame_vehicles = NSU.add_visible_fraction(frame_vehicles, ids, {name: v.id for name, v in vehicles.items()})`
when the instance frame number equals `frame_id`. This adds `visible_fraction` per box, the
ground truth for "could a real detector see this car".

## 4. Before EVERY run

1. Delete (or move away) `live_evidence_stream.jsonl` and `multimodal_errors.log` in the
   output folder. They are cumulative or stale today: every run folder contained the same
   12-day-old error log and a log reaching back to old sessions.
2. Set a new `RFID_RNG_SEED`.
3. On our side the backend runs the VS Code task `netra` (recording on).

## 5. What to run (sessions)

We measured ≈ 8 RFID passes per simulated minute with 8 vehicles. Minutes below are
**simulated** time (about 2× longer on the wall clock). Calibration and test sessions must be
separate runs, ideally on different days.

| Session | Settings (in addition to `RFID_READER_POSITIONS_FILE`) | Sim minutes | Purpose |
|---|---|---|---|
| S1 calibration | box log + frame index on | 75 (several runs) | main result, calibration set (~600 passes) |
| S2 test | same, **different day / seeds** | 40 | main result, test set (~300 passes) |
| S3 ghost tags | `RFID_GHOST_TAGS_PER_JUNCTION=2` | 20 | stationary-tag null |
| S4 antennas | `RFID_ANTENNAS_PER_JUNCTION=4` | 40 | multi-antenna discrimination |
| S5 short reports | `RFID_REPORT_INTERVAL_S=0.2` | 20 | negative evidence |
| S6 clock offsets | `RFID_CLOCK_OFFSETS_S={"J01":0.3,"J02":-0.2,"J03":0.6}` | 20 | clock calibration |
| S7 stopped cars | **without** the positions file (J01's reader then sits at a queue); also stop the ego for 30–60 s **within 5 m** of a reader | 20 | stopped-car failure mode (runs 07 / 08 never stopped inside the zone) |
| S8 weather | `NETRA_WEATHER=ClearNight`, then `HardRainNoon` (needs 3.1) | 20 each | detector / plate robustness |

Missed vehicles (camera misses a car) are produced offline from S1 / S2, so no special run is needed.

## 6. After EACH run: send

The whole `multimodal_evidence` folder, renamed `run_XX`, with the **new files**:
`vehicle_boxes.csv`, `camera_frames_index.csv`, `netra_conditions.json`, plus as before
`rfid_readings.csv`, `rfid_ground_truth.csv`, `gps_raw_readings.csv`, `camera_poses.json`,
`rfid_reader_positions.json`, `final_validation_summary.json`, `RUN_NOTES.txt`. Also send
the three **MP4 recordings** of that run; with the frame index they let us run the real
vehicle detector, tracker and plate reader offline.

## 7. Quick checks in the first minute

* `[RFID] realistic mode ON` and `[LIVE RFID v2] … tag report(s)`.
* `[NETRA] box log ON` and `vehicle_boxes.csv` growing.
* With ghost tags: reports with EPC `E20000172211EE…` appear in `rfid_readings.csv`.
* With antennas: `reader_id` values `RFID_J01_01 … RFID_J01_04`.
