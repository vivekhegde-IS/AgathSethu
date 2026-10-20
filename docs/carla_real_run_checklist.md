# Real CARLA run for NETRA (Phase 4 data) - checklist

Two laptops: **Member 1** runs CARLA + `full_run.py`, **this laptop** runs the
backend, which receives the stream and records it.

## 1. Before the run

**Member 1's laptop**

1. Use `member1/full_run.py` from this repo (V29 + change 5).
2. Copy `rfid_reader_model.py` (repo root) **next to** `full_run.py`.
3. Point it at this backend (same as before):
   `set CARLA_EVIDENCE_WS=ws://<this laptop's IP>:8001/ws/carla/cameras`
4. Optional, for reproducible RFID: `set RFID_RNG_SEED=<a different number per run>`.

**This laptop** (PowerShell, in `member3\backend`)

```
$env:RFID_NETRA_ENABLED = "1"                          # shadow assessment in every vision result
$env:RFID_RECORD_PATH   = "$PWD\runtime\recordings"    # one JSONL per backend start
mkdir runtime\recordings -Force
.\start_backend.ps1 -Port 8001
```

The backend log must show `[RECORD] recording the CARLA stream to ...`.
Images are not recorded by default (boxes and timestamps are); add
`$env:RFID_RECORD_IMAGES = "1"` only if you also want to re-run the plate
reading offline (large files: ~100 KB per frame).

**Restart the backend between runs** (or at least between sessions) so each
recording file is one session; several CARLA runs in one file also work (they
are split on the sim-time reset).

## 2. During the run - check within the first minute

| Where | Expect |
|---|---|
| Member 1 console | `[RFID] realistic mode ON: v2 tag reports, run_id=...` and `[LIVE RFID v2] N tag report(s) junctions=[J0x]` when a car passes a junction |
| Member 1 console | `[LIVE WS] camera_frame vehicle boxes: ON` |
| Backend console | `[CARLA WS] junction=J0x camera=... frame=...` lines |
| `runtime\recordings\carla_stream_*.jsonl` | growing; `rfid_reading` lines contain `"schema":"rfid_tag_report_v2"`, `camera_frame` lines contain `"vehicles":[...]` |

If `vehicles` is missing in camera frames or RFID lines have no `schema`, stop
and fix before collecting more - NETRA can do nothing without both.

## 3. The runs

| # | What | Length |
|---|---|---|
| 1-3 | Normal crash scenario (A hits B, B escapes through J02/J03) | as usual |
| 4+ | Free driving: A drives through J01-J03 repeatedly, B-H on autopilot. More cars help if the laptop copes | **20-30 min in total** (needed to certify the 2 % error target) |
| extra | A car waiting / stopped at a junction for a while | 1-2 min |
| extra | Two cars crossing a junction side by side | 1-2 min |

## 4. After EACH run (files are overwritten by the next run)

Member 1 copies the whole `multimodal_evidence` folder
(`d:\FINAL_PROJECT\debug_frames\multimodal_evidence` by default) to
`run_01`, `run_02`, ... and sends them. Needed in each:

* `camera_poses.json`, `rfid_reader_positions.json` (exact geometry)
* `rfid_readings.csv`, `rfid_ground_truth.csv`
* `gps_raw_readings.csv`

Plus a note per run: what was done (crash / free driving / stopped car ...),
any env vars set, and anything that went wrong.

From this laptop: `runtime\recordings\*.jsonl` and the backend console log.

## 5. What happens with the data (Phase 4)

```
# how does NETRA do on the real runs, with the exact camera geometry?
python tools/netra_replay.py evaluate runtime/recordings/*.jsonl --run-dir run_01

# calibrate from real runs, keep some runs back for testing
python tools/netra_replay.py calibrate --cal <rec A> <rec B> ... --test <rec C> \
    --run-dir run_01 --out member3/backend/data/netra_calibration.json
```

Then decide, from agreement and certified error on the held-out runs, whether
NETRA may drive `vision.associate()` when no actor ids exist.
