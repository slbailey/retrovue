"""
Contract tests: INV-HORIZON-ATOMIC-PUBLISH-001.

Every execution horizon publish is atomic: assigns a monotonically increasing
generation_id, all entries in a publish range carry the same generation_id,
and readers never observe partial publishes.

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/horizon/INV-HORIZON-ATOMIC-PUBLISH-001.md
"""

from __future__ import annotations

from datetime import date

import pytest

from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)

# 2025-02-08T00:00:00Z
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000  # 30 minutes


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


def _populated_store(
    n_blocks: int,
    generation_id: int = 1,
) -> ExecutionWindowStore:
    """Create a store with n_blocks entries published at the given generation."""
    store = ExecutionWindowStore()
    entries = [_make_entry(i, generation_id=0) for i in range(n_blocks)]
    range_start = EPOCH_MS
    range_end = EPOCH_MS + n_blocks * BLOCK_DUR_MS
    result = store.publish_atomic_replace(
        range_start_ms=range_start,
        range_end_ms=range_end,
        new_entries=entries,
        generation_id=generation_id,
        reason_code="INITIAL_POPULATION",
    )
    assert result.ok, f"Initial population failed: {result.error_code}"
    return store


class TestInvHorizonAtomicPublish001:
    """INV-HORIZON-ATOMIC-PUBLISH-001 enforcement tests."""

    def test_thap_001_consumer_sees_complete_generation_after_publish(self) -> None:
        """THAP-001: Publish gen=2 over full range → all entries read as gen=2.

        After publishing 6 blocks at gen=1, re-publish the full range with
        6 new blocks at gen=2. A snapshot read of the full range must return
        all entries with generation_id=2 and none with generation_id=1.
        """
        store = _populated_store(6, generation_id=1)

        # Re-publish full range at gen=2
        new_entries = [_make_entry(i) for i in range(6)]
        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS,
            new_entries=new_entries,
            generation_id=2,
            reason_code="CLOCK_WATERMARK",
        )
        assert result.ok
        assert result.published_generation_id == 2

        # Read full range
        snap = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS,
        )
        assert snap.generation_id == 2
        assert len(snap.entries) == 6
        assert all(e.generation_id == 2 for e in snap.entries)

    def test_thap_002_non_overlapping_range_unaffected(self) -> None:
        """THAP-002: Entries outside publish range retain original generation_id.

        Publish 12 blocks at gen=1. Re-publish first 6 at gen=2.
        First-half snapshot → gen=2. Second-half snapshot → gen=1.
        """
        store = _populated_store(12, generation_id=1)

        # Re-publish first 6 blocks at gen=2
        new_entries = [_make_entry(i) for i in range(6)]
        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS,
            new_entries=new_entries,
            generation_id=2,
            reason_code="CLOCK_WATERMARK",
        )
        assert result.ok

        # First half → gen=2
        snap_r1 = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS,
        )
        assert snap_r1.generation_id == 2
        assert len(snap_r1.entries) == 6
        assert all(e.generation_id == 2 for e in snap_r1.entries)

        # Second half → gen=1 (untouched)
        snap_r2 = store.read_window_snapshot(
            EPOCH_MS + 6 * BLOCK_DUR_MS,
            EPOCH_MS + 12 * BLOCK_DUR_MS,
        )
        assert snap_r2.generation_id == 1
        assert len(snap_r2.entries) == 6
        assert all(e.generation_id == 1 for e in snap_r2.entries)

    def test_thap_003_snapshot_single_generation_monotonicity(self) -> None:
        """THAP-003: Sequential publishes maintain generation monotonicity.

        Publish gen=1, then gen=2 (CLOCK_WATERMARK). Each snapshot must
        show a single generation_id, and generation_ids must be monotonically
        increasing across publishes.
        """
        store = _populated_store(6, generation_id=1)

        # Verify gen=1 snapshot
        snap1 = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS,
        )
        assert snap1.generation_id == 1

        # Publish gen=2 over full range
        new_entries = [_make_entry(i) for i in range(6)]
        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS,
            new_entries=new_entries,
            generation_id=2,
            reason_code="CLOCK_WATERMARK",
        )
        assert result.ok

        snap2 = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS,
        )
        assert snap2.generation_id == 2

        # Monotonicity: gen2 > gen1
        assert snap2.generation_id > snap1.generation_id

        # Reject non-monotonic publish (gen=1 after gen=2)
        stale_entries = [_make_entry(i) for i in range(6)]
        result_bad = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 6 * BLOCK_DUR_MS,
            new_entries=stale_entries,
            generation_id=1,
            reason_code="STALE_ATTEMPT",
        )
        assert not result_bad.ok
        assert "INV-HORIZON-ATOMIC-PUBLISH-001-VIOLATED" in result_bad.error_code

        # Store unchanged after rejected publish
        snap3 = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 6 * BLOCK_DUR_MS,
        )
        assert snap3.generation_id == 2

    def test_thap_004_operator_override_partial_range(self) -> None:
        """THAP-004: Operator override of partial range is generation-consistent.

        Publish 12 blocks at gen=1. Override blocks 3-4 with gen=2
        (operator_override=True). Override entries carry gen=2 and
        is_operator_override=True. Surrounding entries retain gen=1.
        """
        store = _populated_store(12, generation_id=1)

        # Override blocks 3 and 4
        override_entries = [_make_entry(i) for i in range(3, 5)]
        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS + 3 * BLOCK_DUR_MS,
            range_end_ms=EPOCH_MS + 5 * BLOCK_DUR_MS,
            new_entries=override_entries,
            generation_id=2,
            reason_code="OPERATOR_OVERRIDE",
            operator_override=True,
        )
        assert result.ok
        assert result.published_generation_id == 2

        # Override range → gen=2, operator_override=True
        snap_override = store.read_window_snapshot(
            EPOCH_MS + 3 * BLOCK_DUR_MS,
            EPOCH_MS + 5 * BLOCK_DUR_MS,
        )
        assert snap_override.generation_id == 2
        assert len(snap_override.entries) == 2
        assert all(e.generation_id == 2 for e in snap_override.entries)
        assert all(e.is_operator_override for e in snap_override.entries)

        # Before override range → gen=1
        snap_before = store.read_window_snapshot(
            EPOCH_MS,
            EPOCH_MS + 3 * BLOCK_DUR_MS,
        )
        assert snap_before.generation_id == 1
        assert all(e.generation_id == 1 for e in snap_before.entries)
        assert not any(e.is_operator_override for e in snap_before.entries)

        # After override range → gen=1
        snap_after = store.read_window_snapshot(
            EPOCH_MS + 5 * BLOCK_DUR_MS,
            EPOCH_MS + 12 * BLOCK_DUR_MS,
        )
        assert snap_after.generation_id == 1
        assert all(e.generation_id == 1 for e in snap_after.entries)
