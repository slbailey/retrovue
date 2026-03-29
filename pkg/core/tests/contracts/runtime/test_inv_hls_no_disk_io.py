"""Contract tests for INV-HLS-NO-DISK-IO-001.

HLS segment delivery MUST be entirely in-memory. No segment data is written to
disk, referenced by file path, or buffered through a filesystem abstraction.

INV-HLS-NO-DISK-IO-001: LiveSegment.data is bytes, never a file path or handle.
    Enforced both statically (source inspection) and dynamically (runtime checks).
"""

from __future__ import annotations

import inspect
import re

import dataclasses

import pytest

from retrovue.runtime.hls.segment_ring import LiveSegment, SegmentRing
from retrovue.runtime.hls.segmenter import HlsSegmenter, TS_PACKET_SIZE, TS_SYNC_BYTE
from retrovue.runtime.hls.manifest_generator import ManifestGenerator


# ---------------------------------------------------------------------------
# TS helpers
# ---------------------------------------------------------------------------

def _make_ts_packet(
    pid: int = 0x100,
    payload_unit_start: bool = False,
    keyframe: bool = False,
) -> bytes:
    """Build a minimal valid 188-byte TS packet."""
    sync = TS_SYNC_BYTE
    flags = 0x40 if payload_unit_start else 0x00
    b1 = (pid >> 8) & 0x1F | flags
    b2 = pid & 0xFF
    b3 = 0x10  # payload only, continuity=0
    adaptation = b""
    if keyframe:
        # adaptation field with random_access_indicator set
        adaptation = bytes([0x02, 0x40])  # length=2, RAI flag
        b3 = 0x30  # adaptation + payload
    payload_len = TS_PACKET_SIZE - 4 - len(adaptation)
    payload = b"\x00" * payload_len
    pkt = bytes([sync, b1, b2, b3]) + adaptation + payload
    assert len(pkt) == TS_PACKET_SIZE
    return pkt


def _make_pes_header() -> bytes:
    """Minimal PES header for video PID."""
    return bytes([
        0x00, 0x00, 0x01,  # start code prefix
        0xE0,              # stream_id: video
        0x00, 0x00,        # PES packet length (0 = unbounded)
        0x80, 0x00, 0x00,  # flags, PTS_DTS_flags=0, header_data_length=0
    ])


def _push_segment(seg: HlsSegmenter, ring: SegmentRing) -> None:
    """Feed enough keyframe TS data to flush one segment."""
    # First packet: PES header in payload, keyframe
    first_pkt = _make_ts_packet(pid=0x100, payload_unit_start=True, keyframe=True)
    seg.feed(first_pkt)
    # Force segment boundary by feeding a second keyframe
    second_pkt = _make_ts_packet(pid=0x100, payload_unit_start=True, keyframe=True)
    seg.feed(second_pkt)


# ---------------------------------------------------------------------------
# Static analysis: source must not contain disk I/O primitives
# ---------------------------------------------------------------------------

DISK_IO_PATTERNS = [
    r"\bopen\s*\(",         # open() builtin
    r"\bos\.path\b",        # os.path.*
    r"\btempfile\b",        # tempfile module
    r"\bshutil\b",          # shutil module
    r"pathlib\.Path",       # pathlib.Path
    r"io\.FileIO\b",        # io.FileIO
    r"io\.BufferedWriter\b", # io.BufferedWriter
]


@pytest.mark.contract
def test_segment_ring_has_no_disk_io_in_source():
    """INV-HLS-NO-DISK-IO-001: SegmentRing source contains no disk I/O operations."""
    src = inspect.getsource(SegmentRing)
    for pattern in DISK_IO_PATTERNS:
        matches = re.findall(pattern, src)
        assert not matches, (
            f"INV-HLS-NO-DISK-IO-001 violated in SegmentRing: "
            f"found disk I/O pattern '{pattern}' → {matches}"
        )


@pytest.mark.contract
def test_hls_segmenter_has_no_disk_io_in_source():
    """INV-HLS-NO-DISK-IO-001: HlsSegmenter source contains no disk I/O operations."""
    src = inspect.getsource(HlsSegmenter)
    for pattern in DISK_IO_PATTERNS:
        matches = re.findall(pattern, src)
        assert not matches, (
            f"INV-HLS-NO-DISK-IO-001 violated in HlsSegmenter: "
            f"found disk I/O pattern '{pattern}' → {matches}"
        )


@pytest.mark.contract
def test_manifest_generator_has_no_disk_io_in_source():
    """INV-HLS-NO-DISK-IO-001: ManifestGenerator source contains no disk I/O operations."""
    src = inspect.getsource(ManifestGenerator)
    for pattern in DISK_IO_PATTERNS:
        matches = re.findall(pattern, src)
        assert not matches, (
            f"INV-HLS-NO-DISK-IO-001 violated in ManifestGenerator: "
            f"found disk I/O pattern '{pattern}' → {matches}"
        )


@pytest.mark.contract
def test_live_segment_has_no_disk_io_in_source():
    """INV-HLS-NO-DISK-IO-001: LiveSegment source contains no disk I/O operations."""
    src = inspect.getsource(LiveSegment)
    for pattern in DISK_IO_PATTERNS:
        matches = re.findall(pattern, src)
        assert not matches, (
            f"INV-HLS-NO-DISK-IO-001 violated in LiveSegment: "
            f"found disk I/O pattern '{pattern}' → {matches}"
        )


# ---------------------------------------------------------------------------
# Dynamic: LiveSegment construction enforces bytes-only data
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_live_segment_rejects_string_data():
    """INV-HLS-NO-DISK-IO-001: LiveSegment raises TypeError if data is a string (e.g. a file path)."""
    with pytest.raises(TypeError, match="INV-HLS-NO-DISK-IO-001"):
        LiveSegment(
            channel_id="test",
            index=0,
            wall_clock_start_utc_ms=1_000_000,
            duration_ms=2000,
            byte_count=12,
            data="/tmp/segment_0.ts",  # type: ignore[arg-type]  # file path, not bytes
        )


@pytest.mark.contract
def test_live_segment_rejects_bytearray_data():
    """INV-HLS-NO-DISK-IO-001: LiveSegment data must be bytes, not bytearray."""
    raw = bytearray(b"\x47" * 188)
    with pytest.raises(TypeError, match="INV-HLS-NO-DISK-IO-001"):
        LiveSegment(
            channel_id="test",
            index=0,
            wall_clock_start_utc_ms=1_000_000,
            duration_ms=2000,
            byte_count=len(raw),
            data=raw,  # type: ignore[arg-type]
        )


@pytest.mark.contract
def test_live_segment_rejects_none_data():
    """INV-HLS-NO-DISK-IO-001: LiveSegment data cannot be None."""
    with pytest.raises(TypeError, match="INV-HLS-NO-DISK-IO-001"):
        LiveSegment(
            channel_id="test",
            index=0,
            wall_clock_start_utc_ms=1_000_000,
            duration_ms=2000,
            byte_count=0,
            data=None,  # type: ignore[arg-type]
        )


@pytest.mark.contract
def test_live_segment_accepts_bytes_data():
    """INV-HLS-NO-DISK-IO-001: LiveSegment construction succeeds with valid bytes data."""
    raw = b"\x47" * 188
    seg = LiveSegment(
        channel_id="test",
        index=0,
        wall_clock_start_utc_ms=1_000_000,
        duration_ms=2000,
        byte_count=len(raw),
        data=raw,
    )
    assert isinstance(seg.data, bytes)
    assert seg.data == raw


# ---------------------------------------------------------------------------
# Dynamic: SegmentRing holds bytes in-memory, not file handles
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_segment_ring_stores_data_as_bytes():
    """INV-HLS-NO-DISK-IO-001: Segments retrieved from SegmentRing carry bytes data."""
    ring = SegmentRing(capacity=5, manifest_window=3)
    raw = b"\x47" * 188
    seg = LiveSegment(
        channel_id="ch1",
        index=0,
        wall_clock_start_utc_ms=1_000_000,
        duration_ms=2000,
        byte_count=len(raw),
        data=raw,
    )
    ring.push(seg)
    retrieved = ring.window()
    assert len(retrieved) == 1
    assert isinstance(retrieved[0].data, bytes), (
        "INV-HLS-NO-DISK-IO-001: segment data in ring is not bytes"
    )
    assert retrieved[0].data == raw


@pytest.mark.contract
def test_segment_ring_window_all_bytes():
    """INV-HLS-NO-DISK-IO-001: All segments in SegmentRing window are bytes."""
    ring = SegmentRing(capacity=5, manifest_window=3)
    for i in range(4):
        raw = bytes([i % 256]) * 188
        ring.push(LiveSegment(
            channel_id="ch1",
            index=i,
            wall_clock_start_utc_ms=1_000_000 + i * 2000,
            duration_ms=2000,
            byte_count=len(raw),
            data=raw,
        ))
    for seg in ring.window():
        assert isinstance(seg.data, bytes), (
            f"INV-HLS-NO-DISK-IO-001: segment {seg.index} data is not bytes"
        )


@pytest.mark.contract
def test_segment_ring_get_returns_bytes():
    """INV-HLS-NO-DISK-IO-001: ring.get(index) returns segment with bytes data."""
    ring = SegmentRing(capacity=5, manifest_window=3)
    raw = b"\x47" * (188 * 3)
    ring.push(LiveSegment(
        channel_id="ch1",
        index=7,
        wall_clock_start_utc_ms=2_000_000,
        duration_ms=3000,
        byte_count=len(raw),
        data=raw,
    ))
    seg = ring.get(7)
    assert seg is not None
    assert isinstance(seg.data, bytes), (
        "INV-HLS-NO-DISK-IO-001: ring.get() returned non-bytes data"
    )


# ---------------------------------------------------------------------------
# Dynamic: LiveSegment is immutable (frozen dataclass — no post-construction swap)
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_live_segment_data_is_immutable():
    """INV-HLS-NO-DISK-IO-001 + INV-HLS-SEGMENT-IMMUTABLE-001: Cannot replace bytes with file path after construction."""
    raw = b"\x47" * 188
    seg = LiveSegment(
        channel_id="ch1",
        index=0,
        wall_clock_start_utc_ms=1_000_000,
        duration_ms=2000,
        byte_count=len(raw),
        data=raw,
    )
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        seg.data = "/tmp/evil.ts"  # frozen dataclass — direct assignment must raise


# ---------------------------------------------------------------------------
# Integration: HlsSegmenter produces segments whose data is bytes
# ---------------------------------------------------------------------------

@pytest.mark.contract
def test_hls_segmenter_produces_bytes_not_paths():
    """INV-HLS-NO-DISK-IO-001: Segments produced by HlsSegmenter have bytes data."""
    ring = SegmentRing(capacity=5, manifest_window=3)
    seg = HlsSegmenter(
        channel_id="ch-disk-io-test",
        segment_ring=ring,
        target_duration_ms=2000,
    )
    # Feed two keyframes to flush a segment
    _push_segment(seg, ring)
    segments = ring.window()
    if segments:
        for s in segments:
            assert isinstance(s.data, bytes), (
                f"INV-HLS-NO-DISK-IO-001: HlsSegmenter produced segment with "
                f"non-bytes data: {type(s.data)}"
            )
