"""The CARLA demo scenario, shared by the RFID acceptance run and the feed
simulator: 8 vehicles A-H, a crash between A and B at J01, A stopping at the
junction and B escaping through J02 and J03.

Fixed simulated registration numbers and EPCs come from vivek_fb.py so the
ground truth matches the CARLA overlay plates.
"""

from __future__ import annotations

from dataclasses import dataclass

VEHICLE_IDS = tuple("ABCDEFGH")

PLATE_NUMBERS = {
    "A": "KA 01 AT 4521",
    "B": "MH 12 BR 7814",
    "C": "TN 09 CK 2365",
    "D": "KL 07 DL 9182",
    "E": "DL 03 EN 6047",
    "F": "GJ 05 FP 3419",
    "G": "AP 16 GQ 8273",
    "H": "TG 08 HR 5196",
}

JUNCTION_WORLD = {"J01": (-28.7, 28.1), "J02": (-41.6, 82.6), "J03": (-71.3, 132.3)}

# Crash details used by the simulator and the expected-scenario test.
CRASH_JUNCTION = "J01"
CRASH_TIME_S = 40.0
CRASH_FRAME = int(CRASH_TIME_S / 0.05)
INVOLVED = ("A", "B")
# Only A stays at the crash site; B keeps driving (so it keeps its speed for the
# reader model's speed penalty).
STOPPED_AFTER_CRASH = ("A",)


def epc_for(vehicle_id: str) -> str:
    """Exactly Member 1's _epc_for: index is the 1-based position in A-H."""
    index = VEHICLE_IDS.index(vehicle_id) + 1
    return f"E2000017221101{index:02X}{(0xA0B0 + index):04X}"


EPCS = {name: epc_for(name) for name in VEHICLE_IDS}

PLATE_NORM = {
    name: "".join(ch for ch in plate.upper() if ch.isalnum())
    for name, plate in PLATE_NUMBERS.items()
}


@dataclass
class Vehicle:
    vehicle_id: str
    keypoints: list          # [(t, x, y)]
    speed_kmh: float
    crash: bool = False

    def position(self, t: float) -> tuple[float, float]:
        """Linear interpolation between waypoints, clamped at both ends."""
        points = self.keypoints
        if t <= points[0][0]:
            return points[0][1], points[0][2]
        if t >= points[-1][0]:
            return points[-1][1], points[-1][2]
        for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:]):
            if t0 <= t <= t1:
                span = max(1e-9, t1 - t0)
                f = (t - t0) / span
                return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
        return points[-1][1], points[-1][2]


# A is stopped at J01 from the crash on; B escapes J01 -> J02 -> J03.
VEHICLES = [
    Vehicle("A", [(0.0, 62.0, -12.0), (40.0, -28.7, 28.1), (120.0, -28.7, 28.1)], 0.0, crash=True),
    Vehicle("B", [(0.0, 74.0, -20.0), (40.0, -28.7, 28.1), (56.0, -41.6, 82.6),
                  (72.0, -71.3, 132.3), (120.0, -95.0, 155.0)], 42.0, crash=True),
    Vehicle("C", [(0.0, -44.0, 58.0), (14.0, -41.6, 82.6), (40.0, -62.0, 104.0)], 34.0),
    Vehicle("D", [(0.0, -71.3, 108.0), (16.0, -71.3, 132.3), (56.0, -92.0, 152.0)], 30.0),
    Vehicle("E", [(0.0, -6.0, 44.0), (26.0, -28.7, 28.1), (62.0, -54.0, -2.0)], 28.0),
    # F and G cross J02 / J03 together with the fleeing B, so the camera sees an
    # uninvolved plate next to B's (it must land in all_plates_seen, never match).
    Vehicle("F", [(0.0, -18.0, 92.0), (48.0, -18.0, 92.0), (55.5, -41.6, 82.6),
                  (72.0, -72.0, 70.0)], 33.0),
    Vehicle("G", [(0.0, -52.0, 162.0), (60.0, -52.0, 162.0), (72.5, -71.3, 132.3),
                  (95.0, -92.0, 108.0)], 31.0),
    Vehicle("H", [(0.0, -42.0, 8.0), (46.0, -28.7, 28.1), (92.0, -8.0, 62.0)], 36.0),
]


def timeline(duration_s: float = 120.0, dt: float = 0.05) -> list[float]:
    count = int(round(duration_s / dt)) + 1
    return [index * dt for index in range(count)]


def vehicles_at(t: float) -> list[dict]:
    """The vehicle list the reader model's step() expects."""
    out = []
    for vehicle in VEHICLES:
        x, y = vehicle.position(t)
        speed = vehicle.speed_kmh
        if vehicle.vehicle_id in STOPPED_AFTER_CRASH and t >= CRASH_TIME_S:
            speed = 0.0
        out.append({
            "vehicle_id": vehicle.vehicle_id,
            "epc": EPCS[vehicle.vehicle_id],
            "x": x,
            "y": y,
            "speed_kmh": speed,
        })
    return out


def positions_by_vehicle(times: list[float]) -> dict[str, list[tuple[float, float]]]:
    return {
        vehicle.vehicle_id: [vehicle.position(t) for t in times]
        for vehicle in VEHICLES
    }


def speeds_by_vehicle(times: list[float]) -> dict[str, list[float]]:
    return {
        vehicle.vehicle_id: [
            (0.0 if (vehicle.vehicle_id in STOPPED_AFTER_CRASH and t >= CRASH_TIME_S)
             else vehicle.speed_kmh)
            for t in times
        ]
        for vehicle in VEHICLES
    }


def junction_for_point(x: float, y: float, max_distance_m: float = 1e9) -> str | None:
    best, best_distance = None, None
    for junction_id, (jx, jy) in JUNCTION_WORLD.items():
        distance = ((x - jx) ** 2 + (y - jy) ** 2) ** 0.5
        if best_distance is None or distance < best_distance:
            best, best_distance = junction_id, distance
    return best if best_distance is not None and best_distance <= max_distance_m else None
