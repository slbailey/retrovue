"""
Shared fixtures for HLS delivery contract tests.

All fixtures and helpers produce synthetic TS data for use with the
new HLS stack (retrovue.runtime.hls). No real AIR subprocess or network
I/O is involved.

Contract tests MUST NOT use time.sleep. Use contract_clock for deterministic
time advancement.

NOTE: Old hls_writer.HLSSegmenter fixtures retired in refactor step 6f.
The new stack uses HlsSegmenter (retrovue.runtime.hls.segmenter) + SegmentRing.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

import pytest

# MPEG-TS constants (canonical; no longer imported from hls_writer)
TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47


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
