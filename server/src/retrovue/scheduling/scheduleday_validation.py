"""ScheduleDay contiguity validation.

Enforces INV-SCHEDULEDAY-NO-GAPS-001: a materialized ScheduleDay must
provide continuous, gap-free coverage across the full broadcast day
from programming_day_start to programming_day_start + 24h.
"""

from __future__ import annotations

from retrovue.runtime.schedule_types import ResolvedScheduleDay


def validate_scheduleday_contiguity(
    schedule_day: ResolvedScheduleDay,
    *,
    programming_day_start_hour: int,
    grid_block_minutes: int,
) -> None:
    """Validate that a ResolvedScheduleDay tiles the full broadcast day.

    Computes absolute slot intervals from slot positions in the grid,
    sorts by start, and checks:
      1. First slot starts at programming_day_start.
      2. Adjacent pairs have no gap (current.end == next.start).
      3. Last slot ends at programming_day_start + 24h.

    Raises ValueError with INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED on any gap.
    """
    slots = schedule_day.resolved_slots
    if not slots:
        raise ValueError(
            "INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            "ScheduleDay has no slots — entire broadcast day is uncovered"
        )

    grid_ms = grid_block_minutes * 60 * 1000
    day_ms = 24 * 60 * 60 * 1000

    # Compute absolute intervals for each slot
    intervals: list[tuple[int, int]] = []
    for i, slot in enumerate(slots):
        start_ms = i * grid_ms
        end_ms = start_ms + int(slot.duration_seconds * 1000)
        intervals.append((start_ms, end_ms))

    intervals.sort(key=lambda x: x[0])

    # Check first slot starts at day start (offset 0)
    if intervals[0][0] != 0:
        gap_minutes = intervals[0][0] // (60 * 1000)
        raise ValueError(
            f"INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            f"gap at start of broadcast day — first slot starts at offset "
            f"{gap_minutes} minutes instead of 0"
        )

    # Check contiguity between adjacent slots
    for i in range(len(intervals) - 1):
        current_end = intervals[i][1]
        next_start = intervals[i + 1][0]
        if current_end != next_start:
            gap_ms = next_start - current_end
            gap_minutes = gap_ms // (60 * 1000)
            raise ValueError(
                f"INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
                f"gap of {gap_minutes} minutes between slot {i} "
                f"(end={current_end}ms) and slot {i + 1} "
                f"(start={next_start}ms)"
            )

    # Check last slot ends at broadcast day end (24h)
    last_end = intervals[-1][1]
    if last_end != day_ms:
        gap_minutes = (day_ms - last_end) // (60 * 1000)
        raise ValueError(
            f"INV-SCHEDULEDAY-NO-GAPS-001-VIOLATED: "
            f"gap at end of broadcast day — last slot ends at offset "
            f"{last_end}ms ({last_end // (60 * 1000)} minutes), "
            f"expected {day_ms}ms (1440 minutes). "
            f"Gap of {gap_minutes} minutes."
        )
