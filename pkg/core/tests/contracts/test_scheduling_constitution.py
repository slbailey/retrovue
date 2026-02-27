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
