"""
Contract tests for INV-HLS-NO-DISK-IO-001.

HLS segment and playlist data MUST be stored in and served from memory.
No filesystem I/O MUST occur on the segment feed, playlist serve, or
segment serve paths.
"""

import re
import struct
import threading
import time
from unittest.mock import patch

import pytest

from retrovue.streaming.hls_writer import HLSSegmenter, TS_PACKET_SIZE, TS_SYNC_BYTE


# ---------------------------------------------------------------------------
# Helpers — synthetic TS data generation
# ---------------------------------------------------------------------------

def _make_ts_packet(
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
            # AF: length(1) + flags(1) + PCR(6) = 8 bytes
            af_len = 7  # excludes length byte itself
            buf[4] = af_len
            buf[5] = af_flags
            # Encode PCR
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

    # Fill payload
    for i in range(payload_start, TS_PACKET_SIZE):
        buf[i] = payload_fill & 0xFF

    return bytes(buf)


def _generate_segment_data(
    duration: float = 2.5,
    packets_per_second: int = 50,
    pid: int = 0x100,
    pcr_start: float = 0.0,
) -> bytes:
    """Generate TS data that will trigger a segment split.

    Returns enough TS packets to cover `duration` seconds, starting with
    a keyframe+PCR packet and including PCR updates throughout.
    """
    total_packets = int(duration * packets_per_second)
    packets = []
    for i in range(total_packets):
        t = pcr_start + (i / packets_per_second)
        is_first = i == 0
        # Include PCR every ~10 packets
        include_pcr = (i % 10 == 0)
        pkt = _make_ts_packet(
            pid=pid,
            keyframe=is_first,
            pcr=t if include_pcr else None,
            cc=i % 16,
        )
        packets.append(pkt)
    return b"".join(packets)


def _feed_n_segments(seg: HLSSegmenter, n: int, target_dur: float = 2.5) -> None:
    """Feed enough data to finalize exactly n segments.

    Each segment gets its own keyframe-starting block of data, then a final
    keyframe packet triggers the split for the previous segment.
    """
    for i in range(n):
        pcr_start = i * target_dur
        data = _generate_segment_data(
            duration=target_dur, pcr_start=pcr_start,
        )
        seg.feed(data)
    # Feed one more keyframe to trigger finalization of the last segment
    final_pcr = n * target_dur
    trigger = _make_ts_packet(pid=0x100, keyframe=True, pcr=final_pcr)
    seg.feed(trigger)


# ---------------------------------------------------------------------------
# IO Tripwire fixtures
# ---------------------------------------------------------------------------

_VIOLATION_MSG = "INV-HLS-NO-DISK-IO-001 violated"
_HLS_WRITER_MODULE = "retrovue/streaming/hls_writer.py"


def _make_scoped_raiser(original, method_name):
    """Create a wrapper that raises AssertionError only when called from hls_writer module."""
    import inspect

    def _scoped(*args, **kwargs):
        frame = inspect.currentframe()
        try:
            caller = frame.f_back
            caller_file = caller.f_code.co_filename if caller else ""
            if _HLS_WRITER_MODULE in caller_file:
                raise AssertionError(f"{_VIOLATION_MSG}: {method_name}() called from hls_writer")
        finally:
            del frame
        return original(*args, **kwargs)
    return _scoped


@pytest.fixture
def io_tripwires():
    """Monkeypatch filesystem I/O methods to raise when called from hls_writer.

    Uses caller-scoped wrappers so pytest infrastructure is unaffected.
    """
    import pathlib

    patches = []
    originals = {}

    # Patch Path methods — scope to hls_writer callers only
    for method_name in ("write_bytes", "write_text", "read_text", "read_bytes", "mkdir", "unlink"):
        original = getattr(pathlib.Path, method_name)
        originals[method_name] = original
        p = patch.object(pathlib.Path, method_name, _make_scoped_raiser(original, method_name))
        patches.append(p)

    # Patch open scoped to hls_writer module
    p = patch("retrovue.streaming.hls_writer.open", _make_scoped_raiser(open, "open"), create=True)
    patches.append(p)

    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------

class TestInvHlsNoDiskIo:
    """INV-HLS-NO-DISK-IO-001 contract tests."""

    def test_feed_with_io_tripwires_raises_on_any_disk_access(self, io_tripwires):
        """Full lifecycle under IO tripwires — no disk I/O occurs."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        # Feed enough data to finalize multiple segments
        _feed_n_segments(seg, 3, target_dur=2.5)

        # Access playlist and segments
        playlist = seg.get_playlist()
        assert playlist is not None

        # Read each segment referenced in playlist
        for line in playlist.splitlines():
            if line.startswith("seg_"):
                data = seg.get_segment(line.strip())
                assert data is not None

        seg.stop()
        # If we reach here, no AssertionError from tripwires = no disk I/O

    def test_get_playlist_returns_valid_m3u8(self):
        """After first segment finalized, get_playlist() returns valid M3U8."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        # Before any segments, playlist should be None
        assert seg.get_playlist() is None

        _feed_n_segments(seg, 1, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None
        assert playlist.startswith("#EXTM3U")
        assert "#EXT-X-TARGETDURATION:" in playlist
        assert "#EXT-X-MEDIA-SEQUENCE:0" in playlist
        assert "#EXTINF:" in playlist
        # Should contain a segment name
        assert re.search(r"seg_\d{5}\.ts", playlist)

    def test_get_segment_returns_ts_bytes(self):
        """get_segment() returns bytes starting with TS sync byte."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()
        _feed_n_segments(seg, 1, target_dur=2.5)

        playlist = seg.get_playlist()
        assert playlist is not None

        # Extract segment name from playlist
        seg_name = None
        for line in playlist.splitlines():
            if re.match(r"seg_\d{5}\.ts", line.strip()):
                seg_name = line.strip()
                break
        assert seg_name is not None

        data = seg.get_segment(seg_name)
        assert data is not None
        assert isinstance(data, bytes)
        assert len(data) > 0
        assert data[0] == TS_SYNC_BYTE

    def test_expired_segment_returns_none(self):
        """Evicted segments return None from get_segment()."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=3)
        seg.start()

        # Feed 5 segments, only 3 retained
        _feed_n_segments(seg, 5, target_dur=2.5)

        # First segment (seg_00000.ts) should be evicted
        assert seg.get_segment("seg_00000.ts") is None
        assert seg.get_segment("seg_00001.ts") is None
        # Latest segments should exist
        assert seg.get_segment("seg_00004.ts") is not None

    def test_memory_bounded_and_media_sequence_in_playlist(self):
        """With max_segments=5, feeding 20 segments retains exactly 5.
        Media sequence and playlist content reflect evictions."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        _feed_n_segments(seg, 20, target_dur=2.5)

        # Internal state checks
        assert len(seg._segments) == 5
        assert seg._media_sequence == 15

        # Playlist content checks
        playlist = seg.get_playlist()
        assert playlist is not None
        assert "#EXT-X-MEDIA-SEQUENCE:15" in playlist

        # First EXTINF entry should correspond to seg_00015.ts
        lines = playlist.splitlines()
        first_seg_line = None
        for line in lines:
            if re.match(r"seg_\d{5}\.ts", line.strip()):
                first_seg_line = line.strip()
                break
        assert first_seg_line == "seg_00015.ts"

    def test_stop_without_finalize(self):
        """Stop with partial data does not finalize a segment."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        # Feed a small amount of data — not enough for a segment
        partial = _make_ts_packet(pid=0x100, keyframe=True, pcr=0.0)
        seg.feed(partial * 5)

        seg.stop()
        assert seg.get_playlist() is None

    def test_playlist_ready_signaling(self):
        """has_playlist() and wait_for_playlist() work correctly."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=10)
        seg.start()

        assert seg.has_playlist() is False
        assert seg.wait_for_playlist(0) is False

        _feed_n_segments(seg, 1, target_dur=2.5)

        assert seg.has_playlist() is True
        assert seg.wait_for_playlist(0) is True

    def test_concurrent_feed_and_read(self):
        """Concurrent feed and read operations don't deadlock or corrupt state."""
        seg = HLSSegmenter("test-ch", target_duration=2.0, max_segments=5)
        seg.start()

        errors: list[str] = []
        stop_event = threading.Event()

        def _feeder():
            try:
                for i in range(10):
                    if stop_event.is_set():
                        break
                    data = _generate_segment_data(
                        duration=2.5, pcr_start=i * 2.5,
                    )
                    seg.feed(data)
                # Final trigger
                trigger = _make_ts_packet(pid=0x100, keyframe=True, pcr=25.0)
                seg.feed(trigger)
            except Exception as e:
                errors.append(f"feeder: {e}")

        def _reader():
            try:
                for _ in range(50):
                    if stop_event.is_set():
                        break
                    playlist = seg.get_playlist()
                    if playlist is not None:
                        if not playlist.startswith("#EXTM3U"):
                            errors.append(f"invalid playlist: {playlist[:50]}")
                            return
                        # Try to read a segment from the playlist
                        for line in playlist.splitlines():
                            m = re.match(r"(seg_\d{5}\.ts)", line.strip())
                            if m:
                                data = seg.get_segment(m.group(1))
                                if data is not None and data[0] != TS_SYNC_BYTE:
                                    errors.append(f"bad sync byte in {m.group(1)}")
                                    return
                                break
                    time.sleep(0.01)
            except Exception as e:
                errors.append(f"reader: {e}")

        feeder_thread = threading.Thread(target=_feeder)
        reader_thread = threading.Thread(target=_reader)

        feeder_thread.start()
        reader_thread.start()

        feeder_thread.join(timeout=10)
        reader_thread.join(timeout=10)

        assert not feeder_thread.is_alive(), "feeder thread deadlocked"
        assert not reader_thread.is_alive(), "reader thread deadlocked"
        assert errors == [], f"concurrent errors: {errors}"

        seg.stop()
