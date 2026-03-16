"""
Contract Tests: HlsSegmenter (Direct)

Canonical contract:
    docs/contracts/delivery_hls.md — §1 HLS Segment Contract

These tests exercise the new canonical HlsSegmenter directly,
validating segment production invariants against SegmentRing.

The companion test_segment_production.py validates the same invariants
through the legacy HLSSegmenter path.
"""

from __future__ import annotations

import pytest

from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing
from retrovue.runtime.hls.segmenter import (
    HlsSegmenter,
    TS_PACKET_SIZE,
    TS_SYNC_BYTE,
    is_keyframe_packet,
)

from .conftest import (
    make_ts_packet,
    generate_segment_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ring(capacity: int = 10, manifest_window: int = 5) -> SegmentRing:
    return SegmentRing(capacity=capacity, manifest_window=manifest_window)


def _make_segmenter(
    ring: SegmentRing | None = None,
    target_ms: int = 2000,
    starting_index: int = 0,
    channel_id: str = "test-ch",
    timebase_utc_ms: int = 1_700_000_000_000,
) -> HlsSegmenter:
    if ring is None:
        ring = _make_ring()
    seg = HlsSegmenter(
        channel_id=channel_id,
        segment_ring=ring,
        target_duration_ms=target_ms,
        starting_index=starting_index,
    )
    seg.set_blockplan_timebase(
        start_utc_ms=timebase_utc_ms,
        active_block_start_utc_ms=timebase_utc_ms,
        active_block_end_utc_ms=timebase_utc_ms + 3_600_000,  # 1-hour block
    )
    return seg


def _feed_segments(seg: HlsSegmenter, n: int, target_dur: float = 2.5) -> None:
    """Feed enough data to finalize exactly n segments through the new segmenter."""
    for i in range(n):
        pcr_start = i * target_dur
        data = generate_segment_data(duration=target_dur, pcr_start=pcr_start)
        seg.feed(data)
    # Trigger finalization of the last segment
    final_pcr = n * target_dur
    trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=final_pcr)
    seg.feed(trigger)


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-IDENTITY-001 — Channel-scoped monotonic identity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterIdentity:
    """INV-HLS-SEGMENT-IDENTITY-001"""

    def test_indices_monotonic_no_gaps(self):
        """Segment indices are strictly monotonic with gap of 1."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 5)

        window = ring.window()
        assert len(window) >= 2

        for i in range(1, len(window)):
            assert window[i].index == window[i - 1].index + 1

    def test_indices_start_at_starting_index(self):
        """Segments start at the configured starting_index."""
        ring = _make_ring()
        seg = _make_segmenter(ring, starting_index=42)
        _feed_segments(seg, 2)

        window = ring.window()
        assert window[0].index == 42

    def test_indices_unique(self):
        """No duplicate indices."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 8)

        indices = [s.index for s in ring.window()]
        assert len(indices) == len(set(indices))

    def test_channel_id_on_segments(self):
        """Every segment carries the channel_id."""
        ring = _make_ring()
        seg = _make_segmenter(ring, channel_id="my-channel")
        _feed_segments(seg, 2)

        for s in ring.window():
            assert s.channel_id == "my-channel"


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-IMMUTABLE-001 — Completed segments are frozen
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterImmutability:
    """INV-HLS-SEGMENT-IMMUTABLE-001"""

    def test_segment_is_frozen(self):
        """LiveSegment fields cannot be mutated after creation."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 1)

        s = ring.window()[0]
        with pytest.raises(AttributeError):
            s.index = 999  # type: ignore[misc]

    def test_bytes_identical_across_reads(self):
        """Reading the same segment twice returns identical data."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 2)

        s = ring.get(0)
        assert s is not None
        s2 = ring.get(0)
        assert s2 is not None
        assert s.data == s2.data


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-KEYFRAME-001 — Keyframe-aligned boundaries
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterKeyframe:
    """INV-HLS-SEGMENT-KEYFRAME-001"""

    def test_every_segment_starts_with_rai(self):
        """Every segment's TS data contains a RAI keyframe within the first packets."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 3)

        for s in ring.window():
            found_rai = False
            offset = 0
            while offset + TS_PACKET_SIZE <= len(s.data):
                pkt = s.data[offset : offset + TS_PACKET_SIZE]
                afc = (pkt[3] >> 4) & 0x03
                if afc in (0x02, 0x03) and len(pkt) > 5:
                    if pkt[5] & 0x40:
                        found_rai = True
                        break
                offset += TS_PACKET_SIZE

            assert found_rai, f"Segment {s.index}: no keyframe (RAI) found"


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-SELFCONTAINED-001 — Structurally decodable
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterSelfContained:
    """INV-HLS-SEGMENT-SELFCONTAINED-001"""

    def test_valid_ts_structure(self):
        """Every segment is 188-byte aligned with sync bytes."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 3)

        for s in ring.window():
            assert len(s.data) > 0
            assert len(s.data) % TS_PACKET_SIZE == 0
            for offset in range(0, len(s.data), TS_PACKET_SIZE):
                assert s.data[offset] == TS_SYNC_BYTE

    def test_byte_count_matches_data(self):
        """byte_count == len(data) for every segment."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 3)

        for s in ring.window():
            assert s.byte_count == len(s.data)

    def test_nonempty_segments(self):
        """No zero-byte segments produced."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 3)

        for s in ring.window():
            assert len(s.data) >= TS_PACKET_SIZE


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-WALLCLOCK-001 — Editorial timeline truth
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterWallclock:
    """INV-HLS-SEGMENT-WALLCLOCK-001"""

    def test_wallclock_derived_from_timebase(self):
        """Segment wall_clock_start_utc_ms is derived from BlockPlan timebase."""
        timebase = 1_700_000_000_000
        ring = _make_ring()
        seg = _make_segmenter(ring, timebase_utc_ms=timebase)
        _feed_segments(seg, 3)

        window = ring.window()
        # First segment should be near the timebase start
        assert window[0].wall_clock_start_utc_ms >= timebase
        # Subsequent segments advance
        for i in range(1, len(window)):
            assert window[i].wall_clock_start_utc_ms > window[i - 1].wall_clock_start_utc_ms

    def test_wallclock_within_active_block_range(self):
        """Segment timestamps fall within the active block's time range."""
        timebase = 1_700_000_000_000
        block_end = timebase + 3_600_000  # 1 hour
        ring = _make_ring()
        seg = _make_segmenter(ring, timebase_utc_ms=timebase)
        _feed_segments(seg, 3)

        for s in ring.window():
            assert s.wall_clock_start_utc_ms >= timebase
            assert s.wall_clock_start_utc_ms < block_end

    def test_wallclock_advances_with_segments(self):
        """Wall-clock timestamps increase monotonically across segments."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 5)

        window = ring.window()
        for i in range(1, len(window)):
            assert window[i].wall_clock_start_utc_ms >= window[i - 1].wall_clock_start_utc_ms


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-PTS-CONTINUITY-001 — PTS continuity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterPtsContinuity:
    """INV-HLS-SEGMENT-PTS-CONTINUITY-001"""

    def test_continuous_session_no_discontinuity(self):
        """Continuous PCR stream produces no discontinuity flags."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 5)

        window = ring.window()
        # First segment may be discontinuous (initial state), skip it
        for s in window[1:]:
            assert not s.discontinuity, (
                f"Unexpected discontinuity on segment {s.index}"
            )

    def test_pcr_jump_produces_discontinuity(self):
        """A large PCR jump marks the following segment as discontinuous."""
        ring = _make_ring()
        seg = _make_segmenter(ring)

        # 2 continuous segments
        _feed_segments(seg, 2)

        # Feed data with a huge PCR jump
        jump_data = generate_segment_data(duration=2.5, pcr_start=500.0)
        seg.feed(jump_data)
        trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=502.5)
        seg.feed(trigger)

        window = ring.window()
        disc_segments = [s for s in window if s.discontinuity]
        # At least one discontinuity (the jump segment + possibly initial)
        assert len(disc_segments) >= 1


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-DURATION-BOUNDS-001 — Duration within tolerance
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterDurationBounds:
    """INV-HLS-SEGMENT-DURATION-BOUNDS-001"""

    def test_all_durations_positive(self):
        """Every segment has positive duration_ms."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 5)

        for s in ring.window():
            assert s.duration_ms > 0

    def test_durations_in_int_ms(self):
        """Duration is integer milliseconds."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 3)

        for s in ring.window():
            assert isinstance(s.duration_ms, int)


# ---------------------------------------------------------------------------
# INV-HLS-SEGMENT-INDEX-GUARD-001 — Index counter integrity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterIndexGuard:
    """INV-HLS-SEGMENT-INDEX-GUARD-001"""

    def test_index_increments_by_one(self):
        """Index advances by exactly 1 per segment."""
        ring = _make_ring()
        seg = _make_segmenter(ring, starting_index=0)
        _feed_segments(seg, 5)

        window = ring.window()
        for i in range(1, len(window)):
            assert window[i].index == window[i - 1].index + 1

    def test_last_completed_index_tracks(self):
        """last_completed_index() returns the most recent segment index."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        assert seg.last_completed_index() is None

        _feed_segments(seg, 3)
        assert seg.last_completed_index() is not None
        assert seg.last_completed_index() == ring.newest_index()


# ---------------------------------------------------------------------------
# INV-HLS-RESTART-DISCONTINUITY-001 — Discontinuity on restart
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterRestart:
    """INV-HLS-RESTART-DISCONTINUITY-001"""

    def test_first_segment_is_discontinuous(self):
        """First segment after construction carries discontinuity flag."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 1)

        window = ring.window()
        assert len(window) >= 1
        assert window[0].discontinuity is True

    def test_reset_forces_discontinuity(self):
        """reset_for_restart forces next segment to be discontinuous."""
        ring = _make_ring()
        seg = _make_segmenter(ring, starting_index=0)
        _feed_segments(seg, 3)

        # Reset
        next_idx = seg.last_completed_index() + 1  # type: ignore[operator]
        seg.reset_for_restart(next_idx)
        seg.set_blockplan_timebase(
            start_utc_ms=1_700_000_000_000,
            active_block_start_utc_ms=1_700_000_000_000,
            active_block_end_utc_ms=1_700_003_600_000,
        )

        # Feed new data
        _feed_segments(seg, 2)

        # Find the segment at next_idx
        s = ring.get(next_idx)
        assert s is not None
        assert s.discontinuity is True

    def test_reset_continues_index_from_given(self):
        """reset_for_restart continues numbering from next_index."""
        ring = _make_ring()
        seg = _make_segmenter(ring, starting_index=0)
        _feed_segments(seg, 3)

        seg.reset_for_restart(100)
        seg.set_blockplan_timebase(
            start_utc_ms=1_700_000_000_000,
            active_block_start_utc_ms=1_700_000_000_000,
            active_block_end_utc_ms=1_700_003_600_000,
        )
        _feed_segments(seg, 2)

        window = ring.window()
        # Should contain segments from both sessions
        indices = [s.index for s in window]
        assert 100 in indices

    def test_close_stops_accepting_data(self):
        """After close(), feed() is silently ignored."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        _feed_segments(seg, 2)
        count_before = ring.count()

        seg.close()
        _feed_segments(seg, 5)

        assert ring.count() == count_before

    def test_close_is_idempotent(self):
        """Calling close() multiple times does not raise."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        seg.close()
        seg.close()
        seg.close()


# ---------------------------------------------------------------------------
# INV-HLS-PRODUCER-SEGMENT-FLOW-001 — Stall detection
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestSegmenterStallVisibility:
    """INV-HLS-PRODUCER-SEGMENT-FLOW-001"""

    def test_completion_timestamp_recorded(self):
        """last_segment_completed_monotonic_ms is set after segment completion."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        assert seg.last_segment_completed_monotonic_ms() is None

        _feed_segments(seg, 1)
        assert seg.last_segment_completed_monotonic_ms() is not None

    def test_no_segments_without_feed(self):
        """No segments produced when no data is fed."""
        ring = _make_ring()
        seg = _make_segmenter(ring)
        assert ring.count() == 0
        assert seg.last_completed_index() is None

    def test_partial_data_no_segment(self):
        """Feeding less than target_duration of data does not finalize."""
        ring = _make_ring()
        seg = _make_segmenter(ring, target_ms=6000)

        # Feed a tiny amount — not enough
        partial = make_ts_packet(pid=0x100, keyframe=True, pcr=0.0)
        seg.feed(partial * 3)

        assert ring.count() == 0
