"""Master clock abstractions used for broadcasting logic.

The master clock supplies *station time*: a monotonic timeline that all runtime
components share. Station time may advance faster or slower than wall clock
time, but it never jumps backwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Protocol, runtime_checkable

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

import time

MonotonicFn = Callable[[], float]


@runtime_checkable
class MasterClock(Protocol):
    """Protocol implemented by master clock providers."""

    def now(self) -> float:
        """Return the current station time in seconds."""


@dataclass
class RealTimeMasterClock:
    """Master clock backed by a monotonic timer.

    Parameters
    ----------
    rate:
        Scale factor applied to elapsed monotonic time. A value of ``2.0``
        doubles perceived station time. Must be positive.
    start:
        Station time (seconds) to begin counting from.
    monotonic_fn:
        Injectable monotonic function, defaults to :func:`time.perf_counter`.
    """

    rate: float = 1.0
    start: float = 0.0
    monotonic_fn: MonotonicFn = field(default=time.perf_counter)

    def __post_init__(self) -> None:
        if self.rate <= 0.0:
            raise ValueError("rate must be greater than zero")
        self._origin_station: float = self.start
        self._origin_monotonic: float = self.monotonic_fn()

    def now(self) -> float:
        """Return the current station time in seconds."""
        elapsed = self.monotonic_fn() - self._origin_monotonic
        if elapsed < 0.0:
            # Guard against clock implementations that could return a smaller
            # value (should never happen with perf_counter, but keep safety).
            elapsed = 0.0
        return self._origin_station + elapsed * self.rate


class SteppedMasterClock:
    """Deterministic master clock used for tests.

    Station time advances only when :meth:`advance` is called.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._current = start
        self._lock = Lock()

    def now(self) -> float:
        with self._lock:
            return self._current

    def advance(self, seconds: float) -> float:
        """Advance the clock by ``seconds`` (must be non-negative)."""
        if seconds < 0.0:
            raise ValueError("seconds must be non-negative")
        with self._lock:
            self._current += seconds
            return self._current


class MasterClock:
    """Contract-compliant clock providing timezone-aware timestamps."""

    def now_utc(self) -> datetime:
        """Return current UTC time as an aware datetime."""
        return datetime.now(timezone.utc)

    def now_local(self, tz: str | tzinfo | None = None) -> datetime:
        """Return current time in the requested timezone (defaults to system local)."""
        target = self._resolve_timezone(tz)
        return self.now_utc().astimezone(target)

    def seconds_since(self, dt: datetime) -> float:
        """Return non-negative seconds elapsed since the given timestamp."""
        self._ensure_aware(dt)
        delta = self.now_utc() - dt.astimezone(timezone.utc)
        return max(0.0, delta.total_seconds())

    def to_utc(self, dt_local: datetime) -> datetime:
        """Convert an aware datetime to UTC."""
        self._ensure_aware(dt_local)
        return dt_local.astimezone(timezone.utc)

    def to_local(self, dt_utc: datetime, tz: str | tzinfo | None = None) -> datetime:
        """Convert an aware UTC datetime to the requested timezone."""
        self._ensure_aware(dt_utc)
        target = self._resolve_timezone(tz)
        return dt_utc.astimezone(target)

    @staticmethod
    def _ensure_aware(dt: datetime) -> None:
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError("Datetime must be timezone-aware")

    @staticmethod
    def _resolve_timezone(tz: str | tzinfo | None) -> tzinfo:
        if tz is None:
            return datetime.now().astimezone().tzinfo or timezone.utc
        if isinstance(tz, tzinfo):
            return tz
        try:
            return ZoneInfo(tz)
        except Exception:
            return timezone.utc

