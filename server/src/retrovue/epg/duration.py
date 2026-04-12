"""
EPG duration visibility and human formatting.

INV-EPG-DURATION-VISIBILITY-001: Pure functions for determining whether an EPG
entry's duration should be displayed and how to format it in broadcast style.

All functions are timeline-driven. No content-type detection, no metadata
heuristics, no configuration flags.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

_GRID_MINUTES = 30
_GRID_ALIGNED_MINUTES = {0, 30}


def is_grid_aligned(start_minute: int, end_minute: int, slot_duration_sec: int) -> bool:
    """Return True if a schedule item is grid-implicit (duration not shown).

    A schedule item is grid-implicit when ALL of:
      - start.minute in {0, 30}
      - effective end.minute in {0, 30} (derived from rounded duration)
      - rounded duration in whole minutes is a multiple of 30

    Rounding to nearest minute happens BEFORE grid evaluation.
    """
    rounded_minutes = _round_to_minutes(slot_duration_sec)

    if rounded_minutes % _GRID_MINUTES != 0:
        return False
    if start_minute not in _GRID_ALIGNED_MINUTES:
        return False
    if end_minute not in _GRID_ALIGNED_MINUTES:
        return False
    return True


def format_human_duration(slot_duration_sec: int) -> str:
    """Format a duration in broadcast human-readable form.

    Rules:
      - Round to nearest whole minute first.
      - < 60 minutes: "{m}m"
      - >= 60 minutes, no remainder: "{h}h"
      - >= 60 minutes, with remainder: "{h}h {m}m"

    Never returns decimals. Never returns raw minute counts above 59.
    """
    minutes = _round_to_minutes(slot_duration_sec)

    if minutes < 60:
        return f"{minutes}m"

    hours = minutes // 60
    remainder = minutes % 60
    if remainder == 0:
        return f"{hours}h"
    return f"{hours}h {remainder}m"


def epg_display_duration(
    start_time: datetime,
    end_time: datetime,
    slot_duration_sec: int,
    episode_duration_sec: int | None = None,
    *,
    is_movie: bool = True,
) -> str | None:
    """Compute the display_duration field for an EPG entry.

    Grid alignment is evaluated for ALL items. When the content duration
    is grid-implicit, returns None regardless of content type.

    When the content duration disrupts the grid, only movies (is_movie=True)
    receive a formatted duration string. TV episodes are assumed to align
    to grid and always return None.

    When episode_duration_sec is provided and shorter than the slot, the
    content duration drives the grid check and formatting.

    Rounding is applied BEFORE grid alignment evaluation: the effective end
    minute is derived from start_time + rounded duration, not from the raw
    end_time.
    """
    # Use content duration when it meaningfully differs from the slot
    dur_sec = slot_duration_sec
    if episode_duration_sec is not None and episode_duration_sec < slot_duration_sec:
        dur_sec = episode_duration_sec

    rounded_minutes = _round_to_minutes(dur_sec)
    effective_end = start_time + timedelta(minutes=rounded_minutes)

    if is_grid_aligned(start_time.minute, effective_end.minute, dur_sec):
        return None

    if not is_movie:
        return None

    return format_human_duration(dur_sec)


def _round_to_minutes(duration_sec: int) -> int:
    """Round seconds to nearest whole minute (>= 0.5 rounds up).

    Uses math.floor(x + 0.5) instead of round() to avoid Python's
    banker's rounding (round-half-to-even), which would round 90.5 to 90.
    """
    return math.floor(duration_sec / 60 + 0.5)
