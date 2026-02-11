"""Horizon Manager — Passive Mode (Phase 1)

Wall-clock-driven policy enforcer for EPG and execution horizons.
Evaluates horizon depth and triggers extensions when below threshold.

See: docs/domains/HorizonManager_v0.1.md

Phase 1: Additive only. No integration with ChannelManager or burn_in.
No pruning, no persistence, no async. Evaluation via evaluate_once()
or a simple daemon thread via start()/stop().
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocols — what HorizonManager needs from upstream layers
# ---------------------------------------------------------------------------

@runtime_checkable
class ScheduleExtender(Protocol):
    """What HorizonManager needs from the schedule/EPG layer.

    Concrete adapters wrap Phase3ScheduleManager (or mocks) behind
    this interface.  HorizonManager never calls ScheduleManager directly.
    """

    def epg_day_exists(self, broadcast_date: date) -> bool:
        """Return True if the broadcast date has already been resolved."""
        ...

    def extend_epg_day(self, broadcast_date: date) -> None:
        """Resolve EPG for the given broadcast date."""
        ...


@runtime_checkable
class ExecutionExtender(Protocol):
    """What HorizonManager needs from the execution/pipeline layer.

    Concrete adapters wrap run_planning_pipeline (or mocks) behind
    this interface.  HorizonManager never calls the pipeline directly.
    """

    def extend_execution_day(self, broadcast_date: date) -> int:
        """Generate execution data for the given broadcast date.

        Returns the end_utc_ms of the last entry in the generated
        TransmissionLog.
        """
        ...


# ---------------------------------------------------------------------------
# HorizonManager
# ---------------------------------------------------------------------------

# Safety valve: never extend more than this many days in a single evaluation.
_MAX_EXTENSION_DAYS = 30


class HorizonManager:
    """Wall-clock-driven horizon depth enforcer.

    Evaluates EPG and execution horizon depths at a fixed interval.
    Triggers schedule resolution and pipeline execution when depths
    fall below configured minimums.

    Phase 1: passive mode.  Can be evaluated explicitly via
    evaluate_once().  start()/stop() run a background daemon thread.
    """

    def __init__(
        self,
        schedule_manager: ScheduleExtender,
        planning_pipeline: ExecutionExtender,
        master_clock,  # needs .now_utc() -> datetime
        min_epg_days: int = 3,
        min_execution_hours: int = 6,
        evaluation_interval_seconds: int = 10,
        programming_day_start_hour: int = 6,
        execution_store=None,  # Optional ExecutionWindowStore
    ):
        self._schedule_manager = schedule_manager
        self._planning_pipeline = planning_pipeline
        self._clock = master_clock
        self._min_epg_days = min_epg_days
        self._min_execution_hours = min_execution_hours
        self._eval_interval_s = evaluation_interval_seconds
        self._day_start_hour = programming_day_start_hour
        self._execution_store = execution_store
        self._logger = logging.getLogger(__name__)

        # Internal state
        self._epg_farthest_date: date | None = None
        self._execution_window_end_utc_ms: int = 0
        self._last_evaluation_utc_ms: int = 0

        # Background thread
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public properties (observability)
    # ------------------------------------------------------------------

    @property
    def epg_window_end_utc_ms(self) -> int:
        """End of the farthest resolved broadcast day, in epoch ms."""
        if self._epg_farthest_date is None:
            return 0
        return self._day_end_utc_ms(self._epg_farthest_date)

    @property
    def execution_window_end_utc_ms(self) -> int:
        """End of the farthest generated TransmissionLog entry, in epoch ms."""
        return self._execution_window_end_utc_ms

    @property
    def last_evaluation_utc_ms(self) -> int:
        """Wall-clock time of the most recent evaluate_once() call, in epoch ms."""
        return self._last_evaluation_utc_ms

    # ------------------------------------------------------------------
    # Depth queries
    # ------------------------------------------------------------------

    def get_epg_depth_hours(self) -> float:
        """Current EPG horizon depth in hours (from now to farthest day end)."""
        now_ms = self._now_utc_ms()
        end_ms = self.epg_window_end_utc_ms
        if end_ms <= now_ms:
            return 0.0
        return (end_ms - now_ms) / 3_600_000.0

    def get_execution_depth_hours(self) -> float:
        """Current execution horizon depth in hours (from now to farthest entry end)."""
        now_ms = self._now_utc_ms()
        end_ms = self._execution_window_end_utc_ms
        if end_ms <= now_ms:
            return 0.0
        return (end_ms - now_ms) / 3_600_000.0

    # ------------------------------------------------------------------
    # Core evaluation
    # ------------------------------------------------------------------

    def evaluate_once(self) -> None:
        """Evaluate horizon depths and extend if below policy thresholds.

        Safe to call from any thread.  Does not block on I/O (all
        extension calls are synchronous to the planning pipeline).
        """
        now = self._clock.now_utc()
        now_ms = int(now.timestamp() * 1000)
        self._last_evaluation_utc_ms = now_ms

        current_bd = self._broadcast_date_for(now)

        # --- EPG depth ---
        epg_end_ms = self.epg_window_end_utc_ms
        epg_depth_h = max(0.0, (epg_end_ms - now_ms) / 3_600_000.0)
        min_epg_h = self._min_epg_days * 24.0

        extended = False

        if epg_depth_h < min_epg_h:
            self._extend_epg(current_bd, now_ms)
            extended = True

        # --- Execution depth ---
        exec_depth_h = max(0.0, (self._execution_window_end_utc_ms - now_ms) / 3_600_000.0)

        if exec_depth_h < self._min_execution_hours:
            self._extend_execution(current_bd, now_ms)
            extended = True

        # --- Log status (only when an extension occurred) ---
        if extended:
            self._logger.info(
                "HorizonManager: epg=%.1fh (%.1fd) exec=%.1fh "
                "min_epg=%dd min_exec=%dh",
                self.get_epg_depth_hours(),
                self.get_epg_depth_hours() / 24.0,
                self.get_execution_depth_hours(),
                self._min_epg_days,
                self._min_execution_hours,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background evaluation thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="HorizonManager",
            daemon=True,
        )
        self._thread.start()
        self._logger.info(
            "HorizonManager: started (interval=%ds)", self._eval_interval_s,
        )

    def stop(self) -> None:
        """Stop the background evaluation thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._eval_interval_s + 5)
            self._thread = None
        self._logger.info("HorizonManager: stopped")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """Background loop: evaluate → sleep → repeat."""
        while not self._stop_event.is_set():
            try:
                self.evaluate_once()
            except Exception:
                self._logger.exception("HorizonManager: evaluation failed")
            self._stop_event.wait(timeout=self._eval_interval_s)

    def _broadcast_date_for(self, dt: datetime) -> date:
        """Determine which broadcast day a wall-clock time falls in."""
        if dt.hour < self._day_start_hour:
            return (dt - timedelta(days=1)).date()
        return dt.date()

    def _day_end_utc_ms(self, broadcast_date: date) -> int:
        """End of a broadcast day (next calendar day at start hour) in epoch ms."""
        end_dt = datetime(
            broadcast_date.year,
            broadcast_date.month,
            broadcast_date.day,
            self._day_start_hour, 0, 0,
            tzinfo=timezone.utc,
        ) + timedelta(days=1)
        return int(end_dt.timestamp() * 1000)

    def _now_utc_ms(self) -> int:
        return int(self._clock.now_utc().timestamp() * 1000)

    def _extend_epg(self, current_bd: date, now_ms: int) -> None:
        """Extend EPG horizon until depth meets min_epg_days."""
        target_end_ms = now_ms + self._min_epg_days * 24 * 3_600_000

        if self._epg_farthest_date is not None:
            next_date = self._epg_farthest_date + timedelta(days=1)
        else:
            next_date = current_bd

        days_extended = 0
        while (self.epg_window_end_utc_ms < target_end_ms
               and days_extended < _MAX_EXTENSION_DAYS):
            if not self._schedule_manager.epg_day_exists(next_date):
                self._logger.info(
                    "HorizonManager: extending EPG → %s",
                    next_date.isoformat(),
                )
                self._schedule_manager.extend_epg_day(next_date)
            self._epg_farthest_date = next_date
            next_date = next_date + timedelta(days=1)
            days_extended += 1

    def _extend_execution(self, current_bd: date, now_ms: int) -> None:
        """Extend execution horizon until depth meets min_execution_hours."""
        target_end_ms = now_ms + self._min_execution_hours * 3_600_000

        if self._execution_window_end_utc_ms > 0:
            # Find the next broadcast date after current coverage
            end_dt = datetime.fromtimestamp(
                self._execution_window_end_utc_ms / 1000.0,
                tz=timezone.utc,
            )
            next_date = self._broadcast_date_for(end_dt)
            # If current coverage already includes this day's end, move to next
            if self._day_end_utc_ms(next_date) <= self._execution_window_end_utc_ms:
                next_date = next_date + timedelta(days=1)
        else:
            next_date = current_bd

        days_extended = 0
        while (self._execution_window_end_utc_ms < target_end_ms
               and days_extended < _MAX_EXTENSION_DAYS):
            self._logger.info(
                "HorizonManager: extending execution → %s",
                next_date.isoformat(),
            )
            result = self._planning_pipeline.extend_execution_day(next_date)

            # Duck-type: result is int (legacy) or has .end_utc_ms + .entries
            if isinstance(result, int):
                end_ms = result
            else:
                end_ms = result.end_utc_ms
                if self._execution_store is not None and hasattr(result, "entries"):
                    self._execution_store.add_entries(result.entries)

            if end_ms > self._execution_window_end_utc_ms:
                self._execution_window_end_utc_ms = end_ms
            next_date = next_date + timedelta(days=1)
            days_extended += 1
