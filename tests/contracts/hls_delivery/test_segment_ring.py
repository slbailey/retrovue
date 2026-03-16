"""
Contract Tests: HLS Segment Ring

Canonical contract:
    docs/contracts/delivery_hls.md — §2 Segment Window Contract

Test matrix:
    docs/contracts/TEST-MATRIX-HLS-DELIVERY.md — Segment Ring

These tests enforce the segment window invariants
(INV-HLS-RING-BOUNDED-001 through INV-HLS-NO-DISK-IO-001)
using the HLSSegmenter's public API.

Every test references the specific invariant(s) it validates.
"""

from __future__ import annotations

import re
import threading
import time
from unittest.mock import patch

import pytest

from retrovue.streaming.hls_writer import HLSSegmenter, TS_SYNC_BYTE, TS_PACKET_SIZE

from .conftest import (
    feed_n_segments,
    generate_segment_data,
    make_ts_packet,
    extract_segment_names,
    extract_segment_indices,
    extract_media_sequence,
)


# ---------------------------------------------------------------------------
# INV-HLS-RING-BOUNDED-001 — Bounded capacity with FIFO eviction
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingBounded001:
    """INV-HLS-RING-BOUNDED-001"""

    # Tier: 1 | Structural invariant
    def test_ring_never_exceeds_capacity(self):
        """Playlist never lists more segments than max_segments."""
        max_seg = 5
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=max_seg)
        seg.start()

        feed_n_segments(seg, 12, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        # INV-HLS-RING-BOUNDED-001 — at most max_segments in window
        assert len(names) <= max_seg, (
            f"Window has {len(names)} segments, exceeds capacity {max_seg}"
        )

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_fifo_eviction_order(self):
        """Oldest segments are evicted first when capacity is exceeded."""
        max_seg = 3
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=max_seg)
        seg.start()

        feed_n_segments(seg, 6, target_dur=2.5)

        # INV-HLS-RING-BOUNDED-001 — segments 0, 1, 2 should be evicted
        assert seg.get_segment("seg_00000.ts") is None, "seg_00000.ts should be evicted"
        assert seg.get_segment("seg_00001.ts") is None, "seg_00001.ts should be evicted"
        assert seg.get_segment("seg_00002.ts") is None, "seg_00002.ts should be evicted"

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_evicted_segment_returns_none(self):
        """Retrieval of an evicted segment returns None, not an error."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=3)
        seg.start()

        feed_n_segments(seg, 5, target_dur=2.5)

        # INV-HLS-RING-BOUNDED-001 — evicted = absent
        result = seg.get_segment("seg_00000.ts")
        assert result is None

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_contiguous_indices_in_window(self):
        """Segments in the window form a contiguous index range."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        feed_n_segments(seg, 10, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        indices = extract_segment_indices(playlist)
        # INV-HLS-RING-BOUNDED-001 — contiguous range
        for i in range(1, len(indices)):
            assert indices[i] == indices[i - 1] + 1, (
                f"Gap in window: {indices[i-1]} → {indices[i]}"
            )

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-RING-OBSERVATION-001 — Consistent observation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingObservation001:
    """INV-HLS-RING-OBSERVATION-001"""

    # Tier: 1 | Structural invariant
    def test_segment_available_after_production(self):
        """A segment is retrievable immediately after it completes."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        feed_n_segments(seg, 1, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        assert len(names) >= 1

        # INV-HLS-RING-OBSERVATION-001 — immediately available
        data = seg.get_segment(names[0])
        assert data is not None
        assert len(data) > 0

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_empty_ring_returns_none(self):
        """Before any segments, all retrievals return None."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        # INV-HLS-RING-OBSERVATION-001 — empty ring = absence
        assert seg.get_playlist() is None
        assert seg.get_segment("seg_00000.ts") is None

        seg.stop()

    # Tier: 1 | Structural invariant
    def test_window_segments_all_retrievable(self):
        """Every segment listed in the playlist can be retrieved."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        feed_n_segments(seg, 5, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        for name in extract_segment_names(playlist):
            # INV-HLS-RING-OBSERVATION-001 — all listed segments retrievable
            data = seg.get_segment(name)
            assert data is not None, f"Segment {name} listed in playlist but not retrievable"
            assert len(data) > 0

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-RING-PUSH-ATOMIC-001 — Atomic insertion
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingPushAtomic001:
    """INV-HLS-RING-PUSH-ATOMIC-001"""

    # Tier: 3 | Runtime behavior invariant
    def test_concurrent_read_write_no_corruption(self):
        """Concurrent feed and read operations produce no torn state."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        errors: list[str] = []
        stop_event = threading.Event()

        def _feeder():
            try:
                for i in range(15):
                    if stop_event.is_set():
                        break
                    data = generate_segment_data(duration=2.5, pcr_start=i * 2.5)
                    seg.feed(data)
                trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=37.5)
                seg.feed(trigger)
            except Exception as e:
                errors.append(f"feeder: {e}")

        def _reader():
            try:
                for _ in range(100):
                    if stop_event.is_set():
                        break
                    playlist = seg.get_playlist()
                    if playlist is not None:
                        # INV-HLS-RING-PUSH-ATOMIC-001 — no torn state
                        if not playlist.startswith("#EXTM3U"):
                            errors.append(f"corrupt playlist header")
                            return
                        names = extract_segment_names(playlist)
                        indices = extract_segment_indices(playlist)
                        # Check contiguity
                        for j in range(1, len(indices)):
                            if indices[j] != indices[j - 1] + 1:
                                errors.append(
                                    f"index gap during concurrent read: "
                                    f"{indices[j-1]} → {indices[j]}"
                                )
                                return
                        # Check capacity bound
                        if len(names) > 5:
                            errors.append(f"window exceeded capacity: {len(names)}")
                            return
                    time.sleep(0.001)
            except Exception as e:
                errors.append(f"reader: {e}")

        threads = [
            threading.Thread(target=_feeder),
            threading.Thread(target=_reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads), "Thread deadlocked"
        assert errors == [], f"Concurrent access errors: {errors}"

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-RING-WINDOW-VALID-001 — Post-insertion consistency
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingWindowValid001:
    """INV-HLS-RING-WINDOW-VALID-001"""

    # Tier: 1 | Structural invariant
    def test_window_consistency_after_overflow(self):
        """After eviction, window count matches actual segment availability."""
        max_seg = 4
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=max_seg)
        seg.start()

        feed_n_segments(seg, 10, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        indices = extract_segment_indices(playlist)

        # INV-HLS-RING-WINDOW-VALID-001 — count matches
        assert len(names) <= max_seg
        assert len(names) == len(indices)

        # All listed segments are actually retrievable
        for name in names:
            assert seg.get_segment(name) is not None

        # Indices are contiguous
        if len(indices) >= 2:
            expected_count = indices[-1] - indices[0] + 1
            assert len(indices) == expected_count

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-RING-EVICTION-GRACE-001 — Grace margin prevents fetch race
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingEvictionGrace001:
    """INV-HLS-RING-EVICTION-GRACE-001"""

    # Tier: 2 | Configuration invariant
    def test_latest_segments_always_retrievable(self):
        """The most recent segments are always retrievable from the window."""
        max_seg = 5
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=max_seg)
        seg.start()

        feed_n_segments(seg, 8, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        names = extract_segment_names(playlist)
        # INV-HLS-RING-EVICTION-GRACE-001 — latest segments retrievable
        for name in names:
            data = seg.get_segment(name)
            assert data is not None, (
                f"Segment {name} in playlist but not retrievable — "
                f"eviction grace insufficient"
            )

        seg.stop()


# ---------------------------------------------------------------------------
# INV-HLS-NO-DISK-IO-001 — In-memory storage
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsNoDiskIo001:
    """INV-HLS-NO-DISK-IO-001"""

    # Tier: 1 | Structural invariant
    def test_segments_are_bytes_objects(self, segmenter_with_segments):
        """Segments are returned as in-memory bytes, not file paths or handles."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        assert playlist is not None

        for name in extract_segment_names(playlist):
            data = seg.get_segment(name)
            # INV-HLS-NO-DISK-IO-001 — in-memory bytes
            assert isinstance(data, bytes), (
                f"Segment {name} is {type(data).__name__}, expected bytes"
            )

    # Tier: 1 | Structural invariant
    def test_playlist_is_string(self, segmenter_with_segments):
        """Playlist is returned as an in-memory string, not a file path."""
        seg = segmenter_with_segments
        playlist = seg.get_playlist()
        # INV-HLS-NO-DISK-IO-001 — in-memory string
        assert isinstance(playlist, str), (
            f"Playlist is {type(playlist).__name__}, expected str"
        )
