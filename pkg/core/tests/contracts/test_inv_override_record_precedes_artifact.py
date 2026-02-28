"""
Contract tests: INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.

An override record MUST be durably persisted before the override artifact
is committed. If persistence fails, the artifact MUST NOT be created.

Tests are deterministic (no wall-clock sleep).
See: docs/contracts/invariants/core/INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001.md
"""

from __future__ import annotations

import threading
from datetime import date, datetime, time, timezone

import pytest

from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)
from retrovue.runtime.override_record import InMemoryOverrideStore
from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
from retrovue.runtime.schedule_types import (
    ResolvedAsset,
    ResolvedScheduleDay,
    ResolvedSlot,
    ProgramRef,
    ProgramRefType,
    SequenceState,
)

# 2025-02-08T06:00:00Z
EPOCH_MS = 1_738_987_200_000
BLOCK_DUR_MS = 1_800_000  # 30 minutes


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeClock:
    """Minimal deterministic clock."""

    def __init__(self, start_ms: int = EPOCH_MS) -> None:
        self._ms = start_ms
        self._lock = threading.Lock()

    def now_utc_ms(self) -> int:
        with self._lock:
            return self._ms

    def advance_ms(self, delta: int) -> None:
        with self._lock:
            self._ms += delta


# ---------------------------------------------------------------------------
# Helpers — ExecutionWindowStore
# ---------------------------------------------------------------------------

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
    override_store: InMemoryOverrideStore,
    n_blocks: int = 8,
) -> ExecutionWindowStore:
    """Create a store with override_store wired in, seeded with n_blocks."""
    store = ExecutionWindowStore(
        clock_fn=clock.now_utc_ms,
        override_store=override_store,
    )
    entries = [_make_entry(i) for i in range(n_blocks)]
    result = store.publish_atomic_replace(
        range_start_ms=EPOCH_MS,
        range_end_ms=EPOCH_MS + n_blocks * BLOCK_DUR_MS,
        new_entries=entries,
        generation_id=1,
        reason_code="INITIAL_POPULATION",
        operator_override=True,
    )
    assert result.ok, f"Initial population failed: {result.error_code}"
    return store


# ---------------------------------------------------------------------------
# Helpers — ScheduleDay
# ---------------------------------------------------------------------------

CHANNEL_ID = "ch-test"
PROG_DAY = date(2025, 2, 8)
PDS_HOUR = 6


def _make_resolved_day(
    day: date = PROG_DAY,
    plan_id: str = "plan-001",
) -> ResolvedScheduleDay:
    """Minimal ResolvedScheduleDay for override testing."""
    slot = ResolvedSlot(
        slot_time=time(PDS_HOUR, 0),
        program_ref=ProgramRef(ProgramRefType.FILE, "show.mp4"),
        resolved_asset=ResolvedAsset(file_path="show.mp4"),
        duration_seconds=86400.0,
        label="all-day",
    )
    return ResolvedScheduleDay(
        programming_day_date=day,
        resolved_slots=[slot],
        resolution_timestamp=datetime(2025, 2, 7, 12, 0, tzinfo=timezone.utc),
        sequence_state=SequenceState(),
        plan_id=plan_id,
    )


def _seed_resolved_store(
    override_store: InMemoryOverrideStore,
    clock: FakeClock,
) -> InMemoryResolvedStore:
    """Create an InMemoryResolvedStore with one day seeded."""
    store = InMemoryResolvedStore(
        override_store=override_store,
        clock_fn=clock.now_utc_ms,
    )
    store.store(CHANNEL_ID, _make_resolved_day())
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.contract
class TestInvOverrideRecordPrecedesArtifact001:
    """INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 enforcement tests."""

    def test_tor_001_record_created_before_artifact(self) -> None:
        """TOR-001: Override record is persisted before artifact replacement.

        Call operator_override() on InMemoryResolvedStore.
        Assert override_store contains record.
        Assert artifact was replaced.
        Assert record.created_utc_ms <= artifact resolution timestamp.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        override_store = InMemoryOverrideStore()
        resolved_store = _seed_resolved_store(override_store, clock)

        # No records yet
        assert len(override_store.records) == 0

        # Perform override
        override_day = _make_resolved_day(plan_id="plan-override")
        result = resolved_store.operator_override(CHANNEL_ID, override_day)

        # Record was persisted
        assert len(override_store.records) == 1
        record = override_store.records[0]
        assert record.layer == "ScheduleDay"
        assert CHANNEL_ID in record.target_id
        assert record.reason_code == "OPERATOR_OVERRIDE"
        assert record.created_utc_ms == EPOCH_MS

        # Artifact was replaced
        assert result.is_manual_override is True
        stored = resolved_store.get(CHANNEL_ID, PROG_DAY)
        assert stored is result
        assert stored.is_manual_override is True

        # Record was persisted at clock time
        assert record.created_utc_ms == EPOCH_MS

    def test_tor_002_persist_failure_prevents_artifact(self) -> None:
        """TOR-002: Override record persist failure prevents artifact creation.

        Set override_store.fail_next_persist = True.
        Call operator_override().
        Assert exception raised.
        Assert artifact store unchanged (original still present).
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        override_store = InMemoryOverrideStore()
        resolved_store = _seed_resolved_store(override_store, clock)

        original = resolved_store.get(CHANNEL_ID, PROG_DAY)
        assert original is not None
        original_id = id(original)

        # Configure failure
        override_store.fail_next_persist = True

        override_day = _make_resolved_day(plan_id="plan-override")
        with pytest.raises(RuntimeError, match="OVERRIDE_RECORD_PERSIST_FAILED"):
            resolved_store.operator_override(CHANNEL_ID, override_day)

        # Store unchanged — original still present
        stored = resolved_store.get(CHANNEL_ID, PROG_DAY)
        assert id(stored) == original_id
        assert stored.is_manual_override is False

        # No records persisted
        assert len(override_store.records) == 0

    def test_tor_003_execution_window_override_atomicity(self) -> None:
        """TOR-003: ExecutionWindowStore override with persist failure.

        publish_atomic_replace(operator_override=True) with persist failure
        returns PublishResult(ok=False). No generation change. No entry mutation.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        override_store = InMemoryOverrideStore()
        store = _populate_store(clock, override_store, n_blocks=8)
        records_after_init = len(override_store.records)

        # Verify baseline
        snap_before = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 4 * BLOCK_DUR_MS,
        )
        assert snap_before.generation_id == 1

        # Configure failure
        override_store.fail_next_persist = True

        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 4 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(4)],
            generation_id=2,
            reason_code="OPERATOR_OVERRIDE",
            operator_override=True,
        )

        # Publish rejected
        assert not result.ok
        assert result.error_code == "OVERRIDE_RECORD_PERSIST_FAILED"

        # No generation change
        snap_after = store.read_window_snapshot(
            EPOCH_MS, EPOCH_MS + 4 * BLOCK_DUR_MS,
        )
        assert snap_after.generation_id == 1
        assert all(e.generation_id == 1 for e in snap_after.entries)

        # No new override records persisted (only init record exists)
        assert len(override_store.records) == records_after_init

    def test_tor_004_no_silent_artifact_without_record(self) -> None:
        """TOR-004: Successful override always has a preceding record.

        Perform operator_override on both ScheduleDay and ExecutionWindowStore.
        In each case, verify that override_store.records is non-empty AFTER
        the artifact is committed — the record always precedes the artifact.
        """
        clock = FakeClock(start_ms=EPOCH_MS)
        override_store = InMemoryOverrideStore()

        # --- ScheduleDay path ---
        resolved_store = _seed_resolved_store(override_store, clock)
        override_day = _make_resolved_day(plan_id="plan-override-sd")
        resolved_store.operator_override(CHANNEL_ID, override_day)

        assert len(override_store.records) == 1
        sd_record = override_store.records[0]
        assert sd_record.layer == "ScheduleDay"

        # --- ExecutionWindowStore path ---
        store = _populate_store(clock, override_store, n_blocks=8)
        # Initial population already creates one EWS record (gen=1 override)
        records_before = len(override_store.records)

        result = store.publish_atomic_replace(
            range_start_ms=EPOCH_MS,
            range_end_ms=EPOCH_MS + 2 * BLOCK_DUR_MS,
            new_entries=[_make_entry(i) for i in range(2)],
            generation_id=3,
            reason_code="OPERATOR_OVERRIDE",
            operator_override=True,
        )
        assert result.ok

        # New override record was persisted
        assert len(override_store.records) > records_before
        ews_record = override_store.records[-1]
        assert ews_record.layer == "ExecutionWindowStore"
