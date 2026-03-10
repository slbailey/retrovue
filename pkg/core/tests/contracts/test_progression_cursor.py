"""Contract tests for Progression Cursor.

Validates all invariants defined in:
    docs/contracts/progression_cursor.md

Derived from: LAW-CONTENT-AUTHORITY, LAW-DERIVATION, LAW-IMMUTABILITY.

These tests call interfaces that do not yet exist (ProgressionCursor,
ScheduleBlockIdentity, advance_cursor, etc.). They are expected to fail
with ImportError until the implementation is provided.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from retrovue.runtime.progression_cursor import (
    PlanningFault,
    ProgressionCursor,
    ScheduleBlockIdentity,
    advance_cursor,
    derive_shuffle_seed,
    get_shuffle_order,
    initialize_cursor,
    select_random_asset,
)


# ---------------------------------------------------------------------------
# Fake helpers — no database, no real domain objects
# ---------------------------------------------------------------------------

POOL_ASSETS = ["asset-0", "asset-1", "asset-2", "asset-3", "asset-4"]
POOL_SIZE = len(POOL_ASSETS)


def _identity(
    channel_id: str = "ch-1",
    schedule_layer: str = "thursday",
    start_time: str = "20:00",
    program_ref: str = "sitcom_hour",
) -> ScheduleBlockIdentity:
    return ScheduleBlockIdentity(
        channel_id=channel_id,
        schedule_layer=schedule_layer,
        start_time=start_time,
        program_ref=program_ref,
    )


@dataclass
class FakeCursorStore:
    """In-memory cursor store simulating persistence."""

    _data: dict[tuple, ProgressionCursor] = field(default_factory=dict)

    def _key(self, identity: ScheduleBlockIdentity) -> tuple:
        return (
            identity.channel_id,
            identity.schedule_layer,
            identity.start_time,
            identity.program_ref,
        )

    def save(self, cursor: ProgressionCursor) -> None:
        self._data[self._key(cursor.identity)] = cursor

    def load(self, identity: ScheduleBlockIdentity) -> ProgressionCursor | None:
        return self._data.get(self._key(identity))

    def snapshot(self) -> dict[tuple, ProgressionCursor]:
        """Return a copy of persisted state for restart simulation."""
        return dict(self._data)

    @classmethod
    def from_snapshot(cls, snap: dict[tuple, ProgressionCursor]) -> FakeCursorStore:
        """Restore from a snapshot, simulating a restart."""
        store = cls()
        store._data = dict(snap)
        return store


EXECUTION_TS_MS = 1_735_689_600_000  # 2025-01-01T00:00:00Z


# ===========================================================================
# INV-CURSOR-001
# Sequential cursor must exist before asset selection
# ===========================================================================


@pytest.mark.contract
class TestInvCursor001:
    """INV-CURSOR-001"""

    # Tier: 2 | Scheduling logic invariant
    def test_sequential_cursor_required_before_selection(self):
        # INV-CURSOR-001 — sequential selection without resolved cursor → PlanningFault
        identity = _identity()

        with pytest.raises(PlanningFault):
            advance_cursor(
                cursor=None,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )

    # Tier: 2 | Scheduling logic invariant
    def test_sequential_cursor_loaded_before_selection(self):
        # INV-CURSOR-001 — sequential selection with loaded cursor proceeds
        identity = _identity()
        cursor = initialize_cursor(identity)

        result = advance_cursor(
            cursor=cursor,
            pool_assets=POOL_ASSETS,
            progression="sequential",
        )

        assert result.selected_asset is not None


# ===========================================================================
# INV-CURSOR-002
# Cursor must advance exactly one position per execution
# ===========================================================================


@pytest.mark.contract
class TestInvCursor002:
    """INV-CURSOR-002"""

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_advances_one_position(self):
        # INV-CURSOR-002 — single execution: position 0 → 1
        identity = _identity()
        cursor = initialize_cursor(identity)
        assert cursor.position == 0

        result = advance_cursor(
            cursor=cursor,
            pool_assets=POOL_ASSETS,
            progression="sequential",
        )

        assert result.cursor.position == 1

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_advances_once_per_execution(self):
        # INV-CURSOR-002 — two executions: position 0 → 1 → 2
        identity = _identity()
        cursor = initialize_cursor(identity)

        r1 = advance_cursor(
            cursor=cursor,
            pool_assets=POOL_ASSETS,
            progression="sequential",
        )
        assert r1.cursor.position == 1

        r2 = advance_cursor(
            cursor=r1.cursor,
            pool_assets=POOL_ASSETS,
            progression="sequential",
        )
        assert r2.cursor.position == 2

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_does_not_skip(self):
        # INV-CURSOR-002 — 3 executions from 0 yields position exactly 3
        identity = _identity()
        cursor = initialize_cursor(identity)

        for _ in range(3):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )
            cursor = result.cursor

        assert cursor.position == 3


# ===========================================================================
# INV-CURSOR-003
# Cursor must wrap at pool boundary
# ===========================================================================


@pytest.mark.contract
class TestInvCursor003:
    """INV-CURSOR-003"""

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_wraps_at_pool_size(self):
        # INV-CURSOR-003 — after POOL_SIZE advances, position wraps to 0
        identity = _identity()
        cursor = initialize_cursor(identity)

        for _ in range(POOL_SIZE):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )
            cursor = result.cursor

        assert cursor.position == 0

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_increments_cycle_on_wrap(self):
        # INV-CURSOR-003 — cycle increments by 1 on wrap
        identity = _identity()
        cursor = initialize_cursor(identity)
        assert cursor.cycle == 0

        for _ in range(POOL_SIZE):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )
            cursor = result.cursor

        assert cursor.cycle == 1


# ===========================================================================
# INV-CURSOR-004
# Shuffle order must remain stable within a cycle
# ===========================================================================


@pytest.mark.contract
class TestInvCursor004:
    """INV-CURSOR-004"""

    # Tier: 2 | Scheduling logic invariant
    def test_shuffle_order_stable_within_cycle(self):
        # INV-CURSOR-004 — same seed and cycle produce same order
        identity = _identity()
        seed = derive_shuffle_seed(identity, cycle=0)

        order_a = get_shuffle_order(POOL_ASSETS, seed)
        order_b = get_shuffle_order(POOL_ASSETS, seed)

        assert order_a == order_b

    # Tier: 2 | Scheduling logic invariant
    def test_shuffle_order_not_regenerated_mid_cycle(self):
        # INV-CURSOR-004 — advancing within a cycle does not change order
        identity = _identity()
        cursor = initialize_cursor(identity, mode="shuffle")
        seed = cursor.shuffle_seed

        order_before = get_shuffle_order(POOL_ASSETS, seed)

        # Advance twice within the cycle (pool has 5 elements)
        for _ in range(2):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="shuffle",
            )
            cursor = result.cursor

        # Seed must not have changed mid-cycle
        assert cursor.shuffle_seed == seed
        order_after = get_shuffle_order(POOL_ASSETS, cursor.shuffle_seed)
        assert order_before == order_after


# ===========================================================================
# INV-CURSOR-005
# Shuffle must reshuffle on cycle boundary
# ===========================================================================


@pytest.mark.contract
class TestInvCursor005:
    """INV-CURSOR-005"""

    # Tier: 2 | Scheduling logic invariant
    def test_shuffle_reshuffles_on_new_cycle(self):
        # INV-CURSOR-005 — new cycle produces different ordering (pool > 1 element)
        identity = _identity()
        cursor = initialize_cursor(identity, mode="shuffle")
        seed_cycle_0 = cursor.shuffle_seed
        order_cycle_0 = get_shuffle_order(POOL_ASSETS, seed_cycle_0)

        # Exhaust the full cycle
        for _ in range(POOL_SIZE):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="shuffle",
            )
            cursor = result.cursor

        # Now in cycle 1
        assert cursor.cycle == 1
        order_cycle_1 = get_shuffle_order(POOL_ASSETS, cursor.shuffle_seed)

        assert order_cycle_0 != order_cycle_1

    # Tier: 2 | Scheduling logic invariant
    def test_shuffle_new_cycle_different_seed(self):
        # INV-CURSOR-005 — consecutive cycle seeds differ
        identity = _identity()

        seed_0 = derive_shuffle_seed(identity, cycle=0)
        seed_1 = derive_shuffle_seed(identity, cycle=1)

        assert seed_0 != seed_1


# ===========================================================================
# INV-CURSOR-006
# Cursor state must persist across scheduler restarts
# ===========================================================================


@pytest.mark.contract
class TestInvCursor006:
    """INV-CURSOR-006"""

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_survives_restart(self):
        # INV-CURSOR-006 — persisted cursor loaded after simulated restart
        store = FakeCursorStore()
        identity = _identity()
        cursor = initialize_cursor(identity)

        # Advance 3 times and persist
        for _ in range(3):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )
            cursor = result.cursor
        store.save(cursor)

        # Simulate restart: new store from snapshot
        snapshot = store.snapshot()
        restored_store = FakeCursorStore.from_snapshot(snapshot)
        loaded = restored_store.load(identity)

        assert loaded is not None
        assert loaded.position == cursor.position
        assert loaded.cycle == cursor.cycle

    # Tier: 2 | Scheduling logic invariant
    def test_restart_does_not_reset_position(self):
        # INV-CURSOR-006 — position after restart equals position before restart
        store = FakeCursorStore()
        identity = _identity()
        cursor = initialize_cursor(identity)

        # Advance to position 3
        for _ in range(3):
            result = advance_cursor(
                cursor=cursor,
                pool_assets=POOL_ASSETS,
                progression="sequential",
            )
            cursor = result.cursor
        store.save(cursor)
        position_before = cursor.position

        # Simulate restart
        snapshot = store.snapshot()
        new_store = FakeCursorStore.from_snapshot(snapshot)
        loaded = new_store.load(identity)

        assert loaded is not None
        assert loaded.position == position_before
        assert loaded.position != 0


# ===========================================================================
# INV-CURSOR-007
# Random progression must not depend on cursor state
# ===========================================================================


@pytest.mark.contract
class TestInvCursor007:
    """INV-CURSOR-007"""

    # Tier: 2 | Scheduling logic invariant
    def test_random_ignores_cursor_state(self):
        # INV-CURSOR-007 — random selection unchanged by cursor presence
        identity = _identity()

        # Select with no cursor
        asset_no_cursor = select_random_asset(
            identity=identity,
            pool_assets=POOL_ASSETS,
            execution_ts_ms=EXECUTION_TS_MS,
            cursor=None,
        )

        # Select with a stale cursor at position 3
        stale_cursor = ProgressionCursor(
            identity=identity, position=3, cycle=1, shuffle_seed=None,
        )
        asset_with_cursor = select_random_asset(
            identity=identity,
            pool_assets=POOL_ASSETS,
            execution_ts_ms=EXECUTION_TS_MS,
            cursor=stale_cursor,
        )

        assert asset_no_cursor == asset_with_cursor

    # Tier: 2 | Scheduling logic invariant
    def test_random_selection_without_cursor(self):
        # INV-CURSOR-007 — random selection succeeds with no persisted cursor
        identity = _identity()

        asset = select_random_asset(
            identity=identity,
            pool_assets=POOL_ASSETS,
            execution_ts_ms=EXECUTION_TS_MS,
            cursor=None,
        )

        assert asset in POOL_ASSETS


# ===========================================================================
# INV-CURSOR-008
# Cursor initialization must be deterministic
# ===========================================================================


@pytest.mark.contract
class TestInvCursor008:
    """INV-CURSOR-008"""

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_initializes_at_zero(self):
        # INV-CURSOR-008 — new cursor has position=0, cycle=0
        identity = _identity()
        cursor = initialize_cursor(identity)

        assert cursor.position == 0
        assert cursor.cycle == 0

    # Tier: 2 | Scheduling logic invariant
    def test_cursor_initialization_deterministic(self):
        # INV-CURSOR-008 — two independent initializations produce identical state
        identity = _identity()

        cursor_a = initialize_cursor(identity)
        cursor_b = initialize_cursor(identity)

        assert cursor_a.position == cursor_b.position
        assert cursor_a.cycle == cursor_b.cycle
        assert cursor_a.shuffle_seed == cursor_b.shuffle_seed
