"""Contract tests: INV-MIDROLL-INTERLEAVE-001

Midroll filler segments produced by expand_program_block() for network channels
MUST remain interleaved between content acts in compiled_segments.

Separating all filler to trail all content destroys midroll commercial breaks.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata, StubAssetResolver
    from retrovue.runtime.program_assembly import assemble_schedule_block
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


def _make_resolver(*, chapter_markers_sec=None) -> StubAssetResolver:
    """Resolver with a single episode asset, optionally with chapter markers."""
    resolver = StubAssetResolver()
    resolver.add("ep-001", AssetMetadata(
        type="episode",
        duration_sec=1320,  # 22 minutes
        title="Cheers S01E01",
        file_uri="/mnt/episodes/cheers_s01e01.mkv",
        chapter_markers_sec=chapter_markers_sec,
    ))
    return resolver


def _make_assembly_result(*, duration_ms: int = 1_320_000) -> AssemblyResult:
    """Single content segment assembly result (standard sitcom)."""
    return AssemblyResult(
        segments=[
            AssemblySegment(
                asset_id="ep-001",
                duration_ms=duration_ms,
                segment_type="content",
            ),
        ],
        total_runtime_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# INV-MIDROLL-INTERLEAVE-001: midroll filler stays between content acts
# ---------------------------------------------------------------------------


class TestMidrollInterleave:
    """Compiled segments for network channels preserve midroll interleaving."""

    def test_chapter_markers_produce_interleaved_filler(self):
        """When chapter markers exist, filler appears between content acts,
        not trailing all content."""
        # Chapter markers at ~7min and ~15min into a 22-min episode
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly_result()

        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,  # 30 min slot
            start_utc_ms=0,
            channel_type="network",
        )

        types = [seg["segment_type"] for seg in compiled]

        # Must have at least: content, filler, content pattern (midroll between acts)
        assert len(types) >= 3, f"Expected interleaved segments, got: {types}"

        # Find first filler position and last content position
        first_filler_idx = next(
            (i for i, t in enumerate(types) if t == "filler"), None
        )
        content_indices = [i for i, t in enumerate(types) if t == "content"]
        last_content_idx = content_indices[-1] if content_indices else -1

        assert first_filler_idx is not None, "No filler segments found"

        # INV-MIDROLL-INTERLEAVE-001: at least one filler must appear
        # BEFORE the last content segment (i.e., midroll, not just postroll)
        assert first_filler_idx < last_content_idx, (
            f"All filler ({first_filler_idx}) trails all content "
            f"({last_content_idx}) — midroll interleaving destroyed. "
            f"Segment types: {types}"
        )

    def test_algorithmic_breaks_produce_interleaved_filler(self):
        """When no chapter markers exist, algorithmic breaks still produce
        interleaved content/filler in compiled_segments."""
        # No chapter markers — algorithmic breaks kick in
        resolver = _make_resolver(chapter_markers_sec=None)
        result = _make_assembly_result()

        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,  # 30 min slot
            start_utc_ms=0,
            channel_type="network",
        )

        types = [seg["segment_type"] for seg in compiled]

        # Algorithmic breaks should still produce interleaved segments
        first_filler_idx = next(
            (i for i, t in enumerate(types) if t == "filler"), None
        )
        content_indices = [i for i, t in enumerate(types) if t == "content"]
        last_content_idx = content_indices[-1] if content_indices else -1

        assert first_filler_idx is not None, "No filler segments found"
        assert first_filler_idx < last_content_idx, (
            f"All filler ({first_filler_idx}) trails all content "
            f"({last_content_idx}) — midroll interleaving destroyed. "
            f"Segment types: {types}"
        )

    def test_content_filler_alternation_pattern(self):
        """Compiled segments for network must follow content-filler-content
        alternation pattern, not content-content-...-filler-filler."""
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        result = _make_assembly_result()

        compiled = _expand_to_compiled_segments(
            result, resolver,
            slot_duration_ms=1_800_000,
            start_utc_ms=0,
            channel_type="network",
        )

        types = [seg["segment_type"] for seg in compiled]

        # With chapter markers, we expect pattern like:
        # [content, filler, content, filler, content, ...]
        # NOT: [content, content, content, filler, filler, ...]
        seen_filler = False
        content_after_filler = False
        for t in types:
            if t == "filler":
                seen_filler = True
            elif t == "content" and seen_filler:
                content_after_filler = True
                break

        assert content_after_filler, (
            f"No content appears after filler — midroll pattern broken. "
            f"Segment types: {types}"
        )

    def test_movie_channel_filler_trails_content(self):
        """Movie channels should have all filler after content (no midroll).
        This is the correct non-interleaved behavior."""
        resolver = _make_resolver(chapter_markers_sec=(420.0, 900.0))
        # Use longer duration for movie
        resolver.add("movie-001", AssetMetadata(
            type="movie",
            duration_sec=5400,  # 90 min
            title="Test Movie",
            file_uri="/mnt/movies/test.mkv",
            chapter_markers_sec=(1800.0, 3600.0),
        ))
        movie_result = AssemblyResult(
            segments=[
                AssemblySegment(
                    asset_id="movie-001",
                    duration_ms=5_400_000,
                    segment_type="content",
                ),
            ],
            total_runtime_ms=5_400_000,
        )

        compiled = _expand_to_compiled_segments(
            movie_result, resolver,
            slot_duration_ms=7_200_000,  # 2 hour slot
            start_utc_ms=0,
            channel_type="movie",
        )

        types = [seg["segment_type"] for seg in compiled]

        # Movie: single content + trailing filler (no midroll)
        content_indices = [i for i, t in enumerate(types) if t == "content"]
        filler_indices = [i for i, t in enumerate(types) if t == "filler"]

        assert len(content_indices) == 1, "Movie should have single content segment"
        if filler_indices:
            assert all(
                fi > content_indices[-1] for fi in filler_indices
            ), "Movie filler should trail content"
