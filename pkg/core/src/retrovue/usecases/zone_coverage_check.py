"""Pure-function helpers for zone coverage and overlap validation.

Shared by zone_add, zone_update, and the schedule preview endpoint.
No DB access, no side effects — operates on zone-like objects with
start_time, end_time, day_filters, and enabled attributes.

Enforces:
  INV-PLAN-NO-ZONE-OVERLAP-001 — No two active zones may overlap
  INV-PLAN-FULL-COVERAGE-001   — Zones must tile the full broadcast day

All interval arithmetic is normalized to broadcast-day-relative coordinates
[0, 1440] where 0 = programming_day_start and 1440 = programming_day_start + 24h.
This correctly handles programming_day_start ≠ 00:00 and midnight-wrapping zones.

Migration note: Existing plans in DB may violate these invariants.
After this change, editing/saving such plans will fail until corrected.
"""

from __future__ import annotations

from datetime import time as dt_time
from typing import Any, Protocol

# All 7 broadcast days
ALL_DAYS = frozenset({"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"})

# End of day sentinel (24:00 stored as 23:59:59.999999)
END_OF_DAY = dt_time(23, 59, 59, 999999)

# Full broadcast day in minutes
_DAY_MINUTES = 24 * 60  # 1440


class ZoneLike(Protocol):
    """Structural protocol for objects with zone time/filter fields."""

    start_time: dt_time
    end_time: dt_time
    day_filters: list[str] | None
    enabled: bool


def _time_to_minutes(t: dt_time) -> int:
    """Convert a time to minutes from midnight. END_OF_DAY → 1440."""
    if t == END_OF_DAY:
        return _DAY_MINUTES
    return t.hour * 60 + t.minute + (1 if t.second >= 30 else 0)


def _normalize_intervals(
    raw_start: int, raw_end: int, pds_min: int
) -> list[tuple[int, int]]:
    """Normalize a zone's wall-clock interval to broadcast-day-relative
    coordinates [0, 1440] where 0 = programming_day_start.

    Handles midnight-wrapping zones (raw_start > raw_end) by splitting
    into two sub-intervals in normalized space.

    Returns a list of 1 or 2 non-wrapping (start < end) intervals.
    """
    s = (raw_start - pds_min) % _DAY_MINUTES
    e = (raw_end - pds_min) % _DAY_MINUTES

    # e == 0 means the zone ends exactly at programming_day_start,
    # which is the END of the broadcast day → 1440.
    if e == 0:
        e = _DAY_MINUTES

    if s < e:
        return [(s, e)]
    # Zone wraps around end of broadcast day
    intervals: list[tuple[int, int]] = []
    if s < _DAY_MINUTES:
        intervals.append((s, _DAY_MINUTES))
    if e > 0:
        intervals.append((0, e))
    return intervals


def _effective_days(zone: Any) -> frozenset[str]:
    """Return the set of days a zone is active on. None/empty → all days."""
    if zone.day_filters:
        return frozenset(zone.day_filters)
    return ALL_DAYS


def _days_overlap(a: Any, b: Any) -> frozenset[str]:
    """Return the intersection of days two zones are both active."""
    return _effective_days(a) & _effective_days(b)


def _interval_pair_overlap(
    a_start: int, a_end: int, b_start: int, b_end: int
) -> tuple[int, int] | None:
    """Return the overlap interval (start, end) in minutes, or None.

    Assumes non-wrapping intervals where start < end.
    """
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    if lo < hi:
        return (lo, hi)
    return None


def _norm_to_wall(norm_min: int, pds_min: int) -> str:
    """Convert normalized broadcast-day minutes back to wall-clock HH:MM."""
    wall = (norm_min + pds_min) % _DAY_MINUTES
    if norm_min == _DAY_MINUTES:
        wall = (pds_min) % _DAY_MINUTES
        # End of broadcast day = programming_day_start
    h, m = divmod(wall, 60)
    if norm_min == _DAY_MINUTES and wall == 0:
        return "24:00"
    return f"{h:02d}:{m:02d}"


def _minutes_to_hhmm(m: int) -> str:
    """Convert minutes to HH:MM string (for normalized coordinates)."""
    h, mm = divmod(m, 60)
    return f"{h:02d}:{mm:02d}"


def check_overlap(
    zones: list[Any],
    programming_day_start: dt_time = dt_time(0, 0),
) -> list[str]:
    """Check for pairwise overlaps among enabled zones on shared days.

    All intervals are normalized to broadcast-day-relative coordinates
    before comparison.

    Returns a list of violation strings (empty if clean).
    Each violation is tagged with INV-PLAN-NO-ZONE-OVERLAP-001-VIOLATED.
    """
    pds_min = _time_to_minutes(programming_day_start)
    active = [z for z in zones if z.enabled]
    violations: list[str] = []

    for i in range(len(active)):
        for j in range(i + 1, len(active)):
            a, b = active[i], active[j]
            shared_days = _days_overlap(a, b)
            if not shared_days:
                continue

            a_intervals = _normalize_intervals(
                _time_to_minutes(a.start_time),
                _time_to_minutes(a.end_time),
                pds_min,
            )
            b_intervals = _normalize_intervals(
                _time_to_minutes(b.start_time),
                _time_to_minutes(b.end_time),
                pds_min,
            )

            # Check all sub-interval pairs for overlap
            for a_s, a_e in a_intervals:
                for b_s, b_e in b_intervals:
                    hit = _interval_pair_overlap(a_s, a_e, b_s, b_e)
                    if hit:
                        a_name = getattr(a, "name", "?")
                        b_name = getattr(b, "name", "?")
                        days_str = ",".join(sorted(shared_days))
                        violations.append(
                            f"INV-PLAN-NO-ZONE-OVERLAP-001-VIOLATED: "
                            f"zones '{a_name}' and '{b_name}' overlap "
                            f"[{_norm_to_wall(hit[0], pds_min)}"
                            f"-{_norm_to_wall(hit[1], pds_min)}] "
                            f"on days [{days_str}]"
                        )

    return violations


def check_coverage(
    zones: list[Any],
    programming_day_start: dt_time = dt_time(0, 0),
) -> list[str]:
    """Check that enabled zones tile the full broadcast day [0, 1440]
    (normalized to programming_day_start) for every day-of-week that
    any zone applies to.

    Returns a list of violation strings (empty if clean).
    Each violation is tagged with INV-PLAN-FULL-COVERAGE-001-VIOLATED.
    """
    pds_min = _time_to_minutes(programming_day_start)
    active = [z for z in zones if z.enabled]
    if not active:
        return [
            "INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
            "no enabled zones — broadcast day has no coverage"
        ]

    # Determine which days the plan covers
    all_plan_days: set[str] = set()
    for z in active:
        all_plan_days |= _effective_days(z)

    violations: list[str] = []

    for day in sorted(all_plan_days):
        # Collect normalized intervals for this day
        intervals: list[tuple[int, int]] = []
        for z in active:
            if day in _effective_days(z):
                intervals.extend(
                    _normalize_intervals(
                        _time_to_minutes(z.start_time),
                        _time_to_minutes(z.end_time),
                        pds_min,
                    )
                )

        if not intervals:
            violations.append(
                f"INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
                f"day {day} has no zone coverage at all"
            )
            continue

        # Merge intervals and find gaps in [0, 1440]
        intervals.sort()
        merged: list[tuple[int, int]] = [intervals[0]]
        for s, e in intervals[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))

        # Check full coverage [0, 1440]
        if merged[0][0] > 0:
            violations.append(
                f"INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
                f"gap on {day} "
                f"[{_norm_to_wall(0, pds_min)}"
                f"-{_norm_to_wall(merged[0][0], pds_min)}]"
            )
        for k in range(len(merged) - 1):
            if merged[k][1] < merged[k + 1][0]:
                violations.append(
                    f"INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
                    f"gap on {day} "
                    f"[{_norm_to_wall(merged[k][1], pds_min)}"
                    f"-{_norm_to_wall(merged[k + 1][0], pds_min)}]"
                )
        if merged[-1][1] < _DAY_MINUTES:
            violations.append(
                f"INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
                f"gap on {day} "
                f"[{_norm_to_wall(merged[-1][1], pds_min)}"
                f"-{_norm_to_wall(_DAY_MINUTES, pds_min)}]"
            )

    return violations


def check_grid_alignment(
    zones: list[Any],
    grid_block_minutes: int | None = None,
) -> list[str]:
    """Check that every enabled zone's start, end, and duration align to the
    channel grid.

    Returns a list of violation strings (empty if clean).
    Each violation is tagged with INV-PLAN-GRID-ALIGNMENT-001-VIOLATED.
    Skipped if grid_block_minutes is None (channel has no grid configured).
    """
    if grid_block_minutes is None:
        return []

    active = [z for z in zones if z.enabled]
    violations: list[str] = []

    for z in active:
        name = getattr(z, "name", "?")
        s = _time_to_minutes(z.start_time)
        e = _time_to_minutes(z.end_time)

        if s % grid_block_minutes != 0:
            violations.append(
                f"INV-PLAN-GRID-ALIGNMENT-001-VIOLATED: "
                f"zone '{name}' start_time ({_minutes_to_hhmm(s)}) "
                f"is not aligned to grid_block_minutes ({grid_block_minutes})"
            )

        if e % grid_block_minutes != 0:
            violations.append(
                f"INV-PLAN-GRID-ALIGNMENT-001-VIOLATED: "
                f"zone '{name}' end_time ({_minutes_to_hhmm(e)}) "
                f"is not aligned to grid_block_minutes ({grid_block_minutes})"
            )

        # Duration must also be a multiple of grid
        duration = (e - s) % _DAY_MINUTES
        if duration > 0 and duration % grid_block_minutes != 0:
            violations.append(
                f"INV-PLAN-GRID-ALIGNMENT-001-VIOLATED: "
                f"zone '{name}' duration ({duration} minutes) "
                f"is not a multiple of grid_block_minutes ({grid_block_minutes})"
            )

    return violations


def validate_zone_plan_integrity(
    zones: list[Any],
    programming_day_start: dt_time = dt_time(0, 0),
    grid_block_minutes: int | None = None,
) -> None:
    """Run grid alignment, overlap, and coverage checks.

    Raise ValueError on first violation set.
    Precedence: grid alignment > overlap > coverage.

    This is the single enforcement entry point called by zone_add and zone_update
    after assembling the candidate zone list.
    """
    grid_violations = check_grid_alignment(zones, grid_block_minutes)
    if grid_violations:
        raise ValueError(grid_violations[0])

    overlap_violations = check_overlap(zones, programming_day_start)
    if overlap_violations:
        raise ValueError(overlap_violations[0])

    coverage_violations = check_coverage(zones, programming_day_start)
    if coverage_violations:
        raise ValueError(coverage_violations[0])


__all__ = [
    "check_grid_alignment",
    "check_overlap",
    "check_coverage",
    "validate_zone_plan_integrity",
]
