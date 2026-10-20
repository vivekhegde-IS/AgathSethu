"""Part 2 tests for RFID -> camera plate cross-verification.

Run from the repository root:  python -m pytest tests/test_part2_rfid.py -q

Unit tests exercise each pure stage. The scenario tests drive the whole service
in-process with the SAME generators the feed simulator uses (the shared
``rfid_reader_model`` plus the demo trajectories), a fake DB writer, an inline
executor and a mocked ANPR adapter, so the full ladder
report -> incident -> snapshot -> hit -> ANPR -> status is deterministic and
runs without CARLA, Postgres or the model. One integration test at the bottom
loads the real ANPR model through the adapter and is skipped if it is missing.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
import sys
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "member3" / "backend"))

from app.services.rfid.buffer import ReadBuffer  # noqa: E402
from app.services.rfid.config import (  # noqa: E402
    ROLE_INVOLVED,
    ROLE_NEARBY,
    STATUS_NO_PLATE_VISIBLE,
    STATUS_NOT_CONFIRMED,
    STATUS_PLATE_TOO_SMALL,
    STATUS_PROBABLE_MATCH,
    STATUS_VISION_CONFIRMED,
    UNREGISTERED_TAG,
    RfidFeatureConfig,
)
from app.services.rfid.evidence import EvidenceStore  # noqa: E402
from app.services.rfid.incidents import (  # noqa: E402
    IncidentAssembler,
    RunTracker,
    nearest_junction,
    parse_alert,
)
from app.services.rfid.normalize import (  # noqa: E402
    SCHEMA_LEGACY,
    SCHEMA_V2,
    SequenceTracker,
    parse_message,
)
from app.services.rfid.registry import (  # noqa: E402
    VehicleRegistry,
    epc_for,
    normalize_plate,
    seed_rows,
)
from app.services.rfid.service import RfidCrossVerification  # noqa: E402
from app.services.rfid.sightings import (  # noqa: E402
    IGNORE_CRASH_JUNCTION,
    IGNORE_NOT_WATCHLISTED,
    IGNORE_PRE_CRASH,
    SightingTracker,
)
from app.services.rfid.store import Persistence, StoreCounters, retryable  # noqa: E402
from app.services.rfid.plate_rules import apply_rules, check_text, gate  # noqa: E402
from app.services.rfid.vision import (  # noqa: E402
    FrameReads,
    FrameRef,
    FrameRing,
    Suspect,
    cluster_reads,
    edit_distance,
    fuse,
    owner_of,
    parse_vehicle_boxes,
    should_stop_early,
)

EPC = {vehicle: epc_for(vehicle) for vehicle in "ABCDEFGH"}
PLATE = {row["sim_vehicle_id"]: row["plate_norm"] for row in seed_rows()}
UNKNOWN_EPC = "E200001722110199A0FF"


# =====================================================================
# helpers and fakes
# =====================================================================

def make_cfg(**overrides) -> RfidFeatureConfig:
    return RfidFeatureConfig(**{**RfidFeatureConfig().as_dict(), **overrides})


def v2(epc, junction="J02", first=30.0, last=None, seq=None, run_id="run-A",
       rssi=-40.0, count=3, emitted=None):
    last = first if last is None else last
    message = {
        "type": "rfid_reading", "schema": SCHEMA_V2, "run_id": run_id,
        "reader_id": f"RFID_{junction}_01", "junction_id": junction, "antenna_id": "1",
        "epc": epc, "rssi_dbm": rssi, "tag_seen_count": count,
        "first_seen_ts": first, "last_seen_ts": last,
        "timestamp_sim": last + 0.3 if emitted is None else emitted, "frame": int(last * 20),
    }
    if seq is not None:
        message["seq"] = seq
    return message


def read(epc, junction="J02", first=30.0, last=None, seq=None, run_id="run-A", **kw):
    return parse_message(v2(epc, junction, first, last, seq, run_id, **kw))


def physics_alert(ts=40.0, frame=800, a="A", b="B", junction="J01", alert_id=None):
    from app.services.rfid.config import JUNCTION_WORLD

    x, y = JUNCTION_WORLD[junction]
    return {
        "type": "crash_alert", "alert_id": alert_id or f"PHY-{frame}",
        "status": "COLLISION_EVENT_CONFIRMED_CARLA_PHYSICS", "timestamp_sim": ts,
        "frame": frame, "vehicle_id": a, "plate_number": PLATE[a],
        "collision_partner": b, "collision_partner_plate": PLATE[b],
        "world_location": {"x": x, "y": y, "z": 0.0},
    }


def imu_alert(ts=40.2, frame=801, vehicle="A", partner="B", junction="J01", alert_id=None,
              epc=None):
    message = physics_alert(ts, frame, vehicle, partner, junction)
    message.update({
        "alert_id": alert_id or f"MM-{frame:09d}",
        "status": "COLLISION_EVENT_CONFIRMED_IMU_GPS",
        "epc": epc or EPC[vehicle], "gps": {"lat": 12.93, "lon": 77.62},
    })
    return message


class FakeStore:
    """Captures what would be written to Postgres."""

    def __init__(self):
        self.rows: list[tuple[str, dict]] = []
        self.counters = StoreCounters()

    def submit(self, kind, payload):
        self.rows.append((kind, dict(payload)))
        return True

    def of(self, kind) -> list[dict]:
        return [payload for row_kind, payload in self.rows if row_kind == kind]


class InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)

    def shutdown(self, wait=False):
        pass


def frame_bytes(plates: list[tuple]) -> bytes:
    """A fake 'JPEG' whose payload lists the plates the fake ANPR will see:
    (plate, conf) or (plate, conf, slot). The slot places the plate box (see
    slot_plate_box); without one every plate sits at the same legacy box."""
    def item(entry):
        text = f"{entry[0]}:{entry[1]}"
        return text + (f":{entry[2]}" if len(entry) > 2 else "")
    return ("|".join(item(entry) for entry in plates) or "EMPTY").encode()


FAKE_FRAME_SHAPE = (120, 640, 3)


def slot_plate_box(slot: int) -> tuple:
    """Plate box of the vehicle drawn in image slot ``slot`` (60x15 px)."""
    return (30 + 150 * slot, 70, 90 + 150 * slot, 85)


def slot_vehicle_box(slot: int) -> list:
    """Projected image box of the vehicle in slot ``slot`` (holds its plate)."""
    return [10 + 150 * slot, 20, 120 + 150 * slot, 100]


class FakeAnpr:
    """Blind mock of anpr_adapter: it only sees what the frame contains.

    ``decode`` is the service's decoder hook; it remembers which frame is being
    looked at so ``detect_and_read`` can return exactly its plates.
    """

    def __init__(self):
        self.current = b""
        self.calls = 0
        self.seen_kwargs: list[dict] = []

    def decode(self, jpeg: bytes):
        self.current = jpeg
        return np.zeros(FAKE_FRAME_SHAPE, np.uint8)

    def detect_and_read(self, frame, **kwargs):
        self.calls += 1
        self.seen_kwargs.append(kwargs)
        out = []
        for item in self.current.decode().split("|"):
            if ":" not in item:
                continue
            parts = item.split(":")
            plate, conf = parts[0], parts[1]
            box = slot_plate_box(int(parts[2])) if len(parts) > 2 else (10, 10, 60, 30)
            # same attributes as anpr_adapter.PlateRead
            out.append(SimpleNamespace(box=box, plate_text=plate, plate_norm=plate,
                                       raw_ocr=plate, det_confidence=0.8,
                                       ocr_confidence=float(conf), valid=True,
                                       per_char=[[ch, float(conf)] for ch in plate]))
        return out

    def status(self):
        return {"backend": "fake", "imgsz": 512,
                "config": {"model_path": "models/number_plate/number_plate_detector.pt",
                           "mode": "tiled", "det_conf": 0.25, "iou": 0.45}}


def make_service(tmp_path, adapter=None, **cfg_overrides):
    cfg = make_cfg(evidence_dir=str(tmp_path / "evidence"), **cfg_overrides)
    store, events = FakeStore(), []
    fake = adapter
    service = RfidCrossVerification(
        cfg=cfg, registry=VehicleRegistry.from_seed(), persistence=store,
        broadcaster=events.append, adapter=fake,
        decoder=(fake.decode if fake is not None else None),
        evidence=EvidenceStore(root=tmp_path / "evidence", cfg=cfg),
        executor=InlineExecutor())
    return service, store, events


# =====================================================================
# plate normalization + registry
# =====================================================================

class TestPlatesAndRegistry:
    def test_normalize(self):
        assert normalize_plate("ka 01-at 4521") == "KA01AT4521"
        assert normalize_plate("  mh12 BR.7814 ") == "MH12BR7814"
        assert not normalize_plate("")
        assert not normalize_plate(None)

    def test_epc_formula_matches_member1(self):
        # E2000017221101 + index(2 hex) + (0xA0B0 + index)(4 hex), index 1-based in A-H
        assert epc_for("A") == "E200001722110101A0B1"
        assert epc_for("B") == "E200001722110102A0B2"
        assert epc_for("H") == "E200001722110108A0B8"
        rows = seed_rows()
        assert [row["sim_vehicle_id"] for row in rows] == list("ABCDEFGH")
        assert {row["plate_norm"] for row in rows} == {
            "KA01AT4521", "MH12BR7814", "TN09CK2365", "KL07DL9182",
            "DL03EN6047", "GJ05FP3419", "AP16GQ8273", "TG08HR5196"}
        assert rows[1]["state_code"] == "MH"

    def test_lookup(self):
        registry = VehicleRegistry.from_seed()
        assert registry.lookup_epc(EPC["A"]).plate_norm == "KA01AT4521"
        assert registry.lookup_epc(EPC["A"].lower()).plate_norm == "KA01AT4521"
        assert registry.lookup_plate("mh 12 br 7814").epc == EPC["B"]

    def test_unknown_epc_is_unregistered_never_invented(self):
        registry = VehicleRegistry.from_seed()
        assert registry.lookup_epc(UNKNOWN_EPC) is None
        entry, warning = registry.resolve(UNKNOWN_EPC)
        assert entry.plate_norm is None and entry.registered is False
        assert entry.status == UNREGISTERED_TAG
        assert UNREGISTERED_TAG in warning

    def test_message_plate_never_trusted(self):
        registry = VehicleRegistry.from_seed()
        assert "registry wins" in registry.check_message_plate(EPC["A"], "MH 12 BR 7814")
        assert registry.check_message_plate(EPC["A"], "KA 01 AT 4521") is None


# =====================================================================
# parsing both RFID formats
# =====================================================================

class TestParse:
    def test_v2_tag_report(self):
        rfid = parse_message(v2(EPC["B"], first=30.0, last=30.4, seq=5, emitted=30.5))
        assert rfid.schema == SCHEMA_V2 and rfid.is_v2
        assert (rfid.first_seen_ts, rfid.last_seen_ts, rfid.count) == (30.0, 30.4, 3)
        assert rfid.seq == 5 and rfid.run_id == "run-A" and rfid.peak_rssi == -40.0
        assert rfid.debug_plate is None and rfid.debug_vehicle_id is None

    def test_v2_without_event_window_is_rejected(self):
        message = v2(EPC["B"])
        del message["first_seen_ts"]
        assert parse_message(message) is None

    def test_v2_swapped_window_is_repaired_with_warning(self):
        rfid = parse_message(v2(EPC["B"], first=31.0, last=30.0))
        assert (rfid.first_seen_ts, rfid.last_seen_ts) == (30.0, 31.0)
        assert rfid.warnings

    def test_legacy_per_read(self):
        rfid = parse_message({
            "type": "rfid_reading", "timestamp_sim": 12.5, "frame": 250,
            "event_id": "MM-000000001", "junction_id": "J02", "reader_id": "RFID_J02_01",
            "vehicle_id": "B", "plate_number": "MH 12 BR 7814", "epc": EPC["B"],
            "distance_m": 6.0, "speed_kmh": 40.0, "confidence": 0.9, "status": "READ"})
        assert rfid.schema == SCHEMA_LEGACY
        assert rfid.first_seen_ts == rfid.last_seen_ts == 12.5 and rfid.count == 1
        # ground truth kept for debugging only
        assert rfid.debug_vehicle_id == "B" and rfid.debug_distance_m == 6.0
        assert rfid.seq is None and rfid.peak_rssi is None

    def test_junction_forms_and_rejects(self):
        assert parse_message({**v2(EPC["A"]), "junction_id": "2"}).junction_id == "J02"
        assert parse_message({**v2(EPC["A"]), "junction_id": "j3"}).junction_id == "J03"
        assert parse_message({**v2(EPC["A"]), "junction_id": "north"}) is None
        assert parse_message({**v2(EPC["A"]), "epc": ""}) is None
        assert parse_message({"type": "camera_frame"}) is None
        assert parse_message("not a dict") is None


# =====================================================================
# sequence gaps, duplicates, coalescing, windows
# =====================================================================

class TestSequenceAndBuffer:
    def test_gap_and_duplicate_detection(self):
        tracker = SequenceTracker()
        assert tracker.observe(read(EPC["B"], seq=1)) == ("new", 0)
        assert tracker.observe(read(EPC["B"], seq=2)) == ("new", 0)
        assert tracker.observe(read(EPC["B"], seq=2)) == ("duplicate", 0)
        assert tracker.observe(read(EPC["B"], seq=6)) == ("gap", 3)
        assert tracker.observe(read(EPC["B"], seq=4)) == ("new", 0)   # late, not a gap
        # the same seq in a DIFFERENT run is not a duplicate
        assert tracker.observe(read(EPC["B"], seq=2, run_id="run-B"))[0] != "duplicate"
        counters = tracker.counters()
        assert counters["duplicates_ignored"] == 1
        assert counters["missing_reports"] == {"RFID_J02_01": 3}
        assert counters["gap_events"] == {"RFID_J02_01": 1}

    def test_gaps_are_per_reader(self):
        tracker = SequenceTracker()
        tracker.observe(read(EPC["B"], junction="J02", seq=1))
        tracker.observe(read(EPC["B"], junction="J03", seq=10))
        assert tracker.observe(read(EPC["B"], junction="J02", seq=2)) == ("new", 0)
        assert tracker.observe(read(EPC["B"], junction="J03", seq=11)) == ("new", 0)

    def test_duplicate_is_never_stored_twice(self):
        buffer = ReadBuffer()
        assert buffer.add(read(EPC["B"], seq=1)) == "new"
        assert buffer.add(read(EPC["B"], seq=1)) == "duplicate"
        assert len(buffer.window("J02", 0, 100)) == 1

    def test_coalesce_per_epc_with_registry_plate_and_role(self):
        buffer = ReadBuffer()
        registry = VehicleRegistry.from_seed()
        for seq, (epc, first, last, rssi, count) in enumerate([
                (EPC["A"], 38.0, 38.4, -35.0, 4), (EPC["A"], 38.5, 38.9, -30.0, 2),
                (EPC["E"], 39.0, 39.2, -50.0, 1), (UNKNOWN_EPC, 39.5, 39.6, -52.0, 1)]):
            buffer.add(read(epc, junction="J01", first=first, last=last, seq=seq,
                            rssi=rssi, count=count))
        rows = {row.epc: row for row in buffer.coalesce(buffer.window("J01", 0, 100),
                                                        registry, {EPC["A"]})}
        a = rows[EPC["A"]]
        assert (a.first_seen_ts, a.last_seen_ts, a.report_count, a.tag_seen_count) == \
            (38.0, 38.9, 2, 6)
        assert a.peak_rssi_dbm == -30.0 and a.role == ROLE_INVOLVED
        assert a.plate_norm == "KA01AT4521"
        assert rows[EPC["E"]].role == ROLE_NEARBY
        assert rows[UNKNOWN_EPC].plate_norm is None       # never invented

    def test_windows_use_event_time_not_emission_time(self):
        buffer = ReadBuffer()
        # event at 9.8 s, emitted (timestamp_sim) at 10.3 s
        buffer.add(read(EPC["B"], first=9.5, last=9.8, seq=1, emitted=10.3))
        assert buffer.window("J02", 10.0, 20.0) == []
        assert len(buffer.window("J02", 9.0, 9.9)) == 1

    def test_window_bounds_inclusive(self):
        buffer = ReadBuffer()
        for seq, t in enumerate((9.99, 10.0, 70.0, 70.01)):
            buffer.add(read(EPC["B"], first=t, seq=seq))
        times = [r.last_seen_ts for r in buffer.window("J02", 10.0, 70.0)]
        assert times == [10.0, 70.0]

    def test_out_of_order_arrival_stays_sorted_and_is_consumable(self):
        buffer = ReadBuffer()
        buffer.add(read(EPC["A"], first=30.4, seq=1))
        buffer.add(read(EPC["B"], first=30.1, seq=2))    # older event, arrives later
        assert [r.last_seen_ts for r in buffer.window("J02", 30.0, 31.0)] == [30.1, 30.4]
        first_cursor = 1
        assert [r.epc for r in buffer.since(first_cursor)] == [EPC["B"]]

    def test_prune_keeps_the_window(self):
        buffer = ReadBuffer(window_s=120.0)
        for seq, t in enumerate((1.0, 50.0, 130.0)):
            buffer.add(read(EPC["B"], first=t, seq=seq))
        buffer.prune()
        assert [r.last_seen_ts for r in buffer.window("J02", 0, 1e9)] == [50.0, 130.0]

    def test_run_reset_detection(self):
        buffer = ReadBuffer()
        buffer.add(read(EPC["B"], first=80.0, seq=1, run_id="run-A"))
        assert buffer.is_new_run(read(EPC["B"], first=81.0, seq=2, run_id="run-A"), 5.0) is None
        assert "run_id" in buffer.is_new_run(read(EPC["B"], first=81.0, run_id="run-B"), 5.0)
        assert "back" in buffer.is_new_run(read(EPC["B"], first=2.0, run_id="run-A"), 5.0)
        buffer.reset_run("test")
        assert buffer.window("J02", 0, 1e9) == [] and buffer.epoch == 1


# =====================================================================
# crash alerts -> incidents: idempotency and run reset
# =====================================================================

class TestIncidents:
    def test_parse_alerts(self):
        physics = parse_alert(physics_alert())
        assert physics.is_physics and physics.alert_id == "PHY-800"
        imu = parse_alert(imu_alert())
        assert imu.source == "imu_gps" and imu.epc == EPC["A"] and imu.gps["lat"] == 12.93
        assert parse_alert({"type": "crash_alert"}) is None
        assert parse_alert({"type": "rfid_reading", "alert_id": "x"}) is None

    def test_nearest_junction(self):
        assert nearest_junction({"x": -41.0, "y": 80.0})[0] == "J02"
        assert nearest_junction(None) == (None, None)

    def test_one_incident_per_collision_all_alerts_linked(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        verdict, incident = assembler.handle_alert(parse_alert(physics_alert()))
        assert verdict == "created"
        assert incident.crash_junction == "J01"
        assert incident.involved_plates == {"KA01AT4521", "MH12BR7814"}
        assert incident.involved_epcs == {EPC["A"], EPC["B"]}
        for alert in (imu_alert(40.2, 801, "A", "B"), imu_alert(40.4, 802, "B", "A")):
            assert assembler.handle_alert(parse_alert(alert))[0] == "merged"
        assert incident.alert_ids == ["PHY-800", "MM-000000801", "MM-000000802"]
        assert assembler.created == 1

    def test_retried_alert_is_idempotent(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        assembler.handle_alert(parse_alert(physics_alert()))
        for _ in range(3):
            assert assembler.handle_alert(parse_alert(physics_alert()))[0] == "duplicate"
        assert assembler.created == 1 and assembler.duplicates == 3

    def test_far_apart_collision_is_a_new_incident(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        assembler.handle_alert(parse_alert(physics_alert(ts=40.0)))
        verdict, _ = assembler.handle_alert(parse_alert(
            physics_alert(ts=90.0, frame=1800, a="C", b="D", junction="J03")))
        assert verdict == "created" and assembler.created == 2

    def test_same_alert_id_in_two_runs(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        _, first = assembler.handle_alert(parse_alert(physics_alert(ts=40.0)))
        # the next run replays the same alert ids; sim time went backwards
        assembler.handle_alert(parse_alert(imu_alert(ts=95.0, frame=1900, vehicle="C",
                                                     partner="D")))
        verdict, second = assembler.handle_alert(parse_alert(physics_alert(ts=40.0)))
        assert verdict == "created"
        assert second.run_id != first.run_id
        assert second.dedupe_key() != first.dedupe_key()

    def test_run_tracker_rules(self):
        runs = RunTracker(make_cfg(), session="S1")
        assert runs.resolve(parse_alert(physics_alert(ts=10.0)))[1] == "first alert"
        assert runs.run_id == "run-S1-0001"
        assert runs.resolve(parse_alert(physics_alert(ts=8.0)))[1] is None     # 2 s back: same run
        run_id, reason = runs.resolve(parse_alert(physics_alert(ts=1.0)))      # >5 s back
        assert reason and "went back" in reason and run_id == "run-S1-0002"
        runs.request_new_run("rfid run_id changed", "uuid-run-3")
        assert runs.resolve(parse_alert(physics_alert(ts=2.0))) == ("uuid-run-3",
                                                                   "rfid run_id changed")
        message = {**physics_alert(ts=3.0), "run_id": "explicit"}
        assert runs.resolve(parse_alert(message))[0] == "explicit"

    def test_alert_epc_cross_check(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        _, incident = assembler.handle_alert(parse_alert(imu_alert(epc=EPC["C"])))
        assert any("registry wins" in warning for warning in incident.warnings)
        # a disagreeing epc is a cross-check failure, never an extra vehicle
        assert incident.involved_epcs == {EPC["A"], EPC["B"]}

    def test_alert_epc_stands_in_when_no_plate(self):
        assembler = IncidentAssembler(VehicleRegistry.from_seed())
        message = imu_alert()
        message["plate_number"] = None
        _, incident = assembler.handle_alert(parse_alert(message))
        assert incident.involved_epcs == {EPC["A"], EPC["B"]}


# =====================================================================
# watchlist and sightings
# =====================================================================

def incident_at_j01(crash_ts=40.0):
    assembler = IncidentAssembler(VehicleRegistry.from_seed())
    return assembler.handle_alert(parse_alert(physics_alert(ts=crash_ts)))[1]


class TestSightings:
    def test_watchlist_ignores_other_tags_pre_crash_and_crash_junction(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        events = tracker.ingest(incident, [
            read(EPC["C"], "J02", 45.0),        # not watchlisted
            read(EPC["B"], "J02", 39.0),        # before the crash
            read(EPC["B"], "J01", 45.0),        # at the crash junction
        ])
        assert events == []
        assert tracker.ignored == {IGNORE_NOT_WATCHLISTED: 1, IGNORE_PRE_CRASH: 1,
                                   IGNORE_CRASH_JUNCTION: 1}

    def test_pre_crash_is_judged_on_event_time_not_emission(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        late_emitted = read(EPC["B"], "J02", first=39.5, last=39.9, emitted=40.4)
        assert tracker.ingest(incident, [late_emitted]) == []
        assert tracker.ignored == {IGNORE_PRE_CRASH: 1}

    def test_coalesce_into_one_sighting(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        events = tracker.ingest(incident, [read(EPC["B"], "J02", 55.0 + 0.5 * i, 55.4 + 0.5 * i,
                                                rssi=-50.0 + i) for i in range(4)])
        assert [kind for kind, _ in events] == ["opened", "updated", "updated", "updated"]
        sighting = events[0][1]
        assert (sighting.first_seen_ts, sighting.last_seen_ts) == (55.0, 56.9)
        assert sighting.report_count == 4 and sighting.tag_seen_count == 12
        assert sighting.peak_rssi_dbm == -47.0
        assert sighting.plate_norm == "MH12BR7814"

    def test_dropouts_merge_into_one_sighting(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        events = tracker.ingest(incident, [read(EPC["B"], "J02", 55.0),
                                           read(EPC["B"], "J02", 56.5),
                                           read(EPC["B"], "J02", 60.0)])     # 3.5 s drop-out
        assert [kind for kind, _ in events] == ["opened", "updated", "updated"]
        assert len(tracker.sightings) == 1

    def test_closed_unfinalized_sighting_reopens(self):
        tracker = SightingTracker(make_cfg(sighting_close_s=4.0, sighting_merge_s=20.0))
        incident = incident_at_j01()
        sighting = tracker.ingest(incident, [read(EPC["B"], "J03", 70.0)])[0][1]
        assert tracker.tick(75.0) == [sighting] and sighting.closed
        events = tracker.ingest(incident, [read(EPC["B"], "J03", 81.0)])   # 11 s later, same pass
        assert [kind for kind, _ in events] == ["reopened", "updated"]
        assert events[0][1] is sighting and not sighting.closed
        assert len(tracker.open_sightings()) == 1          # at most one per (incident, epc, junction)

    def test_after_finalization_a_return_is_a_new_sighting(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        first = tracker.ingest(incident, [read(EPC["B"], "J03", 70.0)])[0][1]
        tracker.tick(75.0)
        first.finalized = True
        events = tracker.ingest(incident, [read(EPC["B"], "J03", 80.0)])
        assert events[0][0] == "opened" and events[0][1] is not first

    def test_separate_sightings_per_junction(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        tracker.ingest(incident, [read(EPC["B"], "J02", 56.0), read(EPC["B"], "J03", 72.0)])
        assert sorted(s.junction_id for s in tracker.open_sightings()) == ["J02", "J03"]

    def test_tick_closes_quiet_and_overlong(self):
        tracker = SightingTracker(make_cfg(sighting_close_s=2.0, sighting_max_s=10.0))
        incident = incident_at_j01()
        tracker.ingest(incident, [read(EPC["B"], "J02", 56.0)])
        assert tracker.tick(57.5) == []
        assert len(tracker.tick(58.0)) == 1
        tracker.ingest(incident, [read(EPC["A"], "J03", 60.0 + i) for i in range(11)])
        closed = tracker.tick(70.0)
        assert len(closed) == 1 and closed[0].epc == EPC["A"]

    def test_notify_once(self):
        tracker = SightingTracker(make_cfg())
        incident = incident_at_j01()
        sighting = tracker.ingest(incident, [read(EPC["B"], "J02", 56.0)])[0][1]
        assert tracker.mark_notified(sighting) is True
        assert tracker.mark_notified(sighting) is False
        assert tracker.hits == 1

    def test_watch_nearby_flag(self):
        incident = incident_at_j01()
        incident.nearby_epcs = {EPC["E"]}
        assert SightingTracker(make_cfg()).ingest(incident, [read(EPC["E"], "J02", 50.0)]) == []
        nearby = SightingTracker(make_cfg(), watch_nearby=True)
        assert nearby.ingest(incident, [read(EPC["E"], "J02", 50.0)])[0][0] == "opened"
        # never a tag that was not at the crash
        assert nearby.ingest(incident, [read(EPC["H"], "J02", 50.0)]) == []


# =====================================================================
# vision status ladder
# =====================================================================

def frame_reads(*frames, junction="J02", t0=56.0):
    """frames: per frame a list of (raw OCR text, confidence[, vehicle slot]).

    Every read goes through the REAL plate rules (apply_rules); the vehicle slot
    (default: list position) decides where the plate box sits, so the same slot
    in consecutive frames is box-continuous.
    """
    out = []
    for index, plates in enumerate(frames):
        ref = FrameRef(f"CAM_{junction}_01", junction, t0 + 0.2 * index, b"", 1000 + index)
        rules = []
        for position, item in enumerate(plates):
            text, conf = item[0], item[1]
            slot = item[2] if len(item) > 2 else position
            box = (100 + 300 * slot, 400, 180 + 300 * slot, 420)          # 80x20 px plate
            rules.append(apply_rules({"box": box, "det_confidence": 0.8, "raw_ocr": text,
                                      "ocr_variants": [{"text": text,
                                                        "confidences": [conf] * len(text),
                                                        "variant": "single"}]},
                                     make_cfg()))
        out.append(FrameReads(ref, rules))
    return out


def gated_frame(width_px=12.0, t=56.0):
    ref = FrameRef("CAM_J03_01", "J03", t, b"", 2000)
    rule = apply_rules({"box": (500, 400, 500 + width_px, 405), "det_confidence": 0.7,
                        "raw_ocr": None}, make_cfg())
    return FrameReads(ref, [rule])


class TestPlateRules:
    JUNK = ["39E381", "C0356847", "CHR78", "H8918", "1F181", "AEHEPERTB", "RTEFAR", "O04TDT814"]

    @pytest.mark.parametrize("junk", JUNK)
    def test_junk_never_becomes_a_plate(self, junk):
        checked = check_text(junk, [0.8] * len(junk))
        assert checked["valid"] is False and checked["corrected"] is None
        assert checked["reasons"]
        # ...and is never displayed as a plate seen
        result = fuse(frame_reads([(junk, 0.8)], [(junk, 0.8)]), "MH12BR7814", make_cfg())
        assert result["plates_seen"] == [] and result["anpr_plate"] is None
        assert {r["raw"] for r in result["rejected_reads"]} == {junk}

    def test_format_and_position_fixes(self):
        checked = check_text("KA0IAT452I", [0.9] * 10)        # I in digit slots
        assert checked["valid"] and checked["corrected"] == "KA01AT4521"
        assert "POSITION_FIXED" in checked["reasons"] and not checked["state_corrected"]
        assert check_text("KA01A74521")["corrected"] == "KA01AT4521"   # 7 in a letter slot

    def test_invalid_state_is_never_guessed(self):
        # HH is not a state code: the read is rejected, never rewritten to MH
        checked = check_text("HH12BR7B14",
                             [0.38, 0.98, 0.97, 0.98, 0.44, 0.98, 0.9, 0.84, 0.99, 0.99])
        assert not checked["valid"] and checked["corrected"] is None
        assert checked["reasons"] == ["BAD_FORMAT"]
        # a confident, valid state is NOT rewritten
        assert check_text("KA01AT4521")["corrected"] == "KA01AT4521"

    def test_no_regional_prior(self):
        # 8 states on this feed: a valid code is never snapped to another one
        for plate in ("TN09CK2365", "KL07DL9182", "TG08HR5196", "GJ05FP3419"):
            assert check_text(plate, [0.9] * 10)["corrected"] == plate

    def test_extra_characters_rejected(self):
        checked = check_text("94360301ER128R7814")
        assert not checked["valid"] and checked["corrected"] is None
        assert set(checked["reasons"]) & {"EXTRA_CHARACTERS", "BAD_FORMAT"}

    def test_geometry_gating(self):
        cfg = make_cfg()
        assert gate((0, 0, 12, 4), 0.9, cfg) == "PLATE_TOO_SMALL"
        assert gate((0, 0, 60, 40), 0.9, cfg) == "BAD_ASPECT_RATIO"
        assert gate((0, 0, 60, 18), 0.1, cfg) == "LOW_DETECTION_CONFIDENCE"
        assert gate((0, 0, 75, 18), 0.6, cfg) is None
        rule = apply_rules({"box": (0, 0, 12, 4), "det_confidence": 0.9, "raw_ocr": "KA01AT4521",
                            "per_char": [[c, 0.9] for c in "KA01AT4521"]}, cfg)
        assert rule.gated == "PLATE_TOO_SMALL" and not rule.valid


class TestVision:
    def test_edit_distance(self):
        assert edit_distance("MH12BR7814", "MH12BR7814") == 0
        assert edit_distance("HH12BR7814", "MH12BR7814") == 1
        assert edit_distance("HH12BR7B14", "MH12BR7814") == 2
        assert edit_distance("MH12BR7814", "MH12BR781") == 1
        assert edit_distance(None, "AB") == 2

    def test_exact_match_confirmed_by_two_frames(self):
        result = fuse(frame_reads([("MH12BR7814", 0.7)], [("MH12BR7814", 0.72)]),
                      "MH12BR7814", make_cfg(), reference_ts=56.0)
        assert result["status"] == STATUS_VISION_CONFIRMED and not result["rule_assisted"]
        assert result["edit_distance"] == 0 and result["cluster_frames"] == 2
        assert result["anpr_state_name"] == "Maharashtra"
        assert should_stop_early(result, make_cfg())

    def test_one_frame_never_confirms(self):
        result = fuse(frame_reads([("MH12BR7814", 0.99)]), "MH12BR7814", make_cfg())
        assert result["status"] == STATUS_PROBABLE_MATCH

    def test_single_low_confidence_frame_is_only_probable(self):
        assert fuse(frame_reads([("MH12BR7814", 0.4)]), "MH12BR7814",
                    make_cfg())["status"] == STATUS_PROBABLE_MATCH
        assert fuse(frame_reads([("MH12BR7814", 0.7)], []), "MH12BR7814",
                    make_cfg())["status"] == STATUS_PROBABLE_MATCH

    def test_invalid_state_read_is_not_turned_into_the_registry_state(self):
        # HH12BR7814 / HH12BR7B14 (MH misread): the state is never swapped to MH,
        # so these reads attach no plate - and are never shown as MH12BR7814
        for raw in ("HH12BR7814", "HH12BR7B14"):
            result = fuse(frame_reads([(raw, 0.85)], [(raw, 0.85)]), "MH12BR7814", make_cfg())
            assert result["anpr_plate"] is None
            assert result["status"] == STATUS_NO_PLATE_VISIBLE
            assert {r["raw"] for r in result["rejected_reads"]} == {raw}

    def test_dl03en6047_never_becomes_dl83_or_rj83(self):
        from app.services.plate_validation import strict_plate

        assert strict_plate("DL03EN6047").plate == "DL03EN6047"
        # no backend 8->0 hack: a read 8 stays 8 (the overlay font is fixed instead)
        assert strict_plate("DL83EN6047").plate == "DL83EN6047"
        # a mangled state is rejected, never guessed into another state (RJ, ...)
        for raw in ("RL03EN6047", "DJ03EN6047", "BJ83FN6847", "0J03EN6047"):
            assert not strict_plate(raw).valid, raw
        # multi-frame: one slashed-zero misread among good reads still confirms...
        good = fuse(frame_reads([("DL03EN6047", 0.9)], [("DL03EN6047", 0.9)], [("DL83EN6047", 0.9)]),
                    "DL03EN6047", make_cfg())
        assert good["anpr_plate"] == "DL03EN6047" and good["status"] == STATUS_VISION_CONFIRMED
        # ...but disagreeing reads never do, and the plate is never RJ83FN6847
        split = fuse(frame_reads([("DL03EN6047", 0.9)], [("DL83EN6047", 0.9)]), "DL03EN6047", make_cfg())
        assert split["status"] != STATUS_VISION_CONFIRMED
        mostly_wrong = fuse(frame_reads([("DL83EN6047", 0.9)], [("DL83EN6047", 0.9)],
                                        [("RJ83FN6847", 0.6)]), "DL03EN6047", make_cfg())
        assert mostly_wrong["status"] != STATUS_VISION_CONFIRMED
        assert mostly_wrong["anpr_plate"] != "DL03EN6047"
        for result in (good, split, mostly_wrong):
            assert result["anpr_plate"] != "RJ83FN6847"

    def test_confusable_letters_need_two_frames(self):
        # valid state, confusable series letters (M/H, U/V): rule-assisted
        two = fuse(frame_reads([("KA01HV4521", 0.9)], [("KA01HV4521", 0.9)]), "KA01MU4521",
                   make_cfg())
        assert two["status"] == STATUS_PROBABLE_MATCH and two["rule_assisted"]
        assert two["edit_distance"] == 2
        one = fuse(frame_reads([("KA01HV4521", 0.9)]), "KA01MU4521", make_cfg())
        assert one["status"] == STATUS_NOT_CONFIRMED

    def test_edit_distance_one_is_probable(self):
        result = fuse(frame_reads([("MH12BR7815", 0.9)], [("MH12BR7815", 0.9)]),
                      "MH12BR7814", make_cfg())
        assert result["status"] == STATUS_PROBABLE_MATCH and not result["rule_assisted"]
        assert result["edit_distance"] == 1
        assert result["diff"] == [{"position": 10, "anpr": "5", "rfid": "4"}]

    def test_two_plates_without_vehicle_boxes_attach_nothing(self):
        # Older CARLA script (no vehicle boxes): two cars' plates in view. The
        # suspect's plate can NOT be picked by matching its expected text, so
        # nothing is attached - both are only reported as plates seen.
        frames = frame_reads([("GJ05FP3419", 0.95, 0), ("MH12BR7814", 0.7, 1)],
                             [("GJ05FP3419", 0.9, 0), ("MH12BR7814", 0.72, 1)])
        result = fuse(frames, "MH12BR7814", make_cfg())
        assert result["status"] == STATUS_NO_PLATE_VISIBLE
        assert result["anpr_plate"] is None and result["best_frame"] is None
        assert result["association"]["mode"] == "ambiguous"
        assert result["plates_seen"] == ["GJ05FP3419", "MH12BR7814"]

    def test_mismatch_without_boxes_never_shows_the_closest_other_plate(self):
        result = fuse(frame_reads([("KL07DL9182", 0.9, 0), ("GJ05FP3419", 0.8, 1)],
                                  [("KL07DL9182", 0.9, 0)]), "MH12BR7814", make_cfg())
        assert result["anpr_plate"] is None and result["largest_unread"] is None
        assert result["status"] == STATUS_NO_PLATE_VISIBLE
        assert result["plates_seen"] == ["GJ05FP3419", "KL07DL9182"]

    def test_single_plate_without_boxes_is_attached(self):
        result = fuse(frame_reads([("KL07DL9182", 0.9)], [("KL07DL9182", 0.9)]),
                      "MH12BR7814", make_cfg())
        assert result["association"]["mode"] == "single_plate"
        assert result["anpr_plate"] == "KL07DL9182"
        assert result["status"] == STATUS_NOT_CONFIRMED

    def test_voting_within_a_cluster(self):
        frames = frame_reads([("MH12BR7814", 0.8)], [("MH12BR7814", 0.5)], [("MH12BR7814", 0.7)])
        clusters = cluster_reads(frames, make_cfg())
        assert len(clusters) == 1 and clusters[0].voted == "MH12BR7814"
        assert clusters[0].frames == 3

    def test_voting_never_splices_two_vehicles(self):
        frames = frame_reads([("GJ05FP3419", 0.8, 0)], [("MH12BR7814", 0.8, 3)],
                             [("GJ05FP3419", 0.8, 0)])
        clusters = cluster_reads(frames, make_cfg())
        assert sorted(c.voted for c in clusters) == ["GJ05FP3419", "MH12BR7814"]

    def test_nothing_legible_and_too_small(self):
        assert fuse(frame_reads([], []), "MH12BR7814",
                    make_cfg())["status"] == STATUS_NO_PLATE_VISIBLE
        result = fuse([gated_frame(12.0)], "MH12BR7814", make_cfg())
        assert result["status"] == STATUS_PLATE_TOO_SMALL
        assert result["too_small_px"] == [12.0] and result["max_plate_px"] == 12.0

    def test_frame_ring_keeps_vehicle_boxes(self):
        ring = FrameRing(window_s=20.0)
        ring.add("CAM_J02_01", "J02", 50.0, b"x", 1000,
                 parse_vehicle_boxes([{"vehicle_id": "B", "bbox": [1, 2, 30, 40], "depth_m": 30}]))
        ring.add("CAM_J02_01", "J02", 50.2, b"x", 1004)          # older script: no field
        first, second = ring.frames["CAM_J02_01"]
        assert first.vehicle_box("B")["bbox"] == [1.0, 2.0, 30.0, 40.0]
        assert second.vehicles is None and second.vehicle_box("B") is None

    def test_frame_ring_spread_pick_and_prune(self):
        ring = FrameRing(window_s=20.0)
        for i in range(50):
            ring.add("CAM_J02_01", "J02", 50.0 + 0.2 * i, b"x")
        picked = ring.pick("CAM_J02_01", 50.0, 59.8, 8)
        assert len(picked) == 8
        assert picked[0].timestamp_sim == 50.0 and picked[-1].timestamp_sim > 58.0
        assert ring.nearest("J02", 55.03).timestamp_sim == 55.0
        ring.prune(75.0)
        assert all(f.timestamp_sim >= 55.0 for f in ring.frames["CAM_J02_01"])
        ring.clear()
        assert ring.cameras_for_junction("J02") == []


# =====================================================================
# suspect association: the plate must be ON the suspect vehicle
# =====================================================================

def boxed_frames(*frames, junction="J02", t0=56.0):
    """frames: per frame a list of vehicles in view, each
    (vehicle_id, plate OCR text or None, confidence, slot[, depth_m]).

    The vehicle's projected box (camera_frame ``vehicles`` metadata) and its
    plate box are placed at the slot; a None text = a vehicle with no plate
    detection. Every read goes through the real plate rules.
    """
    out = []
    for index, vehicles in enumerate(frames):
        boxes, rules = [], []
        for entry in vehicles:
            vehicle_id, text, conf, slot = entry[:4]
            depth = entry[4] if len(entry) > 4 else 30.0
            boxes.append({"vehicle_id": vehicle_id, "depth_m": depth,
                          "bbox": [60 + 300 * slot, 300, 240 + 300 * slot, 460]})
            if text is None:
                continue
            plate_box = (100 + 300 * slot, 400, 180 + 300 * slot, 420)
            rules.append(apply_rules({"box": plate_box, "det_confidence": 0.8, "raw_ocr": text,
                                      "ocr_variants": [{"text": text,
                                                        "confidences": [conf] * len(text),
                                                        "variant": "single"}]}, make_cfg()))
        ref = FrameRef(f"CAM_{junction}_01", junction, t0 + 0.2 * index, b"", 1000 + index,
                       parse_vehicle_boxes(boxes))
        out.append(FrameReads(ref, rules))
    return out


SUSPECT_B = Suspect(epc=EPC["B"], plate_norm="MH12BR7814", vehicle_id="B")


class TestSuspectAssociation:
    def test_only_the_plate_on_the_suspect_box_is_attached(self):
        # three cars in every frame; F's plate is the most confident in view
        frames = boxed_frames(
            [("F", "GJ05FP3419", 0.97, 0), ("B", "MH12BR7814", 0.70, 1), ("G", "AP16GQ8273", 0.9, 2)],
            [("F", "GJ05FP3419", 0.96, 0), ("B", "MH12BR7814", 0.72, 1), ("G", "AP16GQ8273", 0.9, 2)])
        result = fuse(frames, "MH12BR7814", make_cfg(), suspect=SUSPECT_B)
        assert result["association"]["mode"] == "bbox"
        assert result["association"]["associated_reads"] == 2
        assert result["anpr_plate"] == "MH12BR7814"
        assert result["status"] == STATUS_VISION_CONFIRMED
        assert result["best_read"].corrected == "MH12BR7814"
        assert all(rule.corrected == "MH12BR7814" for _, rule in result["best_members"])
        assert result["other_vehicles"] == ["AP16GQ8273", "GJ05FP3419"]

    def test_text_never_selects_another_vehicle(self):
        # Another car (F) carries a plate reading EXACTLY the registry plate; the
        # suspect's own plate reads differently. Association decides, so the
        # suspect's real read is reported and the result is NOT confirmed.
        frames = boxed_frames(
            [("F", "MH12BR7814", 0.95, 0), ("B", "KL07DL9182", 0.9, 1)],
            [("F", "MH12BR7814", 0.95, 0), ("B", "KL07DL9182", 0.9, 1)])
        result = fuse(frames, "MH12BR7814", make_cfg(), suspect=SUSPECT_B)
        assert result["anpr_plate"] == "KL07DL9182"
        assert result["status"] == STATUS_NOT_CONFIRMED
        assert "KL07DL9182" in result["match_reason"]

    def test_suspect_not_visible_attaches_no_plate(self):
        # B is not in these frames; F shows a plate identical to B's registry plate
        frames = boxed_frames([("F", "MH12BR7814", 0.95, 0), ("G", "AP16GQ8273", 0.9, 1)],
                              [("F", "MH12BR7814", 0.95, 0)])
        result = fuse(frames, "MH12BR7814", make_cfg(), suspect=SUSPECT_B)
        assert result["anpr_plate"] is None
        assert result["best_frame"] is None and result["best_read"] is None
        assert result["largest_unread"] is None and result["best_members"] == []
        assert result["status"] == STATUS_NO_PLATE_VISIBLE
        assert result["association"]["suspect_visible_frames"] == 0
        assert "not visible" in result["match_reason"]
        # the other plates are still recorded as context
        assert result["plates_seen"] == ["AP16GQ8273", "MH12BR7814"]

    def test_suspect_visible_but_plate_unreadable(self):
        frames = boxed_frames([("F", "GJ05FP3419", 0.95, 0), ("B", "CHR78", 0.8, 1)],
                              [("F", "GJ05FP3419", 0.95, 0), ("B", None, 0.0, 1)])
        result = fuse(frames, "MH12BR7814", make_cfg(), suspect=SUSPECT_B)
        assert result["anpr_plate"] is None
        assert result["status"] == STATUS_NO_PLATE_VISIBLE
        assert "plate not read" in result["match_reason"]
        # the unreadable plate shown as evidence is the one ON the suspect
        frame, rule = result["largest_unread"]
        assert rule.raw == "CHR78" and owner_of(rule, frame) == "B"

    def test_front_most_vehicle_owns_a_plate_inside_two_boxes(self):
        # B's box overlaps F's (B is behind F); F's plate centre lies in both boxes
        frames = boxed_frames([("F", "GJ05FP3419", 0.9, 0, 20.0), ("B", None, 0.0, 0.2, 45.0)],
                              [("F", "GJ05FP3419", 0.9, 0, 20.0), ("B", None, 0.0, 0.2, 45.0)])
        frame, rule = frames[0].frame, frames[0].plates[0]
        centre_x = (rule.box[0] + rule.box[2]) / 2
        for vehicle_id in ("F", "B"):        # the plate centre really is inside both boxes
            x1, _, x2, _ = frame.vehicle_box(vehicle_id)["bbox"]
            assert x1 <= centre_x <= x2
        assert owner_of(rule, frame) == "F"
        # swap the depths: now B is in front and owns the plate
        for vehicle in frame.vehicles:
            vehicle["depth_m"] = 45.0 if vehicle["vehicle_id"] == "F" else 20.0
        assert owner_of(rule, frame) == "B"
        for vehicle in frame.vehicles:
            vehicle["depth_m"] = 20.0 if vehicle["vehicle_id"] == "F" else 45.0
        result = fuse(frames, "MH12BR7814", make_cfg(), suspect=SUSPECT_B)
        assert result["anpr_plate"] is None and result["status"] == STATUS_NO_PLATE_VISIBLE

    def test_service_carries_the_suspect_identity(self, tmp_path):
        service, _, _ = make_service(tmp_path, adapter=FakeAnpr())
        incident = SimpleNamespace(vehicles=[SimpleNamespace(epc=EPC["B"], plate_norm="MH12BR7814",
                                                             sim_vehicle_id="B")])
        sighting = SimpleNamespace(epc=EPC["B"], plate_norm="MH12BR7814")
        suspect = service._suspect_for(incident, sighting)
        assert (suspect.vehicle_id, suspect.plate_norm, suspect.epc) == ("B", "MH12BR7814", EPC["B"])
        # an EPC known only to the registry still resolves to its actor id
        other = service._suspect_for(SimpleNamespace(vehicles=[]),
                                     SimpleNamespace(epc=EPC["D"], plate_norm=None))
        assert other.vehicle_id == "D"


class TestSuspectAssociationScenario:
    def test_attached_plates_are_always_the_suspects(self, tmp_path):
        # F crosses J02 and G crosses J03 together with B: only B's plate attaches
        service, store, events, _ = run_scenario(tmp_path)
        assert service.counters["errors"] == 0
        for match in store.of("vision_match"):
            assert match["anpr_plate"] in (None, "MH12BR7814"), match
        results = [e for e in events if e["type"] == "vision_match_result"]
        assert results and all(e["suspect_vehicle_id"] == "B" for e in results)
        assert all(e["association"]["mode"] == "bbox" for e in results)

    def test_tag_swap_reports_the_plate_on_the_tagged_car(self, tmp_path):
        service, store, _, _ = run_scenario(tmp_path, name="tag_swap", swap={"B": "D"})
        assert service.counters["errors"] == 0
        _, vision = vision_by_sighting(store)
        for junction in ("J02", "J03"):
            final = vision[(EPC["B"], junction)][-1]
            assert final["status"] == STATUS_NOT_CONFIRMED
            assert final["anpr_plate"] == "KL07DL9182"   # what is physically on B's car

    def test_older_script_without_boxes_never_attaches_another_vehicle(self, tmp_path):
        service, store, events, _ = run_scenario(tmp_path, vehicle_boxes=False)
        assert service.counters["errors"] == 0
        for match in store.of("vision_match"):
            assert match["anpr_plate"] in (None, "MH12BR7814"), match
        modes = {e["association"]["mode"] for e in events if e["type"] == "vision_match_result"}
        assert modes <= {"single_plate", "ambiguous", "none"}


# =====================================================================
# primary evidence: ONE best frame per (incident, suspect, junction)
# =====================================================================

def candidate(text, conf, width, sharp, t, det=0.8, vehicles=True):
    """One suspect candidate (FrameRef, RuleRead) with a plate of ``width`` px."""
    box = (100.0, 60.0, 100.0 + width, 60.0 + width / 4.0)
    rule = apply_rules({"box": box, "det_confidence": det, "raw_ocr": text,
                        "ocr_variants": [{"text": text, "confidences": [conf] * len(text),
                                          "variant": "single"}]}, make_cfg(), sharpness=sharp)
    boxes = parse_vehicle_boxes([{"vehicle_id": "B", "bbox": [60, 20, 400, 115],
                                  "depth_m": 30.0}]) if vehicles else None
    return FrameRef("CAM_J02_01", "J02", t, b"", int(t * 20), boxes), rule


def textured_decoder(_jpeg):
    rng = np.random.default_rng(7)
    return rng.integers(40, 220, FAKE_FRAME_SHAPE, dtype=np.uint8)


def primary_setup(tmp_path):
    fake = FakeAnpr()
    fake.decode = textured_decoder
    service, store, _ = make_service(tmp_path, adapter=fake)
    incident = SimpleNamespace(incident_id="11111111-1111-1111-1111-111111111111",
                               vehicles=[SimpleNamespace(epc=EPC["B"], plate_norm="MH12BR7814",
                                                         sim_vehicle_id="B")])
    sighting = SimpleNamespace(epc=EPC["B"], junction_id="J02", plate_norm="MH12BR7814",
                               sighting_id="22222222-2222-2222-2222-222222222222")
    return service, store, incident, sighting


def outcome_of(members, strength=1.0):
    return {"best_members": members,
            "association_strength": {(id(ref), id(rule)): strength for ref, rule in members}}


class TestPrimaryEvidence:
    def test_score_prefers_sharp_large_confident_valid(self):
        from app.services.rfid.evidence import primary_score

        crop = textured_decoder(b"")[:20, :80]
        _, good = candidate("MH12BR7814", 0.92, 90, 900.0, 60.0)
        _, small = candidate("MH12BR7814", 0.92, 30, 900.0, 60.2)
        _, blurry = candidate("MH12BR7814", 0.92, 90, 20.0, 60.4)
        _, junk = candidate("CHR78", 0.92, 90, 900.0, 60.6)
        score = {name: primary_score(rule, crop, 1.0)[0]
                 for name, rule in (("good", good), ("small", small),
                                    ("blurry", blurry), ("junk", junk))}
        assert score["good"] > max(score["small"], score["blurry"], score["junk"])
        # association matters: the same read outside the suspect box scores lower
        assert primary_score(good, crop, 0.2)[0] < primary_score(good, crop, 1.0)[0]
        _, parts = primary_score(good, crop, 1.0)
        assert set(parts) == {"quality", "ocr", "valid", "association", "aspect", "exposure"}

    def test_many_candidates_give_exactly_one_primary_the_best(self, tmp_path):
        from app.services.rfid.evidence import primary_score

        service, store, incident, sighting = primary_setup(tmp_path)
        members = [candidate("MH12BR7814", 0.70, 70, 300.0, 60.0),
                   candidate("MH12BR7814", 0.95, 95, 900.0, 60.2),     # the best
                   candidate("MH12BR7814", 0.80, 80, 500.0, 60.4),
                   candidate("HH12BR7B14", 0.60, 60, 200.0, 60.6),
                   candidate("MH12BR7814", 0.75, 50, 900.0, 60.8)]
        service._update_primary(incident, sighting, outcome_of(members), "m-1", textured_decoder)
        primaries = [row for row in store.of("evidence") if row["kind"] == "primary_frame"]
        assert len(primaries) == 1
        scores = {ref.timestamp_sim: primary_score(rule, None, 1.0)[0] for ref, rule in members}
        assert primaries[0]["frame_ts"] == 60.2 == max(scores, key=scores.get)
        kinds = sorted(row["kind"] for row in store.of("evidence"))
        assert kinds == ["primary_frame", "primary_plate", "primary_raw"]
        assert all(Path(row["path"]).is_file() for row in store.of("evidence"))

    def test_a_better_frame_replaces_a_worse_one_never_adds(self, tmp_path):
        service, store, incident, sighting = primary_setup(tmp_path)
        first = [candidate("MH12BR7814", 0.75, 70, 400.0, 60.0)]
        service._update_primary(incident, sighting, outcome_of(first), "m-1", textured_decoder)
        worse = [candidate("MH12BR7814", 0.50, 40, 100.0, 61.0),
                 candidate("CHR78", 0.40, 40, 100.0, 61.2)]
        service._update_primary(incident, sighting, outcome_of(worse), "m-1", textured_decoder)
        primaries = [row for row in store.of("evidence") if row["kind"] == "primary_frame"]
        assert [row["frame_ts"] for row in primaries] == [60.0]          # nothing added
        better = [candidate("MH12BR7814", 0.95, 95, 900.0, 62.0)]
        service._update_primary(incident, sighting, outcome_of(better), "m-1", textured_decoder)
        primaries = [row for row in store.of("evidence") if row["kind"] == "primary_frame"]
        assert [row["frame_ts"] for row in primaries] == [60.0, 62.0]
        assert primaries[1]["score"] > primaries[0]["score"]
        # a second sighting at the same junction competes with the same primary
        again = SimpleNamespace(**{**vars(sighting), "sighting_id": "33333333-3333-3333-3333-333333333333"})
        service._update_primary(incident, again, outcome_of(worse), "m-2", textured_decoder)
        assert len([r for r in store.of("evidence") if r["kind"] == "primary_frame"]) == 2

    def test_unreadable_suspect_plate_is_kept_until_a_legible_one(self, tmp_path):
        service, store, incident, sighting = primary_setup(tmp_path)
        ref, rule = candidate("CHR78", 0.5, 70, 300.0, 60.0)
        service._update_primary(incident, sighting, {"best_members": [],
                                                     "largest_unread": (ref, rule)},
                                "m-1", textured_decoder)
        service._update_primary(incident, sighting,
                                outcome_of([candidate("MH12BR7814", 0.9, 80, 600.0, 61.0)]),
                                "m-1", textured_decoder)
        primaries = [row for row in store.of("evidence") if row["kind"] == "primary_frame"]
        assert [row["frame_ts"] for row in primaries] == [60.0, 61.0]


STAMP0 = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def rows_as_objects(store):
    """FakeStore payloads -> objects shaped like the DB rows the API reads."""
    sightings = {}
    for row in store.of("sighting"):
        sightings[row["id"]] = {**sightings.get(row["id"], {}), **row}
    sightings = [SimpleNamespace(**row) for row in sightings.values()]
    matches = {}
    for row in store.of("vision_match"):
        merged = {**matches.get(row["sighting_id"], {}), **row}
        matches[row["sighting_id"]] = merged
    matches = {key: SimpleNamespace(**value) for key, value in matches.items()}
    files = defaultdict(list)
    for index, row in enumerate(store.of("evidence")):
        if row["owner"] == "vision_match":
            files[str(row["vision_match_id"])].append(
                SimpleNamespace(id=f"ev-{index:04d}", created_at=STAMP0 + timedelta(seconds=index), **row))
    return sightings, matches, files


class TestBestEvidenceByJunction:
    def test_one_card_per_junction_with_the_highest_scoring_primary(self, tmp_path):
        from app.routers.incidents import best_evidence_by_junction

        service, store, events, _ = run_scenario(tmp_path)
        assert service.counters["errors"] == 0
        sightings, matches, files = rows_as_objects(store)
        incident_id = sightings[0].incident_id
        cards = best_evidence_by_junction(incident_id, sightings, matches, files,
                                          {EPC["B"]: "B", EPC["A"]: "A"})
        assert [card["junction_id"] for card in cards] == ["J02", "J03"]      # the route
        for card in cards:
            assert card["suspect_vehicle_id"] == "B" and card["status"] == STATUS_VISION_CONFIRMED
            primary = card["primary"]
            assert primary and not primary["legacy"]
            junction_primaries = [row for rows in files.values() for row in rows
                                  if row.kind == "primary_frame" and row.junction_id == card["junction_id"]]
            assert primary["score"] == max(row.score for row in junction_primaries)
            assert primary["plate_crop"] and primary["raw_frame"]
            assert primary["read_text"] == "MH12BR7814" and primary["read_valid"]
            assert card["anpr_plate"] == "MH12BR7814"
            # supporting candidates: only reads ON the suspect, never F's or G's plate
            assert card["supporting"]["candidate_reads"] >= 1
            assert {r["corrected"] for r in card["supporting"]["candidates"]} == {"MH12BR7814"}

    def test_legacy_rows_fall_back_to_the_newest_hero(self):
        from app.routers.incidents import best_evidence_by_junction

        sighting = SimpleNamespace(id="s1", epc=EPC["B"], junction_id="J03", plate_norm="MH12BR7814",
                                   first_seen_ts=70.0, last_seen_ts=74.0)
        match = SimpleNamespace(id="m1", status=STATUS_PROBABLE_MATCH, anpr_confidence=0.7,
                                rule_assisted=False, match_reason="x", anpr_plate="MH12BR7814",
                                rfid_plate="MH12BR7814", per_frame=[])
        heroes = [SimpleNamespace(id=f"h{i}", kind="hero_frame", vision_match_id="m1", score=0.1 * i,
                                  frame_ts=70.0 + i, created_at=STAMP0 + timedelta(seconds=i), sha256="", width=1,
                                  height=1, junction_id="J03") for i in range(3)]
        cards = best_evidence_by_junction("inc", [sighting], {"s1": match}, {"m1": heroes},
                                          {EPC["B"]: "B"})
        assert len(cards) == 1
        assert cards[0]["primary"]["legacy"] and cards[0]["primary"]["image"]["id"] == "h2"
        assert cards[0]["supporting"]["frames"] == 2


# =====================================================================
# fleeing suspect: Member 1's escape report decides, never hard-coded
# =====================================================================

def escape_state(vehicle="B", ts=43.0, distance=12.5, speed=31.0):
    """Member 1's vehicle_state when its escape detection fires."""
    return {"type": "vehicle_state", "timestamp_sim": ts, "frame": int(ts * 20),
            "vehicle_id": vehicle, "plate_number": SEED_DISPLAY[vehicle], "epc": EPC[vehicle],
            "state": "POST_CRASH_MOVING", "speed_kmh": speed,
            "distance_from_crash_m": distance, "escape_confirmed": True}


SEED_DISPLAY = {vehicle: f"{p[:2]} {p[2:4]} {p[4:6]} {p[6:]}" for vehicle, p in PLATE.items()}


class TestFleeingSuspect:
    def test_escape_marks_the_fled_vehicle(self, tmp_path):
        service, store, events = make_service(tmp_path)
        service.on_crash_alert(physics_alert(ts=40.0))
        assert service.on_vehicle_state(escape_state("B", ts=43.0))["status"] == "suspect"
        incident = next(iter(service.opened_incidents.values()))
        assert set(incident.fled) == {PLATE["B"]}
        fled_rows = [row for row in store.of("incident_vehicle") if row["role"] == "fled"]
        assert [(row["plate_norm"], row["sim_vehicle_id"]) for row in fled_rows] == [(PLATE["B"], "B")]
        announced = [e for e in events if e["type"] == "suspect_identified"]
        assert len(announced) == 1 and announced[0]["suspect_vehicle_id"] == "B"
        # a repeat of the same report changes nothing
        service.on_vehicle_state(escape_state("B", ts=43.5))
        assert len([e for e in events if e["type"] == "suspect_identified"]) == 1

    def test_escape_before_the_incident_is_applied_on_creation(self, tmp_path):
        service, store, events = make_service(tmp_path)
        assert service.on_vehicle_state(escape_state("B", ts=40.5))["status"] == "pending"
        service.on_crash_alert(physics_alert(ts=40.0))
        incident = next(iter(service.opened_incidents.values()))
        assert set(incident.fled) == {PLATE["B"]}
        assert any(e["type"] == "suspect_identified" for e in events)

    def test_unrelated_or_stale_escape_is_ignored(self, tmp_path):
        service, store, _ = make_service(tmp_path)
        service.on_crash_alert(physics_alert(ts=40.0))
        service.on_vehicle_state(escape_state("F", ts=43.0))           # not in this crash
        service.on_vehicle_state(escape_state("B", ts=400.0))          # long after it
        service.on_vehicle_state({**escape_state("B"), "escape_confirmed": False})
        incident = next(iter(service.opened_incidents.values()))
        assert incident.fled == {}
        assert not [row for row in store.of("incident_vehicle") if row["role"] == "fled"]

    def test_anpr_runs_only_on_frames_with_the_suspect(self, tmp_path):
        service, store, _, fake = run_scenario(tmp_path)
        assert service.counters["errors"] == 0
        assert service.counters["anpr_skipped_no_suspect"] > 0
        _, vision = vision_by_sighting(store)
        for junction in ("J02", "J03"):
            assert STATUS_VISION_CONFIRMED in [m["status"] for m in vision[(EPC["B"], junction)]]

    def test_api_cards_only_for_the_fleeing_vehicle(self):
        from app.routers.incidents import (best_evidence_by_junction, fleeing_suspects,
                                           fleeing_vehicle_summary)

        vehicles = [SimpleNamespace(plate_norm=PLATE[v], epc=EPC[v], role="involved", sim_vehicle_id=v)
                    for v in "AB"]
        vehicles.append(SimpleNamespace(plate_norm=PLATE["B"], epc=EPC["B"], role="fled",
                                        sim_vehicle_id="B"))
        # both A and B were (somehow) read at J02; only B fled
        sightings = [SimpleNamespace(id=f"s{v}", epc=EPC[v], junction_id="J02", plate_norm=PLATE[v],
                                     first_seen_ts=50.0, last_seen_ts=52.0) for v in "AB"]
        suspects = fleeing_suspects(vehicles, sightings)
        assert [(s["sim_vehicle_id"], s["basis"].startswith("Member 1")) for s in suspects] == [("B", True)]
        epcs = {s["epc"] for s in suspects}
        match = SimpleNamespace(id="mB", status=STATUS_PROBABLE_MATCH, anpr_confidence=0.7,
                                rule_assisted=False, match_reason="r", anpr_plate=PLATE["B"],
                                rfid_plate=PLATE["B"], per_frame=[])
        cards = best_evidence_by_junction("inc", [s for s in sightings if s.epc in epcs],
                                          {"sB": match}, {}, {EPC["B"]: "B"})
        assert [card["suspect_vehicle_id"] for card in cards] == ["B"]
        header = fleeing_vehicle_summary(suspects[0], cards)
        assert header["junctions"] == ["J02"] and header["overall_status"] == STATUS_PROBABLE_MATCH
        assert header["final_plate_read"] == PLATE["B"]
        # without an escape report, the involved tag sighted elsewhere is the suspect
        fallback = fleeing_suspects([v for v in vehicles if v.role != "fled"], sightings[1:])
        assert [s["sim_vehicle_id"] for s in fallback] == ["B"]
        assert fallback[0]["basis"].startswith("its RFID tag")


# =====================================================================
# the same two cars colliding twice in ONE continuous CARLA session
# =====================================================================

class TestRepeatedCollisionSameSession:
    """Sim time never resets between two A<->B crashes at J01 (the world is not
    reloaded), so the run id stays the same. Each crash must be its own
    incident, and the first must not show the second's junction sightings."""

    def _drive(self, service, crash_ts, alert_id, seq0):
        service.on_crash_alert(physics_alert(ts=crash_ts, frame=int(crash_ts * 20),
                                             alert_id=alert_id))
        for i, (junction, t) in enumerate((("J02", crash_ts + 8.0), ("J03", crash_ts + 18.0))):
            service.on_rfid_message(v2(EPC["B"], junction, first=t, last=t + 1.5, seq=seq0 + i))
            service.tick(now_ts=t + 2.0)
        for extra in range(1, 12):
            service.tick(now_ts=crash_ts + 20.0 + extra)

    def test_two_crashes_are_two_incidents_with_their_own_sightings(self, tmp_path):
        service, store, events = make_service(tmp_path)
        self._drive(service, 26.7, "PHY-000000534", 1)
        self._drive(service, 682.2, "PHY-000013644", 10)

        incidents = final_by_id(store.of("incident"))
        assert len(incidents) == 2, "the second crash must not reuse the first incident"
        by_crash = {round(row["crash_ts_sim"], 1): row["id"] for row in incidents.values()}
        assert set(by_crash) == {26.7, 682.2}
        assert [e["type"] for e in events].count("incident_created") == 2

        sightings = final_by_id(store.of("sighting")).values()
        per_incident = defaultdict(list)
        for row in sightings:
            per_incident[row["incident_id"]].append(row["first_seen_ts"])
        first, second = by_crash[26.7], by_crash[682.2]
        # each incident only holds the passes that followed ITS crash
        assert sorted(per_incident[first]) == [34.7, 44.7]
        assert sorted(per_incident[second]) == [690.2, 700.2]

    def test_watch_window_ends_old_incidents(self, tmp_path):
        service, store, _ = make_service(tmp_path)
        service.on_crash_alert(physics_alert(ts=40.0))
        # B is read at J02 long after the crash: not a sighting of this incident
        service.on_rfid_message(v2(EPC["B"], "J02", first=40.0 + 300.0, last=341.5, seq=1))
        service.tick(now_ts=345.0)
        assert store.of("sighting") == []
        assert service.sightings.ignored.get("after the incident's watch window") == 1


# =====================================================================
# persistence: queue + retry, poison rows never block the queue
# =====================================================================

class _Session:
    def __init__(self, failures):
        self.failures = failures

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class TestPersistence:
    def test_retryable_classification(self):
        from sqlalchemy.exc import IntegrityError, OperationalError

        assert retryable(OperationalError("select 1", {}, Exception("db down")))
        assert not retryable(IntegrityError("insert", {}, Exception("duplicate key")))
        assert not retryable(ValueError("bug"))

    def _store(self, handler):
        store = Persistence(cfg=make_cfg(db_retry_min_s=0.01, db_retry_max_s=0.02),
                            session_factory=lambda: _Session(None))
        store._write_probe = handler
        return store

    def test_permanent_error_drops_the_row_and_keeps_going(self):
        from sqlalchemy.exc import IntegrityError

        written = []

        def handler(session, payload):
            if payload["bad"]:
                raise IntegrityError("insert", {}, Exception("duplicate key"))
            written.append(payload["n"])

        store = self._store(handler).start()
        try:
            store.submit("probe", {"bad": True, "n": 0})
            store.submit("probe", {"bad": False, "n": 1})
            assert store.flush(timeout=5.0)
        finally:
            store.stop()
        assert written == [1]
        assert store.counters.dropped == 1 and store.counters.written == 1

    def test_db_down_is_retried_until_it_comes_back(self):
        from sqlalchemy.exc import OperationalError

        attempts = {"n": 0}

        def handler(session, payload):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise OperationalError("insert", {}, Exception("connection refused"))

        store = self._store(handler).start()
        try:
            store.submit("probe", {})
            assert store.flush(timeout=5.0)
        finally:
            store.stop()
        assert attempts["n"] == 3
        assert store.counters.retries == 2 and store.counters.written == 1

    def test_bounded_queue_when_db_is_down(self):
        store = Persistence(cfg=make_cfg(db_queue_max=2))      # not started: nothing drains
        assert store.submit("probe", {}) and store.submit("probe", {})
        assert store.submit("probe", {}) is False
        assert store.counters.dropped == 1


# =====================================================================
# service: entry points, windows, run scoping (no ANPR)
# =====================================================================

class TestService:
    def test_rfid_entry_counts_and_archives(self, tmp_path):
        service, store, _ = make_service(tmp_path)
        service.on_rfid_message(v2(EPC["B"], seq=1))
        service.on_rfid_message(v2(EPC["B"], seq=1))                 # re-sent
        service.on_rfid_message(v2(EPC["B"], first=31.0, seq=4))     # 2 missing
        service.on_rfid_message(v2(UNKNOWN_EPC, first=31.2, seq=5))
        assert service.counters["rfid_stored"] == 3
        assert service.counters["duplicates"] == 1
        assert service.counters["gaps"] == 1 and service.counters["missing_reports"] == 2
        reports = store.of("rfid_report")
        assert len(reports) == 3                                      # the duplicate is not
        unknown = [r for r in reports if r["epc"] == UNKNOWN_EPC][0]
        assert unknown["plate_norm"] is None and unknown["registry_status"] == UNREGISTERED_TAG
        assert [r for r in reports if r["epc"] == EPC["B"]][0]["registry_status"] == "REGISTERED"

    def test_malformed_messages_never_raise(self, tmp_path):
        service, _, _ = make_service(tmp_path)
        assert service.on_rfid_message({"type": "rfid_reading"})["status"] == "ignored"
        assert service.on_crash_alert({"type": "crash_alert"})["status"] == "ignored"
        service.on_camera_frame({"type": "camera_frame"})
        assert service.counters["errors"] == 0

    def test_crash_zone_snapshot_window(self, tmp_path):
        service, store, events = make_service(tmp_path)
        for seq, (epc, t) in enumerate([(EPC["A"], 9.0), (EPC["A"], 12.0), (EPC["E"], 39.0),
                                        (EPC["B"], 39.5), (UNKNOWN_EPC, 41.0)]):
            service.on_rfid_message(v2(epc, junction="J01", first=t, seq=seq))
        result = service.on_crash_alert(physics_alert(ts=40.0))
        assert result["status"] == "created" and result["crash_junction"] == "J01"
        assert [e["type"] for e in events] == ["incident_created"]
        # a tag read after the crash, still inside +30 s, is captured at close
        service.on_rfid_message(v2(EPC["H"], junction="J01", first=65.0, seq=10))
        service.on_rfid_message(v2(EPC["H"], junction="J01", first=71.0, seq=11))  # outside
        service.tick(now_ts=70.5)
        rows = {}
        for row in store.of("crash_zone"):
            rows[row["epc"]] = row            # last write wins, like the upsert
        assert EPC["A"] in rows and rows[EPC["A"]]["first_seen_ts"] == 12.0   # 9.0 is outside
        assert rows[EPC["A"]]["role"] == ROLE_INVOLVED and rows[EPC["B"]]["role"] == ROLE_INVOLVED
        assert rows[EPC["E"]]["role"] == ROLE_NEARBY
        assert rows[UNKNOWN_EPC]["plate_norm"] is None
        assert rows[EPC["H"]]["last_seen_ts"] == 65.0
        assert all(row["junction_id"] == "J01" for row in rows.values())

    def test_alert_retries_and_duplicates(self, tmp_path):
        service, store, events = make_service(tmp_path)
        assert service.on_crash_alert(physics_alert())["status"] == "created"
        assert service.on_crash_alert(physics_alert())["status"] == "duplicate"
        assert service.on_crash_alert(imu_alert(40.2, 801, "A", "B"))["status"] == "merged"
        assert service.on_crash_alert(imu_alert(40.4, 802, "B", "A"))["status"] == "merged"
        incidents = {row["id"] for row in store.of("incident")}
        assert len(incidents) == 1
        assert sorted({row["alert_id"] for row in store.of("incident_alert")}) == \
            ["MM-000000801", "MM-000000802", "PHY-800"]
        assert [e["type"] for e in events] == ["incident_created"]

    def test_watchlist_hit_notifies_before_vision(self, tmp_path):
        service, store, events = make_service(tmp_path)
        service.on_crash_alert(physics_alert(ts=40.0))
        service.on_rfid_message(v2(EPC["B"], junction="J02", first=55.0, last=55.4, seq=1))
        service.on_rfid_message(v2(EPC["C"], junction="J02", first=55.0, last=55.4, seq=2))
        service.tick(now_ts=55.5)
        hits = [e for e in events if e["type"] == "watchlist_rfid_hit"]
        assert len(hits) == 1 and hits[0]["epc"] == EPC["B"] and hits[0]["junction_id"] == "J02"
        assert hits[0]["plate_norm"] == "MH12BR7814"
        sighting = store.of("sighting")[0]
        assert sighting["closed"] is False
        # quiet for 4 s -> the closed sighting is written with its final counts
        service.on_rfid_message(v2(EPC["B"], junction="J02", first=55.5, last=55.9, seq=3))
        service.tick(now_ts=58.0)
        assert store.of("sighting")[-1]["closed"] is False      # a 2 s drop-out is tolerated
        service.tick(now_ts=60.0)
        final = store.of("sighting")[-1]
        assert final["closed"] is True and final["report_count"] == 2
        assert final["last_seen_ts"] == 55.9

    def test_sighting_with_no_camera_frames_is_recorded_not_dropped(self, tmp_path):
        service, store, events = make_service(tmp_path, adapter=FakeAnpr())
        service.on_crash_alert(physics_alert(ts=40.0))
        service.on_rfid_message(v2(EPC["B"], junction="J02", first=55.0, last=55.4, seq=1))
        service.tick(now_ts=55.5)
        service.tick(now_ts=62.0)          # closed at 59.4, trailing window ends 62.4
        service.tick(now_ts=63.0)
        match = store.of("vision_match")[-1]
        assert match["status"] == STATUS_NO_PLATE_VISIBLE and match["frames_used"] == 0
        assert match["finalized"] is True
        assert match["rfid_plate"] == "MH12BR7814" and match["all_plates_seen"] == []
        assert [e for e in events if e["type"] == "vision_match_result"][-1]["frames_used"] == 0

    def test_run_reset_scopes_buffers_and_alert_ids(self, tmp_path):
        service, store, _ = make_service(tmp_path)
        service.on_rfid_message(v2(EPC["A"], junction="J01", first=39.0, seq=1, run_id="R1"))
        first = service.on_crash_alert(physics_alert(ts=40.0))
        service.on_camera_frame({"camera_id": "CAM_J01_01", "junction_id": "J01",
                                 "timestamp_sim": 60.0, "image": "eA=="})
        # a new CARLA run: new run_id, time restarts
        service.on_rfid_message(v2(EPC["A"], junction="J01", first=5.0, seq=1, run_id="R2"))
        assert service.buffer.window("J01", 0, 1e9)[0].run_id == "R2"
        assert service.frames.cameras_for_junction("J01") == []
        second = service.on_crash_alert(physics_alert(ts=40.0))       # same alert id
        assert second["status"] == "created"
        assert second["incident_id"] != first["incident_id"]
        runs = [row["run_id"] for row in store.of("incident")]
        assert runs[0] != runs[1] and runs[1] == "R2"

    def test_result_events_are_versioned_and_debounced(self, tmp_path):
        clock = {"t": 0.0}
        service, store, events = make_service(tmp_path, adapter=FakeAnpr())
        service._wall = lambda: clock["t"]
        service.on_crash_alert(physics_alert(ts=40.0))
        service.on_rfid_message(v2(EPC["B"], junction="J02", first=55.0, last=55.4, seq=1))
        service.tick(now_ts=55.5)
        incident = next(iter(service.opened_incidents.values()))
        sighting = service.sightings.open_sightings()[0]
        weak = fuse(frame_reads([("MH12BR7815", 0.7)], [("MH12BR7815", 0.7)]), "MH12BR7814", make_cfg())
        strong = fuse(frame_reads([("MH12BR7814", 0.9)], [("MH12BR7814", 0.9)]), "MH12BR7814", make_cfg())
        service._handle_outcome(incident, sighting, weak)
        service._handle_outcome(incident, sighting, weak)            # no material change
        clock["t"] += 1.0
        service._handle_outcome(incident, sighting, strong)          # changed, but debounced
        results = [e for e in events if e["type"] == "vision_match_result"]
        assert [(e["version"], e["status"]) for e in results] == [(1, STATUS_PROBABLE_MATCH)]
        clock["t"] += 3.0
        service._flush_debounced()
        results = [e for e in events if e["type"] == "vision_match_result"]
        assert [(e["version"], e["status"]) for e in results] == \
            [(1, STATUS_PROBABLE_MATCH), (2, STATUS_VISION_CONFIRMED)]
        # finalize exactly once, never a downgrade
        service._finalize(incident, sighting, weak)
        service._finalize(incident, sighting, strong)
        finals = [e for e in events if e["type"] == "vision_match_result" and e["final"]]
        assert len(finals) == 1 and finals[0]["version"] == 3
        assert store.of("vision_match")[-1]["finalized"] is True

    def test_feed_source_classifies_the_run(self, tmp_path):
        service, store, events = make_service(tmp_path)
        service.on_crash_alert({**physics_alert(ts=40.0), "feed_source": "synthetic"})
        assert store.of("incident")[0]["source"] == "synthetic"
        assert events[0]["source"] == "synthetic"
        live, live_store, _ = make_service(tmp_path / "live")
        live.on_crash_alert(physics_alert(ts=148.5, frame=13727))
        assert live_store.of("incident")[0]["source"] == "live"

    @pytest.mark.parametrize("crash_junction", ["J02", "J03"])
    def test_crash_at_any_junction(self, tmp_path, crash_junction):
        others = [j for j in ("J01", "J02", "J03") if j != crash_junction]
        service, store, events = make_service(tmp_path)
        t = 100.0
        # involved tags + a bystander at the crash junction, a watchlist tag and a
        # bystander at another junction during the same window
        service.on_rfid_message(v2(EPC["A"], junction=crash_junction, first=t - 3, seq=1))
        service.on_rfid_message(v2(EPC["C"], junction=crash_junction, first=t - 2, seq=2))
        service.on_rfid_message(v2(EPC["H"], junction=others[0], first=t - 5, seq=3))
        result = service.on_crash_alert(physics_alert(ts=t, frame=2000, junction=crash_junction))
        assert result["crash_junction"] == crash_junction
        # B escapes to BOTH other junctions: each is a "next junction" sighting
        service.on_rfid_message(v2(EPC["B"], junction=crash_junction, first=t + 2, seq=4))
        service.on_rfid_message(v2(EPC["B"], junction=others[0], first=t + 15, seq=5))
        service.on_rfid_message(v2(EPC["B"], junction=others[1], first=t + 40, seq=6))
        service.tick(now_ts=t + 45)
        rows = final_by_id(store.of("crash_zone"), key="epc")
        assert rows[EPC["A"]]["zone"] == "crash" and rows[EPC["A"]]["junction_id"] == crash_junction
        assert rows[EPC["C"]]["zone"] == "crash" and rows[EPC["C"]]["role"] == ROLE_NEARBY
        assert rows[EPC["H"]]["zone"] == "context" and rows[EPC["H"]]["junction_id"] == others[0]
        sightings = final_by_id(store.of("sighting")).values()
        assert sorted(row["junction_id"] for row in sightings) == sorted(others)
        assert all(row["epc"] == EPC["B"] for row in sightings)

    def test_reconnect_alone_is_not_a_new_run(self, tmp_path):
        service, _, _ = make_service(tmp_path, run_reset_gap_s=30.0)
        clock = {"t": 1000.0}
        service._wall = lambda: clock["t"]
        service.on_crash_alert(physics_alert(ts=40.0))
        # a 40 s silence and a reconnect while sim time keeps increasing: same run
        service.note_disconnect()
        clock["t"] += 40.0
        service.on_rfid_message(v2(EPC["B"], first=82.0, seq=1))
        assert service.on_crash_alert(physics_alert(ts=40.0))["status"] == "duplicate"
        assert service.runs.run_index == 1

    def test_reconnect_rule_can_be_switched_back_on(self, tmp_path):
        service, _, _ = make_service(tmp_path, run_reset_gap_s=30.0, run_reset_on_reconnect=True)
        clock = {"t": 1000.0}
        service._wall = lambda: clock["t"]
        service.on_crash_alert(physics_alert(ts=40.0))
        service.note_disconnect()
        clock["t"] += 40.0
        assert service.on_crash_alert(physics_alert(ts=40.0))["status"] == "created"
        assert service.runs.run_index == 2

    def test_reader_restart_with_the_same_run_id_is_a_new_run(self, tmp_path):
        # The live bug: the CARLA copy used a seed-derived run_id, so a second
        # start re-sent seq 1.. under the same run_id while sim time kept running.
        service, store, _ = make_service(tmp_path)
        for seq in range(1, 4):
            service.on_rfid_message(v2(EPC["A"], junction="J01", first=140.0 + seq, seq=seq,
                                       run_id="SEEDED"))
        first = service.on_crash_alert(physics_alert(ts=148.5, frame=13727))
        assert service.on_rfid_message(v2(EPC["A"], junction="J01", first=1940.0, seq=1,
                                          run_id="SEEDED"))["status"] != "duplicate"
        assert service.counters["run_resets"] == 1
        second = service.on_crash_alert(physics_alert(ts=1947.7, frame=180166))
        assert second["status"] == "created" and second["incident_id"] != first["incident_id"]
        # the restarted reader is archived under its own key, never rejected
        archived = {(row["run_id"], row["seq"]) for row in store.of("rfid_report")}
        assert ("SEEDED", 1) in archived and ("SEEDED#2", 1) in archived

    def test_reused_alert_ids_with_a_later_crash_time_are_a_new_run(self, tmp_path):
        service, store, _ = make_service(tmp_path)
        first = service.on_crash_alert(imu_alert(ts=149.48, frame=99, alert_id="MM-000000099"))
        # a second CARLA start: the same alert id, sim time kept increasing
        second = service.on_crash_alert(imu_alert(ts=1948.58, frame=99, alert_id="MM-000000099"))
        assert first["status"] == "created" and second["status"] == "created"
        assert len({row["id"] for row in store.of("incident")}) == 2
        # a genuine retry (same crash time) is still a duplicate
        assert service.on_crash_alert(imu_alert(ts=1948.58, frame=99,
                                                alert_id="MM-000000099"))["status"] == "duplicate"

    def test_backend_restart_never_reuses_an_incident_row(self, tmp_path):
        # Regression: after a restart the generated run id restarted at 0001, the
        # dedupe key matched an OLD incident row while the service used a fresh
        # id, and every child row failed its foreign key.
        first, first_store, _ = make_service(tmp_path / "a")
        first.runs.session = "boot1"
        first.on_crash_alert(physics_alert(ts=40.0))
        second, second_store, _ = make_service(tmp_path / "b")          # "restarted"
        second.runs.session = "boot2"
        second.on_crash_alert(physics_alert(ts=40.0))
        one, two = first_store.of("incident")[0], second_store.of("incident")[0]
        assert one["dedupe_key"] != two["dedupe_key"] and one["id"] != two["id"]
        # every child row carries the id of the row it belongs to
        assert {row["incident_id"] for row in second_store.of("incident_alert")} == {two["id"]}

    def test_restart_mid_run_rejoins_the_same_incident(self, tmp_path):
        # With a v2 run_id on the RFID stream, a restarted backend joins that run
        # and derives the SAME incident id, so the upsert and its children agree.
        ids = []
        for name in ("a", "b"):
            service, store, _ = make_service(tmp_path / name)
            service.on_rfid_message(v2(EPC["A"], junction="J01", first=39.0, seq=1,
                                       run_id="carla-run-7"))
            service.on_crash_alert(physics_alert(ts=40.0))
            ids.append(store.of("incident")[0]["id"])
            assert store.of("incident")[0]["run_id"] == "carla-run-7"
        assert ids[0] == ids[1]

    def test_retried_alert_does_not_look_like_a_new_run(self, tmp_path):
        service, _, _ = make_service(tmp_path)
        service.on_crash_alert(physics_alert(ts=40.0))
        service.on_rfid_message(v2(EPC["B"], first=60.0, seq=1))
        # the same crash, retried 20 s of sim time later
        assert service.on_crash_alert(physics_alert(ts=40.0))["status"] == "duplicate"
        assert service.buffer.epoch == 0


# =====================================================================
# scenario tests: the full ladder, in-process
# =====================================================================

CAMERA_RANGE_M = 14.0


def run_scenario(tmp_path, name="normal", fmt="v2", duration=95.0, repeat=1, swap=None,
                 cfg_overrides=None, resend_rfid=False, tick_every=0.5, vehicle_boxes=True):
    """Replay the demo scenario into one service, in sim-time order, ticking at 2 Hz.

    ``vehicle_boxes``: camera_frame carries the optional per-vehicle image boxes
    (the patched CARLA script); False = the older script without them.
    """
    import scenario as sc
    from rfid_reader_model import RfidConfig
    from simulate_carla_feed import alert_messages, rfid_messages

    fake = FakeAnpr()
    service, store, events = make_service(tmp_path, adapter=fake, **(cfg_overrides or {}))
    times = sc.timeline(duration)
    swap = swap or {}

    messages = list(rfid_messages(RfidConfig(seed=20240930), times, fmt, 20240930, name))
    messages += alert_messages()
    next_frame = 0.0
    for t in times:                                     # 5 fps per camera
        if t + 1e-9 < next_frame:
            continue
        next_frame = t + 0.2
        for junction, (jx, jy) in sc.JUNCTION_WORLD.items():
            plates, boxes = [], []
            for vehicle in sc.vehicles_at(t):
                distance = ((vehicle["x"] - jx) ** 2 + (vehicle["y"] - jy) ** 2) ** 0.5
                if distance < CAMERA_RANGE_M:
                    slot = len(plates)
                    # a swapped car carries ANOTHER vehicle's plate on its own body
                    shown = swap.get(vehicle["vehicle_id"], vehicle["vehicle_id"])
                    plates.append((sc.PLATE_NORM[shown], 0.9, slot) if vehicle_boxes
                                  else (sc.PLATE_NORM[shown], 0.9))
                    boxes.append({"vehicle_id": vehicle["vehicle_id"],
                                  "bbox": slot_vehicle_box(slot), "depth_m": 25.0 + distance})
            message = {"type": "camera_frame", "camera_id": f"CAM_{junction}_01",
                       "junction_id": junction, "timestamp_sim": round(t, 6),
                       "frame": int(t / 0.05), "image": frame_bytes(plates)}
            if vehicle_boxes:
                message["vehicles"] = boxes
            messages.append((t, message))
    messages.sort(key=lambda item: item[0])

    for _ in range(repeat):
        next_tick = 0.0
        for ts, message in messages:
            kind = message["type"]
            if kind == "rfid_reading":
                service.on_rfid_message(message)
                if resend_rfid:                     # the transport re-sends every report
                    service.on_rfid_message(dict(message))
            elif kind == "crash_alert":
                service.on_crash_alert(dict(message))
            else:
                service.on_camera_frame(message)
            if ts >= next_tick:
                service.tick()
                next_tick = ts + tick_every
        for extra in range(1, 12):                      # let every window close
            service.tick(now_ts=duration + extra)
    return service, store, events, fake


def final_by_id(rows, key="id"):
    out = {}
    for row in rows:
        out[row[key]] = {**out.get(row[key], {}), **row}
    return out


def vision_by_sighting(store):
    sightings = final_by_id(store.of("sighting"))
    matches = final_by_id(store.of("vision_match"), key="sighting_id")
    out = defaultdict(list)
    for sighting_id, match in matches.items():
        sighting = sightings[sighting_id]
        out[(sighting["epc"], sighting["junction_id"])].append(match)
    return sightings, out


class TestScenarios:
    def test_expected_scenario(self, tmp_path):
        service, store, events, fake = run_scenario(tmp_path)
        assert service.counters["errors"] == 0, service.last_error

        # one incident, watchlist A and B
        assert len({row["id"] for row in store.of("incident")}) == 1
        involved = {row["plate_norm"] for row in store.of("incident_vehicle")
                    if row["role"] == ROLE_INVOLVED}
        assert involved == {"KA01AT4521", "MH12BR7814"}

        sightings, vision = vision_by_sighting(store)
        seen = {(row["epc"], row["junction_id"]) for row in sightings.values()}
        # B confirmed at J02 and again at J03; A never leaves J01; C-H never watched
        assert (EPC["B"], "J02") in seen and (EPC["B"], "J03") in seen
        assert all(epc == EPC["B"] for epc, _ in seen)
        for junction in ("J02", "J03"):
            statuses = [m["status"] for m in vision[(EPC["B"], junction)]]
            assert STATUS_VISION_CONFIRMED in statuses, (junction, statuses)
            confirmed = [m for m in vision[(EPC["B"], junction)]
                         if m["status"] == STATUS_VISION_CONFIRMED][0]
            assert confirmed["rfid_plate"] == confirmed["anpr_plate"] == "MH12BR7814"
            assert confirmed["camera_id"] == f"CAM_{junction}_01"
            assert "number_plate_detector.pt" in confirmed["anpr_model"]
            assert "confirm conf>=" in confirmed["anpr_model"]
        # uninvolved plates that shared the junction with B are recorded, never matched
        seen_j02 = {p for m in vision[(EPC["B"], "J02")] for p in m["all_plates_seen"]}
        seen_j03 = {p for m in vision[(EPC["B"], "J03")] for p in m["all_plates_seen"]}
        assert "GJ05FP3419" in seen_j02 and "AP16GQ8273" in seen_j03
        assert "KA01AT4521" not in seen_j02 | seen_j03       # A never left J01

        # exactly 2 sightings: B at J02 and B at J03 (drop-outs merged)
        assert sorted(row["junction_id"] for row in sightings.values()) == ["J02", "J03"]

        # the ANPR was blind: only the frame (and an OCR layout hint) went in
        assert fake.calls > 0
        assert all(set(kwargs) <= {"two_line_aspect"} for kwargs in fake.seen_kwargs)
        assert not any("MH12BR7814" in str(kwargs) for kwargs in fake.seen_kwargs)

        # ONE portal row per sighting: versions rise, exactly one final event
        results = [e for e in events if e["type"] == "vision_match_result"]
        for sighting_id in sightings:
            versions = [e["version"] for e in results if e["sighting_id"] == sighting_id]
            assert versions == sorted(versions) and len(set(versions)) == len(versions)
            assert sum(1 for e in results if e["sighting_id"] == sighting_id and e["final"]) == 1
        hits = [e for e in events if e["type"] == "watchlist_rfid_hit"]
        assert all(e["version"] == 0 and e["status"] == "AWAITING_VISION" for e in hits)
        assert len(hits) == 2

        # portal: one incident_created; every vision result follows a hit for
        # the same tag and junction (the hit is sent before vision confirms)
        types = [e["type"] for e in events]
        assert types.count("incident_created") == 1
        assert types.index("incident_created") < types.index("watchlist_rfid_hit")
        for index, event in enumerate(events):
            if event["type"] == "vision_match_result":
                assert any(e["type"] == "watchlist_rfid_hit" and e["epc"] == event["epc"] and
                           e["junction_id"] == event["junction_id"] for e in events[:index])

        # every sighting closed and finalized with its counts
        assert all(row["closed"] for row in sightings.values())

    def test_evidence_files_and_links(self, tmp_path):
        _, store, _, _ = run_scenario(tmp_path)
        match_ids = {row["id"] for row in store.of("vision_match")}
        evidence = store.of("evidence")
        vision_evidence = [row for row in evidence if row["owner"] == "vision_match"]
        assert vision_evidence
        # regression: every evidence row points at a vision_match row that exists
        assert {row["vision_match_id"] for row in vision_evidence} <= match_ids
        kinds = {row["kind"] for row in vision_evidence}
        assert {"hero_frame", "plate_crop", "strip_frame"} <= kinds
        paths = [row["path"] for row in evidence]
        assert len(paths) == len(set(paths)), "an evidence file was written twice"
        for row in evidence:
            path = Path(row["path"])
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
            assert path.parent.parent.name == row["incident_id"]     # <incident>/<junction>/
        # strip: at most 3 DISTINCT frames per sighting (time gap honoured)
        per_match = defaultdict(list)
        for row in vision_evidence:
            if row["kind"] == "strip_frame":
                per_match[row["vision_match_id"]].append(row["frame_ts"])
        assert per_match and max(len(v) for v in per_match.values()) <= 3
        for stamps in per_match.values():
            stamps = sorted(stamps)
            assert all(b - a >= 0.6 - 1e-9 for a, b in zip(stamps, stamps[1:]))
        # crash-junction frames around t_crash (nice-to-have)
        assert any(row["kind"] == "crash_frame" and row["owner"] == "incident"
                   for row in evidence)

    def test_legacy_format_gives_the_same_verdicts(self, tmp_path):
        service, store, _, _ = run_scenario(tmp_path, fmt="legacy")
        assert service.counters["errors"] == 0
        _, vision = vision_by_sighting(store)
        for junction in ("J02", "J03"):
            assert STATUS_VISION_CONFIRMED in [m["status"] for m in vision[(EPC["B"], junction)]]
        assert store.of("rfid_report") == []          # legacy has no seq to archive on

    def test_duplicate_delivery_changes_nothing(self, tmp_path):
        _, clean, _, _ = run_scenario(tmp_path / "a")
        service, doubled, _, _ = run_scenario(tmp_path / "b", resend_rfid=True)
        assert service.counters["duplicates"] == len(clean.of("rfid_report")) > 0
        assert len(clean.of("rfid_report")) == len(doubled.of("rfid_report"))

        def summary(store):
            return sorted((row["epc"], row["junction_id"], row["report_count"],
                           row["tag_seen_count"]) for row in final_by_id(
                               store.of("sighting")).values())
        assert summary(clean) == summary(doubled)

    def test_tag_swap_is_not_confirmed(self, tmp_path):
        service, store, _, _ = run_scenario(tmp_path, name="tag_swap", swap={"B": "D"})
        assert service.counters["errors"] == 0
        _, vision = vision_by_sighting(store)
        for junction in ("J02", "J03"):
            final = vision[(EPC["B"], junction)][-1]
            assert final["status"] == STATUS_NOT_CONFIRMED
            assert final["rfid_plate"] == "MH12BR7814"
            assert "KL07DL9182" in final["all_plates_seen"]
            assert "MH12BR7814" not in final["all_plates_seen"]

    @pytest.mark.parametrize("fmt", ["v2", "legacy"])
    def test_missed_rfid_pass_gives_no_sighting_and_no_error(self, tmp_path, fmt):
        service, store, _, _ = run_scenario(tmp_path, name="missed_pass", fmt=fmt)
        assert service.counters["errors"] == 0
        sightings = final_by_id(store.of("sighting")).values()
        junctions = {row["junction_id"] for row in sightings if row["epc"] == EPC["B"]}
        assert "J02" not in junctions and "J03" in junctions

    def test_unregistered_epc(self, tmp_path):
        service, store, _, _ = run_scenario(tmp_path, name="unregistered")
        assert service.counters["errors"] == 0
        rows = [row for row in store.of("rfid_report") if row["epc"] == UNKNOWN_EPC]
        assert rows
        assert all(row["plate_norm"] is None and row["registry_status"] == UNREGISTERED_TAG
                   for row in rows)
        assert UNKNOWN_EPC not in {row["epc"] for row in store.of("sighting")}

    def test_sparse_ticks_never_starve_vision(self, tmp_path):
        # A stalled ticker (or a replay faster than real time) must not let the
        # frame ring drop the frames a pending sighting still needs.
        service, store, _, _ = run_scenario(tmp_path, tick_every=20.0)
        assert service.counters["errors"] == 0
        sightings, vision = vision_by_sighting(store)
        matches = final_by_id(store.of("vision_match"), key="sighting_id")
        assert set(matches) == set(sightings), "every sighting gets a vision record"
        for junction in ("J02", "J03"):
            assert STATUS_VISION_CONFIRMED in [m["status"] for m in vision[(EPC["B"], junction)]]

    def test_two_runs_same_alert_ids(self, tmp_path):
        service, store, events, _ = run_scenario(tmp_path, repeat=2)
        assert service.counters["errors"] == 0
        incidents = final_by_id(store.of("incident"))
        assert len(incidents) == 2
        assert len({row["run_id"] for row in incidents.values()}) == 2
        assert [e["type"] for e in events].count("incident_created") == 2
        # each run confirms B at J02 and J03 against its OWN incident
        sightings = final_by_id(store.of("sighting")).values()
        per_incident = defaultdict(set)
        for row in sightings:
            per_incident[row["incident_id"]].add((row["epc"], row["junction_id"]))
        assert all({(EPC["B"], "J02"), (EPC["B"], "J03")} <= found
                   for found in per_incident.values())


# =====================================================================
# the real ANPR model (auto-skipped if it is not on this machine)
# =====================================================================

MODEL = ROOT / "member3" / "backend" / "models" / "number_plate" / "number_plate_detector.pt"
VIDEO = ROOT / "member3" / "media" / "videos" / \
    "camera_junction_1_v22_final_visible_anpr_recording.mp4"


def test_tiled_merge_prefers_the_whole_plate_over_fragments():
    from app.services.anpr_adapter import _suppress_overlaps

    whole = ((406, 284, 730, 386), 0.70)          # full-frame pass
    left_half = ((408, 291, 640, 388), 0.90)      # tile fragments score higher
    right_half = ((512, 289, 732, 390), 0.85)
    small_far = ((1100, 200, 1140, 212), 0.40)    # a distant plate only a tile found
    kept = _suppress_overlaps([left_half, whole, right_half, small_far], threshold=0.45)
    boxes = sorted(box for box, _ in kept)
    assert boxes == [whole[0], small_far[0]]


@pytest.mark.skipif(not MODEL.is_file(), reason="ANPR model file not found")
def test_real_anpr_model_through_the_adapter():
    import cv2

    from app.services.anpr_adapter import get_anpr_adapter

    frame = None
    if VIDEO.is_file():
        capture = cv2.VideoCapture(str(VIDEO))
        capture.set(cv2.CAP_PROP_POS_FRAMES, 30)
        ok, frame = capture.read()
        capture.release()
        frame = frame if ok else None
    if frame is None:
        from simulate_carla_feed import synthetic_frame

        frame = synthetic_frame(["MH 12 BR 7814"])

    adapter = get_anpr_adapter()
    started = time.perf_counter()
    reads = adapter.detect_and_read(frame)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    assert isinstance(reads, list)
    for plate in reads:
        assert len(plate.box) == 4
        assert 0.0 <= plate.det_confidence <= 1.0
        assert 0.0 <= plate.ocr_confidence <= 1.0
    status = adapter.status()
    assert status["backend"] and status["frames"] >= 1
    print(f"\nANPR {status['backend']} imgsz={status['imgsz']}: {len(reads)} plate(s), "
          f"first call {elapsed_ms:.0f} ms (includes load), reads="
          f"{[p.plate_norm or p.raw_ocr for p in reads]}")
