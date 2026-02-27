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

from datetime import date, datetime, time, timedelta, timezone

import pytest

from retrovue.runtime.asrun_logger import AsRunEvent, AsRunLogger
from retrovue.runtime.execution_window_store import (
    ExecutionEntry,
    ExecutionWindowStore,
    validate_execution_entry_contiguity,
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


# =========================================================================
# INV-PLAN-GRID-ALIGNMENT-001
# =========================================================================


class _StubChannel:
    def __init__(self, grid_block_minutes=30, block_start_offsets_minutes=None):
        self.grid_block_minutes = grid_block_minutes
        self.block_start_offsets_minutes = block_start_offsets_minutes or [0]


class _StubAssignment:
    def __init__(
        self,
        id="test-assign",
        start_time="06:00",
        duration=30,
        content_type="asset",
        content_ref="asset-001",
    ):
        self.id = id
        self.start_time = start_time
        self.duration = duration
        self.content_type = content_type
        self.content_ref = content_ref


class TestInvPlanGridAlignment001:
    """INV-PLAN-GRID-ALIGNMENT-001

    All plan elements must align to channel grid boundaries.
    Duration must be a multiple of grid_block_minutes.
    Start time must fall on a valid grid offset.

    Enforcement lives in validate_block_assignment() in
    retrovue.core.scheduling.contracts.

    Derived from: LAW-CONTENT-AUTHORITY.
    """

    def test_inv_plan_grid_alignment_001_reject_off_grid_start(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- negative (start time)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: start_time="06:15" on a 30-minute grid with offset [0].
                  Must be rejected with BlockAssignmentValidationError
                  carrying the invariant name.
        """
        from retrovue.core.scheduling.contracts import validate_block_assignment
        from retrovue.core.scheduling.exceptions import BlockAssignmentValidationError

        channel = _StubChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = _StubAssignment(start_time="06:15", duration=30)

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, channel=channel)

        assert "INV-PLAN-GRID-ALIGNMENT-001" in str(exc_info.value), (
            "INV-PLAN-GRID-ALIGNMENT-001 VIOLATED: "
            "off-grid start_time was rejected but the violation message "
            "does not carry the constitutional invariant name."
        )

    def test_inv_plan_grid_alignment_001_reject_off_grid_duration(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- negative (duration)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: duration=25 on a 30-minute grid.
                  Must be rejected with BlockAssignmentValidationError
                  carrying the invariant name.
        """
        from retrovue.core.scheduling.contracts import validate_block_assignment
        from retrovue.core.scheduling.exceptions import BlockAssignmentValidationError

        channel = _StubChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = _StubAssignment(start_time="06:00", duration=25)

        with pytest.raises(BlockAssignmentValidationError) as exc_info:
            validate_block_assignment(assignment, channel=channel)

        assert "INV-PLAN-GRID-ALIGNMENT-001" in str(exc_info.value), (
            "INV-PLAN-GRID-ALIGNMENT-001 VIOLATED: "
            "off-grid duration was rejected but the violation message "
            "does not carry the constitutional invariant name."
        )

    def test_inv_plan_grid_alignment_001_valid_alignment(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- positive

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: start_time="06:00", duration=30 on a 30-minute grid
                  with offset [0]. Must pass without exception.
        """
        from retrovue.core.scheduling.contracts import validate_block_assignment

        channel = _StubChannel(grid_block_minutes=30, block_start_offsets_minutes=[0])
        assignment = _StubAssignment(start_time="06:00", duration=30)

        # Should not raise
        validate_block_assignment(assignment, channel=channel)

    def test_inv_plan_grid_alignment_001_reject_off_grid_zone_end(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- negative (zone end_time)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-GRID
        Failure class: Planning
        Scenario: Zone end_time=17:59 on a 30-minute grid.
                  17:59 is not a multiple of 30 minutes from midnight.
                  Must raise ValueError carrying the invariant name.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zone = _StubZone(name="Bad", start_time="06:00", end_time="17:59")

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity([zone], grid_block_minutes=30)

        assert "INV-PLAN-GRID-ALIGNMENT-001" in str(exc_info.value), (
            "INV-PLAN-GRID-ALIGNMENT-001 VIOLATED: "
            "off-grid zone end_time was not detected."
        )

    def test_inv_plan_grid_alignment_001_reject_off_grid_zone_start(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- negative (zone start_time)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-GRID
        Failure class: Planning
        Scenario: Zone start_time=06:15 on a 30-minute grid.
                  Must raise ValueError carrying the invariant name.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zone = _StubZone(name="Bad", start_time="06:15", end_time="18:00")

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity([zone], grid_block_minutes=30)

        assert "INV-PLAN-GRID-ALIGNMENT-001" in str(exc_info.value), (
            "INV-PLAN-GRID-ALIGNMENT-001 VIOLATED: "
            "off-grid zone start_time was not detected."
        )

    def test_inv_plan_grid_alignment_001_reject_off_grid_zone_duration(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- negative (zone duration)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-GRID
        Failure class: Planning
        Scenario: Zone [06:00-06:45] on a 30-minute grid.
                  Both boundaries are grid-aligned (0 and 45 min past
                  the hour — wait, 45 is not a multiple of 30).
                  Actually 06:45 → 405 min, 405 % 30 = 15 ≠ 0.
                  So end_time itself is off-grid and caught first.
                  Use [06:00-07:15] instead: 06:00=360 (ok), 07:15=435 (435%30=15 ≠ 0).
                  Must raise for off-grid end.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zone = _StubZone(name="Bad", start_time="06:00", end_time="07:15")

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity([zone], grid_block_minutes=30)

        assert "INV-PLAN-GRID-ALIGNMENT-001" in str(exc_info.value)

    def test_inv_plan_grid_alignment_001_accept_aligned_zone(self):
        """INV-PLAN-GRID-ALIGNMENT-001 -- positive (zone boundaries)

        Invariant: INV-PLAN-GRID-ALIGNMENT-001
        Derived law(s): LAW-GRID
        Failure class: N/A (positive path)
        Scenario: Zone [06:00-18:00] on a 30-minute grid.
                  Start, end, and duration all aligned. Must pass.
                  (Coverage check will still fire — provide full tiling.)
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(name="Day", start_time="06:00", end_time="18:00"),
            _StubZone(name="Night", start_time="18:00", end_time="24:00"),
            _StubZone(name="Early", start_time="00:00", end_time="06:00"),
        ]

        # Should not raise — all grid-aligned and full coverage.
        validate_zone_plan_integrity(zones, grid_block_minutes=30)


# =========================================================================
# INV-PLAN-NO-ZONE-OVERLAP-001
# =========================================================================


class _StubZone:
    """Lightweight stand-in for a Zone entity (no DB required)."""

    def __init__(
        self,
        name: str = "zone",
        start_time: str = "00:00",
        end_time: str = "24:00",
        day_filters: list[str] | None = None,
        enabled: bool = True,
    ):
        from datetime import time as dt_time

        self.name = name
        self.enabled = enabled
        self.day_filters = day_filters

        _EOD = dt_time(23, 59, 59, 999999)

        def _parse(t: str) -> dt_time:
            if t in ("24:00", "24:00:00"):
                return _EOD
            parts = t.split(":")
            return dt_time(int(parts[0]), int(parts[1]), 0)

        self.start_time = _parse(start_time)
        self.end_time = _parse(end_time)


class TestInvPlanNoZoneOverlap001:
    """INV-PLAN-NO-ZONE-OVERLAP-001

    No two active zones within the same SchedulePlan may have overlapping
    time windows, after considering day-of-week filters.

    Enforcement lives in validate_zone_plan_integrity() called by
    zone_add and zone_update.

    Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID.
    """

    def test_inv_plan_no_zone_overlap_001_reject_overlapping_zones(self):
        """INV-PLAN-NO-ZONE-OVERLAP-001 -- negative

        Invariant: INV-PLAN-NO-ZONE-OVERLAP-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: Planning
        Scenario: Two zones on the same days with overlapping windows.
                  Zone A: 06:00-18:00, Zone B: 16:00-24:00 (overlap 16:00-18:00).
                  Must raise ValueError carrying the invariant name.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(name="Morning", start_time="06:00", end_time="18:00"),
            _StubZone(name="Evening", start_time="16:00", end_time="24:00"),
        ]

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(zones)

        assert "INV-PLAN-NO-ZONE-OVERLAP-001" in str(exc_info.value), (
            "INV-PLAN-NO-ZONE-OVERLAP-001 VIOLATED: "
            "overlapping zones were rejected but the violation message "
            "does not carry the constitutional invariant name."
        )

    def test_inv_plan_no_zone_overlap_001_allow_mutually_exclusive_days(self):
        """INV-PLAN-NO-ZONE-OVERLAP-001 -- positive (day filter exclusion)

        Invariant: INV-PLAN-NO-ZONE-OVERLAP-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: N/A (positive path)
        Scenario: Two zones with the same time window but mutually exclusive
                  day filters (Mon-Fri vs Sat-Sun). They tile all 7 days
                  with full coverage. Must pass without exception.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(
                name="Weekday",
                start_time="00:00",
                end_time="24:00",
                day_filters=["MON", "TUE", "WED", "THU", "FRI"],
            ),
            _StubZone(
                name="Weekend",
                start_time="00:00",
                end_time="24:00",
                day_filters=["SAT", "SUN"],
            ),
        ]

        # Should not raise — day filters are mutually exclusive and
        # each day has full coverage.
        validate_zone_plan_integrity(zones)

    def test_inv_plan_no_zone_overlap_001_reject_mutation_induced_overlap(self):
        """INV-PLAN-NO-ZONE-OVERLAP-001 -- negative (mutation path)

        Invariant: INV-PLAN-NO-ZONE-OVERLAP-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: Planning
        Scenario: Simulates zone_update.  Three zones tile the day cleanly:
                    A [00:00-08:00], B [08:00-20:00], C [20:00-24:00].
                  Zone A is mutated from [00:00-08:00] → [00:00-10:00],
                  creating a 2-hour overlap with B [08:00-10:00].
                  The candidate list is built the same way zone_update does:
                    siblings (excluding A) + mutated A.
                  Must raise ValueError carrying the invariant name.
        """
        from datetime import time as dt_time

        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        # Original clean tiling
        zone_a = _StubZone(name="A", start_time="00:00", end_time="08:00")
        zone_b = _StubZone(name="B", start_time="08:00", end_time="20:00")
        zone_c = _StubZone(name="C", start_time="20:00", end_time="24:00")

        # Sanity: original tiling is clean
        validate_zone_plan_integrity([zone_a, zone_b, zone_c])

        # Mutate A in-place (same as zone_update does before validation)
        zone_a.end_time = dt_time(10, 0, 0)

        # Build candidate list the way zone_update does:
        # siblings (B, C) + mutated A
        siblings = [zone_b, zone_c]
        candidate_zones = siblings + [zone_a]

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(candidate_zones)

        assert "INV-PLAN-NO-ZONE-OVERLAP-001" in str(exc_info.value), (
            "INV-PLAN-NO-ZONE-OVERLAP-001 VIOLATED: "
            "post-mutation overlap was not detected. "
            "zone_update must validate the mutated zone against siblings."
        )

    def test_inv_plan_no_zone_overlap_001_precedence_over_gap(self):
        """INV-PLAN-NO-ZONE-OVERLAP-001 -- precedence

        Invariant: INV-PLAN-NO-ZONE-OVERLAP-001 (primary),
                   INV-PLAN-FULL-COVERAGE-001 (secondary)
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: Planning
        Scenario: Both overlap AND gap exist simultaneously:
                    A [06:00-12:00], B [11:00-15:00], C [16:00-24:00],
                    D [00:00-06:00].
                  Overlap: A/B at [11:00-12:00].
                  Gap: [15:00-16:00].
                  validate_zone_plan_integrity must report the overlap
                  (INV-PLAN-NO-ZONE-OVERLAP-001) not the gap.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(name="A", start_time="06:00", end_time="12:00"),
            _StubZone(name="B", start_time="11:00", end_time="15:00"),
            _StubZone(name="C", start_time="16:00", end_time="24:00"),
            _StubZone(name="D", start_time="00:00", end_time="06:00"),
        ]

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(zones)

        msg = str(exc_info.value)
        assert "INV-PLAN-NO-ZONE-OVERLAP-001" in msg, (
            "When both overlap and gap exist, overlap must be reported first. "
            f"Got: {msg}"
        )
        assert "INV-PLAN-FULL-COVERAGE-001" not in msg, (
            "Gap error must not mask the overlap error. "
            f"Got: {msg}"
        )


# =========================================================================
# INV-PLAN-FULL-COVERAGE-001
# =========================================================================


class TestInvPlanFullCoverage001:
    """INV-PLAN-FULL-COVERAGE-001

    An active SchedulePlan's zones must collectively cover the full broadcast
    day [00:00, 24:00] with no temporal gaps.

    Enforcement lives in validate_zone_plan_integrity() called by
    zone_add and zone_update.

    Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID.
    """

    def test_inv_plan_full_coverage_001_reject_gap(self):
        """INV-PLAN-FULL-COVERAGE-001 -- negative

        Invariant: INV-PLAN-FULL-COVERAGE-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: Planning
        Scenario: Zones covering [00:00-18:00] and [20:00-24:00] leave a gap
                  at [18:00-20:00]. Must raise ValueError with the invariant name.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(name="Day", start_time="00:00", end_time="18:00"),
            _StubZone(name="Night", start_time="20:00", end_time="24:00"),
        ]

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(zones)

        assert "INV-PLAN-FULL-COVERAGE-001" in str(exc_info.value), (
            "INV-PLAN-FULL-COVERAGE-001 VIOLATED: "
            "gap in zone coverage was rejected but the violation message "
            "does not carry the constitutional invariant name."
        )

    def test_inv_plan_full_coverage_001_accept_exact_tile(self):
        """INV-PLAN-FULL-COVERAGE-001 -- positive

        Invariant: INV-PLAN-FULL-COVERAGE-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: N/A (positive path)
        Scenario: Three zones that tile the broadcast day exactly:
                  [00:00-06:00], [06:00-18:00], [18:00-24:00].
                  Must pass without exception.
        """
        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        zones = [
            _StubZone(name="Overnight", start_time="00:00", end_time="06:00"),
            _StubZone(name="Daytime", start_time="06:00", end_time="18:00"),
            _StubZone(name="Evening", start_time="18:00", end_time="24:00"),
        ]

        # Should not raise — zones tile the full broadcast day.
        validate_zone_plan_integrity(zones)

    def test_inv_plan_full_coverage_001_reject_gap_with_pds_0600(self):
        """INV-PLAN-FULL-COVERAGE-001 -- negative (programming_day_start=06:00)

        Invariant: INV-PLAN-FULL-COVERAGE-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: Planning
        Scenario: programming_day_start=06:00. Broadcast day spans 06:00→06:00.
                  Two zones: [06:00-22:00] and [00:00-04:00].
                  Gap exists at [22:00-00:00] and [04:00-06:00] (wall clock),
                  i.e. hours 16-18 and 22-24 of the broadcast day are uncovered.
                  Must raise ValueError with the invariant name.
        """
        from datetime import time as dt_time

        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        pds = dt_time(6, 0)
        zones = [
            _StubZone(name="Daytime", start_time="06:00", end_time="22:00"),
            _StubZone(name="LateNight", start_time="00:00", end_time="04:00"),
        ]

        with pytest.raises(ValueError) as exc_info:
            validate_zone_plan_integrity(zones, programming_day_start=pds)

        assert "INV-PLAN-FULL-COVERAGE-001" in str(exc_info.value), (
            "INV-PLAN-FULL-COVERAGE-001 VIOLATED: "
            "gap across midnight boundary with pds=06:00 was not detected."
        )

    def test_inv_plan_full_coverage_001_accept_tile_with_pds_0600(self):
        """INV-PLAN-FULL-COVERAGE-001 -- positive (programming_day_start=06:00)

        Invariant: INV-PLAN-FULL-COVERAGE-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID
        Failure class: N/A (positive path)
        Scenario: programming_day_start=06:00. Broadcast day spans 06:00→06:00.
                  Three zones tile the full 24 hours across midnight:
                    [06:00-18:00], [18:00-24:00], [00:00-06:00].
                  Must pass without exception.
        """
        from datetime import time as dt_time

        from retrovue.usecases.zone_coverage_check import validate_zone_plan_integrity

        pds = dt_time(6, 0)
        zones = [
            _StubZone(name="Daytime", start_time="06:00", end_time="18:00"),
            _StubZone(name="Evening", start_time="18:00", end_time="24:00"),
            _StubZone(name="Overnight", start_time="00:00", end_time="06:00"),
        ]

        # Should not raise — zones tile 06:00→18:00→24:00/00:00→06:00 = full day.
        validate_zone_plan_integrity(zones, programming_day_start=pds)


# =========================================================================
# INV-SCHEDULEDAY-ONE-PER-DATE-001
# =========================================================================


class TestInvScheduledayOnePerDate001:
    """INV-SCHEDULEDAY-ONE-PER-DATE-001

    For a given (channel_id, broadcast_date), exactly one authoritative
    ScheduleDay may exist. Duplicate insertion is forbidden. Replacement
    must be atomic via explicit regeneration (force_replace).

    Enforcement lives in InMemoryResolvedStore.store() and force_replace().

    Derived from: LAW-DERIVATION, LAW-IMMUTABILITY.
    """

    def _make_resolved(self, contract_clock, day_date=None):
        """Build a minimal ResolvedScheduleDay for testing."""
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        return ResolvedScheduleDay(
            programming_day_date=day_date or date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )

    def test_inv_scheduleday_one_per_date_001_reject_duplicate_insert(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-ONE-PER-DATE-001 -- negative

        Invariant: INV-SCHEDULEDAY-ONE-PER-DATE-001
        Derived law(s): LAW-DERIVATION, LAW-IMMUTABILITY
        Failure class: Planning
        Scenario: Store a ResolvedScheduleDay for (channel, date). Attempt
                  to store a second ResolvedScheduleDay for the same
                  (channel, date). Assert the second insert is rejected
                  with ValueError carrying the invariant name.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()

        first = self._make_resolved(contract_clock)
        store.store(CHANNEL_ID, first)
        assert store.exists(CHANNEL_ID, date(2026, 1, 1))

        # Second insert for same (channel, date) MUST be rejected.
        second = self._make_resolved(contract_clock)
        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-ONE-PER-DATE-001"):
            store.store(CHANNEL_ID, second)

        # Original must survive — no corruption from rejected insert.
        surviving = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert surviving is first, (
            "INV-SCHEDULEDAY-ONE-PER-DATE-001 VIOLATED: "
            "Original ResolvedScheduleDay was corrupted by the rejected "
            "duplicate insert."
        )

    def test_inv_scheduleday_one_per_date_001_allow_force_regen_atomic_replace(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-ONE-PER-DATE-001 -- positive (atomic replace)

        Invariant: INV-SCHEDULEDAY-ONE-PER-DATE-001
        Derived law(s): LAW-DERIVATION, LAW-IMMUTABILITY
        Failure class: N/A (positive path)
        Scenario: Store a ResolvedScheduleDay for (channel, date). Use
                  force_replace() to atomically swap it with a new one.
                  Assert old is gone, new is present, and exactly one
                  record exists at all times.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()

        original = self._make_resolved(contract_clock)
        store.store(CHANNEL_ID, original)

        # Advance clock so replacement has a different timestamp.
        contract_clock.advance_ms(1000)
        replacement = self._make_resolved(contract_clock)

        # Atomic replace must succeed.
        store.force_replace(CHANNEL_ID, replacement)

        # Exactly one record must exist.
        assert store.exists(CHANNEL_ID, date(2026, 1, 1))
        surviving = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert surviving is replacement, (
            "INV-SCHEDULEDAY-ONE-PER-DATE-001 VIOLATED: "
            "force_replace() did not install the replacement. "
            f"Expected replacement (ts={replacement.resolution_timestamp}), "
            f"got (ts={surviving.resolution_timestamp})."
        )
        assert surviving is not original, (
            "INV-SCHEDULEDAY-ONE-PER-DATE-001 VIOLATED: "
            "force_replace() left the original in place."
        )

    def test_inv_scheduleday_one_per_date_001_different_dates_independent(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-ONE-PER-DATE-001 -- positive (different dates)

        Invariant: INV-SCHEDULEDAY-ONE-PER-DATE-001
        Derived law(s): LAW-DERIVATION, LAW-IMMUTABILITY
        Failure class: N/A (positive path)
        Scenario: Store ResolvedScheduleDays for two different dates on
                  the same channel. Assert both are accepted — uniqueness
                  is per (channel, date), not per channel.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()

        day1 = self._make_resolved(contract_clock, day_date=date(2026, 1, 1))
        day2 = self._make_resolved(contract_clock, day_date=date(2026, 1, 2))

        store.store(CHANNEL_ID, day1)
        store.store(CHANNEL_ID, day2)

        assert store.exists(CHANNEL_ID, date(2026, 1, 1))
        assert store.exists(CHANNEL_ID, date(2026, 1, 2))


# =========================================================================
# INV-SCHEDULEDAY-IMMUTABLE-001
# =========================================================================


class TestInvScheduledayImmutable001:
    """INV-SCHEDULEDAY-IMMUTABLE-001

    A materialized ResolvedScheduleDay must never be mutated in place.
    Any change must occur via force-regeneration (atomic replace) or
    operator override (new record referencing superseded record).

    Enforcement lives in:
    - ResolvedScheduleDay frozen dataclass (type-level)
    - InMemoryResolvedStore.update() rejection (store boundary)
    - InMemoryResolvedStore.operator_override() (override workflow)

    Derived from: LAW-IMMUTABILITY, LAW-DERIVATION.
    """

    def _make_resolved(self, contract_clock, day_date=None, slots=None):
        """Build a ResolvedScheduleDay for testing."""
        from retrovue.runtime.schedule_types import (
            ProgramRef,
            ProgramRefType,
            ResolvedAsset,
            ResolvedScheduleDay,
            ResolvedSlot,
            SequenceState,
        )

        if slots is None:
            slots = [
                ResolvedSlot(
                    slot_time=time(6, 0),
                    program_ref=ProgramRef(
                        ref_type=ProgramRefType.FILE, ref_id="show-001.ts"
                    ),
                    resolved_asset=ResolvedAsset(
                        file_path="/media/show-001.ts",
                        asset_id="asset-001",
                        content_duration_seconds=1800.0,
                    ),
                    duration_seconds=1800.0,
                    label="Morning Show",
                ),
            ]
        return ResolvedScheduleDay(
            programming_day_date=day_date or date(2026, 1, 1),
            resolved_slots=slots,
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )

    def test_inv_scheduleday_immutable_001_reject_in_place_slot_mutation(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-IMMUTABLE-001 -- negative (slot mutation)

        Invariant: INV-SCHEDULEDAY-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-DERIVATION
        Failure class: Runtime
        Scenario: Materialize ResolvedScheduleDay SD for (C, D).
                  Attempt to mutate a slot field or reassign resolved_slots.
                  Assert mutation is rejected. Assert SD content unchanged.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()
        sd = self._make_resolved(contract_clock)
        store.store(CHANNEL_ID, sd)

        retrieved = store.get(CHANNEL_ID, date(2026, 1, 1))

        # Attempt 1: Reassign resolved_slots list on the dataclass.
        # Frozen dataclass MUST reject this.
        with pytest.raises(AttributeError):
            retrieved.resolved_slots = []

        # Attempt 2: Mutate a slot's resolved_asset field.
        # Frozen nested dataclass MUST reject this.
        with pytest.raises(AttributeError):
            retrieved.resolved_slots[0].resolved_asset = None

        # Attempt 3: Update via store boundary must be rejected.
        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-IMMUTABLE-001"):
            store.update(CHANNEL_ID, date(2026, 1, 1), {"resolved_slots": []})

        # Original must be intact after all rejected mutation attempts.
        after = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert after is retrieved, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "ResolvedScheduleDay was replaced or corrupted by rejected "
            "mutation attempts."
        )
        assert len(after.resolved_slots) == 1, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "resolved_slots were mutated despite rejection."
        )
        assert after.resolved_slots[0].resolved_asset.asset_id == "asset-001"

    def test_inv_scheduleday_immutable_001_reject_plan_id_update(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-IMMUTABLE-001 -- negative (field update)

        Invariant: INV-SCHEDULEDAY-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-DERIVATION
        Failure class: Runtime
        Scenario: Materialize ResolvedScheduleDay SD. Attempt to update
                  resolution_timestamp or programming_day_date via store
                  boundary. Assert rejected with invariant tag. Assert
                  original fields preserved.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()
        sd = self._make_resolved(contract_clock)
        original_ts = sd.resolution_timestamp
        store.store(CHANNEL_ID, sd)

        # Attempt to update resolution_timestamp via store boundary.
        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-IMMUTABLE-001"):
            store.update(
                CHANNEL_ID,
                date(2026, 1, 1),
                {"resolution_timestamp": contract_clock.clock.now_utc()},
            )

        # Attempt direct field mutation on frozen dataclass.
        retrieved = store.get(CHANNEL_ID, date(2026, 1, 1))
        with pytest.raises(AttributeError):
            retrieved.programming_day_date = date(2026, 1, 2)

        # Original must be preserved.
        after = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert after.resolution_timestamp == original_ts, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "resolution_timestamp was mutated."
        )

    def test_inv_scheduleday_immutable_001_force_regen_creates_new_record(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-IMMUTABLE-001 -- positive (force regen)

        Invariant: INV-SCHEDULEDAY-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-DERIVATION
        Failure class: N/A (positive path)
        Scenario: Materialize SD_OLD. Trigger force_replace() with SD_NEW.
                  Assert SD_NEW is not SD_OLD (new record, not mutation).
                  Assert only one authoritative record exists for (C, D).
                  Assert no in-place update occurred on SD_OLD.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore()
        sd_old = self._make_resolved(contract_clock)
        old_ts = sd_old.resolution_timestamp
        store.store(CHANNEL_ID, sd_old)

        # Advance clock, create new record.
        contract_clock.advance_ms(5000)
        sd_new = self._make_resolved(contract_clock)

        # force_replace creates new record atomically.
        store.force_replace(CHANNEL_ID, sd_new)

        # Exactly one authoritative record.
        current = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert current is sd_new, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "force_replace() did not install the new record."
        )
        assert current is not sd_old, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "force_replace() returned the old record (in-place mutation?)."
        )
        assert current.resolution_timestamp != old_ts, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "New record has the same timestamp as old — suspicious."
        )

        # SD_OLD was not mutated (frozen dataclass preserves it).
        assert sd_old.resolution_timestamp == old_ts, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "SD_OLD was mutated during force_replace()."
        )

    def test_inv_scheduleday_immutable_001_operator_override_creates_new_record(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-IMMUTABLE-001 -- positive (operator override)

        Invariant: INV-SCHEDULEDAY-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-DERIVATION
        Failure class: N/A (positive path)
        Scenario: Materialize SD_ORIG. Trigger operator_override() with
                  modified content. Assert SD_OVERRIDE is a new record.
                  Assert SD_OVERRIDE.is_manual_override == True.
                  Assert SD_OVERRIDE.supersedes_id references SD_ORIG.
                  Assert SD_ORIG remains unchanged.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import (
            ProgramRef,
            ProgramRefType,
            ResolvedAsset,
            ResolvedSlot,
        )

        store = InMemoryResolvedStore()
        sd_orig = self._make_resolved(contract_clock)
        orig_ts = sd_orig.resolution_timestamp
        store.store(CHANNEL_ID, sd_orig)

        # Build override with different content.
        contract_clock.advance_ms(5000)
        override_slots = [
            ResolvedSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(
                    ref_type=ProgramRefType.FILE, ref_id="override-show.ts"
                ),
                resolved_asset=ResolvedAsset(
                    file_path="/media/override-show.ts",
                    asset_id="asset-override",
                    content_duration_seconds=1800.0,
                ),
                duration_seconds=1800.0,
                label="Override Show",
            ),
        ]
        sd_override = self._make_resolved(
            contract_clock, slots=override_slots
        )

        # Operator override must create a new record.
        result = store.operator_override(CHANNEL_ID, sd_override)

        # SD_OVERRIDE is a new record, not the original.
        assert result is not sd_orig

        # Override metadata.
        assert result.is_manual_override is True, (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "operator_override() did not set is_manual_override=True."
        )
        assert result.supersedes_id == id(sd_orig), (
            "INV-SCHEDULEDAY-IMMUTABLE-001 VIOLATED: "
            "operator_override() did not link to superseded record."
        )

        # Current authoritative record is the override.
        current = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert current is result

        # SD_ORIG must remain unchanged (frozen).
        assert sd_orig.resolution_timestamp == orig_ts
        assert sd_orig.resolved_slots[0].label == "Morning Show"
        assert not hasattr(sd_orig, "is_manual_override") or not getattr(
            sd_orig, "is_manual_override", False
        )


# =========================================================================
# INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
# =========================================================================


class TestInvScheduledayDerivationTraceable001:
    """INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001

    Every ScheduleDay must trace to its generating SchedulePlan (plan_id)
    or be an explicit operator override (is_manual_override=True with
    supersedes_id). A ScheduleDay with plan_id=None and
    is_manual_override=False is constitutionally unanchored.

    Enforcement lives in InMemoryResolvedStore.store() and force_replace(),
    via _enforce_derivation_traceability() called before commit when
    enforce_derivation_traceability=True.

    Derived from: LAW-DERIVATION, LAW-CONTENT-AUTHORITY.
    """

    def test_inv_scheduleday_derivation_traceable_001_reject_unanchored(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 -- negative

        Invariant: INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
        Derived law(s): LAW-DERIVATION, LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: ResolvedScheduleDay with plan_id=None,
                  is_manual_override=False. store() rejects with
                  invariant tag.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        store = InMemoryResolvedStore(enforce_derivation_traceability=True)

        unanchored = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
            plan_id=None,
            is_manual_override=False,
        )

        with pytest.raises(
            ValueError, match="INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001"
        ):
            store.store(CHANNEL_ID, unanchored)

        # Store must remain empty after rejection.
        assert not store.exists(CHANNEL_ID, date(2026, 1, 1)), (
            "INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 VIOLATED: "
            "Store accepted an unanchored ScheduleDay."
        )

    def test_inv_scheduleday_derivation_traceable_001_accept_with_plan_id(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 -- positive (plan_id)

        Invariant: INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
        Derived law(s): LAW-DERIVATION, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: ResolvedScheduleDay with plan_id="plan-001".
                  store() accepts.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        store = InMemoryResolvedStore(enforce_derivation_traceability=True)

        anchored = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
            plan_id="plan-001",
        )

        # Should not raise — plan_id provides derivation anchor.
        store.store(CHANNEL_ID, anchored)
        assert store.exists(CHANNEL_ID, date(2026, 1, 1))

    def test_inv_scheduleday_derivation_traceable_001_accept_manual_override(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001 -- positive (manual override)

        Invariant: INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
        Derived law(s): LAW-DERIVATION, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: ResolvedScheduleDay with is_manual_override=True,
                  supersedes_id set, plan_id=None.
                  operator_override() accepts.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        store = InMemoryResolvedStore(enforce_derivation_traceability=True)

        # First store an original record to override.
        original = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
            plan_id="plan-001",
        )
        store.store(CHANNEL_ID, original)

        # Build an override record with plan_id=None but is_manual_override=True.
        contract_clock.advance_ms(1000)
        override = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
            plan_id=None,
            is_manual_override=True,
            supersedes_id=id(original),
        )

        # operator_override() should accept — manual override is a valid anchor.
        result = store.operator_override(CHANNEL_ID, override)
        assert result.is_manual_override is True
        assert result.supersedes_id is not None


# =========================================================================
# INV-SCHEDULEDAY-LEAD-TIME-001
# =========================================================================


class TestInvScheduledayLeadTime001:
    """INV-SCHEDULEDAY-LEAD-TIME-001

    A ScheduleDay for broadcast date D must be materialized no later than
    D - min_schedule_day_lead_days calendar days. The lead time is
    deployment-configurable (default 3); tests MUST NOT hardcode the
    literal 3.

    Enforcement is a standalone check function, not a store boundary.
    Tests call check_scheduleday_lead_time() directly with injected
    parameters.

    Derived from: LAW-DERIVATION, LAW-RUNTIME-AUTHORITY.
    """

    def test_inv_scheduleday_lead_time_001_reject_missing_at_deadline(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-LEAD-TIME-001 -- negative

        Invariant: INV-SCHEDULEDAY-LEAD-TIME-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY
        Failure class: Planning
        Scenario: min_schedule_day_lead_days=N (N=3). Clock is past
                  deadline (D-N). No ScheduleDay exists for target date D.
                  Check raises violation with invariant tag and
                  configured N.
        """
        from retrovue.runtime.schedule_manager_service import (
            InMemoryResolvedStore,
            check_scheduleday_lead_time,
        )

        store = InMemoryResolvedStore()
        min_lead_days = 3
        target = date(2026, 1, 10)

        # Set clock past the deadline: D-N+1 day at broadcast start.
        # Deadline is D-3 = Jan 7 at 06:00. Clock at Jan 8 06:00.
        past_deadline = datetime(2026, 1, 8, 6, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(
            ValueError, match="INV-SCHEDULEDAY-LEAD-TIME-001"
        ) as exc_info:
            check_scheduleday_lead_time(
                resolved_store=store,
                channel_id=CHANNEL_ID,
                target_date=target,
                now_utc=past_deadline,
                min_lead_days=min_lead_days,
            )

        # Verify the configured N appears in the error, not a hardcoded value.
        msg = str(exc_info.value)
        assert f"min_schedule_day_lead_days={min_lead_days}" in msg

    def test_inv_scheduleday_lead_time_001_accept_materialized_before_deadline(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-LEAD-TIME-001 -- positive

        Invariant: INV-SCHEDULEDAY-LEAD-TIME-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: ScheduleDay exists for target date D. Clock is past
                  deadline. Check passes.
        """
        from retrovue.runtime.schedule_manager_service import (
            InMemoryResolvedStore,
            check_scheduleday_lead_time,
        )
        from retrovue.runtime.schedule_types import ResolvedScheduleDay, SequenceState

        store = InMemoryResolvedStore()
        min_lead_days = 3
        target = date(2026, 1, 10)

        # Materialize the ScheduleDay.
        resolved = ResolvedScheduleDay(
            programming_day_date=target,
            resolved_slots=[],
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )
        store.store(CHANNEL_ID, resolved)

        # Clock past deadline.
        past_deadline = datetime(2026, 1, 8, 6, 0, 0, tzinfo=timezone.utc)

        # Should not raise — ScheduleDay exists.
        check_scheduleday_lead_time(
            resolved_store=store,
            channel_id=CHANNEL_ID,
            target_date=target,
            now_utc=past_deadline,
            min_lead_days=min_lead_days,
        )

    def test_inv_scheduleday_lead_time_001_parameterized_not_hardcoded(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-LEAD-TIME-001 -- parameterization

        Invariant: INV-SCHEDULEDAY-LEAD-TIME-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY
        Failure class: Planning
        Scenario: Use N=5 (not default 3). Verify check uses injected
                  value. Clock at D-4 (past D-5 deadline). Check raises.
                  Then verify D-6 (before deadline) does not raise.
        """
        from retrovue.runtime.schedule_manager_service import (
            InMemoryResolvedStore,
            check_scheduleday_lead_time,
        )

        store = InMemoryResolvedStore()
        min_lead_days = 5
        target = date(2026, 1, 15)

        # Deadline is D-5 = Jan 10 at 06:00. Clock at Jan 11 06:00 (past).
        past_deadline = datetime(2026, 1, 11, 6, 0, 0, tzinfo=timezone.utc)

        with pytest.raises(
            ValueError, match="INV-SCHEDULEDAY-LEAD-TIME-001"
        ) as exc_info:
            check_scheduleday_lead_time(
                resolved_store=store,
                channel_id=CHANNEL_ID,
                target_date=target,
                now_utc=past_deadline,
                min_lead_days=min_lead_days,
            )

        # Verify the configured N=5 appears, not N=3.
        msg = str(exc_info.value)
        assert "min_schedule_day_lead_days=5" in msg
        assert "min_schedule_day_lead_days=3" not in msg

        # Before deadline (Jan 9 06:00, which is D-6): should not raise.
        before_deadline = datetime(2026, 1, 9, 6, 0, 0, tzinfo=timezone.utc)
        check_scheduleday_lead_time(
            resolved_store=store,
            channel_id=CHANNEL_ID,
            target_date=target,
            now_utc=before_deadline,
            min_lead_days=min_lead_days,
        )


# =========================================================================
# INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001
# =========================================================================


class TestInvScheduledaySeamNoOverlap001:
    """INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001

    If a ScheduleDay's last slot carries past the broadcast-day boundary,
    the next ScheduleDay's first slot MUST NOT start before that carry-in
    slot's end. Content MUST NOT be duplicated across the seam.

    Enforcement lives in InMemoryResolvedStore.store() and force_replace(),
    via validate_scheduleday_seam() called inside the lock when
    programming_day_start_hour is set.

    Derived from: LAW-GRID, LAW-DERIVATION.
    """

    def _make_slot(self, hour, minute, duration_seconds, label="slot"):
        """Build a minimal ResolvedSlot."""
        from retrovue.runtime.schedule_types import (
            ProgramRef,
            ProgramRefType,
            ResolvedAsset,
            ResolvedSlot,
        )

        return ResolvedSlot(
            slot_time=time(hour, minute),
            program_ref=ProgramRef(
                ref_type=ProgramRefType.FILE, ref_id=f"{label}.ts"
            ),
            resolved_asset=ResolvedAsset(
                file_path=f"/media/{label}.ts",
                asset_id=f"asset-{label}",
                content_duration_seconds=duration_seconds,
            ),
            duration_seconds=duration_seconds,
            label=label,
        )

    def _make_resolved(self, contract_clock, slots, day_date=None):
        """Build a ResolvedScheduleDay from explicit slots."""
        from retrovue.runtime.schedule_types import (
            ResolvedScheduleDay,
            SequenceState,
        )

        return ResolvedScheduleDay(
            programming_day_date=day_date or date(2026, 1, 1),
            resolved_slots=slots,
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )

    def test_inv_scheduleday_seam_no_overlap_001_reject_carry_in_overlap(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 -- negative

        Invariant: INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001
        Derived law(s): LAW-GRID, LAW-DERIVATION
        Failure class: Planning
        Scenario: Day N (Jan 1) last slot ends at 07:00 (1h past 06:00
                  boundary). Day N+1 (Jan 2) first slot starts at 06:00.
                  Overlap at [06:00→07:00]. store() must reject.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)

        # Day N: two slots tiling 06:00→07:00+1d (25 hours).
        # Slot A: 06:00→18:00 (12h), Slot B: 18:00→07:00+1d (13h carry-in).
        day_n_slots = [
            self._make_slot(6, 0, 43200, label="day-n-morning"),     # 06:00→18:00
            self._make_slot(18, 0, 46800, label="day-n-overnight"),  # 18:00→07:00+1d
        ]
        day_n = self._make_resolved(
            contract_clock, day_n_slots, day_date=date(2026, 1, 1)
        )
        store.store(CHANNEL_ID, day_n)

        # Day N+1: first slot starts at 06:00 (overlaps carry-in until 07:00).
        day_n1_slots = [
            self._make_slot(6, 0, 43200, label="day-n1-morning"),     # 06:00→18:00
            self._make_slot(18, 0, 43200, label="day-n1-overnight"),  # 18:00→06:00+1d
        ]
        day_n1 = self._make_resolved(
            contract_clock, day_n1_slots, day_date=date(2026, 1, 2)
        )

        with pytest.raises(
            ValueError, match="INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001"
        ):
            store.store(CHANNEL_ID, day_n1)

    def test_inv_scheduleday_seam_no_overlap_001_accept_carry_in_honored(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 -- positive (carry-in honored)

        Invariant: INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001
        Derived law(s): LAW-GRID, LAW-DERIVATION
        Failure class: N/A (positive path)
        Scenario: Day N last slot ends at 07:00 (1h carry-in past 06:00).
                  Day N+1 first slot starts at 07:00. Accepted.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)

        # Day N: carry-in until 07:00.
        day_n_slots = [
            self._make_slot(6, 0, 43200, label="day-n-morning"),     # 06:00→18:00
            self._make_slot(18, 0, 46800, label="day-n-overnight"),  # 18:00→07:00+1d
        ]
        day_n = self._make_resolved(
            contract_clock, day_n_slots, day_date=date(2026, 1, 1)
        )
        store.store(CHANNEL_ID, day_n)

        # Day N+1: first slot starts at 07:00, honoring carry-in.
        day_n1_slots = [
            self._make_slot(7, 0, 39600, label="day-n1-morning"),     # 07:00→18:00
            self._make_slot(18, 0, 43200, label="day-n1-overnight"),  # 18:00→06:00+1d
        ]
        day_n1 = self._make_resolved(
            contract_clock, day_n1_slots, day_date=date(2026, 1, 2)
        )

        # Should not raise — carry-in boundary is honored.
        store.store(CHANNEL_ID, day_n1)
        assert store.exists(CHANNEL_ID, date(2026, 1, 2))

    def test_inv_scheduleday_seam_no_overlap_001_no_carry_in_independent(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001 -- positive (no carry-in)

        Invariant: INV-SCHEDULEDAY-SEAM-NO-OVERLAP-001
        Derived law(s): LAW-GRID, LAW-DERIVATION
        Failure class: N/A (positive path)
        Scenario: Day N ends exactly at 06:00 boundary. Day N+1 starts
                  at 06:00. No carry-in, no overlap. Accepted.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)

        # Day N: exactly tiles 06:00→06:00+1d (no carry-in).
        day_n_slots = [
            self._make_slot(6, 0, 43200, label="day-n-morning"),     # 06:00→18:00
            self._make_slot(18, 0, 43200, label="day-n-overnight"),  # 18:00→06:00+1d
        ]
        day_n = self._make_resolved(
            contract_clock, day_n_slots, day_date=date(2026, 1, 1)
        )
        store.store(CHANNEL_ID, day_n)

        # Day N+1: starts at 06:00 boundary.
        day_n1_slots = [
            self._make_slot(6, 0, 43200, label="day-n1-morning"),     # 06:00→18:00
            self._make_slot(18, 0, 43200, label="day-n1-overnight"),  # 18:00→06:00+1d
        ]
        day_n1 = self._make_resolved(
            contract_clock, day_n1_slots, day_date=date(2026, 1, 2)
        )

        # Should not raise — no carry-in, days are independent.
        store.store(CHANNEL_ID, day_n1)
        assert store.exists(CHANNEL_ID, date(2026, 1, 2))


# =========================================================================
# INV-SCHEDULEDAY-NO-GAPS-001
# =========================================================================


class TestInvScheduledayNoGaps001:
    """INV-SCHEDULEDAY-NO-GAPS-001

    A materialized ResolvedScheduleDay must provide continuous, gap-free
    slot coverage across the full broadcast day, from programming_day_start
    to programming_day_start + 24h. No temporal gaps, no overlaps.

    Enforcement lives in InMemoryResolvedStore.store() and force_replace(),
    via validate_scheduleday_contiguity() called before commit.

    Derived from: LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS.
    """

    def _make_slot(self, hour, minute, duration_seconds, label="slot"):
        """Build a minimal ResolvedSlot."""
        from retrovue.runtime.schedule_types import (
            ProgramRef,
            ProgramRefType,
            ResolvedAsset,
            ResolvedSlot,
        )

        return ResolvedSlot(
            slot_time=time(hour, minute),
            program_ref=ProgramRef(
                ref_type=ProgramRefType.FILE, ref_id=f"{label}.ts"
            ),
            resolved_asset=ResolvedAsset(
                file_path=f"/media/{label}.ts",
                asset_id=f"asset-{label}",
                content_duration_seconds=duration_seconds,
            ),
            duration_seconds=duration_seconds,
            label=label,
        )

    def _make_resolved(self, contract_clock, slots, day_date=None):
        """Build a ResolvedScheduleDay from explicit slots."""
        from retrovue.runtime.schedule_types import (
            ResolvedScheduleDay,
            SequenceState,
        )

        return ResolvedScheduleDay(
            programming_day_date=day_date or date(2026, 1, 1),
            resolved_slots=slots,
            resolution_timestamp=contract_clock.clock.now_utc(),
            sequence_state=SequenceState(),
            program_events=[],
        )

    def test_inv_scheduleday_no_gaps_001_reject_internal_gap(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-NO-GAPS-001 -- negative (internal gap)

        Invariant: INV-SCHEDULEDAY-NO-GAPS-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS
        Failure class: Planning
        Scenario: Broadcast day starts at 06:00 (pds=6). Two slots:
                  A [06:00→12:00] (6h), B [14:00→06:00+1d] (16h).
                  Gap exists at [12:00→14:00] (2h).
                  store() must reject with invariant tag.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)
        slots = [
            self._make_slot(6, 0, 21600, label="morning"),    # 06:00→12:00
            self._make_slot(14, 0, 57600, label="afternoon"),  # 14:00→06:00+1d
        ]
        sd = self._make_resolved(contract_clock, slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001"):
            store.store(CHANNEL_ID, sd)

    def test_inv_scheduleday_no_gaps_001_reject_overlap(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-NO-GAPS-001 -- negative (overlap)

        Invariant: INV-SCHEDULEDAY-NO-GAPS-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS
        Failure class: Planning
        Scenario: Broadcast day starts at 06:00 (pds=6). Two slots:
                  A [06:00→18:00] (12h), B [16:00→06:00+1d] (14h).
                  Overlap at [16:00→18:00] (2h).
                  store() must reject with invariant tag.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)
        slots = [
            self._make_slot(6, 0, 43200, label="daytime"),    # 06:00→18:00
            self._make_slot(16, 0, 50400, label="evening"),    # 16:00→06:00+1d
        ]
        sd = self._make_resolved(contract_clock, slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001"):
            store.store(CHANNEL_ID, sd)

    def test_inv_scheduleday_no_gaps_001_reject_missing_day_start(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-NO-GAPS-001 -- negative (missing day start)

        Invariant: INV-SCHEDULEDAY-NO-GAPS-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS
        Failure class: Planning
        Scenario: Broadcast day starts at 06:00 (pds=6). Single slot covers
                  08:00→06:00+1d (22h). Gap at [06:00→08:00] (2h).
                  store() must reject with invariant tag.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)
        slots = [
            self._make_slot(8, 0, 79200, label="late-start"),  # 08:00→06:00+1d
        ]
        sd = self._make_resolved(contract_clock, slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001"):
            store.store(CHANNEL_ID, sd)

    def test_inv_scheduleday_no_gaps_001_reject_missing_day_end(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-NO-GAPS-001 -- negative (missing day end)

        Invariant: INV-SCHEDULEDAY-NO-GAPS-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS
        Failure class: Planning
        Scenario: Broadcast day starts at 06:00 (pds=6). Single slot covers
                  06:00→02:00+1d (20h). Gap at [02:00→06:00+1d] (4h).
                  store() must reject with invariant tag.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)
        slots = [
            self._make_slot(6, 0, 72000, label="early-end"),  # 06:00→02:00+1d
        ]
        sd = self._make_resolved(contract_clock, slots)

        with pytest.raises(ValueError, match="INV-SCHEDULEDAY-NO-GAPS-001"):
            store.store(CHANNEL_ID, sd)

    def test_inv_scheduleday_no_gaps_001_accept_exact_tiling(
        self, contract_clock
    ):
        """INV-SCHEDULEDAY-NO-GAPS-001 -- positive (exact tiling)

        Invariant: INV-SCHEDULEDAY-NO-GAPS-001
        Derived law(s): LAW-CONTENT-AUTHORITY, LAW-GRID, LAW-LIVENESS
        Failure class: N/A (positive path)
        Scenario: Broadcast day starts at 06:00 (pds=6). Two slots tile exactly:
                  A [06:00→18:00] (12h), B [18:00→06:00+1d] (12h).
                  No gap, no overlap. store() must accept without error.
        """
        from retrovue.runtime.schedule_manager_service import InMemoryResolvedStore

        store = InMemoryResolvedStore(programming_day_start_hour=6)
        slots = [
            self._make_slot(6, 0, 43200, label="daytime"),     # 06:00→18:00
            self._make_slot(18, 0, 43200, label="overnight"),  # 18:00→06:00+1d
        ]
        sd = self._make_resolved(contract_clock, slots)

        # Should not raise — slots tile the full broadcast day.
        store.store(CHANNEL_ID, sd)

        # Verify stored successfully.
        assert store.exists(CHANNEL_ID, date(2026, 1, 1))
        retrieved = store.get(CHANNEL_ID, date(2026, 1, 1))
        assert retrieved is sd


# =========================================================================
# INV-PLAYLOG-NO-GAPS-001
# =========================================================================


class TestInvPlaylogNoGaps001:
    """INV-PLAYLOG-NO-GAPS-001

    The ExecutionEntry sequence for an active channel must be temporally
    contiguous with no gaps within the lookahead window. A gap represents
    a window of time for which no execution authority exists.

    Enforcement: validate_execution_entry_contiguity() standalone function
    in execution_window_store.py.

    Derived from: LAW-LIVENESS, LAW-RUNTIME-AUTHORITY.
    """

    def test_inv_playlog_no_gaps_001_detect_gap(self, contract_clock):
        """INV-PLAYLOG-NO-GAPS-001 -- negative (gap detected)

        Invariant: INV-PLAYLOG-NO-GAPS-001
        Derived law(s): LAW-LIVENESS, LAW-RUNTIME-AUTHORITY
        Failure class: Runtime
        Scenario: Construct ExecutionEntry sequence with a 10-minute gap
                  at [EPOCH+1h, EPOCH+1h10m]. Call
                  validate_execution_entry_contiguity(). Assert raises
                  ValueError matching INV-PLAYLOG-NO-GAPS-001-VIOLATED.
                  Assert fault message includes gap boundaries and channel ID.
        """
        # Two contiguous blocks, then a 10-minute gap, then a third block.
        entries = [
            _make_entry(block_index=0, start_offset_ms=0),                     # [EPOCH, EPOCH+30m]
            _make_entry(block_index=1, start_offset_ms=GRID_BLOCK_MS),         # [EPOCH+30m, EPOCH+1h]
            # Gap: [EPOCH+1h, EPOCH+1h10m]
            _make_entry(
                block_index=2,
                start_offset_ms=GRID_BLOCK_MS * 2 + 10 * 60 * 1000,           # EPOCH+1h10m
            ),
        ]

        with pytest.raises(ValueError, match="INV-PLAYLOG-NO-GAPS-001-VIOLATED") as exc_info:
            validate_execution_entry_contiguity(entries)

        msg = str(exc_info.value)
        assert CHANNEL_ID in msg, "Fault must include channel_id"
        # Gap boundaries: end of block 1 and start of block 2
        gap_start = EPOCH_MS + GRID_BLOCK_MS * 2
        gap_end = EPOCH_MS + GRID_BLOCK_MS * 2 + 10 * 60 * 1000
        assert str(gap_start) in msg, "Fault must include gap start boundary"
        assert str(gap_end) in msg, "Fault must include gap end boundary"

    def test_inv_playlog_no_gaps_001_accept_contiguous(self, contract_clock):
        """INV-PLAYLOG-NO-GAPS-001 -- positive (contiguous sequence)

        Invariant: INV-PLAYLOG-NO-GAPS-001
        Derived law(s): LAW-LIVENESS, LAW-RUNTIME-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: Construct contiguous ExecutionEntry sequence (4 consecutive
                  30-min blocks). Call validate_execution_entry_contiguity().
                  Assert no exception.
        """
        entries = [
            _make_entry(block_index=i, start_offset_ms=i * GRID_BLOCK_MS)
            for i in range(4)
        ]
        # Must not raise — entries are contiguous.
        validate_execution_entry_contiguity(entries)


# =========================================================================
# INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001
# =========================================================================


class TestInvPlaylogDerivedFromPlaylist001:
    """INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001

    Every ExecutionEntry must be traceable to a TransmissionLogEntry,
    except those created by an explicit recorded operator override.
    An ExecutionEntry with no TransmissionLogEntry reference and no
    operator override record MUST NOT be persisted.

    Enforcement: ExecutionWindowStore.add_entries() when
    enforce_derivation_from_playlist=True.

    Derived from: LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY.
    """

    def test_inv_playlog_derived_from_playlist_001_reject_unanchored(
        self, contract_clock
    ):
        """INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 -- negative (unanchored)

        Invariant: INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY
        Failure class: Planning
        Scenario: Construct ExecutionEntry with transmission_log_ref=None and
                  is_operator_override=False. Submit to ExecutionWindowStore
                  with enforce_derivation_from_playlist=True. Assert raises
                  ValueError matching INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001-VIOLATED.
        """
        store = ExecutionWindowStore(enforce_derivation_from_playlist=True)
        entry = _make_entry(
            block_index=0,
            start_offset_ms=0,
            transmission_log_ref=None,
            is_operator_override=False,
        )

        with pytest.raises(
            ValueError, match="INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001-VIOLATED"
        ):
            store.add_entries([entry])

        assert len(store.get_all_entries()) == 0, (
            "INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 VIOLATED: "
            "Store accepted entry without playlist derivation."
        )

    def test_inv_playlog_derived_from_playlist_001_accept_with_ref(
        self, contract_clock
    ):
        """INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 -- positive (with ref)

        Invariant: INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: Construct ExecutionEntry with transmission_log_ref="tl-001".
                  Submit to ExecutionWindowStore with enforcement enabled.
                  Assert accepted.
        """
        store = ExecutionWindowStore(enforce_derivation_from_playlist=True)
        entry = _make_entry(
            block_index=0,
            start_offset_ms=0,
            transmission_log_ref="tl-001",
        )

        store.add_entries([entry])
        assert len(store.get_all_entries()) == 1

    def test_inv_playlog_derived_from_playlist_001_accept_override(
        self, contract_clock
    ):
        """INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001 -- positive (operator override)

        Invariant: INV-PLAYLOG-DERIVED-FROM-PLAYLIST-001
        Derived law(s): LAW-DERIVATION, LAW-RUNTIME-AUTHORITY, LAW-CONTENT-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: Construct ExecutionEntry with transmission_log_ref=None,
                  is_operator_override=True. Submit to ExecutionWindowStore
                  with enforcement enabled. Assert accepted.
        """
        store = ExecutionWindowStore(enforce_derivation_from_playlist=True)
        entry = _make_entry(
            block_index=0,
            start_offset_ms=0,
            transmission_log_ref=None,
            is_operator_override=True,
        )

        store.add_entries([entry])
        assert len(store.get_all_entries()) == 1


# =========================================================================
# INV-PLAYLOG-LOCKED-IMMUTABLE-001
# =========================================================================


class TestInvPlaylogLockedImmutable001:
    """INV-PLAYLOG-LOCKED-IMMUTABLE-001

    ExecutionEntry records in the locked execution window are immutable
    except via atomic override. Entries in the past window are immutable
    unconditionally — no override mechanism applies retroactively.

    Enforcement: ExecutionWindowStore.replace_entry() method.

    Derived from: LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY.
    """

    def test_inv_playlog_locked_immutable_001_reject_locked_no_override(
        self, contract_clock
    ):
        """INV-PLAYLOG-LOCKED-IMMUTABLE-001 -- negative (locked, no override)

        Invariant: INV-PLAYLOG-LOCKED-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY
        Failure class: Runtime
        Scenario: Create locked ExecutionEntry at [EPOCH+15m, EPOCH+45m].
                  Call store.replace_entry() without override. Assert raises
                  ValueError matching INV-PLAYLOG-LOCKED-IMMUTABLE-001-VIOLATED.
                  Assert message includes window status "locked".
        """
        store = ExecutionWindowStore()
        entry = _make_entry(
            block_index=0,
            start_offset_ms=15 * 60 * 1000,    # EPOCH + 15m
            duration_ms=30 * 60 * 1000,          # 30m → ends at EPOCH + 45m
            is_locked=True,
        )
        store.add_entries([entry])

        new_entry = _make_entry(
            block_index=0,
            start_offset_ms=15 * 60 * 1000,
            duration_ms=30 * 60 * 1000,
        )

        with pytest.raises(
            ValueError, match="INV-PLAYLOG-LOCKED-IMMUTABLE-001-VIOLATED"
        ) as exc_info:
            store.replace_entry(
                entry.block_id, new_entry, now_utc_ms=EPOCH_MS
            )

        assert '"locked"' in str(exc_info.value), (
            "Fault message must include window status 'locked'"
        )

    def test_inv_playlog_locked_immutable_001_reject_past_unconditional(
        self, contract_clock
    ):
        """INV-PLAYLOG-LOCKED-IMMUTABLE-001 -- negative (past, unconditional)

        Invariant: INV-PLAYLOG-LOCKED-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY
        Failure class: Runtime
        Scenario: Create ExecutionEntry at [EPOCH+30m, EPOCH+60m]. Call
                  store.replace_entry() with now_utc_ms=EPOCH+2h (entry is
                  past) and override_record_id="or-1". Assert raises
                  ValueError matching INV-PLAYLOG-LOCKED-IMMUTABLE-001-VIOLATED.
                  Assert message includes window status "past".
        """
        store = ExecutionWindowStore()
        entry = _make_entry(
            block_index=0,
            start_offset_ms=30 * 60 * 1000,     # EPOCH + 30m
            duration_ms=30 * 60 * 1000,           # 30m → ends at EPOCH + 60m
        )
        store.add_entries([entry])

        new_entry = _make_entry(
            block_index=0,
            start_offset_ms=30 * 60 * 1000,
            duration_ms=30 * 60 * 1000,
        )

        two_hours_ms = 2 * 60 * 60 * 1000
        with pytest.raises(
            ValueError, match="INV-PLAYLOG-LOCKED-IMMUTABLE-001-VIOLATED"
        ) as exc_info:
            store.replace_entry(
                entry.block_id,
                new_entry,
                now_utc_ms=EPOCH_MS + two_hours_ms,
                override_record_id="or-1",
            )

        assert '"past"' in str(exc_info.value), (
            "Fault message must include window status 'past'"
        )

    def test_inv_playlog_locked_immutable_001_accept_override(
        self, contract_clock
    ):
        """INV-PLAYLOG-LOCKED-IMMUTABLE-001 -- positive (override accepted)

        Invariant: INV-PLAYLOG-LOCKED-IMMUTABLE-001
        Derived law(s): LAW-IMMUTABILITY, LAW-RUNTIME-AUTHORITY
        Failure class: N/A (positive path)
        Scenario: Create locked ExecutionEntry at [EPOCH+10m, EPOCH+40m].
                  Call store.replace_entry() with override_record_id="or-1".
                  Assert accepted. Assert replaced entry is in store.
        """
        store = ExecutionWindowStore()
        original = _make_entry(
            block_index=0,
            start_offset_ms=10 * 60 * 1000,     # EPOCH + 10m
            duration_ms=30 * 60 * 1000,           # 30m → ends at EPOCH + 40m
            is_locked=True,
        )
        store.add_entries([original])

        replacement = _make_entry(
            block_index=0,
            start_offset_ms=10 * 60 * 1000,
            duration_ms=30 * 60 * 1000,
        )

        store.replace_entry(
            original.block_id,
            replacement,
            now_utc_ms=EPOCH_MS,
            override_record_id="or-1",
        )

        entries = store.get_all_entries()
        assert len(entries) == 1
        assert entries[0] is replacement, (
            "Store must contain the replacement entry after override."
        )
