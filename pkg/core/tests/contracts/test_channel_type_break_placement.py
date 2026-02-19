"""Contract tests: Channel type drives break placement (B-CT-1 through B-CT-4).

INV-CHANNEL-TYPE-BREAK-PLACEMENT: channel_type is the sole driver of break
placement strategy. Movie channels get post-content breaks only. Network
channels get mid-content breaks.
"""

import pytest
from retrovue.runtime.playout_log_expander import expand_program_block


class TestMovieChannelType:
    """B-CT-2: Movie type = zero mid-content breaks."""

    def test_movie_has_no_mid_content_breaks(self):
        b = expand_program_block(
            asset_id="movie1",
            asset_uri="/test/movie.mp4",
            start_utc_ms=0,
            slot_duration_ms=7200000,
            episode_duration_ms=6420000,
            channel_type="movie",
        )
        content_segs = [s for s in b.segments if s.segment_type == "content"]
        assert len(content_segs) == 1, "Movie must have exactly 1 content segment"

    def test_movie_filler_after_content(self):
        b = expand_program_block(
            asset_id="movie1",
            asset_uri="/test/movie.mp4",
            start_utc_ms=0,
            slot_duration_ms=7200000,
            episode_duration_ms=6420000,
            channel_type="movie",
        )
        assert b.segments[0].segment_type == "content"
        assert b.segments[1].segment_type == "filler"
        assert b.segments[1].segment_duration_ms == 7200000 - 6420000

    def test_movie_content_is_full_duration(self):
        b = expand_program_block(
            asset_id="movie1",
            asset_uri="/test/movie.mp4",
            start_utc_ms=0,
            slot_duration_ms=7200000,
            episode_duration_ms=6420000,
            channel_type="movie",
        )
        assert b.segments[0].segment_duration_ms == 6420000

    def test_movie_no_filler_when_exact_fit(self):
        """If movie exactly fills the slot, no filler segment needed."""
        b = expand_program_block(
            asset_id="movie1",
            asset_uri="/test/movie.mp4",
            start_utc_ms=0,
            slot_duration_ms=7200000,
            episode_duration_ms=7200000,
            channel_type="movie",
        )
        assert len(b.segments) == 1
        assert b.segments[0].segment_type == "content"

    def test_movie_ignores_chapter_markers(self):
        """B-CT-2: Movie channels ignore chapter markers — no mid-content breaks."""
        b = expand_program_block(
            asset_id="movie1",
            asset_uri="/test/movie.mp4",
            start_utc_ms=0,
            slot_duration_ms=7200000,
            episode_duration_ms=6000000,
            chapter_markers_ms=(1200000, 2400000, 3600000),
            channel_type="movie",
        )
        content_segs = [s for s in b.segments if s.segment_type == "content"]
        assert len(content_segs) == 1


class TestNetworkChannelType:
    """B-CT-3: Network type = mid-content breaks (existing behavior)."""

    def test_network_has_mid_content_breaks(self):
        b = expand_program_block(
            asset_id="ep1",
            asset_uri="/test/ep.mp4",
            start_utc_ms=0,
            slot_duration_ms=1800000,
            episode_duration_ms=1320000,
            channel_type="network",
        )
        filler_segs = [s for s in b.segments if s.segment_type == "filler"]
        assert len(filler_segs) == 3

    def test_network_uses_chapter_markers(self):
        b = expand_program_block(
            asset_id="ep1",
            asset_uri="/test/ep.mp4",
            start_utc_ms=0,
            slot_duration_ms=1800000,
            episode_duration_ms=1320000,
            chapter_markers_ms=(330000, 660000, 990000),
            channel_type="network",
        )
        content_segs = [s for s in b.segments if s.segment_type == "content"]
        assert len(content_segs) == 4


class TestDefaultChannelType:
    """B-CT-4: Default channel type is 'network'."""

    def test_default_is_network(self):
        b = expand_program_block(
            asset_id="ep1",
            asset_uri="/test/ep.mp4",
            start_utc_ms=0,
            slot_duration_ms=1800000,
            episode_duration_ms=1320000,
        )
        filler_segs = [s for s in b.segments if s.segment_type == "filler"]
        assert len(filler_segs) == 3, "Default should behave as network"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
