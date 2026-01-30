"""
Schedule Manager Phase 6 Contract Tests

Tests the mid-segment join (seek) functionality defined in:
    docs/contracts/runtime/ScheduleManagerPhase6Contract.md

Phase 6 implements mid-segment join (seek) functionality. When a viewer tunes in
mid-program, playback starts at the correct position within the episode rather
than from the beginning.

Illusion Guarantee: From the viewer's perspective, playback MUST appear as if
the channel has been playing continuously since segment start, regardless of
join time.

Status: Draft
"""

import json
import pytest
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from retrovue.runtime.schedule_types import (
    ProgramRefType,
    ProgramRef,
    ScheduleSlot,
    Episode,
    Program,
    ResolvedAsset,
    ResolvedSlot,
    SequenceState,
    ResolvedScheduleDay,
    EPGEvent,
    Phase3Config,
)
from retrovue.runtime.schedule_manager import Phase3ScheduleManager
from retrovue.runtime.phase3_schedule_service import (
    Phase3ScheduleService,
    InMemorySequenceStore,
    InMemoryResolvedStore,
    JsonFileProgramCatalog,
)
from retrovue.runtime.clock import MasterClock


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_programs_dir(tmp_path: Path) -> Path:
    """Create temporary programs directory with test program."""
    programs_dir = tmp_path / "programs"
    programs_dir.mkdir()

    # Create test_show.json with known durations
    test_program = {
        "program_id": "test_show",
        "name": "Test Show",
        "play_mode": "sequential",
        "episodes": [
            {
                "episode_id": "test-s01e01",
                "title": "Pilot",
                "file_path": "/opt/retrovue/assets/test_s01e01.mp4",
                "duration_seconds": 1800.0,  # 30 minutes
            },
            {
                "episode_id": "test-s01e02",
                "title": "Episode 2",
                "file_path": "/opt/retrovue/assets/test_s01e02.mp4",
                "duration_seconds": 1500.0,  # 25 minutes
            },
        ],
    }

    with open(programs_dir / "test_show.json", "w") as f:
        json.dump(test_program, f)

    return programs_dir


@pytest.fixture
def test_schedules_dir(tmp_path: Path) -> Path:
    """Create temporary schedules directory with test schedule."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()

    # Create test-channel.json
    schedule = {
        "channel_id": "test-channel",
        "slots": [
            {
                "slot_time": "14:00",
                "program_ref": {"type": "program", "id": "test_show"},
                "duration_seconds": 1800,
            },
            {
                "slot_time": "14:30",
                "program_ref": {"type": "program", "id": "test_show"},
                "duration_seconds": 1800,
            },
            {
                "slot_time": "15:00",
                "program_ref": {"type": "program", "id": "test_show"},
                "duration_seconds": 1800,
            },
        ],
    }

    with open(schedules_dir / "test-channel.json", "w") as f:
        json.dump(schedule, f)

    return schedules_dir


@pytest.fixture
def mock_clock() -> MasterClock:
    """Create a mock MasterClock."""
    return MasterClock()


@pytest.fixture
def phase3_service(
    mock_clock: MasterClock,
    test_programs_dir: Path,
    test_schedules_dir: Path,
) -> Phase3ScheduleService:
    """Create Phase3ScheduleService with test fixtures."""
    return Phase3ScheduleService(
        clock=mock_clock,
        programs_dir=test_programs_dir,
        schedules_dir=test_schedules_dir,
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_seconds=3650.0,
        grid_minutes=30,
    )


# =============================================================================
# P6-T001: Offset Calculation - Elapsed Time Correctly Calculated
# =============================================================================


class TestP6T001OffsetCalculation:
    """
    Test INV-P6-001: Core calculates start_offset_ms as elapsed time from segment start.

    Formula:
        if now < segment.start_utc:
            start_offset_ms = 0
        else:
            start_offset_ms = (now - segment.start_utc).total_seconds() * 1000
                            + segment.seek_offset_seconds * 1000
    """

    def test_offset_calculated_from_segment_start(
        self, phase3_service: Phase3ScheduleService
    ):
        """Offset is elapsed time from segment start, not slot start."""
        phase3_service.load_schedule("test-channel")

        # Segment starts at 14:00, query at 14:22:30
        at_time = datetime(2025, 1, 30, 14, 22, 30, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # Elapsed = 22 minutes 30 seconds = 1350 seconds = 1350000 ms
        expected_offset_ms = 22 * 60 * 1000 + 30 * 1000  # 1350000
        assert plan[0]["start_pts"] == expected_offset_ms

    def test_offset_includes_subsecond_precision(
        self, phase3_service: Phase3ScheduleService
    ):
        """Offset calculation preserves subsecond precision."""
        phase3_service.load_schedule("test-channel")

        # Segment starts at 14:00, query at 14:05:00.500 (500ms)
        at_time = datetime(2025, 1, 30, 14, 5, 0, 500000, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # Elapsed = 5 minutes + 500ms = 300500 ms
        expected_offset_ms = 5 * 60 * 1000 + 500  # 300500
        assert plan[0]["start_pts"] == expected_offset_ms


# =============================================================================
# P6-T002: Offset at Segment Start - Should Be Zero
# =============================================================================


class TestP6T002OffsetAtSegmentStart:
    """Test that offset is 0 when joining at segment start."""

    def test_offset_zero_at_exact_segment_start(
        self, phase3_service: Phase3ScheduleService
    ):
        """Offset is 0 when now equals segment.start_utc."""
        phase3_service.load_schedule("test-channel")

        # Query exactly at 14:00:00
        at_time = datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert plan[0]["start_pts"] == 0

    def test_offset_zero_before_segment_start(
        self, phase3_service: Phase3ScheduleService
    ):
        """Per INV-P6-001: if now < segment.start_utc, offset MUST be 0."""
        phase3_service.load_schedule("test-channel")

        # Query before first slot (13:59:00, before 14:00 segment)
        # The schedule service should return next segment with 0 offset
        # or handle this edge case appropriately
        at_time = datetime(2025, 1, 30, 13, 59, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # If segment returned, offset must be 0 (not negative)
        if plan:
            assert plan[0]["start_pts"] >= 0


# =============================================================================
# P6-T003: Offset Mid-Segment - Equals Elapsed Seconds * 1000
# =============================================================================


class TestP6T003OffsetMidSegment:
    """Test offset calculation for mid-segment join scenarios."""

    def test_offset_at_5_minutes(self, phase3_service: Phase3ScheduleService):
        """5 minutes into segment = 300000 ms offset."""
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 5, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert plan[0]["start_pts"] == 5 * 60 * 1000  # 300000

    def test_offset_at_12_minutes_30_seconds(
        self, phase3_service: Phase3ScheduleService
    ):
        """12:30 into segment = 750000 ms offset."""
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 12, 30, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert plan[0]["start_pts"] == (12 * 60 + 30) * 1000  # 750000

    def test_offset_near_segment_end(self, phase3_service: Phase3ScheduleService):
        """Offset near end of 30-minute segment."""
        phase3_service.load_schedule("test-channel")

        # 28 minutes into 30-minute segment
        at_time = datetime(2025, 1, 30, 14, 28, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert plan[0]["start_pts"] == 28 * 60 * 1000  # 1680000


# =============================================================================
# P6-T004 through P6-T010: AIR-Side Tests (Documented for C++ Implementation)
# =============================================================================
#
# The following tests verify AIR (C++) behavior and are documented here
# for completeness. They require C++ test implementation in pkg/air/tests/.
#
# P6-T004: Container seek called
#   - Verify av_seek_frame invoked with AVSEEK_FLAG_BACKWARD
#   - Target timestamp correctly scaled to stream time_base
#
# P6-T005: Decoder buffers flushed
#   - avcodec_flush_buffers called for video decoder after seek
#   - avcodec_flush_buffers called for audio decoder after seek
#
# P6-T006: Video frame admission
#   - Frames with PTS < start_offset_us are decoded but not emitted
#   - First emitted frame has PTS >= start_offset_us
#
# P6-T007: Audio frame admission
#   - Audio frames with PTS < start_offset_us are discarded
#   - Audio and video use same admission threshold
#
# P6-T008: First frame accuracy
#   - first_emitted_pts >= target_pts
#   - first_emitted_pts <= target_pts + max_gop_duration
#
# P6-T009: A/V sync after seek
#   - Audio and video PTS remain synchronized after seek
#   - No drift or desync from seek operation
#
# P6-T010: Seek latency
#   - First output within 5 seconds of seek request (typical GOP)


# =============================================================================
# P6-T011: Zero Offset Skips Seek Logic
# =============================================================================


class TestP6T011ZeroOffset:
    """Test that start_offset_ms=0 results in no seek operation."""

    def test_zero_offset_at_segment_start(
        self, phase3_service: Phase3ScheduleService
    ):
        """start_pts=0 indicates playback from beginning (no seek needed)."""
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # AIR should skip seek logic when start_pts=0
        assert plan[0]["start_pts"] == 0


# =============================================================================
# P6-T012: Near-EOF Seek Handling
# =============================================================================


class TestP6T012NearEOFSeek:
    """Test behavior when calculated offset approaches or exceeds file duration."""

    def test_offset_near_episode_duration(
        self, phase3_service: Phase3ScheduleService
    ):
        """
        When offset approaches episode duration, Core should handle gracefully.

        Episode duration: 1800 seconds (30 minutes)
        If elapsed time exceeds duration, should either:
        - Clamp to valid range
        - Return next segment
        - Signal special handling
        """
        phase3_service.load_schedule("test-channel")

        # Query at 14:29:00 (29 minutes into 30-minute episode)
        at_time = datetime(2025, 1, 30, 14, 29, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # Should return valid playout plan
        assert len(plan) >= 1
        # Offset should be within episode duration
        assert plan[0]["start_pts"] <= 1800 * 1000


# =============================================================================
# Invariant Tests - Core Side
# =============================================================================


class TestINVP6001SeekOffsetCalculation:
    """
    INV-P6-001: Core calculates start_offset_ms as elapsed time from segment start.

    This is the primary invariant for Phase 6 Core behavior.
    """

    def test_formula_elapsed_plus_segment_seek(
        self, phase3_service: Phase3ScheduleService
    ):
        """
        Verify formula: start_offset_ms = (now - segment.start_utc) * 1000
                                        + segment.seek_offset_seconds * 1000

        Note: seek_offset_seconds is for multi-part segments (not tested here).
        """
        phase3_service.load_schedule("test-channel")

        # Segment starts at 14:00, query at 14:15:45
        at_time = datetime(2025, 1, 30, 14, 15, 45, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # elapsed = 15 minutes 45 seconds = 945 seconds
        expected_ms = (15 * 60 + 45) * 1000
        assert plan[0]["start_pts"] == expected_ms

    def test_offset_never_negative(self, phase3_service: Phase3ScheduleService):
        """Offset must never be negative, even with clock drift."""
        phase3_service.load_schedule("test-channel")

        # Various query times
        times = [
            datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 30, 14, 0, 0, 1, tzinfo=timezone.utc),  # 1 microsecond
            datetime(2025, 1, 30, 14, 15, 0, tzinfo=timezone.utc),
        ]

        for at_time in times:
            plan = phase3_service.get_playout_plan_now("test-channel", at_time)
            if plan:
                assert plan[0]["start_pts"] >= 0, f"Negative offset at {at_time}"


class TestIllusionGuarantee:
    """
    Test the Illusion Guarantee: playback MUST appear as if the channel
    has been playing continuously since segment start.

    This is verified by ensuring:
    1. Offset is calculated correctly (Core)
    2. First emitted frame matches offset (AIR)
    3. Audio/video remain synchronized (AIR)
    """

    def test_litmus_scenario(self, phase3_service: Phase3ScheduleService):
        """
        Litmus test from contract:
        1. Schedule shows episode starting at 14:00:00
        2. Tune in at 14:12:30
        3. Verify playback position is approximately 12:30 into episode
        """
        phase3_service.load_schedule("test-channel")

        # Tune in at 14:12:30
        at_time = datetime(2025, 1, 30, 14, 12, 30, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # start_pts should be 12:30 = 750 seconds = 750000 ms
        expected_offset_ms = (12 * 60 + 30) * 1000
        assert plan[0]["start_pts"] == expected_offset_ms

    def test_multiple_viewers_same_offset(
        self, phase3_service: Phase3ScheduleService
    ):
        """
        Multiple viewers joining at the same time should receive
        the same offset (shared timeline).
        """
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 20, 0, tzinfo=timezone.utc)

        # Simulate multiple "viewers" requesting playout plan
        plan1 = phase3_service.get_playout_plan_now("test-channel", at_time)
        plan2 = phase3_service.get_playout_plan_now("test-channel", at_time)
        plan3 = phase3_service.get_playout_plan_now("test-channel", at_time)

        # All should receive identical offset
        assert plan1[0]["start_pts"] == plan2[0]["start_pts"] == plan3[0]["start_pts"]


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases from the Phase 6 contract."""

    def test_segment_transition_boundary(
        self, phase3_service: Phase3ScheduleService
    ):
        """
        Near Segment Boundary: when now is within 5 seconds of segment end,
        behavior should be well-defined.
        """
        phase3_service.load_schedule("test-channel")

        # Query at 14:29:57 (3 seconds before 14:30 segment boundary)
        at_time = datetime(2025, 1, 30, 14, 29, 57, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # Should return valid plan (current or next segment)
        assert len(plan) >= 1
        assert plan[0]["asset_path"]

    def test_offset_is_integer_milliseconds(
        self, phase3_service: Phase3ScheduleService
    ):
        """start_pts must be an integer (milliseconds)."""
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 7, 33, 123456, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert isinstance(plan[0]["start_pts"], int)


# =============================================================================
# Playout Plan Format Tests (Phase 6 specific)
# =============================================================================


class TestPlayoutPlanFormat:
    """Test playout plan format for Phase 6 compatibility."""

    def test_plan_contains_start_pts(self, phase3_service: Phase3ScheduleService):
        """Playout plan must contain start_pts field for seek."""
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 10, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        assert "start_pts" in plan[0]

    def test_plan_start_pts_is_offset_name(
        self, phase3_service: Phase3ScheduleService
    ):
        """
        start_pts is the field name used by Core.
        AIR receives this as start_offset_ms.
        """
        phase3_service.load_schedule("test-channel")

        at_time = datetime(2025, 1, 30, 14, 10, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # start_pts in Core = start_offset_ms in AIR
        # Both represent milliseconds
        start_pts = plan[0]["start_pts"]
        assert start_pts == 10 * 60 * 1000  # 10 minutes in ms
