"""Demo the live dashboards WITHOUT CARLA.

Sends the same v1.8 messages the CARLA script sends, over the same backend
endpoint (/ws/carla/cameras), so the real crash -> text-message / review-queue
path runs. Fines go through the authority REST API.

    python tools/simulate_events.py fine            # (a) authority fines car C
    python tools/simulate_events.py crash-single    # (b) single-vehicle crash of A
    python tools/simulate_events.py crash-pair      # (c) A-B crash, B leaves (hit-and-run)
    python tools/simulate_events.py all             # a, b, c with pauses

Options: --base http://127.0.0.1:8000  --pause 4  --credentials demo_credentials.local.md
The authority password is read from demo_credentials.local.md (gitignored) or
the AGHAT_AUTHORITY_PASSWORD environment variable.

Note: alerts for the same car within CRASH_NOTIFY_COOLDOWN_S (default 120 s)
are one incident - one text message. To see (b) and (c) both text Arjun, start
the backend with CRASH_NOTIFY_COOLDOWN_S=10 or wait between them.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "member3" / "backend"))
from app.core.fleet import FLEET  # noqa: E402  (the single A-H map)

RUN = uuid.uuid4().hex[:6].upper()
_seq = 0


def authority_password(credentials: Path) -> str:
    if os.environ.get("AGHAT_AUTHORITY_PASSWORD"):
        return os.environ["AGHAT_AUTHORITY_PASSWORD"]
    if credentials.exists():
        for line in credentials.read_text(encoding="utf-8").splitlines():
            cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[-2] == "authority.admin":
                return cells[-1]
    sys.exit("Authority password not found: set AGHAT_AUTHORITY_PASSWORD or create demo_credentials.local.md")


def alert(letter: str, status: str, partner: str | None = None, **extra) -> dict:
    global _seq
    _seq += 1
    car = FLEET[letter]
    message = {
        "type": "crash_alert", "alert_id": f"SIM-{RUN}-{_seq:03d}", "timestamp_sim": 40.0 + _seq,
        "frame": 800 + _seq, "vehicle_id": letter, "plate_number": car.plate, "epc": car.epc,
        "status": status, "crash_probability": 0.96,
        "gps": {"latitude": 0.000252, "longitude": -0.000258, "altitude": 0.0},
        # J01 world coordinates: the backend infers junction_id from these
        "world_location": {"x": -28.7, "y": 28.1, "z": 0.0},
        "collision_partner": partner,
    }
    message.update(extra)
    return message


def send_pipeline(base: str, messages: list[dict]) -> None:
    url = base.replace("http", "ws", 1).rstrip("/") + "/ws/carla/cameras"
    token = os.environ.get("CARLA_INGEST_TOKEN")
    if token:
        url += f"?token={token}"
    with connect(url) as ws:
        for message in messages:
            ws.send(json.dumps(message))
            label = message.get("status") or message.get("state")
            print(f"  -> {message['type']} {message['vehicle_id']} {label}")
            if message["type"] == "crash_alert":
                deadline = time.time() + 10
                while time.time() < deadline:
                    reply = json.loads(ws.recv(timeout=10))
                    if reply.get("type") == "crash_alert_ack" and reply.get("alert_id") == message["alert_id"]:
                        print(f"     ack {reply['alert_id']}")
                        break
            time.sleep(0.5)


def do_fine(base: str, credentials: Path) -> None:
    print("(a) authority issues a fine to car C")
    with httpx.Client(base_url=base, timeout=15) as http:
        r = http.post("/api/auth/login", json={"email": "authority.admin",
                                               "password": authority_password(credentials)})
        r.raise_for_status()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = http.post("/api/authority/fines", headers=headers, json={
            "vehicle": "C", "amount": 1500, "reason": "Red-light violation", "location": "Junction 1, Town10HD"})
        r.raise_for_status()
        fine = r.json()
        print(f"  fine #{fine['id']} Rs {fine['amount']:.0f} -> {fine['plate']} ({fine['owner_name']})")


def do_single(base: str) -> None:
    print("(b) single-vehicle crash of car A")
    send_pipeline(base, [alert("A", "COLLISION_EVENT_SINGLE_VEHICLE")])


def do_pair(base: str) -> None:
    print("(c) A-B two-vehicle crash; B leaves the scene")
    b = FLEET["B"]
    send_pipeline(base, [
        alert("A", "COLLISION_EVENT_CONFIRMED_IMU_GPS", partner="B", collision_partner_plate=b.plate,
              decision_route="mutual_shock", pair_distance_m=1.4, relative_speed_kmh=31.5,
              closing_distance_m=3.2, association_score=6),
        alert("B", "COLLISION_EVENT_CONFIRMED_PARTNER_ASSOCIATION", partner="A",
              collision_partner_plate=FLEET["A"].plate, decision_route="mutual_shock"),
        {"type": "vehicle_state", "timestamp_sim": 47.5, "frame": 950, "vehicle_id": "B",
         "plate_number": b.plate, "epc": b.epc, "state": "POST_CRASH_MOVING", "speed_kmh": 22.4,
         "distance_from_crash_m": 14.8, "escape_confirmed": True},
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", choices=["fine", "crash-single", "crash-pair", "all"])
    parser.add_argument("--base", default=os.environ.get("AGHAT_BACKEND", "http://127.0.0.1:8000"))
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between steps of 'all'")
    parser.add_argument("--credentials", type=Path, default=ROOT / "demo_credentials.local.md")
    args = parser.parse_args()
    steps = {"fine": [lambda: do_fine(args.base, args.credentials)],
             "crash-single": [lambda: do_single(args.base)],
             "crash-pair": [lambda: do_pair(args.base)]}
    steps["all"] = steps["fine"] + steps["crash-single"] + steps["crash-pair"]
    for index, step in enumerate(steps[args.scenario]):
        if index:
            time.sleep(args.pause)
        step()
    print("done. Watch /authority/live and /me.")


if __name__ == "__main__":
    main()
