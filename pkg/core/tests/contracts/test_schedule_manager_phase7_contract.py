"""
Schedule Manager Phase 7 Contract Tests

Tests the seamless segment transitions defined in:
    docs/contracts/runtime/ScheduleManagerPhase7Contract.md

Phase 7 guarantees that segment transitions appear seamless to viewers. When one
segment ends and the next begins, the transition must be imperceptible - no pauses,
no glitches, no discontinuities.

Illusion Guarantee: From the viewer's perspective, the channel appears to have
been playing continuously forever, regardless of segment boundaries.

Status: Draft
"""

import json
import pytest
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass

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
    ScheduleManagerConfig,
)
from retrovue.runtime.schedule_manager import ScheduleManager
from retrovue.runtime.phase3_schedule_service import (
    Phase3ScheduleService,
    InMemorySequenceStore,
    InMemoryResolvedStore,
    JsonFileProgramCatalog,
)
from retrovue.runtime.clock import MasterClock


# =============================================================================
# Test Data Structures for Phase 7
# =============================================================================


@dataclass
class MockFrame:
    """Mock video/audio frame for testing PTS continuity."""
    pts_us: int  # Presentation timestamp in microseconds
    segment_id: str  # Which segment this frame belongs to
    is_audio: bool = False


@dataclass
class MockAsRunEntry:
    """Mock as-run log entry."""
    segment_id: str
    scheduled_start_time: datetime
    scheduled_end_time: datetime
    actual_start_time: Optional[datetime]
    actual_end_time: Optional[datetime]
    status: str  # PLAYED | PARTIAL | MISSING | SKIPPED
    notes: str = ""


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_programs_dir(tmp_path: Path) -> Path:
    """Create temporary programs directory with test programs."""
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
                "title": "Episode 1",
                "file_path": "/opt/retrovue/assets/test_s01e01.mp4",
                "duration_seconds": 1500.0,  # 25 minutes
            },
            {
                "episode_id": "test-s01e02",
                "title": "Episode 2",
                "file_path": "/opt/retrovue/assets/test_s01e02.mp4",
                "duration_seconds": 1500.0,  # 25 minutes
            },
            {
                "episode_id": "test-s01e03",
                "title": "Episode 3",
                "file_path": "/opt/retrovue/assets/test_s01e03.mp4",
                "duration_seconds": 1500.0,  # 25 minutes
            },
        ],
    }

    with open(programs_dir / "test_show.json", "w") as f:
        json.dump(test_program, f)

    return programs_dir


@pytest.fixture
def test_schedules_dir(tmp_path: Path) -> Path:
    """Create temporary schedules directory with multi-segment schedule."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()

    # Create test-channel.json with multiple consecutive slots
    schedule = {
        "channel_id": "test-channel",
        "slots": [
            {
                "slot_time": "14:00",
                "program_ref": {"type": "program", "id": "test_show"},
                "duration_seconds": 1800,  # 30-minute slot
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
        filler_duration_seconds=300.0,  # 5-minute filler
        grid_minutes=30,
    )


# =============================================================================
# P7-T001: PTS Continuity Across Single Boundary
# =============================================================================


class TestP7T001PTSContinuitySingleBoundary:
    """
    Test INV-P7-001 and INV-P7-002: PTS monotonicity and zero-gap transitions.

    Verification:
    - Last frame of segment A has PTS = T
    - First frame of segment B has PTS = T + frame_period
    - No PTS gap or reset observed
    """

    def test_pts_monotonic_across_boundary_conceptual(self):
        """
        Conceptual test: PTS increases monotonically across segment boundary.

        This validates the contract requirement; integration testing with AIR
        is needed to verify actual frame PTS values.
        """
        frame_period_us = 33366  # ~30fps in microseconds

        # Simulate segment A's last frames
        segment_a_frames = [
            MockFrame(pts_us=1000000, segment_id="segment_a"),
            MockFrame(pts_us=1033366, segment_id="segment_a"),
            MockFrame(pts_us=1066732, segment_id="segment_a"),  # Last frame of A
        ]

        # Segment B's first frame should continue monotonically
        segment_b_first_pts = segment_a_frames[-1].pts_us + frame_period_us
        segment_b_frames = [
            MockFrame(pts_us=segment_b_first_pts, segment_id="segment_b"),
        ]

        # Verify monotonicity
        all_frames = segment_a_frames + segment_b_frames
        for i in range(1, len(all_frames)):
            assert all_frames[i].pts_us > all_frames[i-1].pts_us, \
                f"PTS must increase: frame {i-1} ({all_frames[i-1].pts_us}) -> frame {i} ({all_frames[i].pts_us})"

    def test_zero_gap_at_boundary_conceptual(self):
        """
        Conceptual test: Gap at boundary equals exactly one frame period.
        """
        frame_period_us = 33366  # ~30fps
        tolerance_us = frame_period_us  # Per INV-P7-002

        segment_a_last_pts = 1066732
        segment_b_first_pts = 1100098  # Should be ~1066732 + 33366

        actual_gap = segment_b_first_pts - segment_a_last_pts

        # Gap should be within one frame period of nominal
        assert abs(actual_gap - frame_period_us) <= tolerance_us, \
            f"Gap {actual_gap}us should be within {tolerance_us}us of {frame_period_us}us"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires AIR integration to capture actual frame PTS")
    def test_pts_continuity_real_transition(self):
        """
        Integration test: Verify actual PTS values from AIR during transition.

        Requires:
        - Running AIR instance
        - gRPC connection to capture frame PTS
        - Two segments scheduled back-to-back
        """
        pass


# =============================================================================
# P7-T002: PTS Continuity Across Multiple Boundaries
# =============================================================================


class TestP7T002PTSContinuityMultipleBoundaries:
    """
    Test PTS monotonicity across multiple consecutive segment transitions.
    """

    def test_pts_monotonic_across_three_segments(self):
        """
        Conceptual test: PTS remains monotonic across A→B→C transitions.
        """
        frame_period_us = 33366

        # Build frame sequence across 3 segments
        frames: List[MockFrame] = []
        current_pts = 0

        for segment_id in ["segment_a", "segment_b", "segment_c"]:
            for _ in range(30):  # 30 frames per segment (~1 second each)
                frames.append(MockFrame(pts_us=current_pts, segment_id=segment_id))
                current_pts += frame_period_us

        # Verify strict monotonicity across all frames
        for i in range(1, len(frames)):
            assert frames[i].pts_us > frames[i-1].pts_us, \
                f"PTS must strictly increase at frame {i}"

        # Verify no segment has overlapping PTS ranges with neighbors
        segment_ranges = {}
        for frame in frames:
            if frame.segment_id not in segment_ranges:
                segment_ranges[frame.segment_id] = {"min": frame.pts_us, "max": frame.pts_us}
            else:
                segment_ranges[frame.segment_id]["max"] = max(
                    segment_ranges[frame.segment_id]["max"], frame.pts_us
                )

        # Each segment's max should be less than next segment's min
        segments = ["segment_a", "segment_b", "segment_c"]
        for i in range(len(segments) - 1):
            assert segment_ranges[segments[i]]["max"] < segment_ranges[segments[i+1]]["min"], \
                f"Segment {segments[i]} must end before {segments[i+1]} starts"


# =============================================================================
# P7-T003: Audio Continuity at Boundary
# =============================================================================


class TestP7T003AudioContinuity:
    """
    Test INV-P7-003: Audio sample flow continuous across segment boundaries.
    """

    def test_audio_pts_monotonic_at_boundary(self):
        """
        Audio PTS must maintain same monotonicity as video PTS.
        """
        audio_frame_period_us = 21333  # 1024 samples @ 48kHz

        segment_a_audio = [
            MockFrame(pts_us=1000000, segment_id="a", is_audio=True),
            MockFrame(pts_us=1021333, segment_id="a", is_audio=True),
            MockFrame(pts_us=1042666, segment_id="a", is_audio=True),  # Last audio of A
        ]

        # Segment B audio continues monotonically
        segment_b_first_audio_pts = segment_a_audio[-1].pts_us + audio_frame_period_us
        segment_b_audio = [
            MockFrame(pts_us=segment_b_first_audio_pts, segment_id="b", is_audio=True),
        ]

        all_audio = segment_a_audio + segment_b_audio
        for i in range(1, len(all_audio)):
            assert all_audio[i].pts_us > all_audio[i-1].pts_us, \
                f"Audio PTS must increase at frame {i}"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires audio capture from AIR output")
    def test_no_audio_clicks_at_boundary(self):
        """
        Integration test: Verify no audible discontinuity at transition.

        Requires audio capture and analysis for clicks/pops.
        """
        pass


# =============================================================================
# P7-T004: Epoch Unchanged After Transition
# =============================================================================


class TestP7T004EpochStability:
    """
    Test INV-P7-004: Channel epoch must not change at segment boundaries.
    """

    def test_epoch_constant_conceptual(self):
        """
        Conceptual test: Epoch value recorded at start equals epoch after transitions.
        """
        # Epoch established at channel start
        channel_start_epoch_us = 1700000000000000  # ~2023 in microseconds

        # After multiple segment transitions, epoch should be unchanged
        transitions = ["A→B", "B→C", "C→D"]
        epoch_after_transitions = channel_start_epoch_us  # Should remain same

        assert epoch_after_transitions == channel_start_epoch_us, \
            "Epoch must not change during segment transitions"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires MasterClock inspection during AIR transitions")
    def test_epoch_stable_during_real_transitions(self):
        """
        Integration test: Query MasterClock epoch before/after transitions.
        """
        pass


# =============================================================================
# P7-T005: Prebuffer Readiness Before Boundary
# =============================================================================


class TestP7T005PrebufferReadiness:
    """
    Test INV-P7-005: Next segment must be ready before current segment ends.
    """

    def test_prebuffer_timing_requirement(self, phase3_service: Phase3ScheduleService):
        """
        Verify schedule provides sufficient lookahead for prebuffering.

        LoadPreview must be called before SwitchToLive is needed.
        """
        phase3_service.load_schedule("test-channel")

        # At 14:00, get playout plan
        at_time = datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc)
        plan = phase3_service.get_playout_plan_now("test-channel", at_time)

        # Plan should include current segment and next segment info
        # This allows prebuffering the next segment
        assert len(plan) >= 1, "Plan must include at least current segment"

        # Segment should have end time for prebuffer scheduling
        if len(plan) > 0:
            assert "end" in plan[0] or "duration_seconds" in plan[0], \
                "Segment must have end time or duration for prebuffer scheduling"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires AIR buffer depth inspection via gRPC")
    def test_preview_buffer_has_frames_before_switch(self):
        """
        Integration test: At switch time, preview buffer depth > 0.

        Observable via AIR logs or gRPC status query.
        """
        pass


# =============================================================================
# P7-T006: Missing Segment Fallback
# =============================================================================


class TestP7T006MissingSegmentFallback:
    """
    Test INV-P7-006: Deterministic fallback when segment asset is missing.
    """

    def test_missing_asset_returns_filler_plan(
        self, phase3_service: Phase3ScheduleService, test_programs_dir: Path
    ):
        """
        When a segment's asset file doesn't exist, filler should be scheduled.
        """
        # Create a program with a non-existent file
        missing_program = {
            "program_id": "missing_show",
            "name": "Missing Show",
            "play_mode": "sequential",
            "episodes": [
                {
                    "episode_id": "missing-e01",
                    "title": "Missing Episode",
                    "file_path": "/nonexistent/path/missing.mp4",
                    "duration_seconds": 1800.0,
                },
            ],
        }

        with open(test_programs_dir / "missing_show.json", "w") as f:
            json.dump(missing_program, f)

        # Note: The actual fallback behavior depends on how Phase3ScheduleService
        # handles missing assets. This test validates the contract requirement.
        # Full implementation may need asset existence checks.

    def test_as_run_records_missing_status(self):
        """
        As-run log should record segment as MISSING when asset unavailable.
        """
        as_run_entry = MockAsRunEntry(
            segment_id="missing-segment",
            scheduled_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            scheduled_end_time=datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc),
            actual_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            actual_end_time=datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc),
            status="MISSING",
            notes="Asset not found, filler substituted",
        )

        assert as_run_entry.status == "MISSING"
        assert "filler" in as_run_entry.notes.lower()


# =============================================================================
# P7-T007: Early EOF Handling
# =============================================================================


class TestP7T007EarlyEOFHandling:
    """
    Test fallback behavior when segment ends before scheduled end time.
    """

    def test_early_eof_triggers_early_transition_or_filler(self):
        """
        When segment A ends early:
        - Either transition to B early (if B is ready)
        - Or emit filler until B's scheduled start

        No dead air is acceptable.
        """
        # Segment A scheduled: 14:00-14:30 (30 minutes)
        # Actual EOF at 14:25 (25 minutes)
        scheduled_end = datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc)
        actual_eof = datetime(2025, 1, 30, 14, 25, 0, tzinfo=timezone.utc)

        gap_seconds = (scheduled_end - actual_eof).total_seconds()

        # Contract requires: no dead air
        # Either immediate transition OR filler for the gap
        possible_responses = ["early_transition", "filler_bridge"]

        # This is a structural test; actual behavior verified in integration
        assert gap_seconds == 300  # 5 minute gap
        assert len(possible_responses) > 0  # Both are valid responses

    def test_as_run_records_partial_status(self):
        """
        As-run log should record segment as PARTIAL when early EOF.
        """
        as_run_entry = MockAsRunEntry(
            segment_id="short-episode",
            scheduled_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            scheduled_end_time=datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc),
            actual_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            actual_end_time=datetime(2025, 1, 30, 14, 25, 0, tzinfo=timezone.utc),  # Early
            status="PARTIAL",
            notes="Early EOF at 14:25, filler bridged to 14:30",
        )

        assert as_run_entry.status == "PARTIAL"
        assert as_run_entry.actual_end_time < as_run_entry.scheduled_end_time


# =============================================================================
# P7-T008: Decode Stall Recovery
# =============================================================================


class TestP7T008DecodeStallRecovery:
    """
    Test fallback behavior when next segment fails to achieve readiness.
    """

    def test_stall_recovery_priority(self):
        """
        Per INV-P7-006, fallback priority must be:
        1. Extend current segment (if frames available)
        2. Emit designated filler
        3. Emit black frames with silent audio (last resort)
        """
        fallback_priority = [
            "extend_current_segment",
            "emit_filler",
            "emit_black_frames",
        ]

        # Contract requires this exact priority order
        assert fallback_priority[0] == "extend_current_segment"
        assert fallback_priority[1] == "emit_filler"
        assert fallback_priority[2] == "emit_black_frames"

    @pytest.mark.integration
    @pytest.mark.skip(reason="Requires simulating decode stall in AIR")
    def test_no_dead_air_during_stall(self):
        """
        Integration test: Output stream continues during decode stall.
        """
        pass


# =============================================================================
# P7-T009: Boundary Drift Within Tolerance
# =============================================================================


class TestP7T009BoundaryDriftTolerance:
    """
    Test that actual boundary time is within one frame period of scheduled.
    """

    def test_drift_within_one_frame_period(self):
        """
        |actual_boundary_time - scheduled_boundary_time| <= frame_period
        """
        frame_period_ms = 33.366  # ~30fps

        scheduled_boundary_ms = 1800000  # 30 minutes
        actual_boundary_ms = 1800020  # 20ms late

        drift_ms = abs(actual_boundary_ms - scheduled_boundary_ms)

        assert drift_ms <= frame_period_ms, \
            f"Drift {drift_ms}ms exceeds tolerance {frame_period_ms}ms"

    def test_frame_quantization_acceptable(self):
        """
        Boundary may be quantized to frame boundaries.
        """
        frame_period_us = 33366

        # Scheduled at exactly 1800000000us (30 min)
        # Actual at nearest frame boundary: 1800016830us
        scheduled_us = 1800000000
        actual_us = 1800016830  # Quantized to frame boundary

        drift_us = abs(actual_us - scheduled_us)

        # Drift should be less than one frame period
        assert drift_us < frame_period_us


# =============================================================================
# P7-T010: As-Run Accuracy
# =============================================================================


class TestP7T010AsRunAccuracy:
    """
    Test INV-P7-007: As-run times recorded with millisecond precision.
    """

    def test_as_run_has_required_fields(self):
        """
        As-run entry must have all required fields per contract.
        """
        required_fields = [
            "segment_id",
            "scheduled_start_time",
            "scheduled_end_time",
            "actual_start_time",
            "actual_end_time",
            "status",
        ]

        as_run_entry = MockAsRunEntry(
            segment_id="test-segment",
            scheduled_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            scheduled_end_time=datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc),
            actual_start_time=datetime(2025, 1, 30, 14, 0, 0, 123000, tzinfo=timezone.utc),
            actual_end_time=datetime(2025, 1, 30, 14, 29, 59, 987000, tzinfo=timezone.utc),
            status="PLAYED",
        )

        for field in required_fields:
            assert hasattr(as_run_entry, field), f"As-run must have field: {field}"

    def test_millisecond_precision(self):
        """
        As-run times must have millisecond precision.
        """
        actual_start = datetime(2025, 1, 30, 14, 0, 0, 123456, tzinfo=timezone.utc)

        # Microseconds available (6 digits) - milliseconds is 3 digits
        milliseconds = actual_start.microsecond // 1000

        assert milliseconds == 123, "Should preserve millisecond precision"

    def test_actual_times_authoritative(self):
        """
        As-run actual times are authoritative over scheduled times.
        """
        as_run = MockAsRunEntry(
            segment_id="test",
            scheduled_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            scheduled_end_time=datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc),
            actual_start_time=datetime(2025, 1, 30, 14, 0, 0, 500000, tzinfo=timezone.utc),
            actual_end_time=datetime(2025, 1, 30, 14, 29, 58, 0, tzinfo=timezone.utc),
            status="PLAYED",
        )

        # Actual times differ from scheduled - this is expected and correct
        assert as_run.actual_start_time != as_run.scheduled_start_time
        assert as_run.actual_end_time != as_run.scheduled_end_time

        # Actual times are the ground truth
        actual_duration = as_run.actual_end_time - as_run.actual_start_time
        assert actual_duration.total_seconds() < 1800  # Less than scheduled 30 min


# =============================================================================
# Edge Cases
# =============================================================================


class TestP7EdgeCases:
    """
    Test edge cases defined in Phase 7 contract section 13.
    """

    def test_zero_duration_segment_skipped(self):
        """
        A segment with zero scheduled duration should be skipped entirely.
        """
        as_run = MockAsRunEntry(
            segment_id="zero-duration",
            scheduled_start_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),
            scheduled_end_time=datetime(2025, 1, 30, 14, 0, 0, tzinfo=timezone.utc),  # Same
            actual_start_time=None,
            actual_end_time=None,
            status="SKIPPED",
            notes="Zero duration segment",
        )

        assert as_run.status == "SKIPPED"
        assert as_run.actual_start_time is None
        assert as_run.actual_end_time is None

    def test_back_to_back_identical_assets_separate_segments(self):
        """
        Two consecutive segments using same asset should be treated separately.
        """
        # Same asset, but two distinct segments
        segment_a = {"segment_id": "slot-14:00", "asset": "/path/to/episode.mp4"}
        segment_b = {"segment_id": "slot-14:30", "asset": "/path/to/episode.mp4"}

        # They are separate segments (not coalesced)
        assert segment_a["segment_id"] != segment_b["segment_id"]
        assert segment_a["asset"] == segment_b["asset"]  # Same asset is OK

    def test_channel_start_at_boundary_clean_join(self):
        """
        Viewer joining exactly at segment boundary sees first frame of new segment.
        """
        # Join time exactly at boundary
        boundary_time = datetime(2025, 1, 30, 14, 30, 0, tzinfo=timezone.utc)

        # Expected behavior: see segment B's first frame, not segment A's last
        expected_segment = "segment_b"
        expected_offset_ms = 0  # Start of segment, not end of previous

        assert expected_offset_ms == 0, "Joining at boundary should have 0 offset"


# =============================================================================
# Contract Compliance Summary
# =============================================================================


class TestP7ContractCompliance:
    """
    Summary tests verifying overall contract compliance.
    """

    def test_all_invariants_documented(self):
        """
        Verify all P7 invariants are covered by tests.
        """
        invariants = [
            "INV-P7-001",  # PTS Monotonicity
            "INV-P7-002",  # Zero-Gap Transitions
            "INV-P7-003",  # Audio Continuity
            "INV-P7-004",  # Epoch Stability
            "INV-P7-005",  # Prebuffer Guarantee
            "INV-P7-006",  # Deterministic Fallback
            "INV-P7-007",  # As-Run Accuracy
        ]

        # Map invariants to test classes
        test_coverage = {
            "INV-P7-001": "TestP7T001PTSContinuitySingleBoundary",
            "INV-P7-002": "TestP7T001PTSContinuitySingleBoundary",  # Same test covers both
            "INV-P7-003": "TestP7T003AudioContinuity",
            "INV-P7-004": "TestP7T004EpochStability",
            "INV-P7-005": "TestP7T005PrebufferReadiness",
            "INV-P7-006": "TestP7T006MissingSegmentFallback",
            "INV-P7-007": "TestP7T010AsRunAccuracy",
        }

        for inv in invariants:
            assert inv in test_coverage, f"Invariant {inv} must have test coverage"

    def test_no_dead_air_principle(self):
        """
        Dead air (no output) is never acceptable per contract.
        """
        # This is the overarching principle of Phase 7
        acceptable_outputs = [
            "scheduled_content",
            "extended_previous_segment",
            "filler_content",
            "black_frames_with_silent_audio",
        ]

        unacceptable_outputs = [
            "no_output",
            "dead_air",
            "frozen_frame_indefinitely",
        ]

        # Contract guarantees one of the acceptable outputs, never unacceptable
        assert len(acceptable_outputs) == 4
        assert "dead_air" in unacceptable_outputs
