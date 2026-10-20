# NETRA in the RFID cross-verification (shadow mode)

Source: the reference implementation and experiments in `claude try/`
(`netra.py`, `experiments.py`, `results.md`).

## What it replaces (eventually) and what it does now

The vision step must decide **which vehicle in the junction frame carries the
sighted EPC** before reading its plate. Today `vision.associate()` gets that
from the registry: EPC -> `sim_vehicle_id` -> the CARLA actor's box. A real
camera has no actor ids, so that step only works in simulation.

NETRA answers the same question from **RFID reads + camera boxes only**:
it scores every camera track by the whole read-and-miss sequence it implies at
the junction reader, competes the tags one-to-one against the tracks (Hungarian
+ Sinkhorn confidences), and has two explicit "on no visible vehicle"
hypotheses (camera missed the car / stationary tag). An identity is
**CONFIRMED** only when its confidence clears a threshold certified by
selection-conditioned risk control (error among confirmed <= alpha with
probability >= 1 - delta, i.i.d. passes).

**Shadow mode**: with `RFID_NETRA_ENABLED=1`, every vision pass also runs NETRA
and attaches its answer to the `vision_match_result` payload as `netra`
(`status`, `proposed_track`, `track_id`, `confidence`, `threshold`,
`null_kind`, `candidates`, `registry_vehicle_id`, `agrees`). The existing
decision, DB rows and portal behaviour are **unchanged**. Counters:
`netra_assessments`, `netra_agree`, `netra_disagree` (per finalized
sighting), `netra_errors`.

## Files

| File | Role |
|---|---|
| `member3/backend/app/services/rfid/netra/core.py` | The algorithm, copied unchanged from `claude try/netra.py` (simulator + baselines left there) |
| `netra/geometry.py` | Junction camera model (Member 1's placement: J01 35 m back / 6 m right, J02 25 / 6, J03 25 / -8; 5 m up, pitch -15, 65 deg). Box + `depth_m` -> camera-local ground point. No camera yaw needed: the reader footprint is radially symmetric |
| `netra/adapter.py` | v2 TAG_REPORT -> one read per 0.5 s slot it covers; `camera_frame.vehicles` -> one ground track per box id |
| `netra/shadow.py` | `NetraShadow.assess()` for one sighting; loads the calibration |
| `config.py` | `netra_enabled` (default **False**), `netra_calibration`, `netra_reads_margin_s` |
| `service.py` | `_netra_shadow()` called at the top of `_run_vision`; payload key `netra` |
| `member3/backend/data/netra_calibration.json` | Learned read fields per junction + certified threshold |
| `tools/netra_sim.py` | Synthetic junction traffic: project's `rfid_reader_model` (unchanged) + projected camera boxes |
| `tools/netra_calibrate.py` | EM self-calibration, threshold certification, held-out test |
| `tools/netra_scenario_eval.py` | NETRA on the A-H acceptance scenario with the service's windows |
| `tests/test_netra.py` | 14 tests (geometry, adapter, determinism, decisions, service hook) |

`scipy` was added to `member3/backend/requirements.txt`; it is imported only
when the flag is on.

## Results

### Calibration (`python tools/netra_calibrate.py`, alpha = 2 %, delta = 0.1)

6 calibration + 3 held-out runs of 300 s, Poisson traffic at J01-J03 from four
approaches, 90 % tagged, 90 % tracked by the camera, one parked roadside tag
per junction, box noise 3 px, depth noise 0.5 m. Certified threshold
**0.913**.

| Held-out test (649 passes) | Accuracy | Coverage | Error among confirmed |
|---|---|---|---|
| Installer-guess fields, accept all | 82.4 % | 73.7 % | 9.6 % |
| Self-calibrated, accept all | 84.6 % | 74.6 % | 7.9 % |
| **Self-calibrated, certified** | 65.8 % | **49.8 %** | **0.93 %** (3 / 323) |

Per junction (certified): J01 61 % coverage / 0.76 % error, J02 55 % / 0.85 %,
J03 33 % / 1.35 %. All under the 2 % target. "Accuracy" counts a
correctly-unconfirmed pass of a tracked car as wrong, hence the drop.

### Acceptance scenario (`python tools/netra_scenario_eval.py`)

| Junction | Vehicle | NETRA | Confidence |
|---|---|---|---|
| J01 | E, H, A (pre-crash) | CONFIRMED, correct | 0.99 |
| J01 | B (crash moment) | UNCERTAIN (B proposed) | 0.66 |
| J01 | A, stopped after the crash (2 passes) | NOT_ON_VISIBLE_VEHICLE (stationary tag) | - |
| J02 | C, F | CONFIRMED, correct | 0.98-0.99 |
| **J02** | **B (fleeing, next to F)** | **CONFIRMED, B** | 0.97 |
| J03 | D, G | CONFIRMED, correct | 0.99 |
| **J03** | **B (fleeing, next to G)** | **CONFIRMED, B** | 0.99 |

12 passes: 10 proposed, **10 correct**, 9 confirmed, **0 wrong**.

## Limits - read before trusting the numbers

* **Synthetic only.** Calibration and evaluation traffic both come from
  `tools/netra_sim.py`. The guarantee is about traffic that resembles the
  calibration traffic; real CARLA runs (and later real readers) need their own
  calibration run before the threshold means anything.
* **One reader per junction.** NETRA was designed for multi-antenna gantries;
  here it can only use timing and distance-to-reader, not lane. Two vehicles
  crossing the read zone side by side at the same speed stay ambiguous (they
  come out UNCERTAIN, which is the intended behaviour).
* **Stopped vehicles at the reader** fit the stationary-tag null better than
  their own track (the calibration traffic has no stopped cars). The only case
  in the scenario is A at the crash junction, whose reads never become
  sightings, but a car waiting at a red light would hit this too.
* **Camera geometry** is Member 1's code constants; if a camera moves, the
  learned field absorbs small offsets, large ones need re-calibration.
* v2 reports hide misses inside a 0.5 s reporting interval; the slot length
  equals that interval to keep the loss small.

## Next step (not done)

Phase 4 - let NETRA drive association when no actor ids exist (real cameras):
use `track_id` of a CONFIRMED result as the suspect's box id in
`vision.associate()`, fall back to today's path otherwise. Decide after
looking at `netra_agree` / `netra_disagree` on real CARLA runs.
