"""Contract tests for HLS segmenter timebase snapshot invariants.

INV-HLS-SEGMENT-TIMEBASE-SNAPSHOT-001:
    Segment timebase frozen at start — mid-segment set_blockplan_timebase()
    MUST NOT affect the current segment's wallclock computation.

INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001:
    No cross-timebase contamination — each segment's wallclock derives from
    the single timebase active when that segment started.

INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001:
    Audit uses snapshot block window — seam-straddling segments are validated
    against the block window from their start-time snapshot.

INV-HLS-PDT-MONOTONIC-001:
    PROGRAM-DATE-TIME non-decreasing across consecutive segments.
"""

from __future__ import annotations

import logging

import pytest

from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing
from retrovue.runtime.hls.segmenter import (
    HlsSegmenter,
    TS_PACKET_SIZE,
    TS_SYNC_BYTE,
)


# ---------------------------------------------------------------------------
# TS packet helpers
# ---------------------------------------------------------------------------

def _make_ts_packet(
    pid: int = 0x100,
    payload_unit_start: bool = False,
    keyframe: bool = False,
    pcr: int | None = None,
) -> bytes:
    """Build a minimal 188-byte TS packet with optional PCR and keyframe flag.

    This mirrors the helper pattern used in other HLS contract tests.
    """
    buf = bytearray(TS_PACKET_SIZE)
    buf[0] = TS_SYNC_BYTE

    # PID in bytes 1-2
    buf[1] = (pid >> 8) & 0x1F
    buf[2] = pid & 0xFF

    if payload_unit_start:
        buf[1] |= 0x40  # PUSI

    has_adaptation = pcr is not None or keyframe
    has_payload = True

    if has_adaptation and has_payload:
        buf[3] = 0x30  # AFC = 11
    elif has_adaptation:
        buf[3] = 0x20  # AFC = 10
    else:
        buf[3] = 0x10  # AFC = 01

    if has_adaptation:
        af_flags = 0
        af_data = bytearray()

        if pcr is not None:
            af_flags |= 0x10  # PCR_flag
            # Encode 33-bit PCR base (90kHz)
            pcr_bytes = bytearray(6)
            pcr_bytes[0] = (pcr >> 25) & 0xFF
            pcr_bytes[1] = (pcr >> 17) & 0xFF
            pcr_bytes[2] = (pcr >> 9) & 0xFF
            pcr_bytes[3] = (pcr >> 1) & 0xFF
            pcr_bytes[4] = ((pcr & 1) << 7) | 0x7E  # PCR ext = 0
            pcr_bytes[5] = 0x00
            af_data.extend(pcr_bytes)

        if keyframe:
            af_flags |= 0x40  # random_access_indicator

        af_len = 1 + len(af_data)  # 1 for flags byte
        buf[4] = af_len
        buf[5] = af_flags
        buf[6 : 6 + len(af_data)] = af_data

    return bytes(buf)


def _make_keyframe_packet(pcr: int | None = None, pid: int = 0x100) -> bytes:
    """Keyframe packet with optional PCR."""
    return _make_ts_packet(pid=pid, keyframe=True, pcr=pcr)


def _make_data_packet(pcr: int | None = None, pid: int = 0x100) -> bytes:
    """Non-keyframe data packet with optional PCR."""
    return _make_ts_packet(pid=pid, pcr=pcr)


def _pcr_for_ms(ms: int) -> int:
    """Convert milliseconds to 90kHz PCR ticks."""
    return (ms * 90000) // 1000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def ring() -> SegmentRing:
    return SegmentRing(capacity=10, manifest_window=3)


@pytest.fixture
def segmenter(ring: SegmentRing) -> HlsSegmenter:
    from retrovue.runtime.clock import SystemClock
    return HlsSegmenter(
        channel_id="test-ch",
        segment_ring=ring,
        clock=SystemClock(),
        target_duration_ms=6000,
        max_gop_ms=1000,
        starting_index=0,
    )


def _feed_packets_to_complete_segment(
    seg: HlsSegmenter,
    start_pcr_ms: int,
    end_pcr_ms: int,
    start_keyframe: bool = True,
    end_keyframe: bool = True,
) -> None:
    """Feed enough packets to fill a segment from start_pcr_ms to end_pcr_ms.

    The first packet is a keyframe (to start the segment).
    Intermediate packets carry advancing PCR.
    The final packet is a keyframe (to trigger the split boundary for the
    *next* segment, which also finalizes the current one).
    """
    pcr_step_ms = 100  # Feed a PCR every 100ms
    current_ms = start_pcr_ms

    # First packet: keyframe with PCR to start segment accumulation
    if start_keyframe:
        seg.feed(_make_keyframe_packet(pcr=_pcr_for_ms(current_ms)))
    else:
        seg.feed(_make_data_packet(pcr=_pcr_for_ms(current_ms)))
    current_ms += pcr_step_ms

    # Intermediate data packets
    while current_ms < end_pcr_ms:
        seg.feed(_make_data_packet(pcr=_pcr_for_ms(current_ms)))
        current_ms += pcr_step_ms

    # Final keyframe triggers segment split (if target duration exceeded)
    if end_keyframe:
        seg.feed(_make_keyframe_packet(pcr=_pcr_for_ms(end_pcr_ms)))


# ---------------------------------------------------------------------------
# Test 1: INV-HLS-SEGMENT-TIMEBASE-SNAPSHOT-001
# ---------------------------------------------------------------------------

class TestInvHlsSegmentTimebaseSnapshot001:
    """INV-HLS-SEGMENT-TIMEBASE-SNAPSHOT-001: Segment timebase frozen at start."""

    def test_seam_integrity_snapshot_protects_mid_segment_timebase_change(
        self, segmenter: HlsSegmenter, ring: SegmentRing
    ):
        """Mid-segment set_blockplan_timebase() does not affect the current
        segment's wallclock.

        Scenario:
        1. Set old block timebase (start_utc_ms=1_000_000, window [1_000_000, 2_000_000))
        2. Feed packets to start a segment (PCR 0..3000ms)
        3. Call set_blockplan_timebase() with new block mid-segment
        4. Feed remaining packets to reach target duration + keyframe
        5. Assert: wallclock uses old timebase, not new
        6. Assert: no audit violation
        """
        old_start_utc = 1_000_000
        old_block_start = 1_000_000
        old_block_end = 2_000_000

        new_start_utc = 2_000_000
        new_block_start = 2_000_000
        new_block_end = 3_000_000

        # Set old timebase
        segmenter.set_blockplan_timebase(
            start_utc_ms=old_start_utc,
            active_block_start_utc_ms=old_block_start,
            active_block_end_utc_ms=old_block_end,
        )

        # Start segment: keyframe at PCR=0
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(0)))

        # Feed data packets to 3000ms (halfway to target duration)
        for ms in range(100, 3100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))

        # Mid-segment: change timebase to new block
        segmenter.set_blockplan_timebase(
            start_utc_ms=new_start_utc,
            active_block_start_utc_ms=new_block_start,
            active_block_end_utc_ms=new_block_end,
        )

        # Feed remaining packets past target_duration (6000ms) + keyframe
        for ms in range(3200, 6100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))

        # Keyframe triggers segment completion
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(6100)))

        # Verify segment was produced
        seg = ring.get(0)
        assert seg is not None, "Segment 0 should have been produced"

        # Wallclock MUST be derived from old timebase (snapshot at segment start).
        # PCR origin was captured at the first PCR of the session (PCR=0).
        # seg_start_pcr = 0, snap_timebase_pcr_origin = 0.
        # wall_clock = old_start_utc + (0 - 0) * 1000 / 90000 = 1_000_000
        expected_wallclock = old_start_utc
        assert seg.wall_clock_start_utc_ms == expected_wallclock, (
            f"INV-HLS-SEGMENT-TIMEBASE-SNAPSHOT-001 violated: "
            f"wall_clock={seg.wall_clock_start_utc_ms}, expected={expected_wallclock} "
            f"(from old timebase, not new)"
        )

        # Wallclock MUST fall within old block window (no audit violation)
        assert old_block_start <= seg.wall_clock_start_utc_ms < old_block_end, (
            f"Segment wallclock {seg.wall_clock_start_utc_ms} outside old block "
            f"window [{old_block_start}, {old_block_end})"
        )


# ---------------------------------------------------------------------------
# Test 2: INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001
# ---------------------------------------------------------------------------

class TestInvHlsSegmentEditorialConsistency001:
    """INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001: No cross-timebase contamination."""

    def test_no_cross_timebase_contamination(
        self, segmenter: HlsSegmenter, ring: SegmentRing
    ):
        """Consecutive segments across a block transition use their own timebases.

        Scenario:
        1. Set timebase A (start_utc_ms=1_000_000)
        2. Start segment 0, mid-segment change to timebase B
        3. Complete segment 0
        4. Set timebase B again (same values) — now seg 1 starts under B
        5. Complete segment 1
        6. Assert: seg 0 wallclock from A, seg 1 wallclock from B
        7. Assert: they are different
        """
        tb_a_start = 1_000_000
        tb_a_block_start = 1_000_000
        tb_a_block_end = 2_000_000

        tb_b_start = 2_000_000
        tb_b_block_start = 2_000_000
        tb_b_block_end = 3_000_000

        # Timebase A
        segmenter.set_blockplan_timebase(
            start_utc_ms=tb_a_start,
            active_block_start_utc_ms=tb_a_block_start,
            active_block_end_utc_ms=tb_a_block_end,
        )

        # Segment 0: start at PCR=0
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(0)))
        for ms in range(100, 3100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))

        # Mid-segment: switch to timebase B
        segmenter.set_blockplan_timebase(
            start_utc_ms=tb_b_start,
            active_block_start_utc_ms=tb_b_block_start,
            active_block_end_utc_ms=tb_b_block_end,
        )

        # Continue feeding to complete seg 0
        for ms in range(3200, 6100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(6100)))

        seg0 = ring.get(0)
        assert seg0 is not None, "Segment 0 should have been produced"

        # Segment 1: starts under timebase B (already set).
        # The snapshot is taken at the keyframe that started the new segment.
        # Feed data from 6200ms to 12200ms + keyframe.
        for ms in range(6200, 12200, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(12200)))

        seg1 = ring.get(1)
        assert seg1 is not None, "Segment 1 should have been produced"

        # Seg 0 wallclock from timebase A:
        # PCR origin = 0, seg_start_pcr = 0 => offset = 0
        # wall_clock = tb_a_start + 0 = 1_000_000
        assert seg0.wall_clock_start_utc_ms == tb_a_start, (
            f"INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001 violated: "
            f"seg0 wallclock={seg0.wall_clock_start_utc_ms}, "
            f"expected={tb_a_start} (from timebase A)"
        )

        # Seg 1 wallclock from timebase B:
        # snap_timebase_pcr_origin was captured at the PCR when timebase B was set.
        # At the time set_blockplan_timebase() was called, _last_pcr was at 3000ms.
        # snap_timebase_pcr_origin = PCR(3000ms), seg_start_pcr = PCR(6100ms)
        # offset = (6100 - 3000) * 1000 / 90000 = 3100ms
        # wall_clock = tb_b_start + 3100 = 2_003_100
        seg1_offset_ms = 6100 - 3000  # 3100
        expected_seg1_wc = tb_b_start + seg1_offset_ms
        assert seg1.wall_clock_start_utc_ms == expected_seg1_wc, (
            f"INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001 violated: "
            f"seg1 wallclock={seg1.wall_clock_start_utc_ms}, "
            f"expected={expected_seg1_wc} (from timebase B)"
        )

        # They MUST differ (proving no contamination)
        assert seg0.wall_clock_start_utc_ms != seg1.wall_clock_start_utc_ms, (
            "INV-HLS-SEGMENT-EDITORIAL-CONSISTENCY-001 violated: "
            "seg0 and seg1 have identical wallclocks despite different timebases"
        )


# ---------------------------------------------------------------------------
# Test 3: INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001
# ---------------------------------------------------------------------------

class TestInvHlsSegmentBlockAlignment001:
    """INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001: Audit uses snapshot block window."""

    def test_block_alignment_audit_uses_snapshot_window(
        self, segmenter: HlsSegmenter, ring: SegmentRing, caplog
    ):
        """Seam-straddling segment audited against snapshot (old) block window.

        Scenario:
        1. Set old block timebase with window [1_000_000, 2_000_000)
        2. Start segment (wallclock will be ~1_000_000)
        3. Set new block timebase with window [2_000_000, 3_000_000) mid-segment
        4. Complete segment
        5. Assert: wallclock in [1_000_000, 2_000_000)
        6. Assert: no audit warning logged
        """
        old_start_utc = 1_000_000
        old_block_start = 1_000_000
        old_block_end = 2_000_000

        new_start_utc = 2_000_000
        new_block_start = 2_000_000
        new_block_end = 3_000_000

        segmenter.set_blockplan_timebase(
            start_utc_ms=old_start_utc,
            active_block_start_utc_ms=old_block_start,
            active_block_end_utc_ms=old_block_end,
        )

        # Start segment at PCR=0
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(0)))
        for ms in range(100, 3100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))

        # Mid-segment: new block
        segmenter.set_blockplan_timebase(
            start_utc_ms=new_start_utc,
            active_block_start_utc_ms=new_block_start,
            active_block_end_utc_ms=new_block_end,
        )

        # Complete segment
        with caplog.at_level(logging.WARNING):
            for ms in range(3200, 6100, 100):
                segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
            segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(6100)))

        seg = ring.get(0)
        assert seg is not None, "Segment 0 should have been produced"

        # Wallclock in old block window
        assert old_block_start <= seg.wall_clock_start_utc_ms < old_block_end, (
            f"INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001 violated: "
            f"wallclock {seg.wall_clock_start_utc_ms} outside snapshot window "
            f"[{old_block_start}, {old_block_end})"
        )

        # No audit warning (wallclock is within snapshot window)
        audit_warnings = [
            r for r in caplog.records
            if "INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001" in r.message
            and r.levelno >= logging.WARNING
        ]
        assert len(audit_warnings) == 0, (
            f"INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001 violated: "
            f"spurious audit warning fired for seam-straddling segment: "
            f"{[w.message for w in audit_warnings]}"
        )


# ---------------------------------------------------------------------------
# Test 4: INV-HLS-PDT-MONOTONIC-001
# ---------------------------------------------------------------------------

class TestInvHlsPdtMonotonic001:
    """INV-HLS-PDT-MONOTONIC-001: Non-decreasing PROGRAM-DATE-TIME."""

    def test_pdt_monotonic_across_block_transition(
        self, segmenter: HlsSegmenter, ring: SegmentRing
    ):
        """PROGRAM-DATE-TIME values are non-decreasing across a block transition.

        Scenario:
        1. Set block A timebase (start_utc_ms=1_000_000)
        2. Produce segment 0 (PCR 0..6100ms)
        3. Set block B timebase (start_utc_ms=2_000_000)
        4. Produce segment 1 (PCR 6200..12300ms)
        5. Produce segment 2 (PCR 12400..18500ms)
        6. Assert: each segment's wallclock >= previous segment's wallclock
        """
        block_a_start = 1_000_000
        block_a_block_start = 1_000_000
        block_a_block_end = 2_000_000

        block_b_start = 2_000_000
        block_b_block_start = 2_000_000
        block_b_block_end = 3_000_000

        # Block A
        segmenter.set_blockplan_timebase(
            start_utc_ms=block_a_start,
            active_block_start_utc_ms=block_a_block_start,
            active_block_end_utc_ms=block_a_block_end,
        )

        # Segment 0: PCR 0..6100ms
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(0)))
        for ms in range(100, 6100, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(6100)))

        # Transition to Block B
        segmenter.set_blockplan_timebase(
            start_utc_ms=block_b_start,
            active_block_start_utc_ms=block_b_block_start,
            active_block_end_utc_ms=block_b_block_end,
        )

        # Segment 1: PCR 6200..12300ms
        for ms in range(6200, 12300, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(12300)))

        # Segment 2: PCR 12400..18500ms
        for ms in range(12400, 18500, 100):
            segmenter.feed(_make_data_packet(pcr=_pcr_for_ms(ms)))
        segmenter.feed(_make_keyframe_packet(pcr=_pcr_for_ms(18500)))

        # Collect all produced segments
        segments: list[LiveSegment] = []
        for i in range(3):
            seg = ring.get(i)
            if seg is not None:
                segments.append(seg)

        assert len(segments) >= 3, (
            f"Expected at least 3 segments, got {len(segments)}"
        )

        # Assert monotonicity
        for i in range(1, len(segments)):
            assert segments[i].wall_clock_start_utc_ms >= segments[i - 1].wall_clock_start_utc_ms, (
                f"INV-HLS-PDT-MONOTONIC-001 violated: "
                f"segment[{i}].wall_clock={segments[i].wall_clock_start_utc_ms} < "
                f"segment[{i-1}].wall_clock={segments[i - 1].wall_clock_start_utc_ms}"
            )
