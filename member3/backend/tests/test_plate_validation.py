"""Unit tests for Indian plate post-processing (app/services/plate_validation.py).

Run from member3/backend:  python -m pytest tests/test_plate_validation.py -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plate_validation import (  # noqa: E402
    STATE_CODES,
    clean_plate_text,
    closest_state_code,
    format_plate,
    parse_plate,
    plate_regex,
    regional_prior,
    validate_plate,
    vote_characters,
)


def check(raw, **kwargs):
    return validate_plate(raw, log=False, **kwargs)


def test_clean_valid_plate_passes_unchanged():
    result = check("KA01AB1234")
    assert result.valid and result.plate == "KA01AB1234"
    assert result.changes == []
    assert result.state_code == "KA" and result.state_name == "Karnataka"
    assert not result.low_confidence


def test_cleaning_removes_spaces_dashes_dots_and_lowercase():
    assert check("ka-01.ab 1234").plate == "KA01AB1234"


def test_invalid_state_ks_is_rejected_not_guessed():
    # KA and KL are equally close: guessing would invent a state code
    result = check("KS01AB1234")
    assert not result.valid and result.plate is None
    assert "not guessed" in result.reason and "KA" in result.reason


def test_invalid_state_kx_is_rejected_not_guessed():
    assert not check("KX01AB1234").valid


def test_invalid_state_is_rejected_whatever_the_confidences():
    confident_k = [0.95, 0.30] + [0.9] * 8
    confident_s = [0.30, 0.95] + [0.9] * 8
    assert not check("KS01AB1234", char_confidences=confident_k).valid
    assert not check("KS01AB1234", char_confidences=confident_s).valid


def test_state_correction_is_deterministic():
    assert {check("KS01AB1234").plate for _ in range(5)} == {check("KS01AB1234").plate}


def test_position_aware_digit_correction():
    result = check("KA0IAB I234")
    assert result.valid and result.plate == "KA01AB1234"
    assert any("district" in change for change in result.changes)
    assert any("number" in change for change in result.changes)


def test_position_aware_letter_correction_in_series():
    assert check("MH12A81234").plate == "MH12AB1234"


def test_digits_in_state_positions_become_letters():
    assert check("0D02AB1234").plate == "OD02AB1234"


def test_unknown_state_is_never_output():
    result = check("XX01AB1234")
    assert (not result.valid) or result.state_code in STATE_CODES
    if result.valid:
        assert result.low_confidence


@pytest.mark.parametrize("raw", ["", "HELLO", "MH12AB12", "KA01AB12#4", "12345678901234"])
def test_garbage_is_invalid_not_passed_through(raw):
    result = check(raw)
    if result.valid:
        assert plate_regex().match(result.plate)
        assert result.state_code in STATE_CODES
    else:
        assert result.plate is None and result.reason


def test_series_letter_count_is_configurable():
    assert not check("KA05L0195").valid
    assert check("KA05L0195", series_letters=(1, 3)).plate == "KA05L0195"
    assert check("DL01CAB1234", series_letters=(1, 3)).plate == "DL01CAB1234"
    assert not check("DL01CAB1234").valid or check("DL01CAB1234").plate != "DL01CAB1234"


def test_default_regex_is_two_series_letters_and_3_or_4_digits():
    assert plate_regex().pattern == "^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{3,4}$"
    assert plate_regex((1, 3)).pattern == "^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{3,4}$"
    assert plate_regex((2, 2), (4, 4)).pattern == "^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{4}$"


# ---------------- 3-digit plates ----------------

def test_three_digit_plate_is_read_but_low_confidence():
    result = check("MP04-QF-926")
    assert result.valid and result.plate == "MP04QF926"
    assert result.number_digits == 3 and result.low_confidence
    assert format_plate(result.plate) == "MP 04 QF 926"


def test_four_digit_plate_is_not_low_confidence():
    result = check("MP09SY0205")
    assert result.valid and result.number_digits == 4 and not result.low_confidence


def test_three_digits_only_when_series_is_real_letters():
    # "KA05L0195" is a misread 4-digit plate, not KA05 LO 195
    assert not check("KA05L0195").valid


# ---------------- state code rules ----------------

def test_valid_state_code_is_not_rewritten():
    # HP is a valid code and legible: it must stay HP (no nearest-code rewrite)
    assert check("HP09SY0205").plate == "HP09SY0205"
    assert check("AP04ZY2442", char_confidences=[0.9] * 10).state_code == "AP"


def test_low_confidence_state_is_kept_as_read_and_flagged():
    low = [0.1, 0.1] + [0.9] * 8
    result = check("HP09SY0205", char_confidences=low, state_prior="MP")
    assert result.state_code == "HP" and result.low_confidence


def test_regional_prior_never_swaps_a_state_code():
    assert check("HP09SY0205", state_prior="MP").state_code == "HP"
    assert check("PB09SY0205", state_prior="MP").state_code == "PB"
    result = check("AP04ZY2442", char_confidences=[0.5, 0.9] + [0.9] * 8, state_prior="MP")
    assert result.state_code == "AP"
    assert any("ignored" in change for change in result.changes)


def test_digit_letter_fixes_only_never_digit_to_digit_or_letter_to_letter():
    assert check("DL03EN6047").plate == "DL03EN6047"
    assert check("DL83EN6047").plate == "DL83EN6047"      # 8 is a valid digit: kept
    assert check("DL03FN6047").plate == "DL03FN6047"      # F is a valid letter: kept
    assert check("DLO3EN6O47").plate == "DL03EN6047"      # O in digit slots -> 0
    assert check("0L03EN6047").valid is False             # 0->O gives OL: not a state


def test_regional_prior_needs_a_clear_majority():
    assert regional_prior([("MP", 0.9), ("MP", 0.8), ("AP", 0.9)]) == "MP"
    assert regional_prior([("MP", 0.9)]) is None
    assert regional_prior([("MP", 0.9), ("KA", 0.9), ("DL", 0.9)]) is None


def test_emblem_text_inside_two_line_read_is_dropped():
    assert check("MP09SINDY0205").plate == "MP09SY0205"
    assert check("MP09SINDNY0205").plate == "MP09SY0205"


# ---------------- character-level voting ----------------

def _read(text, conf=0.9):
    return parse_plate(text, [conf] * len(clean_plate_text(text)))


def test_character_voting_fixes_single_characters_per_position():
    reads = [(_read("HP09SY0205"), 1.0), (_read("MP09SY0285"), 1.0), (_read("MP09SY0205"), 1.0)]
    voted = vote_characters(reads)
    assert voted.chars == "MP09SY0205"
    # the vote is per position: position 0 has M 2/3, position 8 has 0 2/3
    assert voted.alternatives[0]["M"] > voted.alternatives[0]["H"]


def test_character_voting_is_confidence_weighted():
    reads = [(_read("HP09SY0205", 0.3), 1.0), (_read("MP09SY0205", 0.95), 1.0)]
    assert vote_characters(reads).chars[0] == "M"


def test_character_voting_uses_the_dominant_layout():
    reads = [(_read("MP04QF926"), 1.0), (_read("MP04QF926"), 1.0), (_read("MP04QF9260"), 0.5)]
    assert vote_characters(reads).chars == "MP04QF926"


def test_voted_string_is_validated_afterwards():
    voted = vote_characters([(_read("MPO9SY0205"), 1.0), (_read("MP09SY0205"), 1.0)])
    result = check(voted.chars, char_confidences=voted.confidences, alternatives=voted.alternatives)
    assert result.plate == "MP09SY0205"


def test_emblem_prefix_and_border_noise_are_dropped():
    assert check("INDKA05LD0195").plate == "KA05LD0195"
    assert check("|KA05LD0195").plate == "KA05LD0195"


def test_closest_state_code_always_valid():
    for chars in ("ZZ", "QQ", "99", "K", "", "XY"):
        code, _ = closest_state_code(chars)
        assert code in STATE_CODES


def test_state_codes_match_specified_list():
    assert len(STATE_CODES) == 36
    assert "TG" in STATE_CODES and "TS" not in STATE_CODES


def test_format_plate():
    assert format_plate("KA01AB1234") == "KA 01 AB 1234"
    assert format_plate(None) is None
