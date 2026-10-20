# RFID -> camera plate cross-verification: audit, Parts 1-2, and status

Feature: for a CARLA crash, take the RFID reads of the involved tags, follow the
tag to the next junction, and confirm the plate with Member 3's own ANPR model.
This document covers **Part 0 (audit)**, **Part 1 (realistic RFID stream)**,
the **ANPR adapter** and **Part 2 (backend, vision verification, portal)**.

Environment note: **CARLA is not installed on this machine** (`import carla`
fails) and there is no recorded `rfid_readings.csv` / `gps_raw_readings.csv`
(the script writes to `d:\FINAL_PROJECT\debug_frames`, which does not exist
here). Part 0 is therefore verified **from the code**, and the offline replay /
acceptance were driven from synthetic trajectories and the one real recorded
junction video that is in the repo.

---

## PART 0 — audit of the current RFID stream

Read: `MultimodalEvidence.update_rfid`, `RFID_*`, `_epc_for`, `LiveEvidencePublisher`
(`publish`, `_next_message`, `ALWAYS_PASS_TYPES`), `random_read`, and the csv writers in
[vivek_fb.py](../vivek_fb.py).

| Your belief | Verdict | Evidence |
|---|---|---|
| Checks all 8 cars against every junction centre after each world tick | **Confirmed** | `update_rfid()` loops `self.junctions` x `self.states`, called once per tick from the main loop |
| Read radius 18 m | **Confirmed** | `RFID_READ_RADIUS_M = 18.0` |
| At most one read per car per junction every 0.25 s | **Confirmed** | `RFID_MIN_READ_INTERVAL_S = 0.25`, keyed on `(name, junction_id)` |
| Flat 98% success chance | **Confirmed** | `RFID_READ_PROBABILITY = 0.98`; on failure it `continue`s (the interval timer was already consumed) |
| Unseeded RNG | **Confirmed** | `random_read()` returns `random.random()`. The comment says "Local deterministic RNG" but **no seed is ever set** - the stream is not reproducible |
| `junction_id` "J01".."J03", `reader_id` "RFID_J02_01" | **Confirmed** | `f"J{junction_id:02d}"`, `f"RFID_J{junction_id:02d}_01"` |
| Published `rfid_reading` carries type, timestamp_sim, frame, event_id, junction_id, reader_id, vehicle_id, plate_number, epc, distance_m, speed_kmh, confidence, status "READ" | **Confirmed** | all 13 fields, exactly as listed |
| Goes into the shared 80-slot drop-oldest queue | **Confirmed, with a correction** | `LIVE_WS_QUEUE_MAX = 80`, `_put_latest` drops the OLDEST on overflow. But the queue it shares is the *evidence* queue (`self.q`), **not** the camera queues - the risk is IMU/GPS/vehicle_state flood (up to ~1600 msg/s), not camera frames |
| Worker serves camera queues first, so RFID can be delayed or dropped | **Partly confirmed** | `_next_message` does try all three camera queues before `self.q`, so cameras are served first, but the drop risk for RFID comes from the evidence queue filling with IMU traffic |
| `ALWAYS_PASS_TYPES` includes rfid_reading | **Confirmed** | `{"crash_alert", "rfid_reading"}` - RFID bypasses the rate limiter but is still subject to queue overflow |
| Every read written to `rfid_readings.csv` before publishing | **Confirmed** | `self.rfid_csv.write(...)` precedes `self.publisher.publish(...)`. Columns: timestamp_sim, event_id, junction_id, reader_id, vehicle_id, plate_number, epc, timestamp_reader, distance_m, speed_kmh, confidence, status |
| EPC formula `E2000017221101 + %02X(index) + %04X(0xA0B0+index)` | **Confirmed** | `_epc_for` is character-for-character what the spec states. A=…01A0B1 … H=…08A0B8 |

Two real defects found, both fixed by Part 1:

1. **The stream is not reproducible** (unseeded `random.random()`).
2. **RFID shares the evidence queue with a 1600 msg/s IMU flood**, so the drop
   path is real even though it is not camera-driven.

`tools/capture_rfid.py` is the audit/recorder. It records any WebSocket stream
to JSONL, or audits a JSONL / a `rfid_readings.csv` directly, and reports fields,
distinct junctions/readers/EPCs, reads per junction/vehicle, the read-interval
distribution and publish-vs-csv (the drop rate). Run it with `--url` when CARLA
is available.

---

## PART 1 — realistic RFID stream

New, CARLA-free module with pure functions shared by the CARLA script, the
offline replay and the simulator: [rfid_reader_model.py](../rfid_reader_model.py).

**Signal model** (documented as *illustrative, not calibrated*):
`RSSI(d) = -30 dBm - 10 * 2.5 * log10(d)`, plus Gaussian shadowing
(sigma = 3 dB). Sensitivity floor **-55 dBm**, which puts the **nominal read
range at exactly 10.0 m** (mean RSSI equals the floor there). Distance is floored
at 1 m so a tag on the antenna cannot report an absurd positive RSSI.

**Read probability** = logistic in the RSSI margin (scale 4 dB) divided by a
speed penalty (`1 + 0.02 * kmh`) and by anti-collision contention
(`1 + 0.6 * (tags_in_field - 1)`). Zero below the floor.

**Inventory / reporting**: one inventory round per world tick (20 Hz); reads are
aggregated per tag and one `rfid_tag_report_v2` message is emitted every 0.5 s
for each tag seen in that interval, with a monotonic `seq` per reader. The v2
message carries **only RF data** - `run_id, seq, reader_id, junction_id,
antenna_id, epc, rssi_dbm, tag_seen_count, first_seen_ts, last_seen_ts,
timestamp_sim, frame` - and deliberately **no** `plate_number`, `vehicle_id`,
`distance_m`, `speed_kmh` or `confidence`. Ground truth goes to a separate
`rfid_ground_truth.csv` keyed by `(reader_id, seq)`. Seeded via `RFID_RNG_SEED`.

Camera coverage check: `camera_coverage_fraction(10.0)` = **1.0**, i.e. the whole
10 m read zone is inside the junction camera frame (5 m up, 25 m back, 65 deg
FOV, 16:9), so vision verification is possible anywhere a tag can be read.

### Part 1 acceptance (`python tools/rfid_acceptance.py`)

Scenario: A and B collide at J01 at t=40 s, A stops there, B escapes through J02
then J03; C-H cross the junctions on their own schedules, with F crossing J02
and G crossing J03 *together with* B (so an uninvolved plate shares the camera
with B). Only A's speed drops to 0 after the crash; B keeps driving. 120 s,
2401 ticks.

Per junction (v2):

| junction | reports | distinct EPCs | reports/s | RSSI min | RSSI max | RSSI mean |
|---|---|---|---|---|---|---|
| J01 | 260 | 4 | 2.167 | -54.30 | -19.60 | -32.09 |
| J02 | 53 | 3 | 0.442 | -54.11 | -25.53 | -42.46 |
| J03 | 82 | 3 | 0.683 | -54.64 | -22.43 | -41.65 |

Legacy vs v2, same trajectories:

| stream | messages | distinct EPCs | messages per (junction, tag) pass |
|---|---|---|---|
| legacy per-read | 1276 | 8 | 127.6 |
| v2 tag reports | 395 | 8 | 39.5 |

A **missed pass** (`miss_next_pass()` or `RFID_PASS_MISS_PROB`) now suppresses
the tag's whole pass, from entering the read field to leaving it. Previously it
dropped only one 0.5 s report interval, so a "missed" car still produced a
sighting. At the default `PASS_MISS_PROB=0` no extra randomness is consumed,
so the stream above is byte-identical to before the change.

Legacy carries `plate_number`/`vehicle_id`/`distance_m`; v2 does not (verified by
a unit test). **Every car inside a junction read zone produced at least one v2
report (8/8, no misses)**, and the same holds for the legacy stream. Determinism:
same seed -> byte-identical stream and ground truth; a different seed -> a
different stream.

### Delivery path

[vivek_fb_rfid.py](../vivek_fb_rfid.py) is a copy of `vivek_fb.py` with
`RFID_REALISTIC_MODE` **defaulting ON**; the original file is untouched so
Member 1's running script is unaffected. With `RFID_REALISTIC_MODE=0` the legacy
message is emitted unchanged.

The publisher gains a **third, dedicated, unbounded RFID queue on its own
WebSocket connection** (`live-rfid-publisher`), drained independently of the
evidence queue and of the camera queues. `crash_alert` (its own connection and
ack) and camera behaviour are unchanged. No acknowledgement handshake - the
per-reader `seq` is what lets the backend detect gaps.

Patch for Member 1: [rfid_realistic_mode.patch](../rfid_realistic_mode.patch),
**6 hunks, RFID-only** (lines 133, 1939, 2326, 2428, 2439, 3697). Both files are
CRLF, so apply with:

```
patch -p0 --binary < rfid_realistic_mode.patch
```

(`-p0` on a copy named `vivek_fb.py`; verified to apply cleanly with `--binary`,
and to *fail* without it - that is a line-ending artefact, not a conflict.)

---

## ANPR adapter

[anpr_adapter.py](../../member3/backend/app/services/anpr_adapter.py) is the ONE
place that loads the plate model or reads plate text.

* **Model**: `member3/backend/models/number_plate/number_plate_detector.pt` -
  Member 3's own Ultralytics YOLO11n detector, single class `number_plate`. It
  returns **boxes only**, so the box is cropped and read with the project's
  existing recognition-only PP-OCRv3 OCR
  (`routine_violation_video.plate_ocr`). Model files are never modified.
  The identical `.pt` also exists at the outer
  `member3/backend/models/number_plate/` (same md5 `86fa942f...`); the adapter
  uses the in-repo one.
* **Backend/device**: Ultralytics YOLO **OpenVINO**, Intel **iGPU** (falls back
  to OpenVINO CPU, then PyTorch). The export is **static 512x512**; the adapter
  reads that from the export's `metadata.yaml` and overrides `imgsz`. *This bit
  me: at `imgsz=640` the iGPU rejects the tensor (`shape=[1,3,512,512]` vs
  `[1,3,640,640]`) and the first version of `detect_and_read` swallowed the error
  and silently returned `[]`. Detection errors are no longer swallowed.*
* **API**: `detect_and_read(frame_bgr) -> list[PlateRead]` with
  `box, plate_text, plate_norm, raw_ocr, det_confidence, ocr_confidence, valid,
  per_char`; plus module-level `detect_and_read(frame)` returning dicts. Loaded
  and warmed up once at startup (background thread in `main.py` lifespan) and
  reused; `GET /api/anpr/adapter/status` reports backend/device/mode/latency.
* **Blind**: it never sees the RFID plate, and it **does not apply a
  regional/majority-state prior** (the demo plates span eight states).
  Position-aware structure fixes are still applied.

### Measured on the recorded junction video

`member3/media/videos/camera_junction_1_v22_final_visible_anpr_recording.mp4`,
1280x720, 12 frames sampled across the clip (`tools/anpr_benchmark.py`):

| mode | detections | frames with a plate | frames with text | mean ms | p50 ms | max ms | best OCR string |
|---|---|---|---|---|---|---|---|
| full frame | 10/12 | 10 | 10 | 317.2 | 162.1 | 2148.3* | `HA4521` |
| **tiled (default)** | 10/12 | 10 | 10 | 199.6 | 213.8 | 226.2 | **`KATA4521`, `KAAA4521`** |
| upscaled 2x | 10/12 | 10 | 10 | 200.9 | 216.0 | 368.2 | `HA4521` |

**Tiling fix (Part 2).** Tiled mode used to cut any plate that crossed a tile
seam (x = 512/640 at 640 px tiles with 20 % overlap). Each half was then OCR'd
as a "plate", and some halves even passed validation. On synthetic 300 px plates
this turned `MH12BR7814` into `0142BR7814` / `2RD7MH12B7`. The tiled detector
now works like SAHI:

* a full-frame pass always runs alongside the tiles;
* tile boxes touching an interior seam (`TILE_SEAM_PX` = 4) are dropped;
* a box mostly inside a larger box is treated as a fragment, and the larger box
  wins.

After the fix, synthetic plates read exactly (`MH12BR7814` 0.99, `GJ05FP3419`
0.97, 160-280 ms). The real clip keeps the small-plate advantage shown above.

\*first call includes lazy OCR engine init; steady state is ~200-240 ms/frame,
of which the detector is ~15 ms and the rest is OCR on the crops.

**Honest accuracy statement:** the detector finds the plate reliably (10/12
frames, ~0.50-0.70 confidence). The truth for this vehicle is `KA 01 AT 4521`
(`KA01AT4521`); the best OCR output is `KAAA4521` (tiled) - the trailing
`4521` and the leading `KA` are recovered, the middle is not, and **no full
10-character mark was produced, so `valid=False` for every frame**. Tiling
measurably beats the full frame and is now the default. Practically: on this
feed the ANPR can support `PROBABLE_MATCH`/`NOT_CONFIRMED` decisions but cannot
be relied on for exact full-plate confirmation at this plate size. Everything
the OCR does recover is retained (`raw_ocr` + `per_char`), because the vision
layer stores every plate it sees.

---

## PART 2 — backend ingestion, incidents, vision verification

### Pipeline (`member3/backend/app/services/rfid/`)

| module | role |
|---|---|
| `config.py` | every tunable (env `RFID_*`), statuses, roles |
| `normalize.py` | legacy + v2 -> one `RfidRead` (event time = `first/last_seen_ts`); per-reader seq gaps/duplicates |
| `registry.py` | `vehicle_registry` seed from the EPC formula; EPC -> plate; unknown EPC -> NULL plate + `UNREGISTERED_TAG` |
| `buffer.py` | 120 s per-junction buffer, kept sorted by event time, ingest cursor, run reset |
| `incidents.py` | alerts -> incidents (merge within 5 s, run-scoped idempotency, run detection, EPC cross-check) |
| `sightings.py` | watchlist hits -> sightings (2 s gap, 2 s close, 10 s cap, enforced at ingest too) |
| `vision.py` | frame ring, per-plate clustering + character voting, status ladder |
| `evidence.py` | JPEG evidence (annotated frame with box + banner, plate crop), sha256 |
| `store.py` | queued Postgres writer: retries while the DB is down, drops (and logs) permanent errors so one bad row never blocks the queue |
| `service.py` | the orchestrator; RX entry points never block, ticker thread, vision executor |

WS wiring (`routers/carla_ws.py`): `rfid_reading` is ingested, camera frames
are ring-buffered, and crash alerts reach the RFID service **after** the ack is
sent. The ack and popup behaviour are unchanged; the global popup dedupe still
acks repeats as `duplicate:true`. API: `routers/incidents.py`. Migrations:
`alembic/versions/002` (tables) and `003` (`rfid_reports.plate_norm` +
`registry_status`); both are applied to the local `Aghat_Sethu` database.

### Scenario results — live backend + Postgres + the real ANPR model

`tools/simulate_carla_feed.py`, all scenarios replayed back to back into one
backend (each replay is a new CARLA run). J01 uses the real recorded clip;
J02/J03 frames are **synthetic** (see limitations).

| run | scenario | outcome |
|---|---|---|
| 1 | normal (v2) | 1 incident, A+B involved, E/H nearby in the crash zone; **B `VISION_CONFIRMED` at J02 (0.99) and J03 (1.00)**, edit distance 0; no sighting for A; `GJ05FP3419` (F) in `all_plates_seen` at J02 and `AP16GQ8273` (G) at J03 |
| 2 | tag swap | `NOT_CONFIRMED` at J02/J03; `KL07DL9182` stored in `all_plates_seen`, B's own plate never seen |
| 3 | missed pass | no J02 sighting, no error; J03 confirmed (v2 and legacy) |
| 4 | unregistered EPC | 181 `rfid_reports` with NULL plate + `UNREGISTERED_TAG`; never sighted; B still confirmed |
| 5 | normal (legacy format) | same verdicts as v2 |

Every sighting got a verdict. Replayed alert IDs created a new incident per
run. Stage logs (`reports -> incidents -> snapshot_rows -> sightings/hits ->
anpr_frames -> statuses`) appear in the server log. A backend restart between
runs, with the DB kept, dropped 0 rows.

### Defects found and fixed while finishing Part 2

* Each vision upgrade minted a new `vision_match` id, but the DB kept the first
  one. Evidence from later upgrades then failed its FK and was dropped.
* Buffers and the frame ring were not reset between runs, and their
  time-sorted bisects broke when sim time jumped back. A run is now detected
  from a v2 `run_id` change, a >5 s sim-time back-jump on the dense streams, or
  a reconnect after a 30 s silence on **every** connection. A retried alert is
  never mistaken for a new run.
* Generated run IDs restarted at `run-0001` after a backend restart. The new
  incident then matched an old row by dedupe key while the service used a fresh
  id, so 47 child rows failed their FKs and were dropped. Generated IDs are now
  per session (`run-<boot stamp>-NNNN`). The first alert adopts the RFID
  stream's `run_id`. Incident ids are `uuid5(dedupe_key)`, so the row and its
  children always agree.
* The sighting cursor was a global event-time watermark, so out-of-order
  reports were lost. It is now an arrival-index cursor.
* A split sighting (gap or 10 s cap) was replaced in its slot before its final
  vision pass. A stalled ticker also let the 20 s frame ring drop frames a
  pending sighting needed. Retired sightings now stay reachable until
  finalized, and frames still needed are protected from pruning.
* `evaluate()` reported the most confident plate in the frame (another car's)
  as `anpr_plate`, voted characters across different vehicles, and could
  "confirm" from one frame. Reads are now clustered per physical plate. The
  candidate is the read matching (or nearest to) the RFID plate. A single frame
  below the 0.85 single-frame bar is `PROBABLE_MATCH`.
* `IncidentAssembler` made the vehicle behind a mismatched alert EPC
  "involved"; it is now only a cross-check warning. The `rfid` logger had no
  handler, so stage logs were invisible.
* A closed sighting with no camera frames at all is recorded as
  `NO_PLATE_VISIBLE` with `frames_used=0`, and logged.

### Portal

New **Incident Evidence** page (`/authority/incident-evidence[/:id]`, sidebar
entry under Level 2). It has an incident list, crash alerts, the watchlist,
crash-junction frames, the crash-zone RFID table, and sightings with status
badges, ANPR details and an evidence gallery (click to zoom). It refreshes live
on `incident_created` / `watchlist_rfid_hit` / `vision_match_result`, using the
same socket as crash alerts. Type-checks clean. It was verified in a browser
against the live backend: all images load, and a replayed run's events appear
live.

### Tests

`python -m pytest tests/ -q` -> **94 passed** (Part 2 unit + in-process
scenario tests with a mocked ANPR, reader-model tests, and one integration test
that runs the real ANPR model through the adapter, skipped if the model file is
missing).

---

## Files added / changed

| file | what |
|---|---|
| `rfid_reader_model.py` | shared reader simulation (signal, inventory, reports, replay, csv); whole-pass misses |
| `vivek_fb_rfid.py` | CARLA copy with `RFID_REALISTIC_MODE` (default ON) |
| `rfid_realistic_mode.patch` | RFID-only patch for Member 1 (ship `rfid_reader_model.py` next to it) |
| `tools/capture_rfid.py` | Part 0 recorder + audit |
| `tools/scenario.py` | shared demo scenario (routes, EPCs, crash) |
| `tools/rfid_acceptance.py` | Part 1 acceptance harness |
| `tools/anpr_benchmark.py` | ANPR mode/latency/accuracy benchmark |
| `tools/simulate_carla_feed.py` | Part 2 feed simulator (v2/legacy, 4 scenarios, fresh `run_id` per run) |
| `tools/_db_smoke.py`, `tools/_spawn_backend.py` | dev helpers (DB inspect/reset, detached backend) |
| `tests/test_rfid_reader_model.py`, `tests/test_part2_rfid.py`, `tests/conftest.py` | test suites |
| `member3/backend/app/services/anpr_adapter.py` | the ANPR adapter (+ SAHI-style tiling fix) |
| `member3/backend/app/services/rfid/*` | the Part 2 pipeline |
| `member3/backend/app/routers/carla_ws.py` | RFID/camera/alert wiring (RFID after the ack) |
| `member3/backend/app/routers/incidents.py` | incidents API + evidence streaming |
| `member3/backend/app/models/models.py` | feature tables |
| `member3/backend/alembic/versions/002_*.py`, `003_*.py` | migrations |
| `member3/backend/app/main.py` | ANPR warm-up, routers |
| `member3/frontend/src/api/incidentEvidence.ts`, `pages/authority/IncidentEvidence.tsx`, `App.tsx`, `components/layout/Sidebar.tsx` | portal view |

`vivek_fb.py` is **unchanged**. The routine-violation pipeline is **unchanged**.

---

## Limitations

* **J02/J03 frames are synthetic** (clean rendered plates). The `VISION_CONFIRMED`
  results there show the pipeline works; they do **not** measure your model's
  accuracy. On the only real CARLA clip (J01, ~50 px plates) the model detects
  10/12 frames but reads `KATA4521` / `KAAA4521` for `KA01AT4521`. At real
  junction plate sizes, expect `PROBABLE_MATCH` / `NOT_CONFIRMED` rather than
  exact confirmation until it is re-measured on real J02/J03 recordings.
* The RSSI model is **illustrative**, not calibrated to hardware (10 m nominal
  range by construction).
* For a tag swap, `anpr_plate` is the read nearest to the registry plate among
  everything visible. The camera cannot know which car carries the tag, so
  `all_plates_seen` is the evidence that matters.
* CARLA is not installed here, so no live CARLA run was captured. Everything
  above was replayed through `simulate_carla_feed.py`.
