"""
Contract tests for the vertical slice derivation chain.

Derivation chain:
    SchedulePlan → compile → ResolvedScheduleDay → TransmissionLog → ExecutionEntry

Each step is a pure function. Each boundary enforces specific invariants:
    - INV-PLAN-FULL-COVERAGE-001: zones tile full broadcast day
    - INV-PLAN-GRID-ALIGNMENT-001: zone boundaries are grid multiples
    - INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001: plan_id traced on ScheduleDay
    - INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001: transmission log entries grid-aligned
    - INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001: traceability
    - INV-EXECUTIONENTRY-NO-GAPS-001: contiguous execution entries
"""

from datetime import date, datetime, time, timezone, timedelta
from uuid import uuid4

import pytest

from retrovue.runtime.schedule_types import (
    ProgramRef,
    ProgramRefType,
    ResolvedAsset,
    ResolvedScheduleDay,
    ResolvedSlot,
    SequenceState,
)
from retrovue.scheduling.transmission_log import (
    TransmissionLogEntry,
    derive_transmission_log,
    validate_transmission_log_grid_alignment,
)
from retrovue.scheduling.execution_entry import (
    ExecutionEntry,
    derive_execution_entries,
    validate_execution_entry_contiguity,
)


# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

CHANNEL_ID = "test-channel-001"
PLAN_ID = "test-plan-001"
GRID_BLOCK_MINUTES = 30
PROGRAMMING_DAY_START = time(6, 0)  # 06:00
BROADCAST_DAY = date(2026, 4, 6)
SLOTS_PER_DAY = 48  # 24h / 30min

# Broadcast day starts at 06:00 UTC on April 6, ends 06:00 UTC on April 7
BROADCAST_DAY_START_UTC = datetime(2026, 4, 6, 6, 0, 0, tzinfo=timezone.utc)
BROADCAST_DAY_START_UTC_MS = int(BROADCAST_DAY_START_UTC.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_resolved_slot(index: int) -> ResolvedSlot:
    """Build one 30-minute resolved slot at the given grid index."""
    hour = (6 + (index * 30) // 60) % 24
    minute = (index * 30) % 60
    return ResolvedSlot(
        slot_time=time(hour, minute),
        program_ref=ProgramRef(
            ref_type=ProgramRefType.ASSET,
            ref_id=f"asset-{index:03d}",
        ),
        resolved_asset=ResolvedAsset(
            file_path=f"/media/asset-{index:03d}.mp4",
            asset_id=f"asset-{index:03d}",
            title=f"Program {index}",
            content_duration_seconds=1800.0,
        ),
        duration_seconds=1800.0,
        label="zone-day" if index < 24 else "zone-night",
    )


def _build_fixture_schedule_day() -> ResolvedScheduleDay:
    """Build a fixture ResolvedScheduleDay with 48 x 30-min slots tiling 24h.

    Zone 1 (day):   06:00 - 18:00 (indices 0-23)
    Zone 2 (night): 18:00 - 06:00 (indices 24-47)
    """
    slots = [_make_resolved_slot(i) for i in range(SLOTS_PER_DAY)]
    return ResolvedScheduleDay(
        programming_day_date=BROADCAST_DAY,
        resolved_slots=slots,
        resolution_timestamp=datetime.now(timezone.utc),
        sequence_state=SequenceState(positions={}, as_of=datetime.now(timezone.utc)),
        plan_id=PLAN_ID,
    )


# ===========================================================================
# Step 1: SchedulePlan → ScheduleDay contract tests
# ===========================================================================


class TestScheduleDayDerivation:
    """INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001: plan_id must be traced."""

    def test_plan_id_traced(self):
        """Every ResolvedScheduleDay must carry the plan_id that generated it."""
        day = _build_fixture_schedule_day()
        assert day.plan_id is not None, (
            "INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001-VIOLATED: "
            "ResolvedScheduleDay.plan_id is None"
        )
        assert day.plan_id == PLAN_ID

    def test_no_gaps_full_coverage(self):
        """INV-PLAN-FULL-COVERAGE-001: slots must tile the full broadcast day."""
        day = _build_fixture_schedule_day()
        total_seconds = sum(s.duration_seconds for s in day.resolved_slots)
        expected_seconds = 24 * 3600  # full broadcast day
        assert total_seconds == expected_seconds, (
            f"INV-PLAN-FULL-COVERAGE-001-VIOLATED: "
            f"total={total_seconds}s, expected={expected_seconds}s"
        )

    def test_grid_aligned(self):
        """INV-PLAN-GRID-ALIGNMENT-001: all slot times are grid multiples."""
        day = _build_fixture_schedule_day()
        grid_seconds = GRID_BLOCK_MINUTES * 60
        for slot in day.resolved_slots:
            slot_seconds = slot.slot_time.hour * 3600 + slot.slot_time.minute * 60
            assert slot_seconds % grid_seconds == 0, (
                f"INV-PLAN-GRID-ALIGNMENT-001-VIOLATED: "
                f"slot_time={slot.slot_time} is not grid-aligned "
                f"(grid={GRID_BLOCK_MINUTES}min)"
            )

    def test_slot_count(self):
        """48 slots for a 30-min grid across 24h."""
        day = _build_fixture_schedule_day()
        assert len(day.resolved_slots) == SLOTS_PER_DAY


# ===========================================================================
# Step 2: ScheduleDay → TransmissionLog contract tests
# ===========================================================================


class TestTransmissionLogDerivation:
    """INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001: entries must be grid-aligned."""

    def test_derive_produces_entries(self):
        """derive_transmission_log must produce one entry per resolved slot."""
        day = _build_fixture_schedule_day()
        entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        assert len(entries) == SLOTS_PER_DAY

    def test_entries_are_frozen(self):
        """TransmissionLogEntry must be immutable."""
        day = _build_fixture_schedule_day()
        entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        with pytest.raises(AttributeError):
            entries[0].start_utc_ms = 0  # type: ignore[misc]

    def test_grid_alignment_valid(self):
        """INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001: start/end must align to grid."""
        day = _build_fixture_schedule_day()
        entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        # Must not raise
        validate_transmission_log_grid_alignment(entries, GRID_BLOCK_MINUTES)

    def test_grid_alignment_rejects_misaligned(self):
        """Validation must reject entries with non-grid-aligned boundaries."""
        bad_entry = TransmissionLogEntry(
            entry_id="bad-001",
            channel_id=CHANNEL_ID,
            broadcast_day=BROADCAST_DAY,
            start_utc_ms=BROADCAST_DAY_START_UTC_MS + 1000,  # 1s offset — not aligned
            end_utc_ms=BROADCAST_DAY_START_UTC_MS + 1800_000 + 1000,
            asset_id="asset-000",
            asset_path="/media/asset-000.mp4",
            title="Bad Program",
            plan_id=PLAN_ID,
            schedule_day_date=BROADCAST_DAY,
        )
        with pytest.raises(ValueError, match="INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001"):
            validate_transmission_log_grid_alignment([bad_entry], GRID_BLOCK_MINUTES)

    def test_full_coverage(self):
        """Entries must tile the full broadcast day with no gaps."""
        day = _build_fixture_schedule_day()
        entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        sorted_entries = sorted(entries, key=lambda e: e.start_utc_ms)
        # First entry starts at broadcast day start
        assert sorted_entries[0].start_utc_ms == BROADCAST_DAY_START_UTC_MS
        # Last entry ends 24h later
        expected_end = BROADCAST_DAY_START_UTC_MS + 24 * 3600 * 1000
        assert sorted_entries[-1].end_utc_ms == expected_end
        # No gaps between consecutive entries
        for i in range(len(sorted_entries) - 1):
            assert sorted_entries[i].end_utc_ms == sorted_entries[i + 1].start_utc_ms, (
                f"Gap between entries {i} and {i+1}: "
                f"end={sorted_entries[i].end_utc_ms}, "
                f"next_start={sorted_entries[i+1].start_utc_ms}"
            )

    def test_plan_id_traced(self):
        """Every transmission log entry must carry the originating plan_id."""
        day = _build_fixture_schedule_day()
        entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        for entry in entries:
            assert entry.plan_id == PLAN_ID
            assert entry.schedule_day_date == BROADCAST_DAY


# ===========================================================================
# Step 3: TransmissionLog → ExecutionEntry contract tests
# ===========================================================================


class TestExecutionEntryDerivation:
    """INV-EXECUTIONENTRY-NO-GAPS-001 + INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001."""

    def _derive_chain(self) -> tuple[list[TransmissionLogEntry], list[ExecutionEntry]]:
        """Helper: run the full derivation chain up to ExecutionEntry."""
        day = _build_fixture_schedule_day()
        tl_entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        exec_entries = derive_execution_entries(tl_entries)
        return tl_entries, exec_entries

    def test_derive_produces_entries(self):
        """One ExecutionEntry per TransmissionLogEntry."""
        tl_entries, exec_entries = self._derive_chain()
        assert len(exec_entries) == len(tl_entries)

    def test_entries_are_frozen(self):
        """ExecutionEntry must be immutable."""
        _, exec_entries = self._derive_chain()
        with pytest.raises(AttributeError):
            exec_entries[0].start_utc_ms = 0  # type: ignore[misc]

    def test_traceability(self):
        """INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001:
        every ExecutionEntry must reference a TransmissionLogEntry."""
        tl_entries, exec_entries = self._derive_chain()
        tl_ids = {e.entry_id for e in tl_entries}
        for ex in exec_entries:
            assert ex.transmission_log_ref in tl_ids, (
                "INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001-VIOLATED: "
                f"ExecutionEntry {ex.entry_id} references unknown "
                f"transmission_log_ref={ex.transmission_log_ref}"
            )

    def test_contiguity_valid(self):
        """INV-EXECUTIONENTRY-NO-GAPS-001: execution entries must be contiguous."""
        _, exec_entries = self._derive_chain()
        validate_execution_entry_contiguity(exec_entries)

    def test_contiguity_rejects_gap(self):
        """Validation must reject entries with gaps."""
        e1 = ExecutionEntry(
            entry_id="ex-001",
            channel_id=CHANNEL_ID,
            start_utc_ms=0,
            end_utc_ms=1800_000,
            asset_path="/media/a.mp4",
            transmission_log_ref="tl-001",
        )
        e2 = ExecutionEntry(
            entry_id="ex-002",
            channel_id=CHANNEL_ID,
            start_utc_ms=1800_000 + 1000,  # 1s gap
            end_utc_ms=3600_000 + 1000,
            asset_path="/media/b.mp4",
            transmission_log_ref="tl-002",
        )
        with pytest.raises(ValueError, match="INV-EXECUTIONENTRY-NO-GAPS-001"):
            validate_execution_entry_contiguity([e1, e2])

    def test_asset_path_carried(self):
        """ExecutionEntry must carry the asset_path for playout."""
        _, exec_entries = self._derive_chain()
        for ex in exec_entries:
            assert ex.asset_path, f"ExecutionEntry {ex.entry_id} has empty asset_path"


# ===========================================================================
# Step 4: End-to-end derivation chain test
# ===========================================================================


class TestVerticalSliceEndToEnd:
    """Full chain: Plan → ScheduleDay → TransmissionLog → ExecutionEntry.

    Asserts every invariant at every boundary in a single pass.
    """

    def test_full_derivation_chain(self):
        """Plan → ScheduleDay → TransmissionLog → ExecutionEntry.

        Invariants enforced:
        - INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
        - INV-PLAN-FULL-COVERAGE-001
        - INV-PLAN-GRID-ALIGNMENT-001
        - INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001
        - INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001
        - INV-EXECUTIONENTRY-NO-GAPS-001
        """
        # --- ScheduleDay ---
        schedule_day = _build_fixture_schedule_day()

        # INV-SCHEDULEDAY-DERIVATION-TRACEABLE-001
        assert schedule_day.plan_id == PLAN_ID

        # INV-PLAN-FULL-COVERAGE-001
        total_sec = sum(s.duration_seconds for s in schedule_day.resolved_slots)
        assert total_sec == 24 * 3600

        # INV-PLAN-GRID-ALIGNMENT-001
        grid_sec = GRID_BLOCK_MINUTES * 60
        for slot in schedule_day.resolved_slots:
            slot_sec = slot.slot_time.hour * 3600 + slot.slot_time.minute * 60
            assert slot_sec % grid_sec == 0

        # --- TransmissionLog ---
        tl_entries = derive_transmission_log(
            channel_id=CHANNEL_ID,
            schedule_day=schedule_day,
            broadcast_day_start_utc_ms=BROADCAST_DAY_START_UTC_MS,
            grid_block_minutes=GRID_BLOCK_MINUTES,
        )
        assert len(tl_entries) == SLOTS_PER_DAY

        # INV-TRANSMISSIONLOG-GRID-ALIGNMENT-001
        validate_transmission_log_grid_alignment(tl_entries, GRID_BLOCK_MINUTES)

        # Plan traceability through transmission log
        for entry in tl_entries:
            assert entry.plan_id == PLAN_ID

        # --- ExecutionEntry ---
        exec_entries = derive_execution_entries(tl_entries)
        assert len(exec_entries) == SLOTS_PER_DAY

        # INV-EXECUTIONENTRY-DERIVED-FROM-TRANSMISSIONLOG-001
        tl_ids = {e.entry_id for e in tl_entries}
        for ex in exec_entries:
            assert ex.transmission_log_ref in tl_ids

        # INV-EXECUTIONENTRY-NO-GAPS-001
        validate_execution_entry_contiguity(exec_entries)

        # End-to-end: first entry starts at broadcast day start,
        # last entry ends 24h later
        sorted_exec = sorted(exec_entries, key=lambda e: e.start_utc_ms)
        assert sorted_exec[0].start_utc_ms == BROADCAST_DAY_START_UTC_MS
        expected_end = BROADCAST_DAY_START_UTC_MS + 24 * 3600 * 1000
        assert sorted_exec[-1].end_utc_ms == expected_end
