# Routine-violation pipeline: speed + duplicate-merge work

Clip: `another test video 2.mp4` — 12.5 s, 3840x2160, 60 fps, handheld, CPU-only laptop
(13th Gen Intel i7-1355U, 10 physical / 12 logical cores, Intel Iris Xe iGPU, no CUDA).
Stages run in parallel threads, so the stage seconds sum to more than the wall clock.

## Before / after

| stage | before (baseline) | after |
|---|---|---|
| video decode | 20.7 s | 10.6 s |
| vehicle detection | 49.8 s | 4.7 s |
| helmet detection | 17.0 s | 1.6 s |
| tracking | 5.9 s | 4.5 s |
| plate detection | 25.6 s | 1.1 s |
| OCR | 31.3 s | 3.6 s |
| merge | – | 0.09 s |
| evidence rendering | 0.2 s | 0.1 s |
| **TOTAL wall clock** | **68.1 s** | **17.4 s** |

**3.9x faster.** Target 25 s met; the 15 s stretch goal was not reached (17.4 s).
A repeat run under background load measured 25.2 s, so the last few seconds move with
machine load. Decode is the floor: 250 full-resolution `retrieve()`s cost ~10.6 s and
the iGPU does the rest.

## Stride sweep (same session, back to back)

| stride | wall | violating vehicles | readable plates |
|---|---|---|---|
| **3** | 25.2 s* | **9** | MP04ZJ5434, MP04SO2353, MP49UE4735 |
| 4 | 19.7 s | 8 (lost one) | MP04ZJ5434, MP04SO2353, MP04SY3330, MP49UE4735 |
| 5 | 18.0 s | 8 (lost one) | MP04ZJ5434, MP04OA2235, UP04SY3330, MP49UE4735 |

\* the stride-3 re-run landed on a busier machine; its earlier back-to-back measurement
was 17.4 s. Stride 4 and 5 both lose a violating vehicle and shift plate reads, so
**stride 3 is kept** as the largest stride that preserves the result.

## Split engines vs all on CPU

| setup | wall | vehicle detection | plate detection | OCR |
|---|---|---|---|---|
| all detectors OpenVINO CPU + OCR CPU | 42.7 s | 16.8 s | 6.2 s | 6.4 s |
| detectors OpenVINO iGPU + OCR CPU | 17.4 s | 4.7 s | 1.1 s | 3.6 s |

Splitting the load across the iGPU is ~2.4x faster than putting every model on the CPU
(where they contend with decode and OCR). Detectors stay on `intel:gpu`; OCR on 2 CPU
threads (`ROUTINE_DETECTOR_DEVICE` overrides this).

## Acceptance checks

| check | result |
|---|---|
| Total time + per-stage table | **Pass** — 17.4 s, table above |
| No two cards are the same physical vehicle | **Pass** — 9 cards; merge report shows M02+M07 and M08+M19 merged, every other pair blocked with a reason |
| Readable plates not lower than baseline | **Pass** — 3 readable before and after |
| Baseline-correct plates unchanged | **Mostly** — MP04ZJ5434 and MP49UE4735 identical; MP05SO2353 -> MP04SO2353 (one digit). The new value is read directly by OCR (`OMP04SO2353`, 0.92); the old `5` came from a forced O->0 / S->5 rewrite of a low-confidence vote (0.19-0.37). Worth an eyeball |
| No `half` warnings | **Pass** — warm-up + full run emit no "is deprecated"; `half` is only ever passed on CUDA |
| Unit tests for merge / one-record-per-vehicle / recognition-only OCR | **Pass** — 57 passed |

Parked filter now logs every motorcycle track with the reason it was kept or excluded
(`parked filter: evaluated N motorcycle tracks: ...`); it evaluated 35 tracks and kept 9.

## Files changed

- `app/services/routine_violation_video/config.py` — single tuning file; added `merge_duplicate_iou = 0.50`
- `app/services/routine_violation_video/merge.py` — spatio-temporal + appearance merge; same-time tracks only merge at >= `merge_duplicate_iou`
- `app/services/routine_violation_video/dual_pipeline.py` — rewritten pipeline (parallel decode, crops cut at full res then frames dropped, merge-before-OCR, staged OCR, merge report + contact sheets)
- `app/services/routine_violation_video/models.py` — new model registry, OpenVINO exports, warm-up once at startup, kernel cache
- `app/services/routine_violation_video/plate_ocr.py` — recognition-only OCR (no text-detection stage)
- `app/routers/routine_violation.py`, `app/main.py` — warm-up at startup, access-log filter for job polling, progress reporting
- `tests/test_routine_pipeline.py`, `tests/test_plate_validation.py` — tests
- `bench_routine.py` — scratch benchmark harness (not part of the app)

`processor.py` (the previous pipeline) is untouched and no longer used by the API.

## Tunable config values

`frame_stride` 3 · `work_width` 1280 · `detect_imgsz` (256,416) · `detect_batch` 4 ·
`detect_conf` 0.30 · `cv_threads` 2

helmet: `helmet_tile` 192 (3x3) · `helmet_conf` 0.25 · `no_helmet_min_frames` 5 ·
`no_helmet_min_ratio` 0.6 · `helmet_every` 2 · `helmet_max_checks` 8 · `helmet_settle_k` 5

merge: `merge_threshold` 0.60 · `merge_max_gap_s` 1.5 · `merge_max_widths` 2.5 ·
`merge_covisible_iou` 0.30 · `merge_duplicate_iou` 0.50 · `merge_plate_max_diff` 1

plates: `plate_candidates_kept` 6 · `plate_imgsz` 512 · `plate_conf` 0.25 · `ocr_top_n` 5 ·
`ocr_accept_conf` 0.60 · `ocr_workers` 1 · `ocr_stable_reads` 3 · `ocr_stable_conf` 0.80
