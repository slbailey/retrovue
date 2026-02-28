"""
Contract tests: INV-HORIZON-LOCKED-IMMUTABLE-001.

Execution data within the locked window [now, now + locked_window_ms) is
immutable.  publish_atomic_replace() MUST reject any publish overlapping
the locked window unless operator_override=True.

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-LOCKED-IMMUTABLE-001.md
"""

from __future__ import annotations

import threading
from datetime import date

import pytest

from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)

# 2025-02-08T00:00:00Z
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000  # 30 minutes
LOCKED_WINDOW_MS = 7_200_000  # 2 hours


class FakeClock:
    """Minimal deterministic clock for locked-window tests."""

    def __init__(self, start_ms: int = EPOCH_MS) -> None:
        self._ms = start_ms
        self._lock = threading.Lock()

    def now_utc_ms(self) -> int:
        with self._lock:
            return self._ms

    def advance_ms(self, delta: int) -> None:
        with self._lock:
            self._ms += delta


def _make_entry(index: int, *, generation_id: int = 0) -> ExecutionEntry:
    """Create an ExecutionEntry at EPOCH_MS + index * BLOCK_DUR_MS."""
    return ExecutionEntry(
        block_id=f"block-{index:04d}",
        block_index=index,
        start_utc_ms=EPOCH_MS + index * BLOCK_DUR_MS,
        end_utc_ms=EPOCH_MS + (index + 1) * BLOCK_DUR_MS,
        segments=[{"type": "content", "asset_id": f"asset-{index}"}],
        channel_id="ch-test",
        programming_day_date=date(2025, 2, 8),
        generation_id=generation_id,
    )


def _populate_store(
    clock: FakeClock,
    n_blocks: int = 12,
    generation_id: int = 1,
) -> ExecutionWindowStore:
    """Create a store with locked-window enforcement and n_blocks entries."""
    store = ExecutionWindowStore(
        clock_fn=clock.now_utc_ms,
        locked_window_ms=LOCKED_WINDOW_MS,
    )
    entries = [_make_entry(i, generation_id=0) for i in range(n_blocks)]
    range_start = EPOCH_MS
    range_end = EPOCH_MS + n_blocks * BLOCK_DUR_MS
    # Initial population: clock is at EPOCH_MS, so locked window starts
    # at EPOCH_MS.  Use operator_override=True to seed the store.
    result = store.publish_atomic_replace(
        range_start_ms=range_start,
        range_end_ms=range_end,
        new_entries=entries,
        generation_id=generation_id,
        reason_code="INITIAL_POPULATION",
        operator_override=True,
    )
    assert result.ok, f"Initial population failed: {result.error_code}"
    return store


class TestInvHorizonLockedImmutable001:
    """INV-HORIZON-LOCKED-IMMUTABLE-001 enforcement tests."""

    def test_thli_001_publish_inside_locked_window_rejected(self) -> None:
        """THLI-001: publish_atomic_replace overlapping locked window
        without operator_override returns ok=False.

        Clock at EPOCH_MS.  Locked window = [EPOCH_MS, EPOCH_MS + 2h).
        Attempt to replace block 0 (inside locked window) with
        operator_override=False.  Must be rejected.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = _populate_store(clock, n_blocks=12, generation_id=1)

        # Precondition: block 0 is inside locked window
        locked_end = ExecutionWindowStore._locked_window_end_ms(
            clock.now_utc_ms(), LOCKED_WINDOW_MS,
        )
        assert EPOCH_MS + BLOCK_DUR_MS <= locked_end

        # Attempt automated replace inside locked window
        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + BLOCK_DUR_MS,
            new_entries=[_make_entry(0)],
            generation_id=2,
            reason_code="REASON_TIME_THRESHOLD",
            operator_override=False,
        )
        assert not result.ok
        assert "INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result.error_code

        # Store unchanged
        snap = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + BLOCK_DUR_MS)
        assert snap.generation_id == 1
        assert all(e.generation_id == 1 for e in snap.entries)

    def test_thli_002_automated_publish_locked_window_rejected(self) -> None:
        """THLI-002: Automated process publish overlapping the locked window
        is rejected — multi-block range spanning into locked window.

        Clock at EPOCH_MS.  Locked window = [EPOCH_MS, EPOCH_MS + 2h).
        Attempt to replace blocks 0-3 (2h range, fully inside locked window)
        with operator_override=False.  Must be rejected.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = _populate_store(clock, n_blocks=12, generation_id=1)

        locked_end = ExecutionWindowStore._locked_window_end_ms(
            clock.now_utc_ms(), LOCKED_WINDOW_MS,
        )
        # Precondition: blocks 0-3 end at EPOCH_MS + 4*30min = EPOCH_MS + 2h
        assert EPOCH_MS + 4 * BLOCK_DUR_MS <= locked_end

        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 4 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(4)],
            generation_id=2,
            reason_code="AUTOMATED_REGEN",
            operator_override=False,
        )
        assert not result.ok
        assert "INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result.error_code

        # All original entries preserved
        snap = store.read_window_snapshot(EPOCH_MS, EPOCH_MS + 4 * BLOCK_DUR_MS)
        assert snap.generation_id == 1

    def test_thli_003_operator_override_replaces_locked_block(self) -> None:
        """THLI-003: Operator override replaces locked-window blocks
        atomically with a new generation_id.

        Clock at EPOCH_MS.  Locked window = [EPOCH_MS, EPOCH_MS + 2h).
        Replace blocks 0-1 with operator_override=True.  Must succeed
        with new generation_id=2.  Surrounding blocks retain gen=1.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = _populate_store(clock, n_blocks=12, generation_id=1)

        locked_end = ExecutionWindowStore._locked_window_end_ms(
            clock.now_utc_ms(), LOCKED_WINDOW_MS,
        )
        assert EPOCH_MS + 2 * BLOCK_DUR_MS <= locked_end

        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 2 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(2)],
            generation_id=2,
            reason_code="OPERATOR_OVERRIDE",
            operator_override=True,
        )
        assert result.ok
        assert result.published_generation_id == 2

        # Replaced range → gen=2
        snap_replaced = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 2 * BLOCK_DUR_MS,
        )
        assert snap_replaced.generation_id == 2
        assert all(e.generation_id == 2 for e in snap_replaced.entries)

        # Untouched range → gen=1
        snap_rest = store.read_window_snapshot(
            EPOCH_MS + 2 * BLOCK_DUR_MS,
            EPOCH_MS + 12 * BLOCK_DUR_MS,
        )
        assert snap_rest.generation_id == 1
        assert all(e.generation_id == 1 for e in snap_rest.entries)

    def test_thli_004_publish_beyond_locked_window_accepted(self) -> None:
        """THLI-004: Publish targeting only the flexible future (beyond
        locked window) succeeds without operator_override.

        Clock at EPOCH_MS.  Locked window ends at EPOCH_MS + 2h.
        Replace blocks 4-5 (starting at 2h, outside locked window)
        with operator_override=False.  Must succeed.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = _populate_store(clock, n_blocks=12, generation_id=1)

        locked_end = ExecutionWindowStore._locked_window_end_ms(
            clock.now_utc_ms(), LOCKED_WINDOW_MS,
        )
        # Precondition: blocks 4-5 start at EPOCH_MS + 4*30min = EPOCH_MS + 2h
        flexible_start = EPOCH_MS + 4 * BLOCK_DUR_MS
        assert flexible_start >= locked_end

        result = store.publish_atomic_replace(
            range_start_ms=flexible_start,
            range_end_ms=flexible_start + 2 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(4, 6)],
            generation_id=2,
            reason_code="REASON_TIME_THRESHOLD",
            operator_override=False,
        )
        assert result.ok
        assert result.published_generation_id == 2

        # Flexible-future range → gen=2
        snap = store.read_window_snapshot(
            flexible_start, flexible_start + 2 * BLOCK_DUR_MS,
        )
        assert snap.generation_id == 2
        assert all(e.generation_id == 2 for e in snap.entries)

    def test_thli_005_clock_advance_moves_lock_boundary(self) -> None:
        """THLI-005: Clock advance moves the lock boundary; a previously-
        flexible entry becomes locked and rejects mutation.

        Clock at EPOCH_MS.  Locked window = [EPOCH_MS, EPOCH_MS + 2h).
        Blocks 4-5 (at 2h) are in the flexible future → publish succeeds.
        Advance clock by 1h.  Now locked window = [EPOCH_MS + 1h, EPOCH_MS + 3h).
        Blocks 4-5 (at 2h) are now inside locked window → publish rejected.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        store = _populate_store(clock, n_blocks=12, generation_id=1)

        flexible_start = EPOCH_MS + 4 * BLOCK_DUR_MS  # 2h from epoch

        # Phase 1: publish in flexible future succeeds
        result_1 = store.publish_atomic_replace(
            range_start_ms=flexible_start,
            range_end_ms=flexible_start + 2 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(4, 6)],
            generation_id=2,
            reason_code="REASON_TIME_THRESHOLD",
            operator_override=False,
        )
        assert result_1.ok

        # Advance clock by 1h (2 blocks)
        clock.advance_ms(2 * BLOCK_DUR_MS)
        now_after = clock.now_utc_ms()
        locked_end_after = ExecutionWindowStore._locked_window_end_ms(
            now_after, LOCKED_WINDOW_MS,
        )
        # Postcondition: block 4 start (2h) is now inside locked window
        # (locked window = [1h, 3h))
        assert flexible_start < locked_end_after
        assert locked_end_after > EPOCH_MS + LOCKED_WINDOW_MS  # boundary moved

        # Phase 2: same range now rejected
        result_2 = store.publish_atomic_replace(
            range_start_ms=flexible_start,
            range_end_ms=flexible_start + 2 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(4, 6)],
            generation_id=3,
            reason_code="REASON_TIME_THRESHOLD",
            operator_override=False,
        )
        assert not result_2.ok
        assert "INV-HORIZON-LOCKED-IMMUTABLE-001-VIOLATED" in result_2.error_code
