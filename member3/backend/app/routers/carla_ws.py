import asyncio
import math
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Optional, Set

import hmac

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from app.core.config import settings
from app.core.database import SessionLocal
from app.dependencies.deps import authority_from_token, require_authority

from app.services.live_anpr import submit_camera_frame_to_anpr
from app.services.stream_recorder import get_recorder

# Open the recording (RFID_RECORD_PATH) at start-up, so "[RECORD] recording the
# CARLA stream to ..." is in the log before CARLA connects. No-op when unset.
get_recorder()


router = APIRouter()

# Camera server health, measured from the frames that actually arrive.
_ingest_connections = 0
_last_frame_at: Dict[str, float] = {}       # junction -> time.monotonic() of last frame
_last_frame_camera: Dict[str, str] = {}


def _junctions() -> list[str]:
    out = []
    for pair in settings.WEBRTC_STREAMS.split(","):
        if ":" in pair:
            out.append(pair.split(":", 1)[0].strip())
    return out


def camera_feed_live(junction_id: str | None = None) -> bool:
    """True while a CARLA sender is attached and frames arrived recently
    (for one junction, or for any junction when none is given)."""
    if _ingest_connections <= 0:
        return False
    now = time.monotonic()
    stamps = [_last_frame_at.get(junction_id)] if junction_id else list(_last_frame_at.values())
    return any(t is not None and now - t <= settings.CAMERA_STALE_AFTER_S for t in stamps)


@router.get("/api/cameras/status", tags=["CARLA WebSocket"], dependencies=[Depends(require_authority)])
async def camera_status():
    """Is the camera server (the CARLA frame sender) up? Connected means a
    sender is attached AND a frame arrived within CAMERA_STALE_AFTER_S."""
    now = time.monotonic()
    stale = settings.CAMERA_STALE_AFTER_S
    cameras = []
    for junction in sorted(set(_junctions()) | set(_last_frame_at)):
        age = now - _last_frame_at[junction] if junction in _last_frame_at else None
        cameras.append({"junction_id": junction, "camera_id": _last_frame_camera.get(junction),
                        "last_frame_age_s": round(age, 1) if age is not None else None,
                        "connected": _ingest_connections > 0 and age is not None and age <= stale})
    return {"connected": any(c["connected"] for c in cameras), "sender_attached": _ingest_connections > 0,
            "stale_after_s": stale, "cameras": cameras}

# Live ANPR on EVERY camera frame (all vehicles, all junctions) fed the old
# Live-page plate panel only. It is off: plates are read for an incident's
# suspect by the RFID vision step. LIVE_ANPR_ENABLED=1 restores it.
LIVE_ANPR_ENABLED = os.environ.get("LIVE_ANPR_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# RFID -> camera plate cross-verification
#
# Every call below is cheap and non-blocking: the service only buffers and
# enqueues, and it swallows its own errors. RFID can therefore never delay an
# ack, a popup or a camera frame - and a broken RFID path can never stop the
# existing stream.
# ---------------------------------------------------------------------------
_RFID_SERVICE = None
_RFID_LOCK = threading.Lock()


def _rfid_service():
    """The RFID service, or None when the feature is switched off."""
    global _RFID_SERVICE
    try:
        from app.services.rfid.config import RfidFeatureConfig

        if not RfidFeatureConfig.from_env().enabled:
            return None
        with _RFID_LOCK:
            if _RFID_SERVICE is None:
                from app.services.rfid.service import get_service

                _RFID_SERVICE = get_service()
            return _RFID_SERVICE
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[CARLA WS] RFID service unavailable: {exc}")
        return None


def _rfid_call(name, *args):
    service = _rfid_service()
    if service is None:
        return None
    try:
        return getattr(service, name)(*args)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[CARLA WS] RFID {name} failed: {exc}")
        return None


# Known CARLA junction world coordinates (matches Member 1's streaming script).
# Used to tag crash alerts with the nearest junction so the live viewer can
# highlight the exact camera feed at the moment of the crash.
CARLA_JUNCTION_LOCATIONS = {
    "J01": (-28.7, 28.1),
    "J02": (-41.6, 82.6),
    "J03": (-71.3, 132.3),
}


async def _crash_notify(name: str, message: dict) -> dict | None:
    """Owner crash notifications / review queue (services/crash_notify.py), in a
    worker thread so DB work never blocks this socket. Never raises."""
    try:
        from app.services import crash_notify

        result = await asyncio.to_thread(getattr(crash_notify, name), dict(message))
        print(f"[CRASH NOTIFY] {name}: {result}", flush=True)
        return result
    except Exception as error:
        print(f"[CRASH NOTIFY] {name} failed: {error}", flush=True)
        return None


def _utc_now_iso() -> str:
    """Current UTC wall-clock time as an ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def infer_junction_from_world_location(message: dict) -> Optional[str]:
    """Return the nearest junction id for a crash alert's world location."""
    location = message.get("world_location")
    if not isinstance(location, dict):
        return None

    try:
        x = float(location.get("x"))
        y = float(location.get("y"))
    except (TypeError, ValueError):
        return None

    best_id = None
    best_distance = None
    for junction_id, (junction_x, junction_y) in CARLA_JUNCTION_LOCATIONS.items():
        distance = math.hypot(x - junction_x, y - junction_y)
        if best_distance is None or distance < best_distance:
            best_id = junction_id
            best_distance = distance

    return best_id


# Connected React/browser clients receiving live CARLA camera frames and crash alerts.
LIVE_FRAME_BACKLOG_MAX = 2


class ViewerChannel:
    """Outgoing messages for one viewer: lossy live data, lossless alerts.

    Camera frames and telemetry keep only the newest LIVE_FRAME_BACKLOG_MAX
    messages so a slow browser never lags behind the stream. Crash alerts sit
    in their own unbounded deque, are never dropped, and are always sent
    before any pending live data.
    """

    def __init__(self) -> None:
        self.live: deque = deque(maxlen=LIVE_FRAME_BACKLOG_MAX)
        self.alerts: deque = deque()
        self._wake = asyncio.Event()

    # Never dropped, and always sent before pending live data. crash_alert keeps
    # its own semantics (the popup keys off the message type, which is
    # unchanged); the RFID events and live plate cards ride the same lossless
    # path (they are rare, and must not be evicted by camera frames).
    LOSSLESS_TYPES = {
        "crash_alert",
        "incident_created",
        "watchlist_rfid_hit",
        "vision_match_result",
        "live_plate_detection",
        "suspect_identified",
    }

    def push(self, message: dict) -> None:
        if message.get("type") in self.LOSSLESS_TYPES:
            self.alerts.append(message)
        else:
            self.live.append(message)
        self._wake.set()

    async def next_message(self) -> dict:
        while True:
            if self.alerts:
                return self.alerts.popleft()
            if self.live:
                return self.live.popleft()
            self._wake.clear()
            await self._wake.wait()


camera_clients: Set[WebSocket] = set()
camera_client_channels: Dict[WebSocket, ViewerChannel] = {}
camera_client_tasks: Dict[WebSocket, asyncio.Task] = {}

# Recent crash alerts, replayed to viewers that connect (or reconnect) AFTER
# the alert fired. Without this, a browser that reloads or drops its socket
# seconds before a crash would never show the popup. Wall-clock age limited
# so a viewer opening the portal much later is not shown a stale alert.
RECENT_ALERT_BUFFER_MAX = 20
RECENT_ALERT_MAX_AGE_S = 300.0
recent_crash_alerts: deque = deque(maxlen=RECENT_ALERT_BUFFER_MAX)

# Alert ids already accepted. Member 1 retries an alert until it receives an
# ack, so the same alert can arrive more than once (e.g. the ack was lost on a
# Tailscale blip). Duplicates are acked again but never re-broadcast, otherwise
# a retry would re-open a popup the operator already dismissed.
SEEN_ALERT_IDS_MAX = 500
seen_alert_ids: deque = deque(maxlen=SEEN_ALERT_IDS_MAX)


def is_duplicate_crash_alert(alert_id: Optional[str]) -> bool:
    """Record alert_id; return True if it was already accepted before."""
    if not alert_id:
        return False
    if alert_id in seen_alert_ids:
        return True
    seen_alert_ids.append(alert_id)
    return False


def remember_crash_alert(message: dict) -> None:
    """Store a crash alert for replay to late/reconnecting viewers."""
    if message.get("type") != "crash_alert":
        return
    recent_crash_alerts.append((time.monotonic(), message))


def replay_recent_alerts(channel: ViewerChannel) -> None:
    """Push all fresh, buffered crash alerts (oldest first) to a new viewer.

    Oldest-first means the newest alert is registered last, so it is the one
    the popup ends up showing.
    """
    now = time.monotonic()
    for buffered_at, message in tuple(recent_crash_alerts):
        if (now - buffered_at) <= RECENT_ALERT_MAX_AGE_S:
            channel.push(message)


async def _send_camera_frames(websocket: WebSocket, channel: ViewerChannel) -> None:
    """Send queued messages independently of the CARLA ingestion loop."""
    while True:
        message = await channel.next_message()
        try:
            await websocket.send_json(message)
        except Exception:
            return


# The event loop serving the viewers. Worker threads (RFID service, live ANPR)
# also broadcast; asyncio.Event is not thread-safe, so their pushes are handed
# to this loop instead of waking the sender tasks from a foreign thread.
_viewer_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_live_message(message: dict) -> None:
    """Forward any current CARLA event to the authority live viewer clients.
    Safe to call from the event loop or from any worker thread."""
    loop = _viewer_loop
    if loop is not None and not loop.is_closed():
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not loop:
            loop.call_soon_threadsafe(_push_to_viewers, message)
            return
    _push_to_viewers(message)


def _push_to_viewers(message: dict) -> None:
    for client in tuple(camera_clients):
        channel = camera_client_channels.get(client)
        if channel is not None:
            channel.push(message)


def broadcast_camera_frame(message: dict) -> None:
    """Backward-compatible helper for camera frame forwarding."""
    broadcast_live_message(message)


@router.websocket("/ws/carla/cameras")
async def carla_camera_ingestion(websocket: WebSocket):
    """
    CARLA / Member 1 -> FastAPI

    Receives continuous camera_frame messages from CARLA.
    The incoming message format is preserved unchanged.
    """

    expected = settings.CARLA_INGEST_TOKEN
    if expected and not hmac.compare_digest(websocket.query_params.get("token", ""), expected):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await websocket.accept()
    global _ingest_connections
    _ingest_connections += 1

    print("[CARLA WS] Member 1 camera connection established")

    # Opt-in raw stream recording (RFID_RECORD_PATH); None when off.
    recorder = get_recorder()

    try:
        while True:
            message = await websocket.receive_json()
            if recorder is not None:
                recorder.record(message)
            message_type = message.get("type")

            if message_type == "camera_frame":
                required_fields = [
                    "timestamp_sim",
                    "frame",
                    "camera_id",
                    "junction_id",
                    "encoding",
                    "width",
                    "height",
                    "has_number_plate_overlay",
                    "image",
                ]

                missing_fields = [
                    field for field in required_fields
                    if field not in message
                ]

                if missing_fields:
                    print(
                        "[CARLA WS] Invalid camera_frame. "
                        f"Missing fields: {missing_fields}"
                    )
                    continue

                junction_id = message["junction_id"]
                camera_id = message["camera_id"]
                frame_number = message["frame"]
                _last_frame_at[junction_id] = time.monotonic()
                _last_frame_camera[junction_id] = camera_id

                # Fire-and-forget: hand the newest frame to the live ANPR
                # worker. Overwrite semantics keep only the newest frame per
                # junction; a slow ANPR pass never blocks the stream.
                if LIVE_ANPR_ENABLED:
                    submit_camera_frame_to_anpr(
                        junction_id=junction_id,
                        image_base64=message["image"],
                        timestamp_sim=float(message["timestamp_sim"]),
                        frame_number=int(frame_number),
                        camera_id=camera_id,
                    )

                # Ring-buffer the raw frame for a later vision pass. Cheap
                # (bytes only) and lazy: nothing is decoded here.
                _rfid_call("on_camera_frame", message)

                print(
                    f"[CARLA WS] "
                    f"junction={junction_id} "
                    f"camera={camera_id} "
                    f"frame={frame_number}"
                )

            elif message_type == "rfid_reading":
                # Normalize + buffer (legacy per-read OR v2 tag report), count
                # sequence gaps, and archive the raw report. Non-blocking.
                result = _rfid_call("on_rfid_message", message)
                if result and result.get("status") == "ignored":
                    print("[CARLA WS] ignored malformed rfid_reading")

            elif message_type == "vehicle_state":
                # Member 1's escape detection names the fleeing vehicle.
                if message.get("escape_confirmed"):
                    _rfid_call("on_vehicle_state", message)
                    # hit-and-run -> authority review queue (never the accused owner)
                    await _crash_notify("handle_vehicle_state", message)

            elif message_type == "vehicle_boxes":
                # 20 Hz box-only messages (member1/netra/netra_sensor_upgrades.py):
                # NETRA's camera input (no-op unless RFID_NETRA_ENABLED).
                _rfid_call("on_vehicle_boxes", message)

            elif message_type in {
                "imu_reading",
                "imu_detection",
                "gps_reading",
            }:
                pass

            elif message_type == "crash_alert":
                alert_id = message.get("alert_id") or "unknown"

                if is_duplicate_crash_alert(message.get("alert_id")):
                    # Member 1 retried an alert we already broadcast. Do not
                    # re-broadcast (the operator already saw the popup), but DO
                    # still let RFID see it: alert ids repeat every CARLA run, so
                    # the RFID service's own run-scoped dedupe - not this global
                    # transport guard - is what decides idempotency per run.
                    # Ack first: RFID work never delays the ack.
                    print(f"[CARLA WS] duplicate crash_alert acked: alert_id={alert_id}")
                    await websocket.send_json({
                        "type": "crash_alert_ack",
                        "alert_id": alert_id,
                        "duplicate": True,
                    })
                    _rfid_call("on_crash_alert", message)
                    # its own per-vehicle-incident dedup decides; no second SMS
                    await _crash_notify("handle_crash_alert", message)
                    continue

                vehicle_id = message.get("vehicle_id") or "unknown"
                partner = message.get("collision_partner") or "unknown"
                timestamp = message.get("timestamp_sim") or message.get("timestamp")

                # Tag the alert with the junction nearest to the crash location
                # so the live viewer can highlight the correct camera feed.
                if not message.get("junction_id"):
                    inferred_junction = infer_junction_from_world_location(message)
                    if inferred_junction:
                        message["junction_id"] = inferred_junction

                # Wall-clock receive time lets the viewer correlate the popup
                # with real-world timing, separate from the sim timestamp.
                message["received_at"] = _utc_now_iso()

                # Owners' "are you safe?" alerts first (a few ms of DB work), so
                # the viewers' alert carries the crash it was grouped into:
                # incident_id = the CR-... key the owners answer, plus location.
                notified = await _crash_notify("handle_crash_alert", message)
                if notified and notified.get("incident_key"):
                    from app.services.crash_notify import location_text
                    message["incident_id"] = notified["incident_key"]
                    message["location"] = location_text(message)

                # Buffer for viewers that connect/reconnect after the crash.
                remember_crash_alert(message)

                print(
                    "[CARLA WS] crash_alert received: "
                    f"alert_id={alert_id} vehicle={vehicle_id} "
                    f"collision_partner={partner} timestamp={timestamp} "
                    f"junction={message.get('junction_id')}"
                )

            else:
                print(
                    f"[CARLA WS] Ignoring unsupported message type: "
                    f"{message_type}"
                )
                continue

            broadcast_live_message(message)

            if message_type == "crash_alert":
                # Ack only after the alert is buffered and queued to viewers,
                # so Member 1 stops retrying only once delivery is guaranteed.
                await websocket.send_json({
                    "type": "crash_alert_ack",
                    "alert_id": message.get("alert_id") or "unknown",
                    "duplicate": False,
                })
                # RFID cross-verification AFTER the ack: create/merge the
                # incident and start the crash-zone snapshot. All DB work is
                # queued, so this is cheap, but it can never delay the ack.
                _rfid_call("on_crash_alert", message)

    except WebSocketDisconnect:
        print("[CARLA WS] Member 1 camera connection disconnected")
        # A reconnect after a gap is a new CARLA run: run-scoped keys reset.
        _rfid_call("note_disconnect")

    except Exception as exc:
        print(f"[CARLA WS] Camera ingestion error: {exc}")

    finally:
        _ingest_connections = max(0, _ingest_connections - 1)
        print("[CARLA WS] Camera ingestion connection closed")


@router.websocket("/ws/live-cameras")
async def live_camera_stream(websocket: WebSocket):
    """
    FastAPI -> React Authority Portal

    React connects here to receive live CARLA camera frames. Authority only:
    the browser passes its login token as ?token=.
    """

    db = SessionLocal()
    try:
        viewer = authority_from_token(db, websocket.query_params.get("token"))
    finally:
        db.close()
    if viewer is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    global _viewer_loop
    _viewer_loop = asyncio.get_running_loop()

    await websocket.send_json({
        "type": "connected",
        "message": "Live camera stream is ready.",
    })

    camera_clients.add(websocket)
    channel = ViewerChannel()
    camera_client_channels[websocket] = channel
    camera_client_tasks[websocket] = asyncio.create_task(
        _send_camera_frames(websocket, channel)
    )

    # Replay fresh buffered crash alerts so a viewer that opens/reloads the
    # portal after a crash still gets the popup immediately.
    replay_recent_alerts(channel)

    print(
        f"[LIVE CAMERA WS] Frontend connected. "
        f"Clients: {len(camera_clients)}"
    )

    try:
        while True:
            # Keep the WebSocket connection alive.
            # The frontend does not need to send anything.
            await websocket.receive_text()

    except WebSocketDisconnect:
        print("[LIVE CAMERA WS] Frontend disconnected")

    except Exception as exc:
        print(f"[LIVE CAMERA WS] Connection error: {exc}")

    finally:
        camera_clients.discard(websocket)
        camera_client_channels.pop(websocket, None)
        sender_task = camera_client_tasks.pop(websocket, None)
        if sender_task is not None:
            sender_task.cancel()

        print(
            f"[LIVE CAMERA WS] Frontend removed. "
            f"Clients: {len(camera_clients)}"
        )