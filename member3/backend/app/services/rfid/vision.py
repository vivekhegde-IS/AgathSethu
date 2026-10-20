"""Vision verification: frame ring, per-vehicle clustering, voting, status ladder.

The ANPR pass itself lives in the service (it needs the model); everything that
decides the STATUS is here and is pure, so the whole ladder is unit-testable
with a mocked adapter.

The ANPR is **blind**: it is never given the RFID plate. The comparison happens
here, after the fact.

Suspect association comes FIRST, text comparison second. A plate is attached
to the sighted vehicle only because of WHERE it is (inside that vehicle's
projected image box, from the optional ``vehicles`` metadata of camera_frame),
never because its text resembles the RFID plate. When a frame has no vehicle
metadata (older CARLA script), a plate is attached only if it is the ONLY
vehicle plate read in the whole window. Otherwise nothing is attached: another
vehicle's plate is never used as a fallback.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.services.rfid.config import (
    DEFAULT_CONFIG,
    STATUS_NOT_CONFIRMED,
    STATUS_NO_PLATE_VISIBLE,
    STATUS_PLATE_TOO_SMALL,
    STATUS_PROBABLE_MATCH,
    STATUS_VISION_CONFIRMED,
    RfidFeatureConfig,
)


def edit_distance(left: str | None, right: str | None) -> int:
    """Levenshtein distance (small plates, so the simple DP is plenty)."""
    if not left or not right:
        return max(len(left or ""), len(right or ""))
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, start=1):
        current = [i]
        for j, b in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


@dataclass
class FrameRef:
    camera_id: str
    junction_id: str
    timestamp_sim: float
    jpeg: bytes
    frame_no: int | None = None        # CARLA frame number, for the evidence footer
    # Optional per-vehicle image boxes sent with the frame (association metadata
    # only): [{"vehicle_id": "B", "bbox": [x1, y1, x2, y2], "depth_m": 31.2}].
    # None = the sender does not provide it (older CARLA script).
    vehicles: list | None = None

    @property
    def size(self) -> int:
        return len(self.jpeg)

    def vehicle_box(self, vehicle_id: str | None) -> dict | None:
        if not vehicle_id or not self.vehicles:
            return None
        for vehicle in self.vehicles:
            if str(vehicle.get("vehicle_id")) == str(vehicle_id):
                return vehicle
        return None


def parse_vehicle_boxes(raw) -> list | None:
    """Validate the optional camera_frame ``vehicles`` field; None when absent
    or unusable (the frame then counts as having no metadata)."""
    if not isinstance(raw, list):
        return None
    boxes = []
    for item in raw:
        if not isinstance(item, dict) or item.get("vehicle_id") in (None, ""):
            continue
        bbox = item.get("bbox")
        try:
            x1, y1, x2, y2 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        try:
            depth = float(item["depth_m"]) if item.get("depth_m") is not None else None
        except (TypeError, ValueError):
            depth = None
        boxes.append({"vehicle_id": str(item["vehicle_id"]), "bbox": [x1, y1, x2, y2],
                      "depth_m": depth})
    return boxes


class FrameRing:
    """Newest ``window_s`` of raw JPEG frames per camera, decoded lazily."""

    def __init__(self, window_s: float = DEFAULT_CONFIG.vision_ring_s):
        self.window_s = window_s
        self.frames: dict[str, list[FrameRef]] = defaultdict(list)
        self.added = 0
        self.dropped = 0

    def add(self, camera_id: str, junction_id: str, timestamp_sim: float, jpeg: bytes,
            frame_no: int | None = None, vehicles: list | None = None) -> None:
        self.frames[camera_id].append(FrameRef(camera_id, junction_id, timestamp_sim, jpeg,
                                               frame_no, vehicles))
        self.added += 1

    def clear(self) -> None:
        """A new run: the previous run's frames must never be matched."""
        self.dropped += sum(len(items) for items in self.frames.values())
        self.frames.clear()

    def prune(self, now_ts: float, keep_from: float | None = None) -> None:
        """Drop frames older than the ring window, but none newer than ``keep_from``."""
        cutoff = now_ts - self.window_s
        if keep_from is not None:
            cutoff = min(cutoff, keep_from)
        for camera_id, items in self.frames.items():
            keep = [item for item in items if item.timestamp_sim >= cutoff]
            self.dropped += len(items) - len(keep)
            self.frames[camera_id] = keep

    def oldest_ts(self, camera_id: str) -> float | None:
        items = self.frames.get(camera_id) or []
        return items[0].timestamp_sim if items else None

    def nearest(self, junction_id: str, ts: float, max_dt: float = 2.0) -> FrameRef | None:
        """The frame of this junction's camera(s) closest to ``ts``."""
        best = None
        for camera_id in self.cameras_for_junction(junction_id):
            for item in self.frames.get(camera_id, []):
                gap = abs(item.timestamp_sim - ts)
                if gap <= max_dt and (best is None or gap < abs(best.timestamp_sim - ts)):
                    best = item
        return best

    def cameras_for_junction(self, junction_id: str) -> list[str]:
        return [camera_id for camera_id, items in self.frames.items()
                if any(item.junction_id == junction_id for item in items)]

    def window(self, camera_id: str, start_ts: float, end_ts: float) -> list[FrameRef]:
        return [item for item in self.frames.get(camera_id, [])
                if start_ts <= item.timestamp_sim <= end_ts]

    def pick(self, camera_id: str, start_ts: float, end_ts: float, count: int) -> list[FrameRef]:
        """Up to ``count`` frames SPREAD across the window (not just the newest)."""
        candidates = sorted(self.window(camera_id, start_ts, end_ts), key=lambda item: item.timestamp_sim)
        if len(candidates) <= count:
            return candidates
        step = len(candidates) / float(count)
        picked = [candidates[min(len(candidates) - 1, int(index * step))] for index in range(count)]
        # de-duplicate while preserving order
        seen, unique = set(), []
        for item in picked:
            if item.timestamp_sim not in seen:
                seen.add(item.timestamp_sim)
                unique.append(item)
        return unique

    def counters(self) -> dict:
        return {
            "frames_added": self.added,
            "frames_dropped": self.dropped,
            "cameras": {camera: len(items) for camera, items in sorted(self.frames.items())},
        }


@dataclass
class FrameReads:
    """What the ANPR saw in one frame, after the plate rules (RuleRead list)."""

    frame: FrameRef
    plates: list = field(default_factory=list)     # plate_rules.RuleRead


# ======================================================================
# per-vehicle clustering + character voting
# ======================================================================

def _center(box) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


@dataclass
class PlateCluster:
    """One physical plate followed across frames (blind: no RFID input)."""

    members: list = field(default_factory=list)    # (FrameRef, RuleRead)
    voted: str | None = None
    confidence: float = 0.0

    @property
    def frames(self) -> int:
        return len({id(frame) for frame, _ in self.members})

    @property
    def representative(self) -> str:
        return self.voted or self.members[0][1].corrected

    def has_frame(self, frame) -> bool:
        return any(member_frame is frame for member_frame, _ in self.members)

    def vote(self) -> tuple[str | None, float]:
        """Per-position vote weighted by each character's OCR confidence."""
        reads = [rule for _, rule in self.members if rule.valid and rule.corrected]
        if not reads:
            return None, 0.0
        length = max(len(rule.corrected) for rule in reads)
        chars, scores = [], []
        for index in range(length):
            weight: dict[str, float] = defaultdict(float)
            count: dict[str, int] = defaultdict(int)
            total = 0.0
            for rule in reads:
                if index >= len(rule.corrected):
                    continue
                conf = rule.char_conf[index] if index < len(rule.char_conf) else rule.mean_conf
                conf = max(0.01, float(conf))
                weight[rule.corrected[index]] += conf
                count[rule.corrected[index]] += 1
                total += conf
            if not weight:
                continue
            char, score = max(weight.items(), key=lambda kv: (kv[1], kv[0]))
            chars.append(char)
            # share of the vote x mean confidence of the winning character
            scores.append((score / total) * (score / count[char]))
        self.voted = "".join(chars)
        self.confidence = sum(scores) / len(scores) if scores else 0.0
        return self.voted, self.confidence

    def best_member(self):
        """The member to show: largest, sharpest plate (then most confident)."""
        return max(self.members, key=lambda m: (round(m[1].width_px / 4.0), m[1].sharpness,
                                                m[1].mean_conf))


def cluster_reads(frame_reads: list[FrameReads],
                  cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> list[PlateCluster]:
    """Group VALID reads into per-vehicle clusters.

    A read joins a cluster by box continuity (a member within
    ``cluster_box_px`` in a frame at most ``cluster_box_dt_s`` away), else by
    text similarity (edit distance <= ``cluster_text_distance`` to the cluster's
    plate). A cluster takes at most one read per frame: two plates in the same
    frame are two vehicles.
    """
    clusters: list[PlateCluster] = []
    for item in sorted(frame_reads, key=lambda fr: fr.frame.timestamp_sim):
        for rule in item.plates:
            if not rule.valid or not rule.corrected:
                continue
            cx, cy = _center(rule.box)
            best, best_key = None, None
            for cluster in clusters:
                if cluster.has_frame(item.frame):
                    continue
                near = any(abs(frame.timestamp_sim - item.frame.timestamp_sim) <= cfg.cluster_box_dt_s
                           and ((_center(member.box)[0] - cx) ** 2
                                + (_center(member.box)[1] - cy) ** 2) ** 0.5 <= cfg.cluster_box_px
                           for frame, member in cluster.members)
                distance = edit_distance(rule.corrected, cluster.representative)
                if not near and distance > cfg.cluster_text_distance:
                    continue
                key = (0 if near else 1, distance)
                if best_key is None or key < best_key:
                    best, best_key = cluster, key
            if best is None:
                best = PlateCluster()
                clusters.append(best)
            best.members.append((item.frame, rule))
            best.vote()
    return clusters


# ======================================================================
# matching against the RFID plate
# ======================================================================

def plate_diff(anpr: str | None, rfid: str | None) -> list[dict]:
    """Position-by-position differences (same-length plates only)."""
    if not anpr or not rfid or len(anpr) != len(rfid):
        return []
    return [{"position": index + 1, "anpr": a, "rfid": b}
            for index, (a, b) in enumerate(zip(anpr, rfid)) if a != b]


def _confusable_only(diff: list[dict], pairs: set) -> bool:
    return bool(diff) and all(frozenset((d["anpr"], d["rfid"])) in pairs for d in diff)


def _describe(diff: list[dict]) -> str:
    return ", ".join(f"pos {d['position']} {d['anpr']}/{d['rfid']}" for d in diff)


def _judge_cluster(cluster: PlateCluster, rfid_plate: str | None,
                   cfg: RfidFeatureConfig) -> dict:
    voted = cluster.voted
    result = {"cluster": cluster, "status": None, "rule_assisted": False, "reason": None,
              "edit_distance": edit_distance(voted, rfid_plate) if (voted and rfid_plate) else None,
              "diff": plate_diff(voted, rfid_plate)}
    if not voted or not rfid_plate:
        return result
    pairs = cfg.confusable_set()
    if voted == rfid_plate:
        exact = [(frame, rule) for frame, rule in cluster.members if rule.corrected == rfid_plate]
        # Format-certain fixes (a B in a must-be-digit slot is an 8) do not count
        # as assistance; a state code that had to be GUESSED does.
        clean = [(frame, rule) for frame, rule in exact if not rule.state_corrected]

        # CONFIRMED needs >= vision_frames_to_confirm confident frames that read
        # EXACTLY the plate, and those must be a clear majority of the vehicle's
        # reads: one frame, or reads that disagree, are never a confirmation.
        agreeing = len({id(frame) for frame, rule in cluster.members if rule.corrected == voted})
        agreement = agreeing / max(1, cluster.frames)

        def meets(members) -> str | None:
            good = {id(frame) for frame, rule in members if rule.mean_conf >= cfg.vision_conf_threshold}
            if len(good) >= cfg.vision_frames_to_confirm and agreement >= cfg.vision_agreement_min:
                return f"multi-frame, {agreeing} of {cluster.frames} reads agree"
            return None

        if meets(clean):
            result.update(status=STATUS_VISION_CONFIRMED, reason=f"exact plate, {meets(clean)}")
        elif meets(exact):
            assisted = [rule for _, rule in exact if rule.state_corrected]
            window = assisted[0].window if assisted else None
            diff = plate_diff(window, rfid_plate) if window else []
            result.update(status=STATUS_PROBABLE_MATCH, rule_assisted=True, diff=diff,
                          edit_distance=edit_distance(window, rfid_plate) if window else 0,
                          reason="state code corrected by the plate rules" + (
                              f": {_describe(diff)}" if diff else ""))
            if cfg.promote_rule_assisted:
                result["status"] = STATUS_VISION_CONFIRMED
                result["reason"] += " (promoted: PROMOTE_RULE_ASSISTED)"
        else:
            result.update(status=STATUS_PROBABLE_MATCH,
                          reason=(f"exact plate, but only {agreeing} of {cluster.frames} reads agree"
                                  if agreement < cfg.vision_agreement_min
                                  else "exact plate, too few or low-confidence frames"))
            if exact and not clean:
                # the only agreeing reads needed a state-code guess
                window = exact[0][1].window
                diff = plate_diff(window, rfid_plate) if window else []
                result.update(rule_assisted=True, diff=diff,
                              edit_distance=edit_distance(window, rfid_plate) if window else 0)
                result["reason"] += "; state code corrected by the plate rules" + (
                    f": {_describe(diff)}" if diff else "")
        return result
    diff = result["diff"]
    if _confusable_only(diff, pairs) and cluster.frames >= cfg.rule_assisted_min_frames:
        result.update(status=STATUS_PROBABLE_MATCH, rule_assisted=True,
                      reason="differs only in confusable characters: " + _describe(diff))
    elif result["edit_distance"] == 1:
        result.update(status=STATUS_PROBABLE_MATCH, rule_assisted=_confusable_only(diff, pairs),
                      reason="edit distance 1" + (f": {_describe(diff)}" if diff else ""))
    if result["status"] == STATUS_PROBABLE_MATCH and result["rule_assisted"] \
            and cfg.promote_rule_assisted:
        result["status"] = STATUS_VISION_CONFIRMED
        result["reason"] += " (promoted: PROMOTE_RULE_ASSISTED)"
    return result


# ======================================================================
# suspect association: geometry first, never the expected text
# ======================================================================

ASSOC_BBOX = "bbox"                  # plate inside the suspect's projected image box
ASSOC_SINGLE_PLATE = "single_plate"  # no box metadata: the ONLY plate read in the window
ASSOC_AMBIGUOUS = "ambiguous"        # no box metadata, several vehicles' plates: none attached
ASSOC_NONE = "none"                  # no box metadata and no legible plate at all

# Slack around a projected vehicle box (the plate overlay sits a few cm
# outside the CARLA bounding box, and the box is rounded to pixels).
BOX_MARGIN_PX = 6.0


@dataclass
class Suspect:
    """The sighted vehicle, as the RFID tag + registry identify it (never ANPR)."""

    epc: str | None = None
    plate_norm: str | None = None    # registry plate (compared AFTER association)
    vehicle_id: str | None = None    # CARLA actor name, e.g. "B" (registry sim_vehicle_id)


def _inside(point, bbox, margin: float = BOX_MARGIN_PX) -> bool:
    x, y = point
    return bbox[0] - margin <= x <= bbox[2] + margin and bbox[1] - margin <= y <= bbox[3] + margin


def box_overlap(plate_box, vehicle_bbox) -> float:
    """Fraction of the plate box that lies inside the vehicle box (0..1)."""
    x1, y1 = max(plate_box[0], vehicle_bbox[0]), max(plate_box[1], vehicle_bbox[1])
    x2, y2 = min(plate_box[2], vehicle_bbox[2]), min(plate_box[3], vehicle_bbox[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(1e-6, (plate_box[2] - plate_box[0]) * (plate_box[3] - plate_box[1]))
    return min(1.0, inter / area)


def owner_of(rule, frame: FrameRef) -> str | None:
    """The vehicle whose projected box holds this plate's centre. When boxes
    overlap (one car partly hides another) the front-most vehicle owns it."""
    if not frame.vehicles:
        return None
    centre = _center(rule.box)
    holders = [vehicle for vehicle in frame.vehicles if _inside(centre, vehicle["bbox"])]
    if not holders:
        return None
    return min(holders, key=lambda v: v["depth_m"] if v.get("depth_m") is not None
               else float("inf"))["vehicle_id"]


def associate(frame_reads: list[FrameReads], suspect: Suspect | None,
              cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> dict:
    """Which detections are ON the suspect vehicle. Text is never consulted.

    Returns {mode, members: [(FrameRef, RuleRead, strength)] (valid reads, at
    most one per frame), detections: [(FrameRef, RuleRead)] (every detection
    on the suspect, readable or not), suspect_visible_frames,
    frames_with_metadata, reason}.
    """
    with_meta = [item for item in frame_reads if item.frame.vehicles is not None]
    vehicle_id = suspect.vehicle_id if suspect is not None else None
    if vehicle_id and with_meta:
        members, detections, visible = [], [], 0
        for item in with_meta:
            box = item.frame.vehicle_box(vehicle_id)
            if box is None:
                continue                       # suspect not in this frame
            visible += 1
            best = None
            for rule in item.plates:
                if owner_of(rule, item.frame) != vehicle_id:
                    continue
                detections.append((item.frame, rule))
                strength = box_overlap(rule.box, box["bbox"])
                key = (rule.valid, strength, rule.det_confidence)
                if best is None or key > best[0]:
                    best = (key, rule, strength)
            if best is not None and best[1].valid:
                members.append((item.frame, best[1], round(best[2], 3)))
        reason = None
        if visible == 0:
            reason = (f"suspect {vehicle_id} not visible in any of {len(with_meta)} "
                      f"camera frame(s)")
        elif not detections:
            reason = f"suspect {vehicle_id} visible in {visible} frame(s), no plate detected on it"
        elif not members:
            reason = f"suspect {vehicle_id} visible in {visible} frame(s), plate not read"
        return {"mode": ASSOC_BBOX, "members": members, "detections": detections,
                "suspect_visible_frames": visible, "frames_with_metadata": len(with_meta),
                "reason": reason}

    # No vehicle boxes on these frames (older CARLA script): a plate can only be
    # attached when it is the ONLY vehicle plate read in the whole window.
    clusters = cluster_reads(frame_reads, cfg)
    if len(clusters) == 1:
        members = [(frame, rule, None) for frame, rule in clusters[0].members]
        return {"mode": ASSOC_SINGLE_PLATE, "members": members,
                "detections": [(frame, rule) for frame, rule, _ in members],
                "suspect_visible_frames": None, "frames_with_metadata": 0,
                "reason": "no vehicle-position metadata: the only plate read in the window"}
    if len(clusters) > 1:
        return {"mode": ASSOC_AMBIGUOUS, "members": [], "detections": [],
                "suspect_visible_frames": None, "frames_with_metadata": 0,
                "reason": (f"{len(clusters)} vehicles' plates in view and no vehicle-position "
                           f"metadata: the suspect's plate cannot be isolated")}
    return {"mode": ASSOC_NONE, "members": [],
            "detections": [(item.frame, rule) for item in frame_reads for rule in item.plates],
            "suspect_visible_frames": None, "frames_with_metadata": 0,
            "reason": "no legible plate in the window"}


def fuse(frame_reads: list[FrameReads], rfid_plate: str | None,
         cfg: RfidFeatureConfig = DEFAULT_CONFIG,
         reference_ts: float | None = None, suspect: Suspect | None = None) -> dict:
    """Decide the verification status from rule-checked per-frame reads.

    1. associate(): which reads are ON the suspect vehicle (geometry, or the
       single-plate fallback). Text plays no part in this step.
    2. Only the associated reads are voted into the suspect's plate, and only
       then compared with the registry (RFID) plate.
    Plates of other vehicles are reported as context (``other_vehicles``), but
    are never attached to the suspect, not even as a closest-match fallback.
    """
    from app.services.rfid.plate_rules import GATE_TOO_SMALL, state_name

    if suspect is None:
        suspect = Suspect(plate_norm=rfid_plate)
    link = associate(frame_reads, suspect, cfg)

    cluster = None
    if link["members"]:
        cluster = PlateCluster(members=[(frame, rule) for frame, rule, _ in link["members"]])
        cluster.vote()

    judged = _judge_cluster(cluster, rfid_plate, cfg) if cluster is not None else None
    reason = link["reason"]
    if judged is not None and judged["status"] is not None:
        status = judged["status"]
        reason = judged["reason"]
    elif judged is not None:
        # The suspect's own plate was read and it is NOT the registry plate.
        status = STATUS_NOT_CONFIRMED
        reason = (f"suspect's plate read as {cluster.voted}, registry plate "
                  f"{rfid_plate or 'unknown'}")
    else:
        # Nothing legible on the suspect. PLATE_TOO_SMALL only when plates WERE
        # detected on it and every one is below the minimum width.
        detections = [rule for _, rule in link["detections"]]
        too_small = bool(detections) and all(rule.gated == GATE_TOO_SMALL for rule in detections)
        status = STATUS_PLATE_TOO_SMALL if too_small else STATUS_NO_PLATE_VISIBLE

    rejected, seen_raw, too_small_px, widths = [], set(), [], []
    for item in frame_reads:
        for rule in item.plates:
            widths.append(rule.width_px)
            if rule.gated == GATE_TOO_SMALL:
                too_small_px.append(round(rule.width_px, 1))
            if not rule.valid and rule.raw and rule.raw not in seen_raw:
                seen_raw.add(rule.raw)
                rejected.append({"raw": rule.raw, "reasons": list(rule.reasons),
                                 "frame_ts": round(item.frame.timestamp_sim, 3)})

    # The largest unreadable detection ON THE SUSPECT (never another vehicle's).
    largest_unread = None
    for frame, rule in link["detections"]:
        if not rule.valid and (largest_unread is None or rule.width_px > largest_unread[1].width_px):
            largest_unread = (frame, rule)

    best_frame = best_read = None
    if cluster is not None:
        best_frame, best_read = cluster.best_member()
    anpr_plate = cluster.voted if cluster is not None else None
    plates_seen = sorted({c.voted for c in cluster_reads(frame_reads, cfg) if c.voted})
    best_members = sorted(cluster.members, key=lambda m: (round(m[1].width_px / 4.0), m[1].sharpness),
                          reverse=True) if cluster is not None else []
    strengths = {(id(frame), id(rule)): value for frame, rule, value in link["members"]}

    return {
        "status": status,
        "rule_assisted": bool(judged and judged["rule_assisted"]),
        "match_reason": reason,
        "anpr_plate": anpr_plate,
        "anpr_state_code": (anpr_plate or "")[:2] or None,
        "anpr_state_name": state_name(anpr_plate),
        "anpr_confidence": round(cluster.confidence, 4) if cluster is not None else None,
        "edit_distance": judged["edit_distance"] if judged else None,
        "diff": judged["diff"] if judged else [],
        "frames_used": len(frame_reads),
        "cluster_frames": cluster.frames if cluster is not None else 0,
        "plates_seen": plates_seen,
        "all_plates_seen": plates_seen,          # legacy column: valid plates only
        "other_vehicles": [plate for plate in plates_seen if plate != anpr_plate],
        "rejected_reads": rejected,
        "too_small_px": too_small_px,
        "max_plate_px": round(max(widths), 1) if widths else None,
        "best_frame": best_frame,
        "best_read": best_read,
        "largest_unread": largest_unread,        # (FrameRef, RuleRead) on the suspect only
        "best_members": best_members,
        # (id(frame), id(rule)) -> plate-inside-suspect-box fraction (None: no metadata)
        "association_strength": strengths,
        "association": {
            "mode": link["mode"],
            "suspect_vehicle_id": suspect.vehicle_id,
            "suspect_epc": suspect.epc,
            "suspect_visible_frames": link["suspect_visible_frames"],
            "frames_with_metadata": link["frames_with_metadata"],
            "associated_reads": len(link["members"]),
            "reason": link["reason"],
        },
        "camera_id": best_frame.camera_id if best_frame else None,
        "time_delta_s": (round(best_frame.timestamp_sim - reference_ts, 3)
                         if (best_frame is not None and reference_ts is not None) else None),
        "per_frame": [{"ts": round(item.frame.timestamp_sim, 3), "camera_id": item.frame.camera_id,
                       "suspect_box": (item.frame.vehicle_box(suspect.vehicle_id) or {}).get("bbox"),
                       "reads": [{**rule.as_dict(), "owner": owner_of(rule, item.frame)}
                                 for rule in item.plates]}
                      for item in sorted(frame_reads, key=lambda fr: fr.frame.timestamp_sim)],
    }


# Backwards-compatible name.
evaluate = fuse


def should_stop_early(result: dict, cfg: RfidFeatureConfig = DEFAULT_CONFIG) -> bool:
    """A confirmed plate agreed by enough frames: stop burning ANPR time."""
    return result.get("status") == STATUS_VISION_CONFIRMED and not result.get("rule_assisted") \
        and result.get("cluster_frames", 0) >= cfg.vision_frames_to_confirm


def status_rank(status: str) -> int:
    from app.services.rfid.config import STATUS_RANK

    return STATUS_RANK.get(status, -1)


def material_key(result: dict) -> tuple:
    """What must change before a new result is worth pushing to the portal."""
    return (result.get("status"), result.get("anpr_plate"), bool(result.get("rule_assisted")))
