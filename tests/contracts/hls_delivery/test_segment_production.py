"""
Contract Tests: HLS Segment Production

Canonical contract:
    docs/contracts/delivery_hls.md — §1 Segment Production Contract

These tests validate segment production invariants via HlsSegmenter + SegmentRing:
    INV-HLS-SEGMENT-IDENTITY-001       Monotonic channel-scoped indices
    INV-HLS-SEGMENT-IMMUTABLE-001      Completed segments are frozen / not rewritten
    INV-HLS-SEGMENT-KEYFRAME-001       Keyframe-aligned segment boundaries
    INV-HLS-SEGMENT-SELFCONTAINED-001  Each segment starts with a valid TS sync byte
    INV-HLS-SEGMENT-DURATION-BOUNDS-001 Duration within reasonable tolerance
    INV-HLS-SEGMENT-INDEX-GUARD-001    Index increments by exactly 1 per segment

Migrated from the retired hls_writer.HLSSegmenter API (commit 8cccc5b).
New API: HlsSegmenter + SegmentRing + ManifestGenerator.
"""

from __future__ import annotations

import pytest

from .conftest import (
    feed_n_segments,
    generate_segment_data,
    get_playlist,
    make_segmenter,
    make_ts_packet,
    extract_extinf_values,
    extract_segment_indices,
    extract_segment_names,
    TS_PACKET_SIZE,
    TS_SYNC_BYTE,
)


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-IDENTITY-001 — Monotonic channel-scoped indices
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentIdentity001:
    """INV-HLS-SEGMENT-IDENTITY-001: segment indices are monotonically increasing."""

    def test_indices_monotonically_increasing(self):
        """Each new segment has a strictly higher index than the previous."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 2, "Need at least 2 segments to check monotonicity"

        for i in range(1, len(window)):
            assert window[i].index > window[i - 1].index, (
                f"Index not monotonically increasing: "
                f"{window[i-1].index} → {window[i].index}"
            )

    def test_indices_start_at_zero_by_default(self):
        """First segment produced has index 0 when starting_index is 0."""
        seg, ring = make_segmenter(starting_index=0)
        feed_n_segments(seg, 1, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1
        assert window[0].index == 0, (
            f"First segment index expected 0, got {window[0].index}"
        )

    def test_indices_respect_starting_index(self):
        """Indices honour the starting_index parameter (resume from crash/restart)."""
        seg, ring = make_segmenter(starting_index=100)
        feed_n_segments(seg, 3, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1
        assert window[0].index == 100, (
            f"First segment index expected 100, got {window[0].index}"
        )

    def test_indices_increment_by_one(self):
        """Consecutive segment indices differ by exactly 1 (no gaps, no duplicates)."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 6, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 2

        for i in range(1, len(window)):
            delta = window[i].index - window[i - 1].index
            assert delta == 1, (
                f"Index delta expected 1, got {delta} "
                f"({window[i-1].index} → {window[i].index})"
            )

    def test_playlist_indices_match_ring_indices(self):
        """Segment indices in the manifest match those stored in the ring."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        playlist_indices = extract_segment_indices(playlist)
        window = ring.window()
        ring_indices = [s.index for s in window]

        # The manifest window is the tail of the ring window
        assert len(playlist_indices) > 0
        for idx in playlist_indices:
            assert idx in ring_indices, (
                f"Manifest lists segment {idx} not present in ring"
            )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-IMMUTABLE-001 — Completed segments not rewritten
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentImmutable001:
    """INV-HLS-SEGMENT-IMMUTABLE-001: completed segment data is frozen."""

    def test_completed_segment_data_is_bytes(self):
        """Completed segments carry immutable bytes data, not a mutable buffer."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for live_seg in window:
            assert isinstance(live_seg.data, bytes), (
                f"Segment {live_seg.index}: data is {type(live_seg.data).__name__}, expected bytes"
            )

    def test_segment_data_stable_across_reads(self):
        """Reading a segment twice returns identical data."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        newest_idx = ring.newest_index()
        assert newest_idx is not None

        first_read = ring.get(newest_idx)
        second_read = ring.get(newest_idx)

        assert first_read is not None
        assert second_read is not None
        assert first_read.data == second_read.data, (
            f"Segment {newest_idx} returned different data on second read"
        )

    def test_further_feeding_does_not_mutate_old_segment(self):
        """Feeding more TS data does not change the content of a completed segment."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        # Snapshot the first segment
        first_window = ring.window()
        assert len(first_window) >= 1
        first_idx = first_window[0].index
        snapshot_data = ring.get(first_idx)
        assert snapshot_data is not None
        original_data = snapshot_data.data

        # Feed more data
        feed_n_segments(seg, 3, target_dur=2.5, pcr_offset=5.0)

        # First segment must be unchanged (if still in ring)
        refreshed = ring.get(first_idx)
        if refreshed is not None:
            assert refreshed.data == original_data, (
                f"Segment {first_idx} data mutated after further feeding"
            )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-KEYFRAME-001 — Keyframe-aligned boundaries
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentKeyframe001:
    """INV-HLS-SEGMENT-KEYFRAME-001: each segment begins at a keyframe."""

    def test_segment_starts_with_sync_byte(self):
        """All segments start with MPEG-TS sync byte 0x47."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for live_seg in window:
            assert len(live_seg.data) >= TS_PACKET_SIZE, (
                f"Segment {live_seg.index} too short to contain a TS packet"
            )
            assert live_seg.data[0] == TS_SYNC_BYTE, (
                f"Segment {live_seg.index} does not start with TS sync byte 0x47"
            )

    def test_segment_count_matches_keyframe_count(self):
        """Segments are produced only at keyframe boundaries."""
        seg, ring = make_segmenter(target_ms=2000)

        # feed_n_segments delivers exactly N keyframes followed by a flush trigger
        n = 4
        feed_n_segments(seg, n, target_dur=2.5)

        window = ring.window()
        # Expect exactly n segments (one per keyframe group)
        assert len(window) == n, (
            f"Expected {n} segments for {n} keyframe groups, got {len(window)}"
        )

    def test_non_keyframe_data_does_not_produce_segment(self):
        """Feeding non-keyframe TS packets alone does not produce a segment."""
        seg, ring = make_segmenter(target_ms=2000)

        # Feed packets without keyframe marker
        for i in range(50):
            pkt = make_ts_packet(pid=0x100, keyframe=False, cc=i % 16)
            seg.feed(pkt)

        window = ring.window()
        # No keyframe boundary was crossed → no completed segment
        assert len(window) == 0, (
            f"Expected 0 segments from non-keyframe data, got {len(window)}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-SELFCONTAINED-001 — Structurally decodable
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentSelfContained001:
    """INV-HLS-SEGMENT-SELFCONTAINED-001: segments are valid TS packet streams."""

    def test_segment_length_multiple_of_188(self):
        """Each segment's byte length is a multiple of TS_PACKET_SIZE (188)."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for live_seg in window:
            assert len(live_seg.data) % TS_PACKET_SIZE == 0, (
                f"Segment {live_seg.index} length {len(live_seg.data)} "
                f"is not a multiple of {TS_PACKET_SIZE}"
            )

    def test_all_packets_have_valid_sync_byte(self):
        """Every 188-byte packet in each segment has sync byte 0x47."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for live_seg in window:
            data = live_seg.data
            n_packets = len(data) // TS_PACKET_SIZE
            for pkt_i in range(n_packets):
                offset = pkt_i * TS_PACKET_SIZE
                assert data[offset] == TS_SYNC_BYTE, (
                    f"Segment {live_seg.index}, packet {pkt_i} "
                    f"at offset {offset}: bad sync byte 0x{data[offset]:02x}"
                )

    def test_segment_not_empty(self):
        """Completed segments contain at least one TS packet."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for live_seg in window:
            assert len(live_seg.data) >= TS_PACKET_SIZE, (
                f"Segment {live_seg.index} is empty"
            )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-DURATION-BOUNDS-001 — Duration within tolerance
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentDurationBounds001:
    """INV-HLS-SEGMENT-DURATION-BOUNDS-001: segment durations within reasonable bounds."""

    def test_extinf_values_are_positive(self):
        """All EXTINF duration values in the manifest are positive."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        durations = extract_extinf_values(playlist)
        assert len(durations) >= 1

        for d in durations:
            assert d > 0, f"EXTINF duration is not positive: {d}"

    def test_extinf_values_within_2x_target(self):
        """EXTINF durations do not exceed 2× the target duration."""
        target_s = 2.5
        seg, ring = make_segmenter(target_ms=int(target_s * 1000))
        feed_n_segments(seg, 5, target_dur=target_s)

        playlist = get_playlist(ring)
        assert playlist

        durations = extract_extinf_values(playlist)
        assert len(durations) >= 1

        for d in durations:
            assert d <= target_s * 2, (
                f"EXTINF duration {d:.3f}s exceeds 2× target {target_s}s"
            )

    def test_segment_durations_consistent_with_pcr(self):
        """Segment durations are driven by PCR, not wall clock."""
        # Feed uniform 2.5-second PCR segments
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        durations = extract_extinf_values(playlist)
        assert len(durations) >= 2

        # All durations should be approximately 2.5 seconds (± 1s tolerance)
        for d in durations:
            assert 1.0 <= d <= 5.0, (
                f"Duration {d:.3f}s far outside expected 2.5s range"
            )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-INDEX-GUARD-001 — Index counter integrity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentIndexGuard001:
    """INV-HLS-SEGMENT-INDEX-GUARD-001: index counter only advances on completion."""

    def test_no_index_gap_across_segments(self):
        """No index values are skipped between produced segments."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 8, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 2

        for i in range(1, len(window)):
            expected = window[i - 1].index + 1
            actual = window[i].index
            assert actual == expected, (
                f"Index gap: expected {expected}, got {actual}"
            )

    def test_last_completed_index_tracks_newest(self):
        """segmenter.last_completed_index() matches the newest ring entry."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        newest = ring.newest_index()
        last_completed = seg.last_completed_index()

        assert newest is not None
        assert last_completed is not None
        assert last_completed == newest, (
            f"last_completed_index {last_completed} != ring newest {newest}"
        )

    def test_starting_index_honoured_after_multiple_segments(self):
        """starting_index offset is preserved across all produced segments."""
        offset = 500
        seg, ring = make_segmenter(starting_index=offset, target_ms=2000)
        feed_n_segments(seg, 4, target_dur=2.5)

        window = ring.window()
        assert len(window) >= 1

        for i, live_seg in enumerate(window):
            expected_idx = offset + i
            assert live_seg.index == expected_idx, (
                f"Segment position {i}: expected index {expected_idx}, "
                f"got {live_seg.index}"
            )
