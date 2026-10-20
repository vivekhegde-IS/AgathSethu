"""The RFID -> camera plate cross-verification orchestrator.

One object owns the whole feature. The WebSocket handler calls three cheap
entry points (``on_rfid_message``, ``on_crash_alert``, ``on_camera_frame``);
a background thread calls ``tick()``. Nothing on the RX path touches the DB, the
ANPR model or the decoder - those all happen on the store thread and the vision
executor.

Per sighting the portal sees ONE row: a ``watchlist_rfid_hit`` (version 0,
"awaiting vision"), then ``vision_match_result`` events with a rising
``version`` - only when the status or the best plate materially changes
(debounced) and exactly once more when the sighting is finalized.

Stage logging uses the counters from every stage:
report -> incident -> snapshot -> hit -> ANPR -> status.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import cv2
import numpy as np

from app.services.evidence_render import draw_plate_evidence
from app.services.plate_validation import format_plate
from app.services.rfid.buffer import ReadBuffer
from app.services.rfid.config import (
    JUNCTION_WORLD,
    ROLE_NEARBY,
    SOURCE_LIVE,
    STATUS_AWAITING_VISION,
    STATUS_NO_PLATE_VISIBLE,
    STATUS_PLATE_TOO_SMALL,
    STATUS_RANK,
    STATUS_VISION_CONFIRMED,
    ROLE_FLED,
    RfidFeatureConfig,
)
from app.services.rfid.evidence import (
    KIND_CONTEXT,
    KIND_CRASH,
    KIND_HERO,
    KIND_PLATE,
    KIND_PRIMARY,
    KIND_PRIMARY_PLATE,
    KIND_PRIMARY_RAW,
    KIND_STRIP,
    EvidenceStore,
    crop_box,
    dhash,
    hamming,
    plate_sharpness,
    primary_score,
    score_candidate,
    vehicle_box_around_plate,
)
from app.services.rfid.incidents import IncidentAssembler, RunTracker, parse_alert
from app.services.rfid.normalize import parse_message
from app.services.rfid.plate_rules import GATE_TOO_SMALL, apply_rules
from app.services.rfid.registry import VehicleRegistry, normalize_plate
from app.services.rfid.sightings import SightingTracker
from app.services.rfid.store import Persistence, get_persistence, new_id
from app.services.rfid.vision import (
    FrameReads,
    FrameRing,
    Suspect,
    fuse,
    material_key,
    parse_vehicle_boxes,
    should_stop_early,
)

log = logging.getLogger("rfid")

EVENT_INCIDENT_CREATED = "incident_created"
EVENT_WATCHLIST_HIT = "watchlist_rfid_hit"
EVENT_VISION_RESULT = "vision_match_result"
EVENT_SUSPECT = "suspect_identified"

STATUS_LABEL = {
    "VISION_CONFIRMED": "CONFIRMED",
    "PROBABLE_MATCH": "PROBABLE",
    "NOT_CONFIRMED": "NOT CONFIRMED",
    "NO_PLATE_VISIBLE": "NO PLATE VISIBLE",
    "PLATE_TOO_SMALL": "PLATE TOO SMALL",
}


def _float_or_none(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RfidCrossVerification:
    def __init__(self, cfg: RfidFeatureConfig | None = None,
                 registry: VehicleRegistry | None = None,
                 persistence: Persistence | None = None,
                 broadcaster=None,
                 adapter=None,
                 decoder=None,
                 evidence: EvidenceStore | None = None,
                 executor: ThreadPoolExecutor | None = None,
                 wall_clock=None):
        self.cfg = cfg or RfidFeatureConfig.from_env()
        self.registry = registry or VehicleRegistry.from_seed()
        self.buffer = ReadBuffer(self.cfg.buffer_window_s)
        self.frames = FrameRing(self.cfg.vision_ring_s)
        self.runs = RunTracker(self.cfg)
        self.assembler = IncidentAssembler(self.registry, self.cfg, self.runs)
        self.sightings = SightingTracker(self.cfg, watch_nearby=self.cfg.watch_nearby_default)
        self.persistence = persistence if persistence is not None else get_persistence()
        self.broadcaster = broadcaster
        self.adapter = adapter
        self.evidence = evidence or EvidenceStore(cfg=self.cfg)
        self._decoder = decoder or _decode_jpeg
        self._executor = executor or ThreadPoolExecutor(max_workers=max(1, self.cfg.vision_workers),
                                                        thread_name_prefix="rfid-vision")
        self._owns_executor = executor is None
        self._wall = wall_clock or time.monotonic       # injectable for debounce tests
        self._lock = threading.RLock()
        self._vision_jobs: set = set()
        self._closed_windows: dict = {}       # match key -> snapshot end ts
        self._snapshots_done: set = set()
        self.opened_incidents: dict = {}      # match key -> draft
        self.counters = {
            "rfid_messages": 0, "rfid_stored": 0, "duplicates": 0, "gaps": 0,
            "missing_reports": 0, "alerts_seen": 0, "incidents_created": 0,
            "alerts_merged": 0, "alerts_duplicate": 0, "snapshots_written": 0,
            "sightings_opened": 0, "watchlist_hits": 0, "anpr_runs": 0,
            "vision_records": 0, "vision_events": 0, "vision_events_debounced": 0,
            "camera_frames": 0, "frames_evicted_before_vision": 0, "run_resets": 0,
            "primary_evidence_updates": 0, "anpr_skipped_no_suspect": 0, "errors": 0,
            "netra_assessments": 0, "netra_agree": 0, "netra_disagree": 0, "netra_errors": 0,
        }
        # NETRA shadow association (off by default; imported lazily so the
        # disabled path does not need scipy).
        self._camera_last_ts: dict = {}     # camera_id -> newest frame time (new-run check)
        self.netra = None
        self.netra_live = None
        if self.cfg.netra_enabled:
            from app.services.rfid.netra import NetraShadow
            from app.services.rfid.netra.live import NetraLive
            self.netra = NetraShadow.from_file(self.cfg.netra_calibration)
            # NETRA's own history (all reports + 20 Hz boxes) and online clock offsets
            self.netra_live = NetraLive(self.netra, history_s=self.cfg.netra_history_s,
                                        reads_margin_s=self.cfg.netra_reads_margin_s)
            log.info("[RFID] NETRA shadow association ON (%s%s)",
                     "calibrated" if self.netra.calibrated else "UNCALIBRATED - never confirms",
                     ", per-group thresholds" if self.netra.per_group else "")
        # (incident, suspect, junction) -> {score, frame_ts, candidates}
        self._primary: dict = {}
        # recent escape reports (vehicle_state escape_confirmed), applied to
        # incidents created after them as well
        self._escapes: list = []
        self.last_error: str | None = None
        # Sim clock: the newest event time seen on the dense streams (RFID and
        # camera). Windows and the tick use this, never wall clock.
        self._sim_now = 0.0
        self._last_rx: float | None = None
        self._disconnect_pending = False
        self._unknown_epcs: set = set()
        # health (wall clock, monotonic)
        self._last_rfid_wall: float | None = None
        self._last_frame_wall: float | None = None
        self._last_anpr_wall: float | None = None
        # feed bookkeeping
        self._feed_source: str | None = None
        self._run_started_at: str | None = None
        self._archive_suffix: dict = {}       # rfid run_id -> restart count (archive keys)

    # ================================================================
    # cheap RX entry points
    # ================================================================

    def _note_feed(self, message: dict) -> None:
        source = message.get("feed_source")
        if source:
            self._feed_source = str(source)

    def on_rfid_message(self, message: dict) -> dict:
        """Normalize + buffer one rfid_reading. Never raises, never blocks."""
        try:
            self.counters["rfid_messages"] += 1
            read = parse_message(message)
            if read is None:
                return {"status": "ignored"}
            with self._lock:
                self._touch()
                self._note_feed(message)
                self._last_rfid_wall = self._wall()
                reason = self.buffer.is_new_run(read, self.cfg.run_reset_backjump_s,
                                                self.cfg.reader_restart_tolerance_s)
                if reason:
                    if read.run_id and "restarted" in reason:
                        # same run_id reused by a new start: archive it under a new key
                        self._archive_suffix[read.run_id] = self._archive_suffix.get(read.run_id, 0) + 1
                    self._reset_run(reason, run_id=read.run_id)
                verdict = self.buffer.add(read)
                if verdict == "duplicate":
                    self.counters["duplicates"] += 1
                else:
                    self.counters["rfid_stored"] += 1
                    self._sim_now = max(self._sim_now, read.event_time)
                missing = self.buffer.sequence.last_missing
                if verdict == "gap":
                    self.counters["gaps"] += 1
                    self.counters["missing_reports"] += missing
                archive_run = self._archive_run_id(read.run_id)
            if verdict == "gap":
                log.warning("[RFID] seq gap on %s: %d report(s) missing (reader total %s)",
                            read.reader_id, missing,
                            self.buffer.sequence.gaps.get(read.reader_id))
            if self.netra_live is not None and verdict != "duplicate":
                self.netra_live.ingest_report(read)
            for warning in read.warnings:
                log.warning("[RFID] %s", warning)
            if read.debug_plate:
                conflict = self.registry.check_message_plate(read.epc, read.debug_plate)
                if conflict:
                    log.warning("[RFID] %s", conflict)
            entry, unknown = self.registry.resolve(read.epc)
            if unknown and read.epc not in self._unknown_epcs:
                self._unknown_epcs.add(read.epc)
                log.warning("[RFID] %s (reader %s)", unknown, read.reader_id)
            # Archive the raw report. A re-sent duplicate is NOT re-submitted:
            # UNIQUE(run, reader, seq) would reject it.
            if read.seq is not None and verdict != "duplicate":
                self.persistence.submit("rfid_report", {
                    "run_id": archive_run, "reader_id": read.reader_id, "seq": read.seq,
                    "junction_id": read.junction_id, "epc": read.epc,
                    "plate_norm": entry.plate_norm, "registry_status": entry.status,
                    "first_seen_ts": read.first_seen_ts, "last_seen_ts": read.last_seen_ts,
                    "tag_seen_count": read.count, "rssi_dbm": read.peak_rssi,
                    "schema": read.schema, "sim_vehicle_id": read.debug_vehicle_id,
                })
            return {"status": verdict, "epc": read.epc, "junction_id": read.junction_id}
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)
            return {"status": "error"}

    def _archive_run_id(self, run_id: str | None) -> str | None:
        suffix = self._archive_suffix.get(run_id or "", 0)
        return f"{run_id}#{suffix + 1}" if (run_id and suffix) else run_id

    def on_camera_frame(self, message: dict) -> None:
        """Ring-buffer raw JPEG bytes for a later vision pass. Latest-wins."""
        try:
            image = message.get("image")
            if not image:
                return
            import base64

            payload = base64.b64decode(image) if isinstance(image, str) else bytes(image)
            timestamp = float(message.get("timestamp_sim") or 0.0)
            frame_no = message.get("frame")
            vehicles = parse_vehicle_boxes(message.get("vehicles"))
            with self._lock:
                self._touch()
                self._note_feed(message)
                self._last_frame_wall = self._wall()
                # A new run shows as THIS camera's clock going back. Comparing with
                # the newest time of any source (_sim_now) reset the run whenever the
                # JPEG stream lagged the RFID / box messages by more than 5 s.
                camera_key = str(message.get("camera_id") or message.get("junction_id") or "cam")
                last_cam = self._camera_last_ts.get(camera_key)
                if last_cam is not None and timestamp < last_cam - self.cfg.run_reset_backjump_s:
                    self._reset_run(f"camera {camera_key} time went back {last_cam:.2f}s -> "
                                    f"{timestamp:.2f}s")
                self._camera_last_ts[camera_key] = max(timestamp, self._camera_last_ts.get(camera_key, timestamp))
                self.frames.add(str(message.get("camera_id") or message.get("junction_id") or "cam"),
                                str(message.get("junction_id") or "?"), timestamp, payload,
                                int(frame_no) if isinstance(frame_no, (int, float)) else None,
                                # optional per-vehicle image boxes (association only)
                                vehicles)
                self._sim_now = max(self._sim_now, timestamp)
                self.counters["camera_frames"] += 1
            if self.netra_live is not None and vehicles is not None:
                # fallback box source when the sender has no vehicle_boxes stream
                self.netra_live.ingest_boxes(str(message.get("junction_id") or "?"), timestamp,
                                             vehicles, source="camera_frame")
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)

    def on_vehicle_boxes(self, message: dict) -> None:
        """20 Hz box-only message (member1_handoff/netra_sensor_upgrades.py):
        camera boxes for NETRA only. Nothing else uses it."""
        if self.netra_live is None:
            return
        try:
            vehicles = parse_vehicle_boxes(message.get("vehicles"))
            if vehicles is None:
                return
            self.netra_live.ingest_boxes(str(message.get("junction_id") or "?"),
                                         float(message.get("timestamp_sim") or 0.0),
                                         vehicles, source="vehicle_boxes")
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)

    def on_crash_alert(self, message: dict) -> dict:
        """Parse, assemble, snapshot, notify. Returns a small status dict."""
        try:
            self.counters["alerts_seen"] += 1
            alert = parse_alert(message)
            if alert is None:
                return {"status": "ignored"}

            with self._lock:
                self._touch()
                self._note_feed(message)
                # Alerts only move the clock forward: a retried alert is OLD by
                # design, so it must never look like a new run.
                if alert.timestamp_sim is not None:
                    self._sim_now = max(self._sim_now, alert.timestamp_sim)
                if self.runs.run_id is None and self.runs.pending_reset is None and \
                        self.buffer.run_id:
                    # first alert of this process: join the run the RFID stream is on
                    self.runs.request_new_run("first alert (rfid run_id)", self.buffer.run_id)
                verdict, incident = self.assembler.handle_alert(alert, buffer=self.buffer)
                if verdict == "restart":
                    # Same alert id, a different crash time: the alert counters
                    # restarted. Close the previous run's incidents (the RFID and
                    # camera buffers stay - sim time kept running) and retry.
                    self._reset_run(f"alert id {alert.alert_id} reused at "
                                    f"t={alert.timestamp_sim}", keep_buffers=True)
                    verdict, incident = self.assembler.handle_alert(alert, buffer=self.buffer)
                if verdict in ("duplicate", "restart") or incident is None:
                    self.counters["alerts_duplicate"] += 1
                    return {"status": "duplicate", "alert_id": alert.alert_id}

                if verdict == "merged":
                    self.counters["alerts_merged"] += 1
                else:
                    self.counters["incidents_created"] += 1
                    if incident.incident_id is None:
                        incident.incident_id = incident.stable_id()
                        incident.buffer_epoch = self.buffer.epoch
                        incident.source = self._feed_source or SOURCE_LIVE
                        incident.run_started_at = self._run_started_at or _utc_now_iso()
                        self._run_started_at = incident.run_started_at
                        key = incident.match_key()
                        self._supersede_older(incident)
                        self.opened_incidents[key] = incident
                        self._closed_windows[key] = (incident.crash_ts_sim or 0.0) + \
                            self.cfg.snapshot_after_s
                    self._persist_incident(incident)
                    self._emit(EVENT_INCIDENT_CREATED, self._incident_payload(incident))
                    # Grab the crash-time frames while the ring still has them.
                    self._capture_crash_frames(incident)

                self._persist_alert(incident, alert)
                for vehicle in incident.vehicles:
                    self.persistence.submit("incident_vehicle", {
                        "incident_id": incident.incident_id, "plate_norm": vehicle.plate_norm,
                        "plate_display": vehicle.plate_display, "epc": vehicle.epc,
                        "role": vehicle.role, "sim_vehicle_id": vehicle.sim_vehicle_id,
                    })
                # escape reports that arrived before this alert (or before the
                # alert that added the vehicle) apply now
                early = [(escape, self._apply_escape(incident, escape)) for escape in self._escapes]

            for escape, vehicle in early:
                if vehicle is not None:
                    self._announce_suspect(incident, vehicle, escape)
            # The snapshots are window queries; the visible part is written now
            # and refreshed when the window closes in tick().
            self._write_snapshot(incident, final=False)
            self._log_stage(f"crash_alert {alert.alert_id} ({verdict})")
            return {"status": verdict, "alert_id": alert.alert_id,
                    "incident_id": incident.incident_id,
                    "crash_junction": incident.crash_junction}
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)
            return {"status": "error"}

    def on_vehicle_state(self, message: dict) -> dict:
        """Member 1's post-crash escape detection: a ``vehicle_state`` with
        ``escape_confirmed`` (the crash vehicle kept moving >= 5 km/h and got
        >= 8 m from its crash point). That involved vehicle is the fleeing
        suspect. Nothing here is hard-coded: it is whatever Member 1 reports."""
        try:
            if not message.get("escape_confirmed"):
                return {"status": "ignored"}
            escape = {
                "vehicle_id": str(message.get("vehicle_id") or "") or None,
                "plate_norm": normalize_plate(message.get("plate_number")),
                "epc": (str(message.get("epc")).upper() if message.get("epc") else None),
                "timestamp_sim": _float_or_none(message.get("timestamp_sim")),
                "distance_from_crash_m": _float_or_none(message.get("distance_from_crash_m")),
                "speed_kmh": _float_or_none(message.get("speed_kmh")),
            }
            matched = []
            with self._lock:
                self._touch()
                self._escapes.append(escape)
                del self._escapes[:-50]
                for incident in list(self.opened_incidents.values()):
                    vehicle = self._apply_escape(incident, escape)
                    if vehicle is not None:
                        matched.append((incident, vehicle))
            for incident, vehicle in matched:
                self._announce_suspect(incident, vehicle, escape)
            return {"status": "suspect" if matched else "pending", "vehicle_id": escape["vehicle_id"]}
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)
            return {"status": "error"}

    def _supersede_older(self, incident) -> None:
        """A new collision of the same vehicles: older incidents stop taking
        sightings at its crash time (caller holds the lock)."""
        if incident.crash_ts_sim is None:
            return
        for older in self.opened_incidents.values():
            if older is incident or older.crash_ts_sim is None:
                continue
            if older.crash_ts_sim < incident.crash_ts_sim and                     older.involved_epcs & incident.involved_epcs:
                older.watch_until_ts = min(older.watch_until_ts or incident.crash_ts_sim,
                                           incident.crash_ts_sim)

    def _apply_escape(self, incident, escape: dict):
        """Mark the incident vehicle the escape refers to as fled; returns that
        vehicle, or None (caller holds the lock)."""
        crash = incident.crash_ts_sim
        ts = escape["timestamp_sim"]
        if crash is not None and ts is not None and not (crash - 2.0 <= ts <= crash + 180.0):
            return None
        for vehicle in incident.vehicles:
            same = ((escape["vehicle_id"] and vehicle.sim_vehicle_id == escape["vehicle_id"])
                    or (escape["plate_norm"] and vehicle.plate_norm == escape["plate_norm"])
                    or (escape["epc"] and vehicle.epc == escape["epc"]))
            if same and vehicle.plate_norm not in incident.fled:
                incident.fled[vehicle.plate_norm] = {**escape, "sim_vehicle_id": vehicle.sim_vehicle_id}
                return vehicle
        return None

    def _announce_suspect(self, incident, vehicle, escape: dict) -> None:
        self.persistence.submit("incident_vehicle", {
            "incident_id": incident.incident_id, "plate_norm": vehicle.plate_norm,
            "plate_display": vehicle.plate_display, "epc": vehicle.epc,
            "role": ROLE_FLED, "sim_vehicle_id": vehicle.sim_vehicle_id,
        })
        self._emit(EVENT_SUSPECT, {
            "incident_id": incident.incident_id, "plate_norm": vehicle.plate_norm,
            "epc": vehicle.epc, "suspect_vehicle_id": vehicle.sim_vehicle_id,
            "basis": "escape_confirmed", **{k: escape[k] for k in
                                            ("timestamp_sim", "distance_from_crash_m", "speed_kmh")},
        })
        self._log_stage(f"fleeing suspect {vehicle.sim_vehicle_id} ({vehicle.plate_norm}): "
                        f"{escape['distance_from_crash_m']} m from the crash at "
                        f"{escape['speed_kmh']} km/h")

    def note_disconnect(self) -> None:
        """A connection dropped. It only starts a new run if configured to."""
        with self._lock:
            self._disconnect_pending = True

    def _touch(self) -> None:
        """Wall-clock receive bookkeeping. Caller holds the lock.

        A reconnect alone does NOT start a new run (the alert channel reconnects
        mid-run, and sim time keeps increasing): new runs come from a run_id
        change, a sim-time back-jump, a reader restart or reused alert ids.
        ``run_reset_on_reconnect`` restores the old reconnect-after-gap rule.
        """
        now = self._wall()
        if self._disconnect_pending:
            self._disconnect_pending = False
            if self.cfg.run_reset_on_reconnect and self._last_rx is not None and \
                    now - self._last_rx >= self.cfg.run_reset_gap_s:
                self._reset_run(f"reconnect after a {now - self._last_rx:.0f}s quiet gap")
        self._last_rx = now

    def _reset_run(self, reason: str, run_id: str | None = None,
                   keep_buffers: bool = False) -> None:
        """A new CARLA run: scope every key (and buffer) by run. Caller holds the lock."""
        log.warning("[RFID] new run detected: %s", reason)
        self.counters["run_resets"] += 1
        if not keep_buffers:
            self.buffer.reset_run(reason)
            self.frames.clear()
            self._sim_now = 0.0
            self._camera_last_ts = {}
        self.runs.request_new_run(reason, run_id)
        self._run_started_at = _utc_now_iso()
        if self.netra_live is not None:
            self.netra_live.reset(reason)
        # The previous run's incidents stop watching: their tags now belong to a
        # different simulation. Pending sightings are finalized with what they have.
        for key, incident in list(self.opened_incidents.items()):
            self.assembler.close(incident)
            self._snapshots_done.add(key)
            for sighting in self.sightings.pending():
                if sighting.incident_key != key:
                    continue
                if not sighting.closed:
                    self.sightings._close(sighting)
                    self._persist_sighting(incident, sighting)
                if sighting.sighting_id is not None and not sighting.finalized:
                    self._finalize(incident, sighting, sighting.last_outcome)
        self.opened_incidents.clear()

    # ================================================================
    # background tick
    # ================================================================

    def tick(self, now_ts: float | None = None) -> dict:
        now = self._sim_now if now_ts is None else now_ts
        try:
            with self._lock:
                self.buffer.prune()

                for key, incident in list(self.opened_incidents.items()):
                    # watchlist: only newly arrived reads matter
                    self._consume_sightings(incident)
                    # crash/context frames: re-pick once the +window frames arrived
                    if not incident.crash_frames_final and incident.crash_ts_sim is not None and \
                            now >= incident.crash_ts_sim + self.cfg.vision_crash_frame_window_s:
                        self._capture_crash_frames(incident)
                        incident.crash_frames_final = True

                # close quiet / over-long sightings and store their counts
                for sighting in self.sightings.tick(now):
                    incident = self.opened_incidents.get(sighting.incident_key)
                    if incident is not None and sighting.sighting_id is not None:
                        self._persist_sighting(incident, sighting)

                # Prune the frame ring only AFTER new sightings exist, and never
                # drop frames a pending vision pass still needs.
                self.frames.prune(now, keep_from=self._frames_needed_from())

            # finalize snapshots whose window has closed
            for key, end_ts in list(self._closed_windows.items()):
                if key in self._snapshots_done or now < end_ts:
                    continue
                incident = self.opened_incidents.get(key)
                if incident is not None:
                    self._write_snapshot(incident, final=True)
                    if incident.crash_frame_refs or incident.context_frame_refs:
                        # ANPR on the crash frames runs on the vision executor.
                        self._executor.submit(self._save_crash_frames, incident)
                    self.assembler.close(incident)
                self._snapshots_done.add(key)

            self._schedule_vision(now)
            self._flush_debounced()
            return self.counters_snapshot()
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)
            return self.counters_snapshot()

    # ================================================================
    # sightings + vision
    # ================================================================

    def _consume_sightings(self, incident) -> None:
        """Feed NEW reads to the sighting tracker and alert on new hits."""
        if incident.buffer_epoch != self.buffer.epoch:
            return
        reads = self.buffer.since(incident.read_cursor)
        if not reads:
            return
        incident.read_cursor = max(read.ingest_index for read in reads)
        events = self.sightings.ingest(incident, reads)
        for kind, sighting in events:
            if kind in ("closed", "reopened"):
                if sighting.sighting_id is not None:
                    self._persist_sighting(incident, sighting)
                continue
            if kind != "opened":
                continue
            sighting.sighting_id = new_id()
            self.counters["sightings_opened"] += 1
            self._persist_sighting(incident, sighting)
            if self.sightings.mark_notified(sighting):
                self.counters["watchlist_hits"] += 1
                self._emit(EVENT_WATCHLIST_HIT, {
                    **self._sighting_header(incident, sighting),
                    "version": 0, "final": False, "status": STATUS_AWAITING_VISION,
                })
                self._log_stage(f"watchlist hit {sighting.epc} at {sighting.junction_id}")

    def _sighting_header(self, incident, sighting) -> dict:
        return {
            "incident_id": incident.incident_id,
            "sighting_id": sighting.sighting_id,
            "epc": sighting.epc,
            "plate_norm": sighting.plate_norm,
            "rfid_plate": self._rfid_plate_for(incident, sighting),
            "junction_id": sighting.junction_id,
            "reader_id": sighting.reader_id,
            "first_seen_ts": sighting.first_seen_ts,
            "last_seen_ts": sighting.last_seen_ts,
            "report_count": sighting.report_count,
            "peak_rssi_dbm": sighting.peak_rssi_dbm,
        }

    def _schedule_vision(self, now_ts: float) -> None:
        """Queue vision passes and finalize closed sightings (exactly once each).

        Open sightings are re-checked (rate-limited) while the status can still
        improve. A closed sighting gets ONE final pass after its trailing frame
        window, and is finalized when that pass has processed its frames.
        """
        with self._lock:
            candidates = [(self.opened_incidents.get(sighting.incident_key), sighting)
                          for sighting in self.sightings.pending()]
        for incident, sighting in candidates:
            if incident is None or sighting.sighting_id is None or sighting.finalized:
                continue
            job_key = (sighting.incident_key, sighting.sighting_id)
            if job_key in self._vision_jobs:
                continue
            final = False
            if sighting.closed:
                if sighting.final_pass_queued:
                    continue
                if now_ts < sighting.last_seen_ts + self.cfg.vision_window_after_s:
                    continue
                sighting.final_pass_queued = True
                final = True
                if self.adapter is None or sighting.best_status == STATUS_VISION_CONFIRMED:
                    # nothing left to improve: finalize with the best result so far
                    self._finalize(incident, sighting, sighting.last_outcome)
                    continue
            else:
                if self.adapter is None or sighting.best_status == STATUS_VISION_CONFIRMED:
                    continue
                if sighting.last_attempt_ts is not None and \
                        now_ts - sighting.last_attempt_ts < self.cfg.vision_retry_interval_s:
                    continue
            with self._lock:
                refs = self._frames_for_sighting(sighting)
            if not refs:
                if final:
                    log.warning("[RFID] no camera frames at %s for %s in [%.2f, %.2f]",
                                sighting.junction_id, sighting.epc,
                                sighting.first_seen_ts - self.cfg.vision_window_before_s,
                                sighting.last_seen_ts + self.cfg.vision_window_after_s)
                    self._finalize(incident, sighting, sighting.last_outcome)
                continue
            self._vision_jobs.add(job_key)
            sighting.last_attempt_ts = now_ts
            sighting.vision_attempts += 1
            self._executor.submit(self._vision_job, incident, sighting, job_key, refs, final)

    def _frames_needed_from(self) -> float | None:
        """Oldest sim time a pending vision pass or crash-frame pick still needs."""
        if self.adapter is None:
            return None             # no vision will ever run: plain ring window
        needed = [sighting.first_seen_ts - self.cfg.vision_window_before_s
                  for sighting in self.sightings.pending()
                  if sighting.best_status != STATUS_VISION_CONFIRMED
                  and sighting.incident_key in self.opened_incidents]
        needed += [incident.crash_ts_sim - self.cfg.vision_crash_frame_window_s
                   for incident in self.opened_incidents.values()
                   if not incident.crash_frames_final and incident.crash_ts_sim is not None]
        return min(needed) if needed else None

    def _frames_for_sighting(self, sighting) -> list:
        """Up to vision_frames_max frames spread over the widened camera window.

        The camera sits ~25-35 m before the junction centre, the RFID read zone
        is ~10 m around the reader: the best plate frames can come BEFORE the
        first RFID read, hence the wider before-window.
        """
        start = sighting.first_seen_ts - self.cfg.vision_window_before_s
        end = sighting.last_seen_ts + self.cfg.vision_window_after_s
        refs = []
        for camera_id in self.frames.cameras_for_junction(sighting.junction_id):
            oldest = self.frames.oldest_ts(camera_id)
            if oldest is not None and oldest > start + 0.5 and self.frames.dropped:
                # frames this window needed were evicted before the pass ran
                self.counters["frames_evicted_before_vision"] += 1
                log.warning("[RFID] %s: frames before %.2fs were evicted before the vision pass "
                            "(window starts %.2fs)", camera_id, oldest, start)
            refs.extend(self.frames.pick(camera_id, start, end, self.cfg.vision_frames_max))
        if refs:
            nearest = min(abs(ref.timestamp_sim - sighting.first_seen_ts) for ref in refs)
            log.debug("[RFID] %s alignment: nearest frame %.2fs from first RFID read",
                      sighting.junction_id, nearest)
            if nearest > 2.0:
                log.warning("[RFID] %s: RFID/camera event-time gap %.2fs for %s (clock skew?)",
                            sighting.junction_id, nearest, sighting.epc)
        return refs

    def _vision_job(self, incident, sighting, job_key, refs, final: bool = False) -> None:
        try:
            self._run_vision(incident, sighting, refs, final)
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)
            if final and not sighting.finalized:
                self._finalize(incident, sighting, sighting.last_outcome)
        finally:
            with self._lock:
                self._vision_jobs.discard(job_key)

    def read_frame(self, frame) -> list:
        """ANPR (blind) + plate rules for one decoded frame -> [RuleRead]."""
        reads = self.adapter.detect_and_read(frame, two_line_aspect=self.cfg.ocr_two_line_aspect)
        self._last_anpr_wall = self._wall()
        rules = []
        for read in reads:
            box = getattr(read, "box", None) if not isinstance(read, dict) else read.get("box")
            sharp = 0.0
            if box is not None:
                crop = crop_box(frame, box, pad=0)
                sharp = plate_sharpness(crop) if crop.size else 0.0
            rules.append(apply_rules(read, self.cfg, sharpness=sharp))
        return rules

    def _netra_shadow(self, sighting, suspect: Suspect) -> None:
        """Shadow mode: NETRA's own answer to "which visible vehicle carries
        this EPC", from RFID reads + camera boxes only. Stored on the sighting
        and shown in the payload; it never changes the decision."""
        if self.netra is None:
            return
        try:
            if self.netra_live is not None and self.netra_live.has_data(sighting.junction_id):
                result = self.netra_live.assess(sighting.epc, sighting.junction_id,
                                                sighting.first_seen_ts, sighting.last_seen_ts)
            else:
                start = sighting.first_seen_ts - self.cfg.vision_window_before_s
                end = sighting.last_seen_ts + self.cfg.vision_window_after_s
                margin = self.cfg.netra_reads_margin_s
                with self._lock:
                    reports = list(self.buffer.window(sighting.junction_id, start - margin, end + margin))
                    frames = [ref for camera_id in self.frames.cameras_for_junction(sighting.junction_id)
                              for ref in self.frames.window(camera_id, start, end)]
                result = self.netra.assess(sighting.epc, sighting.junction_id,
                                           sighting.first_seen_ts, sighting.last_seen_ts,
                                           reports, frames)
            from app.services.rfid.netra.adapter import track_vehicle
            proposed = track_vehicle(result.get("proposed_track"))
            result["registry_vehicle_id"] = suspect.vehicle_id
            result["agrees"] = (None if not suspect.vehicle_id or proposed is None
                                else proposed == str(suspect.vehicle_id))
            sighting.netra = result
            self.counters["netra_assessments"] += 1
            log.debug("[NETRA] %s at %s: %s track=%s conf=%s registry=%s",
                      sighting.epc, sighting.junction_id, result["status"], proposed,
                      result.get("confidence"), suspect.vehicle_id)
        except Exception as exc:                       # pragma: no cover - defensive
            self.counters["netra_errors"] += 1
            log.warning("[NETRA] shadow assessment failed for %s: %s", sighting.epc, exc)

    def _run_vision(self, incident, sighting, refs, final: bool = False) -> None:
        rfid_plate = self._rfid_plate_for(incident, sighting)
        suspect = self._suspect_for(incident, sighting)
        self._netra_shadow(sighting, suspect)
        frame_reads: list[FrameReads] = []
        for ref in refs:
            if ref.vehicles is not None and suspect.vehicle_id and                     ref.vehicle_box(suspect.vehicle_id) is None:
                # the frame's vehicle metadata says the suspect is not in view:
                # no ANPR on it (other vehicles' plates are never needed)
                frame_reads.append(FrameReads(ref, []))
                self.counters["anpr_skipped_no_suspect"] += 1
                continue
            frame = self._decoder(ref.jpeg)
            if frame is None:
                continue
            frame_reads.append(FrameReads(ref, self.read_frame(frame)))
            self.counters["anpr_runs"] += 1
            if not final and should_stop_early(
                    fuse(frame_reads, rfid_plate, self.cfg, sighting.first_seen_ts,
                         suspect=suspect), self.cfg):
                break
        if not frame_reads:
            if final:
                self._finalize(incident, sighting, sighting.last_outcome)
            return
        outcome = fuse(frame_reads, rfid_plate, self.cfg, reference_ts=sighting.first_seen_ts,
                       suspect=suspect)
        if final:
            self._finalize(incident, sighting, self._better(outcome, sighting.last_outcome))
        else:
            self._handle_outcome(incident, sighting, outcome)

    @staticmethod
    def _better(new: dict | None, old: dict | None) -> dict | None:
        """The stronger of two results (never downgrade a sighting)."""
        if old is None:
            return new
        if new is None:
            return old
        def key(result):
            return (STATUS_RANK.get(result["status"], -1), not result.get("rule_assisted"),
                    result.get("cluster_frames", 0), result.get("anpr_confidence") or 0.0)
        return new if key(new) >= key(old) else old

    def _handle_outcome(self, incident, sighting, outcome: dict) -> None:
        """Store/push a result only when it MATERIALLY changes (debounced)."""
        best = self._better(outcome, sighting.last_outcome)
        sighting.last_outcome = best
        sighting.best_status = best["status"]
        sighting.best_confidence = best.get("anpr_confidence") or 0.0
        if material_key(best) == sighting.last_material:
            return
        sighting.last_material = material_key(best)
        sighting.version += 1
        match_id = self._persist_vision(incident, sighting, best, final=False)
        self.counters["vision_records"] += 1
        self._save_evidence(incident, sighting, best, match_id)
        self._push_result(incident, sighting, best, final=False)
        self._log_stage(f"vision {sighting.epc} at {sighting.junction_id}: {best['status']} "
                        f"(v{sighting.version})")

    def _finalize(self, incident, sighting, outcome: dict | None) -> None:
        """Exactly once per sighting: final DB row, evidence and portal event."""
        if sighting.finalized:
            return
        sighting.finalized = True
        sighting.final_pass_queued = True
        if outcome is None:
            outcome = fuse([], self._rfid_plate_for(incident, sighting), self.cfg,
                           reference_ts=sighting.first_seen_ts,
                           suspect=self._suspect_for(incident, sighting))
        sighting.last_outcome = outcome
        sighting.best_status = outcome["status"]
        sighting.version += 1
        sighting.last_material = material_key(outcome)
        if sighting.netra is not None and sighting.netra.get("agrees") is not None:
            self.counters["netra_agree" if sighting.netra["agrees"] else "netra_disagree"] += 1
        match_id = self._persist_vision(incident, sighting, outcome, final=True)
        self.counters["vision_records"] += 1
        self._save_evidence(incident, sighting, outcome, match_id)
        self._persist_sighting(incident, sighting)
        self._push_result(incident, sighting, outcome, final=True)
        self._log_stage(f"vision {sighting.epc} at {sighting.junction_id}: {outcome['status']} "
                        f"(final v{sighting.version})")

    def _result_payload(self, incident, sighting, outcome: dict, final: bool) -> dict:
        return {
            **self._sighting_header(incident, sighting),
            "version": sighting.version, "final": final,
            "status": outcome["status"],
            "rule_assisted": outcome.get("rule_assisted", False),
            "match_reason": outcome.get("match_reason"),
            "anpr_plate": outcome.get("anpr_plate"),
            "anpr_state_name": outcome.get("anpr_state_name"),
            "anpr_confidence": outcome.get("anpr_confidence"),
            "confidence": outcome.get("anpr_confidence"),
            "edit_distance": outcome.get("edit_distance"),
            "diff": outcome.get("diff", []),
            "frames_used": outcome.get("frames_used", 0),
            "cluster_frames": outcome.get("cluster_frames", 0),
            "plates_seen": outcome.get("plates_seen", []),
            "all_plates_seen": outcome.get("plates_seen", []),
            "other_vehicles": outcome.get("other_vehicles", []),
            "rejected_count": len(outcome.get("rejected_reads", [])),
            "max_plate_px": outcome.get("max_plate_px"),
            "camera_id": outcome.get("camera_id"),
            "suspect_vehicle_id": self._suspect_for(incident, sighting).vehicle_id,
            "association": outcome.get("association"),
            "netra": sighting.netra,
        }

    def _push_result(self, incident, sighting, outcome: dict, final: bool) -> None:
        payload = self._result_payload(incident, sighting, outcome, final)
        now = self._wall()
        if final or sighting.last_emit_wall is None or \
                now - sighting.last_emit_wall >= self.cfg.emit_debounce_s:
            sighting.pending_emit = None
            sighting.last_emit_wall = now
            self.counters["vision_events"] += 1
            self._emit(EVENT_VISION_RESULT, payload)
        else:
            sighting.pending_emit = payload      # newest wins; flushed by tick
            self.counters["vision_events_debounced"] += 1

    def _flush_debounced(self) -> None:
        now = self._wall()
        for sighting in list(self.sightings.sightings.values()) + list(self.sightings.retired):
            if sighting.pending_emit and (sighting.last_emit_wall is None or
                                          now - sighting.last_emit_wall >= self.cfg.emit_debounce_s):
                payload, sighting.pending_emit = sighting.pending_emit, None
                sighting.last_emit_wall = now
                self.counters["vision_events"] += 1
                self._emit(EVENT_VISION_RESULT, payload)

    def _suspect_for(self, incident, sighting) -> Suspect:
        """The sighted vehicle: the EPC the reader saw, its registry plate and
        its CARLA actor id. Comes from the crash_alert's involved vehicles
        (plate -> registry -> EPC) and the registry, never from an ANPR read."""
        vehicle_id = None
        for vehicle in incident.vehicles:
            if vehicle.epc and vehicle.epc == sighting.epc:
                vehicle_id = vehicle.sim_vehicle_id
                break
        if vehicle_id is None:
            entry = self.registry.lookup_epc(sighting.epc)
            vehicle_id = entry.sim_vehicle_id if entry is not None else None
        return Suspect(epc=sighting.epc, plate_norm=self._rfid_plate_for(incident, sighting),
                       vehicle_id=vehicle_id)

    @staticmethod
    def _rfid_plate_for(incident, sighting) -> str | None:
        """The registry plate behind the sighted EPC (never an ANPR read)."""
        for vehicle in incident.vehicles:
            if vehicle.epc and vehicle.epc == sighting.epc:
                return vehicle.plate_norm
        return sighting.plate_norm

    # ================================================================
    # persistence helpers
    # ================================================================

    def _persist_incident(self, incident) -> None:
        self.persistence.submit("incident", {
            "id": incident.incident_id,
            "dedupe_key": incident.dedupe_key(),
            "run_id": incident.run_id,
            "crash_ts_sim": incident.crash_ts_sim,
            "crash_frame": incident.crash_frame,
            "crash_junction": incident.crash_junction,
            "world_x": incident.world_x, "world_y": incident.world_y, "world_z": incident.world_z,
            "gps_lat": incident.gps_lat, "gps_lon": incident.gps_lon,
            "description": "; ".join(incident.warnings) or None,
            "source": incident.source, "run_started_at": incident.run_started_at,
        })

    def _persist_alert(self, incident, alert) -> None:
        self.persistence.submit("incident_alert", {
            "incident_id": incident.incident_id, "alert_id": alert.alert_id,
            "run_id": incident.run_id, "source": alert.source, "status": alert.status,
            "timestamp_sim": alert.timestamp_sim, "frame": alert.frame, "raw": alert.raw,
        })

    def _junctions(self) -> list[str]:
        return sorted(set(JUNCTION_WORLD) | set(self.buffer.junctions))

    def _write_snapshot(self, incident, final: bool) -> None:
        """RFID snapshot of EVERY junction for [t_crash - before, t_crash + after].

        The crash junction is the CRASH ZONE; the others are context snapshots.
        Watchlist (involved) tags are marked in every zone.
        """
        if incident.incident_id is None or incident.crash_ts_sim is None:
            return
        start = incident.crash_ts_sim - self.cfg.snapshot_before_s
        end = incident.crash_ts_sim + self.cfg.snapshot_after_s
        written = {}
        for junction in self._junctions():
            with self._lock:
                rows = self.buffer.coalesce(self.buffer.window(junction, start, end), self.registry,
                                           incident.involved_epcs, incident.involved_plates)
                if junction == incident.crash_junction:
                    # "also watch nearby" (off by default) watches these too
                    incident.nearby_epcs = {row.epc for row in rows if row.role == ROLE_NEARBY}
            zone = "crash" if junction == incident.crash_junction else "context"
            for row in rows:
                self.persistence.submit("crash_zone", {
                    "incident_id": incident.incident_id, "zone": zone, **row.as_dict(),
                })
                self.counters["snapshots_written"] += 1
            written[junction] = len(rows)
        if final:
            self._log_stage(f"snapshots (crash zone {incident.crash_junction}): {written}")

    def _capture_crash_frames(self, incident) -> None:
        """Pick crash-time frames NOW, while they are in the ring.

        Crash junction: up to 2 frames within +-1 s of t_crash. Every other
        junction: the single nearest frame (context snapshot).
        """
        if incident.crash_ts_sim is None:
            return
        window = self.cfg.vision_crash_frame_window_s
        refs = []
        if incident.crash_junction:
            for camera_id in self.frames.cameras_for_junction(incident.crash_junction):
                refs.extend(self.frames.pick(camera_id, incident.crash_ts_sim - window,
                                             incident.crash_ts_sim + window, 2))
        if refs or not incident.crash_frame_refs:
            incident.crash_frame_refs = refs
        for junction in JUNCTION_WORLD:
            if junction == incident.crash_junction:
                continue
            nearest = self.frames.nearest(junction, incident.crash_ts_sim, max_dt=2.0)
            if nearest is not None:
                incident.context_frame_refs[junction] = nearest

    def _save_crash_frames(self, incident) -> None:
        """Crash-junction frames around t_crash (with the plates ANPR reads there)
        and one context frame per other junction."""
        if incident.crash_frame_saved or incident.crash_ts_sim is None:
            return
        incident.crash_frame_saved = True
        saved = 0
        for ref in incident.crash_frame_refs:
            plates = []
            if self.adapter is not None:
                frame = self._decoder(ref.jpeg)
                if frame is not None:
                    try:
                        plates = [rule.corrected for rule in self.read_frame(frame) if rule.valid]
                    except Exception as exc:           # never lose the frame itself
                        self._note_error(exc)
            self._save_scene_frame(incident, incident.crash_junction, ref, plates, KIND_CRASH,
                                   "CRASH ZONE")
            saved += 1
        for junction, ref in incident.context_frame_refs.items():
            self._save_scene_frame(incident, junction, ref, [], KIND_CONTEXT, "CONTEXT")
            saved += 1
        if saved:
            self._log_stage(f"crash/context frames saved: {saved}")

    def _save_scene_frame(self, incident, junction, ref, plates, kind, label) -> None:
        frame = self._decoder(ref.jpeg)
        if frame is None:
            return
        image = frame.copy()
        draw_plate_evidence(
            image, vehicle_box=None, vehicle_label=None, plate_box=None, plate_crop=None,
            plate_label=(format_plate(plates[0]) if plates else None) if kind == KIND_CRASH else label,
            second_line=(f"{label} | plates read: {', '.join(plates)}" if plates else label),
            footer=f"{junction} | frame {ref.frame_no if ref.frame_no is not None else '?'} | "
                   f"t={ref.timestamp_sim:.2f}s")
        saved = self.evidence.save_jpeg(incident.incident_id, junction, kind,
                                        f"{kind}_{int(ref.timestamp_sim * 1000)}", image)
        if saved is not None:
            self.persistence.submit("evidence", {
                "incident_id": incident.incident_id, "vision_match_id": None,
                "owner": "incident", "kind": kind, "path": saved.path,
                "sha256": saved.sha256, "width": saved.width, "height": saved.height,
                "score": 0.0, "frame_ts": ref.timestamp_sim, "junction_id": junction,
            })

    def _persist_sighting(self, incident, sighting) -> None:
        self.persistence.submit("sighting", {
            "id": sighting.sighting_id, "incident_id": incident.incident_id,
            "epc": sighting.epc, "plate_norm": sighting.plate_norm,
            "junction_id": sighting.junction_id, "reader_id": sighting.reader_id,
            "first_seen_ts": sighting.first_seen_ts, "last_seen_ts": sighting.last_seen_ts,
            "report_count": sighting.report_count, "tag_seen_count": sighting.tag_seen_count,
            "peak_rssi_dbm": sighting.peak_rssi_dbm, "closed": sighting.closed,
            "finalized": sighting.finalized, "version": sighting.version,
        })

    def _persist_vision(self, incident, sighting, outcome: dict, final: bool) -> str:
        """Upsert the ONE vision_match row of this sighting; return its id."""
        if sighting.vision_match_id is None:
            sighting.vision_match_id = new_id()
        best_frame = outcome.get("best_frame")
        self.persistence.submit("vision_match", {
            "id": sighting.vision_match_id, "sighting_id": sighting.sighting_id,
            "status": outcome["status"], "rfid_plate": self._rfid_plate_for(incident, sighting),
            "anpr_plate": outcome.get("anpr_plate"),
            "anpr_confidence": outcome.get("anpr_confidence"),
            "edit_distance": outcome.get("edit_distance"), "camera_id": outcome.get("camera_id"),
            "best_frame_ts": best_frame.timestamp_sim if best_frame else None,
            "time_delta_s": outcome.get("time_delta_s"), "frames_used": outcome.get("frames_used"),
            "all_plates_seen": outcome.get("plates_seen", []),
            "anpr_model": self._anpr_model_label(),
            "rule_assisted": bool(outcome.get("rule_assisted")),
            "match_reason": outcome.get("match_reason"),
            "diff": outcome.get("diff", []),
            "other_vehicles": outcome.get("other_vehicles", []),
            "rejected_reads": outcome.get("rejected_reads", []),
            "per_frame": outcome.get("per_frame", []),
            "max_plate_px": outcome.get("max_plate_px"),
            "cluster_frames": outcome.get("cluster_frames", 0),
            "anpr_state_code": outcome.get("anpr_state_code"),
            "version": sighting.version, "finalized": final,
        })
        return sighting.vision_match_id

    def _anpr_model_label(self) -> str | None:
        """Model file + backend + every threshold that shaped the verdict."""
        if self.adapter is None:
            return None
        try:
            status = self.adapter.status()
        except Exception:                              # pragma: no cover - defensive
            return None
        config = status.get("config") or {}
        name = str(config.get("model_path") or "anpr").replace("\\", "/").rsplit("/", 1)[-1]
        label = (f"{name} [{status.get('backend') or 'unloaded'}] "
                 f"mode={config.get('mode')} det_conf={config.get('det_conf')} "
                 f"iou={config.get('iou')} imgsz={status.get('imgsz') or config.get('imgsz')} | "
                 f"confirm conf>={self.cfg.vision_conf_threshold} "
                 f"frames>={self.cfg.vision_frames_to_confirm} "
                 f"single>={self.cfg.vision_single_frame_conf} "
                 f"probable_ed<={self.cfg.vision_probable_edit_distance} "
                 f"rule_assisted={'promote' if self.cfg.promote_rule_assisted else 'probable'} "
                 f"min_plate_px={self.cfg.gate_min_plate_px:g}")
        return label[:255]

    # ---------------- evidence ----------------

    def _distinct(self, sighting, ts: float, image_hash: int) -> bool:
        return all(abs(ts - saved_ts) >= self.cfg.evidence_min_gap_s
                   and hamming(image_hash, saved_hash) >= self.cfg.evidence_min_hash_distance
                   for saved_ts, saved_hash in sighting.saved_frames)

    def _save_evidence(self, incident, sighting, outcome: dict, match_id: str) -> None:
        """Hero card image (when the best frame changes) + distinct strip frames.

        File names carry the frame time, so nothing is ever overwritten; a frame
        too similar to one already saved (time gap / perceptual hash) is skipped.
        """
        members = list(outcome.get("best_members") or [])
        best = outcome.get("best_frame"), outcome.get("best_read")
        if best[0] is None and outcome.get("largest_unread"):
            # nothing legible: show the largest detection (e.g. a too-small plate)
            best = outcome["largest_unread"]
        decoded = {}

        def decode(ref):
            if id(ref) not in decoded:
                decoded[id(ref)] = self._decoder(ref.jpeg)
            return decoded[id(ref)]

        rfid_plate = self._rfid_plate_for(incident, sighting)
        status = outcome["status"]

        # ---- hero (large annotated card image)
        if best[0] is not None and sighting.hero_ts != best[0].timestamp_sim:
            frame = decode(best[0])
            if frame is not None:
                sighting.hero_ts = best[0].timestamp_sim
                self._save_hero(incident, sighting, outcome, best[0], best[1], frame,
                                rfid_plate, status, match_id)

        # ---- strip: up to N distinct best frames of the matched/best vehicle
        for ref, rule in members:
            if len(sighting.saved_frames) >= self.cfg.evidence_max_frames:
                break
            frame = decode(ref)
            if frame is None:
                continue
            region = crop_box(frame, vehicle_box_around_plate(rule.box, frame.shape), pad=0)
            image_hash = dhash(region)
            if not self._distinct(sighting, ref.timestamp_sim, image_hash):
                continue
            sighting.saved_frames.append((ref.timestamp_sim, image_hash))
            image = frame.copy()
            draw_plate_evidence(
                image, vehicle_box=vehicle_box_around_plate(rule.box, frame.shape),
                vehicle_label=None, plate_box=rule.box, plate_crop=None,
                plate_label=format_plate(rule.corrected) if rule.valid else None,
                second_line=f"{rule.width_px:.0f}px plate | OCR {rule.mean_conf:.2f}",
                footer=self._footer(sighting, ref))
            saved = self.evidence.save_jpeg(incident.incident_id, sighting.junction_id, KIND_STRIP,
                                            f"{sighting.sighting_id[:8]}_strip_"
                                            f"{int(ref.timestamp_sim * 1000)}", image,
                                            score=score_candidate(rule.mean_conf,
                                                                  rule.width_px * rule.height_px,
                                                                  rule.sharpness))
            self._record_evidence(incident, sighting, saved, KIND_STRIP, match_id, ref.timestamp_sim)

        # ---- primary: ONE best frame per (incident, suspect, junction)
        self._update_primary(incident, sighting, outcome, match_id, decode)

    # ---------------- primary evidence: one best frame per junction ----------------

    def _primary_key(self, incident, sighting) -> tuple:
        suspect = self._suspect_for(incident, sighting)
        return (incident.incident_id, suspect.vehicle_id or sighting.epc, sighting.junction_id)

    def _update_primary(self, incident, sighting, outcome: dict, match_id: str, decode) -> None:
        """Score every suspect candidate of this pass. Only when the best one
        beats the junction's current primary is a new primary written, so the
        junction keeps ONE primary image that only ever gets better."""
        candidates = list(outcome.get("best_members") or [])
        if not candidates and outcome.get("largest_unread"):
            # the suspect is in view but its plate is unreadable: still evidence
            candidates = [outcome["largest_unread"]]
        if not candidates:
            return
        strengths = outcome.get("association_strength") or {}
        key = self._primary_key(incident, sighting)
        state = self._primary.setdefault(key, {"score": -1.0, "frame_ts": None, "candidates": set()})
        best = None
        for ref, rule in candidates:
            state["candidates"].add((round(ref.timestamp_sim, 3),
                                     tuple(int(round(v)) for v in rule.box)))
            frame = decode(ref)
            if frame is None:
                continue
            score, parts = primary_score(rule, crop_box(frame, rule.box, pad=0),
                                         strengths.get((id(ref), id(rule))), self.cfg)
            if best is None or score > best[0]:
                best = (score, parts, ref, rule, frame)
        if best is None or best[0] <= state["score"] + 1e-9:
            return
        score, parts, ref, rule, frame = best
        state.update(score=score, frame_ts=ref.timestamp_sim)
        self._save_primary(incident, sighting, match_id, ref, rule, frame, score)
        self.counters["primary_evidence_updates"] += 1
        self._log_stage(f"primary evidence {sighting.junction_id} t={ref.timestamp_sim:.2f}s "
                        f"score {score:.3f} {parts} ({len(state['candidates'])} candidates)")

    def _save_primary(self, incident, sighting, match_id, ref, rule, frame, score) -> None:
        suspect = self._suspect_for(incident, sighting)
        box = ref.vehicle_box(suspect.vehicle_id)
        vehicle_box = box["bbox"] if box else vehicle_box_around_plate(rule.box, frame.shape)
        crop = crop_box(frame, rule.box, pad=3)
        read = format_plate(rule.corrected) if rule.valid else None
        image = frame.copy()
        draw_plate_evidence(
            image,
            vehicle_box=vehicle_box,
            vehicle_label=f"SUSPECT {suspect.vehicle_id or ''} | RFID ...{sighting.epc[-6:]}",
            plate_box=rule.box, plate_crop=crop,
            plate_label=read,
            second_line=(f"read {read or rule.raw or 'nothing'} | OCR {rule.mean_conf:.2f} | "
                         f"{rule.width_px:.0f}px plate"),
            extra_lines=[f"best of this junction | score {score:.2f}"],
            footer=self._footer(sighting, ref))
        stem = (f"{sighting.junction_id}_{suspect.vehicle_id or sighting.epc[-6:]}_primary_"
                f"{int(ref.timestamp_sim * 1000)}")
        for kind, picture in ((KIND_PRIMARY, image), (KIND_PRIMARY_RAW, frame),
                              (KIND_PRIMARY_PLATE, crop)):
            if picture is None or not picture.size:
                continue
            saved = self.evidence.save_jpeg(incident.incident_id, sighting.junction_id, kind,
                                            f"{stem}_{kind}", picture, score=score)
            self._record_evidence(incident, sighting, saved, kind, match_id, ref.timestamp_sim)

    def _footer(self, sighting, ref) -> str:
        frame_no = ref.frame_no if ref.frame_no is not None else "?"
        return f"{sighting.junction_id} | frame {frame_no} | t={ref.timestamp_sim:.2f}s"

    def _save_hero(self, incident, sighting, outcome, ref, rule, frame, rfid_plate, status,
                   match_id) -> None:
        image = frame.copy()
        crop = crop_box(frame, rule.box, pad=3)
        anpr = outcome.get("anpr_plate")
        state = outcome.get("anpr_state_name") or "state unknown"
        if anpr is None and status == STATUS_PLATE_TOO_SMALL:
            state = f"plate {rule.width_px:.0f}px wide (< {self.cfg.gate_min_plate_px:g}px)"
        elif anpr is None:
            state = "no legible plate"
        verdict = STATUS_LABEL.get(status, status)
        if outcome.get("rule_assisted"):
            verdict += " (rule-assisted)"
        draw_plate_evidence(
            image,
            vehicle_box=vehicle_box_around_plate(rule.box, frame.shape),
            vehicle_label=f"RFID ...{sighting.epc[-6:]}",
            plate_box=rule.box, plate_crop=crop,
            plate_label=format_plate(anpr) if anpr else None,
            second_line=state,
            extra_lines=[f"RFID {format_plate(rfid_plate) or '-'} | {verdict}"],
            footer=self._footer(sighting, ref))
        stamp = int(ref.timestamp_sim * 1000)
        saved = self.evidence.save_jpeg(incident.incident_id, sighting.junction_id, KIND_HERO,
                                        f"{sighting.sighting_id[:8]}_hero_{stamp}", image,
                                        score=score_candidate(rule.mean_conf,
                                                              rule.width_px * rule.height_px,
                                                              rule.sharpness))
        self._record_evidence(incident, sighting, saved, KIND_HERO, match_id, ref.timestamp_sim)
        if crop.size:
            saved_crop = self.evidence.save_jpeg(incident.incident_id, sighting.junction_id,
                                                 KIND_PLATE, f"{sighting.sighting_id[:8]}_plate_{stamp}",
                                                 crop)
            self._record_evidence(incident, sighting, saved_crop, KIND_PLATE, match_id,
                                  ref.timestamp_sim)

    def _record_evidence(self, incident, sighting, saved, kind, match_id, frame_ts) -> None:
        if saved is None:
            return
        self.persistence.submit("evidence", {
            "incident_id": incident.incident_id, "vision_match_id": match_id,
            "owner": "vision_match", "kind": kind, "path": saved.path,
            "sha256": saved.sha256, "width": saved.width, "height": saved.height,
            "score": saved.score, "frame_ts": frame_ts, "junction_id": sighting.junction_id,
        })

    # ================================================================
    # portal / logging
    # ================================================================

    def _incident_payload(self, incident) -> dict:
        return {
            "incident_id": incident.incident_id,
            "run_id": incident.run_id,
            "source": incident.source,
            "crash_ts_sim": incident.crash_ts_sim,
            "crash_frame": incident.crash_frame,
            "crash_junction": incident.crash_junction,
            "plates": sorted(incident.involved_plates),
            "epcs": sorted(incident.involved_epcs),
            "alert_ids": incident.alert_ids,
            "warnings": list(incident.warnings),
            "fled": [{"plate_norm": plate, **info} for plate, info in incident.fled.items()],
        }

    def _emit(self, event_type: str, payload: dict) -> None:
        message = {"type": event_type, **payload}
        if self.broadcaster is None:
            return
        try:
            self.broadcaster(message)
        except Exception as exc:                       # pragma: no cover - defensive
            self._note_error(exc)

    def _log_stage(self, detail: str) -> None:
        c = self.counters
        log.info("[RFID] %s | reports=%d dup=%d gaps=%d missing=%d -> incidents=%d merged=%d "
                 "-> snapshot_rows=%d -> sightings=%d hits=%d -> anpr_frames=%d -> statuses=%d "
                 "events=%d",
                 detail, c["rfid_messages"], c["duplicates"], c["gaps"],
                 c["missing_reports"], c["incidents_created"], c["alerts_merged"],
                 c["snapshots_written"], c["sightings_opened"], c["watchlist_hits"],
                 c["anpr_runs"], c["vision_records"], c["vision_events"])

    def _note_error(self, exc: BaseException) -> None:
        self.counters["errors"] += 1
        self.last_error = f"{type(exc).__name__}: {exc}"
        log.warning("[RFID] error: %s", self.last_error, exc_info=True)

    # ================================================================
    # reporting
    # ================================================================

    def health(self) -> dict:
        """What the header's RFID FUSION badge shows (green only if all fresh)."""
        now = self._wall()

        def age(stamp):
            return None if stamp is None else round(now - stamp, 1)

        rfid_age, frame_age, anpr_age = (age(self._last_rfid_wall), age(self._last_frame_wall),
                                         age(self._last_anpr_wall))
        depth = len(self._vision_jobs)
        db_depth = self.persistence.counters.queue_depth
        problems = []
        if rfid_age is None or rfid_age > self.cfg.health_rfid_stale_s:
            problems.append("no recent RFID reports")
        if frame_age is None or frame_age > self.cfg.health_frame_stale_s:
            problems.append("no recent camera frames")
        if self.adapter is None:
            problems.append("ANPR adapter unavailable")
        elif anpr_age is not None and anpr_age > self.cfg.health_anpr_stale_s and depth:
            problems.append("ANPR not making progress")
        if depth > self.cfg.health_queue_backlog:
            problems.append(f"fusion queue backlog ({depth})")
        if rfid_age is None and frame_age is None:
            status = "offline"
        else:
            status = "sync" if not problems else "degraded"
        return {
            "status": status, "problems": problems,
            "last_rfid_age_s": rfid_age, "last_frame_age_s": frame_age,
            "last_anpr_age_s": anpr_age, "anpr_available": self.adapter is not None,
            "fusion_queue_depth": depth, "db_queue_depth": db_depth,
            "run_id": self.runs.run_id,
        }

    def counters_snapshot(self) -> dict:
        return {
            **self.counters,
            "buffer": self.buffer.counters(),
            "sightings": self.sightings.counters(),
            "frames": self.frames.counters(),
            "registry_size": len(self.registry),
            "persistence": self.persistence.counters.as_dict(),
            "run_id": self.runs.run_id,
            "runs_started": self.runs.run_index,
            "vision_jobs_in_flight": len(self._vision_jobs),
            "last_error": self.last_error,
        }

    def shutdown(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False)


def _decode_jpeg(payload: bytes) -> np.ndarray | None:
    try:
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        return frame if frame is not None and frame.size else None
    except Exception:                                  # pragma: no cover - defensive
        return None


# ------------------------------------------------------------------
# process-wide service + its ticker thread
# ------------------------------------------------------------------

_singleton: RfidCrossVerification | None = None
_singleton_lock = threading.Lock()
_ticker: threading.Thread | None = None


def _portal_broadcaster(message: dict) -> None:
    """Push to the portal through the SAME channel as crash alerts."""
    from app.routers.carla_ws import broadcast_live_message

    broadcast_live_message(message)


def _configure_logging() -> None:
    """The stage log must reach the server log even when nothing configured
    the 'rfid' logger (uvicorn only sets up its own). Level: RFID_LOG_LEVEL."""
    if log.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(os.environ.get("RFID_LOG_LEVEL", "INFO").upper())
    log.propagate = False


def get_service() -> RfidCrossVerification:
    global _singleton, _ticker
    with _singleton_lock:
        if _singleton is None:
            _configure_logging()
            registry = _load_registry()
            _singleton = RfidCrossVerification(cfg=RfidFeatureConfig.from_env(),
                                               registry=registry,
                                               broadcaster=_portal_broadcaster,
                                               adapter=_load_adapter())
            _ticker = threading.Thread(target=_tick_loop, args=(_singleton,),
                                       name="rfid-ticker", daemon=True)
            _ticker.start()
        return _singleton


def peek_service() -> RfidCrossVerification | None:
    """The running service, without starting one (health endpoint)."""
    return _singleton


def _load_registry() -> VehicleRegistry:
    """Registry from Postgres, falling back to the seed if the DB is down."""
    try:
        from app.core.database import SessionLocal
        from app.services.rfid.registry import build_registry_from_db

        session = SessionLocal()
        try:
            registry = build_registry_from_db(session)
            if len(registry):
                return registry
        finally:
            session.close()
    except Exception as exc:
        log.warning("[RFID] registry load failed (%s); using the seed", exc)
    return VehicleRegistry.from_seed()


def _load_adapter():
    """The blind ANPR adapter, or None when the model cannot be set up.

    Construction is cheap (the model loads lazily on the first detect); never
    fatal, because a missing plate model must not stop RFID ingestion.
    """
    try:
        from app.services.anpr_adapter import get_anpr_adapter

        return get_anpr_adapter()
    except Exception as exc:
        log.warning("[RFID] ANPR adapter unavailable (%s); vision verification disabled", exc)
        return None


def _tick_loop(service: RfidCrossVerification, interval: float = 0.5) -> None:
    while True:
        try:
            service.tick()
        except Exception:                              # pragma: no cover - defensive
            pass
        time.sleep(interval)


def set_service(service: RfidCrossVerification | None) -> None:
    """Test helper: swap in a service built with fakes."""
    global _singleton
    with _singleton_lock:
        _singleton = service


def notify_disconnect() -> None:
    if _singleton is not None:
        _singleton.note_disconnect()
