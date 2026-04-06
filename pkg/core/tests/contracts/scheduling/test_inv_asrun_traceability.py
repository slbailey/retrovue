"""
Contract tests for INV-ASRUN-TRACEABILITY-001.

Every AsRun entry must be traceable through the full derivation chain
back to a SchedulePlan.

CROSS-003 (Tier 2): AsRun entry without ExecutionEntry reference is rejected.
CROSS-004 (Tier 2): AsRun chain is fully traversable to originating SchedulePlan.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from retrovue.scheduling.asrun_traceability import (
    AsRunEntry,
    validate_asrun_traceability,
    traverse_derivation_chain,
)
from retrovue.scheduling.execution_entry import ExecutionEntry, derive_execution_entries
from retrovue.scheduling.transmission_log import (
    TransmissionLogEntry,
    derive_transmission_log,
)
from retrovue.runtime.schedule_types import (
    ProgramRef,
    ProgramRefType,
    ResolvedAsset,
    ResolvedScheduleDay,
    ResolvedSlot,
    SequenceState,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EPOCH = datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)
EPOCH_MS = int(EPOCH.timestamp() * 1000)
GRID_BLOCK_MS = 30 * 60 * 1000
CHANNEL_ID = "test-channel"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_slot(*, hour: int, minute: int = 0, duration_seconds: float = 1800.0) -> ResolvedSlot:
    return ResolvedSlot(
        slot_time=time(hour, minute),
        program_ref=ProgramRef(ref_type=ProgramRefType.PROGRAM, ref_id="prog-1"),
        resolved_asset=ResolvedAsset(
            file_path="/media/test.ts",
            asset_id="asset-001",
            title="Test Show",
            content_duration_seconds=duration_seconds,
        ),
        duration_seconds=duration_seconds,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInvAsrunTraceability001:
    """Contract tests for INV-ASRUN-TRACEABILITY-001."""

    def test_cross_003_asrun_without_execution_entry_ref_rejected(self):
        """CROSS-003: AsRun entry with execution_entry_id=NULL is rejected.

        The application layer must reject AsRun records that lack a
        reference to the ExecutionEntry that authorized the broadcast.
        """
        orphan_asrun = AsRunEntry(
            asrun_id="ar-001",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            execution_entry_id=None,  # NULL — violation
        )

        with pytest.raises(
            ValueError,
            match="INV-ASRUN-TRACEABILITY-001-VIOLATED",
        ):
            validate_asrun_traceability(orphan_asrun)

    def test_cross_003_asrun_with_empty_ref_rejected(self):
        """CROSS-003 variant: empty string execution_entry_id is also rejected."""
        orphan_asrun = AsRunEntry(
            asrun_id="ar-002",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            execution_entry_id="",  # empty — violation
        )

        with pytest.raises(
            ValueError,
            match="INV-ASRUN-TRACEABILITY-001-VIOLATED",
        ):
            validate_asrun_traceability(orphan_asrun)

    def test_cross_004_full_chain_traversable(self):
        """CROSS-004: Full derivation chain from AsRun back to SchedulePlan
        is traversable with no broken links.

        Chain: SchedulePlan → ResolvedScheduleDay → TransmissionLogEntry
               → ExecutionEntry → AsRun
        """
        # Step 1: Build SchedulePlan (represented by plan_id)
        plan_id = "plan-001"

        # Step 2: Generate ResolvedScheduleDay from plan
        slot = _make_slot(hour=6)
        schedule_day = ResolvedScheduleDay(
            programming_day_date=date(2026, 1, 1),
            resolved_slots=[slot],
            resolution_timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            sequence_state=SequenceState(),
            plan_id=plan_id,
        )

        # Step 3: Generate TransmissionLogEntry from ScheduleDay
        tl_entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=schedule_day,
            broadcast_day_start_utc_ms=EPOCH_MS,
            grid_block_minutes=30,
        )
        assert len(tl_entries) == 1
        tl_entry = tl_entries[0]

        # Verify ScheduleDay → Plan link
        assert tl_entry.plan_id == plan_id
        assert tl_entry.schedule_day_date == date(2026, 1, 1)

        # Step 4: Generate ExecutionEntry from TransmissionLog
        exec_entries = derive_execution_entries(tl_entries)
        assert len(exec_entries) == 1
        ee = exec_entries[0]

        # Verify ExecutionEntry → TransmissionLog link
        assert ee.transmission_log_ref == tl_entry.entry_id

        # Step 5: Create AsRun record referencing ExecutionEntry
        asrun = AsRunEntry(
            asrun_id="ar-full-chain",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            execution_entry_id=ee.entry_id,
        )

        # Validation passes
        validate_asrun_traceability(asrun)

        # Step 6: Traverse full chain
        chain = traverse_derivation_chain(
            asrun=asrun,
            execution_entry_id=ee.entry_id,
            transmission_log_ref=ee.transmission_log_ref,
            schedule_day_date=tl_entry.schedule_day_date.isoformat(),
            plan_id=tl_entry.plan_id,
        )

        # All five links are non-null
        assert chain.asrun_id == "ar-full-chain"
        assert chain.execution_entry_id == ee.entry_id
        assert chain.transmission_log_ref == tl_entry.entry_id
        assert chain.schedule_day_date == "2026-01-01"
        assert chain.plan_id == plan_id

    def test_cross_004_broken_chain_link_detected(self):
        """A broken link in the derivation chain is detected during traversal."""
        asrun = AsRunEntry(
            asrun_id="ar-broken",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            execution_entry_id="ex-001",
        )

        # Broken link: plan_id is empty
        with pytest.raises(
            ValueError,
            match="INV-ASRUN-TRACEABILITY-001-VIOLATED",
        ):
            traverse_derivation_chain(
                asrun=asrun,
                execution_entry_id="ex-001",
                transmission_log_ref="tl-001",
                schedule_day_date="2026-01-01",
                plan_id="",  # broken link
            )

    def test_valid_asrun_with_ref_accepted(self):
        """Positive path: AsRun with valid execution_entry_id passes validation."""
        valid_asrun = AsRunEntry(
            asrun_id="ar-valid",
            channel_id=CHANNEL_ID,
            start_utc_ms=EPOCH_MS,
            end_utc_ms=EPOCH_MS + GRID_BLOCK_MS,
            asset_path="/media/test.ts",
            execution_entry_id="ex-001",
        )

        # Must not raise
        validate_asrun_traceability(valid_asrun)
