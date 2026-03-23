"""INV-DSL-TIME-CONSERVATION-001 + INV-BLOCK-SEGMENT-CONSERVATION-001:
Validate that filler placeholders from the schedule compiler are correctly
replaced by traffic fill, with total duration preserved exactly.

These tests verify the full compile → fill pipeline:
1. compile_schedule() produces blocks with filler placeholders (asset_uri="")
2. fill_ad_blocks() replaces placeholders with real or fallback assets
3. No filler placeholders remain after fill
4. Total segment duration == block duration (conservation)
5. Segment ordering: structural segments unchanged, filler replaced in-place
"""
from __future__ import annotations

import pytest

from retrovue.config.testing import TEST_RESOLVED_CONFIG
from retrovue.runtime.schedule_compiler import compile_schedule
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.traffic_manager import fill_ad_blocks

from .conftest import make_network_dsl, make_network_resolver, make_movie_dsl, make_movie_resolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FILLER_URI = "/opt/retrovue/assets/filler.mp4"
FILLER_DURATION_MS = 30_000  # 30 seconds


def _compile_first_block(dsl, resolver) -> ScheduledBlock:
    """Compile and extract the first block as a ScheduledBlock."""
    plan = compile_schedule(dsl, resolver, resolved_config=TEST_RESOLVED_CONFIG)
    block_dict = plan["program_blocks"][0]
    cs = block_dict.get("compiled_segments", [])

    # Build ScheduledBlock from compiled_segments (same as expansion hydration)
    import hashlib
    from datetime import datetime

    dt = datetime.fromisoformat(block_dict["start_at"])
    start_utc_ms = int(dt.timestamp() * 1000)
    slot_ms = block_dict["slot_duration_sec"] * 1000
    end_utc_ms = start_utc_ms + slot_ms

    segments = []
    for s in cs:
        segments.append(ScheduledSegment(
            segment_type=s.get("segment_type", "content"),
            asset_uri=s.get("asset_id", "") if s.get("segment_type") != "filler" else "",
            asset_start_offset_ms=int(s.get("asset_start_offset_ms", 0)),
            segment_duration_ms=int(s["duration_ms"]),
            transition_in=s.get("transition_in", "TRANSITION_NONE"),
            transition_in_duration_ms=int(s.get("transition_in_duration_ms", 0)),
            transition_out=s.get("transition_out", "TRANSITION_NONE"),
            transition_out_duration_ms=int(s.get("transition_out_duration_ms", 0)),
            gain_db=s.get("gain_db", 0.0),
            is_primary=s.get("is_primary", False),
        ))

    raw = f"{block_dict['asset_id']}:{start_utc_ms}"
    block_id = f"blk-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"

    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_utc_ms,
        end_utc_ms=end_utc_ms,
        segments=tuple(segments),
    )


# ---------------------------------------------------------------------------
# Tests: Filler → Traffic Fill
# ---------------------------------------------------------------------------


class TestFillerToTrafficFill:
    """Validate that fill_ad_blocks replaces all filler placeholders."""

    def test_no_empty_filler_after_fill(self):
        """After fill_ad_blocks, no filler segment should have asset_uri=''."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        # Verify we have filler placeholders before fill
        empty_before = [
            s for s in block.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(empty_before) > 0, "Precondition: block must have empty filler"

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        empty_after = [
            s for s in filled.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(empty_after) == 0, (
            f"INV-DSL-TIME-CONSERVATION-001: {len(empty_after)} filler placeholders "
            f"remain after fill_ad_blocks. All must be replaced."
        )

    def test_duration_conservation_after_fill(self):
        """Total segment duration must equal block duration after fill."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        block_duration_ms = filled.end_utc_ms - filled.start_utc_ms
        seg_total_ms = sum(s.segment_duration_ms for s in filled.segments)

        assert seg_total_ms == block_duration_ms, (
            f"INV-BLOCK-SEGMENT-CONSERVATION-001: "
            f"seg_total={seg_total_ms}ms != block_duration={block_duration_ms}ms "
            f"(delta={seg_total_ms - block_duration_ms}ms)"
        )

    def test_structural_segments_unchanged_after_fill(self):
        """Content and presentation segments must not be modified by fill."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        structural_before = [
            (s.segment_type, s.segment_duration_ms, s.asset_start_offset_ms)
            for s in block.segments if s.segment_type != "filler"
        ]

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        structural_after = [
            (s.segment_type, s.segment_duration_ms, s.asset_start_offset_ms)
            for s in filled.segments if s.segment_type not in ("filler", "pad")
        ]

        assert structural_before == structural_after, (
            "INV-EXPANSION-NON-MUTATION-001: Structural segments must not change "
            "during traffic fill."
        )

    def test_movie_filler_replaced(self):
        """Movie post-content filler should be replaced."""
        dsl = make_movie_dsl()
        resolver = make_movie_resolver()
        block = _compile_first_block(dsl, resolver)

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        empty_after = [
            s for s in filled.segments
            if s.segment_type == "filler" and s.asset_uri == ""
        ]
        assert len(empty_after) == 0, "Movie post-content filler must be replaced"

    def test_filled_filler_has_real_uri(self):
        """After fill, all filler segments must have a non-empty asset_uri."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        filler_segs = [s for s in filled.segments if s.segment_type == "filler"]
        for i, seg in enumerate(filler_segs):
            assert seg.asset_uri != "", (
                f"Filler segment {i} still has empty asset_uri after fill"
            )
            assert seg.asset_uri == FILLER_URI, (
                f"Filler segment {i} has unexpected URI: {seg.asset_uri}"
            )

    def test_segment_count_may_increase(self):
        """Fill may split a single filler placeholder into multiple segments
        (wrapping at filler file end). Total duration must still match."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        before_count = len(block.segments)

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        # Segment count may increase (filler wrapping), that's OK
        # But conservation must hold
        block_duration_ms = filled.end_utc_ms - filled.start_utc_ms
        seg_total_ms = sum(s.segment_duration_ms for s in filled.segments)
        assert seg_total_ms == block_duration_ms


# ---------------------------------------------------------------------------
# Debug: Before/After Comparison
# ---------------------------------------------------------------------------


class TestFillerDebugOutput:
    """Diagnostic tests that print before/after state for visual inspection."""

    def test_print_before_after_network(self, capsys):
        """Print segment state before and after fill for a network block."""
        dsl = make_network_dsl(slots=1)
        resolver = make_network_resolver(chapter_markers=True)
        block = _compile_first_block(dsl, resolver)

        print("\n=== BEFORE FILL (schedule compiler output) ===")
        block_dur = block.end_utc_ms - block.start_utc_ms
        print(f"Block: {block.block_id}  duration={block_dur}ms")
        for i, seg in enumerate(block.segments):
            uri_label = seg.asset_uri[:40] if seg.asset_uri else "(empty)"
            print(f"  [{i:2d}] {seg.segment_type:12s}  {seg.segment_duration_ms:>8d}ms  "
                  f"offset={seg.asset_start_offset_ms:>8d}ms  uri={uri_label}")
        before_total = sum(s.segment_duration_ms for s in block.segments)
        print(f"  Total: {before_total}ms  (slot: {block_dur}ms)")

        filled = fill_ad_blocks(
            block,
            filler_uri=FILLER_URI,
            filler_duration_ms=FILLER_DURATION_MS,
        )

        print("\n=== AFTER FILL (traffic manager output) ===")
        for i, seg in enumerate(filled.segments):
            uri_label = seg.asset_uri[:40] if seg.asset_uri else "(empty)"
            print(f"  [{i:2d}] {seg.segment_type:12s}  {seg.segment_duration_ms:>8d}ms  "
                  f"offset={seg.asset_start_offset_ms:>8d}ms  uri={uri_label}")
        after_total = sum(s.segment_duration_ms for s in filled.segments)
        filled_dur = filled.end_utc_ms - filled.start_utc_ms
        print(f"  Total: {after_total}ms  (slot: {filled_dur}ms)")

        delta = after_total - filled_dur
        print(f"\n  Conservation: {'OK' if delta == 0 else f'VIOLATION delta={delta}ms'}")

        empty_remaining = sum(1 for s in filled.segments if s.segment_type == "filler" and s.asset_uri == "")
        print(f"  Empty fillers remaining: {empty_remaining}")

        assert delta == 0
        assert empty_remaining == 0
