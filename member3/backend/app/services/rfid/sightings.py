"""Watchlist and next-junction sightings.

After the crash, the involved tags are watched. A read of a watchlisted tag at a
junction OTHER than the crash junction, in EVENT TIME after the crash, is a
watchlist hit, and coalesces into a sighting per (incident, EPC, junction).

Pre-crash reads and crash-junction reads are ignored by design - the car is
already at the crash site. A missed RFID pass simply produces no sighting: that
is expected, so it is logged and never raised.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.rfid.config import DEFAULT_CONFIG, RfidFeatureConfig
from app.services.rfid.normalize import RfidRead

# Reasons a read did not become a sighting.
IGNORE_NOT_WATCHLISTED = "not on the watchlist"
IGNORE_PRE_CRASH = "before the crash"
IGNORE_CRASH_JUNCTION = "at the crash junction"
IGNORE_NO_INCIDENT = "no incident"
IGNORE_WATCH_ENDED = "after the incident's watch window"


@dataclass
class SightingDraft:
    incident_key: str
    epc: str
    plate_norm: str | None
    junction_id: str
    reader_id: str
    first_seen_ts: float
    last_seen_ts: float
    report_count: int = 0
    tag_seen_count: int = 0
    peak_rssi_dbm: float | None = None
    closed: bool = False
    sighting_id: str | None = None      # set once persisted
    notified: bool = False
    # Best verification result so far: the DB row is upgraded, never downgraded.
    best_status: str | None = None
    best_confidence: float = 0.0
    vision_attempts: int = 0
    last_attempt_ts: float | None = None
    # One vision_matches row per sighting: the id is minted once and reused on
    # every upgrade, so evidence rows always point at the row that exists.
    vision_match_id: str | None = None
    evidence_saved: int = 0
    finalized: bool = False             # final vision pass DONE (finalizes exactly once)
    final_pass_queued: bool = False     # the post-close vision pass has been queued
    # Portal events: one row per sighting, upserted by (sighting_id, version).
    version: int = 0
    last_material: tuple | None = None  # (status, plate, rule_assisted) last pushed
    last_emit_wall: float | None = None  # None: nothing pushed yet (push immediately)
    pending_emit: dict | None = None    # a debounced result waiting to be pushed
    last_outcome: dict | None = None
    # Distinct evidence frames already saved: [(sim ts, dhash int)]
    saved_frames: list = field(default_factory=list)
    hero_ts: float | None = None        # sim ts of the frame rendered as the hero
    netra: dict | None = None           # latest NETRA shadow assessment (netra_enabled)


@dataclass
class SightingTracker:
    cfg: RfidFeatureConfig = field(default_factory=lambda: DEFAULT_CONFIG)
    watch_nearby: bool = False
    sightings: dict = field(default_factory=dict)     # (key, epc, junction) -> SightingDraft
    # Sightings displaced from their slot by a newer pass of the same tag; kept
    # until their final vision pass has been queued.
    retired: list = field(default_factory=list)
    ignored: dict = field(default_factory=dict)       # reason -> count
    opened: int = 0
    closed_count: int = 0
    hits: int = 0
    reopened: int = 0

    def watchlist_for(self, incident) -> set[str]:
        """The involved tags, plus the crash-zone 'nearby' tags when enabled."""
        watchlist = set(incident.involved_epcs)
        if self.watch_nearby:
            watchlist |= set(getattr(incident, "nearby_epcs", ()) or ())
        return watchlist

    def _ignore(self, reason: str) -> None:
        self.ignored[reason] = self.ignored.get(reason, 0) + 1

    def _eligible(self, incident, read: RfidRead) -> str | None:
        """None when the read may open a sighting, else the ignore reason."""
        if incident is None:
            return IGNORE_NO_INCIDENT

        if read.epc not in self.watchlist_for(incident):
            return IGNORE_NOT_WATCHLISTED

        crash_ts = incident.crash_ts_sim
        if crash_ts is not None and read.event_time <= crash_ts:
            return IGNORE_PRE_CRASH
        if incident.crash_junction and read.junction_id == incident.crash_junction:
            return IGNORE_CRASH_JUNCTION
        # A read long after this crash, or after a newer collision of the same
        # vehicles, belongs to that later event - never to this incident.
        if crash_ts is not None and read.event_time > crash_ts + self.cfg.watch_window_s:
            return IGNORE_WATCH_ENDED
        until = getattr(incident, "watch_until_ts", None)
        if until is not None and read.event_time > until:
            return IGNORE_WATCH_ENDED
        return None

    def ingest(self, incident, reads: list[RfidRead]) -> list[tuple[str, SightingDraft]]:
        """Consume reads for one incident.

        Returns ('opened'|'updated'|'reopened'|'closed', sighting) events.

        At most one sighting per (incident, EPC, junction) is live. Report
        drop-outs are tolerated: a read within ``sighting_merge_s`` of the last
        one extends (or reopens) the same sighting as long as it has not been
        finalized. Only a pass after finalization, or after the merge window,
        is a new sighting.
        """
        if incident is None:
            for _ in reads:
                self._ignore(IGNORE_NO_INCIDENT)
            return []

        events: list[tuple[str, SightingDraft]] = []
        key = incident.match_key()

        for read in sorted(reads, key=lambda item: item.event_time):
            reason = self._eligible(incident, read)
            if reason is not None:
                self._ignore(reason)
                continue

            entry = self._find_mergeable(incident, read)
            if entry is None:
                previous = self.sightings.get(self._slot(key, read.epc, read.junction_id))
                if previous is not None and not previous.closed:
                    self._close(previous)
                    events.append(("closed", previous))
                if previous is not None and not previous.finalized:
                    self.retired.append(previous)
                entry = SightingDraft(
                    incident_key=key,
                    epc=read.epc,
                    plate_norm=self._plate_for(incident, read),
                    junction_id=read.junction_id,
                    reader_id=read.reader_id,
                    first_seen_ts=read.first_seen_ts,
                    last_seen_ts=read.last_seen_ts,
                )
                self.sightings[self._slot(key, read.epc, read.junction_id)] = entry
                self._update(entry, read)
                self.opened += 1
                events.append(("opened", entry))
                continue

            if entry.closed:
                # a drop-out longer than the close timer: same pass, reopen it
                entry.closed = False
                self.reopened += 1
                events.append(("reopened", entry))
            self._update(entry, read)
            events.append(("updated", entry))

        return events

    def _plate_for(self, incident, read: RfidRead) -> str | None:
        for vehicle in incident.vehicles:
            if vehicle.epc and vehicle.epc == read.epc:
                return vehicle.plate_norm
        return read.epc

    @staticmethod
    def _slot(key: str, epc: str, junction_id: str) -> tuple:
        return (key, epc, junction_id)

    def _update(self, entry: SightingDraft, read: RfidRead) -> None:
        entry.report_count += 1
        entry.tag_seen_count += read.count
        entry.last_seen_ts = max(entry.last_seen_ts, read.last_seen_ts)
        entry.first_seen_ts = min(entry.first_seen_ts, read.first_seen_ts)
        if read.peak_rssi is not None:
            entry.peak_rssi_dbm = read.peak_rssi if entry.peak_rssi_dbm is None \
                else max(entry.peak_rssi_dbm, read.peak_rssi)

    def _find_open(self, incident, read: RfidRead) -> SightingDraft | None:
        entry = self.sightings.get(self._slot(incident.match_key(), read.epc, read.junction_id))
        if entry is None or entry.closed:
            return None
        return entry

    def _find_mergeable(self, incident, read: RfidRead) -> SightingDraft | None:
        """The live sighting this read belongs to (open, or closed but not finalized)."""
        entry = self.sightings.get(self._slot(incident.match_key(), read.epc, read.junction_id))
        if entry is None or entry.finalized or entry.final_pass_queued:
            return None
        if read.first_seen_ts - entry.last_seen_ts > self.cfg.sighting_merge_s:
            return None
        if read.last_seen_ts - entry.first_seen_ts > self.cfg.sighting_max_s:
            return None
        return entry

    def _close(self, entry: SightingDraft) -> None:
        entry.closed = True
        self.closed_count += 1

    def tick(self, now_ts: float) -> list[SightingDraft]:
        """Close sightings with no reports for sighting_close_s, or over the cap."""
        closed = []
        for entry in self.sightings.values():
            if entry.closed:
                continue
            quiet = now_ts - entry.last_seen_ts
            if quiet >= self.cfg.sighting_close_s or \
                    (entry.last_seen_ts - entry.first_seen_ts) >= self.cfg.sighting_max_s:
                self._close(entry)
                closed.append(entry)
        return closed

    def pending(self) -> list[SightingDraft]:
        """Every sighting that has not been finalized yet."""
        self.retired = [entry for entry in self.retired if not entry.finalized]
        return [entry for entry in list(self.sightings.values()) + self.retired
                if not entry.finalized]

    def open_sightings(self) -> list[SightingDraft]:
        return [entry for entry in self.sightings.values() if not entry.closed]

    def mark_notified(self, entry: SightingDraft) -> bool:
        """True the first time only - the portal is alerted once per sighting."""
        if entry.notified:
            return False
        entry.notified = True
        self.hits += 1
        return True

    def counters(self) -> dict:
        return {
            "opened": self.opened,
            "closed": self.closed_count,
            "reopened_after_gap": self.reopened,
            "watchlist_hits": self.hits,
            "ignored": dict(self.ignored),
            "open_sightings": len(self.open_sightings()),
        }
