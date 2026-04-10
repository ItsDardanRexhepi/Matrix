"""
gateway/event_broadcaster.py
============================

In-process pub/sub fan-out for the ``/api/v1/events/stream`` SSE endpoint.

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
* The broadcaster keeps a bounded **replay buffer** of the most recent
  events so reconnecting SSE clients can ask for everything after
  ``Last-Event-ID`` and not lose data during a brief network drop.
* Subscribers are counted per-IP and globally so a single misbehaving
  client can't exhaust gateway memory.

The Packager's SSE parser (see ``MTRXPackager.handleSSEMessage``)
expects each server-sent event to carry a JSON payload with at least
``type`` and ``payload`` fields. This module guarantees that shape.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, Iterable, List, Optional

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
        "remote_ip",
    )

    def __init__(
        self,
        *,
        max_queue: int,
        components: Optional[Iterable[int]],
        session_id: Optional[str],
        types: Optional[Iterable[str]],
        remote_ip: Optional[str] = None,
    ) -> None:
        self.queue: asyncio.Queue[BroadcastEvent] = asyncio.Queue(maxsize=max_queue)
        self.components = set(components) if components else None
        self.session_id = session_id
        self.types = set(types) if types else None
        self.dropped = 0
        self.created_at = time.time()
        self.remote_ip = remote_ip

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
# Errors
# ---------------------------------------------------------------------------


class BroadcasterCapacityError(Exception):
    """Raised when a new subscriber would exceed a capacity limit."""

    def __init__(self, message: str, *, scope: str) -> None:
        super().__init__(message)
        #: Either ``"global"`` or ``"per_ip"`` so callers can map this
        #: to the right HTTP status (503 vs 429).
        self.scope = scope


# ---------------------------------------------------------------------------
# The broadcaster itself
# ---------------------------------------------------------------------------


class EventBroadcaster:
    """Fan-out hub used by the SSE endpoint and anyone who wants to push."""

    def __init__(
        self,
        *,
        max_queue_per_subscriber: int = 256,
        max_subscribers: int = 512,
        max_subscribers_per_ip: int = 8,
        replay_buffer_size: int = 512,
        metrics: Optional[Any] = None,
    ) -> None:
        self._subs: List[_Subscriber] = []
        self._lock = asyncio.Lock()
        self._max_queue = max_queue_per_subscriber
        self._max_subscribers = max_subscribers
        self._max_subscribers_per_ip = max_subscribers_per_ip
        self._published = 0
        #: Ring buffer of the most recent events, keyed by insertion
        #: order. Used to answer ``Last-Event-ID`` reconnect requests.
        self._replay: Deque[BroadcastEvent] = deque(maxlen=replay_buffer_size)
        self._metrics = metrics

    # -- metrics plumbing -----------------------------------------------

    def attach_metrics(self, metrics: Any) -> None:
        """Attach a ``MetricsCollector`` after construction.

        The gateway typically constructs the broadcaster inside
        ``ServiceRoutes.__init__`` before the metrics collector is
        fully wired; this lets ``GatewayServer`` attach its collector
        once both exist.
        """

        self._metrics = metrics

    def _metric_incr(self, name: str, value: int = 1) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.incr(name, value)
        except Exception:  # pragma: no cover — telemetry must never raise
            pass

    def _metric_gauge(self, name: str, value: float) -> None:
        if self._metrics is None:
            return
        try:
            # MetricsCollector exposes set_gauge(); fall back to incr if
            # the collector predates gauges.
            setter = getattr(self._metrics, "set_gauge", None)
            if callable(setter):
                setter(name, value)
        except Exception:  # pragma: no cover
            pass

    # -- subscription lifecycle -----------------------------------------

    async def register(
        self,
        *,
        components: Optional[Iterable[int]] = None,
        session_id: Optional[str] = None,
        types: Optional[Iterable[str]] = None,
        remote_ip: Optional[str] = None,
    ) -> _Subscriber:
        """Register a new SSE subscriber.

        Raises :class:`BroadcasterCapacityError` if the global cap or
        the per-IP cap would be exceeded. Callers should translate
        ``scope == "global"`` to HTTP 503 (Service Unavailable) and
        ``scope == "per_ip"`` to HTTP 429 (Too Many Requests).
        """

        sub = _Subscriber(
            max_queue=self._max_queue,
            components=components,
            session_id=session_id,
            types=types,
            remote_ip=remote_ip,
        )
        async with self._lock:
            if len(self._subs) >= self._max_subscribers:
                self._metric_incr("sse.rejected.global")
                raise BroadcasterCapacityError(
                    f"SSE subscriber cap reached ({self._max_subscribers})",
                    scope="global",
                )
            if remote_ip is not None:
                same_ip = sum(1 for s in self._subs if s.remote_ip == remote_ip)
                if same_ip >= self._max_subscribers_per_ip:
                    self._metric_incr("sse.rejected.per_ip")
                    raise BroadcasterCapacityError(
                        (
                            f"SSE subscriber cap reached for IP "
                            f"{remote_ip} ({self._max_subscribers_per_ip})"
                        ),
                        scope="per_ip",
                    )
            self._subs.append(sub)

        self._metric_incr("sse.subscribers.opened")
        self._metric_gauge("sse.subscribers.current", len(self._subs))
        logger.debug(
            "SSE subscriber registered (total=%d, components=%s, session=%s, ip=%s)",
            len(self._subs),
            components,
            session_id,
            remote_ip,
        )
        return sub

    async def unregister(self, sub: _Subscriber) -> None:
        async with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass
            remaining = len(self._subs)
        self._metric_incr("sse.subscribers.closed")
        self._metric_gauge("sse.subscribers.current", remaining)
        if sub.dropped:
            self._metric_incr("sse.events.dropped", sub.dropped)
        logger.debug(
            "SSE subscriber gone (remaining=%d, dropped=%d)",
            remaining,
            sub.dropped,
        )

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

    # -- replay ---------------------------------------------------------

    def replay_since(
        self,
        last_event_id: str,
        *,
        matcher: Optional[_Subscriber] = None,
    ) -> List[BroadcastEvent]:
        """Return every buffered event newer than ``last_event_id``.

        If ``last_event_id`` is unknown (rotated out of the ring buffer
        or never existed) the caller gets the entire buffer back — it's
        better to re-deliver than to silently lose state.

        When *matcher* is provided, events that don't pass its filters
        are skipped so a reconnecting client only sees events it would
        have seen on the live stream.
        """

        events = list(self._replay)
        if not events:
            return []

        start_idx: Optional[int] = None
        for idx, evt in enumerate(events):
            if evt.event_id == last_event_id:
                start_idx = idx + 1
                break

        if start_idx is None:
            self._metric_incr("sse.replay.cursor_miss")
            tail = events
        else:
            tail = events[start_idx:]

        if matcher is not None:
            tail = [e for e in tail if matcher.matches(e)]

        if tail:
            self._metric_incr("sse.replay.delivered", len(tail))
        return tail

    def replay_buffer_size(self) -> int:
        """Current number of events held in the replay ring buffer."""

        return len(self._replay)

    # -- publish --------------------------------------------------------

    def publish(self, event: BroadcastEvent) -> int:
        """Fan *event* out to every matching subscriber.

        Safe to call from any async context. Returns the number of
        subscribers the event was delivered to.
        """

        self._published += 1
        self._replay.append(event)
        self._metric_incr("sse.events.published")
        delivered = 0
        # Snapshot the subscriber list so we don't hold the lock while
        # iterating. Registrations during publish are fine — newcomers
        # just get later events.
        for sub in list(self._subs):
            if sub.matches(event):
                sub.try_enqueue(event)
                delivered += 1
        if delivered:
            self._metric_incr("sse.events.delivered", delivered)
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
            "max_subscribers": self._max_subscribers,
            "max_subscribers_per_ip": self._max_subscribers_per_ip,
            "replay_buffer": len(self._replay),
            "replay_buffer_capacity": self._replay.maxlen,
        }
