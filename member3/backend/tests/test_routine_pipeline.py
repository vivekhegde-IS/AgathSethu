"""Unit tests for the routine-violation pipeline logic (no video/models needed):
two-line plate splitting, duplicate merging, rider association and the
temporal helmet rule.

Run from member3/backend:  python -m pytest tests/test_routine_pipeline.py -q
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.routine_violation_video import plate_ocr  # noqa: E402
from app.services.routine_violation_video.config import RoutineConfig  # noqa: E402
from app.services.routine_violation_video.dual_pipeline import (  # noqa: E402
    RiderStats,
    VehicleTrack,
    VIOLATION_NO_HELMET,
    VIOLATION_TRIPLE_RIDING,
    merge_by_plate,
    merge_tracks,
    pair_score,
    pick_plate_box,
    plates_near_equal,
    rider_is_violator,
    rider_on_motorcycle,
    violation_types,
)

CFG = RoutineConfig()


# ---------------- two-line plate splitting ----------------

def _two_line_plate(top="MP09S", bottom="Y0205", width=220, height=120):
    image = np.full((height, width), 255, np.uint8)
    cv2.putText(image, top, (12, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 4)
    cv2.putText(image, bottom, (12, 108), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 4)
    return image


def test_split_rows_cuts_between_the_two_lines():
    image = _two_line_plate()
    top, bottom = plate_ocr.split_rows(image)
    # line 1 occupies rows ~20-52, line 2 rows ~76-108: the top slice must end
    # before line 2's glyphs and the bottom slice must start after line 1's core
    bottom_start = image.shape[0] - bottom.shape[0]
    assert top.shape[0] <= 76
    assert bottom_start >= 36
    # each half contains ink (a line of text), none is empty
    assert (top < 128).sum() > 200 and (bottom < 128).sum() > 200


def test_two_line_variants_read_top_then_bottom():
    image = _two_line_plate()
    variants = plate_ocr._line_variants(image, True, "")
    names = [name for name, _ in variants]
    assert names[0] == "two-line" and "single" in names
    top, bottom = variants[0][1]
    # top line comes from the upper half, bottom from the lower half
    assert top.shape[0] < image.shape[0] and bottom.shape[0] < image.shape[0]
    assert (top[:30] < 128).sum() > 0 and (bottom[-30:] < 128).sum() > 0


def test_single_line_plate_is_not_split():
    image = np.full((40, 200), 255, np.uint8)
    variants = plate_ocr._line_variants(image, False, "")
    assert [name for name, _ in variants] == ["single"]


def test_quality_gate_rejects_small_and_blurry_crops():
    assert not plate_ocr.passes_quality(np.zeros((8, 20, 3), np.uint8))[0]
    flat = np.full((60, 160, 3), 128, np.uint8)
    assert not plate_ocr.passes_quality(flat)[0]
    sharp = cv2.cvtColor(_two_line_plate(), cv2.COLOR_GRAY2BGR)
    assert plate_ocr.passes_quality(sharp)[0]


# ---------------- plate must belong to the vehicle ----------------

def test_plate_box_must_be_inside_the_vehicle_lower_part():
    moto = (100, 100, 300, 400)
    crop_origin = (0, 0)
    good = ((170, 300, 230, 335), 0.8)      # centre inside, lower part, plate-like
    chrome = ((150, 150, 180, 230), 0.9)    # tall/narrow, upper part
    other_bike = ((400, 300, 460, 335), 0.95)
    picked = pick_plate_box([chrome, other_bike, good], None, crop_origin, moto)
    assert picked[0] == good[0]
    reasons = []
    assert pick_plate_box([chrome, other_bike], None, crop_origin, moto, reasons) is None
    assert len(reasons) == 2


# ---------------- rider association ----------------

def test_person_sitting_on_bike_is_a_rider():
    moto = (100, 200, 260, 400)
    rider = (120, 100, 240, 330)            # head above, body over the bike
    assert rider_on_motorcycle(rider, moto) > 0


def test_person_standing_beside_bike_is_not_a_rider():
    moto = (100, 200, 260, 400)
    beside = (280, 120, 360, 400)           # next to the bike
    assert rider_on_motorcycle(beside, moto) == 0


# ---------------- temporal helmet rule ----------------

def test_single_frame_flicker_is_not_a_violation():
    assert not rider_is_violator(RiderStats(helmet=6, no_helmet=1), CFG)
    assert not rider_is_violator(RiderStats(helmet=0, no_helmet=1), CFG)


def test_k_frames_without_helmet_is_a_violation():
    assert rider_is_violator(RiderStats(helmet=3, no_helmet=5), CFG)


def test_majority_of_judged_frames_is_a_violation():
    assert rider_is_violator(RiderStats(helmet=1, no_helmet=3), CFG)       # 75% of 4
    assert not rider_is_violator(RiderStats(helmet=3, no_helmet=3), CFG)   # 50%


# ---------------- duplicate merging ----------------

def _track(track_id, frames, box, hist_value=1.0):
    track = VehicleTrack(track_id, frames[0], frames[-1], fps=60.0)
    for frame in frames:
        track.boxes[frame] = box
    track.members = [track_id]
    hist = np.full((16, 8), hist_value, np.float32)
    hist[0, 0] += 5
    track.hist = hist
    return track


def test_plates_near_equal():
    assert plates_near_equal("MP09SY0205", "MP09SY0205")
    assert plates_near_equal("MP09SY0205", "HP09SY0205")          # 1 char
    assert not plates_near_equal("MP09SY0205", "HP09SY0285")      # 2 chars
    assert not plates_near_equal("MP04QF926", "MP04QF9260")       # length differs
    assert not plates_near_equal(None, "MP09SY0205")


def _groups(tracks):
    groups, _ = merge_tracks(tracks, {}, 60.0, CFG)
    return sorted(sorted(t.track_id for t in g) for g in groups)


def test_same_bike_fragmented_into_two_tracks_is_merged():
    a = _track("M1", [0, 3, 6, 9], (100, 100, 200, 200))
    b = _track("M2", [30, 33], (120, 105, 222, 208))             # 0.35 s later, nearby
    assert pair_score(a, b, {}, 60.0, CFG).score >= CFG.merge_threshold
    assert _groups([b, a]) == [["M1", "M2"]]


def test_chain_of_fragments_merges_transitively():
    a = _track("M1", [0, 3, 6], (100, 100, 200, 200))
    b = _track("M2", [30, 33], (110, 100, 210, 200))
    c = _track("M3", [60, 63], (120, 100, 220, 200))
    assert _groups([a, b, c]) == [["M1", "M2", "M3"]]


def test_two_bikes_side_by_side_are_not_merged():
    left = _track("M1", [0, 3, 6, 9], (100, 100, 200, 200))
    right = _track("M2", [0, 3, 6, 9], (230, 100, 330, 200))     # same frames, other place
    assert pair_score(left, right, {}, 60.0, CFG).score is None
    assert _groups([left, right]) == [["M1"], ["M2"]]


def test_side_by_side_bikes_are_not_joined_through_a_third_fragment():
    left = _track("M1", [0, 3, 6, 9], (100, 100, 200, 200))
    right = _track("M2", [0, 3, 6, 9], (230, 100, 330, 200))
    later = _track("M3", [30, 33], (160, 100, 260, 200))           # close to both
    groups = _groups([left, right, later])
    assert ["M1", "M2"] not in groups and not any({"M1", "M2"} <= set(g) for g in groups)


def test_box_spanning_two_bikes_is_not_a_duplicate_of_one():
    bike = _track("M1", [0, 3, 6, 9], (100, 100, 200, 200))
    spanning = _track("M2", [6, 9, 12], (100, 100, 330, 200))     # IoU ~0.43 with the bike
    assert pair_score(bike, spanning, {}, 60.0, CFG).score is None


def test_duplicate_track_of_the_same_bike_is_merged():
    a = _track("M1", [0, 3, 6, 9], (100, 100, 200, 200))
    b = _track("M2", [6, 9, 12], (104, 102, 204, 202))            # same place, same time
    assert pair_score(a, b, {}, 60.0, CFG).score >= CFG.merge_threshold


def test_far_late_or_different_looking_tracks_are_not_merged():
    a = _track("M1", [0, 3], (100, 100, 200, 200))
    far = _track("M2", [20, 23], (900, 100, 1000, 200))
    late = _track("M3", [600, 603], (100, 100, 200, 200))        # 10 s gap
    assert pair_score(a, far, {}, 60.0, CFG).score is None
    assert pair_score(a, late, {}, 60.0, CFG).score is None
    other_colour = _track("M4", [20, 23], (105, 100, 205, 200))
    other_colour.hist = np.zeros((16, 8), np.float32)
    other_colour.hist[15, 7] = 10
    same_colour = _track("M5", [20, 23], (105, 100, 205, 200))
    assert pair_score(a, other_colour, {}, 60.0, CFG).score < pair_score(a, same_colour, {}, 60.0, CFG).score


# ---------------- one record per vehicle, a set of violation types ----------------

def test_one_vehicle_record_carries_every_violation_type():
    bike = _track("M1", [0, 3, 6, 9, 12], (100, 100, 200, 200))
    riders = {}
    for pid in ("P1", "P2", "P3"):
        bike.riders[pid] = 5
        riders[pid] = RiderStats()
    riders["P1"] = RiderStats(no_helmet=5, per_frame={f: "no_helmet" for f in (0, 3, 6, 9, 12)})
    riders["P2"] = RiderStats(helmet=5)
    riders["P3"] = RiderStats(no_helmet=1)
    for frame in (0, 3, 6, 9, 12):
        bike.frame_riders[frame] = ["P1", "P2", "P3"]
    found = violation_types(bike, riders, CFG)
    assert set(found) == {VIOLATION_NO_HELMET, VIOLATION_TRIPLE_RIDING}
    assert found[VIOLATION_NO_HELMET] == [0, 3, 6, 9, 12]


def test_two_riders_on_one_bike_give_one_record_not_two():
    bike = _track("M1", [0, 3, 6], (100, 100, 200, 200))
    bike.riders.update({"P1": 3, "P2": 3})
    riders = {"P1": RiderStats(no_helmet=5), "P2": RiderStats(no_helmet=5)}
    for frame in (0, 3, 6):
        bike.frame_riders[frame] = ["P1", "P2"]
    found = violation_types(bike, riders, CFG)
    assert list(found) == [VIOLATION_NO_HELMET]                     # one type, one vehicle


def test_riderless_bike_has_no_violation():
    assert violation_types(_track("M1", [0, 3], (0, 0, 10, 10)), {}, CFG) == {}


# ---------------- recognition-only OCR ----------------

def test_ocr_runs_recognition_only_on_the_crop(monkeypatch):
    """The plate crop goes straight to the recognizer (no text-detection
    stage): one recognizer call with one line image per variant line."""
    calls = []

    class FakeRecognizer:
        def __call__(self, images):
            calls.append([img.shape for img in images])
            return [("MP09SY0205", [0.95] * 10)] * len(images)

    monkeypatch.setattr(plate_ocr, "get_recognizer", lambda: FakeRecognizer())
    crop = cv2.cvtColor(np.full((40, 200), 255, np.uint8), cv2.COLOR_GRAY2BGR)   # single-line
    reads = plate_ocr.read_plate(crop, good_enough=lambda read: True)
    assert len(calls) == 1 and len(calls[0]) == 1                    # stage 1 only
    assert reads[0].text == "MP09SY0205" and reads[0].variant == "single"
    assert len(reads[0].confidences) == 10                           # per-character confidences


def test_ocr_two_line_plate_reads_top_then_bottom(monkeypatch):
    class FakeRecognizer:
        def __call__(self, images):
            return [("MP09S", [0.9] * 5), ("Y0205", [0.9] * 5)][:len(images)]

    monkeypatch.setattr(plate_ocr, "get_recognizer", lambda: FakeRecognizer())
    crop = cv2.cvtColor(_two_line_plate(), cv2.COLOR_GRAY2BGR)
    reads = plate_ocr.read_plate(crop, good_enough=lambda read: True)
    assert reads[0].text == "MP09SY0205" and reads[0].variant == "two-line"


def test_plate_merge_joins_equal_or_one_char_plates_regardless_of_time():
    entries = [
        {"vehicle": _track("M1", [0, 3], (0, 0, 10, 10)), "types": ["NO HELMET"], "plate": "MP09SY0205"},
        {"vehicle": _track("M2", [900, 903], (500, 0, 510, 10)), "types": ["NO HELMET"], "plate": "HP09SY0205"},
        {"vehicle": _track("M3", [60, 63], (0, 0, 10, 10)), "types": ["NO HELMET"], "plate": "MP04ZY2442"},
        {"vehicle": _track("M4", [90, 93], (0, 0, 10, 10)), "types": ["NO HELMET"], "plate": None},
    ]
    merged = merge_by_plate(entries, CFG)
    assert len(merged) == 3
    assert merged[0]["vehicle"].members == ["M1", "M2"]
    assert merged[0]["merged"] is True
