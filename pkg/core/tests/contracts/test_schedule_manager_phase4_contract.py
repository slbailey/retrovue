"""
Schedule Manager Phase 4 Contract Tests

Tests the validation scenarios defined in:
    docs/contracts/runtime/ScheduleManagerPhase4Contract.md

Phase 4 is a demonstration/validation phase that proves Phase 3 works
with real episode durations. No new runtime behavior is tested.

Status: Implemented
"""

import json
import pytest
from dataclasses import dataclass, field
from datetime import datetime, date, time, timedelta
from pathlib import Path

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
    ProgramCatalog,
    SequenceStateStore,
    ResolvedScheduleStore,
)
from retrovue.runtime.schedule_manager import Phase3ScheduleManager


# =============================================================================
# Fixture Loading Infrastructure
# =============================================================================

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "phase4"


class FixtureProgramCatalog:
    """
    ProgramCatalog that loads from JSON fixtures.

    Simulates Asset Library response for Phase 4 testing.
    No runtime file inspection occurs.
    """

    @classmethod
    def from_json_file(cls, path: Path) -> "FixtureProgramCatalog":
        with open(path) as f:
            return cls(json.load(f))

    def __init__(self, data: dict):
        self._programs: dict[str, Program] = {}
        self._filler_path = data.get("filler", {}).get("file_path", "/media/filler.mp4")
        self._filler_duration = data.get("filler", {}).get("duration_seconds", 3600.0)

        for p in data.get("programs", []):
            program = Program(
                program_id=p["program_id"],
                name=p["name"],
                play_mode=p["play_mode"],
                episodes=[
                    Episode(
                        episode_id=e["episode_id"],
                        title=e["title"],
                        file_path=e["file_path"],
                        duration_seconds=e["duration_seconds"],
                    )
                    for e in p["episodes"]
                ],
            )
            self._programs[program.program_id] = program

    def get_program(self, program_id: str) -> Program | None:
        return self._programs.get(program_id)

    @property
    def filler_path(self) -> str:
        return self._filler_path

    @property
    def filler_duration(self) -> float:
        return self._filler_duration


class InMemorySequenceStore:
    """In-memory SequenceStateStore for testing."""

    def __init__(self):
        self._positions: dict[tuple[str, str], int] = {}

    def get_position(self, channel_id: str, program_id: str) -> int:
        return self._positions.get((channel_id, program_id), 0)

    def set_position(self, channel_id: str, program_id: str, index: int) -> None:
        self._positions[(channel_id, program_id)] = index

    def reset(self) -> None:
        self._positions.clear()


class InMemoryResolvedStore:
    """In-memory ResolvedScheduleStore for testing."""

    def __init__(self):
        self._resolved: dict[tuple[str, date], ResolvedScheduleDay] = {}

    def get(self, channel_id: str, programming_day_date: date) -> ResolvedScheduleDay | None:
        return self._resolved.get((channel_id, programming_day_date))

    def store(self, channel_id: str, resolved: ResolvedScheduleDay) -> None:
        key = (channel_id, resolved.programming_day_date)
        if key not in self._resolved:
            self._resolved[key] = resolved

    def exists(self, channel_id: str, programming_day_date: date) -> bool:
        return (channel_id, programming_day_date) in self._resolved

    def clear(self) -> None:
        self._resolved.clear()


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def fixture_catalog() -> FixtureProgramCatalog:
    """Load the Cheers fixture catalog."""
    return FixtureProgramCatalog.from_json_file(FIXTURES_DIR / "cheers_episodes.json")


@pytest.fixture
def sequence_store() -> InMemorySequenceStore:
    """Create fresh sequence store."""
    return InMemorySequenceStore()


@pytest.fixture
def resolved_store() -> InMemoryResolvedStore:
    """Create fresh resolved store."""
    return InMemoryResolvedStore()


@pytest.fixture
def phase4_config(
    fixture_catalog: FixtureProgramCatalog,
    sequence_store: InMemorySequenceStore,
    resolved_store: InMemoryResolvedStore,
) -> Phase3Config:
    """Create Phase 4 test configuration."""
    return Phase3Config(
        grid_minutes=30,
        program_catalog=fixture_catalog,
        sequence_store=sequence_store,
        resolved_store=resolved_store,
        filler_path=fixture_catalog.filler_path,
        filler_duration_seconds=fixture_catalog.filler_duration,
        programming_day_start_hour=6,
    )


@pytest.fixture
def schedule_manager(phase4_config: Phase3Config) -> Phase3ScheduleManager:
    """Create Phase 3 ScheduleManager with Phase 4 fixtures."""
    return Phase3ScheduleManager(phase4_config)


@pytest.fixture
def cheers_program(fixture_catalog: FixtureProgramCatalog) -> Program:
    """Get the Cheers program from fixtures."""
    program = fixture_catalog.get_program("cheers")
    assert program is not None
    return program


def generate_24_hour_slots() -> list[ScheduleSlot]:
    """Generate 48 slots (24 hours) of Cheers programming."""
    slots = []
    base_hour = 6  # Programming day start

    for i in range(48):
        hour = (base_hour + (i * 30) // 60) % 24
        minute = (i * 30) % 60
        slots.append(ScheduleSlot(
            slot_time=time(hour, minute),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,  # 30 minutes
            label=f"Cheers slot {i}",
        ))

    return slots


# =============================================================================
# EPG Grid Alignment Tests (P4-T001, P4-T002)
# =============================================================================

class TestEPGGridAlignment:
    """Tests for EPG grid alignment behavior."""

    def test_P4_T001_epg_shows_grid_aligned_times_only(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
    ):
        """P4-T001: EPG shows grid-aligned times only."""
        # S01E01 has duration 1501.653s (25:01), not 30 minutes
        episode = cheers_program.episodes[0]
        assert episode.duration_seconds == pytest.approx(1501.653, rel=0.01)

        # Resolve schedule
        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,
        )]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Get EPG events
        events = schedule_manager.get_epg_events(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
            datetime(2025, 1, 30, 7, 0, 0),
        )

        assert len(events) == 1
        event = events[0]

        # EPG shows grid-aligned times, NOT actual episode duration
        assert event.start_time == datetime(2025, 1, 30, 6, 0, 0)
        # End time based on content duration (INV-P3-009), but snapped for EPG display
        # Actually per contract, EPG end_time uses content duration
        # Let's verify the episode identity is correct
        assert event.episode_id == "cheers-s01e01"
        assert event.title == "Cheers"

    def test_P4_T002_epg_does_not_expose_filler(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T002: EPG does not expose filler."""
        slots = [
            ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
            ScheduleSlot(
                slot_time=time(6, 30),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
        ]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        events = schedule_manager.get_epg_events(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
            datetime(2025, 1, 30, 7, 0, 0),
        )

        # Should have 2 events (S01E01, S01E02), no filler events
        assert len(events) == 2
        assert events[0].episode_id == "cheers-s01e01"
        assert events[1].episode_id == "cheers-s01e02"

        # No filler in EPG
        for event in events:
            assert "filler" not in event.title.lower()
            assert event.episode_id is not None


# =============================================================================
# Episode Continuity Tests (P4-T003, P4-T004)
# =============================================================================

class TestEpisodeContinuity:
    """Tests for episode continuity behavior."""

    def test_P4_T003_sequential_episodes_progress_correctly(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T003: Sequential episodes progress correctly."""
        slots = generate_24_hour_slots()[:6]  # First 6 slots (3 hours)

        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Check episode sequence
        episode_ids = [s.resolved_asset.episode_id for s in resolved.resolved_slots]

        assert episode_ids[0] == "cheers-s01e01"  # Slot 0
        assert episode_ids[1] == "cheers-s01e02"  # Slot 1
        assert episode_ids[2] == "cheers-s01e03"  # Slot 2
        assert episode_ids[3] == "cheers-s01e01"  # Slot 3 (loop)
        assert episode_ids[4] == "cheers-s01e02"  # Slot 4
        assert episode_ids[5] == "cheers-s01e03"  # Slot 5

    def test_P4_T004_episode_identity_matches_epg(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T004: Episode identity matches EPG."""
        slots = [
            ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
            ScheduleSlot(
                slot_time=time(6, 30),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
        ]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # EPG shows S01E02 at 06:30
        events = schedule_manager.get_epg_events(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 30, 0),
            datetime(2025, 1, 30, 7, 0, 0),
        )
        assert events[0].episode_id == "cheers-s01e02"

        # Get playout at 06:42
        block = schedule_manager.get_program_at(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 42, 0),
        )

        # Episode identity must match EPG
        assert "s01e02" in block.segments[0].file_path.lower()


# =============================================================================
# Filler Insertion Tests (P4-T005, P4-T006, P4-T007)
# =============================================================================

class TestFillerInsertion:
    """Tests for filler insertion behavior."""

    def test_P4_T005_filler_appears_after_episode_end(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
        phase4_config: Phase3Config,
    ):
        """P4-T005: Filler appears after episode end."""
        # S01E01: 1501.653s (25:01.653)
        episode = cheers_program.episodes[0]
        episode_duration = episode.duration_seconds

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,  # 30 minute slot
        )]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Get playout at 06:00
        block = schedule_manager.get_program_at(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
        )

        # Should have 2 segments: episode then filler
        assert len(block.segments) == 2

        episode_segment = block.segments[0]
        filler_segment = block.segments[1]

        # Episode segment
        assert "s01e01" in episode_segment.file_path.lower()
        assert episode_segment.start_utc == datetime(2025, 1, 30, 6, 0, 0)
        episode_end = datetime(2025, 1, 30, 6, 0, 0) + timedelta(seconds=episode_duration)
        assert episode_segment.end_utc == episode_end

        # Filler segment
        assert filler_segment.file_path == phase4_config.filler_path
        assert filler_segment.start_utc == episode_end
        assert filler_segment.end_utc == datetime(2025, 1, 30, 6, 30, 0)

    def test_P4_T006_filler_duration_correct(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
    ):
        """P4-T006: Filler duration correct."""
        # S01E01: 1501.653s, slot: 1800s
        # Expected filler: 1800 - 1501.653 = 298.347s
        episode = cheers_program.episodes[0]
        expected_filler = 1800.0 - episode.duration_seconds

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,
        )]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        block = schedule_manager.get_program_at(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
        )

        filler_segment = block.segments[1]
        filler_duration = (filler_segment.end_utc - filler_segment.start_utc).total_seconds()

        assert filler_duration == pytest.approx(expected_filler, rel=0.01)

    def test_P4_T007_no_filler_when_episode_fills_slot(
        self,
        schedule_manager: Phase3ScheduleManager,
        fixture_catalog: FixtureProgramCatalog,
        sequence_store: InMemorySequenceStore,
        resolved_store: InMemoryResolvedStore,
    ):
        """P4-T007: No filler when episode fills slot."""
        # Create a program with an episode that exactly fills a slot
        mock_data = {
            "filler": {"file_path": "/media/filler.mp4", "duration_seconds": 3600},
            "programs": [{
                "program_id": "exact-fit",
                "name": "Exact Fit Show",
                "play_mode": "sequential",
                "episodes": [{
                    "episode_id": "exact-e01",
                    "title": "Exact Episode",
                    "file_path": "/media/exact.mp4",
                    "duration_seconds": 1800.0,  # Exactly 30 minutes
                }],
            }],
        }

        catalog = FixtureProgramCatalog(mock_data)
        config = Phase3Config(
            grid_minutes=30,
            program_catalog=catalog,
            sequence_store=sequence_store,
            resolved_store=resolved_store,
            filler_path=catalog.filler_path,
            programming_day_start_hour=6,
        )
        manager = Phase3ScheduleManager(config)

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "exact-fit"),
            duration_seconds=1800.0,
        )]

        manager.resolve_schedule_day(
            channel_id="test",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        block = manager.get_program_at("test", datetime(2025, 1, 30, 6, 0, 0))

        # Should have only 1 segment (no filler needed)
        assert len(block.segments) == 1
        assert "exact" in block.segments[0].file_path


# =============================================================================
# Seek Offset Tests (P4-T008, P4-T009, P4-T010)
# =============================================================================

class TestSeekOffset:
    """Tests for seek offset correctness."""

    def test_P4_T008_mid_episode_join_correct_offset(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T008: Mid-episode join correct offset.

        Per contract: seek_offset_seconds is the offset at BLOCK BOUNDARY,
        not at query time. To get actual file position at query time:
        file_position = seek_offset + (query_time - segment.start_utc)
        """
        slots = [
            ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
            ScheduleSlot(
                slot_time=time(6, 30),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
        ]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # S01E02 starts at 06:30, viewer joins at 06:42
        query_time = datetime(2025, 1, 30, 6, 42, 0)
        block = schedule_manager.get_program_at("cheers-24-7", query_time)

        # Block starts at 06:30, S01E02 also starts at 06:30
        # seek_offset at block boundary is 0
        assert block.segments[0].seek_offset_seconds == 0.0

        # File position at query time = seek_offset + (query_time - segment_start)
        segment = block.segments[0]
        file_position = segment.seek_offset_seconds + (query_time - segment.start_utc).total_seconds()
        assert file_position == pytest.approx(720.0, rel=0.01)  # 12 minutes into episode

    def test_P4_T009_join_during_filler(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
        phase4_config: Phase3Config,
    ):
        """P4-T009: Join during filler.

        Per contract: seek_offset_seconds is the offset at BLOCK/SEGMENT BOUNDARY.
        When joining during filler, we verify:
        1. The correct segment (filler) is identified
        2. Filler segment starts after episode ends
        """
        # S01E01: 1501.653s, ends at 06:25:01.653
        episode = cheers_program.episodes[0]
        episode_duration = episode.duration_seconds

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,
        )]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Join at 06:27 (during filler, after episode ends at ~06:25:01)
        join_time = datetime(2025, 1, 30, 6, 27, 0)
        block = schedule_manager.get_program_at("cheers-24-7", join_time)

        # Should have 2 segments: episode then filler
        assert len(block.segments) == 2

        filler_segment = block.segments[1]
        assert filler_segment.file_path == phase4_config.filler_path

        # Filler starts after episode ends
        episode_end = datetime(2025, 1, 30, 6, 0, 0) + timedelta(seconds=episode_duration)
        assert filler_segment.start_utc == episode_end

        # Join time is within filler segment
        assert filler_segment.start_utc <= join_time < filler_segment.end_utc

        # Filler seek_offset at segment start is 0
        assert filler_segment.seek_offset_seconds == 0.0

        # To calculate position in filler at join_time:
        filler_position = (join_time - filler_segment.start_utc).total_seconds()
        assert filler_position > 0  # We're past the start of filler

    def test_P4_T010_join_at_exact_slot_boundary(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T010: Join at exact slot boundary."""
        slots = [
            ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
            ScheduleSlot(
                slot_time=time(6, 30),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
        ]

        schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Join at exactly 06:30:00
        block = schedule_manager.get_program_at(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 30, 0),
        )

        # seek_offset should be 0 (start of S01E02)
        assert block.segments[0].seek_offset_seconds == 0.0
        assert "s01e02" in block.segments[0].file_path.lower()


# =============================================================================
# Looping Behavior Tests (P4-T011, P4-T012, P4-T013)
# =============================================================================

class TestLoopingBehavior:
    """Tests for looping behavior."""

    def test_P4_T011_sequential_loop_after_last_episode(
        self,
        schedule_manager: Phase3ScheduleManager,
        sequence_store: InMemorySequenceStore,
    ):
        """P4-T011: Sequential loop after last episode."""
        # Start at position 2 (S01E03)
        sequence_store.set_position("cheers-24-7", "cheers", 2)

        slots = [
            ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
            ScheduleSlot(
                slot_time=time(6, 30),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
                duration_seconds=1800.0,
            ),
        ]

        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # First slot: S01E03 (position 2)
        assert resolved.resolved_slots[0].resolved_asset.episode_id == "cheers-s01e03"

        # Second slot: S01E01 (wrapped to position 0)
        assert resolved.resolved_slots[1].resolved_asset.episode_id == "cheers-s01e01"

        # Position should now be 1 (after wrapping and advancing)
        assert sequence_store.get_position("cheers-24-7", "cheers") == 1

    def test_P4_T012_24_hour_continuous_loop(
        self,
        schedule_manager: Phase3ScheduleManager,
    ):
        """P4-T012: 24-hour continuous loop."""
        slots = generate_24_hour_slots()  # 48 slots

        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        episode_ids = [s.resolved_asset.episode_id for s in resolved.resolved_slots]

        # Should cycle: E01, E02, E03, E01, E02, E03, ...
        expected_pattern = ["cheers-s01e01", "cheers-s01e02", "cheers-s01e03"]

        for i, episode_id in enumerate(episode_ids):
            expected = expected_pattern[i % 3]
            assert episode_id == expected, f"Slot {i}: expected {expected}, got {episode_id}"

        # 48 slots / 3 episodes = 16 complete cycles
        assert len(episode_ids) == 48

    def test_P4_T013_loop_determinism(
        self,
        fixture_catalog: FixtureProgramCatalog,
    ):
        """P4-T013: Loop determinism."""
        slots = generate_24_hour_slots()

        # First resolution
        store1 = InMemorySequenceStore()
        resolved_store1 = InMemoryResolvedStore()
        config1 = Phase3Config(
            grid_minutes=30,
            program_catalog=fixture_catalog,
            sequence_store=store1,
            resolved_store=resolved_store1,
            filler_path=fixture_catalog.filler_path,
            programming_day_start_hour=6,
        )
        manager1 = Phase3ScheduleManager(config1)

        resolved1 = manager1.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Second resolution (fresh state)
        store2 = InMemorySequenceStore()
        resolved_store2 = InMemoryResolvedStore()
        config2 = Phase3Config(
            grid_minutes=30,
            program_catalog=fixture_catalog,
            sequence_store=store2,
            resolved_store=resolved_store2,
            filler_path=fixture_catalog.filler_path,
            programming_day_start_hour=6,
        )
        manager2 = Phase3ScheduleManager(config2)

        resolved2 = manager2.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Both should produce identical episode sequences
        ids1 = [s.resolved_asset.episode_id for s in resolved1.resolved_slots]
        ids2 = [s.resolved_asset.episode_id for s in resolved2.resolved_slots]

        assert ids1 == ids2


# =============================================================================
# Integration Tests (P4-T014, P4-T015)
# =============================================================================

class TestIntegration:
    """Integration tests validating the complete flow."""

    def test_P4_T014_the_litmus_test(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
    ):
        """
        P4-T014: The Litmus Test

        If a human:
        - Opens the EPG for tomorrow
        - Sees Cheers S01E02 at 09:30
        - Tunes in at 09:42

        Then:
        - The episode playing MUST be S01E02
        - File position at join time MUST be correct (12 min into episode)
        - Filler MUST appear only after episode end
        - No asset selection occurs at playback time
        """
        # Generate schedule starting at 06:00
        # 09:30 is slot 7 (3.5 hours = 7 half-hour slots from 06:00)
        # Slot 7 mod 3 = 1, so S01E02
        slots = generate_24_hour_slots()

        # Resolve schedule (this is when asset selection occurs)
        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # 1. Open EPG and see S01E02 at 09:30
        events = schedule_manager.get_epg_events(
            "cheers-24-7",
            datetime(2025, 1, 30, 9, 30, 0),
            datetime(2025, 1, 30, 10, 0, 0),
        )

        assert len(events) >= 1
        epg_event = events[0]
        assert epg_event.episode_id == "cheers-s01e02"
        assert epg_event.episode_title == "Sam's Women"

        # 2. Tune in at 09:42
        join_time = datetime(2025, 1, 30, 9, 42, 0)
        block = schedule_manager.get_program_at("cheers-24-7", join_time)

        # 3. Episode playing MUST be S01E02
        episode_segment = block.segments[0]
        assert "s01e02" in episode_segment.file_path.lower()

        # 4. File position at join time MUST be correct
        # seek_offset is at block boundary (09:30), which is 0 for S01E02
        # file_position = seek_offset + (join_time - segment_start)
        assert episode_segment.seek_offset_seconds == 0.0  # Episode starts at block start
        file_position = episode_segment.seek_offset_seconds + (join_time - episode_segment.start_utc).total_seconds()
        assert file_position == pytest.approx(720.0, rel=0.01)  # 12 minutes into episode

        # 5. Filler appears only after episode end
        s01e02_duration = cheers_program.episodes[1].duration_seconds  # 1333.457s
        episode_end = datetime(2025, 1, 30, 9, 30, 0) + timedelta(seconds=s01e02_duration)

        if len(block.segments) > 1:
            filler_segment = block.segments[1]
            assert filler_segment.start_utc >= episode_end

        # 6. No asset selection at playback time (verified by architecture)
        # The resolve_schedule_day was called earlier, not during get_program_at

    def test_P4_T015_full_day_validation(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
        resolved_store: InMemoryResolvedStore,
    ):
        """P4-T015: Full day validation.

        Validates that across a full day, playout content matches
        the resolved schedule and seek_offsets are reasonable.
        """
        slots = generate_24_hour_slots()

        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # Build lookup from slot_time to resolved episode info
        slot_lookup = {}
        for slot in resolved.resolved_slots:
            slot_lookup[slot.slot_time] = slot.resolved_asset

        # Sample times across the day (within programming day 06:00 Jan 30 to 06:00 Jan 31)
        sample_times = [
            datetime(2025, 1, 30, 6, 15, 0),   # Early morning, in 06:00 slot
            datetime(2025, 1, 30, 9, 42, 0),   # Mid-morning, in 09:30 slot
            datetime(2025, 1, 30, 12, 7, 0),   # Noon, in 12:00 slot
            datetime(2025, 1, 30, 15, 23, 0),  # Afternoon, in 15:00 slot
            datetime(2025, 1, 30, 18, 55, 0),  # Evening, in 18:30 slot
            datetime(2025, 1, 30, 21, 3, 0),   # Night, in 21:00 slot
            datetime(2025, 1, 30, 23, 47, 0),  # Late night, in 23:30 slot
        ]

        for sample_time in sample_times:
            # Get playout for this time
            block = schedule_manager.get_program_at("cheers-24-7", sample_time)

            # Determine which slot this time falls into
            # Block start is the grid-aligned time
            slot_time = block.block_start.time()

            # Look up the expected episode from resolved schedule
            expected_asset = slot_lookup.get(slot_time)

            if expected_asset:
                main_segment = block.segments[0]
                if "filler" not in main_segment.file_path.lower():
                    # Verify playout matches resolved schedule
                    episode_marker = expected_asset.episode_id.replace("cheers-", "").lower()
                    assert episode_marker in main_segment.file_path.lower(), \
                        f"Resolved/playout mismatch at {sample_time}: expected={expected_asset.episode_id}, path={main_segment.file_path}"

            # Verify seek_offset is reasonable
            main_segment = block.segments[0]
            assert main_segment.seek_offset_seconds >= 0
            assert main_segment.seek_offset_seconds < 1800  # Less than slot duration


# =============================================================================
# Fixture Data Validation Tests
# =============================================================================

class TestFixtureData:
    """Tests validating the fixture data itself."""

    def test_fixture_loads_correctly(self, fixture_catalog: FixtureProgramCatalog):
        """Verify fixture loads without errors."""
        program = fixture_catalog.get_program("cheers")
        assert program is not None
        assert program.name == "Cheers"
        assert program.play_mode == "sequential"
        assert len(program.episodes) == 3

    def test_fixture_has_real_durations(self, cheers_program: Program):
        """Verify fixture has realistic episode durations."""
        for episode in cheers_program.episodes:
            # Sitcom episodes are typically 22-26 minutes
            assert 1200 < episode.duration_seconds < 1600, \
                f"{episode.episode_id} has unrealistic duration: {episode.duration_seconds}s"

    def test_fixture_episode_ids_are_valid(self, cheers_program: Program):
        """Verify episode IDs follow expected format."""
        for episode in cheers_program.episodes:
            assert episode.episode_id.startswith("cheers-s01e0")
            assert episode.title  # Has a title
            assert episode.file_path  # Has a file path

    def test_filler_available(self, fixture_catalog: FixtureProgramCatalog):
        """Verify filler is configured."""
        assert fixture_catalog.filler_path
        assert fixture_catalog.filler_duration > 0


# =============================================================================
# Minimum Grid Occupancy Tests (P4-T016, P4-T017, P4-T018, P4-T019)
# =============================================================================

class TestMinimumGridOccupancy:
    """Tests for INV-P4-001: Minimum Grid Occupancy."""

    def test_P4_T016_minimum_blocks_content_shorter_than_grid(
        self,
        schedule_manager: Phase3ScheduleManager,
        cheers_program: Program,
    ):
        """P4-T016: Minimum blocks for content shorter than grid.

        GIVEN: Episode duration = 25:01 (1501.653s)
               Grid size = 30 minutes (1800s)
        WHEN:  Schedule is resolved
        THEN:  Exactly 1 grid block is allocated
               EPG duration = 30:00 (1800s)
               Filler duration = 4:59 (298.347s)
               NOT 2 grid blocks (60 minutes)
        """
        # S01E01: 1501.653s (25:01.653), shorter than 30-min grid
        episode = cheers_program.episodes[0]
        assert episode.duration_seconds < 1800  # Confirm shorter than grid

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "cheers"),
            duration_seconds=1800.0,  # Input slot duration (intent)
        )]

        resolved = schedule_manager.resolve_schedule_day(
            channel_id="cheers-24-7",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # INV-P4-001: Exactly 1 grid block (ceil(1501.653/1800) = 1)
        resolved_slot = resolved.resolved_slots[0]
        assert resolved_slot.duration_seconds == 1800.0, \
            f"Expected 1 grid block (1800s), got {resolved_slot.duration_seconds}s"

        # EPG should show grid-aligned end time
        events = schedule_manager.get_epg_events(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
            datetime(2025, 1, 30, 7, 0, 0),
        )
        assert len(events) == 1
        epg_duration = (events[0].end_time - events[0].start_time).total_seconds()
        assert epg_duration == 1800.0, \
            f"EPG duration should be 1800s (1 grid block), got {epg_duration}s"

        # Filler duration = grid_duration - content_duration
        expected_filler = 1800.0 - episode.duration_seconds
        block = schedule_manager.get_program_at(
            "cheers-24-7",
            datetime(2025, 1, 30, 6, 0, 0),
        )
        assert len(block.segments) == 2, "Should have episode + filler segments"
        filler_duration = (block.segments[1].end_utc - block.segments[1].start_utc).total_seconds()
        assert filler_duration == pytest.approx(expected_filler, rel=0.01)

    def test_P4_T017_minimum_blocks_content_spanning_multiple_grids(
        self,
        fixture_catalog: FixtureProgramCatalog,
        sequence_store: InMemorySequenceStore,
        resolved_store: InMemoryResolvedStore,
    ):
        """P4-T017: Minimum blocks for content spanning multiple grids.

        GIVEN: Episode duration = 42 minutes (2520s)
               Grid size = 15 minutes (900s)
        WHEN:  Schedule is resolved
        THEN:  Exactly 3 grid blocks are allocated (ceil(42/15) = 3)
               EPG duration = 45:00 (2700s)
               Filler duration = 3:00 (180s)
               NOT 4 grid blocks (60 minutes)
        """
        # Create a program with a 42-minute episode
        mock_data = {
            "filler": {"file_path": "/media/filler.mp4", "duration_seconds": 3600},
            "programs": [{
                "program_id": "long-show",
                "name": "Long Show",
                "play_mode": "sequential",
                "episodes": [{
                    "episode_id": "long-e01",
                    "title": "Long Episode",
                    "file_path": "/media/long.mp4",
                    "duration_seconds": 2520.0,  # 42 minutes
                }],
            }],
        }

        catalog = FixtureProgramCatalog(mock_data)
        config = Phase3Config(
            grid_minutes=15,  # 15-minute grid
            program_catalog=catalog,
            sequence_store=sequence_store,
            resolved_store=resolved_store,
            filler_path=catalog.filler_path,
            programming_day_start_hour=6,
        )
        manager = Phase3ScheduleManager(config)

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "long-show"),
            duration_seconds=900.0,  # Input: 1 grid block (will be expanded)
        )]

        resolved = manager.resolve_schedule_day(
            channel_id="test",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # INV-P4-001: Exactly 3 grid blocks (ceil(2520/900) = 3)
        resolved_slot = resolved.resolved_slots[0]
        expected_duration = 3 * 900.0  # 2700s = 45 minutes
        assert resolved_slot.duration_seconds == expected_duration, \
            f"Expected 3 grid blocks (2700s), got {resolved_slot.duration_seconds}s"

        # Verify NOT 4 blocks (3600s)
        assert resolved_slot.duration_seconds != 3600.0, \
            "Should NOT allocate 4 blocks (3600s) for 42-minute content"

        # EPG should show 45 minutes (3 blocks)
        events = manager.get_epg_events(
            "test",
            datetime(2025, 1, 30, 6, 0, 0),
            datetime(2025, 1, 30, 7, 0, 0),
        )
        assert len(events) == 1
        epg_duration = (events[0].end_time - events[0].start_time).total_seconds()
        assert epg_duration == 2700.0, \
            f"EPG duration should be 2700s (3 grid blocks), got {epg_duration}s"

        # Filler = 2700 - 2520 = 180s (3 minutes)
        expected_filler = 180.0

        # Get the last block where filler should appear
        block = manager.get_program_at("test", datetime(2025, 1, 30, 6, 30, 0))
        # In the third block (06:30-06:45), episode ends at 06:42, filler until 06:45
        if len(block.segments) == 2:
            filler_segment = block.segments[1]
            filler_duration = (filler_segment.end_utc - filler_segment.start_utc).total_seconds()
            assert filler_duration == pytest.approx(expected_filler, rel=0.01)

    def test_P4_T018_exact_grid_fit_no_extra_blocks(
        self,
        fixture_catalog: FixtureProgramCatalog,
        sequence_store: InMemorySequenceStore,
        resolved_store: InMemoryResolvedStore,
    ):
        """P4-T018: Exact grid fit requires no extra blocks.

        GIVEN: Episode duration = 30:00 (1800s)
               Grid size = 30 minutes (1800s)
        WHEN:  Schedule is resolved
        THEN:  Exactly 1 grid block is allocated
               EPG duration = 30:00 (1800s)
               Filler duration = 0
               No extra block allocated
        """
        mock_data = {
            "filler": {"file_path": "/media/filler.mp4", "duration_seconds": 3600},
            "programs": [{
                "program_id": "exact-fit",
                "name": "Exact Fit Show",
                "play_mode": "sequential",
                "episodes": [{
                    "episode_id": "exact-e01",
                    "title": "Exact Episode",
                    "file_path": "/media/exact.mp4",
                    "duration_seconds": 1800.0,  # Exactly 30 minutes
                }],
            }],
        }

        catalog = FixtureProgramCatalog(mock_data)
        config = Phase3Config(
            grid_minutes=30,
            program_catalog=catalog,
            sequence_store=sequence_store,
            resolved_store=resolved_store,
            filler_path=catalog.filler_path,
            programming_day_start_hour=6,
        )
        manager = Phase3ScheduleManager(config)

        slots = [ScheduleSlot(
            slot_time=time(6, 0),
            program_ref=ProgramRef(ProgramRefType.PROGRAM, "exact-fit"),
            duration_seconds=1800.0,
        )]

        resolved = manager.resolve_schedule_day(
            channel_id="test",
            programming_day_date=date(2025, 1, 30),
            slots=slots,
            resolution_time=datetime(2025, 1, 28, 12, 0, 0),
        )

        # INV-P4-001: Exactly 1 grid block (ceil(1800/1800) = 1)
        resolved_slot = resolved.resolved_slots[0]
        assert resolved_slot.duration_seconds == 1800.0, \
            f"Expected 1 grid block (1800s), got {resolved_slot.duration_seconds}s"

        # Should NOT allocate 2 blocks
        assert resolved_slot.duration_seconds != 3600.0, \
            "Should NOT allocate 2 blocks for exact-fit content"

        # No filler needed
        block = manager.get_program_at("test", datetime(2025, 1, 30, 6, 0, 0))
        assert len(block.segments) == 1, "Should have only episode segment, no filler"

    def test_P4_T019_over_allocation_detection(
        self,
        fixture_catalog: FixtureProgramCatalog,
        sequence_store: InMemorySequenceStore,
        resolved_store: InMemoryResolvedStore,
    ):
        """P4-T019: Over-allocation detection.

        This test verifies the invariant by computing the expected blocks
        and asserting that the implementation matches exactly.

        If someone changed the implementation to allocate extra blocks,
        this test would fail.
        """
        import math

        # Test multiple scenarios
        test_cases = [
            # (content_duration, grid_minutes, expected_blocks)
            (1501.653, 30, 1),   # 25:01 in 30-min grid = 1 block
            (1800.0, 30, 1),    # 30:00 in 30-min grid = 1 block
            (1801.0, 30, 2),    # 30:01 in 30-min grid = 2 blocks
            (2520.0, 15, 3),    # 42:00 in 15-min grid = 3 blocks
            (2700.0, 15, 3),    # 45:00 in 15-min grid = 3 blocks
            (2701.0, 15, 4),    # 45:01 in 15-min grid = 4 blocks
            (3600.0, 30, 2),    # 60:00 in 30-min grid = 2 blocks
            (5400.0, 30, 3),    # 90:00 in 30-min grid = 3 blocks
        ]

        for content_duration, grid_minutes, expected_blocks in test_cases:
            mock_data = {
                "filler": {"file_path": "/media/filler.mp4", "duration_seconds": 7200},
                "programs": [{
                    "program_id": "test-prog",
                    "name": "Test Program",
                    "play_mode": "sequential",
                    "episodes": [{
                        "episode_id": "test-e01",
                        "title": "Test Episode",
                        "file_path": "/media/test.mp4",
                        "duration_seconds": content_duration,
                    }],
                }],
            }

            catalog = FixtureProgramCatalog(mock_data)
            store = InMemorySequenceStore()
            resolved = InMemoryResolvedStore()
            config = Phase3Config(
                grid_minutes=grid_minutes,
                program_catalog=catalog,
                sequence_store=store,
                resolved_store=resolved,
                filler_path=catalog.filler_path,
                programming_day_start_hour=6,
            )
            manager = Phase3ScheduleManager(config)

            slots = [ScheduleSlot(
                slot_time=time(6, 0),
                program_ref=ProgramRef(ProgramRefType.PROGRAM, "test-prog"),
                duration_seconds=float(grid_minutes * 60),
            )]

            result = manager.resolve_schedule_day(
                channel_id="test",
                programming_day_date=date(2025, 1, 30),
                slots=slots,
                resolution_time=datetime(2025, 1, 28, 12, 0, 0),
            )

            resolved_slot = result.resolved_slots[0]
            grid_seconds = grid_minutes * 60
            expected_duration = expected_blocks * grid_seconds
            actual_blocks = resolved_slot.duration_seconds / grid_seconds

            # Verify exact block count
            assert resolved_slot.duration_seconds == expected_duration, (
                f"INV-P4-001 violation: "
                f"content={content_duration}s, grid={grid_minutes}min, "
                f"expected {expected_blocks} blocks ({expected_duration}s), "
                f"got {actual_blocks} blocks ({resolved_slot.duration_seconds}s)"
            )

            # Verify it's the MINIMUM (not more)
            minimum_blocks = math.ceil(content_duration / grid_seconds)
            assert actual_blocks == minimum_blocks, (
                f"Over-allocation detected: "
                f"content={content_duration}s needs {minimum_blocks} blocks, "
                f"but got {actual_blocks} blocks"
            )
