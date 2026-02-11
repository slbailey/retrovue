"""Tests for HorizonManager passive mode (Phase 1).

Verifies:
- evaluate_once() triggers EPG and execution extensions when depth is below threshold
- evaluate_once() is a no-op when depth is sufficient
- Depth queries report correct values
- Multiple days are extended to meet threshold
- start()/stop() lifecycle works without errors
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.horizon_manager import HorizonManager


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

class MockScheduleExtender:
    """Mock schedule manager that tracks calls and remembers resolved dates."""

    def __init__(self):
        self.resolved_dates: set[date] = set()
        self.extend_calls: list[date] = []

    def epg_day_exists(self, broadcast_date: date) -> bool:
        return broadcast_date in self.resolved_dates

    def extend_epg_day(self, broadcast_date: date) -> None:
        self.extend_calls.append(broadcast_date)
        self.resolved_dates.add(broadcast_date)


class MockExecutionExtender:
    """Mock planning pipeline that tracks calls and returns day-end timestamps."""

    def __init__(self, day_start_hour: int = 6):
        self.extend_calls: list[date] = []
        self._day_start_hour = day_start_hour

    def extend_execution_day(self, broadcast_date: date) -> int:
        self.extend_calls.append(broadcast_date)
        # Return end of broadcast day (next calendar day at start hour)
        end_dt = datetime(
            broadcast_date.year,
            broadcast_date.month,
            broadcast_date.day,
            self._day_start_hour, 0, 0,
            tzinfo=timezone.utc,
        ) + timedelta(days=1)
        return int(end_dt.timestamp() * 1000)


def _make_clock(year=2026, month=2, day=11, hour=14, minute=0) -> ControllableMasterClock:
    """Create a controllable clock at a specific UTC time."""
    epoch = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
    return ControllableMasterClock(epoch=epoch)


def _make_manager(
    clock=None,
    schedule=None,
    pipeline=None,
    min_epg_days=3,
    min_execution_hours=6,
) -> tuple[HorizonManager, MockScheduleExtender, MockExecutionExtender]:
    """Create a HorizonManager with mocks, returning all three."""
    if clock is None:
        clock = _make_clock()
    if schedule is None:
        schedule = MockScheduleExtender()
    if pipeline is None:
        pipeline = MockExecutionExtender()

    hm = HorizonManager(
        schedule_manager=schedule,
        planning_pipeline=pipeline,
        master_clock=clock,
        min_epg_days=min_epg_days,
        min_execution_hours=min_execution_hours,
        evaluation_interval_seconds=10,
        programming_day_start_hour=6,
    )
    return hm, schedule, pipeline


# ---------------------------------------------------------------------------
# EPG extension tests
# ---------------------------------------------------------------------------

class TestEpgExtension:
    """evaluate_once() extends EPG when depth is below min_epg_days."""

    def test_triggers_epg_extension_from_zero(self):
        """Fresh HorizonManager has zero EPG depth; evaluate_once extends."""
        hm, schedule, _ = _make_manager(min_epg_days=1)

        assert hm.get_epg_depth_hours() == 0.0
        hm.evaluate_once()

        assert len(schedule.extend_calls) > 0
        assert hm.get_epg_depth_hours() > 0.0

    def test_extends_enough_days_for_threshold(self):
        """With min_epg_days=3, enough days are resolved to cover 3 days."""
        # Clock at 2026-02-11 14:00 UTC → broadcast date 2026-02-11
        hm, schedule, _ = _make_manager(min_epg_days=3)

        hm.evaluate_once()

        # Need coverage until 2026-02-14 14:00.
        # Day 2026-02-11 ends at 2026-02-12 06:00 (16h, not enough)
        # Day 2026-02-12 ends at 2026-02-13 06:00 (40h, not enough)
        # Day 2026-02-13 ends at 2026-02-14 06:00 (64h, not enough)
        # Day 2026-02-14 ends at 2026-02-15 06:00 (88h, >= 72h)
        assert date(2026, 2, 11) in schedule.resolved_dates
        assert date(2026, 2, 14) in schedule.resolved_dates
        assert hm.get_epg_depth_hours() >= 3 * 24

    def test_skips_already_resolved_days(self):
        """Days already in the store are not re-resolved."""
        hm, schedule, _ = _make_manager(min_epg_days=1)

        # Pre-seed one day as resolved
        schedule.resolved_dates.add(date(2026, 2, 11))

        hm.evaluate_once()

        # 2026-02-11 should NOT appear in extend_calls
        assert date(2026, 2, 11) not in schedule.extend_calls

    def test_no_extension_when_depth_sufficient(self):
        """If EPG depth already meets threshold, no extension occurs."""
        hm, schedule, _ = _make_manager(min_epg_days=1)

        # Pre-set farthest date far enough ahead
        hm._epg_farthest_date = date(2026, 2, 20)

        hm.evaluate_once()

        assert len(schedule.extend_calls) == 0


# ---------------------------------------------------------------------------
# Execution extension tests
# ---------------------------------------------------------------------------

class TestExecutionExtension:
    """evaluate_once() extends execution when depth is below min_execution_hours."""

    def test_triggers_execution_extension_from_zero(self):
        """Fresh HorizonManager has zero execution depth; evaluate_once extends."""
        hm, _, pipeline = _make_manager(min_execution_hours=6)

        assert hm.get_execution_depth_hours() == 0.0
        hm.evaluate_once()

        assert len(pipeline.extend_calls) > 0
        assert hm.get_execution_depth_hours() > 0.0

    def test_single_day_sufficient_for_small_threshold(self):
        """min_execution_hours=6: one day (24h) is more than enough."""
        # Clock at 14:00, day ends at next day 06:00 = 16 hours of coverage
        hm, _, pipeline = _make_manager(min_execution_hours=6)

        hm.evaluate_once()

        # One day generation should suffice (16h > 6h)
        assert len(pipeline.extend_calls) == 1
        assert pipeline.extend_calls[0] == date(2026, 2, 11)

    def test_extends_multiple_days_for_large_threshold(self):
        """min_execution_hours=30: requires 2 days to cover."""
        # Clock at 14:00. Day 2026-02-11 gives until 2026-02-12 06:00 = 16h.
        # Need 30h → must also generate 2026-02-12 (extends to 2026-02-13 06:00 = 40h).
        hm, _, pipeline = _make_manager(min_execution_hours=30)

        hm.evaluate_once()

        assert len(pipeline.extend_calls) == 2
        assert pipeline.extend_calls[0] == date(2026, 2, 11)
        assert pipeline.extend_calls[1] == date(2026, 2, 12)

    def test_no_extension_when_depth_sufficient(self):
        """If execution depth already meets threshold, no extension occurs."""
        hm, _, pipeline = _make_manager(min_execution_hours=6)

        # Pre-set execution window far into the future
        future = datetime(2026, 2, 20, 6, 0, 0, tzinfo=timezone.utc)
        hm._execution_window_end_utc_ms = int(future.timestamp() * 1000)

        hm.evaluate_once()

        assert len(pipeline.extend_calls) == 0


# ---------------------------------------------------------------------------
# Depth query tests
# ---------------------------------------------------------------------------

class TestDepthQueries:
    """get_epg_depth_hours() and get_execution_depth_hours() report correctly."""

    def test_epg_depth_zero_when_no_days_resolved(self):
        hm, _, _ = _make_manager()
        assert hm.get_epg_depth_hours() == 0.0

    def test_epg_depth_correct_after_extension(self):
        # Clock at 2026-02-11 14:00 UTC
        hm, _, _ = _make_manager(min_epg_days=1)
        hm.evaluate_once()

        depth_h = hm.get_epg_depth_hours()
        # Must be >= 24 hours (min_epg_days=1)
        assert depth_h >= 24.0

    def test_execution_depth_zero_when_no_logs_generated(self):
        hm, _, _ = _make_manager()
        assert hm.get_execution_depth_hours() == 0.0

    def test_execution_depth_correct_after_extension(self):
        hm, _, _ = _make_manager(min_execution_hours=6)
        hm.evaluate_once()

        depth_h = hm.get_execution_depth_hours()
        assert depth_h >= 6.0

    def test_epg_window_end_utc_ms_property(self):
        hm, _, _ = _make_manager()
        assert hm.epg_window_end_utc_ms == 0

        hm._epg_farthest_date = date(2026, 2, 11)
        # End of broadcast day 2026-02-11 = 2026-02-12 06:00 UTC
        expected = datetime(2026, 2, 12, 6, 0, 0, tzinfo=timezone.utc)
        assert hm.epg_window_end_utc_ms == int(expected.timestamp() * 1000)


# ---------------------------------------------------------------------------
# No-op when sufficient
# ---------------------------------------------------------------------------

class TestNoOpWhenSufficient:
    """evaluate_once() does nothing when both horizons have sufficient depth."""

    def test_both_sufficient_no_calls(self):
        hm, schedule, pipeline = _make_manager(
            min_epg_days=1,
            min_execution_hours=6,
        )

        # Pre-set both horizons well beyond threshold
        hm._epg_farthest_date = date(2026, 3, 1)
        future = datetime(2026, 3, 1, 6, 0, 0, tzinfo=timezone.utc)
        hm._execution_window_end_utc_ms = int(future.timestamp() * 1000)

        hm.evaluate_once()

        assert len(schedule.extend_calls) == 0
        assert len(pipeline.extend_calls) == 0

    def test_second_evaluate_no_op_after_first_extends(self):
        """After first evaluate extends, second evaluate is a no-op (depth met)."""
        hm, schedule, pipeline = _make_manager(
            min_epg_days=1,
            min_execution_hours=6,
        )

        hm.evaluate_once()  # extends
        epg_calls_1 = len(schedule.extend_calls)
        exec_calls_1 = len(pipeline.extend_calls)

        assert epg_calls_1 > 0
        assert exec_calls_1 > 0

        hm.evaluate_once()  # should be no-op

        assert len(schedule.extend_calls) == epg_calls_1
        assert len(pipeline.extend_calls) == exec_calls_1


# ---------------------------------------------------------------------------
# Internal state tracking
# ---------------------------------------------------------------------------

class TestStateTracking:
    """Internal state updates correctly across evaluations."""

    def test_last_evaluation_utc_ms_updated(self):
        hm, _, _ = _make_manager()
        assert hm.last_evaluation_utc_ms == 0

        hm.evaluate_once()

        assert hm.last_evaluation_utc_ms > 0

    def test_broadcast_date_before_start_hour(self):
        """Time at 03:00 UTC belongs to the previous calendar day's broadcast day."""
        clock = _make_clock(hour=3)  # 2026-02-11 03:00 UTC
        hm, schedule, _ = _make_manager(clock=clock, min_epg_days=1)

        hm.evaluate_once()

        # Current broadcast date should be 2026-02-10 (before 06:00)
        assert date(2026, 2, 10) in schedule.resolved_dates


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    """start() and stop() work without errors."""

    def test_start_stop(self):
        hm, _, _ = _make_manager()
        hm.start()
        hm.stop()
        assert hm._thread is None

    def test_stop_without_start(self):
        """stop() is safe to call without start()."""
        hm, _, _ = _make_manager()
        hm.stop()  # should not raise

    def test_double_start(self):
        """Calling start() twice does not create a second thread."""
        hm, _, _ = _make_manager()
        hm.start()
        thread1 = hm._thread
        hm.start()
        assert hm._thread is thread1
        hm.stop()
