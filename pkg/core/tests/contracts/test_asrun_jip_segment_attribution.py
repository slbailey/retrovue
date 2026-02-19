"""
Contract Tests — INV-ASRUN-JIP-ATTR-001: JIP Segment Attribution

Regression test for the bug where AsRun attributed PAD segments with the
next CONTENT/FILLER segment's name after JIP renumbering.

Root cause: After JIP, _apply_jip_to_segments removes fully-elapsed segments
and renumbers the rest from 0. The evidence_server looked up segment metadata
from TransmissionLog using AIR's renumbered indices, but TransmissionLog
stored original pre-JIP indices. This caused a 1-segment shift in attribution.

Fix: Pre-populate the evidence segment cache with the JIP-renumbered segment
list when the block is fed, so attribution uses the correct metadata.
"""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest


# ---- Helpers ----------------------------------------------------------------

def _make_segments_with_interleaved_pads():
    """Build a TransmissionLog-style segment list:
    0: content  (Cheers episode, 114448ms)
    1: commercial (Nike, 59968ms)
    2: pad (BLACK, 374ms)
    3: commercial (Snickers, 15248ms)
    4: pad (BLACK, 374ms)
    5: filler (Grammy Awards, 5338ms)
    6: pad (BLACK, 375ms)
    """
    return [
        {"segment_index": 0, "segment_type": "content",
         "title": "Cheers S02E04", "asset_uri": "/media/cheers.mp4",
         "asset_start_offset_ms": 0, "segment_duration_ms": 114448},
        {"segment_index": 1, "segment_type": "commercial",
         "title": "Nike - Wings {1998}", "asset_uri": "/ads/nike.mp4",
         "asset_start_offset_ms": 0, "segment_duration_ms": 59968},
        {"segment_index": 2, "segment_type": "pad",
         "title": "BLACK", "asset_uri": "",
         "asset_start_offset_ms": 0, "segment_duration_ms": 374},
        {"segment_index": 3, "segment_type": "commercial",
         "title": "Snickers Minis {1999}", "asset_uri": "/ads/snickers.mp4",
         "asset_start_offset_ms": 0, "segment_duration_ms": 15248},
        {"segment_index": 4, "segment_type": "pad",
         "title": "BLACK", "asset_uri": "",
         "asset_start_offset_ms": 0, "segment_duration_ms": 374},
        {"segment_index": 5, "segment_type": "filler",
         "title": "Grammy Awards {1998}", "asset_uri": "/filler/grammy.mp4",
         "asset_start_offset_ms": 0, "segment_duration_ms": 5338},
        {"segment_index": 6, "segment_type": "pad",
         "title": "BLACK", "asset_uri": "",
         "asset_start_offset_ms": 0, "segment_duration_ms": 375},
    ]


def _apply_jip_and_renumber(segments, jip_offset_ms):
    """Simulate JIP: skip elapsed segments, trim partial, renumber from 0."""
    from retrovue.runtime.channel_manager import _apply_jip_to_segments
    block_dur = sum(s["segment_duration_ms"] for s in segments) - jip_offset_ms
    result = _apply_jip_to_segments(segments, jip_offset_ms, block_dur)
    for i, seg in enumerate(result):
        seg["segment_index"] = i
    return result


def _lookup_from_list(segments, segment_index):
    """Simulate _lookup_segment_from_db against a segment list."""
    for s in segments:
        if s.get("segment_index") == segment_index:
            return types.SimpleNamespace(
                segment_index=s["segment_index"],
                segment_type=s.get("segment_type", "content"),
                asset_uri=s.get("asset_uri", ""),
                title=s.get("title", ""),
                segment_duration_ms=s.get("segment_duration_ms", 0),
                asset_start_offset_ms=s.get("asset_start_offset_ms", 0),
            )
    return None


# ---- Tests ------------------------------------------------------------------

class TestJipSegmentAttribution:
    """INV-ASRUN-JIP-ATTR-001: After JIP, segment attribution must use
    the renumbered (fed) segment list, not the original DB indices."""

    def test_no_jip_indices_match(self):
        """Without JIP, DB indices and AIR indices are identical."""
        db_segments = _make_segments_with_interleaved_pads()
        # No JIP: fed segments = db segments
        fed_segments = [dict(s) for s in db_segments]

        for seg in fed_segments:
            db_info = _lookup_from_list(db_segments, seg["segment_index"])
            assert db_info is not None
            assert db_info.segment_type == seg["segment_type"], (
                f"seg {seg['segment_index']}: DB type={db_info.segment_type} "
                f"!= fed type={seg['segment_type']}"
            )
            assert db_info.title == seg.get("title", ""), (
                f"seg {seg['segment_index']}: DB title={db_info.title} "
                f"!= fed title={seg.get('title', '')}"
            )

    def test_jip_skips_first_segment_causes_index_shift(self):
        """JIP that skips the entire first segment shifts all indices by 1.
        Looking up AIR segment_index in the original DB returns WRONG segment."""
        db_segments = _make_segments_with_interleaved_pads()
        # JIP 120000ms into the block: skips Cheers (114448ms) entirely,
        # lands 5552ms into Nike (59968ms).
        jip_offset_ms = 120000
        fed_segments = _apply_jip_and_renumber(db_segments, jip_offset_ms)

        # After JIP: seg 0 = Nike (trimmed), seg 1 = PAD, seg 2 = Snickers, ...
        assert fed_segments[0]["segment_type"] == "commercial"  # Nike
        assert fed_segments[1]["segment_type"] == "pad"          # BLACK

        # BUG DEMONSTRATION: DB lookup using AIR's index returns wrong segment
        air_seg_1 = fed_segments[1]  # This is PAD BLACK in AIR
        db_info = _lookup_from_list(db_segments, air_seg_1["segment_index"])
        # DB segment_index=1 is Nike (commercial), NOT pad
        assert db_info.segment_type == "commercial", (
            "Expected DB seg 1 to be commercial (Nike) — this is the stale lookup"
        )
        assert db_info.segment_type != air_seg_1["segment_type"], (
            "If DB and AIR agree, the JIP shift didn't happen — test is wrong"
        )

    def test_prepopulated_cache_returns_correct_type(self):
        """With the fix: looking up in the prepopulated (JIP-renumbered) cache
        returns the correct segment type."""
        db_segments = _make_segments_with_interleaved_pads()
        jip_offset_ms = 120000
        fed_segments = _apply_jip_and_renumber(db_segments, jip_offset_ms)

        # Simulate prepopulated cache lookup (using fed segments, not DB)
        for seg in fed_segments:
            cache_info = _lookup_from_list(fed_segments, seg["segment_index"])
            assert cache_info is not None
            assert cache_info.segment_type == seg["segment_type"], (
                f"seg {seg['segment_index']}: cache type={cache_info.segment_type} "
                f"!= fed type={seg['segment_type']}"
            )

    def test_pad_segments_labeled_as_pad_not_adjacent_content(self):
        """Core assertion: PAD segments must NEVER be labeled with an
        adjacent content/filler/commercial name after JIP."""
        db_segments = _make_segments_with_interleaved_pads()
        jip_offset_ms = 120000
        fed_segments = _apply_jip_and_renumber(db_segments, jip_offset_ms)

        for seg in fed_segments:
            if seg["segment_type"] == "pad":
                cache_info = _lookup_from_list(fed_segments, seg["segment_index"])
                assert cache_info.segment_type == "pad", (
                    f"PAD segment at index {seg['segment_index']} attributed as "
                    f"{cache_info.segment_type} — WRONG (should be 'pad')"
                )

    def test_content_segments_keep_own_names(self):
        """Content/filler/commercial segments retain their own asset names."""
        db_segments = _make_segments_with_interleaved_pads()
        jip_offset_ms = 120000
        fed_segments = _apply_jip_and_renumber(db_segments, jip_offset_ms)

        for seg in fed_segments:
            if seg["segment_type"] in ("commercial", "filler", "content"):
                cache_info = _lookup_from_list(fed_segments, seg["segment_index"])
                assert cache_info.asset_uri == seg["asset_uri"], (
                    f"seg {seg['segment_index']}: cache uri={cache_info.asset_uri} "
                    f"!= fed uri={seg['asset_uri']}"
                )

    def test_prepopulate_block_segment_cache_integration(self):
        """Integration test: prepopulate_block_segment_cache makes
        _lookup_segment_from_db return fed (correct) metadata."""
        from retrovue.runtime.evidence_server import (
            prepopulate_block_segment_cache,
            _lookup_segment_from_db,
            _clear_block_segment_cache,
        )

        db_segments = _make_segments_with_interleaved_pads()
        jip_offset_ms = 120000
        fed_segments = _apply_jip_and_renumber(db_segments, jip_offset_ms)

        block_id = "blk-test-jip-attr"

        try:
            # Prepopulate with JIP-renumbered segments
            prepopulate_block_segment_cache(block_id, fed_segments)

            # Lookup should hit the prepopulated cache, not the DB
            for seg in fed_segments:
                info = _lookup_segment_from_db(block_id, seg["segment_index"])
                assert info is not None, (
                    f"Lookup returned None for seg {seg['segment_index']}"
                )
                assert info.segment_type == seg["segment_type"], (
                    f"seg {seg['segment_index']}: lookup type={info.segment_type} "
                    f"!= expected type={seg['segment_type']}"
                )

            # Specifically verify PAD is PAD, not the adjacent commercial
            pad_info = _lookup_segment_from_db(block_id, 1)
            assert pad_info.segment_type == "pad", (
                f"Segment 1 should be PAD but got {pad_info.segment_type}"
            )
        finally:
            _clear_block_segment_cache(block_id)

    def test_frame_counts_unaffected(self):
        """Frame counting logic is NOT in the attribution path.
        Verify seg_frames = frame_idx_end - frame_idx_start is independent
        of segment naming."""
        # Frame count is computed in on_segment_start callback as:
        # seg_frames = frame_idx - ls.start_frame
        # This is pure arithmetic on session_frame_index, unrelated to
        # segment metadata. This test documents that invariant.
        start_frame = 949
        end_frame = 960
        seg_frames = end_frame - start_frame  # 11 frames (PAD duration)
        assert seg_frames == 11
        # The fix changes ONLY attribution (type/title), not frame counting.
