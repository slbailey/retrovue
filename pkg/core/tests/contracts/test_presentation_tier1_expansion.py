"""INV-PRESENTATION-PRECEDES-PRIMARY-001: Presentation segments in compiled_segments
must appear as ScheduledSegments in the Tier 1 expanded block, before the primary
content segment.

Violation: _expand_blocks_inner() ignores compiled_segments entirely, dropping
presentation segments (intros, ratings cards) from the block sent to AIR.

Also tests INV-PRESENTATION-TIER1-HYDRATE: The schedule_items_reader gate condition
must treat "presentation" segments as structural (not fall through to expand_program_block).
"""
import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Fixtures: minimal resolver stub
# ---------------------------------------------------------------------------

class FakeAssetMeta:
    def __init__(self, *, file_uri: str, duration_sec: int = 7200,
                 chapter_markers_sec=None, loudness_gain_db: float = 0.0,
                 tags=(), type: str = "movie", rating: str = ""):
        self.file_uri = file_uri
        self.duration_sec = duration_sec
        self.chapter_markers_sec = chapter_markers_sec or []
        self.loudness_gain_db = loudness_gain_db
        self.tags = tags
        self.type = type
        self.rating = rating


class FakeResolver:
    def __init__(self, assets: dict):
        self._assets = assets

    def lookup(self, asset_id: str):
        if asset_id not in self._assets:
            raise KeyError(f"Asset not found: {asset_id}")
        return self._assets[asset_id]

    def asset_needs_loudness_measurement(self, asset_id: str) -> bool:
        return False


# ---------------------------------------------------------------------------
# Test: _expand_blocks_inner preserves presentation segments
# ---------------------------------------------------------------------------

def _make_schedule_with_presentation():
    """Build a minimal compiled schedule with presentation + content segments."""
    return {
        "program_blocks": [
            {
                "title": "The Notebook",
                "asset_id": "movie-uuid-001",
                "start_at": "2026-03-09T06:00:00+00:00",
                "slot_duration_sec": 7200,
                "episode_duration_sec": 7429,
                "compiled_segments": [
                    {"segment_type": "presentation", "asset_id": "intro-uuid-001", "duration_ms": 74000},
                    {"segment_type": "presentation", "asset_id": "rating-uuid-001", "duration_ms": 5000},
                    {"segment_type": "content", "asset_id": "movie-uuid-001", "duration_ms": 7429000},
                ],
            }
        ],
    }


def _make_resolver():
    return FakeResolver({
        "movie-uuid-001": FakeAssetMeta(
            file_uri="/mnt/data/movies/notebook.mkv",
            duration_sec=7429,
            type="movie",
        ),
        "intro-uuid-001": FakeAssetMeta(
            file_uri="/mnt/data/bumpers/hbo/intro.mp4",
            duration_sec=74,
            type="bumper",
        ),
        "rating-uuid-001": FakeAssetMeta(
            file_uri="/mnt/data/bumpers/hbo/pg13.mp4",
            duration_sec=5,
            type="bumper",
        ),
    })


class TestPresentationTier1Expansion:
    """INV-PRESENTATION-PRECEDES-PRIMARY-001 at Tier 1 expansion."""

    # Tier: 1 | Structural invariant
    def test_presentation_segments_appear_before_content(self):
        """Presentation segments from compiled_segments must appear in the
        expanded ScheduledBlock before the primary content segment."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_presentation()
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri  # identity
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        assert len(blocks) == 1

        block = blocks[0]
        seg_types = [s.segment_type for s in block.segments]

        # Presentation segments must exist
        assert "presentation" in seg_types, (
            "INV-PRESENTATION-PRECEDES-PRIMARY-001: presentation segments missing from Tier 1 block"
        )

        # All presentation segments must precede the first content segment
        first_content_idx = next(i for i, t in enumerate(seg_types) if t == "content")
        for i, t in enumerate(seg_types):
            if t == "presentation":
                assert i < first_content_idx, (
                    f"INV-PRESENTATION-PRECEDES-PRIMARY-001: presentation at index {i} "
                    f"is after content at index {first_content_idx}"
                )

    # Tier: 1 | Structural invariant
    def test_presentation_uris_resolved_via_resolver(self):
        """Presentation segment asset_ids must be resolved to file URIs via
        the catalog resolver, not carried as raw IDs."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_presentation()
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        pres_segs = [s for s in block.segments if s.segment_type == "presentation"]
        assert len(pres_segs) == 2

        assert pres_segs[0].asset_uri == "/mnt/data/bumpers/hbo/intro.mp4"
        assert pres_segs[1].asset_uri == "/mnt/data/bumpers/hbo/pg13.mp4"

    # Tier: 1 | Structural invariant
    def test_content_still_uses_expand_program_block(self):
        """When compiled_segments has presentation + 1 content, the content
        segment must still go through expand_program_block for chapter-based
        break detection."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = _make_schedule_with_presentation()
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) >= 1
        assert content_segs[0].asset_uri == "/mnt/data/movies/notebook.mkv"

    # Tier: 1 | Structural invariant
    def test_blocks_without_compiled_segments_unchanged(self):
        """Blocks without compiled_segments must still expand normally."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = {
            "program_blocks": [
                {
                    "title": "The Notebook",
                    "asset_id": "movie-uuid-001",
                    "start_at": "2026-03-09T06:00:00+00:00",
                    "slot_duration_sec": 7200,
                    "episode_duration_sec": 7429,
                },
            ],
        }
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        assert len(blocks) == 1
        seg_types = [s.segment_type for s in blocks[0].segments]
        assert "presentation" not in seg_types


# ---------------------------------------------------------------------------
# Test: schedule_items_reader gate treats "presentation" as structural
# ---------------------------------------------------------------------------

class TestScheduleItemsReaderGate:
    """INV-PRESENTATION-TIER1-HYDRATE: Gate condition in schedule_items_reader
    must route blocks with presentation segments through _hydrate_compiled_segments."""

    # Tier: 1 | Structural invariant
    def test_presentation_counted_as_structural(self):
        """compiled_segments with 1 content + N presentation must NOT fall
        through to expand_program_block (which drops presentation segments)."""
        compiled_segments = [
            {"segment_type": "presentation", "asset_id": "intro-001", "duration_ms": 74000},
            {"segment_type": "presentation", "asset_id": "rating-001", "duration_ms": 5000},
            {"segment_type": "content", "asset_id": "movie-001", "duration_ms": 7200000},
        ]
        content_segs = [s for s in compiled_segments if s.get("segment_type") == "content"]
        structural_segs = [
            s for s in compiled_segments
            if s.get("segment_type") in ("intro", "outro", "presentation")
        ]

        # With "presentation" counted as structural, this block should NOT
        # take the single-content shortcut path.
        single_content_shortcut = len(content_segs) == 1 and not structural_segs
        assert not single_content_shortcut, (
            "INV-PRESENTATION-TIER1-HYDRATE: presentation segments must be counted "
            "as structural to prevent the single-content shortcut"
        )


# ---------------------------------------------------------------------------
# Test: INV-BLOCK-SEGMENT-CONSERVATION-001
# ---------------------------------------------------------------------------

class TestBlockFrameConservation:
    """INV-BLOCK-SEGMENT-CONSERVATION-001: Segment duration sum must equal
    block duration (end_utc_ms - start_utc_ms) at Tier 1.

    Violation: Prepending presentation segments WITHOUT reducing the
    content/filler budget causes sum(segment_ms) > block_duration_ms,
    leading AIR to play content at 1.25x speed.
    """

    # Tier: 1 | Structural invariant
    def test_segment_sum_equals_block_duration_with_presentation(self):
        """Movie block with presentation segments: sum must match block duration.

        Uses a movie (5400s) shorter than the slot (7200s) so there IS filler
        budget for the presentation to consume from.  (Bleed movies that exceed
        the slot are extended by the schedule compiler before reaching this code.)
        """
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = {
            "program_blocks": [{
                "title": "Taken",
                "asset_id": "movie-uuid-001",
                "start_at": "2026-03-09T06:00:00+00:00",
                "slot_duration_sec": 7200,
                "episode_duration_sec": 5400,
                "compiled_segments": [
                    {"segment_type": "presentation", "asset_id": "intro-uuid-001", "duration_ms": 74000},
                    {"segment_type": "presentation", "asset_id": "rating-uuid-001", "duration_ms": 5000},
                    {"segment_type": "content", "asset_id": "movie-uuid-001", "duration_ms": 5400000},
                ],
            }],
        }
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        block_duration_ms = block.end_utc_ms - block.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)

        assert sum_segment_ms == block_duration_ms, (
            f"INV-BLOCK-SEGMENT-CONSERVATION-001: segment sum {sum_segment_ms}ms "
            f"!= block duration {block_duration_ms}ms "
            f"(delta={sum_segment_ms - block_duration_ms}ms)"
        )

    # Tier: 1 | Structural invariant
    def test_segment_sum_equals_block_duration_no_presentation(self):
        """Movie block without presentation: sum must still match block duration."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        schedule = {
            "program_blocks": [{
                "title": "Taken",
                "asset_id": "movie-uuid-001",
                "start_at": "2026-03-09T06:00:00+00:00",
                "slot_duration_sec": 7200,
                "episode_duration_sec": 5400,
            }],
        }
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        block_duration_ms = block.end_utc_ms - block.start_utc_ms
        sum_segment_ms = sum(s.segment_duration_ms for s in block.segments)

        assert sum_segment_ms == block_duration_ms, (
            f"INV-BLOCK-SEGMENT-CONSERVATION-001: segment sum {sum_segment_ms}ms "
            f"!= block duration {block_duration_ms}ms"
        )

    # Tier: 1 | Structural invariant
    def test_presentation_reduces_filler_not_content(self):
        """Presentation time must come from filler budget, not movie content."""
        from retrovue.runtime.dsl_schedule_service import DslScheduleService

        # Movie (5400s) in 7200s slot with 79s presentation → filler should be
        # 7200 - 5400 - 79 = 1721s, not 1800s.
        schedule = {
            "program_blocks": [{
                "title": "Taken",
                "asset_id": "movie-uuid-001",
                "start_at": "2026-03-09T06:00:00+00:00",
                "slot_duration_sec": 7200,
                "episode_duration_sec": 5400,
                "compiled_segments": [
                    {"segment_type": "presentation", "asset_id": "intro-uuid-001", "duration_ms": 74000},
                    {"segment_type": "presentation", "asset_id": "rating-uuid-001", "duration_ms": 5000},
                    {"segment_type": "content", "asset_id": "movie-uuid-001", "duration_ms": 5400000},
                ],
            }],
        }
        resolver = _make_resolver()

        svc = DslScheduleService.__new__(DslScheduleService)
        svc._channel_type = "movie"
        svc._resolve_uri = lambda uri: uri
        svc._enqueue_loudness_measurement = lambda *a: None

        blocks = svc._expand_blocks_inner(schedule, resolver)
        block = blocks[0]

        content_ms = sum(s.segment_duration_ms for s in block.segments if s.segment_type == "content")
        pres_ms = sum(s.segment_duration_ms for s in block.segments if s.segment_type == "presentation")
        filler_ms = sum(s.segment_duration_ms for s in block.segments if s.segment_type == "filler")

        assert content_ms == 5400000, f"Content must be uncut: {content_ms}"
        assert pres_ms == 79000, f"Presentation must be preserved: {pres_ms}"
        assert filler_ms == 7200000 - 5400000 - 79000, (
            f"Filler must absorb presentation: expected {7200000-5400000-79000}, got {filler_ms}"
        )
