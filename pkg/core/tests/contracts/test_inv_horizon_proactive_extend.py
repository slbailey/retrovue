"""
Contract tests: INV-HORIZON-PROACTIVE-EXTEND-001.

HorizonManager proactively extends execution horizon when remaining depth
falls below proactive_extend_threshold_ms, even if the hard minimum
(min_execution_hours) is still satisfied.

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-PROACTIVE-EXTEND-001.md
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
)

# 2025-02-08T06:00:00Z  (programming day start)
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000              # 30 minutes
MIN_EXEC_HORIZON_MS = 7_200_000       # 2 hours (intentionally low for TPX tests)
PROACTIVE_THRESHOLD_MS = 10_800_000   # 3 hours (above min — triggers before min)
PROG_DAY_START_HOUR = 6
DAY_MS = 86_400_000
LOCKED_WINDOW_MS = 7_200_000          # 2 hours


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

    @property
    def call_count(self) -> int:
        return self._call_count

    def set_fail_on_next(self, error_code: str = "PIPELINE_EXHAUSTED") -> None:
        self._fail_on_next = True
        self._fail_error_code = error_code

    def extend_execution_day(self, broadcast_date: date) -> PipelineResult:
        self._call_count += 1
        if self._fail_on_next:
            self._fail_on_next = False
            raise PipelineError(self._fail_error_code)

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
    min_execution_hours: int = 2,
    proactive_extend_threshold_ms: int = 0,
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
        proactive_extend_threshold_ms=proactive_extend_threshold_ms,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestInvHorizonProactiveExtend001:
    """INV-HORIZON-PROACTIVE-EXTEND-001 enforcement tests."""

    def test_tpx_001_no_extension_when_above_threshold(self) -> None:
        """TPX-001: No proactive extension when remaining depth > threshold.

        Initialize horizon with 24h depth (one full broadcast day).
        Set threshold to 3h.  Advance clock so remaining = ~19h.
        evaluate_once() should NOT trigger proactive extension.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            min_execution_hours=2,
            proactive_extend_threshold_ms=PROACTIVE_THRESHOLD_MS,
        )

        # Initialize horizon — gets 24h of coverage
        hm.evaluate_once()
        window_end_after_init = hm.execution_window_end_utc_ms
        attempts_after_init = hm.extension_attempt_count

        # Advance clock by 5h — remaining = ~19h, well above 3h threshold
        clock.advance_ms(5 * 3_600_000)
        remaining = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert remaining > PROACTIVE_THRESHOLD_MS

        hm.evaluate_once()

        # No proactive extension triggered
        assert hm.proactive_extension_triggered is False
        assert hm.extension_attempt_count == attempts_after_init
        report = hm.get_health_report()
        assert report.proactive_extension_triggered is False

    def test_tpx_002_extension_when_crossing_threshold(self) -> None:
        """TPX-002: Proactive extension triggers when remaining <= threshold.

        Initialize horizon with 24h.  Set threshold to 3h.
        Advance clock so remaining < 3h.  evaluate_once() must
        trigger proactive extension — attempt count incremented,
        success count incremented, depth increased.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            min_execution_hours=2,
            proactive_extend_threshold_ms=PROACTIVE_THRESHOLD_MS,
        )

        # Initialize horizon — gets 24h of coverage
        hm.evaluate_once()
        window_end_after_init = hm.execution_window_end_utc_ms
        attempts_after_init = hm.extension_attempt_count
        successes_after_init = hm.extension_success_count

        # Advance clock so remaining < 3h threshold
        # remaining = window_end - now.  We want remaining <= PROACTIVE_THRESHOLD_MS
        advance = (window_end_after_init - EPOCH_MS) - PROACTIVE_THRESHOLD_MS + BLOCK_DUR_MS
        clock.advance_ms(advance)
        remaining = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert remaining <= PROACTIVE_THRESHOLD_MS
        # But still above min (2h)
        assert remaining >= MIN_EXEC_HORIZON_MS

        hm.evaluate_once()

        # Proactive extension triggered
        assert hm.proactive_extension_triggered is True
        assert hm.extension_attempt_count > attempts_after_init
        assert hm.extension_success_count > successes_after_init

        # Depth increased
        assert hm.execution_window_end_utc_ms > window_end_after_init

        # Health report reflects trigger
        report = hm.get_health_report()
        assert report.proactive_extension_triggered is True

    def test_tpx_003_fires_before_min_violation(self) -> None:
        """TPX-003: Proactive extension fires before min_execution_hours is breached.

        Set min_execution_hours=2h, proactive_threshold=3h.
        Advance clock so remaining = 2.5h (above min, below threshold).
        evaluate_once() must trigger proactive extension.
        The min-depth check (INV-HORIZON-EXECUTION-MIN-001) would NOT
        have triggered yet.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            min_execution_hours=2,
            proactive_extend_threshold_ms=PROACTIVE_THRESHOLD_MS,
        )

        # Initialize
        hm.evaluate_once()
        window_end = hm.execution_window_end_utc_ms

        # Advance so remaining = 2.5h (9_000_000 ms)
        target_remaining = 9_000_000  # 2.5 hours in ms
        advance = (window_end - EPOCH_MS) - target_remaining
        clock.advance_ms(advance)

        remaining = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        # Verify preconditions: above min, below threshold
        assert remaining > MIN_EXEC_HORIZON_MS, (
            f"remaining {remaining} should be > MIN {MIN_EXEC_HORIZON_MS}"
        )
        assert remaining <= PROACTIVE_THRESHOLD_MS, (
            f"remaining {remaining} should be <= threshold {PROACTIVE_THRESHOLD_MS}"
        )

        # Capture state before proactive evaluate
        attempts_before = hm.extension_attempt_count
        report_before = hm.get_health_report()
        # Min-depth is still compliant
        assert report_before.execution_compliant is True

        hm.evaluate_once()

        # Proactive extension triggered even though min wasn't violated
        assert hm.proactive_extension_triggered is True
        assert hm.extension_attempt_count > attempts_before
        assert hm.execution_window_end_utc_ms > window_end

    def test_tpx_004_pipeline_failure_during_proactive_extend(self) -> None:
        """TPX-004: Pipeline failure during proactive extension.

        Remaining below threshold, pipeline raises PipelineError.
        Extension attempt logged with success=False.
        proactive_extension_triggered=True (the attempt was made).
        Store not corrupted — coverage check still passes for
        pre-existing entries.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            min_execution_hours=2,
            proactive_extend_threshold_ms=PROACTIVE_THRESHOLD_MS,
        )

        # Initialize
        hm.evaluate_once()
        window_end = hm.execution_window_end_utc_ms
        entries_before = len(store.get_all_entries())

        # Advance so remaining < threshold
        advance = (window_end - EPOCH_MS) - PROACTIVE_THRESHOLD_MS + BLOCK_DUR_MS
        clock.advance_ms(advance)

        # Configure pipeline to fail
        pipeline.set_fail_on_next("PIPELINE_EXHAUSTED")
        attempts_before = hm.extension_attempt_count
        successes_before = hm.extension_success_count

        hm.evaluate_once()

        # Proactive extension was attempted
        assert hm.proactive_extension_triggered is True
        assert hm.extension_attempt_count > attempts_before

        # But it failed — success count unchanged from before the proactive attempt
        # (note: the min-depth extension might have also fired if remaining
        # dropped below min; we check the last attempt log entry)
        log = hm.extension_attempt_log
        # Find the last attempt — it should be the proactive one that failed
        last = log[-1]
        assert last.success is False
        assert last.error_code == "PIPELINE_EXHAUSTED"

        # Window end unchanged (no new coverage from failed attempt)
        assert hm.execution_window_end_utc_ms == window_end

        # Store not corrupted — coverage still valid for existing entries
        assert hm.coverage_compliant is True

    def test_tpx_005_idempotent_per_tick(self) -> None:
        """TPX-005: Calling evaluate_once() twice without clock advance
        produces only one proactive extension attempt.

        After the first call extends the horizon, remaining > threshold
        again, so the second call should not trigger proactive extension.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        pipeline = StubExecutionExtender()
        store = ExecutionWindowStore(clock_fn=clock.now_utc_ms)
        hm = _build_horizon_manager(
            clock,
            pipeline=pipeline,
            store=store,
            min_execution_hours=2,
            proactive_extend_threshold_ms=PROACTIVE_THRESHOLD_MS,
        )

        # Initialize
        hm.evaluate_once()
        window_end = hm.execution_window_end_utc_ms

        # Advance so remaining < threshold
        advance = (window_end - EPOCH_MS) - PROACTIVE_THRESHOLD_MS + BLOCK_DUR_MS
        clock.advance_ms(advance)

        # First evaluate — triggers proactive extension
        hm.evaluate_once()
        assert hm.proactive_extension_triggered is True
        attempts_after_first = hm.extension_attempt_count
        window_end_after_first = hm.execution_window_end_utc_ms

        # Horizon was extended — remaining should now be > threshold
        remaining = hm.execution_window_end_utc_ms - clock.now_utc_ms()
        assert remaining > PROACTIVE_THRESHOLD_MS

        # Second evaluate at same clock — no proactive extension
        hm.evaluate_once()
        assert hm.proactive_extension_triggered is False
        assert hm.extension_attempt_count == attempts_after_first
        assert hm.execution_window_end_utc_ms == window_end_after_first
