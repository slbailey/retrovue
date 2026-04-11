"""
Contract tests for INV-EXECUTIONENTRY-LOOKAHEAD-001.

ExecutionEntry window MUST extend at least min_execution_hours ahead of
current MasterClock time. HorizonManager detects shortfalls and extends.

PLAYLOG-004 (Tier 3): Lookahead shortfall triggers window extension.
PLAYLOG-005 (Tier 3): Lookahead at exactly min_execution_hours is compliant.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from retrovue.runtime.horizon_manager import HorizonManager, LookaheadViolation


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPOCH = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)
MIN_EXECUTION_HOURS = 3
GRID_BLOCK_MS = 30 * 60 * 1000  # 30 minutes
ONE_HOUR_MS = 60 * 60 * 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeClock:
    """Minimal clock for these tests."""

    def __init__(self, start_ms: int) -> None:
        self._ms = start_ms

    def now_utc_ms(self) -> int:
        return self._ms

    def advance_ms(self, n: int) -> None:
        self._ms += n


def _extend_by_one_day(channel_id: str, extend_from_ms: int) -> int:
    """Extend execution window by one 24-hour day of 30-min grid blocks."""
    return extend_from_ms + 24 * ONE_HOUR_MS


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvExecutionentryLookahead001:
    """Contract tests for INV-EXECUTIONENTRY-LOOKAHEAD-001."""

    def test_playlog_004_shortfall_triggers_extension(self):
        """PLAYLOG-004: ExecutionEntry depth below min_execution_hours
        triggers HorizonManager extension.

        Clock at EPOCH. Execution window ends at EPOCH + min_execution_hours - 10min.
        HorizonManager detects shortfall and extends. After extension, depth >= min_execution_hours.
        """
        clock = _FakeClock(EPOCH_MS)
        shortfall_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS - 10 * 60 * 1000

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_day,
            execution_window_end_ms=shortfall_end,
        )

        # Pre-condition: depth is below minimum
        assert hm.remaining_depth_ms() < MIN_EXECUTION_HOURS * ONE_HOUR_MS

        # Trigger evaluation
        report = hm.evaluate_once()

        # Post-conditions per spec:
        # 1. Extension was triggered
        assert report.extension_attempt_count > 0
        # 2. After extension, depth >= min_execution_hours
        assert report.execution_compliant is True
        assert report.depth_ms >= MIN_EXECUTION_HOURS * ONE_HOUR_MS
        # 3. Extension reason is clock_progression
        for attempt in hm.extension_attempt_log:
            assert attempt.reason_code == "clock_progression"
        # 4. No gaps (window end moved forward)
        assert hm.execution_window_end_ms > shortfall_end

    def test_playlog_005_exact_depth_is_compliant(self):
        """PLAYLOG-005: ExecutionEntry depth at exactly min_execution_hours
        is compliant. No shortfall. No violation. No extension.

        Clock at EPOCH. Execution window ends at EPOCH + min_execution_hours.
        """
        clock = _FakeClock(EPOCH_MS)
        exact_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_day,
            execution_window_end_ms=exact_end,
        )

        # Pre-condition: depth is exactly at minimum
        assert hm.remaining_depth_ms() == MIN_EXECUTION_HOURS * ONE_HOUR_MS

        report = hm.evaluate_once()

        # Post-conditions per spec:
        # 1. No violation
        assert report.execution_compliant is True
        # 2. No extension triggered
        assert report.extension_attempt_count == 0
        # 3. Health report shows exact depth
        assert report.depth_ms == MIN_EXECUTION_HOURS * ONE_HOUR_MS

    def test_slight_excess_no_extension(self):
        """Depth at min_execution_hours + 1 grid block: still compliant,
        no extension triggered."""
        clock = _FakeClock(EPOCH_MS)
        excess_end = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS + GRID_BLOCK_MS

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_day,
            execution_window_end_ms=excess_end,
        )

        report = hm.evaluate_once()

        assert report.execution_compliant is True
        assert report.extension_attempt_count == 0

    def test_shortfall_by_one_ms_triggers_extension(self):
        """Depth at min_execution_hours - 1ms: shortfall detected, extension triggered."""
        clock = _FakeClock(EPOCH_MS)
        barely_short = EPOCH_MS + MIN_EXECUTION_HOURS * ONE_HOUR_MS - 1

        hm = HorizonManager(
            channel_id="test-channel",
            clock=clock,
            min_execution_hours=MIN_EXECUTION_HOURS,
            extend_fn=_extend_by_one_day,
            execution_window_end_ms=barely_short,
        )

        report = hm.evaluate_once()

        assert report.extension_attempt_count > 0
        assert report.execution_compliant is True
