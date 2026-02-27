"""
Contract tests: INV-HORIZON-CONTINUOUS-COVERAGE-001.

All entries in ExecutionWindowStore ordered by start_utc_ms form a
contiguous, non-overlapping sequence.  For every adjacent pair,
E_i.end_utc_ms == E_{i+1}.start_utc_ms (integer equality).

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-CONTINUOUS-COVERAGE-001.md
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pytest

from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)
from retrovue.runtime.horizon_manager import (
    HorizonManager,
    SeamViolation,
)

# 2025-02-08T06:00:00Z  (programming day start)
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000       # 30 minutes
MIN_EXEC_HORIZON_MS = 21_600_000  # 6 hours
PROG_DAY_START_HOUR = 6
DAY_MS = 86_400_000


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
    contiguous BLOCK_DUR_MS blocks filling a full broadcast day.
    """

    def __init__(
        self,
        block_dur_ms: int = BLOCK_DUR_MS,
        day_start_hour: int = PROG_DAY_START_HOUR,
    ) -> None:
        self._block_dur_ms = block_dur_ms
        self._day_start_hour = day_start_hour

    def extend_execution_day(self, broadcast_date: date) -> PipelineResult:
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
    )


def _validate_seams(entries: list[ExecutionEntry]) -> list[tuple[str, str, int]]:
    """Manual seam check returning (left_id, right_id, delta_ms) for violations."""
    sorted_entries = sorted(entries, key=lambda e: e.start_utc_ms)
    violations = []
    for i in range(len(sorted_entries) - 1):
        left = sorted_entries[i]
        right = sorted_entries[i + 1]
        delta = right.start_utc_ms - left.end_utc_ms
        if delta != 0:
            violations.append((left.block_id, right.block_id, delta))
    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvHorizonContinuousCoverage001:
    """INV-HORIZON-CONTINUOUS-COVERAGE-001 enforcement tests."""

    def test_thcc_001_contiguous_boundaries_after_init(self) -> None:
        """THCC-001: Full horizon seam validation after init.
        All adjacent pairs contiguous, positive duration, no duplicate start_utc_ms.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)

        hm.evaluate_once()

        # Store must have entries
        entries = store.get_all_entries()
        assert len(entries) >= 12, f"Expected >= 12 blocks, got {len(entries)}"

        # All adjacent pairs must be contiguous (integer equality)
        for i in range(len(entries) - 1):
            left = entries[i]
            right = entries[i + 1]
            assert left.end_utc_ms == right.start_utc_ms, (
                f"Seam violation at index {i}: "
                f"{left.block_id} end={left.end_utc_ms} != "
                f"{right.block_id} start={right.start_utc_ms}"
            )

        # Every entry has positive duration
        for e in entries:
            assert e.end_utc_ms > e.start_utc_ms, (
                f"Non-positive duration: {e.block_id} "
                f"start={e.start_utc_ms} end={e.end_utc_ms}"
            )

        # No duplicate start_utc_ms
        starts = [e.start_utc_ms for e in entries]
        assert len(starts) == len(set(starts)), "Duplicate start_utc_ms found"

        # HorizonManager reports compliant
        assert hm.coverage_compliant is True
        assert hm.seam_violations == []
        report = hm.get_health_report()
        assert report.coverage_compliant is True

    def test_thcc_002_gap_detected_with_delta(self) -> None:
        """THCC-002: Inject a 1 ms gap between two blocks.
        Seam validation detects it with correct delta_ms=1.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)

        # Block A: [EPOCH, EPOCH + BLOCK_DUR)
        block_a = ExecutionEntry(
            block_id="block-A",
            block_index=0,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + BLOCK_DUR_MS,
            segments=[{"type": "content", "asset_id": "a0"}],
            channel_id="ch-test",
            programming_day_date=date(2025, 2, 8),
        )
        # Block B: 1ms gap — starts at end_A + 1
        block_b = ExecutionEntry(
            block_id="block-B",
            block_index=1,
            start_utc_ms=EPOCH_MS + BLOCK_DUR_MS + 1,
            end_utc_ms=EPOCH_MS + 2 * BLOCK_DUR_MS + 1,
            segments=[{"type": "content", "asset_id": "a1"}],
            channel_id="ch-test",
            programming_day_date=date(2025, 2, 8),
        )
        store.add_entries([block_a, block_b])

        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)
        # Set window end to avoid triggering extension
        hm._execution_window_end_utc_ms = EPOCH_MS + MIN_EXEC_HORIZON_MS + DAY_MS

        hm.evaluate_once()

        # Gap detected
        assert hm.coverage_compliant is False
        violations = hm.seam_violations
        assert len(violations) == 1

        v = violations[0]
        assert v.left_block_id == "block-A"
        assert v.right_block_id == "block-B"
        assert v.delta_ms == 1
        assert v.left_end_utc_ms == EPOCH_MS + BLOCK_DUR_MS
        assert v.right_start_utc_ms == EPOCH_MS + BLOCK_DUR_MS + 1

        report = hm.get_health_report()
        assert report.coverage_compliant is False

    def test_thcc_003_overlap_detected_with_delta(self) -> None:
        """THCC-003: Inject a 1 ms overlap between two blocks.
        Seam validation detects it with correct delta_ms=-1.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)

        # Block A: [EPOCH, EPOCH + BLOCK_DUR)
        block_a = ExecutionEntry(
            block_id="block-A",
            block_index=0,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + BLOCK_DUR_MS,
            segments=[{"type": "content", "asset_id": "a0"}],
            channel_id="ch-test",
            programming_day_date=date(2025, 2, 8),
        )
        # Block B: 1ms overlap — starts at end_A - 1
        block_b = ExecutionEntry(
            block_id="block-B",
            block_index=1,
            start_utc_ms=EPOCH_MS + BLOCK_DUR_MS - 1,
            end_utc_ms=EPOCH_MS + 2 * BLOCK_DUR_MS - 1,
            segments=[{"type": "content", "asset_id": "a1"}],
            channel_id="ch-test",
            programming_day_date=date(2025, 2, 8),
        )
        store.add_entries([block_a, block_b])

        pipeline = StubExecutionExtender()
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)
        hm._execution_window_end_utc_ms = EPOCH_MS + MIN_EXEC_HORIZON_MS + DAY_MS

        hm.evaluate_once()

        # Overlap detected
        assert hm.coverage_compliant is False
        violations = hm.seam_violations
        assert len(violations) == 1

        v = violations[0]
        assert v.left_block_id == "block-A"
        assert v.right_block_id == "block-B"
        assert v.delta_ms == -1
        assert v.left_end_utc_ms == EPOCH_MS + BLOCK_DUR_MS
        assert v.right_start_utc_ms == EPOCH_MS + BLOCK_DUR_MS - 1

        report = hm.get_health_report()
        assert report.coverage_compliant is False

    def test_thcc_004_contiguity_at_extension_join(self) -> None:
        """THCC-004: Horizon extends after clock advance.
        Seam between old and new blocks is contiguous.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)

        # Initialize horizon
        hm.evaluate_once()
        w1 = store.get_window_end()
        assert w1 > 0

        # Advance clock far enough to trigger extension
        # Coverage is 24h from programming day start.  MIN is 6h.
        # Advance to (coverage - slightly-under-MIN) to push depth below MIN.
        advance = (w1 - EPOCH_MS) - MIN_EXEC_HORIZON_MS + BLOCK_DUR_MS
        clock.advance_ms(advance)

        hm.evaluate_once()
        w2 = store.get_window_end()
        assert w2 > w1, f"Window did not extend: w2={w2} <= w1={w1}"

        # Validate all seams including the extension join
        entries = store.get_all_entries()
        for i in range(len(entries) - 1):
            left = entries[i]
            right = entries[i + 1]
            assert left.end_utc_ms == right.start_utc_ms, (
                f"Seam violation at index {i}: "
                f"{left.block_id} end={left.end_utc_ms} != "
                f"{right.block_id} start={right.start_utc_ms}"
            )

        # HorizonManager agrees
        assert hm.coverage_compliant is True
        assert hm.seam_violations == []

    def test_thcc_005_24h_walk_zero_violations(self) -> None:
        """THCC-005: Full 24-hour walk in BLOCK_DUR_MS steps.
        Validate contiguity at every evaluation cycle.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(clock, pipeline=pipeline, store=store)

        # Initialize
        hm.evaluate_once()

        for step in range(48):
            clock.advance_ms(BLOCK_DUR_MS)
            hm.evaluate_once()

            # Coverage must be compliant at every step
            assert hm.coverage_compliant is True, (
                f"Step {step}: coverage_compliant=False, "
                f"violations={hm.seam_violations}"
            )

            # Manual seam check on current snapshot
            now_ms = clock.now_utc_ms()
            end_ms = store.get_window_end()
            snap = store.read_window_snapshot(now_ms, end_ms)
            sorted_entries = sorted(snap.entries, key=lambda e: e.start_utc_ms)
            for i in range(len(sorted_entries) - 1):
                left = sorted_entries[i]
                right = sorted_entries[i + 1]
                assert left.end_utc_ms == right.start_utc_ms, (
                    f"Step {step}, seam {i}: "
                    f"{left.block_id} end={left.end_utc_ms} != "
                    f"{right.block_id} start={right.start_utc_ms}"
                )

        # Final health report
        report = hm.get_health_report()
        assert report.coverage_compliant is True
