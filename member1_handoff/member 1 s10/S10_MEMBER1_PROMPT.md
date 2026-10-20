# S10 – real-world traffic speeds (for Member 1's Claude)

Files in this folder: `netra_real_traffic.py` and `ngsim_motion_profiles.csv`.
Copy both next to `netra_full_run.py`. Everything else stays exactly as in S9c (the
`code/as_run` version, NETRA_PLATE_REAL=1, positions file, NETRA_BOX_LOG=1, NETRA_FRAME_INDEX=1,
backend streaming on).

## Why
NETRA's "missed vehicle" check assumes cars cross the junction at a constant speed. Vivek
measured real traffic (NGSIM, US DOT: real vehicle trajectories every 0.1 s on two city
streets and two freeways). Real cars change speed a lot: on the city streets, a car's speed
over consecutive 80 m stretches varies by 41 % on Lankershim Blvd and 43 % on Peachtree St
(median coefficient of variation per trip).
Today our background cars keep a fairly steady Traffic Manager speed. S10 gives them real
speeds and real speed changes, so we can see whether NETRA still makes no wrong matches.

## Change (env `NETRA_REAL_TRAFFIC=1`, off by default)
1. `import netra_real_traffic as RT` and create one `rng = RT.make_rng()` at start-up.
2. In `release_background_tm(name)`, after the existing Traffic Manager settings, if `RT.ENABLED`:
   `kmh = RT.desired_speed_kmh(rng)`; `tm.set_desired_speed(vehicle, kmh)`; remember `kmh` per car.
   (If your CARLA version has no `set_desired_speed`, use
   `tm.vehicle_percentage_speed_difference(vehicle, 100 * (1 - kmh / speed_limit_kmh))` with the
   road's speed limit, and say which one you used in RUN_NOTES.)
3. Every time a background car passes a junction reader (J01/J02/J03; you already detect the
   pass for the RFID model), if `RT.ENABLED`: `kmh = RT.next_speed_kmh(kmh, rng)` and set it again.
4. Log each speed setting to `traffic_speeds.csv`: `timestamp_sim, vehicle_id, junction, desired_kmh`.
5. Do not change the ego, the crash detector, RFID, cameras or anything else. With
   `NETRA_REAL_TRAFFIC=0` the run must behave exactly as S9c.
6. Leave Traffic Manager's own stopping at lights and keeping distance as it is.

## Run S10
- Weather ClearNoon, seed 1001, about 8 sim min (about 16 real min). Env as S9c plus
  `NETRA_REAL_TRAFFIC=1`, `NETRA_REAL_TRAFFIC_SEED=1001`.
- Vivek's backend must be running (stream recorded).
- Driving (ego A, manual): normal driving through J01–J03, 3–4 times each, often next to
  other cars. **No deliberate crashes in this run** (this run is only about traffic motion).

## Send to Vivek
The whole run folder as for S9 (3 MP4s, vehicle_boxes.csv, camera_frames_index.csv,
crash_alerts.csv, collisions_truth.csv, gps/imu csv, rfid csv, positions file,
traffic_speeds.csv, console.log, RUN_NOTES with which speed call you used), plus the code as run.
