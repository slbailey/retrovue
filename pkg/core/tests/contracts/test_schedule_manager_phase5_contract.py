"""
Schedule Manager Phase 5 Contract Tests

Tests the runtime integration defined in:
    docs/contracts/runtime/ScheduleManagerContract.md

Phase 5 wires Phase 3 ScheduleManager into the production runtime via:
- ScheduleManagerBackedScheduleService adapter
- Config-driven activation (schedule_source: "phase3")
- EPG HTTP endpoint

Status: Implemented
"""

import json
import pytest
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

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
from retrovue.runtime.schedule_manager_service import (
    ScheduleManagerBackedScheduleService,
    InMemorySequenceStore,
    InMemoryResolvedStore,
    JsonFileProgramCatalog,
)
from retrovue.runtime.clock import MasterClock
from retrovue.runtime.config import ChannelConfig, ProgramFormat
from retrovue.runtime.horizon_config import HorizonNoScheduleDataError


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def test_programs_dir(tmp_path: Path) -> Path:
    """Create temporary programs directory with Cheers program."""
    programs_dir = tmp_path / "programs"
    programs_dir.mkdir()

    # Create cheers.json
    cheers_program = {
        "program_id": "cheers",
        "name": "Cheers",
        "play_mode": "sequential",
        "episodes": [
            {
                "episode_id": "cheers-s01e01",
                "title": "Give Me a Ring Sometime",
                "file_path": "/opt/retrovue/assets/cheers_s01e01.mp4",
                "duration_seconds": 1501.653,
            },
            {
                "episode_id": "cheers-s01e02",
                "title": "Sam's Women",
                "file_path": "/opt/retrovue/assets/cheers_s01e02.mp4",
                "duration_seconds": 1333.457,
            },
            {
                "episode_id": "cheers-s01e03",
                "title": "The Tortelli Tort",
                "file_path": "/opt/retrovue/assets/cheers_s01e03.mp4",
                "duration_seconds": 1499.904,
            },
        ],
    }

    with open(programs_dir / "cheers.json", "w") as f:
        json.dump(cheers_program, f)

    return programs_dir


@pytest.fixture
def test_schedules_dir(tmp_path: Path) -> Path:
    """Create temporary schedules directory with cheers-24-7 schedule."""
    schedules_dir = tmp_path / "schedules"
    schedules_dir.mkdir()

    # Create cheers-24-7.json with a few slots
    schedule = {
        "channel_id": "cheers-24-7",
        "slots": [
            {"slot_time": "06:00", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "06:30", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "07:00", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "07:30", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "08:00", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "08:30", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "09:00", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
            {"slot_time": "09:30", "program_ref": {"type": "program", "id": "cheers"}, "duration_seconds": 1800},
        ],
    }

    with open(schedules_dir / "cheers-24-7.json", "w") as f:
        json.dump(schedule, f)

    return schedules_dir


@pytest.fixture
def mock_clock() -> MasterClock:
    """Create a mock MasterClock."""
    clock = MasterClock()
    return clock


@pytest.fixture
def schedule_service(
    mock_clock: MasterClock,
    test_programs_dir: Path,
    test_schedules_dir: Path,
) -> ScheduleManagerBackedScheduleService:
    """Create ScheduleManagerBackedScheduleService with test fixtures."""
    return ScheduleManagerBackedScheduleService(
        clock=mock_clock,
        programs_dir=test_programs_dir,
        schedules_dir=test_schedules_dir,
        filler_path="/opt/retrovue/assets/filler.mp4",
        filler_duration_seconds=3650.0,
        grid_minutes=30,
    )


# =============================================================================
# P5-T001: Load Phase 3 Schedule Successfully
# =============================================================================


class TestP5T001LoadSchedule:
    """Test that Phase 3 schedule loads successfully from JSON."""

    def test_load_schedule_success(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Schedule loads without error."""
        success, error = schedule_service.load_schedule("cheers-24-7")
        assert success is True
        assert error is None

    def test_load_schedule_not_found(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Non-existent schedule returns error."""
        success, error = schedule_service.load_schedule("nonexistent")
        assert success is False
        assert error is not None
        assert "not found" in error.lower()


# =============================================================================
# P5-T002: Playout Plan Format Matches ChannelManager Expectations
# =============================================================================


class TestP5T002PlayoutPlanFormat:
    """Test that playout plan format matches ChannelManager expectations."""

    def test_playout_plan_has_required_keys(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Playout plan segments have required keys."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        # Query at 06:15 (mid-slot)
        at_time = datetime(2025, 1, 30, 6, 15, 0, tzinfo=timezone.utc)
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        assert len(plan) >= 1
        segment = plan[0]

        # Required keys per INV-P5-003
        assert "asset_path" in segment
        assert "start_pts" in segment
        assert "duration_seconds" in segment

    def test_start_pts_is_milliseconds(self, schedule_service: ScheduleManagerBackedScheduleService):
        """start_pts is in milliseconds."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        # Query at 06:15 (15 minutes = 900 seconds into slot)
        at_time = datetime(2025, 1, 30, 6, 15, 0, tzinfo=timezone.utc)
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        segment = plan[0]
        start_pts = segment["start_pts"]

        # 15 minutes = 900 seconds = 900000 milliseconds
        assert start_pts == 900 * 1000

    def test_asset_path_is_string(self, schedule_service: ScheduleManagerBackedScheduleService):
        """asset_path is a valid string path."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        at_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        segment = plan[0]
        assert isinstance(segment["asset_path"], str)
        assert len(segment["asset_path"]) > 0


# =============================================================================
# P5-T003: EPG Endpoint Returns Correct JSON Format
# =============================================================================


class TestP5T003EPGFormat:
    """Test EPG endpoint returns correct JSON format."""

    def test_epg_events_structure(self, schedule_service: ScheduleManagerBackedScheduleService):
        """EPG events have correct structure."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        start_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2025, 1, 30, 10, 0, 0, tzinfo=timezone.utc)

        events = schedule_service.get_epg_events("cheers-24-7", start_time, end_time)

        assert len(events) >= 1
        event = events[0]

        # Required fields per contract
        assert "channel_id" in event
        assert "start_time" in event
        assert "end_time" in event
        assert "title" in event
        assert "episode_title" in event
        assert "episode_id" in event
        assert "asset" in event

    def test_epg_events_title_is_program_name(self, schedule_service: ScheduleManagerBackedScheduleService):
        """EPG title is program name (e.g., 'Cheers')."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        start_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2025, 1, 30, 7, 0, 0, tzinfo=timezone.utc)

        events = schedule_service.get_epg_events("cheers-24-7", start_time, end_time)

        assert events[0]["title"] == "Cheers"

    def test_epg_events_has_episode_title(self, schedule_service: ScheduleManagerBackedScheduleService):
        """EPG events include episode title."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        start_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2025, 1, 30, 7, 0, 0, tzinfo=timezone.utc)

        events = schedule_service.get_epg_events("cheers-24-7", start_time, end_time)

        # First slot should be first episode
        assert events[0]["episode_title"] == "Give Me a Ring Sometime"


# =============================================================================
# P5-T004: No consumer-triggered resolution — raises on unresolved
# =============================================================================


class TestP5T004NoConsumerResolution:
    """Test that unresolved access raises HorizonNoScheduleDataError."""

    def test_playout_access_raises_when_unresolved(
        self,
        mock_clock: MasterClock,
        test_programs_dir: Path,
        test_schedules_dir: Path,
    ):
        """Playout access raises when day not resolved."""
        service = ScheduleManagerBackedScheduleService(
            clock=mock_clock,
            programs_dir=test_programs_dir,
            schedules_dir=test_schedules_dir,
            filler_path="/opt/retrovue/assets/filler.mp4",
            filler_duration_seconds=3650.0,
            grid_minutes=30,
        )
        service.load_schedule("cheers-24-7")

        assert not service._resolved_store.exists("cheers-24-7", date(2025, 1, 30))

        at_time = datetime(2025, 1, 30, 6, 15, 0, tzinfo=timezone.utc)
        with pytest.raises(HorizonNoScheduleDataError):
            service.get_playout_plan_now("cheers-24-7", at_time)

    def test_epg_access_raises_when_unresolved(
        self,
        mock_clock: MasterClock,
        test_programs_dir: Path,
        test_schedules_dir: Path,
    ):
        """EPG access raises when day not resolved."""
        service = ScheduleManagerBackedScheduleService(
            clock=mock_clock,
            programs_dir=test_programs_dir,
            schedules_dir=test_schedules_dir,
            filler_path="/opt/retrovue/assets/filler.mp4",
            filler_duration_seconds=3650.0,
            grid_minutes=30,
        )
        service.load_schedule("cheers-24-7")

        assert not service._resolved_store.exists("cheers-24-7", date(2025, 1, 30))

        start_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2025, 1, 30, 10, 0, 0, tzinfo=timezone.utc)
        with pytest.raises(HorizonNoScheduleDataError):
            service.get_epg_events("cheers-24-7", start_time, end_time)


# =============================================================================
# P5-T005: schedule_source: "phase3" Activates ScheduleManagerBackedScheduleService
# =============================================================================


class TestP5T005ConfigActivation:
    """Test that schedule_source: 'phase3' activates ScheduleManagerBackedScheduleService."""

    def test_phase3_channel_config(self):
        """Channel config with schedule_source='phase3' is valid."""
        config = ChannelConfig(
            channel_id="cheers-24-7",
            channel_id_int=2,
            name="Cheers 24/7",
            program_format=ProgramFormat(
                video_width=1920,
                video_height=1080,
                frame_rate="30/1",
                audio_sample_rate=48000,
                audio_channels=2,
            ),
            schedule_source="phase3",
            schedule_config={
                "grid_minutes": 30,
                "filler_path": "/opt/retrovue/assets/filler.mp4",
            },
        )

        assert config.schedule_source == "phase3"
        assert config.schedule_config["grid_minutes"] == 30


# =============================================================================
# P5-T006: Episode Identity in Playout Matches EPG
# =============================================================================


class TestP5T006EpisodeIdentity:
    """Test that playout episode matches EPG episode."""

    def test_episode_identity_consistency(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Same episode plays as what EPG shows."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        # Query at 06:00 exactly
        at_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)

        # Get playout plan
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        # Get EPG for same time
        events = schedule_service.get_epg_events(
            "cheers-24-7",
            at_time,
            at_time + timedelta(hours=1),
        )

        # First event's asset should match playout asset
        assert events[0]["asset"]["file_path"] == plan[0]["asset_path"]


# =============================================================================
# P5-T007: Seek Offset Correct for Mid-Episode Join
# =============================================================================


class TestP5T007SeekOffset:
    """Test that seek offset is correct for mid-episode join."""

    def test_mid_episode_seek_offset(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Joining mid-episode has correct seek offset."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        # Episode starts at 06:00, join at 06:12 (12 minutes in)
        at_time = datetime(2025, 1, 30, 6, 12, 0, tzinfo=timezone.utc)
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        # start_pts should be 12 minutes = 720 seconds = 720000 ms
        assert plan[0]["start_pts"] == 720 * 1000

    def test_slot_boundary_no_offset(self, schedule_service: ScheduleManagerBackedScheduleService):
        """Joining at slot start has zero offset."""
        schedule_service.load_schedule("cheers-24-7")
        schedule_service.prime_schedule_day("cheers-24-7", date(2025, 1, 30))

        # Join exactly at 06:00
        at_time = datetime(2025, 1, 30, 6, 0, 0, tzinfo=timezone.utc)
        plan = schedule_service.get_playout_plan_now("cheers-24-7", at_time)

        assert plan[0]["start_pts"] == 0


# =============================================================================
# In-Memory Store Tests
# =============================================================================


class TestInMemorySequenceStore:
    """Test InMemorySequenceStore functionality."""

    def test_initial_position_is_zero(self):
        """Initial position for any program is 0."""
        store = InMemorySequenceStore()
        assert store.get_position("channel1", "program1") == 0

    def test_set_and_get_position(self):
        """Can set and get position."""
        store = InMemorySequenceStore()
        store.set_position("channel1", "program1", 5)
        assert store.get_position("channel1", "program1") == 5

    def test_positions_are_isolated_per_channel(self):
        """Positions are isolated per channel."""
        store = InMemorySequenceStore()
        store.set_position("channel1", "program1", 3)
        store.set_position("channel2", "program1", 7)

        assert store.get_position("channel1", "program1") == 3
        assert store.get_position("channel2", "program1") == 7


class TestInMemoryResolvedStore:
    """Test InMemoryResolvedStore functionality."""

    def test_initial_store_is_empty(self):
        """Initial store has no resolved days."""
        store = InMemoryResolvedStore()
        assert store.get("channel1", date(2025, 1, 30)) is None
        assert not store.exists("channel1", date(2025, 1, 30))

    def test_store_and_retrieve(self):
        """Can store and retrieve resolved day."""
        store = InMemoryResolvedStore()

        resolved = ResolvedScheduleDay(
            programming_day_date=date(2025, 1, 30),
            resolved_slots=[],
            resolution_timestamp=datetime(2025, 1, 30, 5, 0, 0),
            sequence_state=SequenceState(),
        )

        store.store("channel1", resolved)

        assert store.exists("channel1", date(2025, 1, 30))
        retrieved = store.get("channel1", date(2025, 1, 30))
        assert retrieved is not None
        assert retrieved.programming_day_date == date(2025, 1, 30)


# =============================================================================
# JsonFileProgramCatalog Tests
# =============================================================================


class TestJsonFileProgramCatalog:
    """Test JsonFileProgramCatalog functionality."""

    def test_load_program_success(self, test_programs_dir: Path):
        """Can load program from JSON file."""
        catalog = JsonFileProgramCatalog(test_programs_dir)
        program = catalog.get_program("cheers")

        assert program is not None
        assert program.program_id == "cheers"
        assert program.name == "Cheers"
        assert program.play_mode == "sequential"
        assert len(program.episodes) == 3

    def test_program_not_found(self, test_programs_dir: Path):
        """Non-existent program returns None."""
        catalog = JsonFileProgramCatalog(test_programs_dir)
        program = catalog.get_program("nonexistent")

        assert program is None

    def test_episode_durations_loaded(self, test_programs_dir: Path):
        """Episode durations are loaded correctly."""
        catalog = JsonFileProgramCatalog(test_programs_dir)
        program = catalog.get_program("cheers")

        assert program.episodes[0].duration_seconds == 1501.653
        assert program.episodes[1].duration_seconds == 1333.457
        assert program.episodes[2].duration_seconds == 1499.904
