"""
Schedule Manager Phase 1 Contract Tests

Tests the invariants and behaviors defined in:
    docs/contracts/runtime/ScheduleManagerPhase1Contract.md

Status: Implemented
"""

import pytest
from datetime import datetime, time, timedelta

from retrovue.runtime.schedule_types import (
    PlayoutSegment,
    ProgramBlock,
    ScheduledProgram,
    DailyScheduleConfig,
    ScheduleManager,
)
from retrovue.runtime.schedule_manager import DailyScheduleManager


# =============================================================================
# Test Helpers (not part of contract)
# =============================================================================

def find_segment_at(block: ProgramBlock, query_time: datetime) -> PlayoutSegment | None:
    """Test helper: Find the segment containing the given time."""
    for segment in block.segments:
        if segment.start_utc <= query_time < segment.end_utc:
            return segment
    return None


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def daily_config() -> DailyScheduleConfig:
    """Standard test configuration with multiple programs."""
    return DailyScheduleConfig(
        grid_minutes=30,
        programs=[
            # Short programs (fit in one slot)
            ScheduledProgram(time(9, 0), "/media/morning_news.mp4", 1500.0, "Morning News"),  # 25 min
            ScheduledProgram(time(21, 0), "/media/cheers.mp4", 1320.0, "Cheers"),  # 22 min
            ScheduledProgram(time(21, 30), "/media/night_court.mp4", 1380.0, "Night Court"),  # 23 min
            # Multi-slot program (45 min spans 2 slots)
            ScheduledProgram(time(22, 0), "/media/drama.mp4", 2700.0, "Drama"),  # 45 min
            # Exact slot fill (30 min program in 30 min slot)
            ScheduledProgram(time(10, 0), "/media/exact_slot.mp4", 1800.0, "Exact Slot"),  # 30 min
            # Program crossing midnight (90 min starting at 23:00)
            ScheduledProgram(time(23, 0), "/media/late_show.mp4", 5400.0, "Late Show"),  # 90 min
            # Program crossing programming-day boundary (05:30 → 06:30, crosses 06:00)
            ScheduledProgram(time(5, 30), "/media/early_bird.mp4", 3600.0, "Early Bird"),  # 60 min
        ],
        filler_path="/media/filler.mp4",
        filler_duration_seconds=3600.0,
        programming_day_start_hour=6,
    )


@pytest.fixture
def movie_config() -> DailyScheduleConfig:
    """Configuration with a long movie spanning many slots."""
    return DailyScheduleConfig(
        grid_minutes=30,
        programs=[
            ScheduledProgram(time(20, 0), "/media/movie.mp4", 7200.0, "Movie"),  # 120 min = 4 slots
        ],
        filler_path="/media/filler.mp4",
        filler_duration_seconds=3600.0,
        programming_day_start_hour=6,
    )


@pytest.fixture
def empty_config() -> DailyScheduleConfig:
    """Configuration with no scheduled programs (all filler)."""
    return DailyScheduleConfig(
        grid_minutes=30,
        programs=[],
        filler_path="/media/filler.mp4",
        filler_duration_seconds=3600.0,
        programming_day_start_hour=6,
    )


@pytest.fixture
def schedule_manager(daily_config: DailyScheduleConfig) -> ScheduleManager:
    """Create a DailyScheduleManager instance."""
    return DailyScheduleManager(config=daily_config)


@pytest.fixture
def movie_schedule_manager(movie_config: DailyScheduleConfig) -> ScheduleManager:
    """Create a DailyScheduleManager with a long movie."""
    return DailyScheduleManager(config=movie_config)


@pytest.fixture
def empty_schedule_manager(empty_config: DailyScheduleConfig) -> ScheduleManager:
    """Create a DailyScheduleManager with no programs."""
    return DailyScheduleManager(config=empty_config)


# =============================================================================
# Program Selection Tests (P1-T001 through P1-T004)
# =============================================================================

class TestProgramSelection:
    """Tests for program selection behavior."""

    def test_P1_T001_scheduled_slot_returns_correct_program(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T001: Scheduled slot returns correct program."""
        at_time = datetime(2025, 1, 30, 21, 15, 0)  # 9:15 PM
        block = schedule_manager.get_program_at("test-channel", at_time)

        assert block.segments[0].file_path == "/media/cheers.mp4"

    def test_P1_T002_unscheduled_slot_returns_filler_only(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T002: Unscheduled slot returns filler only."""
        at_time = datetime(2025, 1, 30, 14, 15, 0)  # 2:15 PM (no program)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Should be filler only
        assert block.segments[0].file_path == daily_config.filler_path

    def test_P1_T003_adjacent_programs_return_different_content(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T003: Adjacent programs return different content."""
        time_1 = datetime(2025, 1, 30, 21, 15, 0)  # 9:15 PM (Cheers)
        time_2 = datetime(2025, 1, 30, 21, 45, 0)  # 9:45 PM (Night Court)

        block_1 = schedule_manager.get_program_at("test-channel", time_1)
        block_2 = schedule_manager.get_program_at("test-channel", time_2)

        assert block_1.segments[0].file_path == "/media/cheers.mp4"
        assert block_2.segments[0].file_path == "/media/night_court.mp4"

    def test_P1_T004_same_slot_always_returns_same_program(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T004: Same slot always returns same program (determinism)."""
        at_time = datetime(2025, 1, 30, 21, 15, 0)

        results = [
            schedule_manager.get_program_at("test-channel", at_time)
            for _ in range(100)
        ]

        first = results[0]
        for result in results[1:]:
            assert result.segments[0].file_path == first.segments[0].file_path
            assert result.block_start == first.block_start
            assert result.block_end == first.block_end


# =============================================================================
# Multi-Slot Program Tests (P1-T005 through P1-T009)
# =============================================================================

class TestMultiSlotPrograms:
    """Tests for programs spanning multiple grid slots."""

    def test_P1_T005_multi_slot_program_first_slot(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T005: Program spanning two slots - first slot returns program."""
        # Drama is 45 min starting at 22:00
        at_time = datetime(2025, 1, 30, 22, 15, 0)  # 15 min into drama
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/drama.mp4"

        # seek_offset_seconds is offset at block_start (22:00), should be 0
        assert segment.seek_offset_seconds == 0.0

        # file_position at query time = seek_offset + (query - segment.start)
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 900.0  # 15 minutes into the program

    def test_P1_T006_multi_slot_program_second_slot(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T006: Program spanning two slots - second slot returns same program."""
        # Drama is 45 min starting at 22:00, second slot is 22:30-23:00
        at_time = datetime(2025, 1, 30, 22, 35, 0)  # 35 min into drama
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/drama.mp4"

        # seek_offset_seconds is offset at block_start (22:30), should be 30 min
        assert segment.seek_offset_seconds == 1800.0  # 30 minutes

        # file_position at query time = seek_offset + (query - segment.start)
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 2100.0  # 35 minutes into the program

    def test_P1_T007_multi_slot_program_filler_after_end(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T007: Filler appears after multi-slot program ends."""
        # Drama is 45 min starting at 22:00, ends at 22:45
        at_time = datetime(2025, 1, 30, 22, 50, 0)  # 5 min into filler
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == daily_config.filler_path

    def test_P1_T008_program_exactly_fills_multiple_slots(
        self, movie_schedule_manager: ScheduleManager
    ):
        """P1-T008: Program exactly fills multiple slots."""
        # Movie is 120 min starting at 20:00, exactly fills 4 slots
        # (query_time, expected_seek_offset, expected_file_position)
        test_cases = [
            (datetime(2025, 1, 30, 20, 15, 0), 0.0, 900.0),      # Block 1: seek=0, pos=15min
            (datetime(2025, 1, 30, 20, 45, 0), 1800.0, 2700.0),  # Block 2: seek=30min, pos=45min
            (datetime(2025, 1, 30, 21, 15, 0), 3600.0, 4500.0),  # Block 3: seek=60min, pos=75min
            (datetime(2025, 1, 30, 21, 45, 0), 5400.0, 6300.0),  # Block 4: seek=90min, pos=105min
        ]

        for at_time, expected_seek, expected_file_pos in test_cases:
            block = movie_schedule_manager.get_program_at("test-channel", at_time)
            segment = find_segment_at(block, at_time)
            assert segment is not None
            assert segment.file_path == "/media/movie.mp4"

            # Verify seek_offset_seconds (offset at block boundary)
            assert segment.seek_offset_seconds == expected_seek, f"At {at_time}"

            # Verify file_position at query time
            file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
            assert file_position == expected_file_pos, f"At {at_time}"

    def test_P1_T009_long_movie_spans_many_slots(
        self, movie_schedule_manager: ScheduleManager
    ):
        """P1-T009: Long movie spans many consecutive slots."""
        # Movie runs 20:00-22:00 (4 slots)
        # Query each slot
        for slot_offset in range(4):
            at_time = datetime(2025, 1, 30, 20, 0, 0) + timedelta(minutes=slot_offset * 30 + 15)
            block = movie_schedule_manager.get_program_at("test-channel", at_time)

            segment = find_segment_at(block, at_time)
            assert segment is not None
            assert segment.file_path == "/media/movie.mp4", f"Failed at {at_time}"


# =============================================================================
# Program Duration Variants Tests (P1-T010, P1-T011)
# =============================================================================

class TestProgramDurationVariants:
    """Tests for different program duration scenarios."""

    def test_P1_T010_program_shorter_than_slot_includes_filler(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T010: Program shorter than slot includes filler."""
        # Cheers is 22 min, filler from 21:22 to 21:30
        at_time = datetime(2025, 1, 30, 21, 25, 0)  # In filler portion
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == daily_config.filler_path

    def test_P1_T011_program_exactly_fills_slot_no_filler(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T011: Program exactly fills slot has no filler."""
        # exact_slot.mp4 is 30 min at 10:00
        at_time = datetime(2025, 1, 30, 10, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Should be exactly one segment (the program)
        assert len(block.segments) == 1
        assert block.segments[0].file_path == "/media/exact_slot.mp4"
        assert block.segments[0].start_utc == block.block_start
        assert block.segments[0].end_utc == block.block_end


# =============================================================================
# Join-In-Progress Tests (P1-T012 through P1-T015)
# =============================================================================

class TestJoinInProgress:
    """Tests for join-in-progress correctness.

    Key distinction:
    - seek_offset_seconds: offset at segment.start_utc (the block boundary)
    - file_position: where to actually start playback = seek_offset + (join_time - start_utc)
    """

    def test_P1_T012_join_mid_program_first_slot(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T012: Join mid-program in first slot."""
        # Drama starts at 22:00, join at 22:15:30
        at_time = datetime(2025, 1, 30, 22, 15, 30)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/drama.mp4"

        # First slot: seek_offset = 0 (block starts at program start)
        assert segment.seek_offset_seconds == 0.0

        # file_position = seek_offset + (join_time - segment.start)
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 930.0  # 15:30 into the program

    def test_P1_T013_join_mid_program_second_slot(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T013: Join mid-program in second slot."""
        # Drama starts at 22:00, join at 22:35:00
        at_time = datetime(2025, 1, 30, 22, 35, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/drama.mp4"

        # Second slot: seek_offset = 30 min (block starts 30 min into program)
        assert segment.seek_offset_seconds == 1800.0

        # file_position = seek_offset + (join_time - segment.start)
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 2100.0  # 35:00 into the program

    def test_P1_T014_join_during_filler_after_multi_slot_program(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T014: Join during filler after multi-slot program ends."""
        # Drama ends at 22:45, join at 22:50
        at_time = datetime(2025, 1, 30, 22, 50, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == daily_config.filler_path

        # Filler segment starts at 22:45 with seek_offset=0
        assert segment.seek_offset_seconds == 0.0

        # file_position = seek_offset + (join_time - segment.start)
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 300.0  # 5:00 into filler

    def test_P1_T015_join_in_unscheduled_slot(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T015: Join in unscheduled slot."""
        at_time = datetime(2025, 1, 30, 14, 15, 0)  # No program at 14:00
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == daily_config.filler_path

        offset = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert offset == 900.0  # 15:00 into filler


# =============================================================================
# Grid Transition Tests (P1-T016 through P1-T018)
# =============================================================================

class TestGridTransitions:
    """Tests for grid transition behavior."""

    def test_P1_T016_get_next_program_within_multi_slot_program(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T016: get_next_program within multi-slot program."""
        # Drama is at 22:00-22:45, current time is 22:25
        after_time = datetime(2025, 1, 30, 22, 25, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        # Next slot is 22:30, still within drama
        assert block.block_start == datetime(2025, 1, 30, 22, 30, 0)
        segment = block.segments[0]
        assert segment.file_path == "/media/drama.mp4"

    def test_P1_T017_get_next_program_at_end_of_multi_slot_program(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T017: get_next_program at end of multi-slot program."""
        # Drama ends at 22:45, filler from 22:45-23:00
        # Note: late_show starts at 23:00, so we test within the filler portion
        after_time = datetime(2025, 1, 30, 22, 50, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        # Next slot is 23:00, which has late_show
        assert block.block_start == datetime(2025, 1, 30, 23, 0, 0)
        assert block.segments[0].file_path == "/media/late_show.mp4"

    def test_P1_T018_get_next_program_transitions_to_new_program(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T018: get_next_program transitions to new program."""
        # Night Court at 21:30, query after Cheers ends
        after_time = datetime(2025, 1, 30, 21, 25, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        assert block.block_start == datetime(2025, 1, 30, 21, 30, 0)
        assert block.segments[0].file_path == "/media/night_court.mp4"


# =============================================================================
# Programming Day Boundary Tests (P1-T019 through P1-T021)
# =============================================================================

class TestProgrammingDayBoundaries:
    """Tests for programming day boundary handling."""

    def test_P1_T019_multi_slot_program_crossing_midnight(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T019: Multi-slot program crossing midnight."""
        # late_show starts at 23:00 and is 90 min (runs until 00:30)
        # Query at 00:15 on next calendar day
        at_time = datetime(2025, 1, 31, 0, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/late_show.mp4"

        # Offset should be 75 minutes (program started at 23:00)
        offset = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert offset == 4500.0  # 75 minutes

    def test_P1_T020_program_before_day_start_belongs_to_previous_day(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T020: Program at 5:30 AM belongs to previous programming day."""
        at_time = datetime(2025, 1, 31, 5, 45, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Block should be 5:30-6:00 (previous programming day)
        assert block.block_start == datetime(2025, 1, 31, 5, 30, 0)
        assert block.block_end == datetime(2025, 1, 31, 6, 0, 0)

    def test_P1_T021_schedule_wraps_at_programming_day_boundary(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T021: Schedule wraps at programming day boundary."""
        time_before = datetime(2025, 1, 31, 5, 59, 59)
        time_after = datetime(2025, 1, 31, 6, 0, 0)

        block_before = schedule_manager.get_program_at("test-channel", time_before)
        block_after = schedule_manager.get_program_at("test-channel", time_after)

        # Different blocks at programming day boundary
        assert block_before.block_end == datetime(2025, 1, 31, 6, 0, 0)
        assert block_after.block_start == datetime(2025, 1, 31, 6, 0, 0)

    def test_P1_T024_program_crossing_programming_day_boundary(
        self, schedule_manager: ScheduleManager
    ):
        """P1-T024: Program crossing programming-day boundary continues into new day.

        INV-P1-007: Programs may cross programming-day boundaries.

        Early Bird starts at 05:30 (previous programming day) with 60-min duration.
        It crosses the 06:00 programming-day boundary and ends at 06:30.
        Query at 06:15 should return the program at the correct offset.
        """
        # Query at 06:15 on Jan 31 - this is in the NEW programming day
        # but the program started in the PREVIOUS programming day at 05:30
        at_time = datetime(2025, 1, 31, 6, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/early_bird.mp4"

        # Block is 06:00-06:30, program started at 05:30
        # seek_offset = (06:00 - 05:30) = 30 minutes
        assert segment.seek_offset_seconds == 1800.0  # 30 minutes

        # file_position at 06:15 = 30 + 15 = 45 minutes
        file_position = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert file_position == 2700.0  # 45 minutes into the program


# =============================================================================
# Full Coverage Tests (P1-T022, P1-T023)
# =============================================================================

class TestFullCoverage:
    """Tests for full schedule coverage."""

    def test_P1_T022_every_minute_of_24_hours_returns_valid_block(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """P1-T022: Every minute of 24 hours returns valid block."""
        start = datetime(2025, 1, 30, daily_config.programming_day_start_hour, 0, 0)

        previous_block_start = None
        previous_block_end = None

        for minute in range(24 * 60):
            at_time = start + timedelta(minutes=minute)
            block = schedule_manager.get_program_at("test-channel", at_time)

            # Block must contain query time
            assert block.block_start <= at_time < block.block_end, (
                f"Block doesn't contain {at_time}"
            )

            # Check for gaps when transitioning blocks
            if previous_block_start is not None and block.block_start != previous_block_start:
                assert block.block_start == previous_block_end, (
                    f"Gap detected at {at_time}: previous ended {previous_block_end}, "
                    f"current starts {block.block_start}"
                )

            previous_block_start = block.block_start
            previous_block_end = block.block_end

    def test_P1_T023_empty_schedule_is_valid(
        self, empty_schedule_manager: ScheduleManager, empty_config: DailyScheduleConfig
    ):
        """P1-T023: Empty schedule (all filler) is valid."""
        at_time = datetime(2025, 1, 30, 14, 15, 0)
        block = empty_schedule_manager.get_program_at("test-channel", at_time)

        assert len(block.segments) == 1
        assert block.segments[0].file_path == empty_config.filler_path
        assert block.segments[0].start_utc == block.block_start
        assert block.segments[0].end_utc == block.block_end


# =============================================================================
# Phase 0 Invariants Still Apply (Regression Tests)
# =============================================================================

class TestPhase0InvariantsStillApply:
    """Verify Phase 0 invariants still hold in Phase 1."""

    def test_INV_SM_001_grid_alignment(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """INV-SM-001: Grid alignment still applies."""
        at_time = datetime(2025, 1, 30, 21, 17, 23)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Block start must be grid-aligned
        minutes = block.block_start.minute
        assert minutes % daily_config.grid_minutes == 0

    def test_INV_SM_002_determinism(
        self, schedule_manager: ScheduleManager
    ):
        """INV-SM-002: Determinism still applies."""
        at_time = datetime(2025, 1, 30, 21, 15, 0)

        results = [
            schedule_manager.get_program_at("test-channel", at_time)
            for _ in range(50)
        ]

        first = results[0]
        for result in results[1:]:
            assert result.block_start == first.block_start
            assert len(result.segments) == len(first.segments)

    def test_INV_SM_003_complete_coverage(
        self, schedule_manager: ScheduleManager
    ):
        """INV-SM-003: Complete coverage still applies."""
        at_time = datetime(2025, 1, 30, 21, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Segments must cover entire block
        assert block.segments[0].start_utc == block.block_start
        assert block.segments[-1].end_utc == block.block_end

        # No gaps
        for i in range(len(block.segments) - 1):
            assert block.segments[i].end_utc == block.segments[i + 1].start_utc

    def test_INV_SM_006_jump_in_anywhere(
        self, schedule_manager: ScheduleManager
    ):
        """INV-SM-006: Jump-in anywhere still applies."""
        test_times = [
            datetime(2025, 1, 30, 21, 0, 0),    # Start of program
            datetime(2025, 1, 30, 21, 10, 30),  # Mid program
            datetime(2025, 1, 30, 22, 35, 0),   # Mid multi-slot program
            datetime(2025, 1, 30, 14, 15, 0),   # Unscheduled slot
        ]

        for at_time in test_times:
            block = schedule_manager.get_program_at("test-channel", at_time)
            segment = find_segment_at(block, at_time)

            assert segment is not None, f"No segment for {at_time}"
            assert segment.start_utc <= at_time < segment.end_utc


# =============================================================================
# New Phase 1 Invariant Tests
# =============================================================================

class TestPhase1Invariants:
    """Tests for Phase 1 specific invariants."""

    def test_INV_P1_003_programs_never_truncated(
        self, schedule_manager: ScheduleManager
    ):
        """INV-P1-003: Programs are never truncated, they span multiple slots."""
        # Drama is 45 minutes - should span 2 slots, not be truncated
        # Check at minute 35 (in second slot) - should still be drama
        at_time = datetime(2025, 1, 30, 22, 35, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None
        assert segment.file_path == "/media/drama.mp4"

        # Offset should be 35 minutes into the program
        offset = segment.seek_offset_seconds + (at_time - segment.start_utc).total_seconds()
        assert offset == 2100.0  # 35 minutes - NOT truncated

    def test_INV_P1_004_program_slot_coverage(
        self, schedule_manager: ScheduleManager, daily_config: DailyScheduleConfig
    ):
        """INV-P1-004: Slots covered by program don't show filler during program runtime."""
        # Drama is 45 min starting at 22:00
        # At 22:35, should be program NOT filler
        at_time = datetime(2025, 1, 30, 22, 35, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment.file_path == "/media/drama.mp4"
        assert segment.file_path != daily_config.filler_path
