# Member 1 handoff — CARLA script changes

Four small, independent changes to the CARLA script. Nothing else changed:
camera positions, junctions, vehicles, routes, physics, IMU/GNSS rates,
crash detection, the `crash_alert` path, plate overlay position/size/warp and
RFID content are all untouched.

| file | what |
|---|---|
| `full_run.py` | the complete script with ALL four changes (drop-in replacement) |
| `01_anpr_legible_plates.patch` | larger, spaced plate text (`KA 01 AT 4521`), 1.20 x 0.30 m plate face |
| `02_camera_vehicle_boxes.patch` | optional `vehicles` field on `camera_frame` (each car's image box) |
| `03_plain_zero_font.patch` | **plate glyphs from a TrueType font with a plain zero** (fixes 0 read as 8) |
| `04_reliable_rfid_and_escape.patch` | RFID reads + the escape `vehicle_state` are never dropped |
| `overlay_preview_before.png` / `overlay_preview_after.png` | all 8 plates rendered by the script's own overlay code |

Use **either** the full file **or** the patches (in order 01 → 04), not both.

## Change 3 — plain zero (`03_plain_zero_font.patch`)

The plate text was drawn with OpenCV's Hershey font. **Every Hershey font draws
the digit zero with a slash (Ø).** With the heavier strokes of newer OpenCV
(5.x draws ~45% thicker than 4.x) the slashed zero fills in, and at junction
camera size it reads as 8 (`DL 03 EN 6047` -> `DL 83 EN 6047`). The letters are
now rendered from a TrueType font with a plain oval zero; the layout, fitting,
size, colours, border and perspective warp are unchanged.

**Font:** the first one found is used:

1. **Arial Narrow Bold** (`ARIALNB.TTF`) — best in our tests (31-32/32 reads)
2. **Arial Bold** (`arialbd.ttf`) — always part of Windows (31/32)
3. Bahnschrift Bold (`bahnschrift.ttf`, Windows 10+)
4. DejaVu Sans Bold

Nothing needs installing on a normal Windows 10/11 laptop: Arial Bold is
always present, and Arial Narrow comes with most installs (and with Office).
Rendering uses **Pillow**, which is already installed with matplotlib
(`member1/requirements.txt`). If it is somehow missing: `pip install pillow`.

`overlay_preview_before.png` vs `overlay_preview_after.png` show the change:
left = the flat plate, right = the plate at camera size (~84 px wide, x4).

## Change 4 — RFID and escape messages never dropped (`04_reliable_rfid_and_escape.patch`)

`rfid_reading` and the one-off escape `vehicle_state` (`escape_confirmed`) used
to share the 80-slot **drop-oldest** evidence queue with the IMU/GPS flood. In
a live run that crashed at t=557 s the backend received ONE RFID read in the
whole ±30 s crash window, and B's reads at J02/J03 never arrived, so the
incident showed "0 sightings". These messages now go into an unbounded queue
that is sent first. Their content is unchanged; IMU/GPS rate limiting and the
camera queues are unchanged. (Tested without CARLA: with 2000 IMU messages
flooding the queue, the old code lost the RFID read and the escape message, the
new code sends both first.)

The backend now uses the escape `vehicle_state` (your existing
`_post_crash_gps` rule: >= 5 km/h and >= 8 m from the crash point) to identify
the fleeing vehicle.

## Changes 1 and 2

See the earlier notes: 01 makes the plate larger and spaces the groups; 02 adds
`"vehicles": [{"vehicle_id": "B", "bbox": [x1, y1, x2, y2], "depth_m": 31.2}, ...]`
to each `camera_frame` (association metadata only: the plate text still comes
from the backend OCR).

## How to apply

Option A — replace the file (simplest):

```
copy member1_handoff\full_run.py <your CARLA folder>\full_run.py
```

Option B — patch your own copy, in order (the files are CRLF, `--binary` is required):

```
patch -p1 --binary < 01_anpr_legible_plates.patch
patch -p1 --binary < 02_camera_vehicle_boxes.patch
patch -p1 --binary < 03_plain_zero_font.patch
patch -p1 --binary < 04_reliable_rfid_and_escape.patch
```

(run in the folder holding `full_run.py`; the patches also apply to
`vivek_fb.py` / `vivek_fb_rfid.py` copied to that name.)

## Network: point the script at Member 3's laptop

The backend runs on Member 3's laptop. It must be started listening on all
interfaces:

```
cd member3\backend
.\start_backend.ps1 -Port 8001        # = uvicorn app.main:app --host 0.0.0.0 --port 8001
```

The script must use Member 3's laptop address, **never 127.0.0.1**:

* over Tailscale (the script's default): `ws://100.118.103.8:8001/ws/carla/cameras`
* on the same Wi-Fi: `set CARLA_EVIDENCE_WS=ws://192.168.1.34:8001/ws/carla/cameras`
  (that Wi-Fi address can change; check `ipconfig` on Member 3's laptop)

If the connection is refused, allow inbound TCP 8001 in Windows Firewall on
Member 3's laptop.

## What to check when running

Startup console:

```
[SCRIPT] VERSION: V28_ANPR_LEGIBLE_PLATES
[PLATE FONT] ARIALNB.TTF (plain zero)          <- or arialbd.ttf / bahnschrift.ttf
[LIVE WS] endpoint configured: ws://100.118.103.8:8001/ws/carla/cameras
[LIVE WS] camera_frame vehicle boxes: ON (optional 'vehicles' field for plate association)
```

If you see `[PLATE FONT] WARNING: ... falling back to OpenCV Hershey`, run
`pip install pillow` and restart: the zero would be slashed again.

During the run:

* On the camera feed/MP4s, the zeros on the plates are **plain ovals** (no slash).
* After the crash: `[GPS ESCAPE] vehicle=B ...` is printed as before.
* No `[LIVE CAMERA PUBLISH ERROR ...]` lines.
* The crash popup behaves exactly as before.

On Member 3's laptop, the Incident Evidence page shows the fleeing vehicle
(header with plate read, registry plate, status, junctions) and one card per
junction it passed.

Frames recorded BEFORE this change still contain the slashed zero; judge plate
accuracy on a new run.

## Verified here (no CARLA on this machine)

* `python -m py_compile` passes for the patched `full_run.py`, and for
  `vivek_fb.py` / `vivek_fb_rfid.py` with all four patches.
* `vivek_fb.py` + 01..04 reproduces `full_run.py` byte for byte.
* The plate renderer, the vehicle-box helper and the publisher queues were run
  through the script's own code (extracted, without importing carla).

## Change 5 — realistic RFID reports (`05_realistic_rfid_v2.patch`)

For the NETRA runs. Applies to the **V29 manual-driving `full_run.py`**
(`member1/full_run.py`), not to the older full file in this folder.

* `RFID_REALISTIC_MODE` (default **ON**): RFID comes from `rfid_reader_model.py`
  as v2 tag reports (EPC, RSSI, seen count, first/last seen time) - no plate,
  vehicle id or distance in the message. `RFID_REALISTIC_MODE=0` gives the old
  stream back unchanged.
* Readers sit at the CARLA junction bounding-box centres (same as before).
* Reports are `rfid_reading` messages, so they use the reliable queue of change 4.
* New files in `multimodal_evidence/`: `rfid_ground_truth.csv` (which vehicle
  each report really was - never sent), `rfid_reader_positions.json`,
  `camera_poses.json` (exact camera transforms). `rfid_readings.csv` now holds
  the v2 reports.
* Nothing else changes (driving, physics, cameras, overlays, IMU/GPS, crash alert).

**Setup:** copy `rfid_reader_model.py` (repo root) **next to `full_run.py`**, then

```
patch -p0 --binary full_run.py < 05_realistic_rfid_v2.patch
```

(or use `member1/full_run.py` from the repo, which already has it). Check the
start-up log for `[RFID] realistic mode ON: v2 tag reports, run_id=...` and
`[LIVE RFID v2] ... tag report(s)` lines while driving.
