"""
Contract tests for INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001.

ExecutionEntry window extension MUST be triggered by clock progression,
not consumer demand. No redundant extensions when depth is sufficient.

HORIZON-001 (Tier 3): Extension triggered by clock progression, not consumer demand.
HORIZON-002 (Tier 3): No extension when depth already satisfies min_execution_hours.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.runtime.horizon_manager import HorizonManager


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPOCH = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)
MIN_EXECUTION_HOURS = 3
ONE_HOUR_MS = 60 * 60 * 1000
GRID_BLOCK_MS = 30 * 60 * 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeClock:
    """Deterministic clock for these tests."""

    def __init__(self, start_ms: int) -> None:
        self._ms = start_ms

    def now_utc_ms(self) -> int:
        return self._ms

    def advance_ms(self, n: int) -> None:
        self._ms += n


def _extend_by_one_grid_block(channel_id: str, extend_from_ms: int) -> int:
    """Extend by one 30-minute grid block."""
    return extend_from_ms + GRID_BLOCK_MS


def _extend_by_one_day(channel_id: str, extend_from_ms: int) -> int:
    """Extend by one full day."""
    return extend_from_ms + 24 * ONE_HOUR_MS


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvExecutionentryLookaheadEnforced001:
    """Contract tests for INV-EXECUTIONENTRY-LOOKAHEAD-ENFORCED-001."""

    def test_horizon_001_extension_by_clock_progression(self):
        """HORIZON-001: Extension is triggered by clock progression only.

        1. Initialize HorizonManager with execution window at EPOCH + min_execution_hours.
        2. Advance clock by 1 grid block increments.
        3. After each advance, trigger evaluate_once().
        4. Assert: extension reason code is always "clock_progression".
        5. Assert: no "consumer_demand" reason codes.
        6. Assert: extension count increases as clock advances.
        """
        clock = _FakeClock(EPOCH_MS)
        initial_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_grid_block,
            execution_window_end_ms=initial_end,
        )

        extension_counts = []

        # Advance clock by grid blocks, evaluating each time
        for step in range(6):  # 6 * 30min = 3 hours of clock advancement
            clock.advance_ms(GRID_BLOCK_MS)
            hm.evaluate_once()
            extension_counts.append(len(hm.extension_attempt_log))

        # Extension count should increase over time
        assert extension_counts[-1] > 0

        # All extension reason codes must be "clock_progression"
        for attempt in hm.extension_attempt_log:
            assert attempt.reason_code == "clock_progression"

        # No consumer demand triggers recorded
        assert hm.extension_forbidden_trigger_count == 0

        # Extension count increases in proportion to clock advancement
        # (not necessarily monotonic per step, but total should be > 0)
        assert extension_counts[-1] >= extension_counts[0]

    def test_horizon_002_no_extension_when_depth_sufficient(self):
        """HORIZON-002: No extension when depth already satisfies min_execution_hours.

        1. Populate execution window to EPOCH + min_execution_hours + 1h (excess).
        2. Trigger evaluate_once() at EPOCH.
        3. Assert: no extension attempt. Health compliant.
        """
        clock = _FakeClock(EPOCH_MS)
        excess_end = EPOCH_MS + (MIN_EXECUTION_HOURS + 1) * ONE_HOUR_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_grid_block,
            execution_window_end_ms=excess_end,
        )

        initial_count = len(hm.extension_attempt_log)

        report = hm.evaluate_once()

        # No extension cycle fired
        assert len(hm.extension_attempt_log) == initial_count
        assert report.extension_attempt_count == 0

        # Health report: compliant with excess depth
        assert report.execution_compliant is True
        assert report.depth_ms == (MIN_EXECUTION_HOURS + 1) * ONE_HOUR_MS

    def test_consumer_demand_is_recorded_as_violation(self):
        """A consumer-triggered extension attempt is recorded as a violation,
        not acted upon."""
        clock = _FakeClock(EPOCH_MS)
        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_grid_block,
            execution_window_end_ms=EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS,
        )

        hm.record_consumer_demand_attempt()
        hm.record_consumer_demand_attempt()

        assert hm.extension_forbidden_trigger_count == 2
        # No actual extension was triggered
        assert len(hm.extension_attempt_log) == 0

    def test_extension_maintains_depth_after_multiple_clock_advances(self):
        """After multiple clock advances, depth is always maintained
        at >= min_execution_hours by clock-driven extensions."""
        clock = _FakeClock(EPOCH_MS)
        initial_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_grid_block,
            execution_window_end_ms=initial_end,
        )

        # Walk 24 hours of simulated time in grid-block steps
        for _ in range(48):
            clock.advance_ms(GRID_BLOCK_MS)
            report = hm.evaluate_once()
            assert report.execution_compliant is True
            assert report.depth_ms >= MIN_EXECUTION_HOURS * ONE_HOUR_MS

    def test_no_redundant_extension_at_exact_minimum(self):
        """At exactly min_execution_hours depth, no extension fires
        (boundary: >= not >)."""
        clock = _FakeClock(EPOCH_MS)
        exact_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_grid_block,
            execution_window_end_ms=exact_end,
        )

        report = hm.evaluate_once()

        assert report.extension_attempt_count == 0
        assert report.execution_compliant is True
