"""Contract tests for INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001.

Premium channels (channel_type="premium") MUST NOT insert mid-content
breaks.  All filler/interstitial time goes after content ends, identical
to the existing "movie" channel_type behaviour.

Chapter markers in the source asset MUST be ignored for break placement
on premium channels.

Derived from: LAW-CONTENT-AUTHORITY, INV-CHANNEL-TYPE-BREAK-PLACEMENT.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.playout_log_expander import expand_program_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SLOT_MS = 120 * 60 * 1000        # 2-hour slot
EPISODE_MS = 108 * 60 * 1000     # 108-minute movie
CHAPTER_MS = tuple(range(10_000, EPISODE_MS, 15 * 60 * 1000))  # every 15 min


def _expand(channel_type: str, chapters=CHAPTER_MS):
    return expand_program_block(
        asset_id="test-movie",
        asset_uri="/movies/test.mkv",
        start_utc_ms=1_700_000_000_000,
        slot_duration_ms=SLOT_MS,
        episode_duration_ms=EPISODE_MS,
        chapter_markers_ms=chapters,
        channel_type=channel_type,
    )


# ---------------------------------------------------------------------------
# INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001
# ---------------------------------------------------------------------------

class TestPremiumNoMidBreak:
    """Premium channels must never split content with mid-content breaks."""

    def test_premium_has_no_mid_content_filler(self):
        """No filler segment should appear before the primary content ends."""
        block = _expand("premium")
        content_ended = False
        for seg in block.segments:
            if seg.segment_type == "content":
                assert not content_ended, (
                    "INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001: "
                    "content segment found after filler — mid-content break detected"
                )
            elif seg.segment_type == "filler":
                content_ended = True

    def test_premium_single_content_segment(self):
        """Premium movie block should have exactly one content segment."""
        block = _expand("premium")
        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) == 1, (
            f"INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001: "
            f"expected 1 content segment, got {len(content_segs)}"
        )

    def test_premium_content_duration_matches_episode(self):
        """The single content segment must span the full episode duration."""
        block = _expand("premium")
        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert content_segs[0].segment_duration_ms == EPISODE_MS

    def test_premium_ignores_chapter_markers(self):
        """Chapter markers must not produce breaks on premium channels."""
        with_chapters = _expand("premium", chapters=CHAPTER_MS)
        without_chapters = _expand("premium", chapters=None)
        assert len(with_chapters.segments) == len(without_chapters.segments), (
            "INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001: "
            "chapter markers affected segment count on premium channel"
        )

    def test_premium_filler_only_after_content(self):
        """Filler must appear only after content (post-content block)."""
        block = _expand("premium")
        types = [s.segment_type for s in block.segments]
        # Valid layouts: [content] or [content, filler]
        assert types[0] == "content"
        for t in types[1:]:
            assert t == "filler", (
                f"INV-CHANNEL-TYPE-PREMIUM-NO-MID-BREAK-001: "
                f"non-filler segment '{t}' after content"
            )

    def test_premium_matches_movie_behaviour(self):
        """Premium and movie channel types must produce identical layouts."""
        premium = _expand("premium")
        movie = _expand("movie")
        assert len(premium.segments) == len(movie.segments)
        for p, m in zip(premium.segments, movie.segments):
            assert p.segment_type == m.segment_type
            assert p.segment_duration_ms == m.segment_duration_ms

    def test_network_still_uses_chapter_breaks(self):
        """Sanity: network channels must still get mid-content breaks."""
        block = _expand("network")
        content_segs = [s for s in block.segments if s.segment_type == "content"]
        assert len(content_segs) > 1, (
            "Sanity check failed: network channel should have mid-content breaks"
        )
