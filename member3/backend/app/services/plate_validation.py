"""
Indian number-plate post-processing: clean, vote, validate and correct OCR text.

Format: [STATE 2 letters][DISTRICT 2 digits][SERIES letters][NUMBER 3-4 digits]
        e.g. KA01AB1234, MP04QF926 (older 3-digit plates)

    ^[A-Z]{2}[0-9]{2}[A-Z]{2}[0-9]{3,4}$      default (SERIES_LETTERS=(2, 2),
                                              NUMBER_DIGITS=(3, 4))
    ^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{3,4}$    with series_letters=(1, 3)

Pipeline for one vehicle:
  1. clean every OCR read (uppercase, drop spaces / dashes / dots, drop the
     "IND" emblem text) and locate the plate inside it (parse_plate)
  2. character-level vote across frames: every plate position is voted
     independently, weighted by that character's OCR confidence
     (vote_characters) - whole strings are never voted
  3. only then: format validation, position-aware digit/letter fixes and the
     state-code rules (validate_plate):
       - a valid state code is kept unless its characters are very low
         confidence,
       - an invalid code is replaced by the best-ranked valid code (votes from
         other frames, visual confusion, confidence, edit distance),
       - optional soft regional prior: when most confidently read plates in
         the video share a state code, visually-close / low-confidence codes
         snap to it (logged).
Text that cannot fit the format is returned as invalid, never passed on.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

# Single source of truth for valid state / UT codes.
STATE_CODES: dict[str, str] = {
    "AN": "Andaman & Nicobar Islands",
    "AP": "Andhra Pradesh",
    "AR": "Arunachal Pradesh",
    "AS": "Assam",
    "BR": "Bihar",
    "CG": "Chhattisgarh",
    "CH": "Chandigarh",
    "DD": "Dadra & Nagar Haveli and Daman & Diu",
    "DL": "Delhi",
    "GA": "Goa",
    "GJ": "Gujarat",
    "HP": "Himachal Pradesh",
    "HR": "Haryana",
    "JH": "Jharkhand",
    "JK": "Jammu & Kashmir",
    "KA": "Karnataka",
    "KL": "Kerala",
    "LA": "Ladakh",
    "LD": "Lakshadweep",
    "MH": "Maharashtra",
    "ML": "Meghalaya",
    "MN": "Manipur",
    "MP": "Madhya Pradesh",
    "MZ": "Mizoram",
    "NL": "Nagaland",
    "OD": "Odisha",
    "PB": "Punjab",
    "PY": "Puducherry",
    "RJ": "Rajasthan",
    "SK": "Sikkim",
    "TG": "Telangana",
    "TN": "Tamil Nadu",
    "TR": "Tripura",
    "UK": "Uttarakhand",
    "UP": "Uttar Pradesh",
    "WB": "West Bengal",
}

# Default series length: exactly two letters. Use (1, 3) to also accept
# one- and three-letter series (KA05L0195, DL01CAB1234).
SERIES_LETTERS: tuple[int, int] = (2, 2)
# Trailing number: 4 digits (current plates) or 3 digits (older plates such as
# MP04QF926). A 3-digit result is always reported as low confidence.
NUMBER_DIGITS: tuple[int, int] = (3, 4)

# Mean OCR confidence below this marks an otherwise valid plate low-confidence.
LOW_CONFIDENCE_THRESHOLD = 0.60
# An already-valid state code is only reconsidered when one of its two
# characters has a confidence below this.
STATE_KEEP_MIN_CONF = 0.35
# Regional prior: a valid code that differs from the video's dominant code only
# in visually confusable characters, or in characters below this confidence,
# snaps to the dominant code.
PRIOR_OVERRIDE_MAX_CONF = 0.60
PRIOR_BONUS = 0.30

# Positions that must be digits (district, number).
TO_DIGIT = {
    "O": "0", "Q": "0", "D": "0", "U": "0",
    "I": "1", "L": "1", "J": "1", "T": "7",
    "Z": "2", "S": "5", "B": "8", "G": "6", "A": "4",
}
# Positions that must be letters (series, state).
TO_LETTER = {
    "0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G",
    "4": "A", "7": "T", "3": "B",
}

# Glyphs OCR confuses on plates; any two members of a group are a cheap
# substitution when ranking state-code candidates.
CONFUSION_GROUPS = (
    "MHNW", "PRB", "0ODQU", "1ILJT", "5S", "8B", "2Z", "6G", "4A", "7T",
    "KX", "CG", "EF", "VYU",
    "AM",   # small, blurred plates: M read as A (seen on the sample video)
)
CONFUSION_PAIRS = {
    frozenset((a, b)) for group in CONFUSION_GROUPS for a in group for b in group if a != b
}
CONFUSION_COST = 0.35
SUBSTITUTION_COST = 1.0
# A state correction this expensive (a confident, non-confusable character
# was overridden) is flagged low-confidence even though the code is valid.
STATE_GUESS_COST = 0.9

# Emblem text printed on HSRP plates that OCR picks up between characters.
EMBLEM_TOKENS = ("IND", "INO", "IN0")


@dataclass
class PlateValidation:
    raw: str
    cleaned: str
    plate: str | None            # corrected, format-valid plate, or None
    valid: bool
    state_code: str | None = None
    state_name: str | None = None
    confidence: float | None = None
    low_confidence: bool = False
    changes: list[str] = field(default_factory=list)
    reason: str | None = None    # why it is invalid / low-confidence
    number_digits: int | None = None

    @property
    def formatted(self) -> str | None:
        return format_plate(self.plate)

    def as_dict(self) -> dict:
        return {
            "raw": self.raw, "cleaned": self.cleaned, "plate": self.plate,
            "formatted": self.formatted, "valid": self.valid,
            "state_code": self.state_code, "state_name": self.state_name,
            "confidence": self.confidence, "low_confidence": self.low_confidence,
            "changes": list(self.changes), "reason": self.reason,
            "number_digits": self.number_digits,
        }


@dataclass
class ParsedRead:
    """Where the plate sits inside one OCR string (characters NOT yet fixed)."""
    chars: str                 # raw characters of the plate window
    confidences: list[float]   # one per character
    series_len: int
    number_len: int
    cost: float                # structural cost (fixes needed, dropped chars)

    @property
    def layout(self) -> tuple[int, int]:
        return self.series_len, self.number_len


@dataclass
class VotedPlate:
    chars: str
    confidences: list[float]              # winning share x mean confidence
    alternatives: list[dict[str, float]]  # per position: char -> vote share
    layout: tuple[int, int]
    reads: int
    layout_share: float


def clean_plate_text(text: str | None) -> str:
    """Uppercase and drop spaces, dashes, dots and any other non-alphanumerics."""
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def plate_regex(
    series_letters: tuple[int, int] = SERIES_LETTERS,
    number_digits: tuple[int, int] = NUMBER_DIGITS,
) -> re.Pattern:
    def rng(low, high):
        return f"{{{low}}}" if low == high else f"{{{low},{high}}}"
    return re.compile(
        rf"^[A-Z]{{2}}[0-9]{{2}}[A-Z]{rng(*series_letters)}[0-9]{rng(*number_digits)}$"
    )


def format_plate(plate: str | None) -> str | None:
    """KA01AB1234 -> 'KA 01 AB 1234', MP04QF926 -> 'MP 04 QF 926'."""
    if not plate:
        return None
    match = re.match(r"^([A-Z]{2})(\d{2})([A-Z]{1,3})(\d{3,4})$", plate)
    return " ".join(match.groups()) if match else plate


def is_confusable(a: str, b: str) -> bool:
    return a == b or frozenset((a, b)) in CONFUSION_PAIRS


def _char_cost(observed: str, target: str, confidence: float) -> float:
    if observed == target:
        return 0.0
    base = CONFUSION_COST if frozenset((observed, target)) in CONFUSION_PAIRS else SUBSTITUTION_COST
    # Overriding a character the OCR was sure about is expensive; overriding
    # an uncertain one is cheap.
    return base * max(0.05, confidence)


def closest_state_code(
    chars: str,
    confidences: Sequence[float] | None = None,
    alternatives: Sequence[dict[str, float]] | None = None,
    prior: str | None = None,
) -> tuple[str, float]:
    """Return (valid state code, correction cost) closest to ``chars``.

    Per position a candidate letter costs ``1 - vote share`` when other frames
    voted for it, else the confusion-aware substitution cost weighted by the
    observed character's OCR confidence (overriding a confident character is
    expensive). ``prior`` (regional prior) gets a bonus. Ties: keep the first
    letter, then alphabetical. Always returns a code from STATE_CODES.
    """
    if (chars + "??")[:2] in STATE_CODES and not alternatives and prior is None:
        return (chars + "??")[:2], 0.0
    code, cost = rank_state_codes(chars, confidences, alternatives, prior, limit=1)[0]
    return code, cost


def rank_state_codes(
    chars: str,
    confidences: Sequence[float] | None = None,
    alternatives: Sequence[dict[str, float]] | None = None,
    prior: str | None = None,
    limit: int = 3,
) -> list[tuple[str, float]]:
    """Valid state codes ranked for ``chars``, best first: [(code, cost)].

    Same costs as closest_state_code (vote share, visual confusion, per-char
    OCR confidence); exposed so callers can show the runner-up candidates.
    """
    chars = (chars + "??")[:2]
    conf = list(confidences)[:2] if confidences else []
    conf += [1.0] * (2 - len(conf))
    alts = list(alternatives)[:2] if alternatives else []
    alts += [{}] * (2 - len(alts))

    def position_cost(i, target):
        if chars[i] == target:
            return 0.0
        substitution = _char_cost(chars[i], target, conf[i])
        share = alts[i].get(target, 0.0)
        return min(substitution, 1.0 - share) if share > 0 else substitution

    ranked = sorted(
        (
            round(position_cost(0, code[0]) + position_cost(1, code[1])
                  - (PRIOR_BONUS if code == prior else 0.0), 6),
            code[0] != chars[0],
            code,
        )
        for code in STATE_CODES
    )
    return [(code, max(0.0, cost)) for cost, _, code in ranked[:max(1, limit)]]


def _layouts(series_letters, number_digits):
    for s in range(series_letters[0], series_letters[1] + 1):
        for n in range(number_digits[1], number_digits[0] - 1, -1):
            yield s, n


def _structure_cost(chunk: str, series_len: int, number_len: int) -> float | None:
    """How well a window fits the layout (None = impossible). A character that
    needs a digit<->letter fix costs 0.3."""
    kinds = ["L", "L", "D", "D"] + ["L"] * series_len + ["D"] * number_len
    cost = 0.0
    for char, kind in zip(chunk, kinds):
        if kind == "D":
            if char.isdigit():
                continue
            if char in TO_DIGIT:
                cost += 0.3
                continue
            return None
        if char.isalpha():
            continue
        if char in TO_LETTER:
            cost += 0.3
            continue
        return None
    if number_len < 4:
        # A 3-digit number with a digit in the series is far more likely a
        # misread 4-digit plate (e.g. KA05L0195): only accept real letters.
        if not chunk[4:4 + series_len].isalpha():
            return None
        cost += 0.5
    return cost


def _strip_emblems(text: str, conf: list[float],
                   max_len: int) -> list[tuple[str, list[float], float]]:
    """(text, confidences, extra cost) variants: as read, with the IND emblem
    text removed, and - for over-long reads - with one stray character
    (emblem fragment, screw, border) removed from anywhere inside."""
    variants = [(text, conf, 0.0, None)]
    for token in EMBLEM_TOKENS:
        index = text.find(token)
        while index >= 0:
            variants.append((text[:index] + text[index + len(token):],
                             conf[:index] + conf[index + len(token):], 0.05, index))
            index = text.find(token, index + 1)
    out = [(t, c, cost) for t, c, cost, _ in variants]
    for base, base_conf, base_cost, emblem_at in variants:
        if len(base) > max_len:
            for i in range(1, len(base) - 1):
                # A leftover glyph right after the removed emblem is the
                # most likely stray character.
                extra = 0.4 if emblem_at is not None and i == emblem_at else 0.6
                out.append((base[:i] + base[i + 1:], base_conf[:i] + base_conf[i + 1:],
                            base_cost + extra))
    return out


def parse_plate(
    raw: str | None,
    char_confidences: Sequence[float] | None = None,
    series_letters: tuple[int, int] = SERIES_LETTERS,
    number_digits: tuple[int, int] = NUMBER_DIGITS,
) -> ParsedRead | None:
    """Locate the plate inside an OCR string without changing characters.

    Tries the text as-is and with the IND emblem text removed, every allowed
    layout and every window; lowest structural cost wins (fewer fixes, fewer
    dropped characters, a valid-looking state code, 4-digit numbers).
    """
    cleaned = clean_plate_text(raw)
    conf = list(char_confidences or [])
    if len(conf) != len(cleaned):
        conf = [1.0] * len(cleaned)
    best: ParsedRead | None = None
    max_len = 4 + series_letters[1] + number_digits[1]
    for text, text_conf, variant_cost in _strip_emblems(cleaned, conf, max_len):
        for series_len, number_len in _layouts(series_letters, number_digits):
            length = 4 + series_len + number_len
            for start in range(0, len(text) - length + 1):
                chunk = text[start:start + length]
                cost = _structure_cost(chunk, series_len, number_len)
                if cost is None:
                    continue
                state = "".join(TO_LETTER.get(c, c) for c in chunk[:2])
                cost += 0.5 * (len(text) - length)
                cost += 0.0 if state in STATE_CODES else 0.4
                cost += variant_cost
                if best is None or cost < best.cost:
                    best = ParsedRead(chunk, text_conf[start:start + length],
                                      series_len, number_len, round(cost, 4))
    return best


def vote_characters(reads: Sequence[tuple[ParsedRead, float]]) -> VotedPlate | None:
    """Character-level vote across frames.

    ``reads`` = [(parsed read, weight)]. The layout (series/number lengths)
    with the most confidence-weighted support wins; then every position is
    voted independently, each character contributing ``weight x its OCR
    confidence``. Whole strings are never compared.
    """
    reads = [(r, w) for r, w in reads if r is not None and w > 0]
    if not reads:
        return None
    by_layout: dict[tuple[int, int], list] = defaultdict(list)
    for read, weight in reads:
        by_layout[read.layout].append((read, weight))
    totals = {layout: sum(w * (sum(r.confidences) / len(r.confidences)) for r, w in items)
              for layout, items in by_layout.items()}
    layout = max(totals, key=lambda k: (totals[k], k[1]))
    items = by_layout[layout]
    chars, confidences, alternatives = [], [], []
    for position in range(len(items[0][0].chars)):
        scores: dict[str, float] = defaultdict(float)
        conf_sum: dict[str, float] = defaultdict(float)
        count: dict[str, int] = defaultdict(int)
        for read, weight in items:
            char, c = read.chars[position], read.confidences[position]
            scores[char] += weight * c
            conf_sum[char] += c
            count[char] += 1
        total = sum(scores.values()) or 1.0
        winner = max(scores, key=lambda ch: (scores[ch], ch))
        chars.append(winner)
        confidences.append(round((scores[winner] / total) * conf_sum[winner] / count[winner], 4))
        alternatives.append({ch: round(v / total, 4) for ch, v in scores.items()})
    return VotedPlate("".join(chars), confidences, alternatives, layout, len(items),
                      round(totals[layout] / (sum(totals.values()) or 1.0), 4))


def regional_prior(
    plates: Sequence[tuple[str, float]], min_plates: int = 2, min_share: float = 0.6
) -> str | None:
    """Dominant state code among confidently read plates [(code, confidence)]."""
    codes = [code for code, conf in plates if code in STATE_CODES and conf >= 0.5]
    if len(codes) < min_plates:
        return None
    best = max(sorted(set(codes)), key=codes.count)
    return best if codes.count(best) / len(codes) >= min_share else None


def _fix_positions(text: str, series_len: int, number_len: int,
                   changes: list[str]) -> tuple[str | None, str | None]:
    """Apply digit/letter fixes to district, series and number positions."""
    out = list(text)
    layout = [("district", i, "digit") for i in (2, 3)]
    layout += [("series", 4 + i, "letter") for i in range(series_len)]
    layout += [("number", 4 + series_len + i, "digit") for i in range(number_len)]
    for part, index, kind in layout:
        char = out[index]
        fixed = TO_DIGIT.get(char, char) if kind == "digit" else TO_LETTER.get(char, char)
        ok = fixed.isdigit() if kind == "digit" else fixed.isalpha()
        if not ok:
            return None, f"{part} position {index + 1} must be a {kind}, got '{char}'"
        if fixed != char:
            changes.append(f"{part} pos {index + 1}: '{char}'->'{fixed}'")
            out[index] = fixed
    return "".join(out), None


def validate_plate(
    raw: str | None,
    char_confidences: Sequence[float] | None = None,
    series_letters: tuple[int, int] = SERIES_LETTERS,
    log: bool = True,
    number_digits: tuple[int, int] = NUMBER_DIGITS,
    state_prior: str | None = None,
    alternatives: Sequence[dict[str, float]] | None = None,
) -> PlateValidation:
    """Clean, correct and validate OCR text (or a voted string).

    ``char_confidences``: one OCR confidence per cleaned character.
    ``alternatives``: per-position vote shares from vote_characters().
    ``state_prior``: dominant state code of the video (soft regional prior).
    """
    cleaned = clean_plate_text(raw)
    confidences = list(char_confidences or [])
    if len(confidences) != len(cleaned):
        confidences = []
    mean_conf = round(sum(confidences) / len(confidences), 4) if confidences else None
    result = PlateValidation(raw=str(raw or ""), cleaned=cleaned, plate=None,
                             valid=False, confidence=mean_conf)

    min_len = 4 + series_letters[0] + number_digits[0]
    max_len = 4 + series_letters[1] + number_digits[1]
    if not cleaned:
        result.reason = "no OCR text"
        return _finish(result, log)
    if len(cleaned) < min_len:
        result.reason = f"too short ({len(cleaned)} chars, need {min_len}-{max_len})"
        return _finish(result, log)

    parsed = parse_plate(cleaned, confidences or None, series_letters, number_digits)
    if parsed is None:
        result.reason = "does not fit the plate format"
        return _finish(result, log)
    if len(parsed.chars) != len(cleaned):
        result.changes.append(
            f"used '{parsed.chars}' from '{cleaned}' (dropped emblem/border characters)")
    conf = parsed.confidences if confidences else []

    fixed, error = _fix_positions(parsed.chars, parsed.series_len, parsed.number_len,
                                  result.changes)
    if fixed is None:
        result.reason = error
        return _finish(result, log)

    # State code: only the letter-vs-digit fix of the two letter positions is
    # applied (a '0' there can only be an 'O'). A state code is NEVER invented
    # or swapped for another one - not by nearest-code ranking, not by vote
    # alternatives, not by a regional prior. An invalid code makes the read
    # invalid; the ranked candidates are reported for information only.
    state_chars = "".join(TO_LETTER.get(c, c) for c in fixed[:2])
    if state_chars != fixed[:2]:
        result.changes.append(f"state '{fixed[:2]}'->'{state_chars}' (digits read as letters)")
    state_conf = conf[:2] if conf else [1.0, 1.0]
    state = state_chars
    if state_chars not in STATE_CODES:
        candidates = ", ".join(code for code, _ in rank_state_codes(
            state_chars, conf[:2] if conf else None, limit=3))
        result.reason = (f"state code '{state_chars}' is not a valid state/UT code "
                         f"(not guessed; closest: {candidates})")
        return _finish(result, log)
    if state_prior and state_prior != state_chars:
        result.changes.append(f"regional prior '{state_prior}' ignored: the state is kept "
                              f"as read ('{state_chars}')")

    plate = state + fixed[2:]
    if not plate_regex(series_letters, number_digits).match(plate):
        result.reason = "does not match plate format after correction"
        return _finish(result, log)

    result.plate = plate
    result.valid = True
    result.state_code = state
    result.state_name = STATE_CODES[state]
    result.number_digits = parsed.number_len
    if parsed.number_len < 4:
        result.low_confidence = True
        result.reason = f"{parsed.number_len}-digit number (older format)"
    elif mean_conf is not None and mean_conf < LOW_CONFIDENCE_THRESHOLD:
        result.low_confidence = True
        result.reason = f"low OCR confidence ({mean_conf:.2f})"
    elif min(state_conf) < STATE_KEEP_MIN_CONF:
        # kept as read, but the OCR was unsure of a state letter
        result.low_confidence = True
        result.reason = f"uncertain state code ({min(state_conf):.2f})"
    return _finish(result, log)


def strict_plate(raw: str | None, char_confidences: Sequence[float] | None = None) -> PlateValidation:
    """validate_plate without logging: positional letter/digit fixes only, the
    state code kept exactly as read (invalid code -> invalid read)."""
    return validate_plate(raw, char_confidences, log=False)


def _finish(result: PlateValidation, log: bool) -> PlateValidation:
    if log and (result.changes or not result.valid or result.low_confidence):
        status = "VALID" if result.valid else "INVALID"
        print(
            f"[PLATE] {status} raw='{result.raw}' corrected='{result.plate or '-'}' "
            f"changes={result.changes or 'none'}"
            + (f" reason={result.reason}" if result.reason else ""),
            flush=True,
        )
    return result
