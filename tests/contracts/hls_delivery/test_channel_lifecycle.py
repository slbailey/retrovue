"""
Contract Tests: HLS Channel Lifecycle

Canonical contract:
    docs/contracts/delivery_hls.md — §7 Failure Contracts

Test matrix:
    docs/contracts/TEST-MATRIX-HLS-DELIVERY.md — Channel Lifecycle

These tests enforce the channel lifecycle invariants
(INV-HLS-RESTART-DISCONTINUITY-001, INV-HLS-PRODUCER-SEGMENT-FLOW-001,
INV-HLS-NO-ORPHAN-PRODUCER-001) using the new HlsSegmenter + SegmentRing API.

Every test references the specific invariant(s) it validates.

Migrated from the retired hls_writer.HLSSegmenter API (commit 8cccc5b).
New API: HlsSegmenter + SegmentRing + ManifestGenerator (retrovue.runtime.hls.*).
"""

from __future__ import annotations

import pytest

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
# INV-HLS-RESTART-DISCONTINUITY-001 — Producer restart continuity
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsRestartDiscontinuity001:
    """INV-HLS-RESTART-DISCONTINUITY-001"""

    def test_discontinuity_after_restart(self):
        """After close + reset_for_restart, first new segment carries discontinuity."""
        seg, ring = make_segmenter(target_ms=2000)

        # Produce some segments
        feed_n_segments(seg, 3, target_dur=2.5)
        segs_before = ring.window()
        assert len(segs_before) >= 1

        # Simulate producer restart
        seg.close()
        ring.clear()
        last_index = (segs_before[-1].index + 1) if segs_before else 0
        seg.reset_for_restart(next_index=last_index)

        # Feed new data after restart
        feed_n_segments(seg, 2, target_dur=2.5)
        new_segs = ring.window()
        assert len(new_segs) >= 1

        # INV-HLS-RESTART-DISCONTINUITY-001 — first segment after restart must be discontinuous
        first_new = new_segs[0]
        assert first_new.discontinuity is True, (
            f"First segment after restart must carry discontinuity=True, "
            f"got discontinuity={first_new.discontinuity}"
        )

    def test_segments_produced_after_restart(self):
        """A restarted segmenter produces valid segments."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        seg.close()
        ring.clear()
        seg.reset_for_restart(next_index=10)  # arbitrary continuation index

        feed_n_segments(seg, 3, target_dur=2.5)

        segs = ring.window()
        assert len(segs) >= 1, "Expected segments after restart"

        # INV-HLS-RESTART-DISCONTINUITY-001 — valid segments after restart
        for s in segs:
            assert s.byte_count > 0, f"Segment {s.index} has zero bytes"
            assert s.data is not None, f"Segment {s.index} has no data"


# ---------------------------------------------------------------------------
# INV-HLS-PRODUCER-SEGMENT-FLOW-001 — Stall detection
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsProducerSegmentFlow001:
    """INV-HLS-PRODUCER-SEGMENT-FLOW-001"""

    def test_segments_produced_at_realtime_rate(self):
        """Feeding real-time data produces segments at expected rate."""
        seg, ring = make_segmenter(target_ms=2000)

        feed_n_segments(seg, 5, target_dur=2.5)

        segs = ring.window()
        # INV-HLS-PRODUCER-SEGMENT-FLOW-001 — segments produced
        assert len(segs) >= 3, (
            f"Expected at least 3 segments after feeding 5, got {len(segs)}"
        )

    def test_no_segments_without_feed(self):
        """No segments are produced when no data is fed."""
        _, ring = make_segmenter(target_ms=2000)

        # INV-HLS-PRODUCER-SEGMENT-FLOW-001 — no data = no segments
        assert ring.count() == 0, (
            f"Expected 0 segments before any feed, got {ring.count()}"
        )
        assert get_playlist(ring) == "", (
            "Expected empty playlist before any feed"
        )

    def test_partial_data_does_not_produce_segment(self):
        """Feeding less than one segment's worth of data does not finalize."""
        seg, ring = make_segmenter(target_ms=2000)

        # Feed a tiny amount — not enough for a segment
        partial = make_ts_packet(pid=0x100, keyframe=True, pcr=0.0)
        seg.feed(partial * 3)

        # INV-HLS-PRODUCER-SEGMENT-FLOW-001 — insufficient data = no segment
        assert ring.count() == 0, (
            f"Expected 0 segments after tiny partial feed, got {ring.count()}"
        )

    def test_stall_detectable_via_last_completed_monotonic_ms(self):
        """last_segment_completed_monotonic_ms() is None before first segment, set after."""
        seg, ring = make_segmenter(target_ms=2000)

        # Before any segments
        assert seg.last_segment_completed_monotonic_ms() is None, (
            "Expected None before first segment"
        )

        feed_n_segments(seg, 2, target_dur=2.5)

        # After segments
        ts = seg.last_segment_completed_monotonic_ms()
        assert ts is not None, (
            "last_segment_completed_monotonic_ms() should be set after segment completion"
        )
        assert ts > 0, f"Expected positive monotonic timestamp, got {ts}"


# ---------------------------------------------------------------------------
# INV-HLS-NO-ORPHAN-PRODUCER-001 — No abandoned producers
# ---------------------------------------------------------------------------


@pytest.mark.contract
class TestInvHlsNoOrphanProducer001:
    """INV-HLS-NO-ORPHAN-PRODUCER-001"""

    def test_close_halts_segment_acceptance(self):
        """After close(), feeding data does not produce new segments."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        count_at_close = ring.count()
        seg.close()

        # INV-HLS-NO-ORPHAN-PRODUCER-001 — closed = no more production
        # Feed data after close — should be silently ignored
        data = generate_segment_data(duration=2.5, pcr_start=100.0)
        seg.feed(data)

        assert ring.count() == count_at_close, (
            f"ring.count() grew after close(): {count_at_close} → {ring.count()}"
        )

    def test_close_is_idempotent(self):
        """Calling close() multiple times does not raise."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 1, target_dur=2.5)

        # INV-HLS-NO-ORPHAN-PRODUCER-001 — idempotent close
        seg.close()
        seg.close()  # second close should not raise
        seg.close()  # third close should not raise

    def test_reset_for_restart_enables_new_production(self):
        """reset_for_restart() after close() allows new segments to be produced."""
        seg, ring = make_segmenter(target_ms=2000)
        feed_n_segments(seg, 2, target_dur=2.5)

        count_before = ring.count()
        assert count_before >= 1

        seg.close()
        ring.clear()
        seg.reset_for_restart(next_index=count_before)

        # INV-HLS-NO-ORPHAN-PRODUCER-001 — clean state after restart
        feed_n_segments(seg, 2, target_dur=2.5)
        assert ring.count() >= 1, "Expected new segments after reset_for_restart()"

    def test_last_completed_index_advances_monotonically(self):
        """last_completed_index() increases with each segment produced."""
        seg, ring = make_segmenter(target_ms=2000, starting_index=0)
        indices_seen = []

        for i in range(4):
            feed_n_segments(seg, 1, target_dur=2.5, pcr_offset=i * 2.5)
            idx = seg.last_completed_index()
            if idx is not None:
                indices_seen.append(idx)

        assert len(indices_seen) >= 2, (
            "Need at least 2 completed segments to verify monotonicity"
        )
        for j in range(1, len(indices_seen)):
            assert indices_seen[j] >= indices_seen[j - 1], (
                f"last_completed_index decreased: {indices_seen[j-1]} → {indices_seen[j]}"
            )
