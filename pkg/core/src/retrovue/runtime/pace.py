"""Pacing controller for runtime components.

The `PaceController` owns the main playout cadence. It drives registered
participants by emitting ticks at the requested frequency using the station
time supplied by a :class:`MasterClock`.

Key guarantees:

- Monotonic station time (supplied by the master clock) is passed to
  participants as `t_now`.
- The delta `dt` is never negative and is clamped to an upper bound to avoid
  runaway catch-up cycles. By default the clamp is three frames.
- Real-time mode (`sleep_fn` provided) sleeps between ticks to honour cadence.
- Stepped/test mode (`sleep_fn=None`) never sleeps; callers should advance the
  clock manually and invoke :meth:`run_once`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Lock
from typing import Callable, Protocol, runtime_checkable

import time

from .clock import MasterClock

SleepFn = Callable[[float], None]


@runtime_checkable
class PaceParticipant(Protocol):
    """Participant contract for paced updates."""

    def on_paced_tick(self, t_now: float, dt: float) -> None:
        """Handle a pacing tick."""


@dataclass
class PaceController:
    """Coordinate paced ticks for registered participants.

    Parameters
    ----------
    clock:
        Master clock that provides monotonically increasing station time.
    target_hz:
        Desired cadence in hertz (frames per second). Must be positive.
    sleep_fn:
        Optional sleep function. If provided, the controller will sleep between
        ticks in :meth:`run_forever` to approximate real-time pacing. When
        ``None`` (default for stepped tests) the controller never sleeps.
    max_frame_multiplier:
        Number of frames used to cap `dt`. Defaults to three so the controller
        never tries to "catch up" more than three frames in a single tick.
    """

    clock: MasterClock
    target_hz: float = 30.0
    sleep_fn: SleepFn | None = time.sleep
    max_frame_multiplier: float = 3.0
    _participants: set[PaceParticipant] = field(default_factory=set, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)
    _stop_event: Event = field(default_factory=Event, init=False)
    _last_time: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if self.target_hz <= 0.0:
            raise ValueError("target_hz must be greater than zero")
        if self.max_frame_multiplier <= 0.0:
            raise ValueError("max_frame_multiplier must be greater than zero")
        self._frame_interval = 1.0 / self.target_hz
        self._max_dt = self._frame_interval * self.max_frame_multiplier

    # Participant management -------------------------------------------------
    def add_participant(self, participant: PaceParticipant) -> None:
        with self._lock:
            self._participants.add(participant)

    def remove_participant(self, participant: PaceParticipant) -> None:
        with self._lock:
            self._participants.discard(participant)

    # Run loop ---------------------------------------------------------------
    def run_forever(self) -> None:
        """Drive the pacing loop until :meth:`stop` is called."""

        self._stop_event.clear()
        self._last_time = None
        next_wall_tick = time.perf_counter()

        while not self._stop_event.is_set():
            tick_emitted = self.run_once()
            if self.sleep_fn is None:
                # Stepped/testing mode should not sleep.
                continue

            # Maintain cadence against wall clock with drift correction.
            next_wall_tick += self._frame_interval
            remaining = next_wall_tick - time.perf_counter()
            if remaining > 0:
                self.sleep_fn(remaining)
            else:
                # We are late; reset baseline to avoid negative spirals.
                next_wall_tick = time.perf_counter()

            # If we did not emit a tick (e.g., no participants or no time
            # advance) keep baseline close to current wall time.
            if not tick_emitted:
                next_wall_tick = time.perf_counter()

    def stop(self) -> None:
        """Signal the controller to stop."""

        self._stop_event.set()

    def run_once(self) -> bool:
        """Execute a single pacing iteration.

        Returns ``True`` when participants received a tick, ``False`` otherwise.
        """

        now = self.clock.now()
        last_time = self._last_time
        if last_time is None:
            dt = self._frame_interval
        else:
            dt = max(0.0, now - last_time)
            if dt == 0.0:
                return False

        dt = min(dt, self._max_dt)
        self._last_time = now

        participants_snapshot: list[PaceParticipant]
        with self._lock:
            participants_snapshot = list(self._participants)
        for participant in participants_snapshot:
            participant.on_paced_tick(now, dt)
        return bool(participants_snapshot)

