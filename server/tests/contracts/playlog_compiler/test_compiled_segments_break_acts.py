"""INV-STRUCTURAL-RESOLUTION-001: compiled_segments must contain break-aware
content acts, not a single flat content entry.

After compile_schedule(), network program blocks with chapter markers MUST
have multiple content segments in compiled_segments, each with a distinct
asset_start_offset_ms. Filler placeholders (break slots) MUST also appear.

This test is expected to FAIL against the current implementation.
The current compiler stores one content entry per AssemblySegment; break
detection runs later in _expand_blocks_inner(). The target model moves
break detection into compile_schedule().
"""
from __future__ import annotations

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.schedule_compiler import compile_schedule

from .conftest import make_network_dsl, make_network_resolver


class TestCompiledSegmentsContainBreakActs:
    """INV-STRUCTURAL-RESOLUTION-001: Break-aware content acts at compile time."""

    def test_network_block_has_multiple_content_segments(self):
        """A 22-min sitcom in a 30-min slot with 2 chapter markers must produce
        3 content acts in compiled_segments (act1, act2, act3)."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        blocks = plan["program_blocks"]
        assert len(blocks) >= 1

        block = blocks[0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        assert len(content_segs) >= 3, (
            f"INV-STRUCTURAL-RESOLUTION-001: Network block with 2 chapter markers "
            f"must have >= 3 content acts in compiled_segments, "
            f"got {len(content_segs)}. Break detection must happen at compile time."
        )

    def test_content_segments_have_asset_start_offset_ms(self):
        """Each content act must carry asset_start_offset_ms indicating its
        position within the source asset."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        for i, seg in enumerate(content_segs):
            assert "asset_start_offset_ms" in seg, (
                f"INV-STRUCTURAL-RESOLUTION-001: Content segment {i} missing "
                f"asset_start_offset_ms. Compile-time break detection must "
                f"produce seek offsets for each content act."
            )

    def test_content_offsets_are_sequential(self):
        """Content act offsets must be monotonically increasing — each act
        starts where the previous one ended within the source asset."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        if len(content_segs) < 2:
            pytest.skip("Need multiple content acts to test offset ordering")

        offsets = [s["asset_start_offset_ms"] for s in content_segs]
        for i in range(1, len(offsets)):
            assert offsets[i] > offsets[i - 1], (
                f"INV-STRUCTURAL-RESOLUTION-001: Content act offsets must be "
                f"monotonically increasing. Got offset[{i-1}]={offsets[i-1]}, "
                f"offset[{i}]={offsets[i]}."
            )

    def test_content_segments_have_transitions(self):
        """Content acts at algorithmic break points must have transition
        metadata (TRANSITION_FADE for second-class breaks)."""
        dsl = make_network_dsl(slots=1)
        # Use no chapter markers to force algorithmic breaks (second-class)
        resolver = make_network_resolver(chapter_markers=False)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        if len(content_segs) < 2:
            pytest.skip("Need multiple content acts to test transitions")

        # At least one non-final content segment should have transition_out
        has_transition = any(
            s.get("transition_out") == "TRANSITION_FADE"
            for s in content_segs[:-1]
        )
        assert has_transition, (
            "INV-STRUCTURAL-RESOLUTION-001: Algorithmic (second-class) break "
            "points must produce TRANSITION_FADE on content acts. No transitions "
            "found in compiled_segments."
        )

    def test_content_segments_have_gain_db(self):
        """Content segments must carry gain_db from the asset catalog."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        for i, seg in enumerate(content_segs):
            assert "gain_db" in seg, (
                f"INV-STRUCTURAL-RESOLUTION-001: Content segment {i} missing "
                f"gain_db. Must be resolved at compile time."
            )
            assert seg["gain_db"] == -2.5, (
                f"INV-STRUCTURAL-RESOLUTION-001: Content segment {i} gain_db "
                f"should be -2.5 (from catalog), got {seg['gain_db']}."
            )

    def test_movie_block_has_single_primary_content(self):
        """Movie/premium blocks must have exactly one content segment with
        is_primary=True (no mid-content breaks)."""
        from .conftest import make_movie_dsl, make_movie_resolver

        dsl = make_movie_dsl()
        resolver = make_movie_resolver()

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        content_segs = [s for s in cs if s.get("segment_type") == "content"]

        assert len(content_segs) == 1, (
            f"INV-MOVIE-PRIMARY-ATOMIC: Movie block must have exactly 1 "
            f"content segment, got {len(content_segs)}."
        )
        assert content_segs[0].get("is_primary", False), (
            "INV-MOVIE-PRIMARY-ATOMIC: Movie content segment must have "
            "is_primary=True."
        )
