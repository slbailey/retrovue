"""
HLS Session Manager — viewer presence tracking for HLS clients.

HLS clients do not maintain persistent connections. Viewer presence is
inferred from recent successful HTTP requests (manifest or segment fetches).

Contracts enforced:
    INV-HLS-VIEWER-PRESENCE-001        Request-based detection
    INV-HLS-VIEWER-COUNT-ACCURATE-001  Count matches session state
    INV-HLS-SESSION-REAP-BOUNDED-001   Bounded reap timing
    INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 First/last viewer atomicity
    INV-HLS-PHANTOM-CLEANUP-001        Failed startup cleanup

Canonical contract: docs/contracts/delivery_hls.md §5
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class HlsSessionManager:
    """Tracks HLS viewer sessions for a single channel.

    Thread-safe for concurrent calls from HTTP handlers and the reap timer.

    INV-HLS-VIEWER-PRESENCE-001: Presence is inferred from request recency.
    INV-HLS-VIEWER-COUNT-ACCURATE-001: count() == len(active sessions) at all times.
    INV-HLS-SESSION-FIRST-VIEWER-ONCE-001: First/last viewer transitions fire exactly once.
    """

    def __init__(
        self,
        channel_id: str,
        session_timeout_ms: int = 30_000,
        reap_interval_ms: int = 10_000,
        viewer_join_callback: Callable[[], None] | None = None,
        viewer_leave_callback: Callable[[], None] | None = None,
        log: logging.Logger | None = None,
    ) -> None:
        self._channel_id = channel_id
        self._session_timeout_ms = session_timeout_ms
        self._reap_interval_ms = reap_interval_ms
        self._on_viewer_join = viewer_join_callback
        self._on_viewer_leave = viewer_leave_callback
        self._log = log or logger

        # INV-HLS-SESSION-REAP-BOUNDED-001: reap_interval <= timeout / 2
        if reap_interval_ms > session_timeout_ms // 2:
            self._log.warning(
                "INV-HLS-SESSION-REAP-BOUNDED-001: reap_interval_ms (%d) exceeds "
                "timeout / 2 (%d) for channel %s — clamping",
                reap_interval_ms, session_timeout_ms // 2, channel_id,
            )
            self._reap_interval_ms = session_timeout_ms // 2

        self._lock = threading.Lock()
        # session_id → last_activity_ms (caller-provided clock)
        self._sessions: dict[str, int] = {}
        # Track lifecycle transition counts for diagnostics
        self._first_viewer_count = 0
        self._last_viewer_count = 0
        # Internal clock for touch timestamps (set by caller or via set_clock)
        self._clock_ms: int = 0

    @property
    def session_timeout_ms(self) -> int:
        return self._session_timeout_ms

    @property
    def reap_interval_ms(self) -> int:
        return self._reap_interval_ms

    def set_clock(self, ms: int) -> None:
        """Set the internal clock for testing. Production code passes now_ms to reap_expired()."""
        self._clock_ms = ms

    def touch(self, session_id: str) -> None:
        """Record activity for a viewer session.

        INV-HLS-VIEWER-PRESENCE-001: First touch creates session.
        INV-HLS-SESSION-FIRST-VIEWER-ONCE-001: 0→1 transition fires exactly once.
        INV-HLS-VIEWER-COUNT-ACCURATE-001: Create + increment atomic.
        INV-HLS-PHANTOM-CLEANUP-001: Only call touch() on successful (200) responses.
        """
        with self._lock:
            is_new = session_id not in self._sessions
            self._sessions[session_id] = self._clock_ms

            if is_new and len(self._sessions) == 1:
                # 0→1 transition: first viewer
                self._first_viewer_count += 1
                self._log.info(
                    "[HLS %s] First viewer: session %s (transition #%d)",
                    self._channel_id, session_id, self._first_viewer_count,
                )
                if self._on_viewer_join is not None:
                    self._on_viewer_join()

    def remove(self, session_id: str) -> None:
        """Immediately remove a session.

        Triggers viewer_leave_callback if the session existed and count reaches 0.
        """
        with self._lock:
            if session_id not in self._sessions:
                return
            del self._sessions[session_id]
            if len(self._sessions) == 0:
                self._last_viewer_count += 1
                self._log.info(
                    "[HLS %s] Last viewer left: session %s (transition #%d)",
                    self._channel_id, session_id, self._last_viewer_count,
                )
                if self._on_viewer_leave is not None:
                    self._on_viewer_leave()

    def count(self) -> int:
        """Return the number of active (non-expired) sessions.

        INV-HLS-VIEWER-COUNT-ACCURATE-001: Always equals len(self._sessions).
        """
        with self._lock:
            return len(self._sessions)

    def reap_expired(self, now_ms: int | None = None) -> None:
        """Remove all sessions whose last activity exceeds the timeout.

        INV-HLS-SESSION-REAP-BOUNDED-001: Examines all sessions, not just recent.
        INV-HLS-SESSION-FIRST-VIEWER-ONCE-001: 1→0 fires exactly once.

        Args:
            now_ms: Current time in ms. If None, uses internal clock.
        """
        if now_ms is None:
            now_ms = self._clock_ms

        with self._lock:
            expired = [
                sid for sid, last_ts in self._sessions.items()
                if now_ms - last_ts > self._session_timeout_ms
            ]
            for sid in expired:
                del self._sessions[sid]

            if expired and len(self._sessions) == 0:
                self._last_viewer_count += 1
                self._log.info(
                    "[HLS %s] All viewers expired (%d reaped, transition #%d)",
                    self._channel_id, len(expired), self._last_viewer_count,
                )
                if self._on_viewer_leave is not None:
                    self._on_viewer_leave()

    # Alias for compatibility with test fixture protocol
    def reap(self) -> None:
        """Convenience alias: reap using internal clock."""
        self.reap_expired(self._clock_ms)
