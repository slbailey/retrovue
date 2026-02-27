"""Tests for ExecutionWindowStore and HorizonManager store integration.

Verifies:
- Entries stored and retrieved correctly
- get_next_entry finds the first entry after a given time
- Window boundaries (start/end) report correctly
- Duplicate entries are deduplicated
- Sorted order maintained regardless of insertion order
- HorizonManager populates store when ExecutionDayResult is returned
- HorizonManager works without store (legacy int path)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from retrovue.runtime.clock import ControllableMasterClock
from retrovue.runtime.execution_window_store import (
    ExecutionDayResult,
    ExecutionEntry,
    ExecutionWindowStore,
)
from retrovue.runtime.horizon_manager import HorizonManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BLOCK_DURATION_MS = 30 * 60 * 1000  # 1,800,000 ms


DEFAULT_CHANNEL = "test-channel"


def _make_entry(
    block_index: int,
    start_utc_ms: int,
    block_id: str | None = None,
    channel_id: str = DEFAULT_CHANNEL,
    programming_day_date: date | None = None,
) -> ExecutionEntry:
    """Create a test ExecutionEntry with 30-minute duration."""
    if block_id is None:
        block_id = f"BLOCK-test-{block_index}"
    if programming_day_date is None:
        programming_day_date = date(2026, 2, 11)
    return ExecutionEntry(
        block_id=block_id,
        block_index=block_index,
        start_utc_ms=start_utc_ms,
        end_utc_ms=start_utc_ms + BLOCK_DURATION_MS,
        segments=[{"segment_type": "episode", "segment_duration_ms": BLOCK_DURATION_MS}],
        channel_id=channel_id,
        programming_day_date=programming_day_date,
    )


def _day_start_ms(year: int, month: int, day: int, hour: int = 6) -> int:
    """Epoch ms for a broadcast day start (e.g. 06:00 UTC)."""
    dt = datetime(year, month, day, hour, 0, 0, tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _make_day_entries(broadcast_date: date, n_blocks: int = 48) -> list[ExecutionEntry]:
    """Create n_blocks entries for one broadcast day starting at 06:00."""
    base_ms = _day_start_ms(broadcast_date.year, broadcast_date.month, broadcast_date.day)
    return [
        _make_entry(
            block_index=i,
            start_utc_ms=base_ms + i * BLOCK_DURATION_MS,
            block_id=f"BLOCK-test-{broadcast_date.isoformat()}-{i}",
            programming_day_date=broadcast_date,
        )
        for i in range(n_blocks)
    ]


# ---------------------------------------------------------------------------
# ExecutionWindowStore unit tests
# ---------------------------------------------------------------------------

class TestStoreBasics:
    """Core store operations."""

    def test_empty_store(self):
        store = ExecutionWindowStore()
        assert store.get_window_start() == 0
        assert store.get_window_end() == 0
        assert store.get_all_entries() == []
        assert store.get_next_entry(0) is None

    def test_add_and_retrieve_entries(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        all_entries = store.get_all_entries()
        assert len(all_entries) == 3

    def test_entries_sorted_by_start_utc_ms(self):
        """Entries are sorted regardless of insertion order."""
        store = ExecutionWindowStore()
        base = _day_start_ms(2026, 2, 11)

        # Insert in reverse order
        e2 = _make_entry(2, base + 2 * BLOCK_DURATION_MS, "B-2")
        e0 = _make_entry(0, base, "B-0")
        e1 = _make_entry(1, base + BLOCK_DURATION_MS, "B-1")
        store.add_entries([e2, e0, e1])

        all_entries = store.get_all_entries()
        assert [e.block_id for e in all_entries] == ["B-0", "B-1", "B-2"]

    def test_duplicate_block_ids_deduplicated(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)
        store.add_entries(entries)  # same entries again

        assert len(store.get_all_entries()) == 3

    def test_add_entries_across_days(self):
        store = ExecutionWindowStore()
        day1 = _make_day_entries(date(2026, 2, 11), n_blocks=2)
        day2 = _make_day_entries(date(2026, 2, 12), n_blocks=2)
        store.add_entries(day1)
        store.add_entries(day2)

        assert len(store.get_all_entries()) == 4


class TestGetNextEntry:
    """get_next_entry(after_utc_ms) finds the correct entry."""

    def test_returns_first_entry_after_time(self):
        store = ExecutionWindowStore()
        base = _day_start_ms(2026, 2, 11)
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        # Ask for entry after the start of block 0
        result = store.get_next_entry(base)
        assert result is not None
        assert result.block_index == 1  # block 1 starts after block 0's start

    def test_returns_first_entry_after_between_blocks(self):
        store = ExecutionWindowStore()
        base = _day_start_ms(2026, 2, 11)
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        # Ask for entry after midpoint of block 0
        mid = base + BLOCK_DURATION_MS // 2
        result = store.get_next_entry(mid)
        assert result is not None
        assert result.block_index == 1

    def test_returns_none_when_past_all_entries(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        far_future = _day_start_ms(2026, 12, 31)
        assert store.get_next_entry(far_future) is None

    def test_returns_first_entry_when_before_all(self):
        store = ExecutionWindowStore()
        base = _day_start_ms(2026, 2, 11)
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        # Ask for entry after time 0 (before everything)
        result = store.get_next_entry(0)
        assert result is not None
        assert result.start_utc_ms == base

    def test_returns_none_on_empty_store(self):
        store = ExecutionWindowStore()
        assert store.get_next_entry(0) is None


class TestWindowBoundaries:
    """get_window_start() and get_window_end() report correct boundaries."""

    def test_single_day(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=48)
        store.add_entries(entries)

        base = _day_start_ms(2026, 2, 11)
        assert store.get_window_start() == base
        assert store.get_window_end() == base + 48 * BLOCK_DURATION_MS

    def test_multi_day(self):
        store = ExecutionWindowStore()
        day1 = _make_day_entries(date(2026, 2, 11), n_blocks=48)
        day2 = _make_day_entries(date(2026, 2, 12), n_blocks=48)
        store.add_entries(day1)
        store.add_entries(day2)

        base1 = _day_start_ms(2026, 2, 11)
        base2 = _day_start_ms(2026, 2, 12)
        assert store.get_window_start() == base1
        assert store.get_window_end() == base2 + 48 * BLOCK_DURATION_MS

    def test_window_end_equals_last_entry_end(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        last = entries[-1]
        assert store.get_window_end() == last.end_utc_ms


class TestGetAllEntries:
    """get_all_entries returns a copy, not a reference."""

    def test_returns_copy(self):
        store = ExecutionWindowStore()
        entries = _make_day_entries(date(2026, 2, 11), n_blocks=3)
        store.add_entries(entries)

        result1 = store.get_all_entries()
        result2 = store.get_all_entries()
        assert result1 is not result2
        assert len(result1) == len(result2)


# ---------------------------------------------------------------------------
# HorizonManager + ExecutionWindowStore integration
# ---------------------------------------------------------------------------

class MockScheduleExtender:
    """Minimal mock for EPG (same as in test_horizon_manager_passive)."""

    def __init__(self):
        self.resolved_dates: set[date] = set()
        self.extend_calls: list[date] = []

    def epg_day_exists(self, broadcast_date: date) -> bool:
        return broadcast_date in self.resolved_dates

    def extend_epg_day(self, broadcast_date: date) -> None:
        self.extend_calls.append(broadcast_date)
        self.resolved_dates.add(broadcast_date)


class MockExecutionExtenderWithEntries:
    """Mock pipeline that returns ExecutionDayResult with entries."""

    def __init__(self, day_start_hour: int = 6):
        self.extend_calls: list[date] = []
        self._day_start_hour = day_start_hour

    def extend_execution_day(self, broadcast_date: date) -> ExecutionDayResult:
        self.extend_calls.append(broadcast_date)
        entries = _make_day_entries(broadcast_date, n_blocks=48)
        exec_entries = [
            ExecutionEntry(
                block_id=e.block_id,
                block_index=e.block_index,
                start_utc_ms=e.start_utc_ms,
                end_utc_ms=e.end_utc_ms,
                segments=e.segments,
                channel_id=e.channel_id,
                programming_day_date=e.programming_day_date,
            )
            for e in entries
        ]
        end_dt = datetime(
            broadcast_date.year, broadcast_date.month, broadcast_date.day,
            self._day_start_hour, 0, 0, tzinfo=timezone.utc,
        ) + timedelta(days=1)
        return ExecutionDayResult(
            end_utc_ms=int(end_dt.timestamp() * 1000),
            entries=exec_entries,
        )


class MockExecutionExtenderLegacy:
    """Mock pipeline that returns plain int (legacy behavior)."""

    def __init__(self, day_start_hour: int = 6):
        self.extend_calls: list[date] = []
        self._day_start_hour = day_start_hour

    def extend_execution_day(self, broadcast_date: date) -> int:
        self.extend_calls.append(broadcast_date)
        end_dt = datetime(
            broadcast_date.year, broadcast_date.month, broadcast_date.day,
            self._day_start_hour, 0, 0, tzinfo=timezone.utc,
        ) + timedelta(days=1)
        return int(end_dt.timestamp() * 1000)


def _make_clock(year=2026, month=2, day=11, hour=14, minute=0):
    epoch = datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)
    return ControllableMasterClock(epoch=epoch)


class TestHorizonManagerStoreIntegration:
    """HorizonManager populates ExecutionWindowStore when extending."""

    def test_store_populated_on_extension(self):
        """evaluate_once with ExecutionDayResult populates the store."""
        clock = _make_clock()
        schedule = MockScheduleExtender()
        pipeline = MockExecutionExtenderWithEntries()
        store = ExecutionWindowStore()

        hm = HorizonManager(
            schedule_manager=schedule,
            planning_pipeline=pipeline,
            master_clock=clock,
            min_epg_days=1,
            min_execution_hours=6,
            execution_store=store,
        )

        hm.evaluate_once()

        assert len(store.get_all_entries()) == 48
        assert store.get_window_start() > 0
        assert store.get_window_end() > store.get_window_start()

    def test_store_empty_with_legacy_int_pipeline(self):
        """Legacy int return → store not populated (no entries available)."""
        clock = _make_clock()
        schedule = MockScheduleExtender()
        pipeline = MockExecutionExtenderLegacy()
        store = ExecutionWindowStore()

        hm = HorizonManager(
            schedule_manager=schedule,
            planning_pipeline=pipeline,
            master_clock=clock,
            min_epg_days=1,
            min_execution_hours=6,
            execution_store=store,
        )

        hm.evaluate_once()

        # Pipeline was called (depth tracking works)
        assert len(pipeline.extend_calls) > 0
        assert hm.get_execution_depth_hours() > 0

        # But store has no entries (int has no entries to store)
        assert len(store.get_all_entries()) == 0

    def test_no_store_still_works(self):
        """HorizonManager without execution_store works as before."""
        clock = _make_clock()
        schedule = MockScheduleExtender()
        pipeline = MockExecutionExtenderWithEntries()

        hm = HorizonManager(
            schedule_manager=schedule,
            planning_pipeline=pipeline,
            master_clock=clock,
            min_epg_days=1,
            min_execution_hours=6,
            # No execution_store
        )

        hm.evaluate_once()

        assert hm.get_execution_depth_hours() > 0
        assert len(pipeline.extend_calls) > 0

    def test_store_multi_day_extension(self):
        """Multiple days of extension populate store with all entries."""
        clock = _make_clock()
        schedule = MockScheduleExtender()
        pipeline = MockExecutionExtenderWithEntries()
        store = ExecutionWindowStore()

        hm = HorizonManager(
            schedule_manager=schedule,
            planning_pipeline=pipeline,
            master_clock=clock,
            min_epg_days=1,
            min_execution_hours=30,  # requires 2 days
            execution_store=store,
        )

        hm.evaluate_once()

        assert len(pipeline.extend_calls) == 2
        assert len(store.get_all_entries()) == 96  # 48 * 2 days

    def test_store_window_matches_horizon_depth(self):
        """Store window end should match HorizonManager's execution depth."""
        clock = _make_clock()
        schedule = MockScheduleExtender()
        pipeline = MockExecutionExtenderWithEntries()
        store = ExecutionWindowStore()

        hm = HorizonManager(
            schedule_manager=schedule,
            planning_pipeline=pipeline,
            master_clock=clock,
            min_epg_days=1,
            min_execution_hours=6,
            execution_store=store,
        )

        hm.evaluate_once()

        assert store.get_window_end() == hm.execution_window_end_utc_ms
