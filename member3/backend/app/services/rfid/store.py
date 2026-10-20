"""Asynchronous persistence for the RFID feature.

Nothing here ever blocks a WebSocket receive loop:

  * every write is a plain dict pushed onto a bounded queue;
  * one background thread drains it, in its own DB session per operation;
  * if Postgres is down the operation is retried with exponential backoff,
    staying at the head of the queue, and the failure is logged with a count.

IDs are generated BEFORE the write (``uuid4``) so callers never need a DB
round-trip: evidence directories can be named immediately.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from app.services.rfid.config import DEFAULT_CONFIG, ROLE_INVOLVED, RfidFeatureConfig

log = logging.getLogger("rfid")


def new_id() -> str:
    return str(uuid.uuid4())


def retryable(exc: BaseException) -> bool:
    """True only for errors a retry could plausibly fix (DB down/unreachable).

    Constraint violations, bad types and our own bugs are PERMANENT: retrying
    them forever would head-of-line block every later write behind one row.
    """
    try:
        from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
    except Exception:                                  # pragma: no cover
        return False
    if isinstance(exc, InterfaceError):
        return True
    if isinstance(exc, OperationalError):
        return True
    if isinstance(exc, DBAPIError):
        return bool(getattr(exc, "connection_invalidated", False))
    return False


@dataclass
class StoreCounters:
    submitted: int = 0
    written: int = 0
    failed: int = 0
    retries: int = 0
    dropped: int = 0
    queue_depth: int = 0
    last_error: str | None = None
    by_kind: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "submitted": self.submitted,
            "written": self.written,
            "failed": self.failed,
            "retries": self.retries,
            "dropped": self.dropped,
            "queue_depth": self.queue_depth,
            "last_error": self.last_error,
            "by_kind": dict(self.by_kind),
        }


class Persistence:
    """Queued Postgres writer."""

    def __init__(self, cfg: RfidFeatureConfig = DEFAULT_CONFIG, session_factory=None,
                 enabled: bool = True):
        self.cfg = cfg
        self.enabled = enabled
        self.counters = StoreCounters()
        self._session_factory = session_factory or _default_session_factory
        self._queue: deque = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._backoff = cfg.db_retry_min_s

    # ---------------- lifecycle ----------------

    def start(self) -> "Persistence":
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="rfid-store", daemon=True)
            self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    # ---------------- submission ----------------

    def submit(self, kind: str, payload: Any) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            if len(self._queue) >= self.cfg.db_queue_max:
                self.counters.dropped += 1
                return False
            self._queue.append((kind, payload))
            self.counters.submitted += 1
            self.counters.by_kind[kind] = self.counters.by_kind.get(kind, 0) + 1
            self.counters.queue_depth = len(self._queue)
        self._wake.set()
        return True

    def flush(self, timeout: float = 30.0) -> bool:
        """Block until the queue drains (used by tests and shutdown)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._queue:
                    return True
            time.sleep(0.05)
        return False

    # ---------------- worker ----------------

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                item = self._queue[0] if self._queue else None
            if item is None:
                self._wake.wait(timeout=0.2)
                self._wake.clear()
                continue

            kind, payload = item
            try:
                self._write(kind, payload)
            except Exception as exc:                 # DB down, constraint, ...
                self.counters.failed += 1
                self.counters.last_error = f"{type(exc).__name__}: {exc}"
                if not retryable(exc):
                    # Permanent: drop the poison row and keep the queue moving.
                    self.counters.dropped += 1
                    log.warning("[RFID] dropping un-writable %s row: %s", kind, exc, exc_info=True)
                    with self._lock:
                        if self._queue and self._queue[0] is item:
                            self._queue.popleft()
                        self.counters.queue_depth = len(self._queue)
                    continue
                time.sleep(self._backoff)
                self._backoff = min(self.cfg.db_retry_max_s, self._backoff * 2)
                self.counters.retries += 1
                continue

            # success: pop it and reset the backoff
            with self._lock:
                if self._queue and self._queue[0] is item:
                    self._queue.popleft()
                self.counters.queue_depth = len(self._queue)
            self.counters.written += 1
            self._backoff = self.cfg.db_retry_min_s
            if not self._wake.is_set():
                self._wake.set()

    def _write(self, kind: str, payload: dict) -> None:
        handler = getattr(self, f"_write_{kind}", None)
        if handler is None:
            raise ValueError(f"unknown persistence kind {kind!r}")
        session = self._session_factory()
        try:
            handler(session, payload)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ---------------- handlers ----------------

    def _write_incident(self, session, payload: dict) -> None:
        from app.models.models import Incident

        existing = (session.query(Incident)
                    .filter(Incident.dedupe_key == payload["dedupe_key"]).one_or_none())
        if existing is not None:
            # Idempotent: refresh the mutable fields, keep the same row.
            existing.crash_ts_sim = payload.get("crash_ts_sim")
            existing.crash_frame = payload.get("crash_frame")
            existing.crash_junction = payload.get("crash_junction")
            existing.world_x = payload.get("world_x")
            existing.world_y = payload.get("world_y")
            existing.world_z = payload.get("world_z")
            if payload.get("source") and not existing.source:
                existing.source = payload["source"]
            return
        session.add(Incident(
            id=payload["id"],
            incident_type="crash",
            severity="critical",
            status="detected",
            description=payload.get("description"),
            run_id=payload.get("run_id"),
            crash_ts_sim=payload.get("crash_ts_sim"),
            crash_frame=payload.get("crash_frame"),
            crash_junction=payload.get("crash_junction"),
            world_x=payload.get("world_x"),
            world_y=payload.get("world_y"),
            world_z=payload.get("world_z"),
            latitude=payload.get("gps_lat"),
            longitude=payload.get("gps_lon"),
            dedupe_key=payload["dedupe_key"],
            source=payload.get("source"),
            run_started_at=_as_datetime(payload.get("run_started_at")),
        ))

    def _write_incident_alert(self, session, payload: dict) -> None:
        from app.models.models import IncidentAlert

        key = (payload["incident_id"], payload["alert_id"])
        existing = (session.query(IncidentAlert)
                    .filter(IncidentAlert.incident_id == key[0],
                            IncidentAlert.alert_id == key[1]).one_or_none())
        if existing is not None:
            return
        session.add(IncidentAlert(
            incident_id=payload["incident_id"], alert_id=payload["alert_id"],
            run_id=payload.get("run_id"), source=payload.get("source") or "imu_gps",
            status=payload.get("status"), timestamp_sim=payload.get("timestamp_sim"),
            frame=payload.get("frame"), raw=payload.get("raw"),
        ))

    def _write_incident_vehicle(self, session, payload: dict) -> None:
        from app.models.models import IncidentVehicle

        existing = (session.query(IncidentVehicle)
                    .filter(IncidentVehicle.incident_id == payload["incident_id"],
                            IncidentVehicle.plate_norm == payload["plate_norm"],
                            IncidentVehicle.role == payload["role"]).one_or_none())
        if existing is not None:
            if payload.get("epc") and not existing.epc:
                existing.epc = payload["epc"]
            return
        session.add(IncidentVehicle(
            incident_id=payload["incident_id"], plate_norm=payload["plate_norm"],
            plate_display=payload.get("plate_display"), epc=payload.get("epc"),
            role=payload["role"], sim_vehicle_id=payload.get("sim_vehicle_id"),
        ))
        if payload["role"] == ROLE_INVOLVED:
            # the registered owner's citizen alert, in the same transaction
            from app.services.notification_service import notify_crash_involvement

            session.flush()
            notify_crash_involvement(session, payload["incident_id"], payload["plate_norm"])

    def _write_rfid_report(self, session, payload: dict) -> None:
        from app.models.models import RfidReport

        session.add(RfidReport(
            run_id=payload.get("run_id"), reader_id=payload["reader_id"],
            seq=payload["seq"], junction_id=payload["junction_id"], epc=payload["epc"],
            plate_norm=payload.get("plate_norm"),
            registry_status=payload.get("registry_status"),
            first_seen_ts=payload["first_seen_ts"], last_seen_ts=payload["last_seen_ts"],
            tag_seen_count=payload.get("tag_seen_count"), rssi_dbm=payload.get("rssi_dbm"),
            schema=payload.get("schema"), sim_vehicle_id=payload.get("sim_vehicle_id"),
        ))

    def _write_crash_zone(self, session, payload: dict) -> None:
        from app.models.models import CrashZoneRfid

        existing = (session.query(CrashZoneRfid)
                    .filter(CrashZoneRfid.incident_id == payload["incident_id"],
                            CrashZoneRfid.junction_id == payload["junction_id"],
                            CrashZoneRfid.epc == payload["epc"]).one_or_none())
        if existing is not None:
            existing.first_seen_ts = min(existing.first_seen_ts, payload["first_seen_ts"])
            existing.last_seen_ts = max(existing.last_seen_ts, payload["last_seen_ts"])
            existing.report_count = payload["report_count"]
            existing.tag_seen_count = payload["tag_seen_count"]
            if payload.get("peak_rssi_dbm") is not None:
                existing.peak_rssi_dbm = payload["peak_rssi_dbm"] if existing.peak_rssi_dbm is None \
                    else max(existing.peak_rssi_dbm, payload["peak_rssi_dbm"])
            existing.role = payload.get("role") or existing.role
            return
        session.add(CrashZoneRfid(
            incident_id=payload["incident_id"], junction_id=payload["junction_id"],
            reader_id=payload.get("reader_id"), epc=payload["epc"],
            plate_norm=payload.get("plate_norm"), first_seen_ts=payload["first_seen_ts"],
            last_seen_ts=payload["last_seen_ts"], report_count=payload["report_count"],
            tag_seen_count=payload["tag_seen_count"], peak_rssi_dbm=payload.get("peak_rssi_dbm"),
            role=payload.get("role") or "involved",
            zone=payload.get("zone") or "crash",
        ))

    def _write_sighting(self, session, payload: dict) -> None:
        from app.models.models import RfidSighting

        existing = session.get(RfidSighting, payload["id"])
        if existing is None:
            session.add(RfidSighting(
                id=payload["id"], incident_id=payload["incident_id"], epc=payload["epc"],
                plate_norm=payload.get("plate_norm"), junction_id=payload["junction_id"],
                reader_id=payload.get("reader_id"), first_seen_ts=payload["first_seen_ts"],
                last_seen_ts=payload["last_seen_ts"], report_count=payload["report_count"],
                tag_seen_count=payload.get("tag_seen_count", 0),
                peak_rssi_dbm=payload.get("peak_rssi_dbm"), closed=payload.get("closed", False),
                finalized=payload.get("finalized", False), version=payload.get("version", 0),
            ))
            return
        existing.last_seen_ts = max(existing.last_seen_ts, payload["last_seen_ts"])
        existing.report_count = payload["report_count"]
        existing.tag_seen_count = payload.get("tag_seen_count", existing.tag_seen_count)
        if payload.get("peak_rssi_dbm") is not None:
            existing.peak_rssi_dbm = payload["peak_rssi_dbm"] if existing.peak_rssi_dbm is None \
                else max(existing.peak_rssi_dbm, payload["peak_rssi_dbm"])
        existing.first_seen_ts = min(existing.first_seen_ts, payload["first_seen_ts"])
        existing.closed = payload.get("closed", existing.closed)
        existing.finalized = bool(existing.finalized or payload.get("finalized", False))
        existing.version = max(existing.version or 0, payload.get("version", 0))

    def _write_vision_match(self, session, payload: dict) -> None:
        from app.models.models import VisionMatch

        existing = (session.query(VisionMatch)
                    .filter(VisionMatch.sighting_id == payload["sighting_id"]).one_or_none())
        if existing is None:
            existing = VisionMatch(id=payload["id"], sighting_id=payload["sighting_id"],
                                   status=payload["status"], version=0)
            session.add(existing)
        elif (payload.get("version") or 0) < (existing.version or 0) or existing.finalized:
            # an older (out-of-order) version, or the row is already final
            return
        for name in VISION_MATCH_FIELDS:
            if name in payload:
                setattr(existing, name, payload[name])

    def _write_evidence(self, session, payload: dict) -> None:
        from app.models.models import EvidenceFile

        session.add(EvidenceFile(
            incident_id=payload.get("incident_id"),
            vision_match_id=payload.get("vision_match_id"),
            owner=payload["owner"], kind=payload["kind"], path=payload["path"],
            sha256=payload["sha256"], width=payload.get("width"),
            height=payload.get("height"), score=payload.get("score"),
            frame_ts=payload.get("frame_ts"), junction_id=payload.get("junction_id"),
        ))

    def _write_seed_registry(self, session, payload: dict) -> None:
        from app.services.rfid.registry import seed_registry

        seed_registry(session)


VISION_MATCH_FIELDS = (
    "status", "rfid_plate", "anpr_plate", "anpr_confidence", "edit_distance", "camera_id",
    "best_frame_ts", "time_delta_s", "frames_used", "all_plates_seen", "anpr_model",
    "rule_assisted", "match_reason", "diff", "other_vehicles", "rejected_reads", "per_frame",
    "max_plate_px", "cluster_frames", "anpr_state_code", "version", "finalized",
)


def _as_datetime(value):
    if value is None or not isinstance(value, str):
        return value
    from datetime import datetime

    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _default_session_factory():
    from app.core.database import SessionLocal

    return SessionLocal()


_SINGLETON: Persistence | None = None
_SINGLETON_LOCK = threading.Lock()


def get_persistence() -> Persistence:
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = Persistence(cfg=RfidFeatureConfig.from_env()).start()
        return _SINGLETON


def reset_persistence(persistence: Persistence | None = None) -> None:
    """Test helper."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is not None:
            _SINGLETON.stop()
        _SINGLETON = persistence
