"""
Shared fixtures for HLS delivery contract tests.

All fixtures produce synthetic TS data and operate against the HLSSegmenter
from retrovue.streaming.hls_writer. No real AIR subprocess or network I/O
is involved — tests validate behavioral contracts through the segmenter's
public API and generated playlists/segments.

Contract tests MUST NOT use time.sleep. Use contract_clock for deterministic
time advancement.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import pytest

from retrovue.streaming.hls_writer import HLSSegmenter, TS_PACKET_SIZE, TS_SYNC_BYTE


# ---------------------------------------------------------------------------
# Synthetic TS helpers
# ---------------------------------------------------------------------------

def make_ts_packet(
    pid: int = 0x100,
    *,
    keyframe: bool = False,
    pcr: float | None = None,
    pusi: bool = False,
    cc: int = 0,
    payload_fill: int = 0x00,
) -> bytes:
    """Build a single 188-byte TS packet with optional RAI and PCR."""
    buf = bytearray(TS_PACKET_SIZE)
    buf[0] = TS_SYNC_BYTE

    # Byte 1-2: PUSI + PID
    buf[1] = (0x40 if pusi else 0x00) | ((pid >> 8) & 0x1F)
    buf[2] = pid & 0xFF

    has_af = keyframe or pcr is not None
    afc = 0x03 if has_af else 0x01  # 3 = AF + payload, 1 = payload only
    buf[3] = (afc << 4) | (cc & 0x0F)

    payload_start = 4
    if has_af:
        af_flags = 0x00
        if keyframe:
            af_flags |= 0x40  # random_access_indicator
        if pcr is not None:
            af_flags |= 0x10  # PCR_flag

        if pcr is not None:
            af_len = 7
            buf[4] = af_len
            buf[5] = af_flags
            pcr_base = int(pcr * 90000)
            pcr_ext = 0
            buf[6] = (pcr_base >> 25) & 0xFF
            buf[7] = (pcr_base >> 17) & 0xFF
            buf[8] = (pcr_base >> 9) & 0xFF
            buf[9] = (pcr_base >> 1) & 0xFF
            buf[10] = ((pcr_base & 1) << 7) | 0x7E | ((pcr_ext >> 8) & 0x01)
            buf[11] = pcr_ext & 0xFF
            payload_start = 12
        else:
            af_len = 1
            buf[4] = af_len
            buf[5] = af_flags
            payload_start = 6

    for i in range(payload_start, TS_PACKET_SIZE):
        buf[i] = payload_fill & 0xFF

    return bytes(buf)


def generate_segment_data(
    duration: float = 2.5,
    packets_per_second: int = 50,
    pid: int = 0x100,
    pcr_start: float = 0.0,
) -> bytes:
    """Generate TS data spanning `duration` seconds, starting with a keyframe."""
    total_packets = int(duration * packets_per_second)
    packets = []
    for i in range(total_packets):
        t = pcr_start + (i / packets_per_second)
        is_first = i == 0
        include_pcr = (i % 10 == 0)
        pkt = make_ts_packet(
            pid=pid,
            keyframe=is_first,
            pcr=t if include_pcr else None,
            cc=i % 16,
        )
        packets.append(pkt)
    return b"".join(packets)


def feed_n_segments(seg: HLSSegmenter, n: int, target_dur: float = 2.5) -> None:
    """Feed enough data to finalize exactly n segments."""
    for i in range(n):
        pcr_start = i * target_dur
        data = generate_segment_data(duration=target_dur, pcr_start=pcr_start)
        seg.feed(data)
    # Feed one more keyframe to trigger finalization of the last segment
    final_pcr = n * target_dur
    trigger = make_ts_packet(pid=0x100, keyframe=True, pcr=final_pcr)
    seg.feed(trigger)


def extract_segment_names(playlist: str) -> list[str]:
    """Extract ordered segment filenames from an M3U8 playlist string."""
    return [
        line.strip()
        for line in playlist.splitlines()
        if re.match(r"seg_\d{5}\.ts", line.strip())
    ]


def extract_extinf_values(playlist: str) -> list[float]:
    """Extract EXTINF duration values from an M3U8 playlist."""
    return [
        float(m.group(1))
        for line in playlist.splitlines()
        if (m := re.match(r"#EXTINF:([\d.]+),?", line))
    ]


def extract_media_sequence(playlist: str) -> int | None:
    """Extract EXT-X-MEDIA-SEQUENCE value from an M3U8 playlist."""
    for line in playlist.splitlines():
        m = re.match(r"#EXT-X-MEDIA-SEQUENCE:(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def extract_target_duration(playlist: str) -> int | None:
    """Extract EXT-X-TARGETDURATION value from an M3U8 playlist."""
    for line in playlist.splitlines():
        m = re.match(r"#EXT-X-TARGETDURATION:(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def extract_program_date_time(playlist: str) -> str | None:
    """Extract EXT-X-PROGRAM-DATE-TIME value from an M3U8 playlist."""
    for line in playlist.splitlines():
        m = re.match(r"#EXT-X-PROGRAM-DATE-TIME:(.*)", line)
        if m:
            return m.group(1).strip()
    return None


def extract_segment_indices(playlist: str) -> list[int]:
    """Extract numeric indices from segment URIs in an M3U8 playlist."""
    return [
        int(m.group(1))
        for line in playlist.splitlines()
        if (m := re.match(r"seg_(\d{5})\.ts", line.strip()))
    ]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def segmenter():
    """Provide a fresh HLSSegmenter with standard test configuration."""
    seg = HLSSegmenter("test-channel", target_duration=2.0, max_segments=5)
    seg.start()
    yield seg
    seg.stop()


@pytest.fixture
def segmenter_with_segments():
    """Provide a segmenter with 3 finalized segments ready for inspection."""
    seg = HLSSegmenter("test-channel", target_duration=2.0, max_segments=10)
    seg.start()
    feed_n_segments(seg, 3, target_dur=2.5)
    yield seg
    seg.stop()
