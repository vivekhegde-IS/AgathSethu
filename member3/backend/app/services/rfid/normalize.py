"""Normalize both RFID wire formats into one internal ``RfidRead``.

Two formats arrive on the same WebSocket:

* **legacy** - one message per successful read, carrying ground truth
  (``vehicle_id``, ``plate_number``, ``distance_m``, ``speed_kmh``, ``confidence``).
* **v2** (``schema: rfid_tag_report_v2``) - one aggregated TAG_REPORT per tag per
  reporting interval, carrying only RF data plus the event-time window.

Everything downstream sees only ``RfidRead``.

Rules that matter:

* **Event time** is ``first_seen_ts`` / ``last_seen_ts``. ``timestamp_sim`` is the
  report's *emission* time and ``received_at`` is wall clock: neither is ever used
  for a window.
* ``vehicle_id`` and the legacy ``distance_m``/``speed_kmh`` are GROUND TRUTH the
  real reader would not know. They are kept in ``debug`` fields and never used in
  matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_V2 = "rfid_tag_report_v2"
SCHEMA_LEGACY = "legacy"


def junction_label(value: Any) -> str | None:
    """'J02' / '2' / 2 -> 'J02'."""
    if value is None:
        return None
    text = str(value).strip().upper()
    if text.startswith("J"):
        text = text[1:]
    if not text.isdigit():
        return None
    return f"J{int(text):02d}"


@dataclass
class RfidRead:
    """One normalized RFID observation, in event time."""

    epc: str
    reader_id: str
    junction_id: str
    first_seen_ts: float
    last_seen_ts: float
    count: int = 1
    peak_rssi: float | None = None
    run_id: str | None = None
    seq: int | None = None
    antenna_id: str | None = None
    schema: str = SCHEMA_LEGACY
    # emission / arrival, diagnostics only
    timestamp_sim: float | None = None
    frame: int | None = None
    received_at: str | None = None
    # legacy ground truth: DEBUG ONLY, never used in matching
    debug_plate: str | None = None
    debug_distance_m: float | None = None
    debug_speed_kmh: float | None = None
    debug_vehicle_id: str | None = None
    debug_confidence: float | None = None
    warnings: list = field(default_factory=list)
    # Arrival order in the buffer: consumers keep a cursor on this, not on
    # event time, so a report that arrives slightly out of order is not lost.
    ingest_index: int = 0

    @property
    def dedupe_key(self) -> tuple:
        """(run, reader, seq) - the identity the backend must not double-store."""
        return (self.run_id or "", self.reader_id, self.seq if self.seq is not None else -1)

    @property
    def is_v2(self) -> bool:
        return self.schema == SCHEMA_V2

    @property
    def event_time(self) -> float:
        return self.last_seen_ts

    def merge_count(self, other: "RfidRead") -> None:
        """Fold a duplicate report into this one (idempotent re-delivery)."""
        self.count += other.count
        self.last_seen_ts = max(self.last_seen_ts, other.last_seen_ts)
        self.first_seen_ts = min(self.first_seen_ts, other.first_seen_ts)
        if other.peak_rssi is not None:
            self.peak_rssi = other.peak_rssi if self.peak_rssi is None else max(self.peak_rssi, other.peak_rssi)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def parse_message(message: dict, received_at: str | None = None) -> RfidRead | None:
    """Parse either format. Returns None for anything unusable (never raises)."""
    if not isinstance(message, dict):
        return None
    if message.get("type") not in (None, "rfid_reading", "rfid_tag_report"):
        return None

    epc = message.get("epc") or message.get("tag_id")
    if not epc:
        return None
    epc = str(epc).strip().upper()

    junction = junction_label(message.get("junction_id"))
    reader_id = str(message.get("reader_id") or (f"RFID_{junction}_01" if junction else "unknown"))
    if junction is None:
        return None

    warnings: list[str] = []
    is_v2 = message.get("schema") == SCHEMA_V2 or message.get("type") == "rfid_tag_report"

    first_seen = _float(message.get("first_seen_ts"))
    last_seen = _float(message.get("last_seen_ts"))
    timestamp_sim = _float(message.get("timestamp_sim"))

    if is_v2:
        if first_seen is None or last_seen is None:
            # A v2 report without its event window is unusable.
            return None
        if last_seen < first_seen:
            warnings.append(f"last_seen_ts < first_seen_ts ({last_seen} < {first_seen})")
            first_seen, last_seen = last_seen, first_seen
        count = _int(message.get("tag_seen_count")) or 1
    else:
        # Legacy: one read = one observation. The only time it has is the
        # emission stamp, which is the closest thing to an event time available.
        when = first_seen if first_seen is not None else timestamp_sim
        if when is None:
            return None
        first_seen = last_seen = when
        count = 1

    return RfidRead(
        epc=epc,
        reader_id=reader_id,
        junction_id=junction,
        first_seen_ts=float(first_seen),
        last_seen_ts=float(last_seen),
        count=count,
        peak_rssi=_float(message.get("rssi_dbm")),
        run_id=(str(message["run_id"]) if message.get("run_id") else None),
        seq=_int(message.get("seq")),
        antenna_id=(str(message["antenna_id"]) if message.get("antenna_id") is not None else None),
        schema=SCHEMA_V2 if is_v2 else SCHEMA_LEGACY,
        timestamp_sim=timestamp_sim,
        frame=_int(message.get("frame")),
        received_at=received_at or _utc_now_iso(),
        debug_plate=message.get("plate_number"),
        debug_distance_m=_float(message.get("distance_m")),
        debug_speed_kmh=_float(message.get("speed_kmh")),
        debug_vehicle_id=(str(message["vehicle_id"]) if message.get("vehicle_id") else None),
        debug_confidence=_float(message.get("confidence")),
        warnings=warnings,
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class SequenceTracker:
    """Per-reader seq bookkeeping: gaps, duplicates and reader restarts.

    ``seq`` is monotonic per reader, so a jump means the transport dropped
    reports and a repeat means the sender re-sent one. The SAME
    (run, reader, seq) arriving with a different event time is not a re-send:
    the reader restarted (a new CARLA script start that reused its run_id).
    History is scoped by epoch, so after a run reset a restarted reader's
    reports are not mistaken for duplicates of the previous run.
    """

    expected: dict = field(default_factory=dict)     # reader_id -> next seq
    gaps: dict = field(default_factory=dict)         # reader_id -> missing count
    gap_events: dict = field(default_factory=dict)   # reader_id -> gap count
    duplicates_ignored: int = 0
    accepted: int = 0
    seen: dict = field(default_factory=dict)         # (epoch, run, reader, seq) -> event time
    last_missing: int = 0                            # missing count of the last observe()
    epoch: int = 0
    restarts: int = 0

    def _key(self, read: RfidRead) -> tuple:
        return (self.epoch,) + read.dedupe_key

    def is_restart(self, read: RfidRead, tolerance_s: float = 1.0) -> bool:
        """Same (run, reader, seq) as an earlier report but a different event time."""
        if read.seq is None:
            return False
        previous = self.seen.get(self._key(read))
        return previous is not None and abs(previous - read.last_seen_ts) > tolerance_s

    def observe(self, read: RfidRead) -> tuple[str, int]:
        """('new'|'duplicate'|'gap'|'no_seq', missing_count)."""
        self.last_missing = 0
        if read.seq is None:
            self.accepted += 1
            return "no_seq", 0

        key = self._key(read)
        if key in self.seen:
            self.duplicates_ignored += 1
            return "duplicate", 0

        self.seen[key] = read.last_seen_ts
        self.accepted += 1

        previous = self.expected.get(read.reader_id)
        self.expected[read.reader_id] = read.seq + 1
        if previous is None:
            return "new", 0
        if read.seq > previous:
            missing = read.seq - previous
            self.gaps[read.reader_id] = self.gaps.get(read.reader_id, 0) + missing
            self.gap_events[read.reader_id] = self.gap_events.get(read.reader_id, 0) + 1
            self.last_missing = missing
            return "gap", missing
        # seq <= previous and not an exact duplicate: reordering, not a gap.
        return "new", 0

    def new_run(self) -> None:
        """seq restarts with a new run: fresh expectations, fresh dedupe scope."""
        self.expected.clear()
        self.epoch += 1
        # keep the history bounded: the previous epochs can never match again
        self.seen = {key: ts for key, ts in self.seen.items() if key[0] >= self.epoch - 1}

    def counters(self) -> dict:
        return {
            "accepted": self.accepted,
            "duplicates_ignored": self.duplicates_ignored,
            "missing_reports": dict(self.gaps),
            "gap_events": dict(self.gap_events),
            "reader_restarts": self.restarts,
        }
