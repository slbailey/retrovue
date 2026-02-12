"""
Integration Tests — Planning Pipeline with Real Catalog Data

Proves the planning pipeline (Stages 0→6) works end-to-end with real
Cheers episodes, real chapter markers, real filler, and sequential
episode advancement across a full 24-hour broadcast day.

Uses:
- StaticAssetLibrary loaded from config/asset_catalog.json
- JsonFileProgramCatalog loaded from config/programs/
- InMemorySequenceStore + InMemoryResolvedStore (volatile)
- PlanningDirective with single full-day zone (06:00→06:00 wraps to 24h)
"""

from __future__ import annotations

from datetime import date, datetime, time
from pathlib import Path

import pytest

from retrovue.catalog.static_asset_library import StaticAssetLibrary
from retrovue.runtime.schedule_manager_service import (
    InMemoryResolvedStore,
    InMemorySequenceStore,
    JsonFileProgramCatalog,
)
from retrovue.runtime.planning_pipeline import (
    PlanningDirective,
    PlanningRunRequest,
    ZoneDirective,
    run_planning_pipeline,
)
from retrovue.runtime.schedule_types import (
    ScheduleManagerConfig,
    ProgramRef,
    ProgramRefType,
)


# =============================================================================
# Paths
# =============================================================================

REPO_ROOT = Path(__file__).resolve().parents[4]  # pkg/core/tests/integration -> repo root
CATALOG_PATH = REPO_ROOT / "config" / "asset_catalog.json"
PROGRAMS_DIR = REPO_ROOT / "config" / "programs"
FILLER_URI = "/opt/retrovue/assets/filler.mp4"
FILLER_DURATION_MS = 3_650_455

BROADCAST_DATE = date(2025, 7, 15)
RESOLUTION_TIME = datetime(2025, 7, 15, 5, 0, 0)
LOCK_TIME = datetime(2025, 7, 15, 5, 30, 0)

NUM_EPISODES = 22
GRID_BLOCK_MINUTES = 30
BLOCK_DURATION_MS = GRID_BLOCK_MINUTES * 60 * 1000  # 1_800_000
EXPECTED_BLOCKS = 48  # 24h / 30min


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def asset_library() -> StaticAssetLibrary:
    return StaticAssetLibrary(CATALOG_PATH)


@pytest.fixture(scope="module")
def transmission_log(asset_library):
    """Run the full pipeline once and cache for all tests in this module."""
    catalog = JsonFileProgramCatalog(PROGRAMS_DIR)
    catalog.load_all()

    config = ScheduleManagerConfig(
        grid_minutes=GRID_BLOCK_MINUTES,
        program_catalog=catalog,
        sequence_store=InMemorySequenceStore(),
        resolved_store=InMemoryResolvedStore(),
        filler_path=FILLER_URI,
        filler_duration_seconds=FILLER_DURATION_MS / 1000.0,
        programming_day_start_hour=6,
    )

    directive = PlanningDirective(
        channel_id="cheers-24-7",
        grid_block_minutes=GRID_BLOCK_MINUTES,
        programming_day_start_hour=6,
        zones=[
            ZoneDirective(
                start_time=time(6, 0),
                end_time=time(6, 0),   # same = full 24h wrap
                programs=[ProgramRef(ProgramRefType.PROGRAM, "cheers")],
                label="Cheers 24/7",
            ),
        ],
    )

    run_req = PlanningRunRequest(directive, BROADCAST_DATE, RESOLUTION_TIME)
    return run_planning_pipeline(run_req, config, asset_library, lock_time=LOCK_TIME)


# =============================================================================
# TestStructure
# =============================================================================


class TestStructure:
    """48 blocks, contiguous, 30-min each, full 24h span, locked."""

    def test_48_blocks(self, transmission_log):
        assert len(transmission_log.entries) == EXPECTED_BLOCKS

    def test_contiguous_blocks(self, transmission_log):
        entries = transmission_log.entries
        for i in range(len(entries) - 1):
            assert entries[i].end_utc_ms == entries[i + 1].start_utc_ms, (
                f"Gap between block {i} and {i+1}: "
                f"{entries[i].end_utc_ms} != {entries[i+1].start_utc_ms}"
            )

    def test_each_block_30_minutes(self, transmission_log):
        for entry in transmission_log.entries:
            duration_ms = entry.end_utc_ms - entry.start_utc_ms
            assert duration_ms == BLOCK_DURATION_MS, (
                f"Block {entry.block_index} duration {duration_ms}ms != {BLOCK_DURATION_MS}ms"
            )

    def test_full_24h_span(self, transmission_log):
        entries = transmission_log.entries
        total_ms = entries[-1].end_utc_ms - entries[0].start_utc_ms
        assert total_ms == 24 * 60 * 60 * 1000  # 86_400_000

    def test_locked(self, transmission_log):
        assert transmission_log.is_locked is True
        assert "locked_at" in transmission_log.metadata


# =============================================================================
# TestAssetResolution
# =============================================================================


class TestAssetResolution:
    """Every episode segment URI exists in catalog; filler uses catalog filler."""

    def test_episode_uris_in_catalog(self, transmission_log, asset_library):
        for entry in transmission_log.entries:
            for seg in entry.segments:
                if seg["segment_type"] == "episode":
                    uri = seg["asset_uri"]
                    dur = asset_library.get_duration_ms(uri)
                    assert dur > 0, f"URI not in catalog: {uri}"

    def test_filler_uris_in_catalog(self, transmission_log, asset_library):
        filler_uris = set()
        for entry in transmission_log.entries:
            for seg in entry.segments:
                if seg["segment_type"] == "filler":
                    filler_uris.add(seg["asset_uri"])
        for uri in filler_uris:
            dur = asset_library.get_duration_ms(uri)
            assert dur > 0, f"Filler URI not in catalog: {uri}"


# =============================================================================
# TestEpisodeSequencing
# =============================================================================


class TestEpisodeSequencing:
    """Episodes advance s01e01→s01e22 then wrap (22 eps across 48 slots)."""

    def _extract_episode_ids(self, transmission_log):
        """Get the first episode segment URI per block to identify episodes."""
        episode_uris = []
        for entry in transmission_log.entries:
            for seg in entry.segments:
                if seg["segment_type"] == "episode":
                    episode_uris.append(seg["asset_uri"])
                    break
        return episode_uris

    def test_sequential_advancement(self, transmission_log):
        uris = self._extract_episode_ids(transmission_log)
        assert len(uris) == EXPECTED_BLOCKS

        # All blocks for the same episode should have the same URI
        # Episodes should change sequentially
        unique_uris_in_order = []
        for uri in uris:
            if not unique_uris_in_order or unique_uris_in_order[-1] != uri:
                unique_uris_in_order.append(uri)
        # Should see 48 unique slots, each with a different episode (cycling through 22)
        assert len(unique_uris_in_order) == EXPECTED_BLOCKS

    def test_wraps_after_22_episodes(self, transmission_log):
        uris = self._extract_episode_ids(transmission_log)
        # Episode at index 0 should reappear at index 22 (wrap)
        assert uris[0] == uris[NUM_EPISODES], (
            f"Expected wrap: slot 0 URI={uris[0]} != slot {NUM_EPISODES} URI={uris[NUM_EPISODES]}"
        )

    def test_first_episode_is_s01e01(self, transmission_log):
        uris = self._extract_episode_ids(transmission_log)
        assert "S01E01" in uris[0], f"First episode URI doesn't contain S01E01: {uris[0]}"


# =============================================================================
# TestChapterSegmentation
# =============================================================================


class TestChapterSegmentation:
    """Episodes with chapter markers produce multiple content segments with interleaved breaks."""

    def test_chaptered_episodes_have_multiple_segments(self, transmission_log, asset_library):
        """Episodes with chapter markers produce chapter-count-based segments."""
        chaptered_count = 0
        for entry in transmission_log.entries:
            episode_segs = [s for s in entry.segments if s["segment_type"] == "episode"]
            if not episode_segs:
                continue
            uri = episode_segs[0]["asset_uri"]
            markers = asset_library.get_markers(uri)
            chapter_markers = [m for m in markers if m.kind == "chapter"]
            if chapter_markers:
                chaptered_count += 1
                # Chapter markers define segment boundaries; with N unique boundaries
                # we expect multiple content segments
                assert len(episode_segs) > 1, (
                    f"Chaptered episode has only 1 segment: {uri}"
                )
        # Most episodes have chapters (20 of 22 have markers, cycling across 48 blocks)
        assert chaptered_count > 0, "No blocks with chapter-based segmentation found"

    def test_chaptered_blocks_have_breaks_between_segments(self, transmission_log):
        """Blocks with multiple episode segments should have break/filler/pad segments."""
        for entry in transmission_log.entries:
            episode_segs = [s for s in entry.segments if s["segment_type"] == "episode"]
            if len(episode_segs) > 1:
                non_episode = [s for s in entry.segments if s["segment_type"] != "episode"]
                assert len(non_episode) > 0, (
                    f"Block {entry.block_index}: multiple episode segments but no breaks/pad"
                )


# =============================================================================
# TestDurationInvariants
# =============================================================================


class TestDurationInvariants:
    """Segment totals == block duration; episode content < block; realistic filler gap."""

    def test_segment_durations_sum_to_block(self, transmission_log):
        for entry in transmission_log.entries:
            total_seg_ms = sum(s["segment_duration_ms"] for s in entry.segments)
            block_ms = entry.end_utc_ms - entry.start_utc_ms
            assert total_seg_ms == block_ms, (
                f"Block {entry.block_index}: segment sum {total_seg_ms}ms != "
                f"block duration {block_ms}ms (delta={total_seg_ms - block_ms}ms)"
            )

    def test_episode_content_less_than_block(self, transmission_log):
        for entry in transmission_log.entries:
            episode_ms = sum(
                s["segment_duration_ms"] for s in entry.segments
                if s["segment_type"] == "episode"
            )
            block_ms = entry.end_utc_ms - entry.start_utc_ms
            assert episode_ms < block_ms, (
                f"Block {entry.block_index}: episode content {episode_ms}ms >= block {block_ms}ms"
            )

    def test_filler_gap_realistic(self, transmission_log):
        """Episode content ~22-25 min in a 30-min block → 5-8 min gap."""
        for entry in transmission_log.entries:
            episode_ms = sum(
                s["segment_duration_ms"] for s in entry.segments
                if s["segment_type"] == "episode"
            )
            gap_ms = BLOCK_DURATION_MS - episode_ms
            gap_minutes = gap_ms / 60_000
            # Episodes are ~24-25 min, so gap should be ~5-8 min
            assert 3.0 <= gap_minutes <= 10.0, (
                f"Block {entry.block_index}: gap {gap_minutes:.1f} min outside 3-10 min range"
            )


# =============================================================================
# TestSegmentOrdering
# =============================================================================


class TestSegmentOrdering:
    """Sequential indices, valid segment types, non-negative offsets."""

    def test_sequential_segment_indices(self, transmission_log):
        for entry in transmission_log.entries:
            indices = [s["segment_index"] for s in entry.segments]
            assert indices == list(range(len(indices))), (
                f"Block {entry.block_index}: non-sequential indices {indices}"
            )

    def test_valid_segment_types(self, transmission_log):
        valid_types = {"episode", "filler", "promo", "ad", "pad"}
        for entry in transmission_log.entries:
            for seg in entry.segments:
                assert seg["segment_type"] in valid_types, (
                    f"Block {entry.block_index}: invalid segment type '{seg['segment_type']}'"
                )

    def test_non_negative_offsets(self, transmission_log):
        for entry in transmission_log.entries:
            for seg in entry.segments:
                if "asset_start_offset_ms" in seg:
                    assert seg["asset_start_offset_ms"] >= 0, (
                        f"Block {entry.block_index}: negative offset "
                        f"{seg['asset_start_offset_ms']}"
                    )
