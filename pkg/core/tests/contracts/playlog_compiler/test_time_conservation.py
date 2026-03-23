"""INV-DSL-TIME-CONSERVATION-001: For every compiled block,
block_duration == sum(structural_segments) + sum(fill_segments).

No time is unaccounted for. No time is double-allocated.

This test validates time conservation at the compilation stage. Every
compiled_segments entry contributes to the total. The sum of all
segment durations must exactly equal slot_duration_sec * 1000.

This test is expected to FAIL against the current implementation.
The current compiled_segments do not include filler placeholders,
so their total is less than slot duration.
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


class TestTimeConservationAllTiers:
    """INV-DSL-TIME-CONSERVATION-001: Time conservation at compile time."""

    def test_network_block_conservation(self):
        """Sum of all compiled_segments durations == slot_duration_sec * 1000
        for a network sitcom block."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        for block in plan["program_blocks"]:
            cs = block.get("compiled_segments", [])
            slot_ms = block["slot_duration_sec"] * 1000
            seg_total_ms = sum(s.get("duration_ms", 0) for s in cs)

            assert seg_total_ms == slot_ms, (
                f"INV-DSL-TIME-CONSERVATION-001: Block '{block['title']}' — "
                f"sum(compiled_segments) = {seg_total_ms}ms, "
                f"slot_duration = {slot_ms}ms. "
                f"Delta = {seg_total_ms - slot_ms}ms. "
                f"All time must be accounted for at compile time."
            )

    def test_movie_block_conservation(self):
        """Sum of all compiled_segments durations == slot_duration_sec * 1000
        for a premium movie block."""
        dsl = make_movie_dsl()
        resolver = make_movie_resolver()

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        for block in plan["program_blocks"]:
            cs = block.get("compiled_segments", [])
            slot_ms = block["slot_duration_sec"] * 1000
            seg_total_ms = sum(s.get("duration_ms", 0) for s in cs)

            assert seg_total_ms == slot_ms, (
                f"INV-DSL-TIME-CONSERVATION-001: Block '{block['title']}' — "
                f"sum(compiled_segments) = {seg_total_ms}ms, "
                f"slot_duration = {slot_ms}ms. "
                f"Delta = {seg_total_ms - slot_ms}ms."
            )

    def test_multi_block_conservation(self):
        """Time conservation holds across all blocks in a multi-block
        schedule compilation."""
        dsl = make_network_dsl(slots=4)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        for i, block in enumerate(plan["program_blocks"]):
            cs = block.get("compiled_segments", [])
            slot_ms = block["slot_duration_sec"] * 1000
            seg_total_ms = sum(s.get("duration_ms", 0) for s in cs)

            assert seg_total_ms == slot_ms, (
                f"INV-DSL-TIME-CONSERVATION-001: Block {i} '{block['title']}' — "
                f"sum = {seg_total_ms}ms, slot = {slot_ms}ms, "
                f"delta = {seg_total_ms - slot_ms}ms."
            )

    def test_no_negative_segment_durations(self):
        """No compiled segment may have duration_ms <= 0."""
        dsl = make_network_dsl(slots=2)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        for block in plan["program_blocks"]:
            cs = block.get("compiled_segments", [])
            for j, seg in enumerate(cs):
                dur = seg.get("duration_ms", 0)
                assert dur > 0, (
                    f"INV-DSL-NONNEGATIVE-FILL-001: Block '{block['title']}' "
                    f"segment {j} (type={seg.get('segment_type')}) has "
                    f"duration_ms={dur}. All segments must have positive duration."
                )

    def test_structural_plus_fill_equals_slot(self):
        """Explicit check: structural (non-filler) + filler = slot duration."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)

        plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)

        block = plan["program_blocks"][0]
        cs = block.get("compiled_segments", [])
        slot_ms = block["slot_duration_sec"] * 1000

        structural_ms = sum(
            s.get("duration_ms", 0) for s in cs
            if s.get("segment_type") != "filler"
        )
        fill_ms = sum(
            s.get("duration_ms", 0) for s in cs
            if s.get("segment_type") == "filler"
        )

        assert structural_ms + fill_ms == slot_ms, (
            f"INV-DSL-TIME-CONSERVATION-001: "
            f"structural({structural_ms}) + fill({fill_ms}) = "
            f"{structural_ms + fill_ms}, expected {slot_ms}."
        )
