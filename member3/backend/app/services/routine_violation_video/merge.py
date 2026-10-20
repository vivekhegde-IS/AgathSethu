"""
Vehicle tracks and duplicate merging for the routine-violation pipeline.

The violation unit is the MOTORCYCLE: a group of tracker fragments of the same
physical bike. Fragments are merged WITHOUT needing plate text:

  pair score (0..1) = 0.45 position + 0.15 size + 0.10 heading + 0.30 appearance
    position   earlier track's last box, moved by the camera motion
               (chained optical-flow affines) and by its own recent motion,
               compared with the later track's first box (IoU / centre
               distance in box widths)
    size       area ratio of predicted vs observed box
    heading    direction of travel at the end of A vs start of B
    appearance HSV histogram of the bike and of the riders' clothing

  hard blocks  - visible in the same frames at clearly different positions
                 (two bikes side by side) -> never merged, not even
                 transitively (checked on every union)
               - time gap above merge_max_gap_s, or position too far

Fragments are grouped with union-find (chains merge transitively). Plate text
is only used as extra evidence: confident plates that are equal or differ by
<= 1 character merge; unreadable / low-confidence plates are "unknown", never
"equal".
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np


# ============================================================
# TRACK STATE
# ============================================================

@dataclass
class VehicleTrack:
    track_id: str
    first_frame: int
    last_frame: int
    boxes: dict = field(default_factory=dict)          # frame -> box (work coords)
    riders: Counter = field(default_factory=Counter)   # person track -> frames on this bike
    rider_offsets: dict = field(default_factory=lambda: defaultdict(list))
    frame_riders: dict = field(default_factory=dict)   # frame -> [person ids]
    rel_motion: list = field(default_factory=list)     # [(frame, (dx_w, dy_w, growth))]
    hist: np.ndarray | None = None                     # bike colour
    rider_hist: np.ndarray | None = None               # riders' clothing colour
    thumbs: dict = field(default_factory=dict)         # "first"/"last" -> (frame, image)
    candidates: list = field(default_factory=list)
    plate_reads: list = field(default_factory=list)
    members: list = field(default_factory=list)        # raw tracker ids merged here
    fps: float = 30.0
    last_thumb_box: tuple | None = None                # (frame, box, frame image) until cropped

    def speed(self):
        """Net motion relative to the background, in vehicle widths per
        second (per-step jitter cancels out, real movement accumulates)."""
        if len(self.rel_motion) < 4:
            return None
        frames = [f for f, _ in self.rel_motion]
        duration = max(1e-3, (max(frames) - min(frames)) / self.fps)
        sx = sum(s[0] for _, s in self.rel_motion)
        sy = sum(s[1] for _, s in self.rel_motion)
        sg = sum(s[2] for _, s in self.rel_motion)
        return (math.hypot(sx, sy) + abs(sg)) / duration


def merge_into(keep: VehicleTrack, other: VehicleTrack) -> VehicleTrack:
    keep.boxes.update(other.boxes)
    keep.first_frame = min(keep.first_frame, other.first_frame)
    keep.last_frame = max(keep.last_frame, other.last_frame)
    keep.riders.update(other.riders)
    for pid, offsets in other.rider_offsets.items():
        keep.rider_offsets[pid].extend(offsets)
    for frame, pids in other.frame_riders.items():
        keep.frame_riders[frame] = sorted(set(keep.frame_riders.get(frame, [])) | set(pids))
    keep.rel_motion = sorted(keep.rel_motion + other.rel_motion, key=lambda x: x[0])
    keep.candidates += other.candidates
    keep.plate_reads += other.plate_reads
    keep.members += [m for m in other.members if m not in keep.members]
    if keep.hist is None:
        keep.hist = other.hist
    if keep.rider_hist is None:
        keep.rider_hist = other.rider_hist
    if other.thumbs.get("first") and (not keep.thumbs.get("first") or other.thumbs["first"][0] < keep.thumbs["first"][0]):
        keep.thumbs["first"] = other.thumbs["first"]
    if other.thumbs.get("last") and (not keep.thumbs.get("last") or other.thumbs["last"][0] > keep.thumbs["last"][0]):
        keep.thumbs["last"] = other.thumbs["last"]
    return keep


# ============================================================
# GEOMETRY HELPERS
# ============================================================

def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _center(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def iou(a, b):
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = _area(a) + _area(b) - inter
    return inter / union if union > 0 else 0.0


def compose(a, b):
    """Affine a then b (both 2x3)."""
    if a is None:
        return b
    if b is None:
        return a
    return (np.vstack([b, [0, 0, 1]]) @ np.vstack([a, [0, 0, 1]]))[:2]


def chain_affine(affines, start, end):
    total = None
    for index in sorted(k for k in affines if start < k <= end):
        total = compose(total, affines[index])
    return total


def warp_box(box, affine):
    if affine is None:
        return tuple(box)
    pts = np.array([[box[0], box[1]], [box[2], box[3]]], dtype=np.float32).reshape(-1, 1, 2)
    out = cv2.transform(pts, affine).reshape(-1, 2)
    return (float(out[0][0]), float(out[0][1]), float(out[1][0]), float(out[1][1]))


def hist_similarity(a, b):
    """HSV histogram correlation mapped to 0..1 (None if either missing)."""
    if a is None or b is None:
        return None
    corr = cv2.compareHist(a.astype(np.float32), b.astype(np.float32), cv2.HISTCMP_CORREL)
    return (float(corr) + 1.0) / 2.0


def plates_near_equal(a: str | None, b: str | None, max_diff: int = 1) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return sum(x != y for x, y in zip(a, b)) <= max_diff


# ============================================================
# PAIR SCORE
# ============================================================

@dataclass
class PairScore:
    a: str
    b: str
    score: float | None          # None = hard-blocked
    reason: str
    parts: dict = field(default_factory=dict)


def co_visible_conflict(a: VehicleTrack, b: VehicleTrack, cfg) -> str | None:
    """Two tracks seen in the same frames at clearly different places are two
    different bikes (e.g. side by side). Returns a reason, or None."""
    common = sorted(set(a.boxes) & set(b.boxes))
    if not common:
        return None
    overlaps = [iou(a.boxes[f], b.boxes[f]) for f in common]
    if float(np.median(overlaps)) < cfg.merge_covisible_iou:
        return f"visible together in {len(common)} frames at different positions (median IoU {np.median(overlaps):.2f})"
    return None


def _recent_step(track: VehicleTrack, end: bool, n: int = 3):
    steps = [s for _, s in track.rel_motion]
    steps = steps[-n:] if end else steps[:n]
    if not steps:
        return None
    return tuple(float(np.mean([s[i] for s in steps])) for i in range(3))


def pair_score(a: VehicleTrack, b: VehicleTrack, affines, fps, cfg) -> PairScore:
    """Merge score of two fragments (order-independent)."""
    if a.first_frame > b.first_frame:
        a, b = b, a
    conflict = co_visible_conflict(a, b, cfg)
    if conflict:
        return PairScore(a.track_id, b.track_id, None, conflict)
    common = sorted(set(a.boxes) & set(b.boxes))
    if common:
        # Seen at the same time: only a near-identical box is the same bike
        # detected twice (duplicate track). A box that merely overlaps (e.g.
        # one detection spanning two bikes side by side) is not merged.
        overlap = float(np.median([iou(a.boxes[f], b.boxes[f]) for f in common]))
        if overlap >= cfg.merge_duplicate_iou:
            return PairScore(a.track_id, b.track_id, 0.95, "duplicate track at the same position",
                             {"co_visible_frames": len(common), "median_iou": round(overlap, 2)})
        return PairScore(a.track_id, b.track_id, None,
                         f"seen together in {len(common)} frames, boxes only partly overlap "
                         f"(median IoU {overlap:.2f} < {cfg.merge_duplicate_iou})")
    gap_frames = b.first_frame - a.last_frame
    gap_s = gap_frames / fps
    if gap_s > cfg.merge_max_gap_s:
        return PairScore(a.track_id, b.track_id, None, f"time gap {gap_s:.2f}s > {cfg.merge_max_gap_s}s")

    a_box, b_box = a.boxes[a.last_frame], b.boxes[b.first_frame]
    predicted = warp_box(a_box, chain_affine(affines, a.last_frame, b.first_frame))
    width = max(1.0, a_box[2] - a_box[0])
    step = _recent_step(a, end=True)
    stride = max(1, cfg.frame_stride)
    if step is not None:                     # A's own motion over the gap
        dx = step[0] * width * gap_frames / stride
        dy = step[1] * width * gap_frames / stride
        grow = math.exp(max(-1.0, min(1.0, step[2] * gap_frames / stride)))
        cx, cy = _center(predicted)
        hw = (predicted[2] - predicted[0]) * grow / 2
        hh = (predicted[3] - predicted[1]) * grow / 2
        predicted = (cx + dx - hw, cy + dy - hh, cx + dx + hw, cy + dy + hh)
    ref_w = max(predicted[2] - predicted[0], b_box[2] - b_box[0], 1.0)
    distance = math.dist(_center(predicted), _center(b_box)) / ref_w
    if distance > cfg.merge_max_widths:
        return PairScore(a.track_id, b.track_id, None,
                         f"predicted position {distance:.2f} widths away (> {cfg.merge_max_widths})")
    position = max(iou(predicted, b_box), math.exp(-distance))
    ratio = max(_area(predicted), _area(b_box)) / max(1.0, min(_area(predicted), _area(b_box)))
    size = float(np.clip(1 - (ratio - 1) / max(1e-3, cfg.merge_size_ratio - 1), 0, 1))
    heading = 0.5
    va, vb = _recent_step(a, end=True), _recent_step(b, end=False)
    if va and vb and math.hypot(va[0], va[1]) > 0.02 and math.hypot(vb[0], vb[1]) > 0.02:
        cos = (va[0] * vb[0] + va[1] * vb[1]) / (math.hypot(va[0], va[1]) * math.hypot(vb[0], vb[1]))
        heading = (cos + 1) / 2
    sims = [s for s in (hist_similarity(a.hist, b.hist), hist_similarity(a.rider_hist, b.rider_hist))
            if s is not None]
    appearance = float(np.mean(sims)) if sims else 0.5
    score = 0.45 * position + 0.15 * size + 0.10 * heading + 0.30 * appearance
    parts = {"gap_s": round(gap_s, 2), "distance_widths": round(distance, 2), "position": round(position, 2),
             "size": round(size, 2), "heading": round(heading, 2), "appearance": round(appearance, 2)}
    return PairScore(a.track_id, b.track_id, round(score, 3), "scored", parts)


# ============================================================
# UNION-FIND MERGE
# ============================================================

class UnionFind:
    def __init__(self, items):
        self.parent = {i: i for i in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra

    def groups(self):
        out = defaultdict(list)
        for item in self.parent:
            out[self.find(item)].append(item)
        return list(out.values())


def merge_tracks(tracks: list[VehicleTrack], affines, fps, cfg):
    """Group fragments of the same bike. Returns (groups, all pair scores).
    Each group is a list of tracks, ordered by first frame."""
    by_id = {t.track_id: t for t in tracks}
    pairs = []
    ids = sorted(by_id, key=lambda i: by_id[i].first_frame)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            pairs.append(pair_score(by_id[x], by_id[y], affines, fps, cfg))
    uf = UnionFind(ids)
    members = {i: {i} for i in ids}
    for pair in sorted((p for p in pairs if p.score is not None), key=lambda p: -p.score):
        if pair.score < cfg.merge_threshold:
            break
        ra, rb = uf.find(pair.a), uf.find(pair.b)
        if ra == rb:
            continue
        # never let a union put two co-visible, differently placed tracks together
        blocked = any(co_visible_conflict(by_id[p], by_id[q], cfg)
                      for p in members[ra] for q in members[rb])
        if blocked:
            pair.reason = "above threshold but would join two bikes seen side by side"
            continue
        uf.union(pair.a, pair.b)
        root = uf.find(pair.a)
        members[root] = members[ra] | members[rb]
        pair.reason = "merged"
    groups = [sorted((by_id[i] for i in group), key=lambda t: t.first_frame) for group in uf.groups()]
    groups.sort(key=lambda g: g[0].first_frame)
    return groups, pairs


def combine(group: list[VehicleTrack]) -> VehicleTrack:
    """One VehicleTrack for a group of fragments (the first is kept)."""
    keep = group[0]
    for other in group[1:]:
        merge_into(keep, other)
    return keep


def merge_by_plate(entries: list[dict], cfg) -> list[dict]:
    """Merge entries whose CONFIDENT plates are equal or differ by <= N chars.
    Entries without a confident plate ('plate' None) are unknown, never
    equal. Entries seen side by side are never merged."""
    out: list[dict] = []
    for entry in entries:
        target = None
        if entry.get("plate"):
            for existing in out:
                if (existing.get("plate") and plates_near_equal(existing["plate"], entry["plate"],
                                                                cfg.merge_plate_max_diff)
                        and not co_visible_conflict(existing["vehicle"], entry["vehicle"], cfg)):
                    target = existing
                    break
        if target is None:
            out.append(entry)
        else:
            merge_into(target["vehicle"], entry["vehicle"])
            target["types"] = sorted(set(target["types"]) | set(entry["types"]))
            target["merged"] = True
    return out
