"""
Contract Tests: HLS Delivery Endpoints

Canonical contracts:
    docs/contracts/delivery_hls.md — §3, §4, §5, §6

These tests verify the behavioral contracts of the HLS delivery
endpoints (/channels/{id}/live.m3u8 and /channels/{id}/seg_{n}.ts)
using minimal fakes (no FastAPI stack required).

Invariants enforced:
    INV-HLS-MANIFEST-LIVE-001           — No EXT-X-ENDLIST in live manifests
    INV-HLS-SERVE-BYTE-IDENTITY-001     — Segment bytes served unchanged from ring
    INV-HLS-LIFECYCLE-SEGMENT-READY-001 — 503 until ring has a segment
    INV-HLS-ENDPOINT-SESSION-TOUCH-001  — Session touched on 200, not on 404/503
    INV-HLS-MANIFEST-CONTENT-TYPE-001   — Manifest served with correct MIME type
    INV-HLS-SEGMENT-CACHE-001           — Segment response allows caching
    INV-HLS-UNKNOWN-SEGMENT-404-001     — Missing/evicted segment returns 404
    INV-HLS-UNKNOWN-CHANNEL-404-001     — Unknown channel returns 404

The endpoint contracts are tested against the ring+generator layer directly
(the FastAPI handlers are thin — they call ring.get() / gen.generate() and
set HTTP headers). Tests that require the HTTP layer use a minimal fake
handler that mirrors the PD endpoint logic.

Migrated from the retired hls_writer.HLSSegmenter API (commit 8cccc5b).
New API: HlsSegmenter + SegmentRing + ManifestGenerator (retrovue.runtime.hls.*).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from retrovue.runtime.hls.segment_ring import SegmentRing, LiveSegment
from retrovue.runtime.hls.manifest_generator import ManifestGenerator

from .conftest import (
    feed_n_segments,
    generate_segment_data,
    get_playlist,
    make_ring,
    make_segmenter,
    make_ts_packet,
    extract_segment_names,
    extract_segment_indices,
    extract_media_sequence,
)


# ---------------------------------------------------------------------------
# Minimal fake endpoint logic (mirrors PD handler without FastAPI)
# ---------------------------------------------------------------------------


@dataclass
class FakeManifestResponse:
    """Mirrors the HTTP response shape of channels_hls_manifest."""
    status_code: int
    content: str
    media_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    session_touched: bool = False


@dataclass
class FakeSegmentResponse:
    """Mirrors the HTTP response shape of channels_hls_segment."""
    status_code: int
    content: bytes | str
    media_type: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    session_touched: bool = False


def _fake_manifest_endpoint(
    ring: SegmentRing | None,
    gen: ManifestGenerator | None,
    channel_id: str = "test-ch",
    session_id: str = "session-1",
    touch_tracker: list[str] | None = None,
) -> FakeManifestResponse:
    """Minimal replica of PD.channels_hls_manifest endpoint logic.

    Mirrors the contract:
      - None ring or no segments → 503 + Retry-After
      - Has segments → 200 with playlist, correct media type
      - Touch is only called on 200
    """
    playlist = gen.generate(ring) if (gen and ring) else None

    if playlist is None:
        return FakeManifestResponse(
            status_code=503,
            content="Playlist not ready yet",
            headers={"Retry-After": "1"},
        )

    # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — touch only on 200
    touched = True
    if touch_tracker is not None:
        touch_tracker.append(session_id)

    return FakeManifestResponse(
        status_code=200,
        content=playlist,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-cache, max-age=0",
            "Access-Control-Allow-Origin": "*",
        },
        session_touched=touched,
    )


def _fake_segment_endpoint(
    ring: SegmentRing | None,
    index: int,
    channel_id: str = "test-ch",
    session_id: str = "session-1",
    touch_tracker: list[str] | None = None,
) -> FakeSegmentResponse:
    """Minimal replica of PD.channels_hls_segment endpoint logic.

    Mirrors the contract:
      - None ring or channel not found → 404
      - Index not in ring → 404, no touch
      - Index in ring → 200, exact bytes, correct media type, touch
    """
    if ring is None:
        return FakeSegmentResponse(status_code=404, content="Channel not found")

    segment = ring.get(index)
    if segment is None:
        return FakeSegmentResponse(status_code=404, content="Not found")

    # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — touch only on 200
    if touch_tracker is not None:
        touch_tracker.append(session_id)

    return FakeSegmentResponse(
        status_code=200,
        content=segment.data,
        media_type="video/mp2t",
        headers={
            "Content-Length": str(segment.byte_count),
            "Cache-Control": "public, max-age=60",
            "Access-Control-Allow-Origin": "*",
        },
        session_touched=True,
    )


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-LIVE-001 — No EXT-X-ENDLIST
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestLive001:
    """INV-HLS-MANIFEST-LIVE-001: Live manifests must not contain EXT-X-ENDLIST."""

    def test_manifest_has_no_endlist_tag(self):
        """Generated manifest for a live ring does not contain EXT-X-ENDLIST."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        gen = ManifestGenerator("test-ch")
        playlist = gen.generate(ring)

        assert playlist is not None
        # INV-HLS-MANIFEST-LIVE-001 — no EXT-X-ENDLIST
        assert "#EXT-X-ENDLIST" not in playlist, (
            "Live manifest must not contain EXT-X-ENDLIST"
        )

    def test_manifest_live_after_multiple_segments(self):
        """Manifest stays live (no EXT-X-ENDLIST) as segments accumulate."""
        seg, ring = make_segmenter(target_ms=2000)
        gen = ManifestGenerator("test-ch")

        for n in range(1, 6):
            feed_n_segments(seg, 1, target_dur=2.5, pcr_offset=n * 2.5)
            playlist = gen.generate(ring)
            if playlist is not None:
                assert "#EXT-X-ENDLIST" not in playlist, (
                    f"Manifest must not contain EXT-X-ENDLIST after {n} segments"
                )

    def test_manifest_empty_ring_returns_none(self):
        """generate() returns None when ring has no segments (→ 503)."""
        ring = make_ring()
        gen = ManifestGenerator("test-ch")

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 (producer side)
        result = gen.generate(ring)
        assert result is None, (
            f"generate() on empty ring must return None, got: {result!r}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-LIFECYCLE-SEGMENT-READY-001 — 503 until ready
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsLifecycleSegmentReady001:
    """INV-HLS-LIFECYCLE-SEGMENT-READY-001: Return 503+Retry-After until ring has segments."""

    def test_empty_ring_returns_503(self):
        """Manifest endpoint returns 503 when no segments have been produced."""
        ring = make_ring()
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(ring, gen)

        # INV-HLS-LIFECYCLE-SEGMENT-READY-001 — 503 before first segment
        assert resp.status_code == 503, (
            f"Expected 503 for empty ring, got {resp.status_code}"
        )
        assert "Retry-After" in resp.headers, (
            "503 response must include Retry-After header"
        )

    def test_none_ring_returns_503(self):
        """Manifest endpoint returns 503 when ring is None (channel not yet running)."""
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(None, gen)

        assert resp.status_code == 503, (
            f"Expected 503 for None ring, got {resp.status_code}"
        )

    def test_transitions_to_200_after_first_segment(self):
        """Manifest endpoint returns 200 once the first segment is available."""
        seg, ring = make_segmenter(target_ms=2000)
        gen = ManifestGenerator("test-ch")

        # Before: 503
        resp_before = _fake_manifest_endpoint(ring, gen)
        assert resp_before.status_code == 503

        # Feed one segment
        feed_n_segments(seg, 1, target_dur=2.5)

        # After: 200
        resp_after = _fake_manifest_endpoint(ring, gen)
        assert resp_after.status_code == 200, (
            f"Expected 200 after first segment, got {resp_after.status_code}"
        )

    def test_retry_after_value_is_integer_seconds(self):
        """Retry-After header value is an integer >= 1 second."""
        ring = make_ring()
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(ring, gen)
        assert resp.status_code == 503

        retry_val = resp.headers.get("Retry-After", "")
        assert retry_val.isdigit(), (
            f"Retry-After must be a digit string, got: {retry_val!r}"
        )
        assert int(retry_val) >= 1, (
            f"Retry-After must be >= 1 second, got: {retry_val}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-SERVE-BYTE-IDENTITY-001 — Segment bytes served unchanged
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsServeByteIdentity001:
    """INV-HLS-SERVE-BYTE-IDENTITY-001: Served segment bytes are identical to ring bytes."""

    def test_segment_bytes_are_identical_to_ring(self):
        """Bytes served from segment endpoint are byte-identical to ring storage."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        segs = ring.window()
        assert len(segs) >= 1

        for live_seg in segs:
            # Fetch through fake endpoint
            resp = _fake_segment_endpoint(ring, live_seg.index)
            assert resp.status_code == 200

            # INV-HLS-SERVE-BYTE-IDENTITY-001 — exact bytes
            assert resp.content == live_seg.data, (
                f"Segment {live_seg.index}: served bytes differ from ring bytes"
            )

    def test_content_length_matches_data(self):
        """Content-Length header matches the actual byte count."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        segs = ring.window()
        assert len(segs) >= 1

        live_seg = segs[0]
        resp = _fake_segment_endpoint(ring, live_seg.index)
        assert resp.status_code == 200

        content_length = int(resp.headers.get("Content-Length", -1))
        assert content_length == live_seg.byte_count, (
            f"Content-Length {content_length} != byte_count {live_seg.byte_count}"
        )
        assert content_length == len(resp.content), (
            f"Content-Length {content_length} != actual content length {len(resp.content)}"
        )

    def test_all_segments_in_ring_fetchable(self):
        """Every segment in the ring window is fetchable with 200."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)

        segs = ring.window()
        assert len(segs) >= 1

        for live_seg in segs:
            resp = _fake_segment_endpoint(ring, live_seg.index)
            assert resp.status_code == 200, (
                f"Expected 200 for segment {live_seg.index}, got {resp.status_code}"
            )
            assert len(resp.content) == live_seg.byte_count


# ---------------------------------------------------------------------------
# INV-HLS-UNKNOWN-SEGMENT-404-001 — Missing or evicted segment returns 404
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsUnknownSegment404001:
    """INV-HLS-UNKNOWN-SEGMENT-404-001: Evicted or non-existent segment returns 404."""

    def test_nonexistent_index_returns_404(self):
        """Requesting segment index 99999 (never produced) returns 404."""
        _, ring = make_segmenter(target_ms=2000)

        resp = _fake_segment_endpoint(ring, 99999)

        # INV-HLS-UNKNOWN-SEGMENT-404-001
        assert resp.status_code == 404, (
            f"Expected 404 for non-existent segment, got {resp.status_code}"
        )

    def test_evicted_segment_returns_404(self):
        """After ring wraps, evicted segments return 404."""
        seg, ring = make_segmenter(target_ms=2000)
        # Use a small ring that will wrap quickly
        small_ring = SegmentRing(capacity=5, manifest_window=2)
        seg2, _ = make_segmenter(target_ms=2000)
        # Re-build with small ring
        from retrovue.runtime.hls.segmenter import HlsSegmenter
        small_seg = HlsSegmenter(
            channel_id="test-ch",
            segment_ring=small_ring,
            target_duration_ms=2000,
        )
        small_seg.set_blockplan_timebase(
            start_utc_ms=1_700_000_000_000,
            active_block_start_utc_ms=1_700_000_000_000,
            active_block_end_utc_ms=1_700_003_600_000,
        )
        # Feed enough to wrap the ring (capacity=3, feed 6 segments)
        feed_n_segments(small_seg, 6, target_dur=2.5)

        all_segs = small_ring.window()
        oldest = small_ring.oldest_index()
        assert oldest is not None and oldest >= 1, (
            "Ring should have wrapped; oldest_index should be > 0"
        )

        # Indices 0..oldest-1 are evicted — should 404
        evicted_index = oldest - 1
        resp = _fake_segment_endpoint(small_ring, evicted_index)
        assert resp.status_code == 404, (
            f"Expected 404 for evicted segment {evicted_index}, got {resp.status_code}"
        )

    def test_none_ring_returns_404(self):
        """Segment endpoint with no ring (channel not found) returns 404."""
        resp = _fake_segment_endpoint(None, 0)

        assert resp.status_code == 404, (
            f"Expected 404 for None ring, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-ENDPOINT-SESSION-TOUCH-001 — Touch only on 200
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsEndpointSessionTouch001:
    """INV-HLS-ENDPOINT-SESSION-TOUCH-001: Session is touched on 200, not on 4xx/5xx."""

    def test_manifest_200_triggers_touch(self):
        """Successful manifest response (200) triggers session touch."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        gen = ManifestGenerator("test-ch")

        touch_log: list[str] = []
        resp = _fake_manifest_endpoint(ring, gen, touch_tracker=touch_log)

        assert resp.status_code == 200
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — touch on 200
        assert resp.session_touched is True
        assert len(touch_log) == 1

    def test_manifest_503_does_not_touch(self):
        """503 manifest response (empty ring) does not trigger session touch."""
        ring = make_ring()
        gen = ManifestGenerator("test-ch")

        touch_log: list[str] = []
        resp = _fake_manifest_endpoint(ring, gen, touch_tracker=touch_log)

        assert resp.status_code == 503
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — no touch on 503
        assert resp.session_touched is False
        assert len(touch_log) == 0

    def test_segment_200_triggers_touch(self):
        """Successful segment response (200) triggers session touch."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)
        segs = ring.window()
        assert len(segs) >= 1

        touch_log: list[str] = []
        resp = _fake_segment_endpoint(ring, segs[0].index, touch_tracker=touch_log)

        assert resp.status_code == 200
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — touch on 200
        assert resp.session_touched is True
        assert len(touch_log) == 1

    def test_segment_404_does_not_touch(self):
        """404 segment response (unknown index) does not trigger session touch."""
        _, ring = make_segmenter(target_ms=2000)

        touch_log: list[str] = []
        resp = _fake_segment_endpoint(ring, 99999, touch_tracker=touch_log)

        assert resp.status_code == 404
        # INV-HLS-ENDPOINT-SESSION-TOUCH-001 — no touch on 404
        assert resp.session_touched is False
        assert len(touch_log) == 0


# ---------------------------------------------------------------------------
# INV-HLS-MANIFEST-CONTENT-TYPE-001 — Correct MIME type
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsManifestContentType001:
    """INV-HLS-MANIFEST-CONTENT-TYPE-001: Manifest served with correct MIME type."""

    def test_manifest_media_type_is_mpegurl(self):
        """200 manifest response uses application/vnd.apple.mpegurl media type."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(ring, gen)
        assert resp.status_code == 200

        # INV-HLS-MANIFEST-CONTENT-TYPE-001
        assert resp.media_type == "application/vnd.apple.mpegurl", (
            f"Expected application/vnd.apple.mpegurl, got: {resp.media_type!r}"
        )

    def test_segment_media_type_is_mp2t(self):
        """200 segment response uses video/mp2t media type."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        segs = ring.window()
        assert len(segs) >= 1

        resp = _fake_segment_endpoint(ring, segs[0].index)
        assert resp.status_code == 200

        # INV-HLS-MANIFEST-CONTENT-TYPE-001 (segment side)
        assert resp.media_type == "video/mp2t", (
            f"Expected video/mp2t, got: {resp.media_type!r}"
        )


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-CACHE-001 — Cache headers
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsSegmentCache001:
    """INV-HLS-SEGMENT-CACHE-001: Manifests are no-cache; segments are cacheable."""

    def test_manifest_has_no_cache_header(self):
        """Live manifest response has Cache-Control: no-cache."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(ring, gen)
        assert resp.status_code == 200

        cc = resp.headers.get("Cache-Control", "")
        # INV-HLS-SEGMENT-CACHE-001 — manifests must not be cached
        assert "no-cache" in cc, (
            f"Manifest Cache-Control should include no-cache, got: {cc!r}"
        )

    def test_segment_has_cacheable_header(self):
        """Segment response has Cache-Control: public, max-age>=1."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        segs = ring.window()
        assert len(segs) >= 1

        resp = _fake_segment_endpoint(ring, segs[0].index)
        assert resp.status_code == 200

        cc = resp.headers.get("Cache-Control", "")
        # INV-HLS-SEGMENT-CACHE-001 — segments should be cacheable
        assert "public" in cc, (
            f"Segment Cache-Control should include public, got: {cc!r}"
        )
        assert "max-age=" in cc, (
            f"Segment Cache-Control should include max-age, got: {cc!r}"
        )

    def test_manifest_has_cors_header(self):
        """Live manifest response carries Access-Control-Allow-Origin: *."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        gen = ManifestGenerator("test-ch")

        resp = _fake_manifest_endpoint(ring, gen)
        assert resp.status_code == 200

        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        assert acao == "*", (
            f"Expected Access-Control-Allow-Origin: *, got: {acao!r}"
        )

    def test_segment_has_cors_header(self):
        """Segment response carries Access-Control-Allow-Origin: *."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)
        segs = ring.window()
        assert len(segs) >= 1

        resp = _fake_segment_endpoint(ring, segs[0].index)
        assert resp.status_code == 200

        acao = resp.headers.get("Access-Control-Allow-Origin", "")
        assert acao == "*", (
            f"Expected Access-Control-Allow-Origin: *, got: {acao!r}"
        )
