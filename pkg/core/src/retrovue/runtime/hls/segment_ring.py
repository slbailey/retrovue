"""
Segment Ring — bounded in-memory window of completed HLS segments.

Contracts enforced:
    INV-HLS-RING-BOUNDED-001    Bounded capacity with FIFO eviction
    INV-HLS-RING-OBSERVATION-001 Consistent observation
    INV-HLS-RING-PUSH-ATOMIC-001 Atomic insertion
    INV-HLS-RING-WINDOW-VALID-001 Post-insertion consistency
    INV-HLS-RING-EVICTION-GRACE-001 Grace margin prevents fetch race
    INV-HLS-NO-DISK-IO-001      In-memory storage

Canonical contract: docs/contracts/delivery_hls.md §2
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ReadyEvent:
    """Thread-safe readiness signal with native async wait.

    INV-HLS-READINESS-001:

    - is_set() is thread-safe (synchronous callers, tests, any thread).
    - set() is thread-safe (called from the fanout thread in push()).
    - clear() is thread-safe (called from clear() on teardown).
    - wait() is async — awaits an asyncio.Event without blocking the
      event loop and without run_in_executor.

    Loop ownership:
        The asyncio.Event is created lazily on the first wait() call,
        which runs on the event loop thread.  set()/clear() from non-loop
        threads use loop.call_soon_threadsafe() to mutate the asyncio.Event
        safely.  A threading flag tracks the canonical state so is_set()
        works from any thread without touching the asyncio.Event.
    """

    __slots__ = ("_flag", "_flag_lock", "_loop", "_async_event")

    def __init__(self) -> None:
        # Canonical state — readable from any thread.
        self._flag: bool = False
        self._flag_lock = threading.Lock()
        # Async plumbing — created lazily on the event loop thread.
        self._loop: asyncio.AbstractEventLoop | None = None
        self._async_event: asyncio.Event | None = None

    def is_set(self) -> bool:
        """Thread-safe synchronous check."""
        return self._flag

    def set(self) -> None:
        """Signal readiness from any thread."""
        with self._flag_lock:
            if self._flag:
                return  # Already set — idempotent.
            self._flag = True
        # Poke the async event so any waiter wakes up.
        if self._loop is not None and self._async_event is not None:
            self._loop.call_soon_threadsafe(self._async_event.set)

    def clear(self) -> None:
        """Reset readiness from any thread."""
        with self._flag_lock:
            self._flag = False
        if self._loop is not None and self._async_event is not None:
            self._loop.call_soon_threadsafe(self._async_event.clear)

    async def wait(self, timeout: float | None = None) -> bool:
        """Await readiness without blocking the event loop.

        Returns True if ready, False if timeout expired.
        Creates the asyncio.Event on first call (binds to the running loop).
        """
        # Fast path — already ready, no async machinery needed.
        if self._flag:
            return True

        # Lazy init: create asyncio.Event on the event loop thread.
        loop = asyncio.get_running_loop()
        if self._async_event is None or self._loop is not loop:
            self._loop = loop
            self._async_event = asyncio.Event()
            # Sync state: if flag was set between is_set() above and now.
            if self._flag:
                self._async_event.set()

        try:
            await asyncio.wait_for(self._async_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


@dataclass(frozen=True)
class LiveSegment:
    """A completed, immutable HLS segment.

    INV-HLS-SEGMENT-IMMUTABLE-001: All fields are frozen after construction.
    INV-HLS-NO-DISK-IO-001: ``data`` is in-memory bytes, never a file path.
    """

    channel_id: str
    index: int
    wall_clock_start_utc_ms: int
    duration_ms: int
    byte_count: int
    data: bytes
    discontinuity: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise TypeError(
                f"INV-HLS-NO-DISK-IO-001: data must be bytes, "
                f"got {type(self.data).__name__}"
            )
        if self.byte_count != len(self.data):
            raise ValueError(
                f"INV-HLS-SEGMENT-IMMUTABLE-001: byte_count ({self.byte_count}) "
                f"!= len(data) ({len(self.data)})"
            )
        if not isinstance(self.index, int) or self.index < 0:
            raise ValueError(
                f"INV-HLS-SEGMENT-IDENTITY-001: index must be non-negative int, "
                f"got {self.index!r}"
            )
        if not isinstance(self.wall_clock_start_utc_ms, int):
            raise TypeError(
                f"INV-HLS-SEGMENT-WALLCLOCK-001: wall_clock_start_utc_ms must be int, "
                f"got {type(self.wall_clock_start_utc_ms).__name__}"
            )
        if not isinstance(self.duration_ms, int) or self.duration_ms <= 0:
            raise ValueError(
                f"INV-HLS-SEGMENT-DURATION-BOUNDS-001: duration_ms must be positive int, "
                f"got {self.duration_ms!r}"
            )


class SegmentRing:
    """Bounded in-memory window of completed HLS segments.

    Thread-safe for 1 writer + N readers.

    INV-HLS-RING-BOUNDED-001: At most ``capacity`` segments retained.
    INV-HLS-RING-OBSERVATION-001: Readers see consistent snapshots.
    INV-HLS-RING-PUSH-ATOMIC-001: Push + evict under single lock.
    INV-HLS-RING-WINDOW-VALID-001: Post-push consistency verified.
    INV-HLS-RING-EVICTION-GRACE-001: capacity > manifest_window + 1.
    INV-HLS-NO-DISK-IO-001: All storage is in-memory.
    INV-HLS-READINESS-001: Readiness signal for playable playlist window.
    """

    def __init__(
        self,
        capacity: int,
        manifest_window: int,
        min_ready_segments: int = 3,
    ) -> None:
        # INV-HLS-RING-EVICTION-GRACE-001: capacity must exceed manifest window + 1
        if capacity <= manifest_window + 1:
            raise ValueError(
                f"INV-HLS-RING-EVICTION-GRACE-001: capacity ({capacity}) must be "
                f"strictly greater than manifest_window + 1 ({manifest_window + 1})"
            )
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        if manifest_window < 1:
            raise ValueError(f"manifest_window must be >= 1, got {manifest_window}")

        self._capacity = capacity
        self._manifest_window = manifest_window
        self._lock = threading.Lock()

        # INV-HLS-READINESS-001: Readiness signal — set when the ring
        # first contains a playable playlist window.  What constitutes
        # "playable" is configured here, not in the contract layer.
        self._min_ready_segments = max(min_ready_segments, 2)
        self._ready = ReadyEvent()

        # Ordered dict by index — segments stored in insertion order.
        # Using a plain dict (Python 3.7+ insertion-ordered) for simplicity.
        self._segments: dict[int, LiveSegment] = {}

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def manifest_window(self) -> int:
        return self._manifest_window

    @property
    def ready(self) -> ReadyEvent:
        """INV-HLS-READINESS-001: Readiness signal for playable playlist window."""
        return self._ready

    def push(self, segment: LiveSegment) -> None:
        """Add a segment. Evict oldest if over capacity.

        INV-HLS-RING-PUSH-ATOMIC-001: Push + evict under single lock.
        INV-HLS-RING-BOUNDED-001: Never exceed capacity.
        INV-HLS-RING-WINDOW-VALID-001: Post-push consistency check.
        """
        with self._lock:
            self._segments[segment.index] = segment

            # Evict oldest while over capacity
            while len(self._segments) > self._capacity:
                oldest_key = next(iter(self._segments))
                del self._segments[oldest_key]

            # INV-HLS-RING-WINDOW-VALID-001: post-push consistency
            self._check_consistency_locked()

            # INV-HLS-READINESS-001: set readiness when playable window reached
            if not self._ready.is_set() and len(self._segments) >= self._min_ready_segments:
                self._ready.set()

    def get(self, index: int) -> LiveSegment | None:
        """Return segment by index, or None if not present.

        INV-HLS-RING-OBSERVATION-001: Consistent read under lock.
        """
        with self._lock:
            return self._segments.get(index)

    def window(self) -> list[LiveSegment]:
        """Return a consistent snapshot of all segments, ordered by index.

        INV-HLS-RING-OBSERVATION-001: Snapshot is internally consistent.
        INV-HLS-RING-PUSH-ATOMIC-001: Acquired under same lock as push.
        """
        with self._lock:
            return sorted(self._segments.values(), key=lambda s: s.index)

    def oldest_index(self) -> int | None:
        """Return the index of the oldest segment, or None if empty."""
        with self._lock:
            if not self._segments:
                return None
            return min(self._segments)

    def newest_index(self) -> int | None:
        """Return the index of the newest segment, or None if empty."""
        with self._lock:
            if not self._segments:
                return None
            return max(self._segments)


    def clear(self) -> None:
        """Clear all retained segments.

        Used when a channel activation is torn down so reconnect cannot
        observe stale manifest windows from the prior activation.

        INV-HLS-READINESS-001: Reset readiness so next activation starts unready.
        """
        with self._lock:
            self._segments.clear()
            self._ready.clear()
    def count(self) -> int:
        """Return the number of segments currently in the ring."""
        with self._lock:
            return len(self._segments)

    def _check_consistency_locked(self) -> None:
        """Verify internal consistency. Must be called with lock held.

        INV-HLS-RING-WINDOW-VALID-001: newest - oldest + 1 == len(segments) <= capacity.
        """
        n = len(self._segments)
        if n == 0:
            return

        indices = sorted(self._segments.keys())
        oldest = indices[0]
        newest = indices[-1]
        expected_count = newest - oldest + 1

        if expected_count != n:
            logger.error(
                "INV-HLS-RING-WINDOW-VALID-001: consistency violation — "
                "oldest=%d, newest=%d, expected_count=%d, actual=%d. "
                "Rebuilding index range.",
                oldest, newest, expected_count, n,
            )
            # Self-repair: rebuild from actual keys (already done — dict is
            # the source of truth). The violation is logged for diagnosis.

        if n > self._capacity:
            logger.error(
                "INV-HLS-RING-WINDOW-VALID-001: capacity violation — "
                "count=%d > capacity=%d",
                n, self._capacity,
            )
