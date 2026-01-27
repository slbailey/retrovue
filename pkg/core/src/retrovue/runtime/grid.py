"""
Phase 1 — Grid math: boundaries defined once, centrally.

Pure functions for 30-minute grid (:00 and :30). No schedule, assets, or CM.
All schedule and playout timing use these same boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


GRID_MINUTES = 30
# Phase 3 uses this to assert config consistency (grid_duration_ms == Phase 1).
GRID_DURATION_MS = GRID_MINUTES * 60 * 1000  # 1_800_000


def grid_start(now: datetime, grid_minutes: int = GRID_MINUTES) -> datetime:
    """Start of the current grid block (floor to :00 or :30).
    
    Args:
        now: Wall-clock time (aware preferred; naive is floored in UTC).
        grid_minutes: Grid size in minutes (default 30).
    
    Returns:
        Start of the block containing `now`.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    block_minute = (now.minute // grid_minutes) * grid_minutes
    return now.replace(minute=block_minute, second=0, microsecond=0)


def grid_end(now: datetime, grid_minutes: int = GRID_MINUTES) -> datetime:
    """End of the current grid block (exclusive end of block).
    
    Returns:
        grid_start(now) + grid_minutes (start of next block).
    """
    start = grid_start(now, grid_minutes)
    return start + timedelta(minutes=grid_minutes)


def elapsed_in_grid(now: datetime, grid_minutes: int = GRID_MINUTES) -> timedelta:
    """Elapsed time since the start of the current grid block."""
    start = grid_start(now, grid_minutes)
    return now - start


def remaining_in_grid(now: datetime, grid_minutes: int = GRID_MINUTES) -> timedelta:
    """Time remaining until the end of the current grid block."""
    end = grid_end(now, grid_minutes)
    return end - now
