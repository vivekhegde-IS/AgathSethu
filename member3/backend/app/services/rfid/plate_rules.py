"""Rule-based plate checks applied to EVERY ANPR read before voting/display.

Reuses the routine-violation validator (``app.services.plate_validation``):
cleaning, position-aware digit/letter fixes, state-code correction ranked by
per-character OCR confidence + visual confusion + edit distance. Two feed
rules are fixed here:

* the regional / majority-state prior is OFF (``state_prior=None``): the
  simulated plates span eight states;
* the RFID plate is NEVER an input: a read is corrected blind.

Order per detection:
  1. geometry gating (box width, aspect ratio, detector confidence) - a gated
     detection is "unreadable", never a read;
  2. every OCR variant of the crop through validate_plate; the best VALID
     variant wins (validity, not low-confidence, mean confidence);
  3. extra rejections the validator does not make on its own (too many stray
     characters dropped to fit the format).

Reads that still do not fit are kept as REJECTED reads (raw text + reason
codes) for the audit trail, and are never shown as plates or matched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.plate_validation import (
    STATE_CODES,
    clean_plate_text,
    parse_plate,
    rank_state_codes,
    validate_plate,
)
from app.services.rfid.config import DEFAULT_CONFIG, RfidFeatureConfig

# Reason codes (stable strings; the portal shows them).
GATE_TOO_SMALL = "PLATE_TOO_SMALL"
GATE_ASPECT = "BAD_ASPECT_RATIO"
GATE_DET_CONF = "LOW_DETECTION_CONFIDENCE"
NO_OCR_TEXT = "NO_OCR_TEXT"
TOO_SHORT = "TOO_SHORT"
BAD_FORMAT = "BAD_FORMAT"
EXTRA_CHARS = "EXTRA_CHARACTERS"
STATE_CORRECTED = "STATE_CORRECTED"
POSITION_FIXED = "POSITION_FIXED"
LOW_CONFIDENCE = "LOW_CONFIDENCE"


@dataclass
class RuleRead:
    """One detection in one frame, after the plate rules."""

    box: tuple
    det_confidence: float
    width_px: float
    height_px: float
    raw: str | None = None             # OCR text as read (best variant)
    corrected: str | None = None       # rule-corrected plate (only when valid)
    window: str | None = None          # the plate window as READ, before any fix
    state_corrected: bool = False      # the state code was a ranked guess, not as read
    valid: bool = False
    gated: str | None = None           # gating reason: detection is unreadable
    reasons: list = field(default_factory=list)    # reason codes
    changes: list = field(default_factory=list)    # human-readable corrections
    char_conf: list = field(default_factory=list)  # one per corrected character
    mean_conf: float = 0.0
    state_code: str | None = None
    state_name: str | None = None
    state_candidates: list = field(default_factory=list)  # [(code, cost)] when corrected
    low_confidence: bool = False
    variant: str | None = None
    sharpness: float = 0.0             # variance of Laplacian of the plate crop

    @property
    def aspect(self) -> float:
        return self.width_px / max(1.0, self.height_px)

    @property
    def readable(self) -> bool:
        return self.gated is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "box": [round(float(v), 1) for v in self.box],
            "det_confidence": self.det_confidence, "width_px": round(self.width_px, 1),
            "height_px": round(self.height_px, 1), "raw": self.raw, "corrected": self.corrected,
            "valid": self.valid, "gated": self.gated, "reasons": list(self.reasons),
            "window": self.window, "state_corrected": self.state_corrected,
            "changes": list(self.changes), "char_conf": list(self.char_conf),
            "mean_conf": round(self.mean_conf, 4), "state_code": self.state_code,
            "state_name": self.state_name, "variant": self.variant,
            "low_confidence": self.low_confidence,
            "state_candidates": [[code, round(cost, 3)] for code, cost in self.state_candidates],
        }


def _get(read, name, default=None):
    if isinstance(read, dict):
        return read.get(name, default)
    return getattr(read, name, default)


def gate(box, det_conf: float, cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> str | None:
    """Reason code when a detection is not a usable plate, else None."""
    width = float(box[2] - box[0])
    height = float(box[3] - box[1])
    if width < cfg.gate_min_plate_px:
        return GATE_TOO_SMALL
    aspect = width / max(1.0, height)
    if aspect < cfg.gate_aspect_min or aspect > cfg.gate_aspect_max:
        return GATE_ASPECT
    if det_conf < cfg.gate_min_det_conf:
        return GATE_DET_CONF
    return None


def check_text(text: str | None, confidences=None,
               cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> dict:
    """Validate ONE OCR string. Blind, no regional prior.

    Returns {valid, corrected, reasons, changes, char_conf, mean_conf,
    state_code, state_name, state_candidates, low_confidence}.
    """
    cleaned = clean_plate_text(text)
    confs = list(confidences or [])
    if len(confs) != len(cleaned):
        confs = []
    series = (cfg.plate_series_letters, cfg.plate_number_digits)
    out = {"valid": False, "corrected": None, "reasons": [], "changes": [],
           "char_conf": [], "mean_conf": (sum(confs) / len(confs)) if confs else 0.0,
           "state_code": None, "state_name": None, "state_candidates": [],
           "low_confidence": False, "window": None, "state_corrected": False}
    if not cleaned:
        out["reasons"].append(NO_OCR_TEXT)
        return out

    validation = validate_plate(cleaned, confs or None,
                                series_letters=(series[0], series[0]),
                                number_digits=(series[1], series[1]),
                                state_prior=None, log=False)
    out["changes"] = list(validation.changes)
    if not validation.valid:
        reason = validation.reason or ""
        out["reasons"].append(TOO_SHORT if reason.startswith("too short") else BAD_FORMAT)
        return out

    length = 4 + series[0] + series[1]
    if len(cleaned) - length > cfg.max_extra_chars:
        # The validator found a plate-shaped window inside a much longer string
        # (e.g. two lines of junk): too much was thrown away to trust it.
        out["reasons"].append(EXTRA_CHARS)
        return out

    parsed = parse_plate(cleaned, confs or None, (series[0], series[0]), (series[1], series[1]))
    char_conf = list(parsed.confidences) if (parsed and confs) else [1.0] * length
    out.update(valid=True, corrected=validation.plate, char_conf=[round(c, 4) for c in char_conf],
               mean_conf=(sum(char_conf) / len(char_conf)) if char_conf else 0.0,
               state_code=validation.state_code, state_name=validation.state_name,
               low_confidence=validation.low_confidence,
               window=(parsed.chars if parsed else None))
    state_changed = any(change.startswith("state ") for change in validation.changes)
    if out["window"] and validation.plate and out["window"][:2] != validation.plate[:2] \
            and state_changed:
        # the state code is a ranked guess, not what the OCR read
        out["state_corrected"] = True
    if any(change.startswith("state ") for change in validation.changes):
        out["reasons"].append(STATE_CORRECTED)
        raw_state = (parsed.chars[:2] if parsed else cleaned[:2])
        out["state_candidates"] = rank_state_codes(raw_state, char_conf[:2], limit=3)
    if any(change.split(" ")[0] in ("district", "series", "number") for change in validation.changes):
        out["reasons"].append(POSITION_FIXED)
    if validation.low_confidence:
        out["reasons"].append(LOW_CONFIDENCE)
    return out


def apply_rules(plate_read, cfg: RfidFeatureConfig = DEFAULT_CONFIG,
                sharpness: float = 0.0) -> RuleRead:
    """Plate rules for one adapter PlateRead (object or dict)."""
    box = tuple(_get(plate_read, "box"))
    det_conf = float(_get(plate_read, "det_confidence", 0.0) or 0.0)
    rule = RuleRead(box=box, det_confidence=det_conf,
                    width_px=float(box[2] - box[0]), height_px=float(box[3] - box[1]),
                    sharpness=sharpness)

    gated = gate(box, det_conf, cfg)
    if gated is None and _get(plate_read, "skipped"):
        gated = GATE_TOO_SMALL
    if gated is not None:
        rule.gated = gated
        rule.reasons.append(gated)
        return rule

    variants = list(_get(plate_read, "ocr_variants", None) or [])
    if not variants and _get(plate_read, "raw_ocr"):
        # a reader without the variant list: judge its single best string
        per_char = _get(plate_read, "per_char", None) or []
        raw = _get(plate_read, "raw_ocr")
        confs = [float(c) for _, c in per_char] if len(per_char) == len(clean_plate_text(raw)) else None
        variants = [{"text": raw, "confidences": confs, "variant": "best"}]
    if not variants:
        rule.reasons.append(NO_OCR_TEXT)
        return rule

    best = None
    for variant in variants:
        checked = check_text(variant.get("text"), variant.get("confidences"), cfg)
        key = (checked["valid"], not checked["low_confidence"], checked["mean_conf"])
        if best is None or key > best[0]:
            best = (key, variant, checked)
    _, variant, checked = best
    rule.raw = variant.get("text")
    rule.variant = variant.get("variant")
    rule.valid = checked["valid"]
    rule.corrected = checked["corrected"]
    rule.reasons = checked["reasons"]
    rule.changes = checked["changes"]
    rule.char_conf = checked["char_conf"]
    rule.mean_conf = checked["mean_conf"]
    rule.state_code = checked["state_code"]
    rule.state_name = checked["state_name"]
    rule.state_candidates = checked["state_candidates"]
    rule.window = checked["window"]
    rule.state_corrected = checked["state_corrected"]
    rule.low_confidence = checked["low_confidence"]
    return rule


def state_name(plate: str | None) -> str | None:
    return STATE_CODES.get((plate or "")[:2])
