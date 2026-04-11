"""Helper classes extracted from channel_manager.py.

INV-PLAYOUT-MODULE-EXTRACTION-001: These classes are importable from this
dedicated module. Backward-compatible re-exports exist in channel_manager.py.
"""

from __future__ import annotations

import logging
import socket
import weakref
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class _FeedState(Enum):
    """Feed-ahead controller state machine.

    CREATED -> SEEDED -> RUNNING -> DRAINING
    """
    CREATED = auto()   # Before seed
    SEEDED = auto()    # After seed, before first BlockCompleted
    RUNNING = auto()   # Active feeding (maintain runway >= horizon)
    DRAINING = auto()  # Session ending, no new feeds


@dataclass(frozen=True)
class _AsRunAnnotation:
    """Lightweight as-run annotation for block-level events.

    In-process only. Will be piped into the full AsRunLogger
    when that integration lands.
    """
    annotation_type: str       # e.g. "missed_ready_by"
    block_id: str
    timestamp_utc_ms: int
    metadata: dict[str, Any]   # e.g. {"lateness_ms": 3200}


class TracedSocket:
    """Diagnostic proxy: intercepts close/shutdown with stack traces.

    Wraps an accepted ``socket.socket`` so that every close/shutdown is
    logged with the full Python stack trace.  Also installs a weak-reference
    callback on the underlying socket to detect unexpected GC collection
    (which would silently close the fd and cause an EPIPE on the AIR side).

    All other attribute access is delegated transparently via ``__getattr__``.
    """

    def __init__(
        self,
        sock: socket.socket,
        channel_id: str,
        accept_generation: int,
        logger: logging.Logger,
    ):
        self._sock = sock
        self._fd = sock.fileno()
        self._channel_id = channel_id
        self._generation = accept_generation
        self._logger = logger
        # Weak-ref finalizer fires when the real socket is GC'd without an
        # explicit close() call — indicates an unexpected socket lifecycle.
        # Stored so close() can cancel it: an explicit close is expected and
        # must not trigger the GC warning.
        self._finalizer = weakref.finalize(sock, self._on_gc)

    def _on_gc(self) -> None:
        self._logger.warning(
            "INV-UDS-GC: channel=%s fd=%d gen=%d socket GC'd",
            self._channel_id,
            self._fd,
            self._generation,
        )

    def close(self) -> None:
        # Cancel the GC finalizer — an explicit close is expected, not a leak.
        self._finalizer.detach()
        self._logger.debug(
            "INV-UDS-CLOSE-TRACE: channel=%s fd=%d gen=%d",
            self._channel_id,
            self._fd,
            self._generation,
        )
        self._sock.close()

    def shutdown(self, how: int) -> None:
        self._logger.debug(
            "INV-UDS-SHUTDOWN-TRACE: channel=%s fd=%d gen=%d how=%s",
            self._channel_id,
            self._fd,
            self._generation,
            how,
        )
        self._sock.shutdown(how)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sock, name)
