"""Contract tests for INV-HLS-DISCONTINUITY-MARKER-001.

HLS segmenter MUST emit #EXT-X-DISCONTINUITY before any segment where
a PCR discontinuity was detected during accumulation.

Rules:
1. When _current_seg_duration() detects a PCR discontinuity, the current
   segment MUST be marked discontinuous.
2. _generate_playlist() MUST emit #EXT-X-DISCONTINUITY before the #EXTINF
   line of any discontinuous segment.
3. HLSSegment MUST carry a discontinuity: bool field.
4. Segments with continuous PCR MUST NOT be marked discontinuous.
"""

import struct
import time
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — synthetic TS packet construction
# ---------------------------------------------------------------------------

TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47


def _make_ts_packet(
    pid: int = 0x100,
    pcr: float | None = None,
    keyframe: bool = False,
    pusi: bool = False,
) -> bytes:
    """Build a minimal 188-byte MPEG-TS packet.

    Args:
        pid: Packet ID (13 bits).
        pcr: If set, embed PCR (in seconds) in the adaptation field.
        keyframe: If True, set random_access_indicator in adaptation field.
        pusi: If True, set payload_unit_start_indicator.
    """
    packet = bytearray(TS_PACKET_SIZE)
    packet[0] = TS_SYNC_BYTE

    # Byte 1-2: flags + PID
    pid_high = (pid >> 8) & 0x1F
    if pusi:
        pid_high |= 0x40
    packet[1] = pid_high
    packet[2] = pid & 0xFF

    has_adaptation = pcr is not None or keyframe
    has_payload = True

    if has_adaptation and has_payload:
        afc = 0x03
    elif has_adaptation:
        afc = 0x02
    else:
        afc = 0x01

    packet[3] = (afc << 4) | 0x00  # cc=0

    if has_adaptation:
        af_flags = 0x00
        af_data = bytearray()

        if pcr is not None:
            af_flags |= 0x10  # PCR_flag
            # Encode PCR: base (33 bits @ 90kHz) + extension (9 bits @ 27MHz)
            pcr_base = int(pcr * 90000)
            pcr_ext = 0
            pcr_bytes = bytearray(6)
            pcr_bytes[0] = (pcr_base >> 25) & 0xFF
            pcr_bytes[1] = (pcr_base >> 17) & 0xFF
            pcr_bytes[2] = (pcr_base >> 9) & 0xFF
            pcr_bytes[3] = (pcr_base >> 1) & 0xFF
            pcr_bytes[4] = ((pcr_base & 0x01) << 7) | 0x7E | ((pcr_ext >> 8) & 0x01)
            pcr_bytes[5] = pcr_ext & 0xFF
            af_data.extend(pcr_bytes)

        if keyframe:
            af_flags |= 0x40  # random_access_indicator

        af_len = 1 + len(af_data)  # 1 for flags byte
        packet[4] = af_len
        packet[5] = af_flags
        packet[6:6 + len(af_data)] = af_data

    return bytes(packet)


def _make_continuous_segment_packets(
    start_pcr: float,
    duration: float,
    packets_per_segment: int = 20,
) -> list[bytes]:
    """Generate a stream of TS packets with continuous PCR progression."""
    packets = []
    pcr_step = duration / packets_per_segment
    for i in range(packets_per_segment):
        pcr = start_pcr + i * pcr_step
        kf = (i == 0)  # First packet is keyframe
        packets.append(_make_ts_packet(pcr=pcr, keyframe=kf))
    return packets


# ---------------------------------------------------------------------------
# Rule 3: HLSSegment MUST carry a discontinuity: bool field
# ---------------------------------------------------------------------------

class TestHLSSegmentDiscontinuityField:
    """Rule 3: HLSSegment MUST have a discontinuity field of type bool."""

    def test_hls_segment_has_discontinuity_field(self):
        from retrovue.streaming.hls_writer import HLSSegment
        import dataclasses

        fields = {f.name: f for f in dataclasses.fields(HLSSegment)}
        assert "discontinuity" in fields, (
            "INV-HLS-DISCONTINUITY-MARKER-001 Rule 3: "
            "HLSSegment MUST carry a 'discontinuity: bool' field"
        )
        assert fields["discontinuity"].type == "bool" or fields["discontinuity"].type is bool, (
            "INV-HLS-DISCONTINUITY-MARKER-001 Rule 3: "
            f"HLSSegment.discontinuity type MUST be bool, got {fields['discontinuity'].type}"
        )


# ---------------------------------------------------------------------------
# Rule 2: Playlist MUST emit #EXT-X-DISCONTINUITY
# ---------------------------------------------------------------------------

class TestPlaylistEmitsDiscontinuityTag:
    """Rule 2: _generate_playlist() MUST emit #EXT-X-DISCONTINUITY before
    the #EXTINF line of any discontinuous segment."""

    def test_playlist_emits_discontinuity_tag(self):
        """Feed synthetic TS packets with a PCR discontinuity mid-stream.
        The playlist MUST contain #EXT-X-DISCONTINUITY before the affected segment."""
        from retrovue.streaming.hls_writer import HLSSegmenter

        seg = HLSSegmenter(channel_id="test-discont", target_duration=2.0, max_segments=10)
        seg.start()

        # Segment 1: continuous PCR 0.0 → 3.0s (enough to exceed target_duration)
        packets_seg1 = _make_continuous_segment_packets(start_pcr=0.0, duration=3.0, packets_per_segment=30)
        for pkt in packets_seg1:
            seg.feed(pkt)

        # Segment 2 start: keyframe with continuous PCR to trigger segment split
        # Then a PCR discontinuity (jump from ~3.0 to 1000.0 — exceeds
        # max_plausible threshold of max(target_duration*10, 120.0) = 120s)
        seg.feed(_make_ts_packet(pcr=3.0, keyframe=True))

        # Continue with post-discontinuity PCR (large jump triggers detection)
        packets_seg2 = _make_continuous_segment_packets(start_pcr=1000.0, duration=3.0, packets_per_segment=30)
        for pkt in packets_seg2:
            seg.feed(pkt)

        # Trigger another segment split
        seg.feed(_make_ts_packet(pcr=1003.0, keyframe=True))
        # Feed a few more packets so the third segment has content
        for pkt in _make_continuous_segment_packets(start_pcr=1003.0, duration=3.0, packets_per_segment=10):
            seg.feed(pkt)
        seg.feed(_make_ts_packet(pcr=1006.0, keyframe=True))

        playlist = seg.get_playlist()
        assert playlist is not None, "Expected at least one finalized segment"
        assert "#EXT-X-DISCONTINUITY" in playlist, (
            "INV-HLS-DISCONTINUITY-MARKER-001 Rule 2: "
            "playlist MUST contain #EXT-X-DISCONTINUITY when PCR discontinuity detected. "
            f"Playlist:\n{playlist}"
        )

        # Verify the tag appears before an #EXTINF line (not at the end or freestanding)
        lines = playlist.strip().split("\n")
        for i, line in enumerate(lines):
            if line == "#EXT-X-DISCONTINUITY":
                assert i + 1 < len(lines), "#EXT-X-DISCONTINUITY must be followed by #EXTINF"
                assert lines[i + 1].startswith("#EXTINF:"), (
                    f"#EXT-X-DISCONTINUITY must be followed by #EXTINF, got: {lines[i + 1]}"
                )
                break


# ---------------------------------------------------------------------------
# Rule 4: No spurious discontinuity on continuous PCR
# ---------------------------------------------------------------------------

class TestNoSpuriousDiscontinuity:
    """Rule 4: Segments with continuous PCR MUST NOT be marked discontinuous."""

    def test_no_spurious_discontinuity_on_continuous_pcr(self):
        """Feed only continuous-PCR packets. The playlist MUST NOT contain
        #EXT-X-DISCONTINUITY."""
        from retrovue.streaming.hls_writer import HLSSegmenter

        seg = HLSSegmenter(channel_id="test-continuous", target_duration=2.0, max_segments=10)
        seg.start()

        # Generate 3 segments worth of continuous PCR data
        pcr = 0.0
        for seg_num in range(4):
            packets = _make_continuous_segment_packets(
                start_pcr=pcr, duration=3.0, packets_per_segment=30,
            )
            for pkt in packets:
                seg.feed(pkt)
            pcr += 3.0
            # Keyframe to trigger segment split
            seg.feed(_make_ts_packet(pcr=pcr, keyframe=True))

        playlist = seg.get_playlist()
        assert playlist is not None, "Expected finalized segments"
        assert "#EXT-X-DISCONTINUITY" not in playlist, (
            "INV-HLS-DISCONTINUITY-MARKER-001 Rule 4: "
            "playlist MUST NOT contain #EXT-X-DISCONTINUITY when PCR is continuous. "
            f"Playlist:\n{playlist}"
        )
