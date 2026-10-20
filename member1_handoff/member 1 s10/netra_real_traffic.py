"""Real-world traffic speeds for CARLA background cars (S10). Pure Python + numpy, no CARLA.

Source: ngsim_motion_profiles.csv (next to this file), built by Vivek from NGSIM
(US DOT, real vehicle trajectories every 0.1 s). Profile "urban" = Lankershim Blvd
(Los Angeles) + Peachtree St (Atlanta), the closest to our CARLA town junctions.

    import netra_real_traffic as RT
    if RT.ENABLED:
        kmh = RT.desired_speed_kmh(rng)            # at spawn / release
        kmh = RT.next_speed_kmh(kmh, rng)          # each time the car passes a junction
        tm.set_desired_speed(vehicle, kmh)

Env: NETRA_REAL_TRAFFIC=1 (off by default), NETRA_REAL_TRAFFIC_SEED (default 0).
Desired speeds are drawn from real MOVING speeds (>= 3 m/s; stops at red lights come
from CARLA itself) and clipped to 10-65 km/h so the Traffic Manager stays sane.
Speed changes use the real ratio "speed 80 m later / speed now".
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import numpy as np

ENABLED = os.environ.get("NETRA_REAL_TRAFFIC", "0") == "1"
PROFILE = "urban"
_HERE = Path(__file__).resolve().parent
_TABLES: dict = {}
MIN_KMH, MAX_KMH = 10.0, 65.0


def _table(metric, vclass="all"):
    key = (metric, vclass)
    if key not in _TABLES:
        q, v = [], []
        with open(_HERE / "ngsim_motion_profiles.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["profile"] == PROFILE and r["metric"] == metric and r["vehicle_class"] == vclass:
                    q.append(float(r["quantile"])); v.append(float(r["value"]))
        if not q:
            raise KeyError(f"no table for {PROFILE}/{metric}/{vclass}")
        _TABLES[key] = (np.array(q), np.array(v))
    return _TABLES[key]


def sample(metric, rng, vclass="all", q_min=0.01, q_max=0.99):
    """Inverse-CDF draw from an empirical quantile table."""
    q, v = _table(metric, vclass)
    return float(np.interp(rng.uniform(q_min, q_max), q, v))


def desired_speed_kmh(rng, vclass="car"):
    q, v = _table("spot_speed", vclass)
    q_moving = float(np.interp(3.0, v, q))          # quantile of 3 m/s: skip stopped cars
    mps = sample("spot_speed", rng, vclass, q_min=max(q_moving, 0.01))
    return float(np.clip(mps * 3.6, MIN_KMH, MAX_KMH))


def next_speed_kmh(current_kmh, rng):
    return float(np.clip(current_kmh * sample("speed_ratio_after_80m", rng), MIN_KMH, MAX_KMH))


def make_rng():
    return np.random.default_rng(int(os.environ.get("NETRA_REAL_TRAFFIC_SEED", "0")))


if __name__ == "__main__":                       # quick self-check
    r = make_rng()
    s = [desired_speed_kmh(r) for _ in range(2000)]
    print("desired km/h p5/p50/p95:", np.percentile(s, [5, 50, 95]).round(1))
    c = [next_speed_kmh(40.0, r) for _ in range(2000)]
    print("after a junction, from 40 km/h, p5/p50/p95:", np.percentile(c, [5, 50, 95]).round(1))
