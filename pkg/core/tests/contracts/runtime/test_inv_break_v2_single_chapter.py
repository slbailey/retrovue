"""
Contract test: INV-BREAK-V2-SINGLE-CHAPTER-001

V2 single-content compiled_segments blocks MUST produce mid-content
breaks when the asset has chapter markers in the catalog.

Rules covered:
- BREAK-025: Single-content + chapters → multiple content acts with filler
- BREAK-026: Multi-content → _hydrate path, no chapter re-splitting
- BREAK-027: Single-content + no chapters → algorithmic breaks
- BREAK-028: Single-content + movie type → no mid-content breaks
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fake CatalogAssetResolver
# ---------------------------------------------------------------------------

@dataclass
class FakeAssetMeta:
    file_uri: str = "/media/shows/ep01.mp4"
    title: str = "Test Episode"
    duration_sec: int = 1440
    chapter_markers_sec: tuple[float, ...] | None = None
    loudness_gain_db: float = 0.0


class FakeCatalogResolver:
    """Minimal resolver returning controlled AssetMetadata."""

    def __init__(self, meta_map: dict[str, FakeAssetMeta]):
        self._map = meta_map

    def lookup(self, asset_id: str) -> FakeAssetMeta:
        return self._map.get(asset_id, FakeAssetMeta())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOW_UTC_MS = int(datetime(2026, 3, 8, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
SLOT_DURATION_MS = 1_800_000  # 30 minutes


def _build_fake_item(
    *,
    compiled_segments: list[dict],
    asset_id: str = "ep-001",
    content_type: str = "episode",
    duration_sec: int = 1800,
    start_time: datetime | None = None,
):
    """Build a fake ScheduleItem-like object for testing."""
    item = MagicMock()
    item.metadata_ = {
        "asset_id_raw": asset_id,
        "compiled_segments": compiled_segments,
    }
    item.asset_id = asset_id
    item.content_type = content_type
    item.duration_sec = duration_sec
    item.start_time = start_time or datetime(2026, 3, 8, 21, 0, tzinfo=timezone.utc)
    item.slot_index = 0
    item.window_uuid = None
    return item


def _run_block_expansion(
    item,
    resolver: FakeCatalogResolver,
) -> dict:
    """Run the block expansion routing from load_segmented_blocks_from_active_revision.

    Extracts the exact routing logic from schedule_items_reader.py to test
    against the actual production code path.
    """
    from retrovue.runtime.schedule_items_reader import (
        _hydrate_compiled_segments,
        _serialize_scheduled_block,
    )

    meta = item.metadata_ or {}
    raw_asset_id = meta.get("asset_id_raw", "")
    start_utc_ms = int(item.start_time.timestamp() * 1000)
    slot_duration_ms = int(item.duration_sec) * 1000
    compiled_segments = meta.get("compiled_segments")

    if compiled_segments:
        expanded = _hydrate_compiled_segments(
            compiled_segments=compiled_segments,
            asset_id=raw_asset_id,
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            resolver=resolver,
        )
    else:
        raise ValueError("Test requires compiled_segments")

    return _serialize_scheduled_block(expanded)


def _run_block_expansion_with_routing(
    item,
    resolver: FakeCatalogResolver,
) -> dict:
    """Run the FIXED routing logic that honors INV-BREAK-V2-SINGLE-CHAPTER-001.

    This mirrors what the production code MUST do after the fix.
    """
    from retrovue.runtime.playout_log_expander import expand_program_block
    from retrovue.runtime.schedule_items_reader import (
        _hydrate_compiled_segments,
        _serialize_scheduled_block,
    )

    meta = item.metadata_ or {}
    raw_asset_id = meta.get("asset_id_raw", "")
    start_utc_ms = int(item.start_time.timestamp() * 1000)
    slot_duration_ms = int(item.duration_sec) * 1000
    compiled_segments = meta.get("compiled_segments")

    content_segs = [s for s in compiled_segments if s.get("segment_type") == "content"]
    structural_segs = [
        s for s in compiled_segments if s.get("segment_type") in ("intro", "outro")
    ]

    if len(content_segs) == 1 and not structural_segs:
        # INV-BREAK-V2-SINGLE-CHAPTER-001: route through expand_program_block
        cs = content_segs[0]
        seg_asset_id = cs.get("asset_id", raw_asset_id)
        asset_meta = resolver.lookup(seg_asset_id)

        chapter_ms = None
        if asset_meta.chapter_markers_sec:
            chapter_ms = tuple(
                int(c * 1000) for c in asset_meta.chapter_markers_sec if c > 0
            )

        channel_type = "movie" if item.content_type == "movie" else "network"

        expanded = expand_program_block(
            asset_id=seg_asset_id,
            asset_uri=asset_meta.file_uri or "",
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            episode_duration_ms=int(cs["duration_ms"]),
            chapter_markers_ms=chapter_ms,
            channel_type=channel_type,
            gain_db=asset_meta.loudness_gain_db,
        )
    else:
        expanded = _hydrate_compiled_segments(
            compiled_segments=compiled_segments,
            asset_id=raw_asset_id,
            start_utc_ms=start_utc_ms,
            slot_duration_ms=slot_duration_ms,
            resolver=resolver,
        )

    return _serialize_scheduled_block(expanded)


# ---------------------------------------------------------------------------
# BREAK-025: Single-content + chapters → mid-content acts
# ---------------------------------------------------------------------------

class TestSingleContentWithChapters:
    """BREAK-025: V2 single-content block with chapter markers produces
    multiple content acts interleaved with filler."""

    def _make_fixtures(self):
        compiled = [
            {"segment_type": "content", "asset_id": "ep-001", "duration_ms": 1_440_000},
        ]
        resolver = FakeCatalogResolver({
            "ep-001": FakeAssetMeta(
                file_uri="/media/shows/ep01.mp4",
                duration_sec=1440,
                chapter_markers_sec=(360.0, 720.0, 1080.0),
            ),
        })
        item = _build_fake_item(compiled_segments=compiled)
        return item, resolver

    # Tier: 2 | Scheduling logic invariant
    def test_hydrate_alone_produces_monolithic_content(self):
        """_hydrate_compiled_segments alone (without routing) still produces
        a single content segment. This confirms the routing gate is needed."""
        item, resolver = self._make_fixtures()
        block_dict = _run_block_expansion(item, resolver)

        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]

        # _hydrate_compiled_segments: ONE content segment (no chapter awareness)
        assert len(content_segs) == 1, (
            "_hydrate_compiled_segments must produce 1 content segment (no chapter logic)"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_fixed_routing_produces_chapter_acts(self):
        """After fix: 3 chapter markers → 4 content acts with filler between."""
        item, resolver = self._make_fixtures()
        block_dict = _run_block_expansion_with_routing(item, resolver)

        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]
        filler_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] == "filler"
        ]

        assert len(content_segs) == 4, (
            f"Expected 4 content acts from 3 chapter markers, got {len(content_segs)}"
        )
        assert len(filler_segs) >= 3, (
            f"Expected ≥3 filler segments between acts, got {len(filler_segs)}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_fixed_routing_content_offsets(self):
        """Content segments have correct asset_start_offset_ms at chapter positions."""
        item, resolver = self._make_fixtures()
        block_dict = _run_block_expansion_with_routing(item, resolver)

        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]

        assert content_segs[0]["asset_start_offset_ms"] == 0
        assert content_segs[1]["asset_start_offset_ms"] == 360_000
        assert content_segs[2]["asset_start_offset_ms"] == 720_000
        assert content_segs[3]["asset_start_offset_ms"] == 1_080_000

    # Tier: 2 | Scheduling logic invariant
    def test_fixed_routing_same_asset_uri(self):
        """All content segments reference the same file."""
        item, resolver = self._make_fixtures()
        block_dict = _run_block_expansion_with_routing(item, resolver)

        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]

        for seg in content_segs:
            assert seg["asset_uri"] == "/media/shows/ep01.mp4"


# ---------------------------------------------------------------------------
# BREAK-026: Multi-content → hydrate path, no chapter re-splitting
# ---------------------------------------------------------------------------

class TestMultiContentBypassesChapterExpansion:
    """BREAK-026: Multi-content compiled_segments continues through
    _hydrate_compiled_segments, preserving segment structure."""

    # Tier: 2 | Scheduling logic invariant
    def test_multi_content_not_resplit(self):
        compiled = [
            {"segment_type": "content", "asset_id": "ep-001", "duration_ms": 700_000},
            {"segment_type": "content", "asset_id": "ep-002", "duration_ms": 700_000},
        ]
        resolver = FakeCatalogResolver({
            "ep-001": FakeAssetMeta(
                file_uri="/media/shows/ep01.mp4",
                chapter_markers_sec=(180.0, 360.0),
            ),
            "ep-002": FakeAssetMeta(
                file_uri="/media/shows/ep02.mp4",
                chapter_markers_sec=(180.0, 360.0),
            ),
        })
        item = _build_fake_item(
            compiled_segments=compiled,
            asset_id="ep-001",
        )

        block_dict = _run_block_expansion_with_routing(item, resolver)
        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] == "content"
        ]

        # Multi-content: exactly 2 content segments, not re-split by chapters
        assert len(content_segs) == 2


# ---------------------------------------------------------------------------
# BREAK-027: Single-content + no chapters → algorithmic breaks
# ---------------------------------------------------------------------------

class TestSingleContentNoChapters:
    """BREAK-027: Single-content without chapter markers still gets
    algorithmic break placement (not all post-content)."""

    # Tier: 2 | Scheduling logic invariant
    def test_no_chapters_still_produces_mid_content_breaks(self):
        compiled = [
            {"segment_type": "content", "asset_id": "ep-001", "duration_ms": 1_440_000},
        ]
        resolver = FakeCatalogResolver({
            "ep-001": FakeAssetMeta(
                file_uri="/media/shows/ep01.mp4",
                chapter_markers_sec=None,
            ),
        })
        item = _build_fake_item(compiled_segments=compiled)

        block_dict = _run_block_expansion_with_routing(item, resolver)
        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]

        # Without chapters, algorithmic breaks still split content
        assert len(content_segs) > 1, (
            "Expected algorithmic breaks to split content into multiple acts"
        )


# ---------------------------------------------------------------------------
# BREAK-028: Single-content + movie type → no mid-content breaks
# ---------------------------------------------------------------------------

class TestMovieTypeNoMidBreaks:
    """BREAK-028: Movie-type single-content block produces no
    mid-content breaks, even with chapter markers."""

    # Tier: 2 | Scheduling logic invariant
    def test_movie_type_single_content_no_mid_breaks(self):
        compiled = [
            {"segment_type": "content", "asset_id": "movie-001", "duration_ms": 5_400_000},
        ]
        resolver = FakeCatalogResolver({
            "movie-001": FakeAssetMeta(
                file_uri="/media/movies/movie.mp4",
                duration_sec=5400,
                chapter_markers_sec=(900.0, 1800.0, 2700.0, 3600.0),
            ),
        })
        item = _build_fake_item(
            compiled_segments=compiled,
            asset_id="movie-001",
            content_type="movie",
            duration_sec=7200,
        )

        block_dict = _run_block_expansion_with_routing(item, resolver)
        content_segs = [
            s for s in block_dict["segments"]
            if s["segment_type"] in ("content", "episode")
        ]

        # Movie: single uninterrupted content segment
        assert len(content_segs) == 1, (
            f"Movie type must have exactly 1 content segment, got {len(content_segs)}"
        )
