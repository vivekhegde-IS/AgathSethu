"""Every tunable for RFID -> camera plate cross-verification, in one place.

All values are overridable from the environment (prefix ``RFID_`` /
``INCIDENT_``) so nothing is baked into the code. No secrets here: the DB URL
stays in ``DATABASE_URL``.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from app.core.config import data_dir

BACKEND_DIR = Path(__file__).resolve().parents[3]

# The 8 simulated registrations (test data only, matching vivek_fb.py).
# Single source: app/core/fleet.py
from app.core.fleet import PLATES as SEED_PLATES  # noqa: E402

# Junction world coordinates (matches vivek_fb.py and carla_ws.py).
JUNCTION_WORLD = {
    "J01": (-28.7, 28.1),
    "J02": (-41.6, 82.6),
    "J03": (-71.3, 132.3),
}


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RfidFeatureConfig:
    # ---------------- rolling buffers ----------------
    buffer_window_s: float = 120.0          # sim seconds of reads kept per junction
    snapshot_before_s: float = 30.0         # crash-zone / context snapshot window
    snapshot_after_s: float = 30.0

    # ---------------- incident assembly / runs ----------------
    alert_merge_window_s: float = 5.0       # later alerts for the same crash
    run_reset_backjump_s: float = 5.0       # timestamp_sim going back = new run
    run_reset_gap_s: float = 30.0           # only used when run_reset_on_reconnect
    # A reconnect alone never starts a new run while sim time keeps increasing.
    run_reset_on_reconnect: bool = False
    # Same (run, reader, seq) re-sent with an event time this far off = the
    # reader (CARLA script) restarted with the same run_id.
    reader_restart_tolerance_s: float = 1.0

    # ---------------- watchlist / sightings ----------------
    watch_nearby_default: bool = False      # also watch non-involved tags
    sighting_gap_s: float = 4.0             # report drop-outs up to this are tolerated
    sighting_close_s: float = 4.0           # no reports this long -> close
    sighting_merge_s: float = 20.0          # a closed, unfinalized sighting reopens within this
    sighting_max_s: float = 60.0            # safety cap on one sighting
    # An incident watches its vehicles' tags this long after its crash (and
    # never past a newer collision of the same vehicles).
    watch_window_s: float = 120.0

    # ---------------- vision verification ----------------
    vision_ring_s: float = 30.0             # raw JPEG ring buffer per camera
    vision_frames_max: int = 12             # frames ANPR'd per sighting (spread)
    vision_window_before_s: float = 6.0     # camera is ~25-35 m before the junction
    vision_window_after_s: float = 3.0
    vision_conf_threshold: float = 0.60     # ANPR confidence for a real match
    vision_frames_to_confirm: int = 2       # agreeing frames needed
    vision_single_frame_conf: float = 0.85  # (no longer confirms on its own: one frame is never enough)
    vision_agreement_min: float = 0.6       # share of the vehicle's reads that must read the plate exactly
    vision_probable_edit_distance: int = 1  # "unconfirmed" band
    vision_workers: int = 1                 # ANPR passes in parallel
    vision_retry_interval_s: float = 2.0    # min gap between ANPR passes per sighting
    vision_crash_frame_window_s: float = 1.0
    # OCR two-line split threshold for this feed: 0 = never split (the CARLA
    # overlay plates are single-line).
    ocr_two_line_aspect: float = 0.0

    # ---------------- plate rules (applied to EVERY read) ----------------
    plate_series_letters: int = 2           # series letters (positions 5-6)
    plate_number_digits: int = 4            # trailing digits
    gate_min_plate_px: float = 18.0         # plate box narrower than this = too small
    gate_aspect_min: float = 2.0            # plate box width / height
    gate_aspect_max: float = 6.0
    gate_min_det_conf: float = 0.30         # detector confidence
    max_extra_chars: int = 2                # OCR chars dropped to fit the format

    # ---------------- fusion ----------------
    promote_rule_assisted: bool = False     # rule-assisted PROBABLE counts as CONFIRMED
    rule_assisted_min_frames: int = 2       # frames that must agree on a confusable diff
    # Confusable pairs for rule-assisted matching (comma separated).
    confusable_pairs: str = "MH,0O,0D,OD,1I,5S,8B,2Z,6G,UV"
    cluster_text_distance: int = 2          # reads this close join one vehicle cluster
    cluster_box_px: float = 80.0            # ...or boxes this close in nearby frames
    cluster_box_dt_s: float = 1.0

    # ---------------- events ----------------
    emit_debounce_s: float = 3.0            # min wall time between result pushes per sighting

    # ---------------- evidence ----------------
    evidence_dir: str = str(data_dir() / "runtime" / "incident_evidence")
    evidence_max_frames: int = 3            # distinct strip frames per sighting
    evidence_jpeg_quality: int = 90
    evidence_min_gap_s: float = 0.6         # distinct frames: min sim-time gap ...
    evidence_min_hash_distance: int = 6     # ... and min perceptual-hash distance

    # ---------------- persistence ----------------
    db_queue_max: int = 5000                # buffered writes if Postgres is down
    db_retry_min_s: float = 1.0
    db_retry_max_s: float = 30.0
    db_batch_max: int = 50

    # ---------------- fusion health (header badge) ----------------
    health_rfid_stale_s: float = 10.0
    health_frame_stale_s: float = 10.0
    health_anpr_stale_s: float = 120.0
    health_queue_backlog: int = 4

    # ---------------- NETRA shadow association (netra/) ----------------
    # Off by default. When on, every vision pass also asks NETRA which visible
    # vehicle carries the sighted EPC (RFID reads + camera boxes only) and
    # attaches the answer to the result payload as "netra". The decision path
    # itself is unchanged. alpha / delta are fixed by the calibration file
    # (tools/netra_calibrate.py --alpha); without the file NETRA never confirms.
    netra_enabled: bool = False
    netra_calibration: str = str(BACKEND_DIR / "data" / "netra_calibration.json")
    netra_reads_margin_s: float = 20.0      # other tags' reads considered around the pass
    netra_history_s: float = 660.0          # NETRA's own reports + boxes history (clock window 600 s)

    # ---------------- misc ----------------
    enabled: bool = True
    seq_gap_log_every: int = 1              # log every gap (spec asks for the counters)

    # env names that predate the RFID_<FIELD> convention
    _ENV_ALIASES = {"watch_nearby_default": "RFID_WATCH_NEARBY"}

    @classmethod
    def from_env(cls) -> "RfidFeatureConfig":
        """Every field from RFID_<FIELD_NAME> (falls back to the default)."""
        values = {}
        for item in fields(cls):
            name = cls._ENV_ALIASES.get(item.name, "RFID_" + item.name.upper())
            default = getattr(cls, item.name)
            if isinstance(default, bool):
                values[item.name] = _bool(name, default)
            elif isinstance(default, int):
                values[item.name] = _int(name, default)
            elif isinstance(default, float):
                values[item.name] = _float(name, default)
            else:
                values[item.name] = os.environ.get(name, default)
        return cls(**values)

    def as_dict(self) -> dict:
        return asdict(self)

    def confusable_set(self) -> set:
        pairs = set()
        for pair in self.confusable_pairs.split(","):
            pair = pair.strip().upper()
            if len(pair) == 2:
                pairs.add(frozenset(pair))
        return pairs


DEFAULT_CONFIG = RfidFeatureConfig()


# Vision statuses, in the order they improve.
STATUS_NO_PLATE_VISIBLE = "NO_PLATE_VISIBLE"
STATUS_PLATE_TOO_SMALL = "PLATE_TOO_SMALL"
STATUS_NOT_CONFIRMED = "NOT_CONFIRMED"
STATUS_PROBABLE_MATCH = "PROBABLE_MATCH"
STATUS_VISION_CONFIRMED = "VISION_CONFIRMED"

STATUS_RANK = {
    STATUS_NO_PLATE_VISIBLE: 0,
    STATUS_PLATE_TOO_SMALL: 0,
    STATUS_NOT_CONFIRMED: 1,
    STATUS_PROBABLE_MATCH: 2,
    STATUS_VISION_CONFIRMED: 3,
}

# Roles used in incident_vehicles.
ROLE_INVOLVED = "involved"
ROLE_NEARBY = "nearby"
# The involved vehicle Member 1 reported as escaping (vehicle_state escape_confirmed).
ROLE_FLED = "fled"

UNREGISTERED_TAG = "UNREGISTERED_TAG"

# Before vision has run for a sighting (the portal shows "awaiting vision").
STATUS_AWAITING_VISION = "AWAITING_VISION"

# incidents.source
SOURCE_LIVE = "live"
SOURCE_REPLAY = "replay"
SOURCE_SYNTHETIC = "synthetic"
