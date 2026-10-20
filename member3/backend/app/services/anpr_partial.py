"""
AGHAT SETHU — Rule-based partial ANPR for Indian number plates

Turns the raw OCR reads of ONE tracked vehicle into a plate pattern that marks
every character that was not actually read. Nothing is ever guessed: no
nearest-valid-plate correction, no database fill-in, no "likely" plates.

Plate rules (each segment = character type + length range)
    standard   SS DD LLL NNNN
        state   letters, exactly 2, must be a valid state/UT code
        rto     digits, 1-2
        series  letters, 0-3, never I or O
        number  digits, 1-4 (a COMPLETE plate needs all 4: with fewer digits a
                truncated read cannot be told apart from a short number)
    bh         YY BH NNNN LL
        year    digits, exactly 2
        bh      the literal "BH"
        number  digits, exactly 4
        series  letters, 1-2, never I or O

Pattern notation (identical for ANPR and RFID reads)
    A-Z 0-9   a character that was read
    _         exactly ONE unknown character at a known position
    *         0-2 unknown characters (length not known)
    +         0 or 1 unknown character (the position may or may not exist)
    Segments are separated by spaces: "KA __ AT 3514", "MH +4+ _ 3*4",
    "22 BH 1234 AA". A standard plate with no series has 3 groups ("KA 05 1234").
    An unknown always takes its segment's type ("_" in the state is a letter,
    "_" in the number a digit), so every pattern has an exact regex.

How a read becomes a pattern
    * characters below UNKNOWN_CONF_THRESHOLD are unknown ("_"); the recognizer
      is CTC-based and emits no per-character boxes, so segments are found from
      character order, type and the segment rules;
    * every way of laying the read onto the rules is scored (corrections,
      unread segments, uncommon segment lengths) and the best one is used; the
      other plausible layouts are kept as alternative_patterns and included in
      the regex, so later matching never depends on that choice;
    * a region that was not read at all has an unknown LENGTH, so it is written
      with "*"/"+" (e.g. an unread RTO is "_+", 1-2 digits);
    * the only corrections are digit/letter look-alikes (TYPE_CONFUSIONS) inside
      a segment whose type the rules fix, and each one is logged; a character
      that breaks the rules otherwise becomes unknown instead of being forced;
    * one unreadable glyph where the rules normally have two characters (RTO,
      series) is written "_+": the recognizer is CTC-based and merges adjacent
      characters it cannot separate (seen on the CARLA feed: RTO "01" read as
      a single "F"), so claiming exactly one character would exclude the real
      plate;
    * reads of the same raw tracker id are merged per character (highest
      confidence wins), and only reads that agree on the plate layout are
      merged; reads of different tracker ids are never merged.
"""

from __future__ import annotations

import functools
import itertools
import re
import string
from collections import defaultdict
from dataclasses import dataclass
from typing import Sequence

from app.services.plate_validation import STATE_CODES

# Characters read below this confidence are unknown.
UNKNOWN_CONF_THRESHOLD = 0.60
# Alternative layouts whose score is within this of the best are kept.
ALT_MARGIN = 0.7
MAX_ALTERNATIVES = 6
# A layout group of a track's reads is kept as an alternative when it has at
# least this many reads AND this share of the track's reads.
GROUP_MIN_READS = 2
GROUP_MIN_SHARE = 0.10
# The ONLY corrections allowed: digit <-> letter look-alikes, and only inside a
# segment whose type is fixed by the rules.
TYPE_CONFUSIONS = {"0": "O", "1": "I", "5": "S", "8": "B"}
EMBLEM_TOKENS = ("IND",)

# Layout scoring (lower is better).
COST_CORRECTION = 0.5
COST_RULE_VIOLATION = 1.0
COST_UNREAD_SEGMENT = 0.5
COST_OPEN_SIDE = 0.3
COST_EMBLEM_STRIPPED = 0.05
FORMAT_COST = {"standard": 0.0, "bh": 0.2}
# An empty series is legal but rare; it must not be the cheap way to split a digit run.
LENGTH_PRIOR = {("rto", 1): 0.3, ("series", 0): 1.5, ("series", 1): 0.15, ("series", 3): 0.3}

LETTER, DIGIT = "letter", "digit"
ALL_LETTERS = frozenset(string.ascii_uppercase)
SERIES_LETTERS = ALL_LETTERS - {"I", "O"}
DIGITS = frozenset(string.digits)


@dataclass(frozen=True)
class SegmentRule:
    name: str
    char_type: str                      # letter | digit
    min_len: int
    max_len: int
    allowed: frozenset                  # characters allowed at every position
    values: frozenset | None = None     # whole-segment values (state codes, "BH")
    complete_min: int | None = None     # length needed for a COMPLETE plate
    nonzero: bool = False               # all zeros is not a valid value (RTO 00, number 0000)
    typical_len: int | None = None      # usual length: one unreadable glyph may hide this many

    @property
    def full_min(self) -> int:
        return self.complete_min or self.min_len


FORMATS: dict[str, tuple[SegmentRule, ...]] = {
    "standard": (
        SegmentRule("state", LETTER, 2, 2, ALL_LETTERS, values=frozenset(STATE_CODES)),
        SegmentRule("rto", DIGIT, 1, 2, DIGITS, nonzero=True, typical_len=2),
        SegmentRule("series", LETTER, 0, 3, SERIES_LETTERS, typical_len=2),
        SegmentRule("number", DIGIT, 1, 4, DIGITS, complete_min=4, nonzero=True),
    ),
    "bh": (
        SegmentRule("year", DIGIT, 2, 2, DIGITS),
        SegmentRule("bh", LETTER, 2, 2, frozenset("BH"), values=frozenset({"BH"})),
        SegmentRule("number", DIGIT, 4, 4, DIGITS, nonzero=True),
        SegmentRule("series", LETTER, 1, 2, SERIES_LETTERS),
    ),
}


# =================================================================================
# Pattern notation: parse, expand, regex, match  (shared by ANPR and RFID)
# =================================================================================

def _gap(n: int) -> str:
    """n optional unknown characters as '*' (0-2) / '+' (0-1) tokens."""
    return "*" * (n // 2) + "+" * (n % 2)


def _class_regex(rule: SegmentRule) -> str:
    if rule.allowed == DIGITS:
        return r"\d"
    if rule.allowed == SERIES_LETTERS:
        return "[A-HJ-NP-Z]"
    if rule.allowed == ALL_LETTERS:
        return "[A-Z]"
    return "[" + "".join(sorted(rule.allowed)) + "]"


def _allowed_text(rule: SegmentRule) -> str:
    return {r"\d": "0-9", "[A-HJ-NP-Z]": "A-Z except I,O", "[A-Z]": "A-Z"}.get(_class_regex(rule),
                                                                              "".join(sorted(rule.allowed)))


def parse_pattern(pattern: str) -> tuple[str, list[tuple[SegmentRule, str]]]:
    """'KA __ AT 3514' -> ('standard', [(state rule, 'KA'), (rto rule, '__'), ...])."""
    groups = (pattern or "").upper().split()
    if not groups:
        raise ValueError("empty pattern")
    if len(groups) == 4 and (re.search(r"\d", groups[0]) or re.fullmatch(r"[BH_]{2}", groups[1])
                             and re.search("[BH]", groups[1])):
        fmt, parts = "bh", groups
    elif len(groups) == 4:
        fmt, parts = "standard", groups
    elif len(groups) == 3:
        fmt, parts = "standard", [groups[0], groups[1], "", groups[2]]   # no series
    else:
        raise ValueError(f"expected 3 or 4 space-separated segments, got {len(groups)}: {pattern!r}")
    out = []
    for rule, tokens in zip(FORMATS[fmt], parts):
        for ch in tokens:
            if ch not in "_*+" and ch not in rule.allowed:
                raise ValueError(f"{rule.name}: {ch!r} is not allowed ({rule.char_type}, {_allowed_text(rule)})")
        lo = sum(1 for ch in tokens if ch not in "*+")
        hi = lo + sum(2 if ch == "*" else 1 for ch in tokens if ch in "*+")
        if lo > rule.max_len or hi < rule.min_len:
            raise ValueError(f"{rule.name}: {tokens!r} cannot be {rule.min_len}-{rule.max_len} characters")
        out.append((rule, tokens))
    return fmt, out


def _expansions(rule: SegmentRule, tokens: str) -> list[tuple]:
    """Every concrete position sequence of a segment: a char, or None (= one
    unknown character of the segment's class), filtered by the segment rules."""
    choices = []
    for ch in tokens:
        if ch == "_":
            choices.append([(None,)])
        elif ch == "*":
            choices.append([(), (None,), (None, None)])
        elif ch == "+":
            choices.append([(), (None,)])
        else:
            choices.append([(ch,)])
    seen = set()
    for combo in itertools.product(*choices):
        seq = tuple(c for part in combo for c in part)
        if rule.min_len <= len(seq) <= rule.max_len and seq not in seen:
            if rule.values is None or any(_fits_value(seq, v) for v in rule.values):
                seen.add(seq)
    return sorted(seen, key=lambda s: (len(s), [c or "" for c in s]))


def _fits_value(seq: tuple, value: str) -> bool:
    return len(seq) == len(value) and all(c is None or c == v for c, v in zip(seq, value))


def _seq_regex(rule: SegmentRule, seq: tuple) -> str:
    out, run = [], 0
    for c in list(seq) + ["END"]:
        if c is None:
            run += 1
            continue
        if run:
            out.append(_class_regex(rule) + (f"{{{run}}}" if run > 1 else ""))
            run = 0
        if c != "END":
            out.append(re.escape(c))
    return "".join(out)


def _segment_regex(rule: SegmentRule, tokens: str, expansions: list[tuple]) -> str:
    if not expansions:
        return "(?!)"
    if rule.values is not None:
        values = sorted(v for v in rule.values if any(_fits_value(s, v) for s in expansions))
        return values[0] if len(values) == 1 else "(?:" + "|".join(values) + ")"
    lo = sum(1 for ch in tokens if ch not in "*+")
    hi = lo + sum(2 if ch == "*" else 1 for ch in tokens if ch in "*+")
    if rule.min_len <= lo and hi <= rule.max_len:
        # the tokens alone respect the length rule: one compact regex
        out, run_lo, run_hi = [], 0, 0
        for ch in tokens + "\0":
            if ch in "_*+":
                run_lo += ch == "_"
                run_hi += 2 if ch == "*" else 1
                continue
            if run_hi:
                quant = (f"{{{run_lo}}}" if run_lo == run_hi else f"{{{run_lo},{run_hi}}}")
                out.append(_class_regex(rule) + ("" if quant == "{1}" else quant))
                run_lo = run_hi = 0
            if ch != "\0":
                out.append(re.escape(ch))
        return "".join(out)
    alts = sorted({_seq_regex(rule, s) for s in expansions})
    return alts[0] if len(alts) == 1 else "(?:" + "|".join(alts) + ")"


def pattern_regex(pattern: str) -> str:
    """'KA __ AT 3514' -> '^KA\\d{2}AT3514$' (exact: unknowns take their segment's class)."""
    fmt, parts = parse_pattern(pattern)
    return "^" + "".join(_segment_regex(rule, tokens, _expansions(rule, tokens))
                         for rule, tokens in parts) + "$"


def describe_pattern(pattern: str) -> dict:
    """Structured form of a pattern: format, per-segment value/pattern, length
    range, allowed type of every unknown, completeness and regex. ANPR results
    and RFID reads both go through this, so they are directly comparable."""
    fmt, parts = parse_pattern(pattern)
    segments, complete = {}, True
    for rule, tokens in parts:
        expansions = _expansions(rule, tokens)
        lengths = [len(s) for s in expansions] or [0]
        value = (tokens if tokens and all(ch not in "_*+" for ch in tokens)
                 and (rule.values is None or tokens in rule.values) else ("" if tokens == "" else None))
        if value is None or len(value) < rule.full_min:
            complete = False
        info = {
            "pattern": tokens,
            "value": value,
            "length": [min(lengths), max(lengths)],
            "known_length": min(lengths) == max(lengths),
            "char_type": rule.char_type,
            "allowed_chars": _allowed_text(rule),
            "unknowns": [{"index": i, "token": ch, "count": {"_": "1", "*": "0-2", "+": "0-1"}[ch],
                          "allowed_type": rule.char_type}
                         for i, ch in enumerate(tokens) if ch in "_*+"],
        }
        if rule.values is not None and value is None:
            info["allowed_values"] = sorted(v for v in rule.values if any(_fits_value(s, v) for s in expansions))
        segments[rule.name] = info
    normalized = " ".join(t for _, t in parts if t != "")
    return {
        "format": fmt,
        "pattern": normalized,
        "segments": segments,
        "is_complete": complete,
        "plate": "".join(t for _, t in parts) if complete else None,
        "regex": pattern_regex(normalized),
    }


def known_char_count(pattern: str) -> int:
    return sum(1 for ch in pattern if ch.isalnum())


def match_pattern(pattern: str, candidate_plate: str) -> float:
    """Score how well a full plate fits a pattern: 0.0 = impossible, otherwise
    the share of the plate's characters the pattern actually read (1.0 = a
    complete pattern equal to the plate; a pattern with nothing read still
    scores 0.01, because the plate is possible)."""
    plate = re.sub(r"[^A-Z0-9]", "", (candidate_plate or "").upper())
    if not plate or not re.fullmatch(pattern_regex(pattern), plate, flags=re.ASCII):
        return 0.0
    return round(max(0.01, min(1.0, known_char_count(pattern) / len(plate))), 3)


def parse_rfid_partial(pattern: str) -> dict:
    """A partial RFID read in the same notation ('_', '*', '+'), structured
    exactly like an ANPR result so the two can be compared or intersected."""
    return {**describe_pattern(pattern), "source": "rfid"}


def patterns_overlap(pattern_a: str, pattern_b: str) -> bool:
    """True if at least one plate satisfies both patterns (ANPR x RFID, etc.)."""
    fmt_a, parts_a = parse_pattern(pattern_a)
    fmt_b, parts_b = parse_pattern(pattern_b)
    if fmt_a != fmt_b:
        return False
    for (rule, ta), (_, tb) in zip(parts_a, parts_b):
        ea, eb = _expansions(rule, ta), _expansions(rule, tb)
        if not any(len(x) == len(y) and all(p is None or q is None or p == q for p, q in zip(x, y))
                   and (rule.values is None or any(_fits_value(x, v) and _fits_value(y, v) for v in rule.values))
                   for x in ea for y in eb):
            return False
    return True


# =================================================================================
# OCR reads -> pattern
# =================================================================================

@dataclass
class _Char:
    ch: str | None      # the accepted character, None = unknown
    conf: float
    raw: str            # what OCR emitted


@dataclass
class _Seg:
    rule: SegmentRule
    chars: list[_Char] | None   # None = segment not read at all
    open_left: bool = False     # the read may have missed characters on this side
    open_right: bool = False

    def tokens(self) -> str:
        rule = self.rule
        if self.chars is None:
            return "_" * rule.min_len + _gap(rule.max_len - rule.min_len)
        body = "".join(c.ch or "_" for c in self.chars)
        n = len(self.chars)
        if self.open_left and self.open_right:
            room = rule.max_len - n
            return _gap(room) + body + _gap(room)
        if self.open_left or self.open_right:
            side = "_" * max(0, rule.min_len - n) + _gap(rule.max_len - max(n, rule.min_len))
            return side + body if self.open_left else body + side
        if (rule.typical_len and 0 < n < rule.typical_len and n < rule.max_len
                and all(c.ch is None for c in self.chars)):
            # unreadable glyph(s) shorter than usual: may be merged characters
            return body + _gap(min(rule.typical_len, rule.max_len) - n)
        return body

    @property
    def closed(self) -> bool:
        return self.chars is not None and not self.open_left and not self.open_right


@dataclass
class _Layout:
    fmt: str
    segs: list[_Seg]
    cost: float
    notes: list[str]

    @property
    def pattern(self) -> str:
        return " ".join(t for t in (s.tokens() for s in self.segs) if t != "")

    @property
    def known(self) -> int:
        return sum(1 for s in self.segs if s.chars for c in s.chars if c.ch)


def _fit_char(raw: str, conf: float, rule: SegmentRule, threshold: float) -> tuple[str | None, float, str | None]:
    if conf < threshold:
        return None, 0.0, None
    if raw in rule.allowed:
        return raw, 0.0, None
    swapped = TYPE_CONFUSIONS.get(raw) or {v: k for k, v in TYPE_CONFUSIONS.items()}.get(raw)
    if swapped and swapped in rule.allowed:
        return swapped, COST_CORRECTION, f"corrected '{raw}'->'{swapped}' ({rule.char_type} segment)"
    return None, COST_RULE_VIOLATION, f"'{raw}' not allowed ({rule.char_type}, {_allowed_text(rule)}) -> unknown"


def _segment_violation(seg: "_Seg") -> str | None:
    """Why the characters read for a segment break its rules (None = they fit):
    no valid state code / "BH" can contain them, or a complete RTO / number is all zeros."""
    rule, known = seg.rule, "".join(c.ch or "_" for c in seg.chars or [])
    if not seg.chars or all(c.ch is None for c in seg.chars):
        return None
    if rule.values is not None and not _expansions(rule, seg.tokens()):
        return f"'{known}' cannot be part of a valid {rule.name}"
    if rule.nonzero and seg.closed and all(c.ch == "0" for c in seg.chars):
        return f"'{known}' (all zeros) is not a valid {rule.name}"
    return None


def _splits(n: int, rules: Sequence[SegmentRule], a: int, b: int):
    """Lengths for segments a..b (the observed span) that sum to n."""
    def rec(i, remaining):
        rule = rules[i]
        edge = i in (a, b)
        lo, hi = (1 if edge else rule.min_len), rule.max_len
        if i == b:
            if lo <= remaining <= hi:
                yield (remaining,)
            return
        for length in range(lo, min(hi, remaining) + 1):
            for rest in rec(i + 1, remaining - length):
                yield (length,) + rest
    yield from rec(a, n)


def _layouts(chars: list[tuple[str, float]], threshold: float) -> list[_Layout]:
    out = []
    n = len(chars)
    for fmt, rules in FORMATS.items():
        k = len(rules)
        for a in range(k):
            for b in range(a, k):
                for lengths in _splits(n, rules, a, b):
                    cost, notes, segs, pos = FORMAT_COST[fmt], [], [], 0
                    for i, rule in enumerate(rules):
                        if i < a or i > b:
                            segs.append(_Seg(rule, None))
                            cost += COST_UNREAD_SEGMENT
                            continue
                        length = lengths[i - a]
                        fitted = []
                        for raw, conf in chars[pos:pos + length]:
                            ch, extra, note = _fit_char(raw, conf, rule, threshold)
                            cost += extra
                            fitted.append(_Char(ch, conf, raw))
                            if note:
                                notes.append(f"{rule.name}: {note}")
                        pos += length
                        seg = _Seg(rule, fitted,
                                   open_left=i == a and (a > 0 or length < rule.full_min),
                                   open_right=i == b and (b < k - 1 or length < rule.full_min))
                        if seg.tokens() != "".join(c.ch or "_" for c in fitted):   # gap tokens were added
                            cost += COST_OPEN_SIDE * (seg.open_left + seg.open_right)
                        reason = _segment_violation(seg)
                        if reason:
                            notes.append(f"{rule.name}: {reason} -> unknown")
                            for c in fitted:
                                if c.ch:
                                    c.ch = None
                                    cost += COST_RULE_VIOLATION
                        if seg.closed:
                            cost += LENGTH_PRIOR.get((rule.name, length), 0.0)
                        segs.append(seg)
                    # BH format only when a B/H was actually read in its place:
                    # assuming the format would be a guess (and "__" is ambiguous).
                    if fmt == "bh" and not any(c.ch for c in segs[1].chars or []):
                        continue
                    out.append(_Layout(fmt, segs, round(cost, 3), notes))
    return out


def _clean(text: str, confidences: Sequence[float]) -> list[tuple[str, float]]:
    pairs = [(ch.upper(), float(c)) for ch, c in zip(text or "", confidences or [])]
    return [(ch, c) for ch, c in pairs if ch.isascii() and ch.isalnum()]


def analyze_read(text: str, confidences: Sequence[float],
                 threshold: float = UNKNOWN_CONF_THRESHOLD) -> list[_Layout]:
    """All layouts of one OCR read, best first (empty for an empty read).
    Cached: a live track re-merges the same reads on every new frame."""
    return _analyze_read_cached(text or "", tuple(round(float(c), 4) for c in confidences or []), threshold)


@functools.lru_cache(maxsize=4096)
def _analyze_read_cached(text: str, confidences: tuple, threshold: float) -> list[_Layout]:
    chars = _clean(text, confidences)
    variants = [(chars, 0.0, None)]
    raw = "".join(ch for ch, _ in chars)
    for token in EMBLEM_TOKENS:
        index = raw.find(token)
        if index >= 0:
            variants.append((chars[:index] + chars[index + len(token):], COST_EMBLEM_STRIPPED,
                             f"emblem text '{token}' removed"))
    layouts = []
    for variant, extra, note in variants:
        if not variant:
            continue
        for layout in _layouts(variant, threshold):
            layout.cost = round(layout.cost + extra, 3)
            if note:
                layout.notes.insert(0, note)
            layouts.append(layout)
    layouts.sort(key=lambda lay: (lay.cost, -lay.known))
    unique, seen = [], set()
    for layout in layouts:
        if layout.pattern not in seen and _parses_as(layout.pattern, layout.fmt):
            seen.add(layout.pattern)
            unique.append(layout)
    return unique


def _signature(layout: _Layout) -> tuple:
    """Which segments were read and how many characters each has."""
    return tuple((len(s.chars) if s.chars is not None else None, s.open_left, s.open_right) for s in layout.segs)


def _parses_as(pattern: str, fmt: str) -> bool:
    try:
        parsed_fmt, parts = parse_pattern(pattern)
        return parsed_fmt == fmt and all(_expansions(rule, tokens) for rule, tokens in parts)
    except ValueError:
        return False


def _merge_segments(fmt: str, layouts: list[_Layout], notes: list[str], conflicts: list[dict]) -> list[_Seg]:
    """Per segment: closed observations of one length are merged per character
    (highest confidence wins); otherwise the best partial observation is used."""
    def strength(seg):            # characters actually read, then their confidence
        return (sum(1 for c in seg.chars if c.ch), sum(c.conf for c in seg.chars if c.ch))

    merged = []
    for i, rule in enumerate(FORMATS[fmt]):
        observations = [lay.segs[i] for lay in layouts]
        options = []
        closed = [s for s in observations if s.closed]
        if closed:
            by_length = defaultdict(list)
            for s in closed:
                by_length[len(s.chars)].append(s)
            group = max(by_length.values(), key=lambda g: sum(c.conf for s in g for c in s.chars if c.ch))
            chars, disagreements = [], []
            for j in range(len(group[0].chars)):
                readings = [s.chars[j] for s in group]
                known = [c for c in readings if c.ch]
                best = max(known, key=lambda c: c.conf) if known else max(readings, key=lambda c: c.conf)
                if len({c.ch for c in known}) > 1:
                    disagreements.append({"segment": rule.name, "index": j, "kept": best.ch,
                                          "readings": sorted({(c.ch, round(c.conf, 3)) for c in known}, key=str)})
                chars.append(_Char(best.ch, best.conf, best.raw))
            reason = _segment_violation(_Seg(rule, chars))
            if reason:
                notes.append(f"{rule.name}: merged {reason} -> unknown")
                chars, disagreements = [_Char(None, c.conf, c.raw) for c in chars], []
            options.append((_Seg(rule, chars), disagreements))
        options += [(_Seg(rule, list(s.chars), s.open_left, s.open_right), [])
                    for s in observations if s.chars is not None and not s.closed]
        if not options:
            merged.append(_Seg(rule, None))
            continue
        # never prefer a reading with fewer characters actually read; closed wins ties
        seg, disagreements = max(options, key=lambda o: (*strength(o[0]), o[0].closed))
        for d in disagreements:
            notes.append(f"{d['segment']}[{d['index']}]: frames disagree {d['readings']} -> kept '{d['kept']}' "
                         f"(highest confidence)")
        conflicts.extend(disagreements)
        merged.append(seg)
    return merged


def _confidence(segs: list[_Seg], pattern: str) -> float:
    known = [c.conf for s in segs if s.chars for c in s.chars if c.ch]
    if not known:
        return 0.0
    unknown = pattern.count("_") + 0.5 * (pattern.count("*") + pattern.count("+"))
    return round(sum(known) / len(known) * len(known) / (len(known) + unknown), 3)


def _empty_result(reads, threshold, note) -> dict:
    pattern = " ".join(_Seg(r, None).tokens() for r in FORMATS["standard"])
    return {**describe_pattern(pattern), "source": "anpr", "partial_pattern": pattern,
            "raw_ocr_text": "", "char_confidences": [],
            "track_id": None, "frames_used": [], "alternative_patterns": [], "confidence": 0.0,
            "corrections": [], "conflicts": [], "notes": [note], "threshold": threshold, "reads": list(reads)}


def analyze_reads(reads: Sequence[dict], threshold: float = UNKNOWN_CONF_THRESHOLD) -> dict:
    """Partial plate for one violating vehicle.

    reads: [{"text", "confidences", "frame", "track_id"}], one per OCR'd frame.
    Reads are merged only within one raw tracker id; the tracker id whose
    merged pattern read the most characters is reported.
    """
    reads = [r for r in reads if r.get("text")]
    if not reads:
        return _empty_result([], threshold, "no OCR read for this vehicle")

    candidates = []
    by_track = defaultdict(list)
    for read in reads:
        by_track[read.get("track_id") or "?"].append(read)
    for track_id, group in by_track.items():
        analysed = [(read, analyze_read(read["text"], read["confidences"], threshold)) for read in group]
        analysed = [(read, lays) for read, lays in analysed if lays]
        if not analysed:
            continue
        # one format for the whole track: the lowest summed best cost
        fmt = min(FORMATS, key=lambda f: sum(min((lay.cost for lay in lays if lay.fmt == f), default=5.0)
                                             for _, lays in analysed))
        best = [(read, next(lay for lay in lays if lay.fmt == fmt)) for read, lays in analysed
                if any(lay.fmt == fmt for lay in lays)]
        # Positions are only comparable between reads laid out the same way:
        # merge the layout group with the most characters actually read.
        groups = defaultdict(list)
        for read, lay in best:
            groups[_signature(lay)].append((read, lay))
        ranked = sorted(groups.values(), key=lambda g: (-sum(lay.known for _, lay in g), -len(g)))
        kept = ranked[0]
        notes = [f"track {track_id}: {len(kept)} read(s) merged per character" if len(kept) > 1
                 else f"track {track_id}: single read"]
        # Frames that support another layout are not merged into this one, but
        # their merged pattern stays an alternative: choosing one layout when
        # frames disagree would be a guess, and could exclude the real plate.
        group_alternatives = []
        for group in ranked[1:]:
            if len(group) >= GROUP_MIN_READS and len(group) >= GROUP_MIN_SHARE * len(best):
                other = _merge_segments(fmt, [lay for _, lay in group], [], [])
                group_alternatives.append(" ".join(t for t in (s.tokens() for s in other) if t != ""))
        if len(kept) < len(best):
            notes.append(f"track {track_id}: {len(best) - len(kept)} read(s) with a different layout not merged; "
                         f"supported alternatives: {group_alternatives or 'none'}")
        best = kept
        conflicts: list[dict] = []
        segs = _merge_segments(fmt, [lay for _, lay in best], notes, conflicts)
        pattern = " ".join(t for t in (s.tokens() for s in segs) if t != "")
        anchor_read, anchor = max(best, key=lambda item: (item[1].known, -item[1].cost))
        alternatives = list(group_alternatives)
        if anchor.pattern == pattern:   # layout alternatives of the read the pattern came from
            lays = next(lays for read, lays in analysed if read is anchor_read)
            alternatives += [lay.pattern for lay in lays[1:] if lay.cost <= anchor.cost + ALT_MARGIN]
        alternatives = list(dict.fromkeys(a for a in alternatives if a != pattern))[:MAX_ALTERNATIVES]
        corrections = [f"frame {read.get('frame')}: {note}" for read, lay in best for note in lay.notes]
        candidates.append({
            "track_id": track_id, "pattern": pattern, "segs": segs, "alternatives": alternatives,
            "known": sum(1 for s in segs if s.chars for c in s.chars if c.ch),
            "confidence": _confidence(segs, pattern), "anchor": anchor_read, "notes": notes,
            "corrections": corrections, "conflicts": conflicts, "frames": [read.get("frame") for read, _ in best],
            "per_read": [{"frame": read.get("frame"), "track_id": track_id, "text": read["text"],
                          "confidences": [round(float(c), 3) for c in read["confidences"]],
                          "pattern": lay.pattern} for read, lay in best],
        })
    if not candidates:
        return _empty_result(reads, threshold, "no read fits the plate rules")

    chosen = max(candidates, key=lambda c: (c["known"], c["confidence"]))
    described = describe_pattern(chosen["pattern"])
    for seg in chosen["segs"]:
        described["segments"][seg.rule.name]["chars"] = (
            [{"char": c.ch, "raw": c.raw, "conf": round(c.conf, 3)} for c in seg.chars] if seg.chars else [])
    regexes = [described["regex"]] + [pattern_regex(p) for p in chosen["alternatives"]]
    other_tracks = [{"track_id": c["track_id"], "pattern": c["pattern"]} for c in candidates if c is not chosen]
    return {
        **described,
        "source": "anpr",
        "raw_ocr_text": chosen["anchor"]["text"],
        "char_confidences": [round(float(c), 3) for c in chosen["anchor"]["confidences"]],
        "partial_pattern": described["pattern"],
        "alternative_patterns": chosen["alternatives"],
        # union of every plausible layout, for DB / RFID matching
        "regex": regexes[0] if len(regexes) == 1 else "^(?:" + "|".join(r[1:-1] for r in regexes) + ")$",
        "confidence": chosen["confidence"],
        "track_id": chosen["track_id"],
        "frames_used": chosen["frames"],
        "other_tracks": other_tracks,
        "corrections": chosen["corrections"],
        # positions where frames of the track confidently read different characters
        "conflicts": chosen["conflicts"],
        "notes": chosen["notes"],
        "threshold": threshold,
        "reads": chosen["per_read"],
    }


def candidate_plates(result: dict, plates: Sequence[str]) -> list[dict]:
    """Registered plates that fit the partial pattern (or any alternative layout)."""
    patterns = [result["partial_pattern"]] + list(result.get("alternative_patterns") or [])
    out = []
    for plate in plates:
        score = max(match_pattern(p, plate) for p in patterns)
        if score > 0:
            out.append({"plate": plate, "score": score})
    return sorted(out, key=lambda c: (-c["score"], c["plate"]))
