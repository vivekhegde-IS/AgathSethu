# S9c – one live check of the fixed crash detector (for Member 1's Claude)

Vivek checked run_39 / run_40 against collisions_truth.csv (live detector, as it ran):
- car-car contacts caught 7/10; 0 false alerts in 39 next-lane near passes; 1 duplicate
  (single-vehicle alert 3.4 s after A-C).
- missed: A-H gentle rear-end (run_39), A-F parallel side-swipe and A-E GPS lag (run_40).
- static: wall hit caught; **F hit a pole at run_40 t=485.6 s (4130 N*s) - no alert.**
- Your post-run fixes (single-IMU limits, 5 s duplicate suppression, closing-speed waiver
  when both IMUs fire and gap = 0, pending check waits for GPS up to 6 s) only passed a
  replay. They have not run live.

## Before the run
1. Check why F's pole hit gave no single-vehicle alert. The rule must run for every car
   (A-H), not only the ego. Replay run_40 and confirm it now fires at ~485.6 s. Do not
   change any thresholds for this; if it needs a threshold change, say so in RUN_NOTES.
2. Do not change anything else. NETRA_PLATE_REAL=1 stays on.
3. If the instance camera can run without dropping the frame rate, turn it on (plates then
   hide behind other cars). Note in RUN_NOTES whether it was on.

## Run S9c
- Weather ClearNoon, seed 913, about 7-8 sim min (about 15 real min). Env as S9.
- Vivek's backend must be running (stream recorded). Write the real STREAM_ENABLED value
  in RUN_NOTES (run_39/40 said 0, but the stream did arrive).
- Driving (ego A), through J01-J03 3-4 times each, plenty of next-lane passes as before,
  and these contacts, each with its sim time in RUN_NOTES:
  1. very gentle rear-end into a STOPPED car, under 10 km/h (the A-H miss);
  2. parallel side-swipe: drive alongside a car and drift into it (the A-F miss);
  3. normal rear-end at 10-15 km/h;
  4. one hit into a pole or wall at about 30 km/h, away from other cars (single-vehicle).
- No other crashes.

## Send
The whole run folder as for S9 (3 MP4s, all CSVs incl. collisions_truth.csv, console.log,
RUN_NOTES) and the code actually used for the run.
