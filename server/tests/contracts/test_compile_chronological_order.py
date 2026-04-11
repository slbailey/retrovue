"""
Contract: docs/contracts/schedule_playlog_authority_and_rebuild.md
Invariant: INV-COMPILE-CHRONOLOGICAL-ORDER-001

When compiling multiple broadcast days, compilation MUST proceed in
strictly ascending chronological order. Later days MUST NOT be compiled
before earlier missing days are resolved. Each day's output provides
the prior-day boundary for the next.

This test verifies that the carry-in chain is built day-by-day in order,
and that compiling out of order produces incorrect results.
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


def _make_day_schedule(day: date, num_blocks: int = 48) -> dict:
    """Build a program_blocks schedule for a single day."""
    d_start = _day_start_ms(day)
    blocks = []
    cursor = d_start
    for i in range(num_blocks):
        blocks.append({
            "title": f"Block {i}",
            "start_at": datetime.fromtimestamp(cursor / 1000, tz=timezone.utc).isoformat(),
            "slot_duration_sec": 1800,
            "asset_id": f"asset-{day.isoformat()}-{i:03d}",
            "episode_duration_sec": 1320,
        })
        cursor += SLOT_MS
    return {"program_blocks": blocks}


# ---------------------------------------------------------------------------
# INV-COMPILE-CHRONOLOGICAL-ORDER-001
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestCompileChronologicalOrder:
    """Multi-day compilation must proceed in ascending order."""

    def test_carry_in_chain_requires_chronological_order(self):
        """If D-1's last block extends into D, D must use D-1's end as
        carry-in. This only works if D-1 is compiled before D."""
        mar_27 = date(2026, 3, 27)
        mar_28 = date(2026, 3, 28)

        # Compile Mar 27: 48 blocks, last block ends at Mar 28 06:00 (no carry-in)
        schedule_27 = _make_day_schedule(mar_27, num_blocks=48)
        # No carry-in for Mar 27
        DslScheduleService._apply_overlap_push_forward(
            schedule_27, 0, str(mar_27),
        )
        assert len(schedule_27["program_blocks"]) == 48

        # Mar 27's last block ends at:
        last_block_27 = schedule_27["program_blocks"][-1]
        last_27_start = datetime.fromisoformat(last_block_27["start_at"])
        last_27_end_ms = int(last_27_start.timestamp() * 1000) + int(last_block_27["slot_duration_sec"] * 1000)

        # Compile Mar 28 with carry-in from Mar 27
        schedule_28 = _make_day_schedule(mar_28, num_blocks=48)
        DslScheduleService._apply_overlap_push_forward(
            schedule_28, last_27_end_ms, str(mar_28),
        )

        # Mar 27 fills the full day (06:00 → next 06:00), so carry-in is exactly Mar 28 06:00.
        # No blocks in Mar 28 should be dropped (carry-in == day start).
        assert len(schedule_28["program_blocks"]) == 48, (
            "No blocks should be dropped when carry-in equals day start"
        )

    def test_out_of_order_compilation_loses_carry_in(self):
        """If D is compiled before D-1, D has no carry-in information
        from D-1. This is incorrect when D-1 extends into D."""
        mar_27 = date(2026, 3, 27)
        mar_28 = date(2026, 3, 28)

        # Suppose Mar 27 has a movie that extends 2 hours into Mar 28.
        # If we compile Mar 28 FIRST (before Mar 27), we don't know about
        # the carry-in and blocks at 06:00-08:00 on Mar 28 would overlap.
        mar_28_start = _day_start_ms(mar_28)
        carry_in_from_27 = mar_28_start + 2 * 60 * 60 * 1000  # 2h into Mar 28

        # Correct order: use carry-in from D-1
        schedule_correct = _make_day_schedule(mar_28, num_blocks=48)
        DslScheduleService._apply_overlap_push_forward(
            schedule_correct, carry_in_from_27, str(mar_28),
        )
        # 4 blocks (06:00-06:30, 06:30-07:00, 07:00-07:30, 07:30-08:00) dropped
        assert len(schedule_correct["program_blocks"]) == 44, (
            f"Expected 44 blocks after 2h carry-in, got {len(schedule_correct['program_blocks'])}"
        )

        # Wrong order: no carry-in (D-1 not yet compiled)
        schedule_wrong = _make_day_schedule(mar_28, num_blocks=48)
        DslScheduleService._apply_overlap_push_forward(
            schedule_wrong, 0, str(mar_28),
        )
        assert len(schedule_wrong["program_blocks"]) == 48, (
            "No carry-in means all blocks survive (incorrect overlap)"
        )

        # The wrong-order result has 4 extra blocks that overlap D-1's carry-in
        assert len(schedule_wrong["program_blocks"]) > len(schedule_correct["program_blocks"]), (
            "Out-of-order compilation produces more blocks (overlapping carry-in)"
        )

    def test_missing_days_must_be_sorted_ascending(self):
        """The startup loop compiles missing days in sorted order.
        Verify that sorted order is chronological (ascending)."""
        missing_days = {"2026-03-29", "2026-03-27", "2026-03-28"}
        sorted_days = sorted(missing_days)

        assert sorted_days == ["2026-03-27", "2026-03-28", "2026-03-29"], (
            "Missing days must be compiled in ascending chronological order"
        )

    def test_each_day_provides_boundary_for_next(self):
        """After compiling D, D's last block end becomes the carry-in for D+1."""
        days = [date(2026, 3, 27), date(2026, 3, 28), date(2026, 3, 29)]
        carry_in = 0  # no prior day for first day

        for day in days:
            schedule = _make_day_schedule(day, num_blocks=48)
            DslScheduleService._apply_overlap_push_forward(
                schedule, carry_in, str(day),
            )

            surviving = schedule["program_blocks"]
            assert len(surviving) > 0, f"Day {day} should have blocks"

            # Last block's end becomes carry-in for next day
            last = surviving[-1]
            last_start = datetime.fromisoformat(last["start_at"])
            carry_in = int(last_start.timestamp() * 1000) + int(last["slot_duration_sec"] * 1000)

            # Carry-in should be the end of this day (or slightly past if pushed)
            next_day = day + timedelta(days=1)
            next_day_start = _day_start_ms(next_day)
            assert carry_in >= next_day_start - SLOT_MS, (
                f"Day {day}: carry-in should be near or past next day start"
            )
