# S9 – crash detector fix + realistic plates (for Member 1's Claude)

Files in this folder: `netra_plate_realism.py` (new, copy next to `netra_full_run.py`).
Everything else stays as in S8 (positions file on, 1 antenna per junction, NETRA_BOX_LOG=1,
NETRA_FRAME_INDEX=1, streaming to ws://100.118.103.8:8001/ws/carla/cameras).

## Why

Vivek checked every crash alert of S1–S8 against the car positions and the ego collision sensor:

* All 11 IMU/GPS crash alerts were false. The two cars were 2.1–3.5 m apart sideways,
  i.e. in the next lane (near passes, overtaking, side-by-side at a light); footprint gap ≥ 0.6 m.
* All 4 real ego hits were missed (run_20 A–F, run_21 A–E, run_27 A–B, run_33 A–B).
* Cause, in the pair gate of the crash detector:
  1. `near_contact = centre distance <= GPS_COLLISION_DISTANCE_M (3.5 m)`. 3.5 m is one lane
     width, so a car in the next lane passes it, but it is less than one car length, so a
     rear-end or front contact (centres ~4.2–4.6 m apart) can never pass it.
  2. `high_relative_motion = max relative speed in the window >= 8 km/h`: two cars passing
     in opposite directions or overtaking have 50–80 km/h relative speed without touching.
  3. `partner_was_moving` / `primary_moving`: three of the four missed hits involved a car
     standing still (you can hit a stopped car).
* Run_29 t≈619 s: A had a 19.9 g IMU spike and dropped from 60 to 5 km/h, but hit no vehicle
  (static object). There is no alert type for single-vehicle crashes.

Plates: `draw_projected_plate` paints a 1.20 x 0.30 m pure-white plate with a black outline
on top of everything, so plate reading looks the same in clear, night and rain. In a pilot on
S2/S8 frames with real-size plates (0.52 x 0.12 m) the backend read 9 % of plates in clear
and 0 % at night and in rain on single frames. A real run is needed to confirm that.

## Changes to make

### A. Crash detector

1. **Ground truth, report only.** Attach a `sensor.other.collision` to every vehicle (A–H),
   not only the ego. Write every event to `collisions_truth.csv`:
   `timestamp_sim, frame, vehicle_id, other (vehicle id, or the static actor type), impulse_Ns`.
   Do not feed it to the detector, the backend or the stream. It is only for evaluation, as
   the ego collision sensor is today.
2. **Contact = footprint gap, not centre distance.** Replace `near_contact` with the gap
   between the two cars' footprints. Use oriented rectangles from each actor's
   `bounding_box.extent` and transform (yaw). Contact: gap <= 0.3 m.
   Keep `GPS_COLLISION_DISTANCE_M` only as a cheap pre-filter (e.g. centres < 8 m).
3. **Closing speed, not relative speed.** Replace `max_relative_speed >= 8` with the closing
   speed: the component of the relative velocity along the line between the two centres,
   positive when they approach. Use its maximum over the 0.5 s before contact.
   Require >= 3 km/h. A car passing in the next lane has ~0 closing speed.
4. **Stopped cars can be hit.** Remove `partner_was_moving`. `primary_moving` becomes:
   either car >= 2 km/h before the event.
5. **Single-vehicle crash.** If one car has an IMU spike >= 5 g and loses >= 15 km/h within
   1 s, and no other car is within 0.3 m, publish a `crash_alert` with
   `status = COLLISION_EVENT_SINGLE_VEHICLE` (no partner).
6. Keep the IMU confirmation and everything else (alert ids, ack, CSV columns) as it is.
   Print the gap and closing speed in the `[COLLISION]` log lines.

### B. Realistic plates (env `NETRA_PLATE_REAL=1`, off by default)

Import `netra_plate_realism as PR` in `netra_full_run.py`, then:

1. Plate geometry: where the plate size is computed (`ANPR_PLATE_WIDTH_M`, `ANPR_PLATE_HEIGHT_M`,
   about line 556 of the old full_run.py), use
   `plate_w_m, plate_h_m = PR.plate_size_m(ANPR_PLATE_WIDTH_M, ANPR_PLATE_HEIGHT_M)`
   instead of the constants.
2. In `draw_projected_plate`, after `warped` and `mask` are computed and before pasting:
   `warped = PR.match_scene(frame, warped, mask, rain=<current precipitation>/100)`.
   `frame` must still be the frame without this plate.
3. Replace `alpha = mask / 255` with `alpha = PR.visible_alpha(mask, instance_ids, actor_id)`.
   Pass the instance-segmentation ids of this camera frame (`netra_sensor_upgrades.instance_ids`)
   and the vehicle's actor id, if the instance camera is running. Otherwise pass `None`, None
   (then the plate is not hidden behind other cars; say so in RUN_NOTES).
4. Draw the black `cv2.polylines` outline only if `PR.draw_outline()`.
5. Plate text, font and everything else stay the same.

Check with `NETRA_PLATE_REAL=0` that a frame looks exactly as before.

## S9 runs

Two runs, about 7–8 simulated minutes each:

| run | weather | seed |
|---|---|---|
| S9a | ClearNight | 911 |
| S9b | HardRainNoon | 912 |

Env as S8, plus `NETRA_PLATE_REAL=1`. Backend must be running (Vivek records the stream).

Driving (manual, ego A):
* Drive normally through J01, J02 and J03, 3–4 times each.
* Drive often right next to other cars in the next lane: overtaking, side by side at a light,
  passing oncoming traffic. These were the false alerts before.
* **Two deliberate gentle contacts per run, away from the junction readers if possible:**
  1. rear-end a car that is stopped or slow, at 10–15 km/h;
  2. a low-speed side scrape (< 15 km/h).
  Note the sim time of each in RUN_NOTES.
* No other deliberate crashes.

Send to Vivek: the whole run folders as in S8 (3 MP4s, vehicle_boxes.csv,
camera_frames_index.csv, crash_alerts.csv, collisions_truth.csv, gps/imu csv,
rfid csv, positions file, console.log, RUN_NOTES with the contact times and whether
the instance camera was on).
