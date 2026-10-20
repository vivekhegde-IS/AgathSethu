"""Crash alerts -> one incident per collision.

Idempotency rules (all of them matter, because Member 1 retries an alert until
the backend acks it, and alert ids restart every CARLA run):

* a repeated ``alert_id`` never creates or re-merges anything;
* the run is taken from ``run_id`` when present, otherwise a new run starts when
  ``timestamp_sim`` jumps backwards by more than ``run_reset_backjump_s`` or the
  connection reconnects after a quiet gap. Alerts are sparse, so the service
  also detects both from the dense RFID/camera stream and hands the reset over
  with ``RunTracker.request_new_run``;
* every key and buffer is scoped by run, so an ``alert_id`` reused in a later
  run is a different alert.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any

from app.services.rfid.config import (
    DEFAULT_CONFIG,
    JUNCTION_WORLD,
    ROLE_INVOLVED,
    RfidFeatureConfig,
)
from app.services.rfid.registry import normalize_plate


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class AlertRecord:
    alert_id: str
    source: str                  # "physics" | "imu_gps"
    status: str | None
    timestamp_sim: float | None
    frame: int | None
    vehicle_id: str | None
    plate_number: str | None
    collision_partner: str | None
    collision_partner_plate: str | None
    epc: str | None
    world_location: dict | None
    gps: dict | None
    junction_id: str | None
    raw: dict = field(default_factory=dict)

    @property
    def is_physics(self) -> bool:
        return self.source == "physics"


def parse_alert(message: dict) -> AlertRecord | None:
    """A crash_alert -> AlertRecord. Returns None when unusable."""
    if not isinstance(message, dict) or message.get("type") != "crash_alert":
        return None
    alert_id = str(message.get("alert_id") or "").strip()
    if not alert_id:
        return None

    status = str(message.get("status") or "")
    source = "physics" if status.upper().startswith("COLLISION_EVENT_CONFIRMED_CARLA_PHYSICS") \
        else "imu_gps"

    world = message.get("world_location")
    if isinstance(world, list) and len(world) >= 2:
        world = {"x": world[0], "y": world[1], "z": world[2] if len(world) > 2 else None}
    if not isinstance(world, dict):
        world = None

    gps = message.get("gps")
    gps = gps if isinstance(gps, dict) else None

    timestamp = _float(message.get("timestamp_sim"))
    if timestamp is None:
        timestamp = _float(message.get("timestamp"))

    frame = message.get("frame")
    try:
        frame = int(frame) if frame is not None else None
    except (TypeError, ValueError):
        frame = None

    return AlertRecord(
        alert_id=alert_id,
        source=source,
        status=status or None,
        timestamp_sim=timestamp,
        frame=frame,
        vehicle_id=(str(message["vehicle_id"]) if message.get("vehicle_id") else None),
        plate_number=(str(message["plate_number"]) if message.get("plate_number") else None),
        collision_partner=(str(message["collision_partner"]) if message.get("collision_partner") else None),
        collision_partner_plate=(str(message["collision_partner_plate"])
                                 if message.get("collision_partner_plate") else None),
        epc=(str(message["epc"]).upper() if message.get("epc") else None),
        world_location=world,
        gps=gps,
        junction_id=(str(message["junction_id"]) if message.get("junction_id") else None),
        raw=dict(message),
    )


def nearest_junction(world_location: dict | None) -> tuple[str | None, float | None]:
    """Nearest configured junction to a world location."""
    if not world_location:
        return None, None
    x, y = _float(world_location.get("x")), _float(world_location.get("y"))
    if x is None or y is None:
        return None, None
    best, best_distance = None, None
    for junction_id, (jx, jy) in JUNCTION_WORLD.items():
        distance = math.hypot(x - jx, y - jy)
        if best_distance is None or distance < best_distance:
            best, best_distance = junction_id, distance
    return best, best_distance


@dataclass
class IncidentVehicleDraft:
    plate_norm: str
    plate_display: str | None
    epc: str | None
    role: str = ROLE_INVOLVED
    sim_vehicle_id: str | None = None       # debug only


@dataclass
class IncidentDraft:
    """In-memory incident being assembled. The DB row is written asynchronously."""

    run_id: str
    crash_ts_sim: float | None
    crash_frame: int | None
    crash_junction: str | None
    world_x: float | None
    world_y: float | None
    world_z: float | None
    gps_lat: float | None
    gps_lon: float | None
    vehicles: list[IncidentVehicleDraft] = field(default_factory=list)
    alerts: list[AlertRecord] = field(default_factory=list)
    warnings: list = field(default_factory=list)
    incident_id: str | None = None          # set once persisted
    closed: bool = False
    # Sightings are fed from the buffer incrementally; this is the watermark so
    # the same read is never consumed twice.
    sighting_cursor_ts: float | None = None
    crash_frame_saved: bool = False
    # Frozen at creation: a LATER alert may add a plate, but the identity of the
    # incident (and therefore its DB row) must not change under it.
    frozen_key: str | None = None
    frozen_dedupe_key: str | None = None
    # Run scoping: the RFID buffer epoch this incident was created in, and the
    # buffer ingest index up to which reads were already fed to the watchlist.
    buffer_epoch: int = 0
    read_cursor: int = 0
    nearby_epcs: set = field(default_factory=set)
    crash_frame_refs: list = field(default_factory=list)
    crash_frames_final: bool = False
    # live | replay | synthetic (from the feeder's feed_source header)
    source: str = "live"
    run_started_at: str | None = None       # wall clock when this run was first seen
    # nearest frame at t_crash for every OTHER junction (context snapshot)
    context_frame_refs: dict = field(default_factory=dict)
    # plate_norm -> Member 1's escape evidence (vehicle_state escape_confirmed):
    # the involved vehicle that drove away from the crash = the fleeing suspect
    fled: dict = field(default_factory=dict)
    # Last sim time whose RFID reads may still become sightings of THIS crash:
    # set when a newer collision of the same vehicles opens its own incident.
    watch_until_ts: float | None = None

    def crash_token(self) -> str:
        """Part of the identity: the same two cars can collide twice at the same
        junction in one continuous CARLA session (sim time never resets)."""
        return f"t{int(round(self.crash_ts_sim))}" if self.crash_ts_sim is not None else "t?"

    @property
    def alert_ids(self) -> list[str]:
        return [alert.alert_id for alert in self.alerts]

    @property
    def involved_plates(self) -> set[str]:
        return {vehicle.plate_norm for vehicle in self.vehicles if vehicle.plate_norm}

    @property
    def involved_epcs(self) -> set[str]:
        return {vehicle.epc for vehicle in self.vehicles if vehicle.epc}

    def time_span(self) -> tuple[float, float]:
        times = [alert.timestamp_sim for alert in self.alerts if alert.timestamp_sim is not None]
        if not times:
            return (self.crash_ts_sim or 0.0, self.crash_ts_sim or 0.0)
        return min(times), max(times)

    def match_key(self) -> str:
        if self.frozen_key is not None:
            return self.frozen_key
        plates = ",".join(sorted(self.involved_plates))
        return f"{self.run_id}|{plates}|{self.crash_token()}"

    def dedupe_key(self) -> str:
        """Stable identity for the DB unique constraint.

        Run + involved plates + crash junction, FROZEN at creation so a later
        alert adding a plate cannot make the same incident look like a new one.
        """
        if self.frozen_dedupe_key is not None:
            return self.frozen_dedupe_key
        plates = ",".join(sorted(self.involved_plates))
        return f"{self.run_id}|{plates}|{self.crash_junction or '?'}|{self.crash_token()}"[:255]

    def stable_id(self) -> str:
        """The incident's DB id, derived from its dedupe key.

        Deterministic, so a replayed or re-created draft for the same collision
        always addresses the same row (and its child rows' foreign keys match).
        """
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "aghat-sethu/incident/" + self.dedupe_key()))

    def freeze_keys(self) -> None:
        if self.frozen_key is None:
            plates = ",".join(sorted(self.involved_plates))
            self.frozen_key = f"{self.run_id}|{plates}|{self.crash_token()}"
            self.frozen_dedupe_key = (f"{self.run_id}|{plates}|{self.crash_junction or '?'}|"
                                      f"{self.crash_token()}")[:255]


class RunTracker:
    """Works out which CARLA run an alert belongs to."""

    def __init__(self, cfg: RfidFeatureConfig = DEFAULT_CONFIG, session: str | None = None):
        self.cfg = cfg
        # Generated ids carry a per-process session stamp: after a backend
        # restart "run-0001" must not collide with a previous session's run.
        self.session = session or datetime.now().strftime("%Y%m%d%H%M%S")
        self.run_id: str | None = None
        self.run_index = 0
        self.last_ts: float | None = None
        self.resets: list[dict] = []
        self.pending_reset: tuple[str, str | None] | None = None   # (reason, run_id)
        self.used_run_ids: set = set()

    def _generated_run_id(self) -> str:
        return f"run-{self.session}-{self.run_index:04d}"

    def request_new_run(self, reason: str, run_id: str | None = None) -> None:
        """The next alert starts a new run (detected from the stream by the service)."""
        self.pending_reset = (reason, run_id)

    def resolve(self, alert: AlertRecord, *, reconnect_gap: bool = False) -> tuple[str, str | None]:
        """Returns (run_id, reason-if-new)."""
        message_run = str(alert.raw.get("run_id")) if alert.raw.get("run_id") else None
        reason = None

        if message_run and message_run != self.run_id:
            reason = f"run_id {message_run} on the message"
            self.run_id, self.run_index = message_run, self.run_index + 1
        elif self.pending_reset is not None:
            reason, stream_run = self.pending_reset
            self.run_index += 1
            if stream_run in self.used_run_ids:
                # a replay with a fixed seed reuses its run_id: keep runs distinct
                stream_run = f"{stream_run}#{self.run_index}"
            self.run_id = stream_run or self._generated_run_id()
        elif self.run_id is None:
            reason = "first alert"
            self.run_index += 1
            self.run_id = self._generated_run_id()
        elif alert.timestamp_sim is not None and self.last_ts is not None and \
                alert.timestamp_sim < self.last_ts - self.cfg.run_reset_backjump_s:
            reason = (f"timestamp_sim went back by "
                      f"{self.last_ts - alert.timestamp_sim:.2f}s")
            self.run_index += 1
            self.run_id = self._generated_run_id()
        elif reconnect_gap:
            reason = "reconnect after a gap"
            self.run_index += 1
            self.run_id = self._generated_run_id()

        self.pending_reset = None
        self.used_run_ids.add(self.run_id)
        if reason:
            self.resets.append({"run_id": self.run_id, "reason": reason})
        if alert.timestamp_sim is not None:
            self.last_ts = alert.timestamp_sim
        return self.run_id, reason


class IncidentAssembler:
    """Groups crash alerts into incidents. Pure logic - no DB, no I/O."""

    def __init__(self, registry, cfg: RfidFeatureConfig = DEFAULT_CONFIG,
                 runs: RunTracker | None = None):
        self.registry = registry
        self.cfg = cfg
        self.runs = runs or RunTracker(cfg)
        self.incidents: dict[str, IncidentDraft] = {}     # match_key -> open incident
        # (run_id, alert_id) -> timestamp_sim of the first delivery
        self.seen_alert_ids: dict[tuple[str, str], float | None] = {}
        self.duplicates = 0
        self.created = 0
        self.merged = 0
        self.involved_by_alert: dict[str, list[str]] = {}

    # ---------------- helpers ----------------

    def _involved(self, alert: AlertRecord) -> list[IncidentVehicleDraft]:
        """Involved plates = this alert's plate + its collision partner's plate.

        Each plate is mapped to its EPC THROUGH THE REGISTRY; the alert's own
        ``epc`` is only a cross-check.
        """
        seen: dict[str, IncidentVehicleDraft] = {}
        for plate_text in (alert.plate_number, alert.collision_partner_plate):
            plate_norm = normalize_plate(plate_text)
            if not plate_norm or plate_norm in seen:
                continue
            entry = self.registry.lookup_plate(plate_norm)
            if entry is None:
                self.involved_by_alert.setdefault(alert.alert_id, []).append(plate_norm)
            seen[plate_norm] = IncidentVehicleDraft(
                plate_norm=plate_norm,
                plate_display=(entry.plate_display if entry else None),
                epc=(entry.epc if entry else None),
                role=ROLE_INVOLVED,
                sim_vehicle_id=(entry.sim_vehicle_id if entry else None),
            )

        # The alert's epc only stands in when the alert names no plate of its own;
        # otherwise it is a cross-check (see _epc_warning), never a new vehicle.
        entry = self.registry.lookup_epc(alert.epc) if not normalize_plate(alert.plate_number) \
            else None
        if entry is not None and entry.plate_norm and entry.plate_norm not in seen:
            seen[entry.plate_norm] = IncidentVehicleDraft(
                plate_norm=entry.plate_norm, plate_display=entry.plate_display,
                epc=entry.epc, role=ROLE_INVOLVED, sim_vehicle_id=entry.sim_vehicle_id)

        return list(seen.values())

    def _epc_warning(self, alert: AlertRecord) -> str | None:
        """Cross-check the alert's own epc against the registry EPC of its plate."""
        if not alert.epc or not alert.plate_number:
            return None
        entry = self.registry.lookup_plate(normalize_plate(alert.plate_number))
        if entry is not None and entry.epc != alert.epc:
            return (f"alert {alert.alert_id}: epc {alert.epc} disagrees with the registry EPC "
                    f"{entry.epc} for {entry.plate_norm}; registry wins")
        return None

    def _same_collision(self, incident: IncidentDraft, alert: AlertRecord) -> bool:
        """Same run (guaranteed by the caller), overlapping plates, close in time."""
        if incident.closed:
            return False

        start, end = incident.time_span()
        if alert.timestamp_sim is not None:
            if alert.timestamp_sim < start - self.cfg.alert_merge_window_s:
                return False
            if alert.timestamp_sim > end + self.cfg.alert_merge_window_s:
                return False

        new_plates = {vehicle.plate_norm for vehicle in self._involved(alert)}
        if new_plates and incident.involved_plates:
            return bool(new_plates & incident.involved_plates)
        # An alert carrying no recognisable plate can only be merged on time.
        return True

    # ---------------- main entry ----------------

    def handle_alert(self, alert: AlertRecord, *, reconnect_gap: bool = False,
                     buffer=None) -> tuple[str, IncidentDraft | None]:
        """('duplicate'|'merged'|'created', incident-or-None)."""
        run_id, reset_reason = self.runs.resolve(alert, reconnect_gap=reconnect_gap)

        key = (run_id, alert.alert_id)
        if key in self.seen_alert_ids:
            first_ts = self.seen_alert_ids[key]
            if first_ts is not None and alert.timestamp_sim is not None and \
                    abs(alert.timestamp_sim - first_ts) > self.cfg.alert_merge_window_s:
                # Same alert id, a different crash time: Member 1's alert
                # counters restarted (new script start, sim time kept running).
                return "restart", None
            self.duplicates += 1
            return "duplicate", None
        self.seen_alert_ids[key] = alert.timestamp_sim

        # find an open incident in this run that this alert belongs to
        for incident in self.incidents.values():
            if incident.run_id != run_id or incident.closed:
                continue
            if self._same_collision(incident, alert):
                self._merge(incident, alert)
                self.merged += 1
                return "merged", incident

        incident = self._create(run_id, alert, buffer, reset_reason)
        self.created += 1
        return "created", incident

    def _merge(self, incident: IncidentDraft, alert: AlertRecord) -> None:
        incident.alerts.append(alert)
        warning = self._epc_warning(alert)
        if warning:
            incident.warnings.append(warning)
        known = {vehicle.plate_norm for vehicle in incident.vehicles}
        for vehicle in self._involved(alert):
            if vehicle.plate_norm not in known:
                incident.vehicles.append(vehicle)
                known.add(vehicle.plate_norm)
        if incident.crash_ts_sim is None and alert.timestamp_sim is not None:
            incident.crash_ts_sim = alert.timestamp_sim
        if incident.crash_junction is None:
            incident.crash_junction, _ = nearest_junction(alert.world_location)

    def _create(self, run_id: str, alert: AlertRecord, buffer, reset_reason: str | None) -> IncidentDraft:
        world = alert.world_location or {}
        gps = alert.gps or {}
        junction, distance = nearest_junction(world)

        incident = IncidentDraft(
            run_id=run_id,
            crash_ts_sim=alert.timestamp_sim,
            crash_frame=alert.frame,
            crash_junction=junction or alert.junction_id,
            world_x=_float(world.get("x")),
            world_y=_float(world.get("y")),
            world_z=_float(world.get("z")),
            gps_lat=_float(gps.get("lat") or gps.get("latitude")),
            gps_lon=_float(gps.get("lon") or gps.get("lng") or gps.get("longitude")),
            vehicles=self._involved(alert),
            alerts=[alert],
        )
        if reset_reason:
            incident.warnings.append(f"new run: {reset_reason}")
        if junction is not None and distance is not None and distance > 120.0:
            incident.warnings.append(
                f"crash location is {distance:.0f} m from the nearest junction ({junction})")

        # Cross-check the geometric junction against the reader evidence.
        if buffer is not None and incident.involved_epcs and incident.crash_ts_sim is not None:
            reader_junction = buffer.most_recent_reader_for(incident.involved_epcs,
                                                            incident.crash_ts_sim + 1e-6)
            if reader_junction and reader_junction != incident.crash_junction:
                incident.warnings.append(
                    f"crash junction {incident.crash_junction} from world_location but the "
                    f"involved tags were last read at {reader_junction}")

        warning = self._epc_warning(alert)
        if warning:
            incident.warnings.append(warning)
        for plate_norm in self.involved_by_alert.get(alert.alert_id, []):
            incident.warnings.append(
                f"involved plate {plate_norm} is not in the vehicle registry")

        incident.freeze_keys()
        self.incidents[incident.match_key()] = incident
        return incident

    def close(self, incident: IncidentDraft) -> None:
        incident.closed = True

    def reopen_key(self, incident: IncidentDraft) -> None:
        """A merged alert after close must land on the same DB row."""
        incident.closed = False
        self.incidents[incident.match_key()] = incident
