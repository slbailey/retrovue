"""
Bounded ring buffer for TS bytes: upstream (AIR) → buffer → downstream (HTTP clients).

Decouples upstream from downstream: upstream never blocks on slow clients.
When full, oldest data is overwritten (live mode). Provides metrics.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Callable, Optional

_logger = logging.getLogger(__name__)

# Default max size: 8 MB (configurable 8–32 MB typical)
DEFAULT_RING_BUFFER_MAX_BYTES = 8 * 1024 * 1024


class TsRingBuffer:
    """
    Bounded thread-safe ring buffer for MPEG-TS bytes.

    - Single producer (upstream reader), single consumer (fanout thread).
    - When full, oldest chunks are dropped and dropped_bytes is updated.
    - Metrics: current_bytes, dropped_bytes, high_water_mark.
    """

    def __init__(
        self,
        max_bytes: int = DEFAULT_RING_BUFFER_MAX_BYTES,
        on_drop: Optional[Callable[[int], None]] = None,
    ):
        self._max_bytes = max(64 * 1024, max_bytes)  # at least 64 KB
        self._lock = threading.Lock()
        self._deque: deque[bytes] = deque()
        self._current_bytes = 0
        self._dropped_bytes = 0
        self._high_water_mark = 0
        self._not_empty = threading.Condition(self._lock)
        self._closed = False
        self._on_drop = on_drop  # optional callback(bytes_dropped) when we drop oldest

    def put(self, data: bytes) -> None:
        """
        Append data. If over max size, drop oldest chunks (live mode).
        Non-blocking; never blocks on downstream.
        """
        if not data or self._closed:
            return
        with self._lock:
            if self._closed:
                return
            self._deque.append(data)
            self._current_bytes += len(data)
            while self._current_bytes > self._max_bytes and len(self._deque) > 1:
                old = self._deque.popleft()
                self._current_bytes -= len(old)
                self._dropped_bytes += len(old)
                if self._on_drop:
                    try:
                        self._on_drop(len(old))
                    except Exception:
                        pass
            if self._current_bytes > self._high_water_mark:
                self._high_water_mark = self._current_bytes
            self._not_empty.notify()

    def get(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Block until a chunk is available or timeout.
        Returns None if closed or timeout.
        """
        with self._not_empty:
            while not self._closed and not self._deque:
                if timeout is not None:
                    if not self._not_empty.wait(timeout=timeout):
                        return None
                else:
                    self._not_empty.wait()
            if self._closed:
                return None
            if not self._deque:
                return None
            chunk = self._deque.popleft()
            self._current_bytes -= len(chunk)
            return chunk

    def close(self) -> None:
        """Signal no more data; unblock get()."""
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()

    @property
    def current_bytes(self) -> int:
        with self._lock:
            return self._current_bytes

    @property
    def dropped_bytes(self) -> int:
        with self._lock:
            return self._dropped_bytes

    @property
    def high_water_mark(self) -> int:
        with self._lock:
            return self._high_water_mark

    @property
    def is_closed(self) -> bool:
        with self._lock:
            return self._closed
