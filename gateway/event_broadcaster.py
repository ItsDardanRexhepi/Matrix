"""
gateway/event_broadcaster.py
============================

In-process pub/sub fan-out for the `/api/v1/events/stream` SSE endpoint.

The ``EventBroadcaster`` is intentionally tiny and has **no persistence**
— it's purely a live feed for connected SSE subscribers. Durable events
still go through ``hivemind.events.EventBus``; the broadcaster is the
push side of the house.

Design notes
------------

* Each connected SSE client gets its own ``asyncio.Queue`` (bounded, to
  prevent a slow mobile client from pinning gateway memory).
* Publishing is **lossless by default** for fast clients and
  **lossy for slow clients** — if a subscriber's queue is full we drop
  the oldest event (``QueueFull`` → ``get_nowait``/``put_nowait`` dance)
  and increment a dropped counter so operators can see abuse.
* ``publish`` is a synchronous, non-blocking call that can be invoked
  from any async context (including middleware and service handlers).
* ``subscribe`` returns a ``Subscription`` context manager that yields
  events as an async iterator.

The Packager's SSE parser (see ``MTRXPackager.handleSSEMessage``)
expects each server-sent event to carry a JSON payload with at least
``type`` and ``payload`` fields. This module guarantees that shape.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public event shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BroadcastEvent:
    """A single event pushed to every matching SSE subscriber."""

    type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    #: Optional component id — used to filter for clients that only
    #: care about one service (e.g. ``?components=3,13``).
    component: Optional[int] = None
    #: Optional session id — lets clients scope the feed to their own
    #: session (``?session=<id>``).
    session_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "payload": self.payload,
            "component": self.component,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "event_id": self.event_id,
        }


# ---------------------------------------------------------------------------
# Per-subscriber state
# ---------------------------------------------------------------------------


class _Subscriber:
    """One connected SSE client."""

    __slots__ = (
        "queue",
        "components",
        "session_id",
        "types",
        "dropped",
        "created_at",
    )

    def __init__(
        self,
        *,
        max_queue: int,
        components: Optional[Iterable[int]],
        session_id: Optional[str],
        types: Optional[Iterable[str]],
    ) -> None:
        self.queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue(maxsize=max_queue)
        self.components = set(components) if components else None
        self.session_id = session_id
        self.types = set(types) if types else None
        self.dropped = 0
        self.created_at = time.time()

    def matches(self, event: BroadcastEvent) -> bool:
        if self.types is not None and event.type not in self.types:
            return False
        if self.components is not None:
            if event.component is None or event.component not in self.components:
                return False
        if self.session_id is not None:
            if event.session_id is not None and event.session_id != self.session_id:
                return False
        return True

    def try_enqueue(self, event: BroadcastEvent) -> None:
        """Non-blocking enqueue; drops the oldest on overflow."""

        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                _ = self.queue.get_nowait()
                self.queue.task_done()
            except Exception:  # pragma: no cover — best effort
                pass
            try:
                self.queue.put_nowait(event)
            except asyncio.QueueFull:  # pragma: no cover
                self.dropped += 1
                return
            self.dropped += 1


# ---------------------------------------------------------------------------
# The broadcaster itself
# ---------------------------------------------------------------------------


class EventBroadcaster:
    """Fan-out hub used by the SSE endpoint and anyone who wants to push."""

    def __init__(self, *, max_queue_per_subscriber: int = 256) -> None:
        self._subs: List[_Subscriber] = []
        self._lock = asyncio.Lock()
        self._max_queue = max_queue_per_subscriber
        self._published = 0

    # -- subscription lifecycle -----------------------------------------

    async def register(
        self,
        *,
        components: Optional[Iterable[int]] = None,
        session_id: Optional[str] = None,
        types: Optional[Iterable[str]] = None,
    ) -> _Subscriber:
        sub = _Subscriber(
            max_queue=self._max_queue,
            components=components,
            session_id=session_id,
            types=types,
        )
        async with self._lock:
            self._subs.append(sub)
        logger.debug(
            "SSE subscriber registered (total=%d, components=%s, session=%s)",
            len(self._subs),
            components,
            session_id,
        )
        return sub

    async def unregister(self, sub: _Subscriber) -> None:
        async with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass
        logger.debug("SSE subscriber gone (remaining=%d, dropped=%d)",
                     len(self._subs), sub.dropped)

    async def iter_events(
        self,
        sub: _Subscriber,
        *,
        keepalive_interval: float = 15.0,
    ) -> AsyncIterator[Optional[BroadcastEvent]]:
        """Yield events for *sub* until cancelled.

        ``None`` is yielded every ``keepalive_interval`` seconds so the
        caller can emit an SSE comment line and keep the TCP connection
        warm through NAT / load-balancer idle timeouts.
        """

        while True:
            try:
                event = await asyncio.wait_for(sub.queue.get(), keepalive_interval)
            except asyncio.TimeoutError:
                yield None
                continue
            except asyncio.CancelledError:
                return
            yield event

    # -- publish --------------------------------------------------------

    def publish(self, event: BroadcastEvent) -> int:
        """Fan *event* out to every matching subscriber.

        Safe to call from any async context. Returns the number of
        subscribers the event was delivered to.
        """

        self._published += 1
        delivered = 0
        # Snapshot the subscriber list so we don't hold the lock while
        # iterating. Registrations during publish are fine — newcomers
        # just get later events.
        for sub in list(self._subs):
            if sub.matches(event):
                sub.try_enqueue(event)
                delivered += 1
        return delivered

    def publish_dict(
        self,
        type_: str,
        payload: Dict[str, Any],
        *,
        component: Optional[int] = None,
        session_id: Optional[str] = None,
    ) -> int:
        return self.publish(
            BroadcastEvent(
                type=type_,
                payload=payload,
                component=component,
                session_id=session_id,
            )
        )

    # -- introspection --------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        return {
            "subscribers": len(self._subs),
            "published_total": self._published,
            "dropped_total": sum(s.dropped for s in self._subs),
            "max_queue_per_subscriber": self._max_queue,
        }
