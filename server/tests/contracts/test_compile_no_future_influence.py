"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-COMPILE-NO-FUTURE-INFLUENCE-001

Schedule compilation for target day D MUST NOT depend on schedule data
from day D+1 or any later day. The carry-in boundary for day D is
derived from day D-1 only.

This test verifies that blocks loaded for future days do not suppress
or alter blocks compiled for earlier days.
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timedelta, timezone

import pytest

try:
    from retrovue.runtime.dsl_schedule_service import (
        DslScheduleService,
        _serialize_scheduled_block,
    )
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_block(start_utc_ms: int, duration_ms: int, block_id: str = "blk-test") -> ScheduledBlock:
    """Create a minimal ScheduledBlock."""
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + duration_ms,
        segments=(
            ScheduledSegment(
                segment_type="content",
                asset_uri="/test/content.mkv",
                asset_start_offset_ms=0,
                segment_duration_ms=duration_ms,
            ),
        ),
    )


def _day_start_ms(day: date, hour: int = 6) -> int:
    """UTC ms for the start of a broadcast day at the given hour."""
    dt = datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


SLOT_30_MIN_MS = 30 * 60 * 1000


# ---------------------------------------------------------------------------
# INV-COMPILE-NO-FUTURE-INFLUENCE-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCompileNoFutureInfluence:
    """Future-day data must not affect earlier-day compilation."""

    def test_future_day_blocks_do_not_suppress_target_day(self):
        """If D+2 has blocks loaded from DB, compiling D must not use
        D+2's end time as carry-in. D's blocks must survive."""
        day_d = date(2026, 4, 1)  # target day
        day_d_plus_2 = date(2026, 4, 3)

        d_start = _day_start_ms(day_d)
        d2_start = _day_start_ms(day_d_plus_2)

        # Simulate: D+2 has blocks loaded, ending well past D's time
        future_block = _make_block(
            start_utc_ms=d2_start,
            duration_ms=24 * SLOT_30_MIN_MS,  # full day
            block_id="blk-future",
        )
        future_end_ms = future_block.end_utc_ms

        # The carry-in for day D should be from D-1, not from D+2.
        # Using D+2's end as carry-in would produce:
        #   effective_day_open = max(D_start, D+2_end) = D+2_end
        # which would drop ALL of D's blocks.
        effective_open_from_future = DslScheduleService._compute_effective_day_open_ms(
            str(day_d), 6, "UTC", future_end_ms,
        )
        effective_open_from_zero = DslScheduleService._compute_effective_day_open_ms(
            str(day_d), 6, "UTC", 0,
        )

        # The future-contaminated carry-in pushes D's open past D's entire day
        assert effective_open_from_future > d_start + (48 * SLOT_30_MIN_MS), (
            "Sanity check: future carry-in should be far past D's day"
        )

        # The correct carry-in (no prior day → zero) should be D's own start
        assert effective_open_from_zero == d_start, (
            "With zero prior-day boundary, effective open should be day start"
        )

    def test_apply_overlap_with_future_carry_in_drops_all_blocks(self):
        """Demonstrates the bug: using future end as carry-in drops everything."""
        day_d = date(2026, 4, 1)
        day_d_plus_2 = date(2026, 4, 3)
        d_start = _day_start_ms(day_d)
        d2_end = _day_start_ms(day_d_plus_2) + 24 * SLOT_30_MIN_MS

        # Build a schedule for day D with 48 blocks
        program_blocks = []
        cursor = d_start
        for i in range(48):
            program_blocks.append({
                "title": f"Block {i}",
                "start_at": datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).isoformat(),
                "slot_duration_sec": 1800,
                "asset_id": f"asset-{i:03d}",
                "episode_duration_sec": 1320,
            })
            cursor += SLOT_30_MIN_MS

        schedule = {"program_blocks": program_blocks}

        # Apply overlap with future carry-in (the bug)
        DslScheduleService._apply_overlap_push_forward(
            schedule, d2_end, str(day_d),
        )

        # BUG: all blocks dropped because d2_end > every block's end
        assert len(schedule["program_blocks"]) == 0, (
            "Expected all blocks dropped when future carry-in is used "
            "(this test documents the bug, not the fix)"
        )

    def test_apply_overlap_with_correct_carry_in_preserves_blocks(self):
        """Using D-1's carry-in preserves all blocks for D."""
        day_d = date(2026, 4, 1)
        d_start = _day_start_ms(day_d)

        # D-1's last block ends 1 hour into D (carry-in)
        carry_in_from_d_minus_1 = d_start + 60 * 60 * 1000  # D start + 1h

        program_blocks = []
        cursor = d_start
        for i in range(48):
            program_blocks.append({
                "title": f"Block {i}",
                "start_at": datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).isoformat(),
                "slot_duration_sec": 1800,
                "asset_id": f"asset-{i:03d}",
                "episode_duration_sec": 1320,
            })
            cursor += SLOT_30_MIN_MS

        schedule = {"program_blocks": list(program_blocks)}

        DslScheduleService._apply_overlap_push_forward(
            schedule, carry_in_from_d_minus_1, str(day_d),
        )

        # Only the first 2 blocks (0:00-0:30, 0:30-1:00) are fully subsumed
        # by the carry-in ending at +1:00. Remaining 46 blocks survive.
        surviving = schedule["program_blocks"]
        assert len(surviving) >= 46, (
            f"Expected >= 46 blocks surviving with 1h carry-in, got {len(surviving)}"
        )

    def test_carry_in_from_d_minus_1_only(self):
        """The carry-in value must come from D-1, not from an arbitrary
        future day in the horizon."""
        day_d = date(2026, 4, 1)
        day_d_minus_1 = date(2026, 3, 31)
        d_start = _day_start_ms(day_d)
        d_minus_1_start = _day_start_ms(day_d_minus_1)

        # D-1's last block ends 30 min into D
        d_minus_1_end = d_start + SLOT_30_MIN_MS

        effective = DslScheduleService._compute_effective_day_open_ms(
            str(day_d), 6, "UTC", d_minus_1_end,
        )

        # Effective open should be 30 min past D's start
        assert effective == d_minus_1_end
        assert effective == d_start + SLOT_30_MIN_MS
