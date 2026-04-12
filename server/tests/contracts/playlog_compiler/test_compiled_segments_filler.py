"""INV-STRUCTURAL-RESOLUTION-001: compiled_segments must contain filler
placeholders (break slots) with positive duration.

After compile_schedule(), blocks where episode_duration < slot_duration
MUST have segment_type="filler" entries in compiled_segments. These are
Tier 4 placeholders — their asset identity is resolved later by the
traffic manager, but their duration and position are determined at
compile time.

This test is expected to FAIL against the current implementation.
The current compiler stores only assembly-level segments (content,
presentation, intro, outro) in compiled_segments. Filler placeholders
are created later by expand_program_block().
"""
from __future__ import annotations

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.schedule_compiler import compile_schedule

from .conftest import (
    make_movie_dsl,
    make_movie_resolver,
    make_network_dsl,
    make_network_resolver,
)


class TestCompiledSegmentsContainFillerPlaceholders:
    """INV-STRUCTURAL-RESOLUTION-001: Filler placeholders at compile time."""

    def test_network_block_has_filler_segments(self):
        """A 22-min sitcom in a 30-min slot has 8 minutes of break budget.
        compiled_segments must contain filler entries for that budget."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        filler_segs = [s for s in cs if s.get("segment_type") == "filler"]

        assert len(filler_segs) > 0, (
            "INV-STRUCTURAL-RESOLUTION-001: Network block with break budget "
            "must have filler placeholder segments in compiled_segments. "
            "Break detection must produce filler slots at compile time."
        )

    def test_filler_segments_have_positive_duration(self):
        """Every filler placeholder must have duration_ms > 0."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        filler_segs = [s for s in cs if s.get("segment_type") == "filler"]

        for i, seg in enumerate(filler_segs):
            assert seg.get("duration_ms", 0) > 0, (
                f"INV-STRUCTURAL-RESOLUTION-001: Filler segment {i} has "
                f"duration_ms={seg.get('duration_ms')}. Must be > 0."
            )

    def test_movie_block_has_post_content_filler(self):
        """A 115-min movie in a 4-slot (120-min) grid has 5 minutes of
        post-content filler."""
        dsl = make_movie_dsl()
        resolver = make_movie_resolver()

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        filler_segs = [s for s in cs if s.get("segment_type") == "filler"]

        assert len(filler_segs) > 0, (
            "INV-STRUCTURAL-RESOLUTION-001: Movie block with remaining "
            "slot time must have post-content filler in compiled_segments."
        )

    def test_filler_total_equals_break_budget(self):
        """Sum of filler durations must equal the break budget
        (slot_duration - episode_duration)."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        slot_ms = block["slot_duration_sec"] * 1000
        episode_ms = block["episode_duration_sec"] * 1000

        filler_total_ms = sum(
            s.get("duration_ms", 0) for s in cs
            if s.get("segment_type") == "filler"
        )
        expected_budget = slot_ms - episode_ms

        # The expected budget calculation is approximate because presentation
        # segments (if any) also consume grid time. For a block with no
        # presentation, filler_total should equal slot - episode.
        content_total_ms = sum(
            s.get("duration_ms", 0) for s in cs
            if s.get("segment_type") != "filler"
        )
        expected_filler = slot_ms - content_total_ms

        assert filler_total_ms == expected_filler, (
            f"INV-DSL-TIME-CONSERVATION-001: Filler total {filler_total_ms}ms "
            f"must equal slot_ms ({slot_ms}) - structural_ms ({content_total_ms}) "
            f"= {expected_filler}ms."
        )
