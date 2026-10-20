"""Capture and audit a CARLA RFID stream (Member 1 -> backend WebSocket).

Part 0 tooling for the RFID cross-verification feature. It does three things:

  1. ``--url``      listen to the live CARLA WebSocket and record every message
                    it sees (raw JSONL), so the stream can be audited offline.
  2. ``--jsonl``    audit an already-recorded raw capture.
  3. ``--csv``      audit Member 1's ``rfid_readings.csv`` directly (works with
                    no CARLA, no WebSocket and no backend).

The audit reports the fields present, the distinct junction/reader/EPC values,
reads per junction and per vehicle, the read-interval distribution, and - when a
live capture AND the csv are both available - the number of published messages
against the number of csv rows (the difference is the drop rate).

Run:
    python tools/capture_rfid.py --url ws://127.0.0.1:8001/ws/carla/cameras --seconds 60
    python tools/capture_rfid.py --jsonl runtime/rfid_capture.jsonl --csv rfid_readings.csv
    python tools/capture_rfid.py --csv "<OUT_DIR>/multimodal_evidence/rfid_readings.csv"
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

RFID_TYPES = {"rfid_reading", "rfid_tag_report"}


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def _interval_report(intervals: list[float]) -> dict[str, float]:
    if not intervals:
        return {"count": 0}
    return {
        "count": len(intervals),
        "min_s": round(min(intervals), 4),
        "p50_s": round(statistics.median(intervals), 4),
        "p90_s": round(_percentile(intervals, 0.90), 4),
        "max_s": round(max(intervals), 4),
        "mean_s": round(statistics.fmean(intervals), 4),
    }


def _record_time(record: dict) -> float | None:
    """Event time of a report: v2 uses last_seen_ts, legacy the emission stamp."""
    for key in ("last_seen_ts", "timestamp_sim", "timestamp_reader", "timestamp"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def audit_records(records: Iterable[dict], csv_path: Path | None = None,
                  csv_rows: int | None = None) -> dict[str, Any]:
    """Produce the Part 0 audit from a sequence of RFID messages."""
    records = list(records)
    rfid = [r for r in records if r.get("type") in RFID_TYPES] or list(records)

    field_counter: Counter = Counter()
    for record in rfid:
        field_counter.update(record.keys())

    junctions = Counter()
    readers = Counter()
    epcs = Counter()
    per_vehicle = Counter()
    sequences: dict[str, list[float]] = defaultdict(list)
    statuses = Counter()
    schemas = Counter()

    for record in rfid:
        junction = record.get("junction_id")
        junction_label = f"J{int(junction):02d}" if isinstance(junction, (int, float)) else str(junction)
        junctions[junction_label] += 1
        readers[str(record.get("reader_id"))] += 1
        if record.get("epc"):
            epcs[str(record["epc"])] += 1
        if record.get("vehicle_id"):
            per_vehicle[str(record["vehicle_id"])] += 1
        statuses[str(record.get("status", "n/a"))] += 1
        schemas[str(record.get("schema", "legacy"))] += 1

        when = _record_time(record)
        if when is not None:
            sequences[str(record.get("reader_id"))].append(when)

    intervals: list[float] = []
    for times in sequences.values():
        times.sort()
        intervals.extend(b - a for a, b in zip(times, times[1:]) if b >= a)

    rows = csv_rows
    if rows is None and csv_path is not None and csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = sum(1 for _ in csv.DictReader(handle))

    report: dict[str, Any] = {
        "messages": len(records),
        "rfid_messages": len(rfid),
        "message_types": dict(Counter(str(r.get("type")) for r in records)),
        "schemas": dict(schemas),
        "fields": dict(field_counter.most_common()),
        "distinct_junctions": len(junctions),
        "reads_per_junction": dict(sorted(junctions.items())),
        "distinct_readers": len(readers),
        "reads_per_reader": dict(sorted(readers.items())),
        "distinct_epcs": len(epcs),
        "reads_per_epc": dict(sorted(epcs.items())),
        "reads_per_vehicle": dict(sorted(per_vehicle.items())),
        "statuses": dict(statuses),
        "read_interval_s": _interval_report(intervals),
    }

    if rows is not None:
        report["csv_rows"] = rows
        report["publish_vs_csv"] = {
            "published_messages": len(rfid),
            "csv_rows": rows,
            "missing_from_stream": max(0, rows - len(rfid)),
            "drop_rate_pct": round(100.0 * max(0, rows - len(rfid)) / rows, 2) if rows else 0.0,
        }
    return report


def read_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def csv_to_records(path: Path) -> list[dict]:
    """Member 1's rfid_readings.csv -> records in the published field naming."""
    records = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            records.append({
                "type": "rfid_reading",
                "timestamp_sim": row.get("timestamp_sim"),
                "event_id": row.get("event_id"),
                "junction_id": row.get("junction_id"),
                "reader_id": row.get("reader_id"),
                "vehicle_id": row.get("vehicle_id"),
                "plate_number": row.get("plate_number"),
                "epc": row.get("epc"),
                "distance_m": row.get("distance_m"),
                "speed_kmh": row.get("speed_kmh"),
                "confidence": row.get("confidence"),
                "status": row.get("status"),
            })
    return records


def capture_live(url: str, seconds: float, out_path: Path) -> list[dict]:
    """Listen to the CARLA WebSocket and record every message as raw JSONL."""
    try:
        from websocket import create_connection  # websocket-client
    except ImportError:
        try:
            import websockets.sync.client as ws_sync
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise SystemExit(
                "Need a WebSocket client: pip install websocket-client"
            ) from exc
        return _capture_live_websockets(ws_sync, url, seconds, out_path)

    import time

    connection = create_connection(url, timeout=10)
    records: list[dict] = []
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            try:
                raw = connection.recv()
            except Exception:
                break
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            # Do not keep megabytes of JPEG in the capture.
            if isinstance(message, dict) and message.get("type") == "camera_frame":
                message = {k: v for k, v in message.items() if k != "image"}
                message["image"] = "<dropped>"
            records.append(message)
    finally:
        connection.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return records


def _capture_live_websockets(ws_sync, url: str, seconds: float, out_path: Path) -> list[dict]:
    import time

    records: list[dict] = []
    deadline = time.monotonic() + seconds
    with ws_sync.connect(url) as connection:
        while time.monotonic() < deadline:
            try:
                raw = connection.recv(timeout=5)
            except Exception:
                break
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("type") == "camera_frame":
                message = {k: v for k, v in message.items() if k != "image"}
                message["image"] = "<dropped>"
            records.append(message)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return records


def print_report(report: dict[str, Any]) -> None:
    print("=" * 72)
    print("RFID STREAM AUDIT (Part 0)")
    print("=" * 72)
    print(f"messages received          : {report['messages']}")
    print(f"  of which RFID            : {report['rfid_messages']}")
    print(f"  rfid schema              : {report.get('schemas')}")
    print(f"message types              : {report['message_types']}")
    print()
    print("fields seen (count):")
    for field, count in report["fields"].items():
        print(f"  {field:24s} {count}")
    print()
    print(f"distinct junctions         : {report['distinct_junctions']}  {report['reads_per_junction']}")
    print(f"distinct readers           : {report['distinct_readers']}  {report['reads_per_reader']}")
    print(f"distinct EPCs              : {report['distinct_epcs']}")
    print(f"reads per vehicle          : {report['reads_per_vehicle']}")
    print(f"statuses                   : {report['statuses']}")
    interval = report["read_interval_s"]
    if interval.get("count"):
        print("read interval per reader (s): "
              f"min={interval['min_s']} p50={interval['p50_s']} "
              f"p90={interval['p90_s']} max={interval['max_s']} mean={interval['mean_s']}")
    else:
        print("read interval per reader (s): n/a")
    if "publish_vs_csv" in report:
        drop = report["publish_vs_csv"]
        print()
        print("publish vs csv:")
        print(f"  published messages       : {drop['published_messages']}")
        print(f"  rows in rfid_readings.csv: {drop['csv_rows']}")
        print(f"  ever written, never sent : {drop['missing_from_stream']} "
              f"({drop['drop_rate_pct']}%)")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="live CARLA WebSocket URL to record")
    parser.add_argument("--seconds", type=float, default=60.0, help="capture duration")
    parser.add_argument("--out", type=Path, default=Path("runtime/rfid_capture.jsonl"),
                        help="raw capture output (JSONL)")
    parser.add_argument("--jsonl", type=Path, help="audit an existing raw capture")
    parser.add_argument("--csv", type=Path, help="Member 1's rfid_readings.csv")
    parser.add_argument("--json", type=Path, help="also write the audit report as JSON")
    args = parser.parse_args(argv)

    records: list[dict] = []
    csv_rows = None
    if args.url:
        print(f"[capture] listening on {args.url} for {args.seconds:.0f}s ...")
        records = capture_live(args.url, args.seconds, args.out)
        print(f"[capture] {len(records)} messages -> {args.out}")
    if args.jsonl:
        records.extend(read_jsonl(args.jsonl))
    if args.csv:
        csv_rows = len(csv_to_records(args.csv))
        if not records:
            records = csv_to_records(args.csv)
    if not records:
        parser.error("nothing to audit: pass --url, --jsonl or --csv")

    report = audit_records(records, csv_path=args.csv, csv_rows=csv_rows)
    print_report(report)
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"[capture] report -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
