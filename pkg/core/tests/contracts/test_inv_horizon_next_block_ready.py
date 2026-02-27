"""
Contract tests: INV-HORIZON-NEXT-BLOCK-READY-001.

At every HorizonManager evaluation tick, the next grid block after "now"
MUST be present in ExecutionWindowStore.  This is a per-fence readiness
guarantee enforced by HorizonManager._check_next_block_ready().

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-NEXT-BLOCK-READY-001.md
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest

from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)
from retrovue.runtime.horizon_manager import (
    HorizonManager,
    ScheduleExtender,
)

# 2025-02-08T06:00:00Z  (programming day start)
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000       # 30 minutes
MIN_EXEC_HORIZON_MS = 21_600_000  # 6 hours
PROG_DAY_START_HOUR = 6
DAY_MS = 86_400_000
LOCKED_WINDOW_MS = 7_200_000   # 2 hours


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeClock:
    """Deterministic clock returning datetime objects."""

    def __init__(self, start_ms: int = EPOCH_MS) -> None:
        self._ms = start_ms
        self._lock = threading.Lock()

    def now_utc(self) -> datetime:
        with self._lock:
            return datetime.fromtimestamp(self._ms / 1000.0, tz=timezone.utc)

    def now_utc_ms(self) -> int:
        with self._lock:
            return self._ms

    def advance_ms(self, delta: int) -> None:
        with self._lock:
            self._ms += delta


class StubScheduleExtender:
    """No-op schedule extender (EPG not under test)."""

    def __init__(self) -> None:
        self._days: set[date] = set()

    def epg_day_exists(self, broadcast_date: date) -> bool:
        return broadcast_date in self._days

    def extend_epg_day(self, broadcast_date: date) -> None:
        self._days.add(broadcast_date)


class PipelineError(Exception):
    """Planning pipeline failure with error_code."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


@dataclass
class PipelineResult:
    """Result from StubExecutionExtender.extend_execution_day()."""
    end_utc_ms: int
    entries: list[ExecutionEntry]


class StubExecutionExtender:
    """Generates execution blocks covering a broadcast day.

    Each call to extend_execution_day returns a PipelineResult with
    end_utc_ms and entries for a full day of BLOCK_DUR_MS blocks.

    Set fail_on_next=True to raise PipelineError on the next call.
    """

    def __init__(
        self,
        block_dur_ms: int = BLOCK_DUR_MS,
        day_start_hour: int = PROG_DAY_START_HOUR,
    ) -> None:
        self._block_dur_ms = block_dur_ms
        self._day_start_hour = day_start_hour
        self._fail_on_next = False
        self._fail_error_code = "PIPELINE_EXHAUSTED"
        self._call_count = 0

    def set_fail_on_next(self, error_code: str = "PIPELINE_EXHAUSTED") -> None:
        self._fail_on_next = True
        self._fail_error_code = error_code

    def extend_execution_day(self, broadcast_date: date) -> PipelineResult:
        if self._fail_on_next:
            self._fail_on_next = False
            raise PipelineError(self._fail_error_code)

        self._call_count += 1

        day_start_dt = datetime(
            broadcast_date.year,
            broadcast_date.month,
            broadcast_date.day,
            self._day_start_hour, 0, 0,
            tzinfo=timezone.utc,
        )
        day_start_ms = int(day_start_dt.timestamp() * 1000)
        day_end_dt = day_start_dt + timedelta(days=1)
        day_end_ms = int(day_end_dt.timestamp() * 1000)

        entries = _make_entries(
            day_start_ms,
            n_blocks=DAY_MS // self._block_dur_ms,
            block_dur_ms=self._block_dur_ms,
            programming_day_date=broadcast_date,
        )
        return PipelineResult(end_utc_ms=day_end_ms, entries=entries)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entries(
    start_ms: int,
    n_blocks: int,
    block_dur_ms: int = BLOCK_DUR_MS,
    channel_id: str = "ch-test",
    programming_day_date: date | None = None,
) -> list[ExecutionEntry]:
    """Create a list of contiguous ExecutionEntry objects."""
    if programming_day_date is None:
        programming_day_date = date(2025, 2, 8)
    entries = []
    for i in range(n_blocks):
        entries.append(ExecutionEntry(
            block_id=f"block-{start_ms + i * block_dur_ms}",
            block_index=i,
            start_utc_ms=start_ms + i * block_dur_ms,
            end_utc_ms=start_ms + (i + 1) * block_dur_ms,
            segments=[{"type": "content", "asset_id": f"asset-{i}"}],
            channel_id=channel_id,
            programming_day_date=programming_day_date,
        ))
    return entries


def _build_horizon_manager(
    clock: FakeClock,
    pipeline: StubExecutionExtender | None = None,
    store: ExecutionWindowStore | None = None,
    locked_window_ms: int = 0,
    min_execution_hours: int = 6,
    min_epg_days: int = 3,
    programming_day_start_hour: int = PROG_DAY_START_HOUR,
) -> HorizonManager:
    if pipeline is None:
        pipeline = StubExecutionExtender()
    schedule = StubScheduleExtender()
    if store is None:
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
    return HorizonManager(
        schedule_manager=schedule,
        planning_pipeline=pipeline,
        master_clock=clock,
        min_epg_days=min_epg_days,
        min_execution_hours=min_execution_hours,
        programming_day_start_hour=programming_day_start_hour,
        execution_store=store,
        locked_window_ms=locked_window_ms,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvHorizonNextBlockReady001:
    """INV-HORIZON-NEXT-BLOCK-READY-001 enforcement tests."""

    def test_tnb_001_next_block_present_after_init(self) -> None:
        """TNB-001: Initialize horizon via evaluate_once() with store.
        Block at 'now' exists, next_block_compliant=True, no fence-specific
        extension attempt recorded.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)

        # Precondition: empty store
        assert store.get_entry_at(EPOCH_MS) is None

        hm.evaluate_once()

        # Block at now must exist
        entry = store.get_entry_at(EPOCH_MS)
        assert entry is not None
        assert entry.start_utc_ms <= EPOCH_MS < entry.end_utc_ms

        # Compliance
        assert hm.next_block_compliant is True
        report = hm.get_health_report()
        assert report.next_block_compliant is True

        # All logged attempts should be successes (from depth extension);
        # no fence-specific failure should be present
        for attempt in hm.extension_attempt_log:
            assert attempt.success is True

    def test_tnb_002_gap_filled_by_extension(self) -> None:
        """TNB-002: Store has blocks starting at +1 block (gap at now).
        evaluate_once() fills the gap via pipeline. Verify get_entry_at(now_ms)
        is non-None, next_block_compliant=True.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)

        # Pre-populate store with blocks starting at +1 block (gap at now)
        gap_entries = _make_entries(
            EPOCH_MS + BLOCK_DUR_MS,
            n_blocks=47,
            programming_day_date=date(2025, 2, 8),
        )
        store.add_entries(gap_entries)

        # Precondition: gap at now
        assert store.get_entry_at(EPOCH_MS) is None
        assert store.get_entry_at(EPOCH_MS + BLOCK_DUR_MS) is not None

        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)
        # Set window end to match pre-populated entries so depth check
        # doesn't independently trigger extension for depth reasons
        hm._execution_window_end_utc_ms = EPOCH_MS + 48 * BLOCK_DUR_MS

        hm.evaluate_once()

        # Gap must be filled
        entry = store.get_entry_at(EPOCH_MS)
        assert entry is not None
        assert entry.start_utc_ms <= EPOCH_MS < entry.end_utc_ms

        # Compliance
        assert hm.next_block_compliant is True
        report = hm.get_health_report()
        assert report.next_block_compliant is True

        # Snapshot generation should be consistent — store should have
        # contiguous entries at now
        snap = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 2 * BLOCK_DUR_MS)
        assert len(snap.entries) >= 1

    def test_tnb_003_pipeline_failure_leaves_gap(self) -> None:
        """TNB-003: Same gap setup, pipeline configured to fail.
        evaluate_once() → gap persists, next_block_compliant=False,
        last attempt logged with error_code="PIPELINE_EXHAUSTED",
        health_report().next_block_compliant=False.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)

        # Pre-populate store with blocks starting at +1 block (gap at now)
        gap_entries = _make_entries(
            EPOCH_MS + BLOCK_DUR_MS,
            n_blocks=47,
            programming_day_date=date(2025, 2, 8),
        )
        store.add_entries(gap_entries)

        # Configure pipeline to fail
        pipeline.set_fail_on_next("PIPELINE_EXHAUSTED")

        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)
        # Set window end so depth check doesn't trigger independent extension
        hm._execution_window_end_utc_ms = EPOCH_MS + 48 * BLOCK_DUR_MS

        hm.evaluate_once()

        # Gap persists
        assert store.get_entry_at(EPOCH_MS) is None

        # Not compliant
        assert hm.next_block_compliant is False

        # Last attempt is the fence-fill failure
        log = hm.extension_attempt_log
        assert len(log) >= 1
        last = log[-1]
        assert last.success is False
        assert last.error_code == "PIPELINE_EXHAUSTED"

        # Health report reflects non-compliance
        report = hm.get_health_report()
        assert report.next_block_compliant is False

    def test_tnb_004_locked_window_prevents_fill(self) -> None:
        """TNB-004: Store with locked_window_ms configured. Gap at now.
        HM also configured with locked_window_ms. evaluate_once() →
        gap persists, error contains LOCKED_IMMUTABLE, store entries
        unchanged.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(
            clock_fn=clock.now_utc_ms,
            locked_window_ms=LOCKED_WINDOW_MS,
        )

        # Pre-populate store with blocks starting at +1 block (gap at now)
        gap_entries = _make_entries(
            EPOCH_MS + BLOCK_DUR_MS,
            n_blocks=47,
            programming_day_date=date(2025, 2, 8),
        )
        store.add_entries(gap_entries)
        entries_before = store.get_all_entries()
        count_before = len(entries_before)

        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            locked_window_ms=LOCKED_WINDOW_MS,
        )
        # Set window end so depth check doesn't trigger independent extension
        hm._execution_window_end_utc_ms = EPOCH_MS + 48 * BLOCK_DUR_MS

        hm.evaluate_once()

        # Gap persists
        assert store.get_entry_at(EPOCH_MS) is None

        # Not compliant
        assert hm.next_block_compliant is False

        # Last attempt logged with locked-immutable error
        log = hm.extension_attempt_log
        assert len(log) >= 1
        last = log[-1]
        assert last.success is False
        assert "LOCKED-IMMUTABLE" in last.error_code

        # Store entries unchanged — no new entries added
        entries_after = store.get_all_entries()
        assert len(entries_after) == count_before
