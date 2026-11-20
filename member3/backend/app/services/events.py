"""
AGHAT SETHU — Live event hub for the dashboards (/ws/events).

Rooms
  authority      every event (authority / admin users)
  user:<id>      only that owner's own events

Room membership is decided on the server from the verified token, never by the
client, so an owner can never subscribe to another owner's room.

The database is the source of truth: callers commit first, then ``publish``.
A client that missed events re-fetches state over REST when it (re)connects.

``publish`` is thread-safe (crash handling runs in a worker thread); each
event is handed to the event loop that serves that subscriber's socket.
"""

from __future__ import annotations

import asyncio
import itertools
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

AUTHORITY_ROOM = "authority"
EVENT_TYPES = {"fine.issued", "fine.updated", "crash.detected", "crash.partner_named",
               "hit_and_run.detected", "notification.created", "review.updated",
               "crash.response", "crash.response_reviewed"}
QUEUE_MAX = 500


def user_room(user_id) -> str:
    return f"user:{user_id}"


@dataclass
class Subscriber:
    rooms: frozenset
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_MAX))
    dropped: bool = False

    def offer(self, event: dict) -> None:
        """Runs on the subscriber's own loop."""
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # A stuck client: its socket closes, the page reconnects and
            # reloads state over REST.
            self.dropped = True


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[int, Subscriber] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Kept for the app lifespan; each socket records its own loop."""

    def subscribe(self, rooms) -> tuple[int, Subscriber]:
        """Call from the socket's coroutine."""
        sub = Subscriber(rooms=frozenset(rooms), loop=asyncio.get_running_loop())
        with self._lock:
            sub_id = next(self._ids)
            self._subs[sub_id] = sub
        return sub_id, sub

    def unsubscribe(self, sub_id: int) -> None:
        with self._lock:
            self._subs.pop(sub_id, None)

    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(self, event_type: str, data: dict, rooms) -> None:
        """Queue ``event_type`` for every subscriber in any of ``rooms``.
        Safe to call from any thread."""
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {event_type}")
        event = {"type": event_type, "data": data, "at": datetime.now(timezone.utc).isoformat()}
        rooms = frozenset(rooms)
        with self._lock:
            targets = [sub for sub in self._subs.values() if sub.rooms & rooms]
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        for sub in targets:
            if sub.loop is running:
                sub.offer(event)
            elif not sub.loop.is_closed():
                sub.loop.call_soon_threadsafe(sub.offer, event)


hub = EventHub()


def publish(event_type: str, data: dict, *, user_ids=(), authority: bool = True) -> None:
    rooms = [user_room(u) for u in user_ids if u]
    if authority:
        rooms.append(AUTHORITY_ROOM)
    hub.publish(event_type, data, rooms)
