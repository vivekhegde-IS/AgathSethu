"""Incident evidence API: the crash, the per-junction RFID snapshots, the
next-junction sightings and their vision verdicts, with the evidence files.

Read-only. Every window in the response is SIM event time (``*_ts`` fields) -
never arrival or emission time.

  GET /api/incidents                        runs (grouped), filter by source, paginated
  GET /api/incidents/{id}                   full timeline + snapshot panels + sighting cards
  GET /api/incidents/{id}/tracks            per watchlist vehicle: crash zone -> junctions
  GET /api/incidents/{id}/evidence/{eid}    streams one evidence image
  GET /api/rfid/health                      what the RFID FUSION badge shows
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, exists, func, or_, true
from sqlalchemy.orm import Session

from app.core.config import data_dir, settings
from app.core.database import get_db
from app.core.security import verify_password
from app.dependencies.deps import require_authority
from app.models.models import (
    CrashZoneRfid,
    EvidenceFile,
    Incident,
    IncidentAlert,
    IncidentVehicle,
    RfidSighting,
    User,
    VisionMatch,
)
from app.services.plate_validation import STATE_CODES, format_plate
from app.services.rfid.config import JUNCTION_WORLD, ROLE_FLED, STATUS_RANK
from app.services.notification_service import IST, incident_reference, junction_label
from app.services.rfid.evidence import KIND_PRIMARY, KIND_PRIMARY_PLATE, KIND_PRIMARY_RAW

# Authority only: crash records, plates and evidence images are never public.
router = APIRouter(prefix="/api/incidents", tags=["Incidents"],
                   dependencies=[Depends(require_authority)])
health_router = APIRouter(prefix="/api/rfid", tags=["Incidents"],
                          dependencies=[Depends(require_authority)])

EVIDENCE_DIR = data_dir() / "runtime" / "incident_evidence"

# Evidence kinds (older rows used "annotated_frame" for the card image).
HERO_KINDS = ("hero_frame", "annotated_frame")


def _iso(value):
    return value.isoformat() if value else None


def _run_label(started_at, crash_ts_sim) -> str:
    when = started_at.strftime("%d %b %H:%M:%S") if started_at else "unknown start"
    crash = f"crash t={crash_ts_sim:.1f}s" if crash_ts_sim is not None else "crash time unknown"
    return f"{when} · {crash}"


def _state(plate: str | None) -> str | None:
    return STATE_CODES.get((plate or "")[:2])


def _incident_summary(db: Session, incident: Incident) -> dict:
    vehicles = db.query(IncidentVehicle).filter(IncidentVehicle.incident_id == incident.id).all()
    sightings = db.query(RfidSighting).filter(RfidSighting.incident_id == incident.id).all()
    matches = {}
    if sightings:
        matches = {
            row.sighting_id: row
            for row in db.query(VisionMatch)
            .filter(VisionMatch.sighting_id.in_([sighting.id for sighting in sightings]))
            .all()
        }
    statuses = [matches[s.id].status for s in sightings if s.id in matches]
    return {
        "id": str(incident.id),
        "run_id": incident.run_id,
        "source": incident.source,
        "archived": bool(incident.archived),
        "run_started_at": _iso(incident.run_started_at),
        "label": _run_label(incident.run_started_at or incident.created_at, incident.crash_ts_sim),
        "status": incident.status,
        "severity": incident.severity,
        "incident_type": incident.incident_type,
        "crash_ts_sim": incident.crash_ts_sim,
        "crash_frame": incident.crash_frame,
        "crash_junction": incident.crash_junction,
        "world": {"x": incident.world_x, "y": incident.world_y, "z": incident.world_z},
        "gps": {"lat": incident.latitude, "lon": incident.longitude},
        "created_at": _iso(incident.created_at),
        "plates": sorted({vehicle.plate_norm for vehicle in vehicles if vehicle.plate_norm}),
        "vehicle_count": len(vehicles),
        "sighting_count": len(sightings),
        "vision_confirmed": sum(1 for status in statuses if status == "VISION_CONFIRMED"),
        "vision_probable": sum(1 for status in statuses if status == "PROBABLE_MATCH"),
        **_resolution(db, incident, vehicles),
    }


def camera_stream_for(junction_id: str | None) -> str | None:
    """The WebRTC stream path of the camera covering a junction (WEBRTC_STREAMS)."""
    for pair in settings.WEBRTC_STREAMS.split(","):
        if ":" in pair:
            junction, path = (part.strip() for part in pair.split(":", 1))
            if junction_id and junction == junction_id:
                return path
    return None


def _resolution(db: Session, incident: Incident, vehicles) -> dict:
    """Operator-facing fields: reference, plates of the involved vehicles,
    resolution state and who resolved it."""
    resolver = db.get(User, incident.resolved_by) if incident.resolved_by else None
    involved = sorted({v.plate_norm for v in vehicles if v.plate_norm and v.role == "involved"})
    return {
        "reference": incident_reference(incident.id),
        "location": junction_label(incident.crash_junction),
        "involved_plates": involved,
        "involved_plates_display": [format_plate(p) for p in involved],
        "resolved": incident.status == "resolved",
        "resolved_at": _iso(incident.resolved_at),
        "resolved_by_name": resolver.full_name if resolver else None,
        "resolution_note": incident.resolution_note,
        "camera_stream": camera_stream_for(incident.crash_junction),
        # "View live feed" only for an unresolved crash of the run streaming right now
        "live_feed": bool(incident.status != "resolved" and incident.run_id
                          and incident.run_id == _live_run_id() and _feed_live(incident.crash_junction)),
    }


def _ist_day_start() -> datetime:
    """00:00 today in Asia/Kolkata, as an aware datetime."""
    today = datetime.now(IST).date()
    return datetime.combine(today, time.min, tzinfo=IST)


def _board_query(db: Session):
    return (db.query(Incident)
            .filter(Incident.dedupe_key.isnot(None), Incident.source == "live",
                    Incident.archived.is_(False)))


def _search_clause(q: str):
    """Incident ID (the INC-xxxxxxxx reference, full or part) or the plate of
    any vehicle recorded on the incident (full or part; spacing/case ignored)."""
    text = re.sub(r"[^A-Z0-9]", "", q.upper())
    if not text:
        return true()
    clauses = [exists().where(IncidentVehicle.incident_id == Incident.id,
                              IncidentVehicle.plate_norm.contains(text, autoescape=True))]
    hex_part = re.sub(r"^INC", "", text).lower()
    if hex_part and re.fullmatch(r"[0-9a-f]+", hex_part):
        clauses.append(func.replace(cast(Incident.id, String), "-", "").like(f"%{hex_part}%"))
    return or_(*clauses)


def _live_run_id() -> str | None:
    """run_id of the CARLA run the backend is receiving now, if any."""
    from app.services.rfid.service import peek_service

    service = peek_service()
    return service.runs.run_id if service is not None else None


def _feed_live(junction_id: str | None) -> bool:
    from app.routers.carla_ws import camera_feed_live

    return camera_feed_live(junction_id)


@router.get("/board")
async def incident_board(
    view: str = Query("radar", description="radar | records"),
    status: str = Query("all", description="records only: all | resolved | unresolved"),
    day: date | None = Query(None, alias="date", description="records only: crashes on this IST day (YYYY-MM-DD)"),
    q: str | None = Query(None, max_length=40,
                          description="records only: incident ID (INC-xxxxxxxx, full or part) or a plate of either vehicle"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Flat incident lists for the operator pages.

    radar:   only incidents that happened today (since 00:00 IST): unresolved
             ones as active, resolved ones under "resolved today". At the next
             IST midnight they all leave the radar and stay in records.
    records: every incident (Evidence Records), newest first, paginated;
             optionally only one IST calendar day (?date=YYYY-MM-DD) and/or a
             search (?q=) on the incident ID or the plate of any involved vehicle.
    """
    query = _board_query(db)
    if view == "radar":
        query = query.filter(Incident.created_at >= _ist_day_start())
        rows = query.order_by(Incident.created_at.desc()).all()
        items = [_incident_summary(db, row) for row in rows]
        return {
            "view": "radar",
            "day_start": _ist_day_start().isoformat(),
            "active": [i for i in items if not i["resolved"]],
            "resolved_today": [i for i in items if i["resolved"]],
        }
    if status == "resolved":
        query = query.filter(Incident.status == "resolved")
    elif status == "unresolved":
        query = query.filter(Incident.status != "resolved")
    if day is not None:
        start = datetime.combine(day, time.min, tzinfo=IST)
        query = query.filter(Incident.created_at >= start, Incident.created_at < start + timedelta(days=1))
    if q:
        query = query.filter(_search_clause(q))
    total = query.count()
    rows = (query.order_by(Incident.created_at.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return {"view": "records", "total": total, "page": page, "page_size": page_size,
            "items": [_incident_summary(db, row) for row in rows]}


class ResolveRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    note: str | None = Field(default=None, max_length=2000)


@router.post("/{incident_id}/resolve")
async def resolve_incident(incident_id: str, body: ResolveRequest,
                           officer: User = Depends(require_authority), db: Session = Depends(get_db)):
    """Mark an incident resolved. The officer re-enters their own password,
    checked against their stored hash; who, when and the note are recorded."""
    incident = _load(db, incident_id)
    if not verify_password(body.password, officer.password_hash):
        raise HTTPException(status_code=403, detail="Password is incorrect.")
    if incident.status == "resolved":
        raise HTTPException(status_code=409, detail="Incident is already resolved.")
    incident.status = "resolved"
    incident.resolved_at = datetime.now(timezone.utc)
    incident.resolved_by = officer.id
    incident.resolution_note = (body.note or "").strip() or None
    db.commit()
    db.refresh(incident)
    return _incident_summary(db, incident)


@router.get("")
async def list_incidents(
    source: str = Query("live", description="live | replay | synthetic | all"),
    include_archived: bool = Query(False),
    run_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100, description="runs per page"),
    limit: int = Query(500, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    """Feature incidents grouped by run, newest run first.

    Defaults to LIVE runs only (replays and synthetic simulator runs are behind
    the ``source`` filter) and hides archived incidents.
    """
    query = db.query(Incident).filter(Incident.dedupe_key.isnot(None))
    if source != "all":
        query = query.filter(Incident.source == source)
    if not include_archived:
        query = query.filter(Incident.archived.is_(False))
    if run_id:
        query = query.filter(Incident.run_id == run_id)
    incidents = query.order_by(Incident.created_at.desc()).limit(limit).all()

    runs: dict[str, dict] = {}
    for incident in incidents:
        key = incident.run_id or f"no-run-{incident.id}"
        run = runs.get(key)
        started = incident.run_started_at or incident.created_at
        if run is None:
            run = runs[key] = {"run_id": incident.run_id, "source": incident.source,
                               "started_at": started, "incidents": []}
        run["started_at"] = min(run["started_at"], started) if run["started_at"] else started
        run["incidents"].append(_incident_summary(db, incident))
    ordered = sorted(runs.values(), key=lambda r: r["started_at"] or 0, reverse=True)
    total = len(ordered)
    page_runs = ordered[(page - 1) * page_size: page * page_size]
    for run in page_runs:
        first = min(run["incidents"], key=lambda i: i["crash_ts_sim"] or 0)
        run["label"] = _run_label(run["started_at"], first["crash_ts_sim"])
        run["started_at"] = _iso(run["started_at"])

    counts = defaultdict(int)
    for (value,) in db.query(Incident.source).filter(Incident.dedupe_key.isnot(None),
                                                     Incident.archived.is_(False)).all():
        counts[value or "unknown"] += 1
    return {
        "runs": page_runs,
        "total_runs": total,
        "page": page,
        "page_size": page_size,
        "source": source,
        "source_counts": dict(counts),
        # flat list kept for older callers
        "incidents": [incident for run in page_runs for incident in run["incidents"]],
    }


def _evidence_ref(row: EvidenceFile, incident_id: str) -> dict:
    return {
        "id": str(row.id),
        "kind": row.kind,
        "url": f"/api/incidents/{incident_id}/evidence/{row.id}",
        "sha256": row.sha256,
        "width": row.width,
        "height": row.height,
        "score": row.score,
        "frame_ts": row.frame_ts,
        "junction_id": row.junction_id,
        "created_at": _iso(row.created_at),
    }


def _vision_payload(match: VisionMatch | None, files: list[EvidenceFile],
                    incident_id: str) -> dict | None:
    if match is None:
        return None
    by_kind = defaultdict(list)
    for row in sorted(files, key=lambda r: r.created_at or 0):
        by_kind[row.kind].append(row)
    heroes = [row for kind in HERO_KINDS for row in by_kind.get(kind, [])]
    hero = max(heroes, key=lambda r: r.created_at or 0) if heroes else None
    crop = by_kind.get("plate_crop", [])[-1] if by_kind.get("plate_crop") else None
    strip = by_kind.get("strip_frame", [])[:3]
    rejected = match.rejected_reads
    if rejected is None and match.all_plates_seen:
        # rows written before the plate rules: keep only what passes them now
        from app.services.rfid.plate_rules import check_text

        valid = [p for p in match.all_plates_seen if check_text(p)["valid"]]
        rejected = [{"raw": p, "reasons": check_text(p)["reasons"]}
                    for p in match.all_plates_seen if p not in valid]
        plates_seen = valid
    else:
        plates_seen = match.all_plates_seen or []
    return {
        "id": str(match.id),
        "status": match.status,
        "version": match.version or 0,
        "finalized": bool(match.finalized),
        "rule_assisted": bool(match.rule_assisted),
        "match_reason": match.match_reason,
        "rfid_plate": match.rfid_plate,
        "rfid_plate_display": format_plate(match.rfid_plate),
        "rfid_state_name": _state(match.rfid_plate),
        "anpr_plate": match.anpr_plate,
        "anpr_plate_display": format_plate(match.anpr_plate),
        "anpr_state_name": _state(match.anpr_plate),
        "anpr_confidence": match.anpr_confidence,
        "edit_distance": match.edit_distance,
        "diff": match.diff or [],
        "camera_id": match.camera_id,
        "best_frame_ts": match.best_frame_ts,
        "time_delta_s": match.time_delta_s,
        "frames_used": match.frames_used,
        "cluster_frames": match.cluster_frames,
        "max_plate_px": match.max_plate_px,
        "plates_seen": plates_seen,
        "all_plates_seen": plates_seen,
        "other_vehicles": match.other_vehicles or [p for p in plates_seen if p != match.anpr_plate],
        "rejected_reads": rejected or [],
        "per_frame": match.per_frame or [],
        "anpr_model": match.anpr_model,
        "hero": _evidence_ref(hero, incident_id) if hero else None,
        "plate_crop": _evidence_ref(crop, incident_id) if crop else None,
        "strip": [_evidence_ref(row, incident_id) for row in strip],
        "evidence": [_evidence_ref(row, incident_id) for row in files],
    }


def _suspect_reads(match, vehicle_id: str | None) -> list[dict]:
    """Every plate read of this match that sat ON the suspect (supporting
    candidates). Rows written before association metadata have no ``owner``:
    then a read counts only if it is the match's own attached plate."""
    reads = []
    for frame in (match.per_frame or []) if match is not None else []:
        for read in frame.get("reads") or []:
            if "owner" in read:
                if not vehicle_id or read.get("owner") != vehicle_id:
                    continue
            elif not match.anpr_plate or read.get("corrected") != match.anpr_plate:
                continue
            reads.append({"ts": frame.get("ts"), "raw": read.get("raw"),
                          "corrected": read.get("corrected"), "valid": read.get("valid"),
                          "mean_conf": read.get("mean_conf"), "width_px": read.get("width_px"),
                          "det_confidence": read.get("det_confidence")})
    return reads


def best_evidence_by_junction(incident_id: str, sightings, matches: dict, files_by_match: dict,
                              vehicle_by_epc: dict) -> list[dict]:
    """ONE evidence card per (suspect vehicle, junction) on the suspect's route.

    The primary item is the highest-scoring ``primary_frame`` written for that
    junction (a better frame later adds a higher-scoring row; older files are
    kept and are listed as supporting images, never deleted). Rows from before
    primary evidence existed fall back to the newest hero image.
    """
    groups: dict = defaultdict(list)
    for sighting in sightings:
        groups[(sighting.epc, sighting.junction_id)].append(
            (sighting, matches.get(sighting.id)))
    cards = []
    for (epc, junction), items in groups.items():
        vehicle_id = vehicle_by_epc.get(epc)
        match_rows = [match for _, match in items if match is not None]
        files = [row for match in match_rows for row in files_by_match.get(str(match.id), [])]

        primaries = [row for row in files if row.kind == KIND_PRIMARY]
        legacy = False
        best = max(primaries, key=lambda r: ((r.score or 0.0), str(r.created_at or ""))) \
            if primaries else None
        if best is None:
            heroes = [row for row in files if row.kind in HERO_KINDS]
            best = max(heroes, key=lambda r: str(r.created_at or "")) if heroes else None
            legacy = best is not None

        def companion(kind):
            if best is None or legacy:
                return None
            same = [row for row in files if row.kind == kind
                    and str(row.vision_match_id) == str(best.vision_match_id)
                    and row.frame_ts == best.frame_ts]
            return max(same, key=lambda r: str(r.created_at or "")) if same else None

        # the junction's verdict: the strongest of its sightings' matches
        verdict = max(match_rows, key=lambda m: (STATUS_RANK.get(m.status, -1),
                                                 m.anpr_confidence or 0.0)) if match_rows else None
        candidates = [read for match in match_rows for read in _suspect_reads(match, vehicle_id)]
        read_at_best = None
        if best is not None and best.frame_ts is not None:
            at = [read for read in candidates
                  if read["ts"] is not None and abs(read["ts"] - best.frame_ts) < 1e-3]
            read_at_best = max(at, key=lambda r: (bool(r["valid"]), r["mean_conf"] or 0.0)) \
                if at else None
        shown = {id(best), id(companion(KIND_PRIMARY_RAW)), id(companion(KIND_PRIMARY_PLATE))}
        supporting = [row for row in files if id(row) not in shown
                      and row.kind not in (KIND_PRIMARY_RAW, KIND_PRIMARY_PLATE, "plate_crop")]
        plate_crop = companion(KIND_PRIMARY_PLATE)
        if plate_crop is None and legacy:
            crops = [row for row in files if row.kind == "plate_crop"]
            plate_crop = max(crops, key=lambda r: str(r.created_at or "")) if crops else None

        first_seen = min(s.first_seen_ts for s, _ in items)
        cards.append({
            "junction_id": junction,
            "epc": epc,
            "suspect_vehicle_id": vehicle_id,
            "rfid_plate": verdict.rfid_plate if verdict else items[0][0].plate_norm,
            "rfid_plate_display": format_plate(verdict.rfid_plate if verdict
                                               else items[0][0].plate_norm),
            "sighting_ids": [str(s.id) for s, _ in items],
            "first_seen_ts": first_seen,
            "last_seen_ts": max(s.last_seen_ts for s, _ in items),
            "status": verdict.status if verdict else None,
            "rule_assisted": bool(verdict.rule_assisted) if verdict else False,
            "match_reason": verdict.match_reason if verdict else None,
            "anpr_plate": verdict.anpr_plate if verdict else None,
            "anpr_plate_display": format_plate(verdict.anpr_plate) if verdict else None,
            "anpr_confidence": verdict.anpr_confidence if verdict else None,
            "primary": None if best is None else {
                "image": _evidence_ref(best, incident_id),
                "raw_frame": (_evidence_ref(companion(KIND_PRIMARY_RAW), incident_id)
                              if companion(KIND_PRIMARY_RAW) else None),
                "plate_crop": _evidence_ref(plate_crop, incident_id) if plate_crop else None,
                "score": best.score,
                "frame_ts": best.frame_ts,
                "read_text": (read_at_best or {}).get("corrected") or (read_at_best or {}).get("raw"),
                "read_text_display": format_plate((read_at_best or {}).get("corrected"))
                or (read_at_best or {}).get("raw"),
                "read_valid": bool((read_at_best or {}).get("valid")),
                "read_confidence": (read_at_best or {}).get("mean_conf"),
                "legacy": legacy,
            },
            "supporting": {
                "frames": len(supporting),
                "images": [_evidence_ref(row, incident_id)
                           for row in sorted(supporting, key=lambda r: (r.frame_ts or 0.0))],
                "candidate_reads": len(candidates),
                "candidates": sorted(candidates, key=lambda r: r["ts"] or 0.0),
            },
        })
    return sorted(cards, key=lambda card: (card["first_seen_ts"], card["junction_id"]))


BASIS_ESCAPE = ("Member 1 escape detection: kept moving after the crash "
                "(>= 5 km/h, >= 8 m from its crash point)")
BASIS_SIGHTING = "its RFID tag was read at another junction after the crash"


def fleeing_suspects(vehicles, sightings) -> list[dict]:
    """Which involved vehicle(s) fled. Member 1's escape report (role "fled")
    decides; without one, an involved tag read at another junction after the
    crash does. Never hard-coded, never an ANPR read."""
    involved = {v.plate_norm: v for v in vehicles if v.role != ROLE_FLED}
    fled = [v for v in vehicles if v.role == ROLE_FLED]
    out, seen = [], set()
    for vehicle in fled:
        base = involved.get(vehicle.plate_norm, vehicle)
        out.append({"plate_norm": vehicle.plate_norm, "epc": vehicle.epc or base.epc,
                    "sim_vehicle_id": vehicle.sim_vehicle_id or base.sim_vehicle_id,
                    "basis": BASIS_ESCAPE})
        seen.add(vehicle.plate_norm)
    if not out:
        sighted = {s.epc for s in sightings}
        for vehicle in involved.values():
            if vehicle.epc and vehicle.epc in sighted and vehicle.plate_norm not in seen:
                out.append({"plate_norm": vehicle.plate_norm, "epc": vehicle.epc,
                            "sim_vehicle_id": vehicle.sim_vehicle_id, "basis": BASIS_SIGHTING})
    return out


def fleeing_vehicle_summary(suspect: dict, cards: list[dict]) -> dict:
    """Header for one fleeing vehicle: its route and the overall verdict."""
    mine = [card for card in cards if card["epc"] == suspect["epc"]]
    judged = [card for card in mine if card["status"]]
    best = max(judged, key=lambda c: (STATUS_RANK.get(c["status"], -1), c["anpr_confidence"] or 0.0))         if judged else None
    return {
        **suspect,
        "plate_display": format_plate(suspect["plate_norm"]),
        "state_name": _state(suspect["plate_norm"]),
        "junctions": [card["junction_id"] for card in mine],
        "final_plate_read": best["anpr_plate"] if best else None,
        "final_plate_read_display": best["anpr_plate_display"] if best else None,
        "overall_status": best["status"] if best else None,
        "overall_reason": best["match_reason"] if best else None,
    }


def _sighting_payload(sighting: RfidSighting, match, files, incident_id) -> dict:
    return {
        "id": str(sighting.id),
        "epc": sighting.epc,
        "plate_norm": sighting.plate_norm,
        "plate_display": format_plate(sighting.plate_norm),
        "state_name": _state(sighting.plate_norm),
        "junction_id": sighting.junction_id,
        "reader_id": sighting.reader_id,
        "first_seen_ts": sighting.first_seen_ts,
        "last_seen_ts": sighting.last_seen_ts,
        "report_count": sighting.report_count,
        "tag_seen_count": sighting.tag_seen_count,
        "peak_rssi_dbm": sighting.peak_rssi_dbm,
        "closed": sighting.closed,
        "finalized": bool(sighting.finalized),
        "version": max(sighting.version or 0, (match.version or 0) if match else 0),
        "vision": _vision_payload(match, files, incident_id),
    }


def _load(db: Session, incident_id: str):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found.")
    return incident


def _detail(db: Session, incident: Incident) -> dict:
    incident_id = str(incident.id)
    alerts = (db.query(IncidentAlert).filter(IncidentAlert.incident_id == incident.id)
              .order_by(IncidentAlert.timestamp_sim).all())
    vehicles = db.query(IncidentVehicle).filter(IncidentVehicle.incident_id == incident.id).all()
    zone_rows = (db.query(CrashZoneRfid).filter(CrashZoneRfid.incident_id == incident.id)
                 .order_by(CrashZoneRfid.first_seen_ts).all())
    sightings = (db.query(RfidSighting).filter(RfidSighting.incident_id == incident.id)
                 .order_by(RfidSighting.first_seen_ts).all())
    matches = {}
    if sightings:
        matches = {row.sighting_id: row for row in db.query(VisionMatch)
                   .filter(VisionMatch.sighting_id.in_([s.id for s in sightings])).all()}
    evidence = db.query(EvidenceFile).filter(EvidenceFile.incident_id == incident.id).all()
    by_match = defaultdict(list)
    for row in evidence:
        by_match[str(row.vision_match_id)].append(row)
    incident_files = by_match.get("None", [])
    suspects = fleeing_suspects(vehicles, sightings)
    suspect_epcs = {suspect["epc"] for suspect in suspects if suspect["epc"]}
    fled_plates = {vehicle.plate_norm for vehicle in vehicles if vehicle.role == ROLE_FLED}
    vehicles = [vehicle for vehicle in vehicles if vehicle.role != ROLE_FLED]
    watch_epcs = {vehicle.epc for vehicle in vehicles if vehicle.epc}

    # one snapshot panel per junction: crash zone + context snapshots
    snapshots = []
    for junction in sorted(set(JUNCTION_WORLD) | {row.junction_id for row in zone_rows}):
        rows = [row for row in zone_rows if row.junction_id == junction]
        is_crash = junction == incident.crash_junction
        frames = [row for row in incident_files
                  if (row.junction_id == junction) or (row.junction_id is None and is_crash
                                                      and row.kind == "crash_frame")]
        snapshots.append({
            "junction_id": junction,
            "zone": "crash" if is_crash else "context",
            "label": "CRASH ZONE" if is_crash else "Context snapshot",
            "window": ([incident.crash_ts_sim - 30.0, incident.crash_ts_sim + 30.0]
                       if incident.crash_ts_sim is not None else None),
            "rows": [{
                "epc": row.epc, "plate_norm": row.plate_norm,
                "plate_display": format_plate(row.plate_norm), "state_name": _state(row.plate_norm),
                "junction_id": row.junction_id, "reader_id": row.reader_id,
                "first_seen_ts": row.first_seen_ts, "last_seen_ts": row.last_seen_ts,
                "report_count": row.report_count, "tag_seen_count": row.tag_seen_count,
                "peak_rssi_dbm": row.peak_rssi_dbm, "role": row.role,
                "watchlist": row.epc in watch_epcs,
                "registry": "REGISTERED" if row.plate_norm else "UNREGISTERED_TAG",
            } for row in rows],
            "frames": [_evidence_ref(row, incident_id) for row in frames],
        })

    cards = best_evidence_by_junction(
        incident_id, [s for s in sightings if s.epc in suspect_epcs], matches, by_match,
        {vehicle.epc: vehicle.sim_vehicle_id for vehicle in vehicles if vehicle.epc})
    return {
        "incident": _incident_summary(db, incident) | {"description": incident.description},
        "evidence_url_template": f"/api/incidents/{incident_id}/evidence/{{evidence_id}}",
        "alerts": [{
            "alert_id": row.alert_id, "source": row.source, "status": row.status,
            "timestamp_sim": row.timestamp_sim, "frame": row.frame,
            "created_at": _iso(row.created_at),
        } for row in alerts],
        "involved_vehicles": [{
            "plate_norm": row.plate_norm, "plate_display": row.plate_display,
            "state_name": _state(row.plate_norm), "epc": row.epc, "role": row.role,
            # an involved plate always exists; what can be missing is its tag
            "registry": "REGISTERED" if row.epc else "NOT_IN_REGISTRY",
            "fled": row.plate_norm in fled_plates,
        } for row in vehicles],
        "snapshots": snapshots,
        # older single-panel shape, kept for callers that used it
        "crash_zone_rfid": [r for panel in snapshots if panel["zone"] == "crash" for r in panel["rows"]],
        "crash_frames": [_evidence_ref(row, incident_id) for row in incident_files
                         if row.kind == "crash_frame"],
        "sightings": [_sighting_payload(s, matches.get(s.id),
                                        by_match.get(str(matches[s.id].id), []) if s.id in matches else [],
                                        incident_id)
                      for s in sightings],
        # ONE primary evidence card per junction on the fleeing suspect's route
        # (other vehicles never get a card)
        "best_evidence_by_junction": cards,
        "fleeing_vehicles": [fleeing_vehicle_summary(suspect, cards) for suspect in suspects],
    }


@router.get("/{incident_id}")
async def get_incident(incident_id: str, db: Session = Depends(get_db)):
    """The full cross-verification timeline for one incident."""
    return _detail(db, _load(db, incident_id))


@router.get("/{incident_id}/tracks")
async def get_tracks(incident_id: str, db: Session = Depends(get_db)):
    """Per watchlist vehicle: crash zone, then every junction it was sighted at.

    Built from the same payload as the incident view, so the tracking page and
    the evidence page always agree.
    """
    detail = _detail(db, _load(db, incident_id))
    incident = detail["incident"]
    tracks = []
    for vehicle in detail["involved_vehicles"]:
        steps = [{
            "junction_id": incident["crash_junction"], "kind": "crash",
            "t": incident["crash_ts_sim"],
            "rfid": next((r for p in detail["snapshots"] if p["zone"] == "crash"
                          for r in p["rows"] if r["epc"] == vehicle["epc"]), None),
        }]
        for sighting in detail["sightings"]:
            if vehicle["epc"] and sighting["epc"] == vehicle["epc"]:
                steps.append({"junction_id": sighting["junction_id"], "kind": "sighting",
                              "t": sighting["first_seen_ts"], "sighting": sighting})
        tracks.append({"epc": vehicle["epc"], "plate_norm": vehicle["plate_norm"],
                       "plate_display": vehicle["plate_display"],
                       "state_name": vehicle["state_name"], "steps": steps})
    return {"incident": incident, "snapshots": detail["snapshots"], "tracks": tracks}


@router.get("/{incident_id}/evidence/{evidence_id}")
async def get_evidence(incident_id: str, evidence_id: str, db: Session = Depends(get_db)):
    """Stream an evidence image (bytes never live in the database)."""
    row = db.get(EvidenceFile, evidence_id)
    if row is None or str(row.incident_id) != str(incident_id):
        raise HTTPException(status_code=404, detail="Evidence not found.")
    path = Path(row.path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=410, detail="Evidence file is gone from disk.")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@health_router.get("/health")
async def fusion_health():
    """RFID FUSION health: green only if RFID reports, camera frames and the
    ANPR adapter are recent and the fusion queue is not backlogged."""
    from app.services.rfid.service import peek_service

    service = peek_service()
    if service is None:
        return {"status": "offline", "problems": ["RFID service not started (no CARLA feed yet)"],
                "last_rfid_age_s": None, "last_frame_age_s": None, "last_anpr_age_s": None,
                "anpr_available": False, "fusion_queue_depth": 0, "db_queue_depth": 0,
                "run_id": None}
    return service.health()
