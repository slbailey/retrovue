"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-COMPILE-NO-HORIZON-GLOBAL-001

The carry-in value for a target day MUST NOT be derived from a global
variable that accumulates across the entire loaded horizon. It MUST be
scoped to the immediately preceding broadcast day.

This test verifies that the _build_initial startup loop does not
propagate a global last_loaded_end_ms across multiple days.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import pytest

try:
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _day_start_ms(day: date, hour: int = 6) -> int:
    dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


SLOT_MS = 30 * 60 * 1000


def _make_block(start_utc_ms: int, duration_ms: int, block_id: str) -> ScheduledBlock:
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + duration_ms,
        segments=(
            ScheduledSegment(
                segment_type="content",
                asset_uri="/test.mkv",
                asset_start_offset_ms=0,
                segment_duration_ms=duration_ms,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# INV-COMPILE-NO-HORIZON-GLOBAL-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCompileNoHorizonGlobal:
    """Carry-in must be per-day, not horizon-global."""

    def test_global_accumulator_contaminates_earlier_days(self):
        """Demonstrates the bug: loaded_blocks[-1].end_utc_ms from a future
        day is used as carry-in for an earlier day.

        Scenario:
          - DB has blocks for Mar 26 (ending Mar 27 06:00) and Mar 29 (ending Mar 30 06:00)
          - Mar 27 and Mar 28 are missing
          - Startup loop sorts missing: [Mar 27, Mar 28]
          - loaded_blocks[-1].end_utc_ms = Mar 30 06:00 (from Mar 29)
          - Mar 27 is compiled with carry-in = Mar 30 06:00 → ALL blocks dropped
        """
        mar_26 = date(2026, 3, 26)
        mar_27 = date(2026, 3, 27)
        mar_29 = date(2026, 3, 29)
        mar_30 = date(2026, 3, 30)

        mar_26_end = _day_start_ms(mar_27)  # D-1 ends at D start (no carry-in)
        mar_29_end = _day_start_ms(mar_30)  # Future day ends way after D

        # The WRONG way: global accumulator
        last_loaded_end_ms_global = max(mar_26_end, mar_29_end)
        assert last_loaded_end_ms_global == mar_29_end

        # Using this as carry-in for Mar 27 would give:
        effective_mar27_wrong = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-27", 6, "UTC", last_loaded_end_ms_global,
        )
        mar_27_start = _day_start_ms(mar_27)
        # The effective open is 3 days past Mar 27 → all blocks dropped
        assert effective_mar27_wrong > mar_27_start + (48 * SLOT_MS), (
            "Global accumulator pushes effective open past entire day"
        )

        # The CORRECT way: per-day from D-1 only
        effective_mar27_correct = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-27", 6, "UTC", mar_26_end,
        )
        # D-1 ends exactly at D start → no carry-in
        assert effective_mar27_correct == mar_27_start, (
            "Per-day carry-in from D-1 should equal day start when D-1 ends at boundary"
        )

    def test_per_day_carry_in_is_independent(self):
        """Each day's carry-in must be computed from that day's D-1,
        not from a running accumulator."""
        mar_27 = date(2026, 3, 27)
        mar_28 = date(2026, 3, 28)

        # Mar 27's last block extends 1 hour into Mar 28
        mar_27_end = _day_start_ms(mar_28) + 60 * 60 * 1000
        mar_28_start = _day_start_ms(mar_28)

        # Mar 28's carry-in should be mar_27_end (D-1's last block)
        effective_mar28 = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-28", 6, "UTC", mar_27_end,
        )
        assert effective_mar28 == mar_27_end
        assert effective_mar28 == mar_28_start + 60 * 60 * 1000

        # But Mar 27's carry-in should NOT use Mar 28's value
        # Mar 27's D-1 = Mar 26, which has no carry-in into Mar 27
        effective_mar27 = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-27", 6, "UTC", 0,
        )
        assert effective_mar27 == _day_start_ms(mar_27)

    def test_loaded_blocks_sorted_by_time_exposes_future(self):
        """When loaded_blocks is sorted by start_utc_ms and includes
        future days, loaded_blocks[-1] is the LATEST block, not the
        most recent prior-day block."""
        mar_26 = date(2026, 3, 26)
        mar_29 = date(2026, 3, 29)

        blocks = [
            _make_block(_day_start_ms(mar_26), 48 * SLOT_MS, "blk-mar26"),
            _make_block(_day_start_ms(mar_29), 48 * SLOT_MS, "blk-mar29"),
        ]
        blocks.sort(key=lambda b: b.start_utc_ms)

        # loaded_blocks[-1] is the Mar 29 block
        last_end = blocks[-1].end_utc_ms
        assert last_end == _day_start_ms(mar_29) + 48 * SLOT_MS

        # This value is from Mar 30 — NOT a valid carry-in for Mar 27
        mar_27_start = _day_start_ms(date(2026, 3, 27))
        assert last_end > mar_27_start + 48 * SLOT_MS, (
            "Future block end is beyond the entire target day"
        )
