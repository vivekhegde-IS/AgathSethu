"""Unit tests for rule-based partial ANPR (app/services/anpr_partial.py).

Run from member3/backend:  python -m pytest tests/test_anpr_partial.py -q

"Unreadable" characters are modelled the way the OCR reports them: emitted
with a confidence below the threshold (position known -> "_"), or not emitted
at all (length unknown -> "*" / "+").
"""

import itertools
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.anpr_partial import (  # noqa: E402
    UNKNOWN_CONF_THRESHOLD,
    analyze_reads,
    candidate_plates,
    describe_pattern,
    match_pattern,
    parse_pattern,
    parse_rfid_partial,
    pattern_regex,
    patterns_overlap,
)

HI, LO = 0.95, 0.30


def read(text, confs=None, frame=1, track="M1"):
    return {"text": text, "confidences": confs or [HI] * len(text), "frame": frame, "track_id": track}


def analyze(text, confs=None):
    return analyze_reads([read(text, confs)])


def masked(plate, unknown_positions):
    return [LO if i in unknown_positions else HI for i in range(len(plate))]


# ── KA 05 AT 3514: every combination of unreadable segments ───────────────────────
KA = "KA05AT3514"
SEGMENTS = {"state": (0, 1), "rto": (2, 3), "series": (4, 5), "number": (6, 7, 8, 9)}
SEGMENT_TEXT = {"state": "KA", "rto": "05", "series": "AT", "number": "3514"}


@pytest.mark.parametrize("hidden", [c for n in range(5) for c in itertools.combinations(SEGMENTS, n)],
                         ids=lambda c: "+".join(c) or "none")
def test_every_combination_of_unreadable_segments(hidden):
    positions = {p for name in hidden for p in SEGMENTS[name]}
    result = analyze(KA, masked(KA, positions))
    expected = " ".join("_" * len(SEGMENT_TEXT[n]) if n in hidden else SEGMENT_TEXT[n] for n in SEGMENTS)
    assert result["partial_pattern"] == expected
    assert result["is_complete"] is (not hidden)
    # the real plate always matches (no assumption ever excludes it) ...
    assert re.fullmatch(result["regex"], KA)
    assert match_pattern(result["partial_pattern"], KA) > 0
    # ... and every character shown is one that was actually read
    for name in SEGMENTS:
        if name not in hidden:
            assert result["segments"][name]["value"] == SEGMENT_TEXT[name]
        else:
            assert all(u["allowed_type"] == result["segments"][name]["char_type"]
                       for u in result["segments"][name]["unknowns"])


@pytest.mark.parametrize("positions,expected", [
    ({2, 3}, "KA __ AT 3514"),          # RTO unreadable
    ({4, 5, 6, 7, 8, 9}, "KA 05 __ ____"),  # only state + RTO visible
    ({8, 9}, "KA 05 AT 35__"),          # last 2 digits unreadable
    ({0, 1, 2, 3, 4, 5}, "__ __ __ 3514"),  # only last 4 digits visible
    ({1}, "K_ 05 AT 3514"),             # single character
    ({0, 3, 5, 9}, "_A 0_ A_ 351_"),    # scattered characters
])
def test_spec_examples_and_single_characters(positions, expected):
    result = analyze(KA, masked(KA, positions))
    assert result["partial_pattern"] == expected
    assert re.fullmatch(result["regex"], KA)


def test_every_single_unreadable_character_is_marked_in_place():
    for i in range(len(KA)):
        result = analyze(KA, masked(KA, {i}))
        flat = result["partial_pattern"].replace(" ", "")
        assert flat == KA[:i] + "_" + KA[i + 1:], (i, result["partial_pattern"])


def test_threshold_is_configurable():
    confs = [HI] * 8 + [0.5, 0.5]
    assert analyze_reads([read(KA, confs)], threshold=0.6)["partial_pattern"] == "KA 05 AT 35__"
    assert analyze_reads([read(KA, confs)], threshold=0.4)["partial_pattern"] == "KA 05 AT 3514"
    assert UNKNOWN_CONF_THRESHOLD == 0.60


# ── characters not emitted at all: unknown length -> "*" / "+" ────────────────────
@pytest.mark.parametrize("text,expected", [
    ("KA05", "KA 05 *+ _*+"),        # series (0-3) and number (1-4) never read
    ("3514", "__ _+ *+ 3514"),       # state exactly 2, RTO 1-2, series 0-3
    ("AT3514", "__ _+ +AT 3514"),    # series may have one more letter before AT
    ("KA05AT35", "KA 05 AT 35*"),    # 2 digits read: 0-2 more may follow
    ("KA05AT351", "KA 05 AT 351+"),  # 3 digits read: maybe one more
])
def test_unread_regions_use_variable_length_notation(text, expected):
    result = analyze(text)
    assert result["partial_pattern"] == expected
    assert result["is_complete"] is False
    assert re.fullmatch(result["regex"], KA)


def test_short_number_is_not_assumed_complete():
    # "KA05AT35" is rule-valid but may be a truncated read of KA05AT35xx
    result = analyze("KA05AT35")
    assert result["is_complete"] is False
    assert re.fullmatch(result["regex"], "KA05AT35")
    assert re.fullmatch(result["regex"], "KA05AT3514")


# ── single-letter series / single-digit RTO ───────────────────────────────────────
def test_single_letter_series_mh_4_c_1234():
    result = analyze("MH4C1234")
    assert result["partial_pattern"] == "MH 4 C 1234"
    assert result["is_complete"] is True
    assert result["plate"] == "MH4C1234"
    assert result["segments"]["rto"]["value"] == "4"
    assert result["segments"]["series"]["value"] == "C"


def test_single_letter_series_with_unreadable_characters():
    result = analyze("MH4C1234", masked("MH4C1234", {4, 5}))
    assert result["partial_pattern"] == "MH 4 C __34"
    assert re.fullmatch(result["regex"], "MH4C1234")


# ── BH series ─────────────────────────────────────────────────────────────────────
def test_bh_series_complete():
    result = analyze("22BH1234AA")
    assert result["format"] == "bh"
    assert result["partial_pattern"] == "22 BH 1234 AA"
    assert result["is_complete"] is True
    assert set(result["segments"]) == {"year", "bh", "number", "series"}


def test_bh_series_partial():
    result = analyze("22BH1234AA", masked("22BH1234AA", {0, 1, 8}))
    assert result["partial_pattern"] == "__ BH 1234 _A"
    assert result["regex"] == r"^\d{2}BH1234[A-HJ-NP-Z]A$"
    assert re.fullmatch(result["regex"], "22BH1234AA")


def test_bh_format_is_never_assumed_without_reading_b_or_h():
    result = analyze("1234", None)
    assert result["format"] == "standard"


# ── "*" and "+" notation (RFID and ANPR share it) ─────────────────────────────────
@pytest.mark.parametrize("pattern,regex", [
    ("MH 4 C _34", r"^MH4C\d34$"),
    ("MH +4+ _ 3*4", r"^MH(?:4|4\d|\d4)[A-HJ-NP-Z]3\d{0,2}4$"),
    ("KA __ AT 3514", r"^KA\d{2}AT3514$"),
    ("KA _+ AT 3514", r"^KA\d{1,2}AT3514$"),
    ("KA 05 *+ _*+", r"^KA05[A-HJ-NP-Z]{0,3}\d{1,4}$"),
    ("22 BH 1234 A+", r"^22BH1234A[A-HJ-NP-Z]{0,1}$"),
])
def test_pattern_regex(pattern, regex):
    assert pattern_regex(pattern) == regex


def test_plus_means_at_most_one_and_segment_length_is_enforced():
    # "+4+" in a 1-2 digit RTO: 4, x4 or 4x - never x4x
    assert match_pattern("MH +4+ C 1234", "MH4C1234") > 0
    assert match_pattern("MH +4+ C 1234", "MH14C1234") > 0
    assert match_pattern("MH +4+ C 1234", "MH41C1234") > 0
    assert match_pattern("MH +4+ C 1234", "MH141C1234") == 0


def test_star_means_zero_to_two():
    for plate, ok in [("MH4C34", True), ("MH4C304", True), ("MH4C3004", True), ("MH4C30004", False)]:
        assert (match_pattern("MH 4 C 3*4", plate) > 0) is ok, plate


def test_unknowns_respect_segment_types():
    d = describe_pattern("__ _+ *+ 3514")
    assert d["segments"]["state"]["unknowns"][0]["allowed_type"] == "letter"
    assert d["segments"]["rto"]["unknowns"][0]["allowed_type"] == "digit"
    assert d["segments"]["state"]["length"] == [2, 2]
    assert d["segments"]["rto"]["length"] == [1, 2]
    assert d["segments"]["series"]["length"] == [0, 3]
    assert match_pattern("KA __ AT 3514", "KAAAAT3514") == 0      # letters in RTO
    assert match_pattern("__ 05 AT 3514", "1205AT3514") == 0      # digits in state
    assert match_pattern("KA 05 _T 3514", "KA05OT3514") == 0      # O never in a series


def test_partial_state_is_limited_to_valid_codes():
    d = describe_pattern("M_ 04 ZH 5581")
    assert d["segments"]["state"]["allowed_values"] == ["MH", "ML", "MN", "MP", "MZ"]
    assert match_pattern("M_ 04 ZH 5581", "MP04ZH5581") > 0
    assert match_pattern("M_ 04 ZH 5581", "MQ04ZH5581") == 0


def test_rfid_partial_has_the_same_structure_as_anpr():
    rfid = parse_rfid_partial("KA 05 AT 35__")
    anpr = analyze(KA, masked(KA, {8, 9}))
    assert rfid["source"] == "rfid" and anpr["source"] == "anpr"
    assert rfid["pattern"] == anpr["partial_pattern"]
    assert rfid["regex"] == anpr["regex"]
    assert rfid["segments"].keys() == anpr["segments"].keys()


def test_patterns_overlap_for_fusion():
    assert patterns_overlap("KA __ AT 3514", "KA 05 AT 35__")
    assert patterns_overlap("__ _+ *+ 3514", "KA 05 AT 3514")
    assert not patterns_overlap("KA __ AT 3514", "KA 05 AT 36__")
    assert not patterns_overlap("KA 05 AT 3514", "22 BH 1234 AA")


def test_match_score():
    assert match_pattern("KA 05 AT 3514", "KA05AT3514") == 1.0
    assert match_pattern("KA __ AT 3514", "KA05AT3514") == 0.8
    assert match_pattern("KA __ AT 3514", "ka-05 at 3514") == 0.8   # candidate normalized
    assert match_pattern("KA __ AT 3514", "KA05AT3515") == 0.0


def test_candidate_plates_from_a_registry():
    result = analyze(KA, masked(KA, {2, 3}))
    found = candidate_plates(result, ["KA05AT3514", "KA19AT3514", "KA05AT3515", "MH05AT3514", "KA1AAT3514",
                                      "KA1OAT3514"])
    # KA1AAT3514 is legal and fits: the 2 unread characters may be a 1-digit RTO + a 3rd series
    # letter (alternative layout "KA _ _AT 3514"). KA1OAT3514 does not: O is never in a series.
    assert [c["plate"] for c in found] == ["KA05AT3514", "KA19AT3514", "KA1AAT3514"]
    assert result["alternative_patterns"] == ["KA _+ _AT 3514"]


@pytest.mark.parametrize("bad", ["", "KA", "KA 05", "KA 05 AT 35 14 9", "K1 05 AT 3514", "KA AB AT 3514",
                                 "KA 05 IO 3514", "KA 05 AT 35145"])
def test_invalid_patterns_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_pattern(bad)


# ── strict "no assumption" rules ──────────────────────────────────────────────────
def test_digit_in_state_becomes_unknown_not_forced():
    result = analyze("K405AT3514")
    assert result["partial_pattern"] == "K_ 05 AT 3514"
    assert any("'4' not allowed" in c for c in result["corrections"])


def test_invalid_state_code_becomes_unknown():
    result = analyze("XX05AT3514")
    assert result["partial_pattern"] == "__ 05 AT 3514"
    assert result["is_complete"] is False
    assert any("not a valid state" in c or "valid state" in c for c in result["corrections"])


@pytest.mark.parametrize("text,plate,correction", [
    ("KAO5AT3514", "KA05AT3514", "'O'->'0'"),
    ("KA05AT35I4", "KA05AT3514", "'I'->'1'"),
    ("KA05AT3S14", "KA05AT3514", "'S'->'5'"),
    ("0D05AT3514", "OD05AT3514", "'0'->'O'"),
    ("KA05AT35B4", "KA05AT3584", "'B'->'8'"),
])
def test_only_type_confusions_are_corrected_and_logged(text, plate, correction):
    result = analyze(text)
    assert result["plate"] == plate
    assert any(correction in c for c in result["corrections"])


def test_no_other_corrections():
    # 'Z' in a digit position is not an allowed confusion -> unknown, never '2'
    result = analyze("KA05AT35Z4")
    assert result["partial_pattern"] != "KA 05 AT 3524"
    assert "2" not in result["partial_pattern"].split()[-1]


def test_o_is_never_produced_in_a_series():
    result = analyze("KA050T3514")     # '0' in the series: 'O' is not allowed there
    assert "O" not in result["segments"]["series"]["pattern"]


def test_all_zero_rto_or_number_is_invalid():
    assert analyze("KA00AT3514")["is_complete"] is False
    assert analyze("KA05AT0000")["is_complete"] is False


def test_emblem_text_is_removed():
    result = analyze("INDKA05AT3514")
    assert result["plate"] == "KA05AT3514"


def test_nothing_read():
    result = analyze_reads([])
    assert result["partial_pattern"] == "__ _+ *+ _*+"
    assert result["confidence"] == 0.0 and result["is_complete"] is False


# ── multi-frame merging ───────────────────────────────────────────────────────────
def test_same_track_merges_per_character_highest_confidence():
    reads = [read(KA, masked(KA, {8, 9}), frame=10, track="M3"),
             read(KA, masked(KA, {2, 3}), frame=12, track="M3")]
    result = analyze_reads(reads)
    assert result["partial_pattern"] == "KA 05 AT 3514"
    assert result["is_complete"] is True
    assert result["frames_used"] == [10, 12]


def test_conflicting_frames_keep_highest_confidence_and_log_it():
    reads = [read("KA05AT3514", [HI] * 9 + [0.70], frame=1, track="M3"),
             read("KA05AT3519", [HI] * 9 + [0.90], frame=2, track="M3")]
    result = analyze_reads(reads)
    assert result["plate"] == "KA05AT3519"
    assert any("disagree" in n for n in result["notes"])


def test_merge_never_prefers_a_reading_with_fewer_characters_read():
    # real case (another test video.mp4): two frames read the number "926" (3 digits, so the
    # number may continue: open), one frame read 4 number positions with only one digit legible
    reads = [read("MP04QF926", [HI] * 9, frame=138, track="M01"),
             read("MP04QF926", [HI] * 9, frame=141, track="M01"),
             read("MP04QF4QF9", [HI] * 7 + [LO] * 3, frame=147, track="M01")]
    result = analyze_reads(reads)
    assert result["partial_pattern"] == "MP 04 QF 926+"


def test_conflicts_are_reported_structurally():
    reads = [read("KA05AT3514", [HI] * 9 + [0.70], frame=1, track="M3"),
             read("KA05AT3519", [HI] * 9 + [0.90], frame=2, track="M3")]
    conflicts = analyze_reads(reads)["conflicts"]
    assert conflicts == [{"segment": "number", "index": 3, "kept": "9", "readings": [("4", 0.7), ("9", 0.9)]}]


def test_single_unreadable_glyph_in_a_two_character_segment_may_hide_two():
    # real CARLA case: the RTO "01" of KA 01 AT 4521 read as one low-confidence glyph
    result = analyze("KAFAT4521", [0.9, 1.0, 0.26, 1.0, 0.82, 0.99, 1.0, 0.97, 0.99])
    assert result["partial_pattern"] == "KA _+ AT 4521"
    assert re.fullmatch(result["regex"], "KA01AT4521")     # the real plate is never excluded
    assert re.fullmatch(result["regex"], "KA1AT4521")


def test_only_reads_with_the_same_layout_are_merged():
    reads = [read("KAFAT4521", [0.9, 1.0, 0.26, 1.0, 0.82, 0.99, 1.0, 0.97, 0.99], frame=f, track="J01-1")
             for f in range(10)]
    reads.append(read("KA91AT4521", [0.99, 1.0, 0.88, 1.0, 0.99, 1.0, 1.0, 1.0, 1.0, 1.0], frame=99, track="J01-1"))
    result = analyze_reads(reads)
    assert result["partial_pattern"] == "KA _+ AT 4521"
    assert any("different layout not merged" in n for n in result["notes"])


def test_frames_supporting_another_layout_stay_as_an_alternative():
    # real CARLA case (KA 01 AT 4521): most reads "RACAT4521" (R, C just above threshold) are best
    # laid out as "_R _+ CAT 4521"; other reads "KAFAT4521" support "KA _+ AT 4521"
    racat = [0.66, 1.0, 0.66, 1.0, 0.94, 0.99, 1.0, 0.99, 0.98]
    kafat = [0.70, 1.0, 0.26, 1.0, 0.82, 0.99, 1.0, 0.97, 0.99]
    reads = ([read("RACAT4521", racat, frame=f, track="J01-1") for f in range(6)]
             + [read("KAFAT4521", kafat, frame=10 + f, track="J01-1") for f in range(3)])
    result = analyze_reads(reads)
    assert "KA _+ AT 4521" in [result["partial_pattern"]] + result["alternative_patterns"]
    assert re.fullmatch(result["regex"], "KA01AT4521")      # the real plate is never excluded


def test_different_tracks_are_never_merged():
    reads = [read(KA, masked(KA, {8, 9}), frame=1, track="M3"),
             read(KA, masked(KA, {0, 1, 2, 3}), frame=2, track="M7")]
    result = analyze_reads(reads)
    assert result["partial_pattern"] == "KA 05 AT 35__"     # M3 alone (more characters read)
    assert result["track_id"] == "M3"
    assert result["other_tracks"] == [{"track_id": "M7", "pattern": "__ __ AT 3514"}]


def test_output_structure():
    result = analyze(KA, masked(KA, {2, 3}))
    for key in ("raw_ocr_text", "char_confidences", "partial_pattern", "segments", "is_complete",
                "confidence", "regex", "corrections", "alternative_patterns", "track_id", "frames_used"):
        assert key in result
    assert set(result["segments"]) == {"state", "rto", "series", "number"}
    seg = result["segments"]["rto"]
    assert seg["pattern"] == "__" and seg["known_length"] and seg["char_type"] == "digit"
    assert [c["conf"] for c in seg["chars"]] == [LO, LO]
    assert 0 < result["confidence"] < 1
