"""
Phase 1 — Grid Math Contract tests.

Unit tests only: fixed datetimes, no HTTP, no tune-in.
Asserts grid_start, grid_end, elapsed_in_grid, remaining_in_grid per Phase 1 Contract.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from retrovue.runtime.grid import (
    GRID_MINUTES,
    elapsed_in_grid,
    grid_end,
    grid_start,
    remaining_in_grid,
)

# Fixed date for reproducible tests
BASE = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)


def test_phase1_10_00_start_end():
    """Phase 1: 10:00 → start=10:00, end=10:30."""
    now = BASE.replace(hour=10, minute=0, second=0, microsecond=0)
    start = grid_start(now)
    end = grid_end(now)
    assert start == BASE.replace(hour=10, minute=0, second=0, microsecond=0)
    assert end == BASE.replace(hour=10, minute=30, second=0, microsecond=0)


def test_phase1_10_07_elapsed():
    """Phase 1: 10:07 → elapsed=7:00."""
    now = BASE.replace(hour=10, minute=7, second=0, microsecond=0)
    elapsed = elapsed_in_grid(now)
    assert elapsed == timedelta(minutes=7)


def test_phase1_10_29_59_remaining():
    """Phase 1: 10:29:59 → remaining=0:01."""
    now = BASE.replace(hour=10, minute=29, second=59, microsecond=0)
    remaining = remaining_in_grid(now)
    assert remaining == timedelta(seconds=1)


def test_phase1_10_30_new_grid():
    """Phase 1: 10:30 → new grid (start=10:30, end=11:00)."""
    now = BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    start = grid_start(now)
    end = grid_end(now)
    assert start == BASE.replace(hour=10, minute=30, second=0, microsecond=0)
    assert end == BASE.replace(hour=11, minute=0, second=0, microsecond=0)


def test_phase1_grid_size_constant():
    """Phase 1: Grid size = 30 minutes."""
    assert GRID_MINUTES == 30


def test_phase1_boundaries_00_and_30():
    """Phase 1: Boundaries at :00 and :30."""
    # :00 is start of block
    now_00 = BASE.replace(hour=14, minute=0, second=0, microsecond=0)
    assert grid_start(now_00).minute == 0
    assert grid_end(now_00) == BASE.replace(hour=14, minute=30, second=0, microsecond=0)
    # :30 is start of next block
    now_30 = BASE.replace(hour=14, minute=30, second=0, microsecond=0)
    assert grid_start(now_30).minute == 30
    assert grid_end(now_30) == BASE.replace(hour=15, minute=0, second=0, microsecond=0)


def test_phase1_elapsed_remaining_consistency():
    """elapsed_in_grid + remaining_in_grid = grid period (30 min)."""
    now = BASE.replace(hour=10, minute=17, second=45, microsecond=0)
    elapsed = elapsed_in_grid(now)
    remaining = remaining_in_grid(now)
    assert elapsed + remaining == timedelta(minutes=GRID_MINUTES)
