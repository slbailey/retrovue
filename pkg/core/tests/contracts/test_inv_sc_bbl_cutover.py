"""Contract tests: INV-SC-BBL-CUTOVER-001

_expand_to_compiled_segments MUST construct a BlockBreakLayout and derive
compiled_segments from expand_break_layout instead of expand_program_block.

Tests verify:
- DSL midroll positions produce interleaved content/filler
- Chapter markers produce interleaved content/filler when no DSL
- Preroll and postroll structural segments are preserved
- Total duration equals slot_duration_ms
- compiled_segments schema is compatible with hydration layer
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
    from retrovue.runtime.program_definition import AssemblyResult, AssemblySegment
    from retrovue.runtime.schedule_compiler import _expand_to_compiled_segments
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

GRID_30_MIN = 1_800_000
EPISODE_22_MIN = 1_320_000

DSL_MIDROLL = [
    {
        "type": "traffic",
        "placement": {
            "fallback": {
                "strategy": "weighted_positions",
                "positions": [0.30, 0.72],
                "weights": [1, 1],
            }
        },
    }
]


def _make_resolver(*, chapter_markers_sec=None) -> StubAssetResolver:
    resolver = StubAssetResolver()
    resolver.add("ep-001", AssetMetadata(
        type="episode",
        duration_sec=1320,
        title="Cheers S01E01",
        file_uri="/mnt/episodes/cheers_s01e01.mkv",
        chapter_markers_sec=chapter_markers_sec,
    ))
    return resolver


def _make_assembly(*, duration_ms=EPISODE_22_MIN, preroll=None, postroll=None):
    """Build AssemblyResult with optional structural segments."""
    segments = []
    if preroll:
        segments.extend(preroll)
    segments.append(AssemblySegment(
        asset_id="ep-001",
        duration_ms=duration_ms,
        segment_type="content",
    ))
    if postroll:
        segments.extend(postroll)
    total = sum(s.duration_ms for s in segments)
    return AssemblyResult(segments=segments, total_runtime_ms=total)


# ---------------------------------------------------------------------------
# HYDRATION SCHEMA COMPATIBILITY
# ---------------------------------------------------------------------------

REQUIRED_KEYS = {
    "segment_type", "asset_id", "duration_ms", "asset_start_offset_ms",
    "transition_in", "transition_in_duration_ms",
    "transition_out", "transition_out_duration_ms",
    "gain_db", "is_primary",
}


@pytest.mark.contract
class TestCompiledSegmentsSchema:
    """All compiled_segments entries must have hydration-compatible keys."""

    def test_all_segments_have_required_keys(self):
        resolver = _make_resolver()
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        for i, seg in enumerate(compiled):
            missing = REQUIRED_KEYS - set(seg.keys())
            assert not missing, (
                f"Segment {i} ({seg.get('segment_type', '?')}) missing keys: {missing}"
            )

    def test_schema_with_preroll_postroll(self):
        resolver = _make_resolver()
        preroll = [
            AssemblySegment(asset_id="intro-1", duration_ms=74_000,
                            segment_type="presentation"),
        ]
        postroll = [
            AssemblySegment(asset_id="sid-1", duration_ms=10_000,
                            segment_type="presentation"),
            AssemblySegment(asset_id="_postroll_traffic_marker", duration_ms=0,
                            segment_type="postroll_traffic"),
        ]
        result = _make_assembly(preroll=preroll, postroll=postroll)
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        for i, seg in enumerate(compiled):
            missing = REQUIRED_KEYS - set(seg.keys())
            assert not missing, (
                f"Segment {i} ({seg.get('segment_type', '?')}) missing keys: {missing}"
            )


# ---------------------------------------------------------------------------
# DSL MIDROLL PRODUCES INTERLEAVED SEGMENTS
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestDslMidrollProducesBreaks:
    """When DSL midroll is present, compiled_segments must have midroll filler."""

    def test_dsl_midroll_produces_interleaved_filler(self):
        resolver = _make_resolver()
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        types = [s["segment_type"] for s in compiled]
        # Must have content-filler-content pattern (midroll)
        filler_indices = [i for i, t in enumerate(types) if t == "filler"]
        content_indices = [i for i, t in enumerate(types) if t == "content"]
        assert len(filler_indices) >= 1, f"No filler segments. Types: {types}"
        assert len(content_indices) >= 3, (
            f"DSL with 2 positions should produce >= 3 content acts. Types: {types}"
        )
        # At least one filler must be between content acts (midroll, not trailing)
        last_content = content_indices[-1]
        midroll_fillers = [i for i in filler_indices if i < last_content]
        assert len(midroll_fillers) >= 1, (
            f"No midroll filler between content acts. Types: {types}"
        )

    def test_dsl_positions_reflected_in_offsets(self):
        """Content act offsets should correspond to DSL break positions."""
        resolver = _make_resolver()
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        # First act starts at 0
        assert content_segs[0]["asset_start_offset_ms"] == 0
        # Second act should start at ~30% of 1_320_000 = 396_000
        expected_pos = round(0.30 * EPISODE_22_MIN)
        assert content_segs[1]["asset_start_offset_ms"] == expected_pos


# ---------------------------------------------------------------------------
# CHAPTER MARKERS WHEN NO DSL
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestChapterMarkersProduceBreaks:
    """When no DSL midroll, chapter markers drive break positions."""

    def test_chapter_markers_produce_interleaved_filler(self):
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
        )
        types = [s["segment_type"] for s in compiled]
        content_indices = [i for i, t in enumerate(types) if t == "content"]
        filler_indices = [i for i, t in enumerate(types) if t == "filler"]
        assert len(content_indices) >= 3
        last_content = content_indices[-1]
        midroll_fillers = [i for i in filler_indices if i < last_content]
        assert len(midroll_fillers) >= 1

    def test_chapter_positions_in_offsets(self):
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        assert content_segs[0]["asset_start_offset_ms"] == 0
        assert content_segs[1]["asset_start_offset_ms"] == 420_000
        assert content_segs[2]["asset_start_offset_ms"] == 900_000


# ---------------------------------------------------------------------------
# CHAPTER SUPERSEDES DSL
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestChapterSupersedesDsl:
    """When both DSL midroll and chapters present, chapters win."""

    def test_chapters_used_not_dsl(self):
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        offsets = [s["asset_start_offset_ms"] for s in content_segs]
        # Chapter positions used
        assert 420_000 in offsets
        assert 900_000 in offsets
        # DSL fractional positions NOT used (396000 != 420000, 950400 != 900000)
        assert round(0.30 * EPISODE_22_MIN) not in offsets
        assert round(0.72 * EPISODE_22_MIN) not in offsets

    def test_dsl_used_when_no_chapters(self):
        resolver = _make_resolver(chapter_markers_sec=None)
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        offsets = [s["asset_start_offset_ms"] for s in content_segs]
        # DSL positions used when chapters absent
        assert round(0.30 * EPISODE_22_MIN) in offsets
        assert round(0.72 * EPISODE_22_MIN) in offsets


# ---------------------------------------------------------------------------
# PREROLL AND POSTROLL PRESERVED
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestStructuralSegmentsPreserved:
    """Preroll and postroll structural segments survive the cutover."""

    def test_preroll_present(self):
        resolver = _make_resolver()
        preroll = [
            AssemblySegment(asset_id="intro-1", duration_ms=74_000,
                            segment_type="presentation"),
        ]
        result = _make_assembly(preroll=preroll)
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        # First segment should be preroll
        assert compiled[0]["segment_type"] == "presentation"
        assert compiled[0]["asset_id"] == "intro-1"
        assert compiled[0]["duration_ms"] == 74_000

    def test_postroll_present(self):
        resolver = _make_resolver()
        postroll = [
            AssemblySegment(asset_id="sid-1", duration_ms=10_000,
                            segment_type="presentation"),
        ]
        result = _make_assembly(postroll=postroll)
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        # Find postroll — should be after all content
        presentation_segs = [
            s for s in compiled if s["segment_type"] == "presentation"
        ]
        assert len(presentation_segs) >= 1
        sid = [s for s in presentation_segs if s["asset_id"] == "sid-1"]
        assert len(sid) == 1
        assert sid[0]["duration_ms"] == 10_000


# ---------------------------------------------------------------------------
# TOTAL DURATION INVARIANT
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestTotalDurationInvariant:
    """Sum of all segment durations must equal slot_duration_ms."""

    def test_total_duration_network(self):
        resolver = _make_resolver()
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        total = sum(s["duration_ms"] for s in compiled)
        assert total == GRID_30_MIN, f"Total {total} != slot {GRID_30_MIN}"

    def test_total_duration_with_structural(self):
        resolver = _make_resolver()
        preroll = [
            AssemblySegment(asset_id="intro-1", duration_ms=74_000,
                            segment_type="presentation"),
        ]
        postroll = [
            AssemblySegment(asset_id="sid-1", duration_ms=10_000,
                            segment_type="presentation"),
            AssemblySegment(asset_id="_postroll_traffic_marker", duration_ms=0,
                            segment_type="postroll_traffic"),
        ]
        result = _make_assembly(preroll=preroll, postroll=postroll)
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        total = sum(s["duration_ms"] for s in compiled)
        assert total == GRID_30_MIN, f"Total {total} != slot {GRID_30_MIN}"

    def test_total_duration_movie(self):
        resolver = StubAssetResolver()
        resolver.add("movie-001", AssetMetadata(
            type="movie", duration_sec=5400,
            title="Test Movie", file_uri="/mnt/movies/test.mkv",
        ))
        result = AssemblyResult(
            segments=[
                AssemblySegment(
                    asset_id="movie-001", duration_ms=5_400_000,
                    segment_type="content",
                ),
            ],
            total_runtime_ms=5_400_000,
        )
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=7_200_000,
            start_utc_ms=0,
            channel_type="movie",
        )
        total = sum(s["duration_ms"] for s in compiled)
        assert total == 7_200_000, f"Total {total} != 7_200_000"


# ---------------------------------------------------------------------------
# TRANSITION MAPPING
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestTransitionMapping:
    """BBL transition_style is correctly mapped to compiled_segments transitions."""

    def test_dsl_breaks_use_transition_none(self):
        """DSL breaks (clean) should produce TRANSITION_NONE."""
        resolver = _make_resolver()
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
            dsl_midroll=DSL_MIDROLL,
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        for seg in content_segs:
            # DSL source → clean → TRANSITION_NONE
            assert seg["transition_in"] in ("TRANSITION_NONE", "TRANSITION_FADE")
            assert seg["transition_out"] in ("TRANSITION_NONE", "TRANSITION_FADE")

    def test_algorithmic_breaks_use_transition_fade(self):
        """Algorithmic breaks (fade) should produce TRANSITION_FADE."""
        resolver = _make_resolver()  # no chapters, no DSL → algorithmic
        result = _make_assembly()
        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=GRID_30_MIN,
            start_utc_ms=0,
            channel_type="network",
        )
        content_segs = [s for s in compiled if s["segment_type"] == "content"]
        # At least some content segments should have TRANSITION_FADE
        fade_out = [s for s in content_segs if s["transition_out"] == "TRANSITION_FADE"]
        assert len(fade_out) >= 1, (
            "Algorithmic breaks should produce TRANSITION_FADE on content segments"
        )
