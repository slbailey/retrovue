"""
Contract Tests: HLS Delivery Endpoints

Canonical contract:
    docs/contracts/delivery_hls.md — §4 HLS Delivery Contract

Test matrix:
    docs/contracts/TEST-MATRIX-HLS-DELIVERY.md — Endpoint Coexistence

These tests enforce the delivery endpoint invariants
(INV-HLS-ENDPOINT-COEXIST-001, INV-HLS-LIFECYCLE-SEGMENT-READY-001,
INV-HLS-SERVE-BYTE-IDENTITY-001, INV-HLS-ENDPOINT-SESSION-TOUCH-001,
INV-HLS-QUIET-POLLING-001) using the HLSSegmenter's public API.

Every test references the specific invariant(s) it validates.

Note: These tests validate behavioral contracts at the segmenter level.
Full HTTP-level endpoint tests (Content-Type, Cache-Control, status codes)
require integration with the FastAPI application and are defined separately
in pkg/core/tests/contracts/runtime/.
"""

from __future__ import annotations

import re

import pytest

from retrovue.streaming.hls_writer import HLSSegmenter, TS_SYNC_BYTE, TS_PACKET_SIZE

from .conftest import (
    feed_n_segments,
    extract_segment_names,
    extract_segment_indices,
)


# ---------------------------------------------------------------------------
# INV-HLS-ENDPOINT-COEXIST-001 — Protocol coexistence
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsEndpointCoexist001:
    """INV-HLS-ENDPOINT-COEXIST-001"""

    # Tier: 2 | Structural invariant
    def test_segment_data_is_valid_ts(self, segmenter_with_segments):
        """Every segment served is valid MPEG-TS (sync bytes at 188-byte boundaries)."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        for name in extract_segment_names(playlist):
            data = seg.get_segment(name)
            assert data is not None

            # INV-HLS-ENDPOINT-COEXIST-001 — valid TS content
            assert len(data) > 0
            assert len(data) % TS_PACKET_SIZE == 0, (
                f"Segment {name}: {len(data)} bytes not aligned to {TS_PACKET_SIZE}"
            )
            for offset in range(0, min(len(data), TS_PACKET_SIZE * 10), TS_PACKET_SIZE):
                assert data[offset] == TS_SYNC_BYTE, (
                    f"Bad sync byte at offset {offset} in {name}"
                )

    # Tier: 2 | Structural invariant
    def test_playlist_and_segments_coexist(self, segmenter_with_segments):
        """Playlist and segment data can be retrieved simultaneously."""
        seg = segmenter_with_segments

        # INV-HLS-ENDPOINT-COEXIST-001 — both paths work
        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        assert len(names) >= 1

        # Interleave playlist and segment reads
        for name in names:
            assert seg.get_playlist() is not None  # playlist still works
            data = seg.get_segment(name)
            assert data is not None  # segment still works


# ---------------------------------------------------------------------------
# INV-HLS-LIFECYCLE-SEGMENT-READY-001 — Startup availability
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsLifecycleSegmentReady001:
    """INV-HLS-LIFECYCLE-SEGMENT-READY-001"""

    # Tier: 2 | Lifecycle invariant
    def test_no_playlist_before_first_segment(self):
        """Before any segment completes, playlist returns None."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — not ready = None
        assert seg.get_playlist() is None
        assert seg.has_playlist() is False

        seg.stop()

    # Tier: 2 | Lifecycle invariant
    def test_playlist_available_after_first_segment(self):
        """After first segment completes, playlist is available."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        feed_n_segments(seg, 1, target_dur=2.5)

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — ready after first segment
        assert seg.has_playlist() is True
        playlist = seg.get_playlist()
        assert playlist is not None
        assert playlist.startswith("#EXTM3U")

        seg.stop()

    # Tier: 2 | Lifecycle invariant
    def test_wait_for_playlist_returns_false_when_empty(self):
        """wait_for_playlist with zero timeout returns False when no segments."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — immediate check = not ready
        assert seg.wait_for_playlist(0) is False

        seg.stop()

    # Tier: 2 | Lifecycle invariant
    def test_wait_for_playlist_returns_true_when_ready(self, segmenter_with_segments):
        """wait_for_playlist returns True after segments are available."""
        seg = segmenter_with_segments

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — ready = True
        assert seg.wait_for_playlist(0) is True

    # Tier: 2 | Lifecycle invariant
    def test_additional_viewers_see_same_playlist(self, segmenter_with_segments):
        """Additional readers see the same playlist — no per-viewer state."""
        seg = segmenter_with_segments

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — no per-viewer impact
        p1 = seg.get_playlist()
        p2 = seg.get_playlist()
        p3 = seg.get_playlist()

        assert p1 == p2 == p3


# ---------------------------------------------------------------------------
# INV-HLS-SERVE-BYTE-IDENTITY-001 — Segment fidelity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsServeByteIdentity001:
    """INV-HLS-SERVE-BYTE-IDENTITY-001"""

    # Tier: 1 | Structural invariant
    def test_segment_bytes_identical_across_reads(self, segmenter_with_segments):
        """Two reads of the same segment return byte-identical data."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        for name in names:
            read_1 = seg.get_segment(name)
            read_2 = seg.get_segment(name)

            assert read_1 is not None
            assert read_2 is not None
            # INV-HLS-SERVE-BYTE-IDENTITY-001 — byte identity
            assert read_1 == read_2, f"Bytes differ for {name}"

    # Tier: 1 | Structural invariant
    def test_evicted_segment_returns_none_not_error(self):
        """Requesting an evicted segment returns None, not an exception."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=3)
        seg.start()

        feed_n_segments(seg, 6, target_dur=2.5)

        # INV-HLS-SERVE-BYTE-IDENTITY-001 — absent = None
        result = seg.get_segment("seg_00000.ts")
        assert result is None

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_nonexistent_segment_returns_none(self, segmenter_with_segments):
        """Requesting a never-produced segment returns None."""
        seg = segmenter_with_segments

        # INV-HLS-SERVE-BYTE-IDENTITY-001 — never produced = None
        result = seg.get_segment("seg_99999.ts")
        assert result is None

    # Tier: 1 | Structural invariant
    def test_segment_name_validation(self, segmenter_with_segments):
        """Invalid segment names return None, not an error."""
        seg = segmenter_with_segments

        # INV-HLS-SERVE-BYTE-IDENTITY-001 — invalid names handled gracefully
        assert seg.get_segment("") is None
        assert seg.get_segment("not_a_segment") is None
        assert seg.get_segment("../../../etc/passwd") is None


# ---------------------------------------------------------------------------
# INV-HLS-ENDPOINT-SESSION-TOUCH-001 — Touch on success only
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsEndpointSessionTouch001:
    """INV-HLS-ENDPOINT-SESSION-TOUCH-001

    Session touch behavior is tested at the session manager level
    (see test_viewer_presence.py). These tests validate the preconditions:
    successful retrieval vs. failure.
    """

    # Tier: 2 | Lifecycle invariant
    def test_successful_segment_retrieval_is_touchable(self, segmenter_with_segments):
        """A successful segment retrieval (non-None) represents a touchable event."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        for name in names:
            result = seg.get_segment(name)
            # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — success = touchable
            assert result is not None, f"Expected success for {name}"

    # Tier: 2 | Lifecycle invariant
    def test_failed_retrieval_is_not_touchable(self):
        """A failed retrieval (None) represents a non-touchable event."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=3)
        seg.start()
        feed_n_segments(seg, 5, target_dur=2.5)

        # Evicted segment — failure
        result = seg.get_segment("seg_00000.ts")
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — failure = not touchable
        assert result is None

        seg.stop()

    # Tier: 2 | Lifecycle invariant
    def test_playlist_none_is_not_touchable(self):
        """Empty playlist (None) represents a non-touchable event (503 scenario)."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        result = seg.get_playlist()
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — no playlist = not touchable
        assert result is None

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-QUIET-POLLING-001 — Polling noise suppression
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsQuietPolling001:
    """INV-HLS-QUIET-POLLING-001"""

    # Tier: 1 | Operational invariant
    def test_high_frequency_reads_do_not_crash(self, segmenter_with_segments):
        """Rapid polling of playlist and segments is safe and stable."""
        seg = segmenter_with_segments

        # INV-HLS-QUIET-POLLING-001 — high-frequency access is safe
        for _ in range(100):
            playlist = seg.get_playlist()
            assert playlist is not None

            names = extract_segment_names(playlist)
            for name in names:
                data = seg.get_segment(name)
                assert data is not None

    # Tier: 1 | Operational invariant
    def test_segment_name_pattern_is_canonical(self, segmenter_with_segments):
        """All segment names match the canonical pattern seg_NNNNN.ts."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        for name in names:
            # INV-HLS-QUIET-POLLING-001 — canonical naming enables log filtering
            assert re.match(r"^seg_\d{5}\.ts$", name), (
                f"Segment name does not match canonical pattern: {name}"
            )
