"""Rolling per-junction buffer of normalized RFID reads.

Holds ``buffer_window_s`` of sim time per junction, dedupes on
``(run_id, reader_id, seq)`` and counts sequence gaps. The crash-zone snapshot
is a *window query* over this buffer, so no separate "keep capturing" state is
needed: the buffer already covers ``t_crash ± snapshot`` windows.

Reads are kept sorted by EVENT time even when they arrive slightly out of order
(a reader emits one report per tag per interval, so ``last_seen_ts`` interleaves
across tags). Every read also gets a monotonic ``ingest_index`` so incremental
consumers (the watchlist) never skip a late arrival.

Buffers are scoped by run: ``reset_run()`` empties them when the service detects
a new CARLA run (new ``run_id``, or sim time jumping backwards).
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.services.rfid.config import DEFAULT_CONFIG, ROLE_INVOLVED, ROLE_NEARBY
from app.services.rfid.normalize import RfidRead, SequenceTracker


@dataclass
class CoalescedRead:
    """All reads of one tag at one junction, folded into one row."""

    epc: str
    junction_id: str
    reader_id: str
    plate_norm: str | None
    first_seen_ts: float
    last_seen_ts: float
    report_count: int
    tag_seen_count: int
    peak_rssi_dbm: float | None
    role: str = ROLE_INVOLVED

    def as_dict(self) -> dict:
        return {
            "epc": self.epc, "junction_id": self.junction_id, "reader_id": self.reader_id,
            "plate_norm": self.plate_norm, "first_seen_ts": self.first_seen_ts,
            "last_seen_ts": self.last_seen_ts, "report_count": self.report_count,
            "tag_seen_count": self.tag_seen_count, "peak_rssi_dbm": self.peak_rssi_dbm,
            "role": self.role,
        }


class JunctionBuffer:
    """Time-ordered reads for one junction."""

    def __init__(self, window_s: float = DEFAULT_CONFIG.buffer_window_s):
        self.window_s = window_s
        self.reads: list[RfidRead] = []
        self._times: list[float] = []

    def add(self, read: RfidRead) -> None:
        """Insert in event-time order (appends in the common, in-order case)."""
        index = bisect_right(self._times, read.event_time)
        self.reads.insert(index, read)
        self._times.insert(index, read.event_time)

    def prune(self, now_ts: float) -> int:
        """Drop reads older than the window. Returns how many were dropped."""
        cutoff = now_ts - self.window_s
        if not self._times or self._times[0] >= cutoff:
            return 0
        index = bisect_left(self._times, cutoff)
        if index <= 0:
            return 0
        del self.reads[:index]
        del self._times[:index]
        return index

    def window(self, start_ts: float, end_ts: float) -> list[RfidRead]:
        if not self._times:
            return []
        lo = bisect_left(self._times, start_ts)
        return [read for read in self.reads[lo:] if read.event_time <= end_ts]

    def latest_for_epc(self, epc: str) -> RfidRead | None:
        for read in reversed(self.reads):
            if read.epc == epc:
                return read
        return None


class ReadBuffer:
    """All junctions plus the global dedupe / gap counters."""

    def __init__(self, window_s: float = DEFAULT_CONFIG.buffer_window_s):
        self.window_s = window_s
        self.junctions: dict[str, JunctionBuffer] = defaultdict(
            lambda: JunctionBuffer(self.window_s))
        self.sequence = SequenceTracker()
        self.last_event_ts: float = 0.0
        self.total_received = 0
        self.by_schema: Counter = Counter()
        self.ingest_counter = 0
        self.epoch = 0                      # bumped by reset_run()
        self.run_id: str | None = None      # run_id carried by v2 reports, if any
        self.run_resets: list[str] = []

    # ---------------- ingest ----------------

    def add(self, read: RfidRead) -> str:
        """Store a read. Returns the SequenceTracker verdict."""
        verdict, _missing = self.sequence.observe(read)
        if verdict == "duplicate":
            # The transport re-sent an already-stored report: never store twice.
            return verdict

        self.ingest_counter += 1
        read.ingest_index = self.ingest_counter
        if read.run_id:
            self.run_id = read.run_id
        self.junctions[read.junction_id].add(read)
        self.total_received += 1
        self.by_schema[read.schema] += 1
        self.last_event_ts = max(self.last_event_ts, read.event_time)
        if self.total_received % 200 == 0:
            self.prune()
        return verdict

    def is_new_run(self, read: RfidRead, backjump_s: float,
                   restart_tolerance_s: float = 1.0) -> str | None:
        """The reason this read starts a new run, or None."""
        if self.sequence.is_restart(read, restart_tolerance_s):
            self.sequence.restarts += 1
            return (f"rfid reader {read.reader_id} restarted: seq {read.seq} of run "
                    f"{read.run_id} re-sent with a different event time")
        if read.run_id and self.run_id and read.run_id != self.run_id:
            return f"rfid run_id changed {self.run_id} -> {read.run_id}"
        if self.total_received and read.event_time < self.last_event_ts - backjump_s:
            return (f"rfid event time went back {self.last_event_ts:.2f}s -> "
                    f"{read.event_time:.2f}s")
        return None

    def reset_run(self, reason: str) -> None:
        """Forget the previous run's reads. Counters and dedupe history stay."""
        self.junctions.clear()
        self.sequence.new_run()
        self.last_event_ts = 0.0
        self.run_id = None
        self.epoch += 1
        self.run_resets.append(reason)

    def prune(self) -> None:
        for buffer in self.junctions.values():
            buffer.prune(self.last_event_ts)

    # ---------------- queries ----------------

    def window(self, junction_id: str, start_ts: float, end_ts: float) -> list[RfidRead]:
        return self.junctions.get(junction_id, JunctionBuffer()).window(start_ts, end_ts)

    def since(self, ingest_index: int) -> list[RfidRead]:
        """Every buffered read that arrived after ``ingest_index``, any junction."""
        return [read for buffer in list(self.junctions.values()) for read in buffer.reads
                if read.ingest_index > ingest_index]

    def coalesce(self, reads: list[RfidRead], registry, involved_epcs: set[str] | None = None,
                 involved_plates: set[str] | None = None) -> list[CoalescedRead]:
        """Fold reads per EPC into one row each, marking role.

        The plate comes from the REGISTRY (via the EPC), never from a message.
        """
        involved_epcs = involved_epcs or set()
        involved_plates = involved_plates or set()
        grouped: dict[str, list[RfidRead]] = defaultdict(list)
        for read in reads:
            grouped[read.epc].append(read)

        out: list[CoalescedRead] = []
        for epc, items in grouped.items():
            entry, _warning = registry.resolve(epc)
            plate = entry.plate_norm
            involved = epc in involved_epcs or (plate is not None and plate in involved_plates)
            rssis = [item.peak_rssi for item in items if item.peak_rssi is not None]
            out.append(CoalescedRead(
                epc=epc,
                junction_id=items[0].junction_id,
                reader_id=items[0].reader_id,
                plate_norm=plate,
                first_seen_ts=min(item.first_seen_ts for item in items),
                last_seen_ts=max(item.last_seen_ts for item in items),
                report_count=len(items),
                tag_seen_count=sum(item.count for item in items),
                peak_rssi_dbm=(max(rssis) if rssis else None),
                role=ROLE_INVOLVED if involved else ROLE_NEARBY,
            ))
        out.sort(key=lambda row: (row.first_seen_ts, row.epc))
        return out

    def most_recent_reader_for(self, epcs: set[str], before_ts: float) -> str | None:
        """Which junction most recently read any of these tags (crash-junction cross-check)."""
        best_junction, best_time = None, None
        for junction_id, buffer in self.junctions.items():
            for epc in epcs:
                read = buffer.latest_for_epc(epc)
                if read is None or read.event_time > before_ts:
                    continue
                if best_time is None or read.event_time > best_time:
                    best_junction, best_time = junction_id, read.event_time
        return best_junction

    def counters(self) -> dict:
        return {
            "total_received": self.total_received,
            "by_schema": dict(self.by_schema),
            "epoch": self.epoch,
            "run_resets": list(self.run_resets),
            "junctions": {junction: len(buffer.reads)
                          for junction, buffer in sorted(self.junctions.items())},
            **self.sequence.counters(),
        }
