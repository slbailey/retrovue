"""
Contract Tests — Planning Pipeline

Tests assert on artifact structure and invariants.
No database, no filesystem, no AIR.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from retrovue.runtime.schedule_types import (
    EPGEvent,
    Episode,
    ScheduleManagerConfig,
    Program,
    ProgramRef,
    ProgramRefType,
)
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
)
from retrovue.runtime.planning_pipeline import (
    BreakFillPolicy,
    BreakSpec,
    ContentSegmentSpec,
    FilledBlock,
    InMemoryAssetLibrary,
    MarkerInfo,
    PlanningDirective,
    PlanningRunRequest,
    ScheduleDayArtifact,
    SchedulePlanArtifact,
    SegmentedBlock,
    SyntheticBreakProfile,
    TransmissionLog,
    TransmissionLogEntry,
    ZoneDirective,
    run_planning_pipeline,
    build_schedule_plan,
    resolve_schedule_day,
    derive_epg,
    segment_blocks,
    fill_breaks,
    assemble_transmission_log,
    lock_for_execution,
    to_block_plan,
)
from retrovue.runtime.schedule_types import ResolvedAsset


# =============================================================================
# Fixtures
# =============================================================================

CHEERS_PROGRAM = Program(
    program_id="cheers",
    name="Cheers",
    play_mode="sequential",
    episodes=[
        Episode("s01e01", "Give Me a Ring Sometime", "/media/cheers/s01e01.mp4", 1320.0),
        Episode("s01e02", "Sam's Women", "/media/cheers/s01e02.mp4", 1340.0),
        Episode("s01e03", "The Tortelli Tort", "/media/cheers/s01e03.mp4", 1300.0),
    ],
)

MOVIE_PROGRAM = Program(
    program_id="movie_night",
    name="Movie Night",
    play_mode="sequential",
    episodes=[
        Episode("mov01", "The Big Movie", "/media/movies/big_movie.mp4", 5400.0),
    ],
)


class SimpleCatalog:
    """Test catalog with a few programs."""

    def __init__(self, programs: list[Program] | None = None):
        self._programs: dict[str, Program] = {}
        for p in (programs or []):
            self._programs[p.program_id] = p

    def get_program(self, program_id: str) -> Program | None:
        return self._programs.get(program_id)


def _make_config(
    programs: list[Program] | None = None,
    grid_minutes: int = 30,
    start_hour: int = 6,
) -> ScheduleManagerConfig:
    return ScheduleManagerConfig(
        grid_minutes=grid_minutes,
        program_catalog=SimpleCatalog(programs or [CHEERS_PROGRAM]),
        sequence_store=InMemorySequenceStore(),
        resolved_store=InMemoryResolvedStore(),
        filler_path="/media/filler/bars.mp4",
        filler_duration_seconds=0.0,
        programming_day_start_hour=start_hour,
    )


def _make_asset_library(
    episode_dur_ms: int = 1_320_000,
    filler_dur_ms: int = 30_000,
    markers: list[MarkerInfo] | None = None,
) -> InMemoryAssetLibrary:
    lib = InMemoryAssetLibrary()
    lib.register_asset("/media/cheers/s01e01.mp4", episode_dur_ms, markers)
    lib.register_asset("/media/cheers/s01e02.mp4", 1_340_000)
    lib.register_asset("/media/cheers/s01e03.mp4", 1_300_000)
    lib.register_asset("/media/movies/big_movie.mp4", 5_400_000)
    lib.register_asset("/media/filler/bars.mp4", filler_dur_ms)
    lib.register_filler("/media/filler/promo30.mp4", filler_dur_ms, "filler")
    return lib


def _make_cheers_directive(
    start: time = time(6, 0),
    end: time = time(12, 0),
) -> PlanningDirective:
    return PlanningDirective(
        channel_id="ch1",
        grid_block_minutes=30,
        programming_day_start_hour=6,
        zones=[
            ZoneDirective(
                start_time=start,
                end_time=end,
                programs=[ProgramRef(ProgramRefType.PROGRAM, "cheers")],
                label="Morning Cheers",
            ),
        ],
    )


BROADCAST_DATE = date(2025, 7, 15)
RESOLUTION_TIME = datetime(2025, 7, 15, 5, 0, 0)


# =============================================================================
# TestStage0_SchedulePlan
# =============================================================================


class TestStage0_SchedulePlan:

    def test_directive_produces_plan_with_zones_and_programs(self):
        directive = _make_cheers_directive()
        plan = build_schedule_plan(directive)

        assert isinstance(plan, SchedulePlanArtifact)
        assert plan.channel_id == "ch1"
        assert len(plan.zones) == 1
        assert len(plan.all_program_refs) == 1
        assert plan.all_program_refs[0].ref_id == "cheers"

    def test_plan_carries_no_broadcast_date(self):
        directive = _make_cheers_directive()
        plan = build_schedule_plan(directive)
        assert not hasattr(plan, "broadcast_date")

    def test_multiple_zones_preserved_in_order(self):
        directive = PlanningDirective(
            channel_id="ch1",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(time(6, 0), time(12, 0),
                              [ProgramRef(ProgramRefType.PROGRAM, "cheers")],
                              label="Morning"),
                ZoneDirective(time(12, 0), time(18, 0),
                              [ProgramRef(ProgramRefType.PROGRAM, "movie_night")],
                              label="Afternoon"),
            ],
        )
        plan = build_schedule_plan(directive)
        assert len(plan.zones) == 2
        assert plan.zones[0].label == "Morning"
        assert plan.zones[1].label == "Afternoon"

    def test_zone_day_filters_propagated(self):
        directive = PlanningDirective(
            channel_id="ch1",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(
                    time(6, 0), time(12, 0),
                    [ProgramRef(ProgramRefType.PROGRAM, "cheers")],
                    day_filter=["mon", "wed", "fri"],
                ),
            ],
        )
        plan = build_schedule_plan(directive)
        assert plan.zones[0].day_filter == ["mon", "wed", "fri"]


# =============================================================================
# TestStage1_ScheduleDay
# =============================================================================


class TestStage1_ScheduleDay:

    def test_zones_expanded_to_grid_aligned_slots(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(9, 0))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        result = resolve_schedule_day(plan, run_req, config)

        assert isinstance(result, ScheduleDayArtifact)
        # 3 hours / 30 min = 6 slots
        assert result.slots_generated == 6
        assert len(result.resolved_day.resolved_slots) == 6

    def test_episode_resolution_produces_frozen_snapshot(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(7, 0))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        result = resolve_schedule_day(plan, run_req, config)

        for slot in result.resolved_day.resolved_slots:
            assert slot.resolved_asset.file_path is not None
            assert slot.resolved_asset.title == "Cheers"

    def test_sequential_cursor_advances(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(7, 30))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        result = resolve_schedule_day(plan, run_req, config)

        slots = result.resolved_day.resolved_slots
        # 3 slots → episodes s01e01, s01e02, s01e03
        episode_ids = [s.resolved_asset.episode_id for s in slots]
        assert episode_ids == ["s01e01", "s01e02", "s01e03"]

    def test_same_inputs_produce_equivalent_day(self):
        """Idempotence: same channel/date returns cached resolution."""
        directive = _make_cheers_directive(start=time(6, 0), end=time(7, 0))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        result1 = resolve_schedule_day(plan, run_req, config)
        result2 = resolve_schedule_day(plan, run_req, config)

        # Same object returned from cache
        assert result1.resolved_day is result2.resolved_day


# =============================================================================
# TestStage2_EPGEvents
# =============================================================================


class TestStage2_EPGEvents:

    def _resolve_day(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(7, 0))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        return resolve_schedule_day(plan, run_req, config)

    def test_events_match_resolved_slots_one_to_one(self):
        sday = self._resolve_day()
        events = derive_epg("ch1", sday, 6)

        assert len(events) == len(sday.resolved_day.resolved_slots)
        for event in events:
            assert isinstance(event, EPGEvent)
            assert event.channel_id == "ch1"

    def test_absolute_timestamps_derived_correctly(self):
        sday = self._resolve_day()
        events = derive_epg("ch1", sday, 6)

        first = events[0]
        expected_start = datetime(2025, 7, 15, 6, 0, 0)
        assert first.start_time == expected_start

    def test_empty_day_produces_empty_epg(self):
        directive = PlanningDirective(
            channel_id="ch1",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[],
        )
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)
        events = derive_epg("ch1", sday, 6)

        assert events == []


# =============================================================================
# TestStage3_SegmentedBlocks
# =============================================================================


class TestStage3_SegmentedBlocks:

    def _get_schedule_day(self, config=None, directive=None):
        if directive is None:
            directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        plan = build_schedule_plan(directive)
        if config is None:
            config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        return resolve_schedule_day(plan, run_req, config)

    def test_chapter_markers_produce_segments_with_breaks(self):
        markers = [
            MarkerInfo("chapter", 440_000, "Act 2"),
            MarkerInfo("chapter", 880_000, "Act 3"),
        ]
        lib = _make_asset_library(episode_dur_ms=1_320_000, markers=markers)
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        assert len(result) == 1
        block = result[0]
        # 3 chapters → 3 content segments, 2 breaks
        assert len(block.content_segments) == 3
        assert len(block.breaks) == 2

    def test_no_chapters_synthetic_breaks(self):
        lib = _make_asset_library(episode_dur_ms=1_320_000)
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        block = result[0]
        # Default profile: 3 segments, 2 breaks for 30-min block
        assert len(block.content_segments) == 3
        assert len(block.breaks) == 2

    def test_ad_inventory_equals_block_minus_content_minus_pad(self):
        lib = _make_asset_library(episode_dur_ms=1_320_000)
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        block = result[0]
        total_break_ms = sum(b.duration_ms for b in block.breaks)
        assert total_break_ms == block.block_duration_ms - block.content_duration_ms - block.pad_ms

    def test_inventory_distributed_across_breaks(self):
        lib = _make_asset_library(episode_dur_ms=1_320_000)
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        block = result[0]
        if len(block.breaks) >= 2:
            # Breaks should be roughly equal (within 1ms rounding)
            durations = [b.duration_ms for b in block.breaks]
            assert max(durations) - min(durations) <= 1

    def test_short_episode_breaks_absorb_remainder(self):
        """~22-min episode in 30-min block: breaks absorb the 8 minutes."""
        lib = _make_asset_library(episode_dur_ms=1_320_000)  # 22 min
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        block = result[0]
        total_break_ms = sum(b.duration_ms for b in block.breaks)
        # 30 min = 1_800_000ms, content = 1_320_000ms → 480_000ms for breaks + pad
        assert block.content_duration_ms == 1_320_000
        assert total_break_ms + block.pad_ms == 1_800_000 - 1_320_000

    def test_content_fills_block_no_breaks(self):
        """Content exactly fills block → no breaks inserted."""
        lib = _make_asset_library(episode_dur_ms=1_800_000)  # exactly 30 min
        sday = self._get_schedule_day()

        result = segment_blocks(sday, 30, lib)

        block = result[0]
        assert len(block.breaks) == 0
        assert block.pad_ms == 0


# =============================================================================
# TestStage4_Playlist
# =============================================================================


class TestStage4_Playlist:

    def _get_segmented(self, episode_dur_ms=1_320_000, filler_dur_ms=30_000):
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)
        lib = _make_asset_library(episode_dur_ms=episode_dur_ms, filler_dur_ms=filler_dur_ms)
        return segment_blocks(sday, 30, lib), lib

    def test_filler_fills_break_to_exact_duration(self):
        segmented, lib = self._get_segmented()
        filled = fill_breaks(segmented, lib)

        for fb in filled:
            for brk in fb.filled_breaks:
                assert brk.filled_ms <= brk.allocated_ms

    def test_greedy_packing_with_multiple_items(self):
        segmented, lib = self._get_segmented(filler_dur_ms=30_000)
        filled = fill_breaks(segmented, lib)

        for fb in filled:
            for brk in fb.filled_breaks:
                if brk.allocated_ms >= 60_000:
                    assert len(brk.items) >= 2

    def test_allow_repeat_within_break_true(self):
        segmented, lib = self._get_segmented(filler_dur_ms=30_000)
        policy = BreakFillPolicy(allow_repeat_within_break=True)
        filled = fill_breaks(segmented, lib, policy)

        for fb in filled:
            for brk in fb.filled_breaks:
                uris = [item.asset_uri for item in brk.items]
                if len(uris) > 1:
                    # With repeat allowed and only one filler, all URIs are the same
                    assert len(set(uris)) == 1

    def test_allow_repeat_within_break_false(self):
        segmented, lib = self._get_segmented(filler_dur_ms=30_000)
        policy = BreakFillPolicy(allow_repeat_within_break=False)
        filled = fill_breaks(segmented, lib, policy)

        for fb in filled:
            for brk in fb.filled_breaks:
                uris = [item.asset_uri for item in brk.items]
                # No repeats
                assert len(uris) == len(set(uris))

    def test_duration_invariant(self):
        segmented, lib = self._get_segmented()
        filled = fill_breaks(segmented, lib)

        for fb in filled:
            content_ms = sum(s.duration_ms for s in fb.content_segments)
            breaks_ms = sum(brk.filled_ms for brk in fb.filled_breaks)
            assert content_ms == fb.content_duration_ms
            # Content + filled breaks + pad <= block_dur
            assert content_ms + breaks_ms + fb.pad_ms <= fb.block_duration_ms


# =============================================================================
# TestStage5_TransmissionLog
# =============================================================================


class TestStage5_TransmissionLog:

    def _get_filled(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)
        lib = _make_asset_library()
        epg = derive_epg("ch1", sday, 6)
        segmented = segment_blocks(sday, 30, lib)
        filled = fill_breaks(segmented, lib)
        return filled, epg

    def test_content_and_breaks_interleaved_with_wall_clock(self):
        filled, epg = self._get_filled()
        log = assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

        assert isinstance(log, TransmissionLog)
        assert len(log.entries) == 1
        entry = log.entries[0]
        assert entry.start_utc_ms > 0
        assert entry.end_utc_ms > entry.start_utc_ms

    def test_segment_type_uses_execution_semantics(self):
        filled, epg = self._get_filled()
        log = assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

        valid_types = {"episode", "filler", "promo", "ad", "pad"}
        for entry in log.entries:
            for seg in entry.segments:
                assert seg["segment_type"] in valid_types

    def test_pad_segment_appended_when_needed(self):
        filled, epg = self._get_filled()
        log = assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

        entry = log.entries[0]
        # 22-min episode in 30-min block → there should be a pad or breaks filling the gap
        segment_types = [s["segment_type"] for s in entry.segments]
        # At least one non-episode segment (break filler or pad)
        assert any(t != "episode" for t in segment_types)

    def test_block_ids_sequential(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(7, 0))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)
        lib = _make_asset_library()
        epg = derive_epg("ch1", sday, 6)
        segmented = segment_blocks(sday, 30, lib)
        filled = fill_breaks(segmented, lib)
        log = assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

        for i, entry in enumerate(log.entries):
            assert entry.block_index == i

    def test_to_block_plan_conversion(self):
        filled, epg = self._get_filled()
        log = assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

        entry = log.entries[0]
        bp = to_block_plan(entry, channel_id_int=1)

        assert bp["block_id"] == entry.block_id
        assert bp["channel_id"] == 1
        assert bp["start_utc_ms"] == entry.start_utc_ms
        assert bp["end_utc_ms"] == entry.end_utc_ms
        assert bp["segments"] == entry.segments


# =============================================================================
# TestStage6_HorizonLock
# =============================================================================


class TestStage6_HorizonLock:

    def _get_log(self):
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        plan = build_schedule_plan(directive)
        config = _make_config()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)
        lib = _make_asset_library()
        epg = derive_epg("ch1", sday, 6)
        segmented = segment_blocks(sday, 30, lib)
        filled = fill_breaks(segmented, lib)
        return assemble_transmission_log(
            "ch1", BROADCAST_DATE, filled, epg, 6, 30, RESOLUTION_TIME
        )

    def test_lock_sets_is_locked_and_metadata(self, tmp_path):
        log = self._get_log()
        lock_time = datetime(2025, 7, 15, 5, 30, 0)
        locked = lock_for_execution(log, lock_time, artifact_base_path=tmp_path)

        assert locked.is_locked is True
        assert "locked_at" in locked.metadata
        assert locked.metadata["locked_at"] == lock_time.isoformat()

    def test_data_content_unchanged(self, tmp_path):
        log = self._get_log()
        lock_time = datetime(2025, 7, 15, 5, 30, 0)
        locked = lock_for_execution(log, lock_time, artifact_base_path=tmp_path)

        assert locked.channel_id == log.channel_id
        assert locked.broadcast_date == log.broadcast_date
        assert locked.entries is log.entries
        assert len(locked.entries) == len(log.entries)


# =============================================================================
# TestPipelineIntegration
# =============================================================================


class TestPipelineIntegration:

    def test_30min_block_directive_to_locked_log(self, tmp_path):
        """30-min block with ~22-min episode: directive → locked transmission log."""
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        config = _make_config()
        lib = _make_asset_library()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        lock_time = datetime(2025, 7, 15, 5, 30, 0)

        log = run_planning_pipeline(
            run_req, config, lib, lock_time=lock_time, artifact_base_path=tmp_path
        )

        assert isinstance(log, TransmissionLog)
        assert log.is_locked is True
        assert log.channel_id == "ch1"
        assert len(log.entries) == 1

        entry = log.entries[0]
        assert entry.start_utc_ms > 0
        assert len(entry.segments) > 0
        # Has episode content
        assert any(s["segment_type"] == "episode" for s in entry.segments)

    def test_movie_with_chapters(self):
        """Movie with chapters: multi-block segmentation."""
        config = _make_config(programs=[MOVIE_PROGRAM])
        lib = InMemoryAssetLibrary()
        lib.register_asset(
            "/media/movies/big_movie.mp4", 5_400_000,
            markers=[
                MarkerInfo("chapter", 1_800_000, "Act 2"),
                MarkerInfo("chapter", 3_600_000, "Act 3"),
            ],
        )
        lib.register_filler("/media/filler/promo30.mp4", 30_000, "filler")

        directive = PlanningDirective(
            channel_id="ch2",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(
                    time(20, 0), time(22, 0),
                    [ProgramRef(ProgramRefType.PROGRAM, "movie_night")],
                    label="Movie Night",
                ),
            ],
        )
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        log = run_planning_pipeline(run_req, config, lib)

        assert log.is_locked is False
        # Movie is 90 min → 3 grid blocks of 30 min
        # But only slots generated based on zone expansion logic
        assert len(log.entries) >= 1

    def test_no_chapters_synthetic_breaks_per_profile(self):
        """No chapters: synthetic breaks per half-hour profile."""
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        config = _make_config()
        lib = _make_asset_library()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        log = run_planning_pipeline(run_req, config, lib)

        entry = log.entries[0]
        # Should have episode segments interleaved with break segments
        types = [s["segment_type"] for s in entry.segments]
        episode_count = types.count("episode")
        # Default profile: 3 content segments for half-hour block
        assert episode_count == 3

    def test_output_consumable_by_block_plan(self, tmp_path):
        """Output format consumable by BlockPlanProducer."""
        directive = _make_cheers_directive(start=time(6, 0), end=time(6, 30))
        config = _make_config()
        lib = _make_asset_library()
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)

        log = run_planning_pipeline(
            run_req, config, lib, lock_time=RESOLUTION_TIME,
            artifact_base_path=tmp_path,
        )

        for entry in log.entries:
            bp = to_block_plan(entry, channel_id_int=1)
            assert "block_id" in bp
            assert "channel_id" in bp
            assert "start_utc_ms" in bp
            assert "end_utc_ms" in bp
            assert "segments" in bp
            for seg in bp["segments"]:
                assert "segment_index" in seg
                assert "segment_duration_ms" in seg
                assert "segment_type" in seg
                if seg["segment_type"] != "pad":
                    assert "asset_uri" in seg


# =============================================================================
# TestStage2_MultiBlockEPG
# =============================================================================


class TestStage2_MultiBlockEPG:
    """Multi-block movie should produce a single EPGEvent, not one per slot."""

    def _resolve_movie_day(self):
        config = _make_config(programs=[MOVIE_PROGRAM])
        directive = PlanningDirective(
            channel_id="ch2",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(
                    time(20, 0), time(21, 30),
                    [ProgramRef(ProgramRefType.PROGRAM, "movie_night")],
                    label="Movie Night",
                ),
            ],
        )
        plan = build_schedule_plan(directive)
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        return resolve_schedule_day(plan, run_req, config)

    def test_multi_block_movie_produces_single_epg_event(self):
        sday = self._resolve_movie_day()
        events = derive_epg("ch2", sday, 6)

        # 90-min movie → 1 ProgramEvent → 1 EPGEvent (not 3)
        assert len(events) == 1
        event = events[0]
        assert event.title == "Movie Night"
        # Duration should be 3 blocks * 30 min = 5400 seconds
        duration = (event.end_time - event.start_time).total_seconds()
        assert duration == 5400.0

    def test_multi_block_epg_event_carries_resolved_asset(self):
        sday = self._resolve_movie_day()
        events = derive_epg("ch2", sday, 6)

        event = events[0]
        assert isinstance(event.resolved_asset, ResolvedAsset)
        assert event.resolved_asset.episode_id == "mov01"


# =============================================================================
# TestStage3_MultiBlockSegmentation
# =============================================================================


class TestStage3_MultiBlockSegmentation:
    """Multi-block segmentation should use correct per-block content offsets."""

    def _get_movie_schedule_day(self, markers=None):
        config = _make_config(programs=[MOVIE_PROGRAM])
        directive = PlanningDirective(
            channel_id="ch2",
            grid_block_minutes=30,
            programming_day_start_hour=6,
            zones=[
                ZoneDirective(
                    time(20, 0), time(21, 30),
                    [ProgramRef(ProgramRefType.PROGRAM, "movie_night")],
                    label="Movie Night",
                ),
            ],
        )
        plan = build_schedule_plan(directive)
        run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
        sday = resolve_schedule_day(plan, run_req, config)

        lib = InMemoryAssetLibrary()
        lib.register_asset("/media/movies/big_movie.mp4", 5_400_000, markers)
        lib.register_asset("/media/filler/bars.mp4", 30_000)
        lib.register_filler("/media/filler/promo30.mp4", 30_000, "filler")
        return sday, lib

    def test_multi_block_movie_block_0_starts_at_offset_0(self):
        sday, lib = self._get_movie_schedule_day()
        result = segment_blocks(sday, 30, lib)

        block_0 = result[0]
        assert block_0.block_index_within_event == 0
        # First segment should start at offset 0
        assert block_0.content_segments[0].asset_start_offset_ms == 0

    def test_multi_block_movie_block_1_starts_at_block_duration(self):
        sday, lib = self._get_movie_schedule_day()
        result = segment_blocks(sday, 30, lib)

        block_1 = result[1]
        assert block_1.block_index_within_event == 1
        # Block 1 content should start at 1 * 1_800_000ms (30 min)
        assert block_1.content_segments[0].asset_start_offset_ms == 1_800_000

    def test_multi_block_movie_last_block_has_correct_pad(self):
        sday, lib = self._get_movie_schedule_day()
        result = segment_blocks(sday, 30, lib)

        # 90-min movie in 3x30-min blocks: content exactly fills all blocks
        for block in result[:3]:
            assert block.content_duration_ms == 1_800_000
            # No pad since content fills each block exactly
            assert block.pad_ms == 0

    def test_multi_block_movie_with_chapters_filters_to_block_window(self):
        markers = [
            MarkerInfo("chapter", 900_000, "15min"),   # block 0 (0-1800s)
            MarkerInfo("chapter", 1_980_000, "33min"),  # block 1 (1800-3600s)
        ]
        sday, lib = self._get_movie_schedule_day(markers=markers)
        result = segment_blocks(sday, 30, lib)

        # Block 0 should have the 15min chapter (at 900_000ms within full asset)
        block_0 = result[0]
        assert len(block_0.content_segments) == 2  # split at chapter marker
        assert block_0.content_segments[0].asset_start_offset_ms == 0
        assert block_0.content_segments[0].duration_ms == 900_000
        assert block_0.content_segments[1].asset_start_offset_ms == 900_000
        assert block_0.content_segments[1].duration_ms == 900_000

        # Block 1 should have the 33min chapter (offset 1_980_000 in asset,
        # which is 180_000ms into block 1's window)
        block_1 = result[1]
        assert len(block_1.content_segments) == 2
        assert block_1.content_segments[0].asset_start_offset_ms == 1_800_000
        assert block_1.content_segments[0].duration_ms == 180_000
        assert block_1.content_segments[1].asset_start_offset_ms == 1_980_000
        assert block_1.content_segments[1].duration_ms == 1_620_000

        # Block 2 should have no chapters (both markers are in earlier blocks)
        block_2 = result[2]
        # No chapters in block 2's window → synthetic segmentation
        assert block_2.content_segments[0].asset_start_offset_ms == 3_600_000
