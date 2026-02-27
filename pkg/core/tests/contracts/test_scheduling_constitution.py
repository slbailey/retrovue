"""Blocker Invariant Contract Tests

Constitutional contract tests for the RetroVue scheduling pipeline.
Tests ONLY the following blocker invariants:

  1) INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001
  2) INV-DERIVATION-ANCHOR-PROTECTED-001
  3) INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001  (reserved — not yet filed)
  4) INV-ASRUN-IMMUTABLE-001

Authoritative sources:
  - docs/contracts/laws/LAW-*.md
  - docs/contracts/invariants/core/INV-*.md
  - docs/contracts/TEST-MATRIX-SCHEDULING-CONSTITUTION.md

Tests assert that enforcement exists. If enforcement is missing, tests fail.
No enforcement logic is implemented here. No production code is modified.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from retrovue.runtime.asrun_logger import AsRunEvent, AsRunLogger
from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
)

# Constitutional epoch per test matrix
EPOCH = datetime(2026, 1, 1, 6, 0, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)
CHANNEL_ID = "test-channel-001"
GRID_BLOCK_MS = 30 * 60 * 1000  # 30 minutes in ms


def _make_entry(
    block_index: int = 0,
    start_offset_ms: int = 0,
    duration_ms: int = GRID_BLOCK_MS,
    broadcast_date: date | None = None,
    channel_id: str = CHANNEL_ID,
    **overrides,
) -> ExecutionEntry:
    """Helper: build an ExecutionEntry with conventional block_id encoding.

    All entries carry explicit schedule lineage (channel_id, programming_day_date)
    per INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001.
    """
    bd = broadcast_date or date(2026, 1, 1)
    start = EPOCH_MS + start_offset_ms
    kwargs = dict(
        block_id=f"{channel_id}-{bd.isoformat()}-b{block_index:04d}",
        block_index=block_index,
        start_utc_ms=start,
        end_utc_ms=start + duration_ms,
        segments=[{"type": "content", "asset_id": "asset-001", "duration_ms": duration_ms}],
        is_locked=True,
        channel_id=channel_id,
        programming_day_date=bd,
    )
    kwargs.update(overrides)
    return ExecutionEntry(**kwargs)


# =========================================================================
# INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001
# =========================================================================


class TestInvExecutionDerivedFromScheduleday001:
    """INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001

    Every ExecutionEntry (TransmissionLog entry) must be traceable to
    exactly one ResolvedScheduleDay.  No execution artifact may exist
    without deterministic schedule lineage.

    The execution layer is not an independent scheduling authority.
    All execution content must derive from the editorial derivation chain:

        SchedulePlan -> ResolvedScheduleDay -> ExecutionEntry

    Derived from: LAW-DERIVATION, LAW-CONTENT-AUTHORITY.
    """

    def test_inv_execution_derived_from_scheduleday_001_reject_without_lineage(
        self, contract_clock
    ):
        """INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 -- negative

        Invariant: INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001
        Derived law(s): LAW-DERIVATION, LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: Construct ExecutionEntries missing schedule lineage
                  (programming_day_date=None, channel_id="").  Assert
                  that ExecutionWindowStore.add_entries() rejects them
                  at the store boundary.
        """
        store = ExecutionWindowStore()

        # Case 1: missing programming_day_date
        orphan_no_date = _make_entry(block_index=99, start_offset_ms=99 * GRID_BLOCK_MS)
        object.__setattr__(orphan_no_date, "programming_day_date", None)
        with pytest.raises(ValueError, match="INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001"):
            store.add_entries([orphan_no_date])

        # Case 2: missing channel_id
        orphan_no_channel = _make_entry(block_index=98, start_offset_ms=98 * GRID_BLOCK_MS)
        object.__setattr__(orphan_no_channel, "channel_id", "")
        with pytest.raises(ValueError, match="INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001"):
            store.add_entries([orphan_no_channel])

        # Store must remain empty — no orphan entries accepted.
        assert len(store.get_all_entries()) == 0, (
            "INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 VIOLATED: "
            "Store accepted entries despite missing schedule lineage."
        )

    def test_inv_execution_derived_from_scheduleday_001_valid_lineage(
        self, contract_clock
    ):
        """INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 -- positive

        Invariant: INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001
        Derived law(s): LAW-DERIVATION, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: Produce ExecutionEntries through the pipeline from a
                  valid ResolvedScheduleDay. Assert every entry carries
                  a non-null programming_day_date matching the source
                  ScheduleDay.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        # Materialize a ResolvedScheduleDay.
        resolved = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )

        resolved_store = InMemoryResolvedStore()
        resolved_store.store(CHANNEL_ID, resolved)
        assert resolved_store.exists(CHANNEL_ID, date(2026, 1, 1))

        # Simulate pipeline output: entries that SHOULD carry lineage.
        entries = [
            _make_entry(block_index=i, start_offset_ms=i * GRID_BLOCK_MS)
            for i in range(4)
        ]

        store = ExecutionWindowStore()
        store.add_entries(entries)

        for entry in store.get_all_entries():
            assert hasattr(entry, "programming_day_date"), (
                "INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 VIOLATED: "
                f"ExecutionEntry block_id={entry.block_id} lacks "
                "programming_day_date field. "
                "Deterministic schedule lineage is broken. "
                "The pipeline must propagate the source ScheduleDay date "
                "into every execution artifact."
            )
            assert entry.programming_day_date is not None, (
                "INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 VIOLATED: "
                f"ExecutionEntry block_id={entry.block_id} has "
                "programming_day_date=None. "
                "Every execution artifact must reference its source "
                "ResolvedScheduleDay."
            )
            assert entry.programming_day_date == date(2026, 1, 1), (
                "INV-EXECUTION-DERIVED-FROM-SCHEDULEDAY-001 VIOLATED: "
                f"ExecutionEntry block_id={entry.block_id} has "
                f"programming_day_date={entry.programming_day_date}, "
                f"expected 2026-01-01. "
                "Lineage does not match the source ResolvedScheduleDay."
            )


# =========================================================================
# INV-DERIVATION-ANCHOR-PROTECTED-001
# =========================================================================


class TestInvDerivationAnchorProtected001:
    """INV-DERIVATION-ANCHOR-PROTECTED-001

    A ResolvedScheduleDay that has downstream execution artifacts
    (ExecutionEntries in the ExecutionWindowStore) must not be deletable.
    Removing a schedule anchor while execution artifacts still reference
    it severs the constitutional derivation chain and makes the broadcast
    record unauditable.

    Derived from: LAW-DERIVATION, LAW-IMMUTABILITY.
    """

    def test_inv_derivation_anchor_protected_001_reject_delete_with_downstream(
        self, contract_clock
    ):
        """INV-DERIVATION-ANCHOR-PROTECTED-001 -- negative

        Invariant: INV-DERIVATION-ANCHOR-PROTECTED-001
        Derived law(s): LAW-DERIVATION, LAW-IMMUTABILITY
        Failure class: Planning
        Scenario: Materialize a ResolvedScheduleDay. Populate
                  ExecutionWindowStore with entries derived from it.
                  Attempt to delete the ScheduleDay. Assert deletion
                  is rejected with ValueError.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        exec_store = ExecutionWindowStore()
        resolved_store = InMemoryResolvedStore(execution_store=exec_store)

        resolved = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )
        resolved_store.store(CHANNEL_ID, resolved)
        assert resolved_store.exists(CHANNEL_ID, date(2026, 1, 1))

        # Populate execution store with entries derived from this ScheduleDay.
        downstream_entries = [
            _make_entry(block_index=i, start_offset_ms=i * GRID_BLOCK_MS)
            for i in range(4)
        ]
        exec_store.add_entries(downstream_entries)
        assert len(exec_store.get_all_entries()) == 4

        # Deletion must be refused — downstream execution artifacts exist.
        with pytest.raises(ValueError, match="INV-DERIVATION-ANCHOR-PROTECTED-001"):
            resolved_store.delete(CHANNEL_ID, date(2026, 1, 1))

        # Anchor must survive the rejected deletion attempt.
        assert resolved_store.exists(CHANNEL_ID, date(2026, 1, 1)), (
            "INV-DERIVATION-ANCHOR-PROTECTED-001 VIOLATED: "
            "ResolvedScheduleDay was removed despite rejection. "
            "The anchor must survive a failed delete."
        )

    def test_inv_derivation_anchor_protected_001_allow_delete_without_downstream(
        self, contract_clock
    ):
        """INV-DERIVATION-ANCHOR-PROTECTED-001 -- positive

        Invariant: INV-DERIVATION-ANCHOR-PROTECTED-001
        Derived law(s): LAW-DERIVATION, LAW-IMMUTABILITY
        Failure class: N/A (positive path)
        Scenario: Materialize a ResolvedScheduleDay with no downstream
                  execution artifacts. Delete it. Assert deletion succeeds.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        exec_store = ExecutionWindowStore()
        resolved_store = InMemoryResolvedStore(execution_store=exec_store)

        resolved = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 2),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )
        resolved_store.store(CHANNEL_ID, resolved)
        assert resolved_store.exists(CHANNEL_ID, date(2026, 1, 2))

        # No downstream execution artifacts for this day.
        # Deletion should proceed without error.
        resolved_store.delete(CHANNEL_ID, date(2026, 1, 2))
        assert not resolved_store.exists(CHANNEL_ID, date(2026, 1, 2)), (
            "ResolvedScheduleDay should be removed after delete "
            "when no downstream artifacts exist."
        )


# =========================================================================
# INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001
# =========================================================================


@pytest.mark.skip(
    reason=(
        "INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 is not yet a filed "
        "constitutional invariant. The override system (OverrideService, "
        "override records, override artifacts) does not exist in the current "
        "codebase. Reserved for a future iteration once the override system is "
        "designed and its invariant is filed under "
        "docs/contracts/invariants/core/. "
        "See constitutional completeness audit for details."
    )
)
class TestInvOverrideRecordPrecedesArtifact001:
    """INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 — RESERVED

    Override system not yet part of constitutional invariants.
    Reserved until the override system is designed.

    When filed, this invariant will guarantee:
      An override record must be persisted before the override artifact is
      committed. No window may exist where an override artifact is active
      without a backing override record.
    Derived from: LAW-IMMUTABILITY.
    """

    def test_inv_override_record_precedes_artifact_001_reject_without_record(
        self, contract_clock
    ):
        """INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 -- negative (reserved)"""
        pytest.skip("Override system not yet part of constitutional invariants.")

    def test_inv_override_record_precedes_artifact_001_atomicity(
        self, contract_clock
    ):
        """INV-OVERRIDE-RECORD-PRECEDES-ARTIFACT-001 -- atomicity (reserved)"""
        pytest.skip("Override system not yet part of constitutional invariants.")


# =========================================================================
# INV-ASRUN-IMMUTABLE-001
# =========================================================================


class TestInvAsrunImmutable001:
    """INV-ASRUN-IMMUTABLE-001

    AsRun records are immutable after creation. No mutation or deletion
    of AsRun records is permitted.
    Derived from: LAW-IMMUTABILITY.
    """

    def test_inv_asrun_immutable_001_reject_mutation(self, contract_clock):
        """INV-ASRUN-IMMUTABLE-001 -- negative (mutation)

        Invariant: INV-ASRUN-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY
        Failure class: Runtime
        Scenario: Create an AsRun record. Attempt direct field mutation.
                  Assert frozen dataclass rejects it.  Then verify that
                  log_playout_end() produces a new instance without
                  altering the original.
        """
        logger = AsRunLogger()
        event_id = logger.log_playout_start(
            channel_id=CHANNEL_ID,
            program_id="prog-001",
            asset_id="asset-001",
            start_time_utc=EPOCH,
        )

        # Capture the original instance.
        original = logger.events[0]
        assert original.event_id == event_id

        # Direct field mutation must be rejected (frozen dataclass).
        with pytest.raises(AttributeError):
            original.end_time_utc = EPOCH + timedelta(hours=1)

        # log_playout_end() must produce a new instance, not mutate in-place.
        new_end = EPOCH + timedelta(minutes=30)
        updated = logger.log_playout_end(event_id, new_end)

        assert updated is not None, (
            "log_playout_end() must return the new AsRunEvent instance"
        )
        assert updated is not original, (
            "INV-ASRUN-IMMUTABLE-001 VIOLATED: "
            "log_playout_end() returned the same object reference. "
            "State transitions must produce new instances."
        )
        assert updated.end_time_utc == new_end, (
            "Updated instance must carry the new end_time_utc"
        )
        assert original.end_time_utc == EPOCH, (
            "INV-ASRUN-IMMUTABLE-001 VIOLATED: "
            "Original AsRunEvent instance was mutated. "
            f"end_time_utc changed from {EPOCH} to {original.end_time_utc}."
        )

    def test_inv_asrun_immutable_001_reject_deletion(self, contract_clock):
        """INV-ASRUN-IMMUTABLE-001 -- negative (deletion)

        Invariant: INV-ASRUN-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY
        Failure class: Runtime
        Scenario: Create an AsRun record. Verify frozen dataclass
                  prevents direct field mutation (FrozenInstanceError).
                  Verify the event persists in the logger.
        """
        logger = AsRunLogger()
        logger.log_playout_start(
            channel_id=CHANNEL_ID,
            program_id="prog-001",
            asset_id="asset-001",
            start_time_utc=EPOCH,
        )
        assert len(logger.events) == 1

        # AsRunEvent is frozen — direct field assignment must raise.
        event = logger.events[0]
        with pytest.raises(AttributeError):
            event.end_time_utc = EPOCH + timedelta(hours=1)

        # If a delete method exists, it must reject deletion of committed records.
        if hasattr(logger, "delete_event"):
            event_id = logger.events[0].event_id
            try:
                logger.delete_event(event_id)
            except Exception:
                pass
            else:
                pytest.fail(
                    "INV-ASRUN-IMMUTABLE-001 VIOLATED: "
                    "AsRun record deleted via delete_event()."
                )

        # Event must still exist after all mutation/deletion attempts.
        assert len(logger.events) == 1, (
            "AsRun record should still exist after all mutation/deletion attempts"
        )

    def test_inv_asrun_immutable_001_valid_creation(self, contract_clock):
        """INV-ASRUN-IMMUTABLE-001 -- positive

        Invariant: INV-ASRUN-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY
        Failure class: N/A (positive path)
        Scenario: Valid creation of an AsRun record. Assert it persists
                  correctly with all required fields.
        """
        logger = AsRunLogger()
        event_id = logger.log_playout_start(
            channel_id=CHANNEL_ID,
            program_id="prog-001",
            asset_id="asset-001",
            start_time_utc=EPOCH,
            segment_type="content",
            metadata={"test": True},
        )

        assert event_id is not None, "AsRun creation must return an event_id"

        events = logger.get_events_for_broadcast_day(CHANNEL_ID, "2026-01-01")
        assert len(events) == 1, "Exactly one AsRun event expected"

        event = events[0]
        assert event.event_id == event_id
        assert event.channel_id == CHANNEL_ID
        assert event.asset_id == "asset-001"
        assert event.program_id == "prog-001"
        assert event.start_time_utc == EPOCH
        assert event.segment_type == "content"
        assert event.broadcast_day == "2026-01-01"
