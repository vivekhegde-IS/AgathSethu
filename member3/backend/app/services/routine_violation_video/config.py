"""Tuning values for the routine-violation pipeline (one place to adjust)."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class RoutineConfig:
    # ---------------- speed ----------------
    # Process every Nth decoded frame (60 fps video, stride 3 = 20 fps).
    # Skipped frames are only grab()bed (cheap); each processed 4K frame costs
    # ~45 ms to retrieve, which is the floor of the whole pipeline.
    frame_stride: int = 3
    # Width frames are downscaled to (right after decode) for detection and
    # tracking. Full resolution is only used to cut helmet and plate crops.
    work_width: int = 1280
    # Vehicle/person detector (COCO YOLO11n, OpenVINO, static batch of 4
    # letterboxed frames at 256x416). Classes: person + motorcycle only.
    detect_imgsz: tuple = (256, 416)
    detect_batch: int = 4
    detect_conf: float = 0.30
    # OpenCV worker threads while a job runs (resize, optical flow).
    cv_threads: int = 2

    # ---------------- helmet ----------------
    # Rider head crops are packed into a 3x3 mosaic (576 px, static model
    # input) and the helmet model runs once per mosaic.
    helmet_tile: int = 192
    helmet_tiles_per_side: int = 3
    helmet_conf: float = 0.25
    # Temporal rule: a rider is a violator when seen without a helmet in at
    # least K frames, or in >= ratio of the frames where the head was judged
    # (with at least ratio_min_frames such frames). Single flickers never count.
    no_helmet_min_frames: int = 5
    no_helmet_min_ratio: float = 0.6
    no_helmet_ratio_min_frames: int = 3
    # Each rider is checked on every Nth sighting, at most helmet_max_checks
    # times, and no more once helmet_settle_k verdicts either way are in.
    helmet_every: int = 2
    helmet_max_checks: int = 8
    helmet_settle_k: int = 5
    # Heads smaller than this (px, work resolution) or cut by the frame edge
    # are not judged.
    min_person_height: int = 70
    edge_margin: int = 6

    # ---------------- other violations ----------------
    # TRIPLE RIDING: >= 3 riders on the bike in at least this many frames.
    triple_riding: bool = True
    triple_riding_min_frames: int = 3

    # ---------------- tracking ----------------
    # Processed frames a track survives without a detection (track buffer).
    track_max_age: int = 20
    # A person counts as a rider of a motorcycle in >= this share of the
    # main rider's frames on it, and in at least rider_min_frames frames.
    rider_min_share: float = 0.4
    rider_min_frames: int = 3
    # A rider's centre must stay put on the bike (std of offset, in bike
    # widths/heights); pedestrians crossing a parked bike drift more.
    rider_max_offset_std: float = 0.20
    # Parked filter: net vehicle motion relative to the nearby background, in
    # vehicle widths per second. Below this = parked.
    parked_max_speed: float = 0.15
    exclude_static_vehicles: bool = True

    # ---------------- merging duplicates ----------------
    merge_threshold: float = 0.60        # pair score needed to merge
    merge_near_miss: float = 0.15        # pairs this far below are reviewed
    merge_max_gap_s: float = 1.5         # max time between two fragments
    merge_max_widths: float = 2.5        # max predicted-position error (box widths)
    merge_size_ratio: float = 2.2        # area ratio at which size score reaches 0
    merge_covisible_iou: float = 0.30    # seen together below this IoU = two bikes
    merge_duplicate_iou: float = 0.50    # seen together at/above this IoU = one bike, double-detected
    merge_plate_max_diff: int = 1

    # ---------------- plates ----------------
    plate_candidates_kept: int = 6       # vehicle crops kept per track
    plate_imgsz: int = 512               # static model input
    plate_conf: float = 0.25
    ocr_top_n: int = 5                   # sharpest crops OCR'd per vehicle
    ocr_accept_conf: float = 0.60        # a structurally valid read above this skips extra variants
    ocr_workers: int = 1                 # vehicles OCR'd in parallel (1 measured as fast as 3, with half the CPU)
    ocr_stable_reads: int = 3            # stop once this many agree...
    ocr_stable_conf: float = 0.80        # ...with at least this mean conf
    regional_prior: bool = True
    prior_min_plates: int = 2            # plates needed before the prior applies
    prior_min_share: float = 0.5         # share of them with the same state

    # ---------------- output ----------------
    evidence_jpeg_quality: int = 90

    def as_dict(self):
        return asdict(self)


DEFAULT_CONFIG = RoutineConfig()
