"""UHF RFID reader simulation shared by the CARLA script, the offline replay
and the feed simulator.

Pure Python: this module must NOT import carla (or cv2/torch), so it can run on
any machine and be unit-tested without the simulator.

What it models
--------------
1. Placement    one reader per junction, at a configurable position (default the
                junction centre plus an optional offset). The read zone is
                centred on the READER, not implicitly on the junction.
2. Signal       RSSI from a log-distance path-loss model with a per-read
                Gaussian shadowing term. A tag is readable only while its RSSI
                is above the reader sensitivity floor.
3. Inventory    the reader runs inventory rounds at RFID_INVENTORY_HZ (about
                20 Hz, one round per world tick). In each round a tag in range
                is read with a probability that falls with its RSSI margin, its
                speed, and the number of tags competing for the round
                (anti-collision).
4. Reporting    a reader does not emit one message per successful read. Reads
                are aggregated per tag and one TAG_REPORT is emitted every
                RFID_REPORT_INTERVAL_S for each tag seen in that interval.

Optional test conditions (all OFF by default; the default stream is unchanged)
-----------------------------------------------------------------------------
RFID_READER_POSITIONS_FILE   JSON {"J01": {"x": .., "y": ..}, ...}: move readers
                             (e.g. into the camera view). Logged in the config.
RFID_ANTENNAS_PER_JUNCTION   k antennas per junction on a circle of
                             RFID_ANTENNA_RADIUS_M around the reader position,
                             at RFID_ANTENNA_ANGLE_DEG + i * 360/k. Each antenna is
                             its own reader (reader_id RFID_Jnn_0i, antenna_id Ai).
RFID_GHOST_TAGS_PER_JUNCTION stationary tags (roadside / parked) at
                             RFID_GHOST_DISTANCE_M from each reader; EPC
                             E20000172211EE<jj><gggg>, ground truth GHOST_Jnn_g.
RFID_CLOCK_OFFSETS_S         JSON {"J01": 0.3, ...}: the reader clock runs ahead of
                             sim time by this much (all report timestamps shifted;
                             ground truth unaffected).

Calibration caveat
------------------
The RSSI values are ILLUSTRATIVE. They are chosen so the nominal read range is
about 10 m (the mean RSSI equals the sensitivity floor at that distance), which
is a plausible UHF handheld/gate range. They are NOT measured against real
hardware and must not be presented as calibrated.
"""

from __future__ import annotations

import csv
import json
import math
import os
import random
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_V2 = "rfid_tag_report_v2"

# Output file names, written under <OUT_DIR>/multimodal_evidence.
RFID_REPORTS_CSV = "rfid_readings.csv"
RFID_GROUND_TRUTH_CSV = "rfid_ground_truth.csv"

# Junction world coordinates (matches vivek_fb.py JUNCTIONS and the backend's
# CARLA_JUNCTION_LOCATIONS).
JUNCTION_WORLD = {
    "J01": (-28.7, 28.1),
    "J02": (-41.6, 82.6),
    "J03": (-71.3, 132.3),
}

# Camera geometry from Member 1's script, used only for the coverage check.
CAMERA_HEIGHT_M = 5.0
CAMERA_BACK_DISTANCE_M = 25.0
CAMERA_FOV_DEG = 65.0
CAMERA_WIDTH_PX = 1280
CAMERA_HEIGHT_PX = 720


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RfidConfig:
    """Every RFID tunable. Read from the environment by ``from_env()``."""

    enabled: bool = True

    # --- signal model ---
    reference_rssi_dbm: float = -30.0     # mean RSSI at 1 m (illustrative)
    path_loss_exponent: float = 2.5       # 2.5 gives ~10 m at the floor below
    shadowing_sigma_db: float = 3.0       # per-read Gaussian shadowing
    sensitivity_dbm: float = -55.0        # reader sensitivity floor
    margin_scale_db: float = 4.0          # logistic read-probability steepness

    # --- inventory model ---
    inventory_hz: float = 20.0            # one round per world tick
    speed_penalty_per_kmh: float = 0.02   # faster vehicles are read less
    anticollision_share: float = 0.6      # contention between tags in the field
    pass_miss_prob: float = 0.0           # optional whole-pass miss

    # --- reporting ---
    report_interval_s: float = 0.5        # one TAG_REPORT per tag per interval
    antenna_id: str = "A1"

    # --- delivery / optional realism ---
    cross_read_enabled: bool = False
    cross_read_radius_m: float = 35.0
    cross_read_probability: float = 0.05
    duplicate_report_enabled: bool = False
    duplicate_report_probability: float = 0.02

    # --- placement / determinism ---
    reader_offset_m: tuple = (0.0, 0.0)   # added to every junction centre
    reader_positions: str = ""            # JSON {"J01": {"x":..,"y":..}} override ("" = off)
    antennas_per_junction: int = 1
    antenna_radius_m: float = 6.0
    antenna_angle_deg: float = 0.0
    ghost_tags_per_junction: int = 0
    ghost_distance_m: float = 7.0
    clock_offsets_s: str = ""             # JSON {"J01": 0.3} ("" = all 0)
    seed: int = 20240930
    deterministic_run_id: bool = False     # seed-derived run_id even on a live start

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_env(cls, prefix: str = "RFID_") -> "RfidConfig":
        cfg = cls(
            reference_rssi_dbm=_env_float(prefix + "REFERENCE_RSSI_DBM", cls.reference_rssi_dbm),
            path_loss_exponent=_env_float(prefix + "PATH_LOSS_EXPONENT", cls.path_loss_exponent),
            shadowing_sigma_db=_env_float(prefix + "SHADOWING_SIGMA_DB", cls.shadowing_sigma_db),
            sensitivity_dbm=_env_float(prefix + "SENSITIVITY_DBM", cls.sensitivity_dbm),
            margin_scale_db=_env_float(prefix + "MARGIN_SCALE_DB", cls.margin_scale_db),
            inventory_hz=_env_float(prefix + "INVENTORY_HZ", cls.inventory_hz),
            speed_penalty_per_kmh=_env_float(prefix + "SPEED_PENALTY_PER_KMH", cls.speed_penalty_per_kmh),
            anticollision_share=_env_float(prefix + "ANTICOLLISION_SHARE", cls.anticollision_share),
            pass_miss_prob=_env_float(prefix + "PASS_MISS_PROB", cls.pass_miss_prob),
            report_interval_s=_env_float(prefix + "REPORT_INTERVAL_S", cls.report_interval_s),
            antenna_id=os.environ.get(prefix + "ANTENNA_ID", cls.antenna_id),
            cross_read_enabled=_env_bool(prefix + "CROSS_READ", cls.cross_read_enabled),
            cross_read_radius_m=_env_float(prefix + "CROSS_READ_RADIUS_M", cls.cross_read_radius_m),
            cross_read_probability=_env_float(prefix + "CROSS_READ_PROB", cls.cross_read_probability),
            duplicate_report_enabled=_env_bool(prefix + "DUPLICATE_REPORT", cls.duplicate_report_enabled),
            duplicate_report_probability=_env_float(prefix + "DUPLICATE_REPORT_PROB",
                                                    cls.duplicate_report_probability),
            seed=_env_int(prefix + "RNG_SEED", cls.seed),
            deterministic_run_id=_env_bool(prefix + "DETERMINISTIC_RUN_ID", cls.deterministic_run_id),
            reader_positions=_read_positions_file(os.environ.get(prefix + "READER_POSITIONS_FILE", "")),
            antennas_per_junction=max(1, _env_int(prefix + "ANTENNAS_PER_JUNCTION", cls.antennas_per_junction)),
            antenna_radius_m=_env_float(prefix + "ANTENNA_RADIUS_M", cls.antenna_radius_m),
            antenna_angle_deg=_env_float(prefix + "ANTENNA_ANGLE_DEG", cls.antenna_angle_deg),
            ghost_tags_per_junction=max(0, _env_int(prefix + "GHOST_TAGS_PER_JUNCTION", cls.ghost_tags_per_junction)),
            ghost_distance_m=_env_float(prefix + "GHOST_DISTANCE_M", cls.ghost_distance_m),
            clock_offsets_s=os.environ.get(prefix + "CLOCK_OFFSETS_S", cls.clock_offsets_s).strip(),
        )
        return cfg


def _read_positions_file(path: str) -> str:
    """Contents of RFID_READER_POSITIONS_FILE as a compact JSON string ("" = off).
    Stored in the config so the run's logged config records the real positions."""
    if not path:
        return ""
    with open(path, encoding="utf-8-sig") as handle:
        data = json.load(handle)
    readers = data.get("readers", data)
    return json.dumps({jid: {"x": float(v["x"]), "y": float(v["y"])} for jid, v in readers.items()},
                      sort_keys=True)


def antenna_layout(junction_xy: dict, cfg: "RfidConfig") -> list[dict]:
    """Every antenna (= reader): junction, reader_id, antenna_id, x, y.

    junction_xy: {junction_id: (x, y)} BEFORE the optional positions override;
    the override and the antenna circle are applied here, so offline tools can
    rebuild the exact layout from a run's logged config.
    """
    override = json.loads(cfg.reader_positions) if cfg.reader_positions else {}
    out = []
    for junction_id in sorted(junction_xy):
        if junction_id in override:
            x, y = override[junction_id]["x"], override[junction_id]["y"]
        else:
            x, y = junction_xy[junction_id]
        x, y = x + cfg.reader_offset_m[0], y + cfg.reader_offset_m[1]
        k = max(1, int(cfg.antennas_per_junction))
        for i in range(k):
            if k == 1:
                ax, ay = x, y
            else:
                angle = math.radians(cfg.antenna_angle_deg + i * 360.0 / k)
                ax, ay = x + cfg.antenna_radius_m * math.cos(angle), y + cfg.antenna_radius_m * math.sin(angle)
            out.append({"junction": junction_id, "reader_id": f"RFID_J{int(junction_id[1:]):02d}_{i + 1:02d}",
                        "antenna_id": cfg.antenna_id if i == 0 else f"A{i + 1}", "x": ax, "y": ay})
    return out


DEFAULT_CONFIG = RfidConfig()


# ============================================================
# SIGNAL MODEL
# ============================================================

def mean_rssi_dbm(distance_m: float, cfg: RfidConfig = DEFAULT_CONFIG) -> float:
    """Log-distance path loss: RSSI(d) = P0 - 10 n log10(d).

    Distance is floored at 1 m, the model's reference point, so a tag sitting on
    the antenna does not report an absurd positive RSSI.
    """
    distance = max(1.0, float(distance_m))
    return cfg.reference_rssi_dbm - 10.0 * cfg.path_loss_exponent * math.log10(distance)


def nominal_range_m(cfg: RfidConfig = DEFAULT_CONFIG) -> float:
    """Distance at which the MEAN RSSI equals the sensitivity floor."""
    span = cfg.reference_rssi_dbm - cfg.sensitivity_dbm
    if span <= 0:
        return 0.0
    return 10.0 ** (span / (10.0 * cfg.path_loss_exponent))


def sample_rssi_dbm(distance_m: float, rng: random.Random,
                    cfg: RfidConfig = DEFAULT_CONFIG) -> float:
    """One read's RSSI: mean path loss plus Gaussian shadowing."""
    return mean_rssi_dbm(distance_m, cfg) + rng.gauss(0.0, cfg.shadowing_sigma_db)


def read_probability(rssi_dbm: float, speed_kmh: float, tags_in_field: int,
                     cfg: RfidConfig = DEFAULT_CONFIG) -> float:
    """Probability that this tag wins one inventory round.

    Zero below the sensitivity floor; then a logistic in the RSSI margin,
    reduced by speed and by anti-collision contention with other tags.
    """
    margin = rssi_dbm - cfg.sensitivity_dbm
    if margin < 0:
        return 0.0
    probability = 1.0 / (1.0 + math.exp(-margin / max(1e-6, cfg.margin_scale_db)))
    probability /= 1.0 + cfg.speed_penalty_per_kmh * max(0.0, speed_kmh)
    competitors = max(1, int(tags_in_field))
    probability /= 1.0 + (competitors - 1) * cfg.anticollision_share
    return max(0.0, min(1.0, probability))


# ============================================================
# CAMERA COVERAGE CHECK
# ============================================================

def camera_coverage_fraction(radius_m: float = 10.0, samples: int = 360,
                             cfg: RfidConfig = DEFAULT_CONFIG) -> float:
    """Fraction of a disc of ``radius_m`` around a junction centre that the
    junction camera can see.

    Approximate pinhole check with Member 1's geometry (camera 5 m up, 25 m
    back, 65 deg horizontal FOV, 16:9). Used to confirm that a vehicle inside
    the RFID read zone is also inside the camera frame, which the vision
    verification needs.
    """
    half_h = math.radians(CAMERA_FOV_DEG) / 2.0
    half_v = math.atan(math.tan(half_h) * CAMERA_HEIGHT_PX / CAMERA_WIDTH_PX)
    visible = 0
    for index in range(samples):
        angle = 2.0 * math.pi * index / samples
        lateral = radius_m * math.cos(angle)
        forward = CAMERA_BACK_DISTANCE_M + radius_m * math.sin(angle)
        if forward <= 1.0:
            continue
        if abs(math.atan(lateral / forward)) <= half_h and abs(math.atan(
                CAMERA_HEIGHT_M / forward)) <= half_v:
            visible += 1
    return visible / samples


# ============================================================
# READER / INVENTORY MODEL
# ============================================================

@dataclass
class TagObservation:
    """One vehicle seen by one reader in the current interval."""

    vehicle_id: str
    epc: str
    peak_rssi: float
    count: int
    first_seen_ts: float
    last_seen_ts: float
    last_distance_m: float
    last_speed_kmh: float
    nearby: bool = False        # cross-read (neighbouring lane), never involved


@dataclass
class _ReaderState:
    seq: int = 0
    interval_start: float | None = None
    observations: dict[str, TagObservation] = field(default_factory=dict)
    present: set = field(default_factory=set)       # EPCs inside the RF field last round


class RfidReaderModel:
    """Stateful, seeded RFID reader simulation.

    ``step(timestamp_sim, frame, vehicles)`` is called once per world tick with
    every vehicle's world pose; it returns the v2 TAG_REPORT messages (and the
    matching ground-truth rows) produced at that tick. Most ticks return
    nothing, exactly like a real reader that reports on an interval.
    """

    def __init__(self, cfg: RfidConfig | None = None, seed: int | None = None,
                 junction_locations: dict[str, tuple[float, float]] | None = None,
                 run_id: str | None = None):
        self.cfg = cfg or DEFAULT_CONFIG
        explicit_seed = seed is not None
        seed = self.cfg.seed if seed is None else seed
        self.seed = seed
        self.rng = random.Random(seed)
        # run_id identifies ONE start of the reader. A live start (no explicit
        # seed) gets a fresh uuid4, like a real reader: a seed-derived id would
        # repeat on every CARLA start and the backend could not tell runs apart.
        # Offline replays that pass an explicit seed (or set
        # RFID_DETERMINISTIC_RUN_ID=1) keep the seed-derived id, so a fixed seed
        # still reproduces the whole stream byte-for-byte.
        if run_id:
            self.run_id = run_id
        elif explicit_seed or self.cfg.deterministic_run_id:
            self.run_id = str(uuid.UUID(int=random.Random(f"rfid-run:{seed}").getrandbits(128)))
        else:
            self.run_id = str(uuid.uuid4())
        self.junctions = dict(junction_locations or JUNCTION_WORLD)
        self.antennas = antenna_layout(self.junctions, self.cfg)
        self.readers = {a["reader_id"]: _ReaderState() for a in self.antennas}
        self.junction_present: dict[str, set] = {junction: set() for junction in self.junctions}
        self.clock_offsets = ({str(k): float(v) for k, v in json.loads(self.cfg.clock_offsets_s).items()}
                              if self.cfg.clock_offsets_s else {})
        self.ghosts = self._place_ghosts()
        # Optional fault injection, all default-off. A key here suppresses the
        # NEXT report interval for that (junction, tag) - a whole missed pass.
        self.missed_pass: set[tuple[str, str]] = set()   # armed: miss the NEXT pass
        self.suppressed: set[tuple[str, str]] = set()    # a pass being missed right now

    # ---------------- placement ----------------

    def reader_position(self, junction_id: str) -> tuple[float, float]:
        """Centre of the junction's read zone (first antenna when there is one)."""
        override = json.loads(self.cfg.reader_positions) if self.cfg.reader_positions else {}
        if junction_id in override:
            x, y = override[junction_id]["x"], override[junction_id]["y"]
        else:
            x, y = self.junctions[junction_id]
        dx, dy = self.cfg.reader_offset_m
        return (x + dx, y + dy)

    def reader_id(self, junction_id: str) -> str:
        return f"RFID_J{int(junction_id[1:]):02d}_01"

    def _place_ghosts(self) -> list[dict]:
        """Stationary tags near each reader, placed by their own seeded RNG so
        enabling them does not depend on the vehicles."""
        ghosts = []
        for j_index, junction_id in enumerate(sorted(self.junctions)):
            x, y = self.reader_position(junction_id)
            for g in range(self.cfg.ghost_tags_per_junction):
                rng = random.Random(f"ghost:{self.seed}:{junction_id}:{g}")
                angle = rng.uniform(0.0, 2.0 * math.pi)
                ghosts.append({
                    "vehicle_id": f"GHOST_{junction_id}_{g + 1}",
                    "epc": f"E20000172211EE{j_index + 1:02X}{g + 1:04X}",
                    "x": x + self.cfg.ghost_distance_m * math.cos(angle),
                    "y": y + self.cfg.ghost_distance_m * math.sin(angle),
                    "speed_kmh": 0.0,
                })
        return ghosts

    # ---------------- inventory ----------------

    def step(self, timestamp_sim: float, frame: int,
             vehicles: Iterable[dict]) -> tuple[list[dict], list[dict]]:
        """Run one inventory round at every reader and emit due reports.

        ``vehicles`` items: ``{vehicle_id, epc, x, y, speed_kmh}``.
        Returns ``(reports, ground_truth_rows)``.
        """
        vehicles = list(vehicles) + self.ghosts
        reports: list[dict] = []
        truth: list[dict] = []

        for junction_id in sorted(self.junctions):
            antennas = [a for a in self.antennas if a["junction"] == junction_id]

            def field_of(antenna):
                return [(vehicle, math.hypot(float(vehicle["x"]) - antenna["x"],
                                             float(vehicle["y"]) - antenna["y"]))
                        for vehicle in vehicles
                        if math.hypot(float(vehicle["x"]) - antenna["x"],
                                      float(vehicle["y"]) - antenna["y"]) <= self.cfg.cross_read_radius_m]

            fields_by_antenna = [field_of(antenna) for antenna in antennas]

            # Pass bookkeeping per JUNCTION (all antennas together). A missed pass
            # means the junction decodes NOTHING from that tag from the moment it
            # enters the field until it leaves.
            present = {str(vehicle["epc"]) for in_field in fields_by_antenna for vehicle, _ in in_field}
            for epc in sorted(present - self.junction_present[junction_id]):      # entered the field
                key = (junction_id, epc)
                if key in self.missed_pass:
                    self.missed_pass.discard(key)
                    self.suppressed.add(key)
                elif self.cfg.pass_miss_prob > 0.0 and self.rng.random() < self.cfg.pass_miss_prob:
                    self.suppressed.add(key)
            for key in [key for key in self.suppressed
                        if key[0] == junction_id and key[1] not in present]:
                self.suppressed.discard(key)                      # left: the pass is over
            self.junction_present[junction_id] = present

            for antenna, in_field in zip(antennas, fields_by_antenna):
                state = self.readers[antenna["reader_id"]]
                if state.interval_start is None:
                    state.interval_start = timestamp_sim
                state.present = {str(vehicle["epc"]) for vehicle, _ in in_field}

                # tags competing for this round: everything inside the wide
                # (cross-read) radius, whether or not it wins.
                tags_in_field = max(1, len(in_field))

                for vehicle, distance in in_field:
                    if (junction_id, str(vehicle["epc"])) in self.suppressed:
                        continue
                    speed = float(vehicle.get("speed_kmh", 0.0))
                    rssi = sample_rssi_dbm(distance, self.rng, self.cfg)
                    probability = read_probability(rssi, speed, tags_in_field, self.cfg)
                    # "inside" = within the nominal read zone. Beyond it, a read can
                    # only happen as an opt-in cross-read from a neighbouring lane.
                    inside = distance <= nominal_range_m(self.cfg)
                    if not inside and not self.cfg.cross_read_enabled:
                        continue
                    if probability <= 0.0:
                        continue
                    if self.rng.random() > probability:
                        continue
                    if not inside:
                        # Optional cross-read from a neighbouring lane.
                        if self.rng.random() > self.cfg.cross_read_probability:
                            continue

                    observation = state.observations.get(str(vehicle["epc"]))
                    if observation is None:
                        observation = TagObservation(
                            vehicle_id=str(vehicle["vehicle_id"]),
                            epc=str(vehicle["epc"]),
                            peak_rssi=rssi,
                            count=0,
                            first_seen_ts=timestamp_sim,
                            last_seen_ts=timestamp_sim,
                            last_distance_m=distance,
                            last_speed_kmh=speed,
                            nearby=not inside,
                        )
                        state.observations[str(vehicle["epc"])] = observation
                    observation.count += 1
                    observation.peak_rssi = max(observation.peak_rssi, rssi)
                    observation.last_seen_ts = timestamp_sim
                    observation.last_distance_m = distance
                    observation.last_speed_kmh = speed

                # ---- interval boundary: emit one report per tag seen ----
                if timestamp_sim - state.interval_start >= self.cfg.report_interval_s:
                    offset = self.clock_offsets.get(junction_id, 0.0)
                    for observation in list(state.observations.values()):
                        state.seq += 1
                        report = {
                            "type": "rfid_reading",
                            "schema": SCHEMA_V2,
                            "run_id": self.run_id,
                            "seq": state.seq,
                            "reader_id": antenna["reader_id"],
                            "junction_id": junction_id,
                            "antenna_id": antenna["antenna_id"],
                            "epc": observation.epc,
                            "rssi_dbm": round(observation.peak_rssi, 2),
                            "tag_seen_count": observation.count,
                            "first_seen_ts": round(observation.first_seen_ts + offset, 6),
                            "last_seen_ts": round(observation.last_seen_ts + offset, 6),
                            "timestamp_sim": round(timestamp_sim + offset, 6),
                            "frame": int(frame),
                        }
                        reports.append(report)
                        truth.append({
                            "reader_id": report["reader_id"],
                            "seq": report["seq"],
                            "epc": observation.epc,
                            "vehicle_id": observation.vehicle_id,
                            "true_distance_m": round(observation.last_distance_m, 6),
                            "speed_kmh": round(observation.last_speed_kmh, 6),
                            "peak_rssi_dbm": round(observation.peak_rssi, 4),
                            "tag_seen_count": observation.count,
                            "nearby_cross_read": int(observation.nearby),
                        })
                        if (self.cfg.duplicate_report_enabled
                                and self.rng.random() < self.cfg.duplicate_report_probability):
                            # Same seq, sent twice: the backend must dedupe it.
                            reports.append(dict(report))
                    state.observations.clear()
                    state.interval_start = timestamp_sim

        return reports, truth

    # ---------------- optional fault injection ----------------

    def miss_next_pass(self, junction_id: str, epc: str) -> None:
        """Miss this tag's whole NEXT pass at this reader (entry to exit).

        Used by the scenario tests ("a missed RFID pass must produce no
        sighting and no error"). If the tag is already in the field, the pass
        that follows its next entry is missed.
        """
        self.missed_pass.add((junction_id, str(epc)))


# ============================================================
# CSV / JSONL OUTPUT
# ============================================================

REPORT_FIELDS = [
    "type", "schema", "run_id", "seq", "reader_id", "junction_id", "antenna_id",
    "epc", "rssi_dbm", "tag_seen_count", "first_seen_ts", "last_seen_ts",
    "timestamp_sim", "frame",
]
GROUND_TRUTH_FIELDS = [
    "reader_id", "seq", "epc", "vehicle_id", "true_distance_m", "speed_kmh",
    "peak_rssi_dbm", "tag_seen_count", "nearby_cross_read",
]


class CsvSink:
    """Minimal append-and-flush CSV writer (no pandas, no csv dict caching)."""

    def __init__(self, path: str | Path, fields: Sequence[str]):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fields = list(fields)
        self._handle = self.path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._handle, fieldnames=self.fields,
                                      extrasaction="ignore")
        self._writer.writeheader()

    def write(self, row: dict) -> None:
        self._writer.writerow({key: row.get(key) for key in self.fields})
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


# ============================================================
# OFFLINE REPLAY
# ============================================================

def read_gps_csv(path: str | Path) -> dict[float, list[dict]]:
    """Group Member 1's gps_raw_readings.csv rows by timestamp_sim.

    Columns used: timestamp_sim, frame, vehicle_id, epc, world_x, world_y,
    speed_kmh. Rows without a timestamp or world position are skipped.
    """
    frames: dict[float, list[dict]] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                timestamp = float(row["timestamp_sim"])
                x = float(row["world_x"])
                y = float(row["world_y"])
            except (KeyError, TypeError, ValueError):
                continue
            frames.setdefault(timestamp, []).append({
                "vehicle_id": row.get("vehicle_id") or "?",
                "epc": row.get("epc") or "",
                "x": x,
                "y": y,
                "speed_kmh": float(row.get("speed_kmh") or 0.0),
            })
    for timestamp, vehicles in frames.items():
        frames[timestamp] = [v for v in vehicles if v["epc"]]
    return dict(sorted(frames.items()))


def frames_from_gps(timestamp: float, vehicles: list[dict], index: int) -> tuple[float, int]:
    return timestamp, index


def replay_gps_csv(gps_path: str | Path, cfg: RfidConfig | None = None,
                   seed: int | None = None) -> tuple[list[dict], list[dict]]:
    """Drive the reader model from a recorded GPS CSV (works with no CARLA)."""
    model = RfidReaderModel(cfg=cfg, seed=seed)
    reports: list[dict] = []
    truth: list[dict] = []
    for index, (timestamp, vehicles) in enumerate(read_gps_csv(gps_path).items()):
        step_reports, step_truth = model.step(timestamp, index, vehicles)
        reports.extend(step_reports)
        truth.extend(step_truth)
    return reports, truth


def replay_trajectories(timestamps: Sequence[float], positions: dict[str, list[tuple[float, float]]],
                        speeds: dict[str, list[float]] | None = None,
                        epcs: dict[str, str] | None = None,
                        cfg: RfidConfig | None = None,
                        seed: int | None = None) -> tuple[list[dict], list[dict]]:
    """Drive the reader model from synthetic trajectories.

    ``positions[vehicle_id][i]`` is the world (x, y) at ``timestamps[i]``.
    """
    model = RfidReaderModel(cfg=cfg, seed=seed)
    reports: list[dict] = []
    truth: list[dict] = []
    for index, timestamp in enumerate(timestamps):
        vehicles = []
        for vehicle_id, path in positions.items():
            if index >= len(path):
                continue
            x, y = path[index]
            vehicles.append({
                "vehicle_id": vehicle_id,
                "epc": (epcs or {}).get(vehicle_id, f"EPC_{vehicle_id}"),
                "x": x,
                "y": y,
                "speed_kmh": (speeds or {}).get(vehicle_id, [0.0] * len(timestamps))[index]
                if speeds else 0.0,
            })
        step_reports, step_truth = model.step(timestamp, index, vehicles)
        reports.extend(step_reports)
        truth.extend(step_truth)
    return reports, truth


# ============================================================
# LEGACY FORMAT (for the "flag off" path and the comparison)
# ============================================================

def legacy_read_message(timestamp_sim: float, frame: int, event_id: str, junction_id: str,
                        reader_id: str, vehicle_id: str, plate_number: str, epc: str,
                        distance_m: float, speed_kmh: float) -> dict:
    """The pre-existing per-read rfid_reading message, byte-for-byte fields."""
    confidence = max(0.50, 1.0 - (distance_m / 18.0) * 0.25)
    return {
        "type": "rfid_reading",
        "timestamp_sim": timestamp_sim,
        "frame": frame,
        "event_id": event_id,
        "junction_id": junction_id,
        "reader_id": reader_id,
        "vehicle_id": vehicle_id,
        "plate_number": plate_number,
        "epc": epc,
        "distance_m": distance_m,
        "speed_kmh": speed_kmh,
        "confidence": confidence,
        "status": "READ",
    }


def to_json_line(message: dict) -> str:
    return json.dumps(message, separators=(",", ":"))


__all__ = [
    "SCHEMA_V2", "RFID_REPORTS_CSV", "RFID_GROUND_TRUTH_CSV",
    "JUNCTION_WORLD", "RfidConfig", "DEFAULT_CONFIG", "TagObservation",
    "RfidReaderModel", "CsvSink", "REPORT_FIELDS", "GROUND_TRUTH_FIELDS",
    "mean_rssi_dbm", "nominal_range_m", "sample_rssi_dbm", "read_probability",
    "camera_coverage_fraction", "read_gps_csv", "replay_gps_csv",
    "replay_trajectories", "legacy_read_message", "to_json_line",
]
