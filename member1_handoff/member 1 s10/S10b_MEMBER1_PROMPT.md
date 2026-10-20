# S10b – real-world traffic speeds at night (for Member 1's Claude)

Same code as S10 (run_42): `code/as_run` of S10, i.e. S9c post_run crash detector + the S10
traffic change, `netra_real_traffic.py` and `ngsim_motion_profiles.csv` unchanged.
**Do not change any code.**

## Why
In S10 (clear noon), real speeds made background cars slow at the readers (median 3.9 m/s in
the zones) and NETRA still made 0 wrong matches, also with the real detector's boxes. But the
detector saw every tagged car inside the read zone, so the case we need never happened: a tag on
a SLOW car that the camera does NOT see. In the simulator that case caused wrong matches. At
night the detector misses many cars near the readers (S8: 29 of 36 lost passes), so S10b
should produce that case.

## Run S10b
- Env exactly as S10, except: `NETRA_WEATHER=ClearNight`, `RFID_RNG_SEED=1002`,
  `NETRA_REAL_TRAFFIC_SEED=1002`. `NETRA_REAL_TRAFFIC=1`, `NETRA_PLATE_REAL=1` stay on.
- About 8–10 sim min (about 16–20 real min). Longer is fine.
- Vivek's backend must be running (stream recorded).
- Driving (ego A, manual): normal driving through J01–J03, 3–4 times each, often next to other
  cars, and sometimes slow through a junction or stop near a reader in traffic.
  **No deliberate crashes.**

## Send to Vivek
- The whole run folder as for S10, including the 3 MP4s (needed: the detector runs on them),
  `traffic_speeds.csv`, `collisions_truth.csv`, RUN_NOTES, console.log, code as run.
- **Pack it as a real .zip** (Windows: right-click the folder > Send to > Compressed (zipped)
  folder, or `Compress-Archive`). The S10 file was a tar archive renamed to .zip, which Windows
  shows as empty. Tell Vivek the exact file size in bytes.
