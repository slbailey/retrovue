"""
Contract tests for INV-SCHEDULEDAY-NO-GAPS-001.

A materialized ScheduleDay must provide continuous, gap-free coverage
across the full broadcast day from programming_day_start to
programming_day_start + 24h.

SCHED-DAY-005 (Tier 2): ScheduleDay with upstream plan gap raises gap fault.
SCHED-DAY-006 (Tier 2): Full-coverage plan produces gap-free output.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from retrovue.runtime.schedule_types import (
    ProgramRef,
    ProgramRefType,
    ResolvedAsset,
    ResolvedScheduleDay,
    ResolvedSlot,
    SequenceState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(*, hour: int, minute: int = 0, duration_seconds: float = 1800.0) -> ResolvedSlot:
    """Build a 30-min ResolvedSlot at the given time."""
    return ResolvedSlot(
        slot_time=time(hour, minute),
        program_ref=ProgramRef(ref_type=ProgramRefType.PROGRAM, ref_id="prog-1"),
        resolved_asset=ResolvedAsset(
            file_path="/media/test.ts",
            asset_id="asset-001",
            title="Test Show",
            content_duration_seconds=duration_seconds,
        ),
        duration_seconds=duration_seconds,
    )


def _make_full_day_slots(pds_hour: int = 6, grid_minutes: int = 30) -> list[ResolvedSlot]:
    """Build 48 slots covering a full 24-hour broadcast day."""
    slots = []
    for i in range(48):
        total_minutes = pds_hour * 60 + i * grid_minutes
        h = (total_minutes // 60) % 24
        m = total_minutes % 60
        slots.append(_make_slot(hour=h, minute=m, duration_seconds=grid_minutes * 60.0))
    return slots


def _make_schedule_day(slots: list[ResolvedSlot]) -> ResolvedScheduleDay:
    """Wrap slots into a ResolvedScheduleDay."""
    return ResolvedScheduleDay(
        programming_day_date=date(2026, 1, 1),
        resolved_slots=slots,
        resolution_timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        sequence_state=SequenceState(),
        plan_id="plan-001",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvScheduledayNoGaps001:
    """Contract tests for INV-SCHEDULEDAY-NO-GAPS-001."""

    def test_sched_day_005_plan_gap_raises_fault(self):
        """SCHED-DAY-005: ScheduleDay with upstream plan gap raises gap fault.

        A plan covering only [06:00, 18:00] (bypassing INV-PLAN-FULL-COVERAGE-001)
        produces a ScheduleDay with only 24 slots instead of 48. The gap
        [18:00, 06:00+24h] must be detected.
        """
        from retrovue.scheduling.scheduleday_validation import validate_scheduleday_contiguity

        # Only 24 slots: [06:00, 18:00) — missing [18:00, 06:00+24h)
        partial_slots = _make_full_day_slots()[:24]
        sd = _make_schedule_day(partial_slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED"):
            validate_scheduleday_contiguity(
                sd,
                programming_day_start_hour=6,
                grid_block_minutes=30,
            )

    def test_sched_day_006_full_coverage_no_gap(self):
        """SCHED-DAY-006: Full-coverage plan produces gap-free output.

        A plan with full 24-hour zone coverage generates a ScheduleDay with
        48 contiguous 30-minute slots. No gap fault is raised.
        """
        from retrovue.scheduling.scheduleday_validation import validate_scheduleday_contiguity

        full_slots = _make_full_day_slots()
        sd = _make_schedule_day(full_slots)

        # Must not raise
        validate_scheduleday_contiguity(
            sd,
            programming_day_start_hour=6,
            grid_block_minutes=30,
        )

    def test_internal_gap_detected(self):
        """A gap in the middle of the day is detected even if start/end are correct."""
        from retrovue.scheduling.scheduleday_validation import validate_scheduleday_contiguity

        # Build full day, then remove slot 24 (the noon slot)
        slots = _make_full_day_slots()
        del slots[24]  # Remove the slot at 18:00
        sd = _make_schedule_day(slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED"):
            validate_scheduleday_contiguity(
                sd,
                programming_day_start_hour=6,
                grid_block_minutes=30,
            )

    def test_single_slot_day_raises_gap(self):
        """A ScheduleDay with a single slot must raise a gap fault —
        it can't cover 24 hours with one 30-minute slot."""
        from retrovue.scheduling.scheduleday_validation import validate_scheduleday_contiguity

        sd = _make_schedule_day([_make_slot(hour=6)])

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED"):
            validate_scheduleday_contiguity(
                sd,
                programming_day_start_hour=6,
                grid_block_minutes=30,
            )
