"""
Contract Tests: SegmentRing (Direct)

Canonical contract:
    docs/contracts/delivery_hls.md — §2 Segment Window Contract

These tests exercise SegmentRing and LiveSegment directly, validating
the storage layer independently of the HLSSegmenter pipeline.

The companion test_segment_ring.py validates the same invariants through
the HLSSegmenter's public API (integration path).
"""

from __future__ import annotations

import threading

import pytest

from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seg(index: int, *, data: bytes = b"\x47" * 188, duration_ms: int = 6000,
         wall_clock_ms: int = 0, channel_id: str = "test-ch",
         discontinuity: bool = False) -> LiveSegment:
    """Build a LiveSegment with sensible defaults."""
    return LiveSegment(
        channel_id=channel_id,
        index=index,
        wall_clock_start_utc_ms=wall_clock_ms,
        duration_ms=duration_ms,
        byte_count=len(data),
        data=data,
        discontinuity=discontinuity,
    )


# ---------------------------------------------------------------------------
# LiveSegment structural invariants
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestLiveSegmentStructure:
    """LiveSegment construction-time invariants."""

    def test_frozen_after_construction(self):
        """LiveSegment is immutable (frozen dataclass)."""
        seg = _seg(0)
        with pytest.raises(AttributeError):
            seg.index = 99  # type: ignore[misc]

    def test_data_must_be_bytes(self):
        """INV-HLS-NO-DISK-IO-001: data field rejects non-bytes."""
        with pytest.raises(TypeError, match="INV-HLS-NO-DISK-IO-001"):
            LiveSegment(
                channel_id="ch", index=0, wall_clock_start_utc_ms=0,
                duration_ms=1000, byte_count=3, data="abc",  # type: ignore[arg-type]
                discontinuity=False,
            )

    def test_byte_count_must_match_data_length(self):
        """INV-HLS-SEGMENT-IMMUTABLE-001: byte_count == len(data)."""
        with pytest.raises(ValueError, match="INV-HLS-SEGMENT-IMMUTABLE-001"):
            LiveSegment(
                channel_id="ch", index=0, wall_clock_start_utc_ms=0,
                duration_ms=1000, byte_count=999, data=b"\x47" * 188,
                discontinuity=False,
            )

    def test_index_must_be_nonnegative_int(self):
        """INV-HLS-SEGMENT-IDENTITY-001: index >= 0."""
        with pytest.raises(ValueError, match="INV-HLS-SEGMENT-IDENTITY-001"):
            _seg(-1)

    def test_duration_must_be_positive_int(self):
        """INV-HLS-SEGMENT-DURATION-BOUNDS-001: duration_ms > 0."""
        with pytest.raises(ValueError, match="INV-HLS-SEGMENT-DURATION-BOUNDS-001"):
            _seg(0, duration_ms=0)

    def test_wallclock_must_be_int(self):
        """INV-HLS-SEGMENT-WALLCLOCK-001: wall_clock_start_utc_ms must be int."""
        with pytest.raises(TypeError, match="INV-HLS-SEGMENT-WALLCLOCK-001"):
            LiveSegment(
                channel_id="ch", index=0,
                wall_clock_start_utc_ms=1000.5,  # type: ignore[arg-type]
                duration_ms=1000, byte_count=188, data=b"\x47" * 188,
            )


# ---------------------------------------------------------------------------
# INV-HLS-RING-BOUNDED-001 — Bounded capacity with FIFO eviction
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingBounded001Direct:
    """INV-HLS-RING-BOUNDED-001 — direct SegmentRing tests."""

    def test_ring_never_exceeds_capacity(self):
        """Ring holds at most capacity segments."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        for i in range(10):
            ring.push(_seg(i))

        assert ring.count() == 5

    def test_fifo_eviction_oldest_first(self):
        """Oldest segment is evicted when capacity exceeded."""
        ring = SegmentRing(capacity=3, manifest_window=1)
        for i in range(5):
            ring.push(_seg(i))

        assert ring.get(0) is None
        assert ring.get(1) is None
        assert ring.get(2) is not None
        assert ring.get(3) is not None
        assert ring.get(4) is not None

    def test_evicted_segment_returns_none(self):
        """Retrieval of evicted index returns None."""
        ring = SegmentRing(capacity=3, manifest_window=1)
        for i in range(6):
            ring.push(_seg(i))

        assert ring.get(0) is None
        assert ring.get(1) is None
        assert ring.get(2) is None

    def test_contiguous_indices(self):
        """Window always has contiguous indices."""
        ring = SegmentRing(capacity=4, manifest_window=2)
        for i in range(8):
            ring.push(_seg(i))

        window = ring.window()
        for j in range(1, len(window)):
            assert window[j].index == window[j - 1].index + 1


# ---------------------------------------------------------------------------
# INV-HLS-RING-OBSERVATION-001 — Consistent observation
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingObservation001Direct:
    """INV-HLS-RING-OBSERVATION-001 — direct SegmentRing tests."""

    def test_segment_available_immediately_after_push(self):
        """Segment is retrievable right after push."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        seg = _seg(0)
        ring.push(seg)

        result = ring.get(0)
        assert result is not None
        assert result.data == seg.data

    def test_empty_ring_returns_none(self):
        """Empty ring returns None for any index."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        assert ring.get(0) is None
        assert ring.get(99) is None

    def test_empty_ring_window_is_empty(self):
        """Empty ring window() returns empty list."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        assert ring.window() == []

    def test_empty_ring_indices_are_none(self):
        """Empty ring oldest/newest return None."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        assert ring.oldest_index() is None
        assert ring.newest_index() is None

    def test_window_returns_copy(self):
        """window() returns a snapshot, not a live view."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        ring.push(_seg(0))

        w1 = ring.window()
        ring.push(_seg(1))
        w2 = ring.window()

        assert len(w1) == 1
        assert len(w2) == 2

    def test_push_only_mutation(self):
        """Ring has no delete/update/reorder — only push."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        # Verify no delete/remove/clear/pop methods exist
        assert not hasattr(ring, "delete")
        assert not hasattr(ring, "remove")
        assert not hasattr(ring, "pop")

    def test_window_ordered_by_index(self):
        """window() returns segments in ascending index order."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        # Push out of order (shouldn't happen in practice, but tests ordering)
        ring.push(_seg(2))
        ring.push(_seg(0))
        ring.push(_seg(1))

        window = ring.window()
        indices = [s.index for s in window]
        assert indices == sorted(indices)


# ---------------------------------------------------------------------------
# INV-HLS-RING-PUSH-ATOMIC-001 — Atomic insertion
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingPushAtomic001Direct:
    """INV-HLS-RING-PUSH-ATOMIC-001 — direct SegmentRing tests."""

    def test_concurrent_push_and_read(self):
        """Concurrent writer + readers see no torn state."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        errors: list[str] = []

        def _writer():
            try:
                for i in range(50):
                    ring.push(_seg(i))
            except Exception as e:
                errors.append(f"writer: {e}")

        def _reader():
            try:
                for _ in range(200):
                    window = ring.window()
                    if len(window) > 5:
                        errors.append(f"window exceeded capacity: {len(window)}")
                        return
                    indices = [s.index for s in window]
                    for j in range(1, len(indices)):
                        if indices[j] != indices[j - 1] + 1:
                            errors.append(f"gap: {indices[j-1]} → {indices[j]}")
                            return
                    # Also try get()
                    for s in window:
                        result = ring.get(s.index)
                        if result is None:
                            # May have been evicted between window() and get()
                            pass
            except Exception as e:
                errors.append(f"reader: {e}")

        threads = [threading.Thread(target=_writer)]
        threads.extend(threading.Thread(target=_reader) for _ in range(3))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not any(t.is_alive() for t in threads), "Deadlock"
        assert errors == [], f"Concurrent errors: {errors}"

    def test_concurrent_push_no_capacity_overflow(self):
        """Even under concurrent pressure, capacity is never exceeded."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        errors: list[str] = []
        max_observed = [0]

        def _writer():
            for i in range(100):
                ring.push(_seg(i))

        def _observer():
            for _ in range(500):
                c = ring.count()
                if c > 5:
                    errors.append(f"count={c}")
                if c > max_observed[0]:
                    max_observed[0] = c

        t1 = threading.Thread(target=_writer)
        t2 = threading.Thread(target=_observer)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        assert errors == []
        assert max_observed[0] <= 5


# ---------------------------------------------------------------------------
# INV-HLS-RING-WINDOW-VALID-001 — Post-insertion consistency
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingWindowValid001Direct:
    """INV-HLS-RING-WINDOW-VALID-001 — direct SegmentRing tests."""

    def test_consistency_after_push(self):
        """newest - oldest + 1 == count after every push."""
        ring = SegmentRing(capacity=4, manifest_window=2)
        for i in range(10):
            ring.push(_seg(i))

            oldest = ring.oldest_index()
            newest = ring.newest_index()
            count = ring.count()

            assert oldest is not None
            assert newest is not None
            assert newest - oldest + 1 == count
            assert count <= 4

    def test_count_matches_window_length(self):
        """count() always equals len(window())."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        for i in range(12):
            ring.push(_seg(i))
            assert ring.count() == len(ring.window())


# ---------------------------------------------------------------------------
# INV-HLS-RING-EVICTION-GRACE-001 — Grace margin prevents fetch race
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRingEvictionGrace001Direct:
    """INV-HLS-RING-EVICTION-GRACE-001 — direct SegmentRing tests."""

    def test_capacity_must_exceed_manifest_window_plus_one(self):
        """Configuration with insufficient grace is rejected."""
        with pytest.raises(ValueError, match="INV-HLS-RING-EVICTION-GRACE-001"):
            SegmentRing(capacity=3, manifest_window=3)

        with pytest.raises(ValueError, match="INV-HLS-RING-EVICTION-GRACE-001"):
            SegmentRing(capacity=4, manifest_window=3)

    def test_valid_capacity_accepted(self):
        """Configuration with sufficient grace succeeds."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        assert ring.capacity == 5
        assert ring.manifest_window == 3

    def test_grace_segments_survive_eviction(self):
        """Segments within grace margin are retained after manifest window advances."""
        # capacity=7, manifest_window=5 → grace of 1
        ring = SegmentRing(capacity=7, manifest_window=5)

        for i in range(10):
            ring.push(_seg(i))

        # Ring has segments 3..9 (7 segments)
        # Manifest would show 5..9 (5 segments)
        # Grace: segments 3 and 4 still retrievable
        assert ring.get(3) is not None
        assert ring.get(4) is not None
        assert ring.get(2) is None  # evicted


# ---------------------------------------------------------------------------
# INV-HLS-NO-DISK-IO-001 — In-memory storage
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsNoDiskIo001Direct:
    """INV-HLS-NO-DISK-IO-001 — direct SegmentRing tests."""

    def test_segment_data_is_bytes(self):
        """Stored segment data is in-memory bytes."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        ring.push(_seg(0))

        result = ring.get(0)
        assert result is not None
        assert isinstance(result.data, bytes)

    def test_window_returns_bytes_segments(self):
        """All segments in window have bytes data."""
        ring = SegmentRing(capacity=5, manifest_window=3)
        for i in range(3):
            ring.push(_seg(i))

        for seg in ring.window():
            assert isinstance(seg.data, bytes)
            assert isinstance(seg, LiveSegment)
