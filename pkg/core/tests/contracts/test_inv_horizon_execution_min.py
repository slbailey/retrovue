"""
Contract tests: INV-HORIZON-EXECUTION-MIN-001.

After every successful evaluate_once() cycle, execution horizon depth
(execution_window_end - now) >= execution_horizon_min_duration_ms.
When the planning pipeline fails, the deficit MUST be reported as a
planning fault.

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-EXECUTION-MIN-001.md
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import pytest

from retrovue.runtime.horizon_manager import (
    ExecutionExtender,
    HorizonManager,
    ScheduleExtender,
)

# 2025-02-08T06:00:00Z  (programming day start)
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000       # 30 minutes
MIN_EXEC_HORIZON_MS = 21_600_000  # 6 hours
PROG_DAY_START_HOUR = 6
DAY_MS = 86_400_000


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeClock:
    """Deterministic clock returning datetime objects."""

    def __init__(self, start_ms: int = EPOCH_MS) -> None:
        self._ms = start_ms
        self._lock = threading.Lock()

    def now_utc(self) -> datetime:
        with self._lock:
            return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def now_utc_ms(self) -> int:
        with self._lock:
            return self._ms

    def advance_ms(self, delta: int) -> None:
        with self._lock:
            self._ms += delta


class StubScheduleExtender:
    """No-op schedule extender (EPG not under test)."""

    def __init__(self) -> None:
        self._days: set[date] = set()

    def epg_day_exists(self, broadcast_date: date) -> bool:
        return broadcast_date in self._days

    def extend_epg_day(self, broadcast_date: date) -> None:
        self._days.add(broadcast_date)


class PipelineError(Exception):
    """Planning pipeline failure with error_code."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


class StubExecutionExtender:
    """Generates execution blocks covering a broadcast day.

    Each call to extend_execution_day returns end_utc_ms for a full day
    of BLOCK_DUR_MS blocks starting at programming_day_start_hour.

    Set fail_on_next=True to raise PipelineError on the next call.
    """

    def __init__(
        self,
        block_dur_ms: int = BLOCK_DUR_MS,
        day_start_hour: int = PROG_DAY_START_HOUR,
    ) -> None:
        self._block_dur_ms = block_dur_ms
        self._day_start_hour = day_start_hour
        self._fail_on_next = False
        self._fail_error_code = "PIPELINE_EXHAUSTED"

    def set_fail_on_next(self, error_code: str = "PIPELINE_EXHAUSTED") -> None:
        self._fail_on_next = True
        self._fail_error_code = error_code

    def extend_execution_day(self, broadcast_date: date) -> int:
        if self._fail_on_next:
            self._fail_on_next = False
            raise PipelineError(self._fail_error_code)

        # Day starts at broadcast_date + day_start_hour,
        # ends at broadcast_date + 1 day + day_start_hour.
        day_start_dt = datetime(
            broadcast_date.year,
            broadcast_date.month,
            broadcast_date.day,
            self._day_start_hour, 0, 0,
            tzinfo=timezone.utc,
        )
        day_end_dt = day_start_dt + timedelta(days=1)
        return int(day_end_dt.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_horizon_manager(
    clock: FakeClock,
    pipeline: StubExecutionExtender | None = None,
    schedule: StubScheduleExtender | None = None,
    min_execution_hours: int = 6,
    min_epg_days: int = 3,
    programming_day_start_hour: int = PROG_DAY_START_HOUR,
) -> HorizonManager:
    if pipeline is None:
        pipeline = StubExecutionExtender()
    if schedule is None:
        schedule = StubScheduleExtender()
    return HorizonManager(
        schedule_manager=schedule,
        planning_pipeline=pipeline,
        master_clock=clock,
        min_epg_days=min_epg_days,
        min_execution_hours=min_execution_hours,
        programming_day_start_hour=programming_day_start_hour,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvHorizonExecutionMin001:
    """INV-HORIZON-EXECUTION-MIN-001 enforcement tests."""

    def test_them_001_depth_meets_minimum_after_init(self) -> None:
        """THEM-001: Empty store -> evaluate_once() -> depth >= MIN,
        execution_compliant=True, attempt logged as success.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline)

        # Precondition: no execution coverage
        assert hm.execution_window_end_utc_ms == 0

        hm.evaluate_once()

        # Depth must meet minimum
        depth_ms = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert depth_ms >= MIN_EXEC_HORIZON_MS

        # Health report shows compliant
        report = hm.get_health_report()
        assert report.execution_compliant is True

        # At least one successful attempt was logged
        assert hm.extension_success_count >= 1
        log = hm.extension_attempt_log
        assert len(log) >= 1
        last = log[-1]
        assert last.reason_code == "REASON_TIME_THRESHOLD"
        assert last.success is True
        assert last.triggered_by == "SCHED_MGR_POLICY"

    def test_them_002_depth_maintained_across_24h_walk(self) -> None:
        """THEM-002: 48 steps x BLOCK_DUR_MS, depth >= MIN at every step,
        forbidden_trigger_count == 0.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline)

        # Initialize horizon
        hm.evaluate_once()

        for step in range(48):
            clock.advance_ms(BLOCK_DUR_MS)
            hm.evaluate_once()

            depth_ms = hm.execution_window_end_utc_ms - clock.now_utc_ms()
            assert depth_ms >= MIN_EXEC_HORIZON_MS, (
                f"Step {step}: depth {depth_ms} < {MIN_EXEC_HORIZON_MS}"
            )

            report = hm.get_health_report()
            assert report.execution_compliant is True, (
                f"Step {step}: execution_compliant=False"
            )

        # No forbidden triggers
        assert hm.extension_forbidden_trigger_count == 0

        # All attempts used SCHED_MGR_POLICY
        for attempt in hm.extension_attempt_log:
            assert attempt.triggered_by == "SCHED_MGR_POLICY"

    def test_them_003_pipeline_failure_produces_deficit(self) -> None:
        """THEM-003: Pre-populate to MIN depth, configure failure,
        advance clock until depth drops below threshold, then
        evaluate_once -> execution_compliant=False, attempt logged
        with error_code.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline)

        # Initialize — produces 24h of coverage (one full broadcast day)
        hm.evaluate_once()
        assert hm.get_health_report().execution_compliant is True
        window_end = hm.execution_window_end_utc_ms
        success_count_before = hm.extension_success_count

        # Advance clock to consume coverage down to just above MIN.
        # Coverage = window_end - now.  We want to erode to < MIN
        # after 2 more blocks, so advance to (window_end - MIN) first
        # without calling evaluate_once (which would trigger extension).
        advance_to_threshold = (window_end - EPOCH_MS) - MIN_EXEC_HORIZON_MS
        clock.advance_ms(advance_to_threshold)

        # Precondition: depth is exactly MIN_EXEC_HORIZON_MS
        depth_at_threshold = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert depth_at_threshold == MIN_EXEC_HORIZON_MS

        # Configure pipeline to fail on next call
        pipeline.set_fail_on_next("PIPELINE_EXHAUSTED")

        # Advance 2 more blocks — now depth is below MIN
        clock.advance_ms(2 * BLOCK_DUR_MS)
        hm.evaluate_once()

        # Depth below minimum -> not compliant
        report = hm.get_health_report()
        assert report.execution_compliant is False

        depth_ms = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert depth_ms < MIN_EXEC_HORIZON_MS

        # Failed attempt logged
        log = hm.extension_attempt_log
        last = log[-1]
        assert last.success is False
        assert last.error_code == "PIPELINE_EXHAUSTED"

        # Success count unchanged from before the failed attempt
        assert hm.extension_success_count == success_count_before

    def test_them_004_depth_survives_programming_day_boundary(self) -> None:
        """THEM-004: Start at 05:00, 4 steps across 06:00 boundary,
        depth >= MIN at every step.
        """
        # 05:00 UTC = EPOCH_MS - 1h
        start_ms = EPOCH_MS - 3_600_000
        clock = FakeClock(start_ms=start_ms)
        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline)

        # Initialize
        hm.evaluate_once()

        for step in range(4):
            clock.advance_ms(BLOCK_DUR_MS)
            hm.evaluate_once()

            depth_ms = hm.execution_window_end_utc_ms - clock.now_utc_ms()
            assert depth_ms >= MIN_EXEC_HORIZON_MS, (
                f"Step {step}: depth {depth_ms} < {MIN_EXEC_HORIZON_MS}"
            )

            report = hm.get_health_report()
            assert report.execution_compliant is True, (
                f"Step {step}: execution_compliant=False"
            )

        # All attempts are policy-triggered with valid reason codes
        for attempt in hm.extension_attempt_log:
            assert attempt.triggered_by == "SCHED_MGR_POLICY"
            assert attempt.reason_code in {"REASON_TIME_THRESHOLD", "DAILY_ROLL"}
