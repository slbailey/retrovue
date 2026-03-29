"""
Contract Tests: HLS Segment Ring (via HlsSegmenter integration path)

Canonical contract:
    docs/contracts/delivery_hls.md — §2 Segment Window Contract

These tests validate the segment window invariants
(INV-HLS-RING-BOUNDED-001 through INV-HLS-NO-DISK-IO-001)
through the HlsSegmenter + SegmentRing integration path.

Companion test_segment_ring_direct.py validates the same invariants directly
against SegmentRing.

Migrated from the retired hls_writer.HLSSegmenter API (commit 8cccc5b).
New API: HlsSegmenter + SegmentRing + ManifestGenerator.
"""

from __future__ import annotations

import threading

import pytest

from .conftest import (
    feed_n_segments,
    generate_segment_data,
    get_playlist,
    make_segmenter,
    make_ts_packet,
    extract_segment_indices,
    extract_segment_names,
)


# ---------------------------------------------------------------------------
# INV-HLS-RING-BOUNDED-001 — Bounded capacity with FIFO eviction
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingBounded001:
    """INV-HLS-RING-BOUNDED-001: ring never exceeds capacity; FIFO eviction."""

    def test_ring_never_exceeds_capacity(self):
        """Playlist never lists more segments than manifest_window."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 12, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        names = extract_segment_names(playlist)
        # manifest_window defaults to 5 in make_segmenter (via make_ring default)
        assert len(names) <= ring.manifest_window, (
            f"Window has {len(names)} segments, exceeds manifest_window {ring.manifest_window}"
        )

    def test_fifo_eviction_oldest_first(self):
        """Oldest segments are evicted first when ring capacity is exceeded."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 12, target_dur=2.5)

        # After 12 segments, early indices must be evicted (capacity=10)
        assert ring.get(0) is None, "seg 0 should have been evicted"
        assert ring.get(1) is None, "seg 1 should have been evicted"

        # The newest should still be present
        newest = ring.newest_index()
        assert newest is not None
        assert ring.get(newest) is not None

    def test_evicted_segment_returns_none(self):
        """Retrieval of an evicted index returns None, not an error."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 12, target_dur=2.5)

        # Index 0 is definitely evicted after 12 segments through a ring of capacity 10
        result = ring.get(0)
        assert result is None

    def test_contiguous_indices_in_window(self):
        """Segments in the manifest window form a contiguous index range."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 10, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        indices = extract_segment_indices(playlist)
        assert len(indices) >= 2, "Need at least 2 segments for contiguity check"
        for i in range(1, len(indices)):
            assert indices[i] == indices[i - 1] + 1, (
                f"Gap in manifest window: {indices[i-1]} → {indices[i]}"
            )


# ---------------------------------------------------------------------------
# INV-HLS-RING-OBSERVATION-001 — Consistent observation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingObservation001:
    """INV-HLS-RING-OBSERVATION-001: every segment in the manifest is retrievable."""

    def test_segment_available_after_production(self):
        """A segment is retrievable immediately after it completes."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        names = extract_segment_names(playlist)
        assert len(names) >= 1, "Expected at least one segment after feeding"

        # INV-HLS-RING-OBSERVATION-001 — immediately available
        newest_idx = ring.newest_index()
        assert newest_idx is not None
        data = ring.get(newest_idx)
        assert data is not None
        assert len(data.data) > 0

    def test_empty_ring_returns_none_and_empty_playlist(self):
        """Before any segments, ring returns None and get_playlist returns empty."""
        seg, ring = make_segmenter(target_ms=2000)

        # INV-HLS-RING-OBSERVATION-001 — empty ring = absence
        assert ring.get(0) is None
        assert ring.newest_index() is None
        playlist = get_playlist(ring)
        # Empty ring → no manifest or empty manifest
        assert playlist == "" or "seg_" not in playlist

    def test_window_segments_all_retrievable(self):
        """Every segment listed in the playlist can be retrieved."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 5, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        indices = extract_segment_indices(playlist)
        for idx in indices:
            # INV-HLS-RING-OBSERVATION-001 — all manifest segments retrievable
            segment = ring.get(idx)
            assert segment is not None, (
                f"Segment index {idx} listed in manifest but not retrievable"
            )
            assert len(segment.data) > 0


# ---------------------------------------------------------------------------
# INV-HLS-RING-PUSH-ATOMIC-001 — Atomic insertion
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingPushAtomic001:
    """INV-HLS-RING-PUSH-ATOMIC-001: concurrent feed+read produces no torn state."""

    def test_concurrent_read_write_no_corruption(self):
        """Concurrent feed and read operations produce no torn state."""
        seg, ring = make_segmenter(target_ms=2000)
        errors: list[str] = []

        def _feeder():
            try:
                for i in range(15):
                    data = generate_segment_data(duration=2.5, pcr_start=i * 2.5)
                    seg.feed(data)
                trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=37.5)
                seg.feed(trigger)
            except Exception as e:
                errors.append(f"feeder: {e}")

        def _reader():
            try:
                for _ in range(200):
                    playlist = get_playlist(ring)
                    if playlist and "#EXTM3U" in playlist:
                        # INV-HLS-RING-PUSH-ATOMIC-001 — no torn state
                        if not playlist.startswith("#EXTM3U"):
                            errors.append("corrupt playlist header")
                            return
                        names = extract_segment_names(playlist)
                        indices = extract_segment_indices(playlist)
                        for j in range(1, len(indices)):
                            if indices[j] != indices[j - 1] + 1:
                                errors.append(
                                    f"index gap during concurrent read: "
                                    f"{indices[j-1]} → {indices[j]}"
                                )
                                return
                        if len(names) > ring.manifest_window:
                            errors.append(
                                f"window exceeded manifest_window: {len(names)}"
                            )
                            return
            except Exception as e:
                errors.append(f"reader: {e}")

        threads = [threading.Thread(target=_feeder)]
        threads.extend(threading.Thread(target=_reader) for _ in range(2))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads), "Thread deadlocked"
        assert errors == [], f"Concurrent access errors: {errors}"


# ---------------------------------------------------------------------------
# INV-HLS-RING-WINDOW-VALID-001 — Post-insertion consistency
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingWindowValid001:
    """INV-HLS-RING-WINDOW-VALID-001: window count and index consistency after eviction."""

    def test_window_consistency_after_overflow(self):
        """After eviction, manifest count matches actual segment availability."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 10, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        names = extract_segment_names(playlist)
        indices = extract_segment_indices(playlist)

        # INV-HLS-RING-WINDOW-VALID-001 — count matches
        assert len(names) <= ring.manifest_window
        assert len(names) == len(indices)

        # All listed segments are actually retrievable
        for idx in indices:
            assert ring.get(idx) is not None, (
                f"Segment {idx} in manifest but not retrievable"
            )

        # Indices are contiguous
        if len(indices) >= 2:
            expected_count = indices[-1] - indices[0] + 1
            assert len(indices) == expected_count


# ---------------------------------------------------------------------------
# INV-HLS-RING-EVICTION-GRACE-001 — Grace margin prevents fetch race
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingEvictionGrace001:
    """INV-HLS-RING-EVICTION-GRACE-001: latest segments always retrievable."""

    def test_latest_segments_always_retrievable(self):
        """The most recent segments are always retrievable from the ring."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 8, target_dur=2.5)

        playlist = get_playlist(ring)
        assert playlist

        indices = extract_segment_indices(playlist)
        # INV-HLS-RING-EVICTION-GRACE-001 — latest segments retrievable
        for idx in indices:
            segment = ring.get(idx)
            assert segment is not None, (
                f"Segment {idx} in manifest but not retrievable — "
                f"eviction grace insufficient"
            )


# ---------------------------------------------------------------------------
# INV-HLS-NO-DISK-IO-001 — In-memory storage
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsNoDiskIo001:
    """INV-HLS-NO-DISK-IO-001: segments stored as in-memory bytes."""

    def test_segments_are_bytes_objects(self):
        """Segments returned from ring are in-memory bytes, not file paths."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        window = ring.window()
        assert len(window) > 0

        for live_seg in window:
            # INV-HLS-NO-DISK-IO-001 — in-memory bytes
            assert isinstance(live_seg.data, bytes), (
                f"Segment {live_seg.index} is {type(live_seg.data).__name__}, expected bytes"
            )

    def test_playlist_is_string(self):
        """Manifest returned by ManifestGenerator is an in-memory string."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 3, target_dur=2.5)

        playlist = get_playlist(ring)
        # INV-HLS-NO-DISK-IO-001 — in-memory string
        assert isinstance(playlist, str), (
            f"Playlist is {type(playlist).__name__}, expected str"
        )
