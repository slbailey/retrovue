"""Authoritative clock boundary for runtime and application code."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from threading import Lock
from typing import Callable, Protocol, runtime_checkable
from zoneinfo import ZoneInfo

import time

UtcNowFn = Callable[[], datetime]
MonotonicFn = Callable[[], float]


def _default_utcnow() -> datetime:
    """Default provider for ``SystemClock.utcnow_fn``.

    Module-level (not a lambda closure) so ``SystemClock`` instances
    remain picklable and can be passed across process boundaries — e.g.
    into ``ProcessPoolExecutor`` payloads — without pickle failing on
    local-lambda references.  Behaviour is identical to the prior
    lambda default: returns the current wall-clock time as a
    timezone-aware UTC ``datetime``.
    """
    return datetime.now(timezone.utc)


@runtime_checkable
class AuthoritativeClock(Protocol):
    """Single authoritative time source for system time."""

    def now_utc(self) -> datetime:
        """Return the current authoritative UTC timestamp."""

    def monotonic(self) -> float:
        """Return a monotonic elapsed-time reading in seconds."""

    def now_utc_ms(self) -> int:
        """Return the current authoritative UTC timestamp in milliseconds."""
        return int(self.now_utc().timestamp() * 1000)

    def monotonic_ms(self) -> int:
        """Return the current monotonic reading in milliseconds."""
        return int(self.monotonic() * 1000)

    def monotonic_ns(self) -> int:
        """Return the current monotonic reading in nanoseconds."""
        return int(self.monotonic() * 1_000_000_000)


@dataclass
class SystemClock:
    """Production clock backed by the system UTC wall clock and monotonic timer."""

    utcnow_fn: UtcNowFn = field(default=_default_utcnow)
    monotonic_fn: MonotonicFn = field(default=time.monotonic)

    def now_utc(self) -> datetime:
        current = self.utcnow_fn()
        if current.tzinfo is None or current.tzinfo.utcoffset(current) is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def monotonic(self) -> float:
        return self.monotonic_fn()

    def now_utc_ms(self) -> int:
        return int(self.now_utc().timestamp() * 1000)

    def monotonic_ms(self) -> int:
        return int(self.monotonic() * 1000)

    def monotonic_ns(self) -> int:
        # Delegates to time.monotonic_ns() for full nanosecond precision
        # (float*1e9 rounding would drop low-order bits on long uptimes).
        return time.monotonic_ns()

    def now_local(self, tz: str | tzinfo | None = None) -> datetime:
        target = self._resolve_timezone(tz)
        return self.now_utc().astimezone(target)

    def seconds_since(self, dt: datetime) -> float:
        self._ensure_aware(dt)
        delta = self.now_utc() - dt.astimezone(timezone.utc)
        return max(0.0, delta.total_seconds())

    def to_utc(self, dt_local: datetime) -> datetime:
        self._ensure_aware(dt_local)
        return dt_local.astimezone(timezone.utc)

    def to_local(self, dt_utc: datetime, tz: str | tzinfo | None = None) -> datetime:
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
            return datetime.now(timezone.utc).astimezone().tzinfo or timezone.utc
        if isinstance(tz, tzinfo):
            return tz
        try:
            return ZoneInfo(tz)
        except Exception:
            return timezone.utc


class ControllableClock:
    """Deterministic UTC clock for tests with manual time control."""

    def __init__(self, epoch: datetime | None = None) -> None:
        if epoch is None:
            epoch = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        if epoch.tzinfo is None or epoch.tzinfo.utcoffset(epoch) is None:
            epoch = epoch.replace(tzinfo=timezone.utc)
        self._epoch = epoch.astimezone(timezone.utc)
        self._seconds = 0.0
        self._lock = Lock()

    def now_utc(self) -> datetime:
        with self._lock:
            return self._epoch + timedelta(seconds=self._seconds)

    def monotonic(self) -> float:
        with self._lock:
            return self._seconds

    def now_utc_ms(self) -> int:
        return int(self.now_utc().timestamp() * 1000)

    def monotonic_ms(self) -> int:
        return int(self.monotonic() * 1000)

    def monotonic_ns(self) -> int:
        return int(self.monotonic() * 1_000_000_000)

    def advance(self, seconds: float) -> datetime:
        if seconds < 0.0:
            raise ValueError("seconds must be non-negative")
        with self._lock:
            self._seconds += seconds
            return self._epoch + timedelta(seconds=self._seconds)

    def advance_to(self, seconds_since_epoch: float) -> datetime:
        with self._lock:
            if seconds_since_epoch < self._seconds:
                raise ValueError("advance_to must not go backwards")
            self._seconds = seconds_since_epoch
            return self._epoch + timedelta(seconds=self._seconds)


class SteppedClock:
    """Deterministic stepped clock for tests and pacing simulations."""

    def __init__(
        self,
        start: float = 0.0,
        *,
        epoch: datetime | None = None,
    ) -> None:
        if epoch is None:
            epoch = datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        if epoch.tzinfo is None or epoch.tzinfo.utcoffset(epoch) is None:
            epoch = epoch.replace(tzinfo=timezone.utc)
        self._epoch = epoch.astimezone(timezone.utc)
        self._current = start
        self._lock = Lock()

    def now_utc(self) -> datetime:
        with self._lock:
            return self._epoch + timedelta(seconds=self._current)

    def monotonic(self) -> float:
        with self._lock:
            return self._current

    def now_utc_ms(self) -> int:
        return int(self.now_utc().timestamp() * 1000)

    def monotonic_ms(self) -> int:
        return int(self.monotonic() * 1000)

    def monotonic_ns(self) -> int:
        return int(self.monotonic() * 1_000_000_000)

    def advance(self, seconds: float) -> float:
        if seconds < 0.0:
            raise ValueError("seconds must be non-negative")
        with self._lock:
            self._current += seconds
            return self._current
