"""
Schedule Manager Contract Tests

Tests the invariants and behaviors defined in:
    docs/contracts/runtime/ScheduleManagerContract.md

Status: Design (pre-implementation)
    These tests define expected behavior. They will FAIL until
    ScheduleManager is implemented. This is intentional.
"""

import pytest
from datetime import datetime, timedelta

# Import canonical types from shared module (Issue 1 fix)
from retrovue.runtime.schedule_types import (
    PlayoutSegment,
    ProgramBlock,
    SimpleGridConfig,
    ScheduleManager,
)


# =============================================================================
# Test Helpers (not part of contract - Issue 4 fix)
# =============================================================================

def find_segment_at(block: ProgramBlock, time: datetime) -> PlayoutSegment | None:
    """
    Test helper: Find the segment containing the given time.

    NOTE: This is a test utility, NOT part of the ScheduleManager contract.
    ProgramBlock is a data structure; lookup logic belongs in calling code.
    """
    for segment in block.segments:
        if segment.start_utc <= time < segment.end_utc:
            return segment
    return None


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def simple_config() -> SimpleGridConfig:
    """Standard test configuration: 30-min grid, 22-min main show."""
    return SimpleGridConfig(
        grid_minutes=30,
        main_show_path="/media/samplecontent.mp4",
        main_show_duration_seconds=1320.0,  # 22 minutes
        filler_path="/media/filler.mp4",
        filler_duration_seconds=3600.0,  # 60 minutes (more than enough)
        programming_day_start_hour=6,
    )


@pytest.fixture
def schedule_manager(simple_config: SimpleGridConfig) -> ScheduleManager:
    """Create a ScheduleManager instance."""
    from retrovue.runtime.schedule_manager import SimpleGridScheduleManager
    return SimpleGridScheduleManager(config=simple_config)


# =============================================================================
# Invariant Tests (INV-SM-*)
# =============================================================================

class TestScheduleManagerInvariants:
    """Tests for Schedule Manager invariants."""

    def test_INV_SM_001_grid_alignment(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        INV-SM-001: Main show MUST start exactly at grid boundaries.
        """
        # Test various times throughout the day
        test_times = [
            datetime(2025, 1, 30, 9, 17, 23),   # Mid-slot
            datetime(2025, 1, 30, 9, 0, 0),     # Exact boundary
            datetime(2025, 1, 30, 9, 29, 59),   # Just before boundary
            datetime(2025, 1, 30, 14, 45, 30),  # Afternoon
            datetime(2025, 1, 30, 23, 15, 0),   # Late night
        ]

        for at_time in test_times:
            block = schedule_manager.get_program_at("test-channel", at_time)

            # block_start must be aligned to grid
            minutes_since_day_start = (
                (block.block_start.hour - simple_config.programming_day_start_hour) * 60
                + block.block_start.minute
            )
            assert minutes_since_day_start % simple_config.grid_minutes == 0, (
                f"block_start {block.block_start} not aligned to {simple_config.grid_minutes}-min grid"
            )

            # First segment must start at block_start
            assert block.segments[0].start_utc == block.block_start, (
                "First segment must start at block_start"
            )

    def test_INV_SM_002_deterministic_calculation(
        self, schedule_manager: ScheduleManager
    ):
        """
        INV-SM-002: Same inputs MUST produce same outputs.
        """
        at_time = datetime(2025, 1, 30, 9, 17, 23)
        channel_id = "test-channel"

        # Call 100 times
        results = [
            schedule_manager.get_program_at(channel_id, at_time)
            for _ in range(100)
        ]

        # All results must be identical
        first = results[0]
        for i, result in enumerate(results[1:], start=2):
            assert result.block_start == first.block_start, f"Call {i}: block_start differs"
            assert result.block_end == first.block_end, f"Call {i}: block_end differs"
            assert len(result.segments) == len(first.segments), f"Call {i}: segment count differs"
            for j, (seg, first_seg) in enumerate(zip(result.segments, first.segments)):
                assert seg.start_utc == first_seg.start_utc, f"Call {i}, segment {j}: start differs"
                assert seg.end_utc == first_seg.end_utc, f"Call {i}, segment {j}: end differs"
                assert seg.file_path == first_seg.file_path, f"Call {i}, segment {j}: path differs"

    def test_INV_SM_003_complete_coverage(
        self, schedule_manager: ScheduleManager
    ):
        """
        INV-SM-003: Every moment within grid slot MUST be covered by exactly one segment.
        """
        at_time = datetime(2025, 1, 30, 9, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Segments must cover [block_start, block_end) completely
        assert block.segments[0].start_utc == block.block_start, "Gap at start of block"
        assert block.segments[-1].end_utc == block.block_end, "Gap at end of block"

        # No gaps between segments
        for i in range(len(block.segments) - 1):
            current = block.segments[i]
            next_seg = block.segments[i + 1]
            assert current.end_utc == next_seg.start_utc, (
                f"Gap between segment {i} (ends {current.end_utc}) "
                f"and segment {i+1} (starts {next_seg.start_utc})"
            )

        # No overlaps
        for i in range(len(block.segments) - 1):
            current = block.segments[i]
            next_seg = block.segments[i + 1]
            assert current.end_utc <= next_seg.start_utc, (
                f"Overlap between segment {i} and {i+1}"
            )

    def test_INV_SM_004_hard_cut_at_grid_boundary(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        INV-SM-004: Filler MUST be truncated at grid boundary.
        """
        at_time = datetime(2025, 1, 30, 9, 25, 0)  # In filler portion
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Find filler segment (second segment)
        assert len(block.segments) >= 2, "Expected main show + filler segments"
        filler_segment = block.segments[1]

        # Filler must end exactly at block_end
        assert filler_segment.end_utc == block.block_end, (
            f"Filler ends at {filler_segment.end_utc}, expected {block.block_end}"
        )

        # Filler duration should be less than filler file duration
        expected_filler_duration = (
            simple_config.grid_minutes * 60 - simple_config.main_show_duration_seconds
        )
        assert filler_segment.duration_seconds == expected_filler_duration, (
            f"Filler duration {filler_segment.duration_seconds}s, "
            f"expected {expected_filler_duration}s (truncated)"
        )

    def test_INV_SM_005_main_show_never_truncated(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        INV-SM-005: Main show always plays full duration.
        """
        at_time = datetime(2025, 1, 30, 9, 10, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # First segment is main show
        main_segment = block.segments[0]
        assert main_segment.file_path == simple_config.main_show_path
        assert main_segment.duration_seconds == simple_config.main_show_duration_seconds, (
            f"Main show duration {main_segment.duration_seconds}s, "
            f"expected {simple_config.main_show_duration_seconds}s"
        )

    def test_INV_SM_006_jump_in_anywhere(
        self, schedule_manager: ScheduleManager
    ):
        """
        INV-SM-006: Any wall-clock time MUST map to correct file + offset.
        """
        # Test jump-in at various points
        test_times = [
            datetime(2025, 1, 30, 9, 0, 0),    # Exact start
            datetime(2025, 1, 30, 9, 10, 30),  # Mid main show
            datetime(2025, 1, 30, 9, 21, 59),  # End of main show
            datetime(2025, 1, 30, 9, 22, 0),   # Start of filler
            datetime(2025, 1, 30, 9, 26, 15),  # Mid filler
            datetime(2025, 1, 30, 9, 29, 59),  # End of filler
        ]

        for at_time in test_times:
            block = schedule_manager.get_program_at("test-channel", at_time)
            segment = find_segment_at(block, at_time)

            assert segment is not None, f"No segment found for time {at_time}"
            assert segment.start_utc <= at_time < segment.end_utc, (
                f"Segment [{segment.start_utc}, {segment.end_utc}) doesn't contain {at_time}"
            )

    # =========================================================================
    # INV-SM-007: No System Clock Access
    #
    # NOTE: This is a DESIGN CONSTRAINT, not a runtime-testable behavior.
    # An implementation could call datetime.now() once, cache it, and still
    # pass determinism tests. This invariant is enforced via CODE REVIEW,
    # not automated testing.
    #
    # The test below verifies a necessary (but not sufficient) condition:
    # that outputs are deterministic regardless of when the test runs.
    # =========================================================================

    def test_INV_SM_007_determinism_necessary_for_no_clock_access(
        self, schedule_manager: ScheduleManager
    ):
        """
        INV-SM-007: Partial verification - determinism is necessary for no clock access.

        DESIGN CONSTRAINT: ScheduleManager MUST NOT access system time directly.
        This test verifies a necessary condition (determinism) but cannot prove
        the implementation doesn't call datetime.now(). Full enforcement requires
        code review.
        """
        # Use a fixed time far in the past - if implementation uses system clock,
        # results would vary or be obviously wrong
        fixed_time = datetime(2020, 6, 15, 14, 23, 45)

        # Call multiple times - should always return the same result
        results = [
            schedule_manager.get_program_at("test-channel", fixed_time)
            for _ in range(10)
        ]

        first = results[0]
        for result in results[1:]:
            assert result.block_start == first.block_start
            assert result.block_end == first.block_end

    # =========================================================================
    # INV-SM-008: Configuration Snapshot Consistency
    #
    # NOTE: The full invariant ("configuration read once per call") cannot be
    # tested without injecting mutable config and observing mid-call behavior.
    # This test verifies that returned values MATCH the config, not that the
    # config was read exactly once.
    # =========================================================================

    def test_INV_SM_008_returned_values_match_config(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        INV-SM-008: Partial verification - returned values match configuration.

        This test verifies that block/segment properties align with config values.
        It does NOT verify snapshot-at-call-time behavior (would require mutable
        config injection).
        """
        at_time = datetime(2025, 1, 30, 9, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Block duration must match grid_minutes
        expected_duration = simple_config.grid_minutes * 60
        actual_duration = (block.block_end - block.block_start).total_seconds()
        assert actual_duration == expected_duration, (
            f"Block duration {actual_duration}s doesn't match grid {expected_duration}s"
        )

        # Main show duration must match configuration
        main_segment = block.segments[0]
        assert main_segment.duration_seconds == simple_config.main_show_duration_seconds, (
            f"Main show duration {main_segment.duration_seconds}s doesn't match "
            f"config {simple_config.main_show_duration_seconds}s"
        )


# =============================================================================
# Behavior Tests (B-SM-*)
# =============================================================================

class TestScheduleManagerBehavior:
    """Tests for Schedule Manager behaviors."""

    def test_B_SM_001_program_block_contains_query_time(
        self, schedule_manager: ScheduleManager
    ):
        """
        B-SM-001: Returned block MUST contain query time.
        """
        at_time = datetime(2025, 1, 30, 14, 23, 45)
        block = schedule_manager.get_program_at("test-channel", at_time)

        assert block.block_start <= at_time < block.block_end, (
            f"Block [{block.block_start}, {block.block_end}) doesn't contain {at_time}"
        )

    def test_B_SM_002_next_program_boundary_semantics(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        B-SM-002: Next program boundary semantics.

        - If after_time is exactly on a grid boundary, return that boundary's block
        - If after_time is between boundaries, return the next boundary's block
        """
        # Mid-block: should return next boundary
        after_time = datetime(2025, 1, 30, 9, 28, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        assert block.block_start >= after_time, (
            f"Next block starts at {block.block_start}, expected >= {after_time}"
        )

        expected_start = datetime(2025, 1, 30, 9, 30, 0)
        assert block.block_start == expected_start, (
            f"Next block starts at {block.block_start}, expected {expected_start}"
        )

    def test_B_SM_002b_exact_boundary_belongs_to_new_block(
        self, schedule_manager: ScheduleManager
    ):
        """
        B-SM-002: When after_time is exactly on a grid boundary,
        that boundary's block is returned (boundary belongs to NEW block).
        """
        # Exactly on boundary
        after_time = datetime(2025, 1, 30, 9, 30, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        # Should return the 9:30-10:00 block, NOT the 10:00-10:30 block
        assert block.block_start == datetime(2025, 1, 30, 9, 30, 0), (
            f"Boundary case: expected 9:30 block, got {block.block_start}"
        )
        assert block.block_end == datetime(2025, 1, 30, 10, 0, 0)

    def test_B_SM_002c_just_after_boundary(
        self, schedule_manager: ScheduleManager
    ):
        """
        B-SM-002: When after_time is just after a boundary,
        return the NEXT boundary's block.
        """
        # Just after boundary (1 millisecond)
        after_time = datetime(2025, 1, 30, 9, 30, 0, 1000)  # 9:30:00.001
        block = schedule_manager.get_next_program("test-channel", after_time)

        # Should return the 10:00-10:30 block
        assert block.block_start == datetime(2025, 1, 30, 10, 0, 0), (
            f"Just-after-boundary case: expected 10:00 block, got {block.block_start}"
        )

    def test_B_SM_003_segments_are_contiguous(
        self, schedule_manager: ScheduleManager
    ):
        """
        B-SM-003: Segments must be contiguous with no gaps.
        """
        at_time = datetime(2025, 1, 30, 9, 15, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # First segment starts at block_start
        assert block.segments[0].start_utc == block.block_start

        # Segments are contiguous
        for i in range(len(block.segments) - 1):
            assert block.segments[i].end_utc == block.segments[i + 1].start_utc

        # Last segment ends at block_end
        assert block.segments[-1].end_utc == block.block_end

    def test_B_SM_005_programming_day_boundary(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        B-SM-005: Grid slots calculated relative to programming day start.
        """
        # 5:45 AM is within the PREVIOUS programming day (day starts at 6 AM)
        at_time = datetime(2025, 1, 30, 5, 45, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        # Block should be 5:30-6:00 (last slot of previous day)
        assert block.block_start == datetime(2025, 1, 30, 5, 30, 0)
        assert block.block_end == datetime(2025, 1, 30, 6, 0, 0)


# =============================================================================
# Specific Test Cases (SM-*)
# =============================================================================

class TestScheduleManagerSpecific:
    """Specific test cases from the contract."""

    def test_SM_001_grid_boundary_alignment(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-001: Verify grid boundary alignment for 9:17:23.
        """
        at_time = datetime(2025, 1, 30, 9, 17, 23)
        block = schedule_manager.get_program_at("test-channel", at_time)

        assert block.block_start == datetime(2025, 1, 30, 9, 0, 0)
        assert block.block_end == datetime(2025, 1, 30, 9, 30, 0)

    def test_SM_002_main_show_segment(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        SM-002: Verify main show segment properties.
        """
        at_time = datetime(2025, 1, 30, 9, 10, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        main_segment = block.segments[0]
        assert main_segment.file_path == simple_config.main_show_path
        assert main_segment.start_utc == datetime(2025, 1, 30, 9, 0, 0)
        assert main_segment.end_utc == datetime(2025, 1, 30, 9, 22, 0)
        assert main_segment.seek_offset_seconds == 0

    def test_SM_003_filler_segment(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        SM-003: Verify filler segment properties.
        """
        at_time = datetime(2025, 1, 30, 9, 25, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        assert len(block.segments) >= 2
        filler_segment = block.segments[1]

        assert filler_segment.file_path == simple_config.filler_path
        assert filler_segment.start_utc == datetime(2025, 1, 30, 9, 22, 0)
        assert filler_segment.end_utc == datetime(2025, 1, 30, 9, 30, 0)  # Hard cut
        assert filler_segment.seek_offset_seconds == 0

    def test_SM_004_filler_truncation(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        SM-004: Filler file is 60 min but only 8 min used.
        """
        at_time = datetime(2025, 1, 30, 9, 25, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        filler_segment = block.segments[1]
        # Filler duration should be 8 minutes (480 seconds), not 60 minutes
        assert filler_segment.duration_seconds == 480.0

    def test_SM_005_jump_in_mid_main_show(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-005: Jump in at 9:15:30 - should be 930 seconds into main show.
        """
        at_time = datetime(2025, 1, 30, 9, 15, 30)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None

        # Calculate file position
        file_position = (
            segment.seek_offset_seconds
            + (at_time - segment.start_utc).total_seconds()
        )
        assert file_position == 930.0  # 15:30 into the file

    def test_SM_006_jump_in_mid_filler(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-006: Jump in at 9:26:00 - should be 240 seconds into filler.
        """
        at_time = datetime(2025, 1, 30, 9, 26, 0)
        block = schedule_manager.get_program_at("test-channel", at_time)

        segment = find_segment_at(block, at_time)
        assert segment is not None

        # Calculate file position
        file_position = (
            segment.seek_offset_seconds
            + (at_time - segment.start_utc).total_seconds()
        )
        assert file_position == 240.0  # 4 minutes into filler

    def test_SM_007_next_program_calculation(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-007: Next program after 9:28:00 should be 9:30-10:00.
        """
        after_time = datetime(2025, 1, 30, 9, 28, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        assert block.block_start == datetime(2025, 1, 30, 9, 30, 0)
        assert block.block_end == datetime(2025, 1, 30, 10, 0, 0)

    def test_SM_007b_next_program_exact_boundary(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-007b: Next program at exactly 9:30:00 returns 9:30-10:00 block.
        Boundary belongs to the new block.
        """
        after_time = datetime(2025, 1, 30, 9, 30, 0)
        block = schedule_manager.get_next_program("test-channel", after_time)

        assert block.block_start == datetime(2025, 1, 30, 9, 30, 0)
        assert block.block_end == datetime(2025, 1, 30, 10, 0, 0)

    def test_SM_007c_next_program_just_after_boundary(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-007c: Next program at 9:30:00.001 returns 10:00-10:30 block.
        """
        after_time = datetime(2025, 1, 30, 9, 30, 0, 1000)
        block = schedule_manager.get_next_program("test-channel", after_time)

        assert block.block_start == datetime(2025, 1, 30, 10, 0, 0)
        assert block.block_end == datetime(2025, 1, 30, 10, 30, 0)

    def test_SM_008_determinism(
        self, schedule_manager: ScheduleManager
    ):
        """
        SM-008: 100 calls with same input must return identical results.
        """
        at_time = datetime(2025, 1, 30, 9, 17, 23)

        results = [
            schedule_manager.get_program_at("test-channel", at_time)
            for _ in range(100)
        ]

        first = results[0]
        for result in results[1:]:
            assert result.block_start == first.block_start
            assert result.block_end == first.block_end

    def test_SM_010_full_24_hour_loop(
        self, schedule_manager: ScheduleManager, simple_config: SimpleGridConfig
    ):
        """
        SM-010: Every minute of 24 hours must return valid block.
        """
        # Start at programming day start
        start = datetime(2025, 1, 30, simple_config.programming_day_start_hour, 0, 0)

        previous_block_start = None
        previous_block_end = None

        # Check every minute for 24 hours
        for minute in range(24 * 60):
            at_time = start + timedelta(minutes=minute)
            block = schedule_manager.get_program_at("test-channel", at_time)

            # Block must contain the query time
            assert block.block_start <= at_time < block.block_end, (
                f"Block doesn't contain {at_time}"
            )

            # Check for gaps when transitioning to a new block
            if previous_block_start is not None and block.block_start != previous_block_start:
                # We've moved to a new block - verify no gap
                assert block.block_start == previous_block_end, (
                    f"Gap detected: previous ended {previous_block_end}, "
                    f"current starts {block.block_start}"
                )

            previous_block_start = block.block_start
            previous_block_end = block.block_end
