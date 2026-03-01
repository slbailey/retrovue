"""
HLS Writer — Pure Python MPEG-TS segmenter.

Receives raw MPEG-TS bytes (from the existing single FFmpeg pipe:1 output),
splits them into HLS segments by detecting keyframes, and maintains a
rolling live.m3u8 playlist.  No additional FFmpeg process is spawned.

Integration points:
  1. ChannelStream reader loop calls hls_manager.feed(channel_id, chunk) on
     every TS chunk — zero-copy tee to both HTTP viewers and HLS.
  2. If no raw-TS viewer exists, the /hls/ endpoint starts the channel's
     FFmpeg itself and pipes output exclusively to the segmenter.
"""

from __future__ import annotations

import logging
import os
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MPEG-TS constants
# ---------------------------------------------------------------------------
TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47

# H.264 NAL unit types that indicate an IDR (keyframe)
_H264_IDR_NAL_TYPES = {5}  # IDR slice
# Also treat SPS (7) as keyframe indicator — encoders emit SPS before IDR
_H264_KEYFRAME_NAL_TYPES = _H264_IDR_NAL_TYPES | {7}


@dataclass(frozen=True, slots=True)
class HLSSegment:
    """In-memory HLS segment."""
    name: str       # e.g. "seg_00042.ts"
    duration: float  # seconds
    data: bytes      # raw TS payload


def _is_keyframe_packet(packet: bytes) -> bool:
    """Detect whether an MPEG-TS packet contains the start of an H.264 keyframe.

    We check:
      1. Adaptation field has random_access_indicator set, OR
      2. PES payload starts with an H.264 IDR or SPS NAL unit.

    This is intentionally lenient — false positives just cause a slightly
    early segment split, which is harmless.
    """
    if len(packet) < TS_PACKET_SIZE or packet[0] != TS_SYNC_BYTE:
        return False

    # Byte 1-2: flags
    pusi = (packet[1] & 0x40) != 0  # payload_unit_start_indicator
    # Byte 3: adaptation_field_control + continuity_counter
    afc = (packet[3] >> 4) & 0x03

    offset = 4  # start of adaptation field or payload

    # --- Check adaptation field for random_access_indicator ---
    has_adaptation = afc in (2, 3)
    has_payload = afc in (1, 3)
    rai = False

    if has_adaptation:
        af_len = packet[4]
        if af_len > 0 and len(packet) > 5:
            af_flags = packet[5]
            rai = (af_flags & 0x40) != 0  # random_access_indicator
        offset = 5 + af_len

    if rai:
        return True

    # --- If PUSI, peek into PES for H.264 NAL types ---
    if pusi and has_payload and offset < len(packet) - 10:
        payload = packet[offset:]
        # PES start code: 00 00 01
        if payload[:3] == b'\x00\x00\x01':
            # Skip PES header to get to ES data
            pes_header_data_len = payload[8] if len(payload) > 8 else 0
            es_start = 9 + pes_header_data_len
            es = payload[es_start:]
            # Look for H.264 start codes in first ~32 bytes of ES data
            for i in range(min(len(es) - 4, 32)):
                if es[i:i+3] == b'\x00\x00\x01' or es[i:i+4] == b'\x00\x00\x00\x01':
                    nal_offset = i + 3 if es[i:i+3] == b'\x00\x00\x01' else i + 4
                    if nal_offset < len(es):
                        nal_type = es[nal_offset] & 0x1F
                        if nal_type in _H264_KEYFRAME_NAL_TYPES:
                            return True
    return False


class HLSSegmenter:
    """Pure-Python MPEG-TS → HLS segmenter.

    Call :meth:`feed` with raw TS bytes.  The segmenter accumulates packets,
    detects keyframes, and stores segments in memory.
    """

    def __init__(
        self,
        channel_id: str,
        target_duration: float = 2.0,
        max_segments: int = 10,
    ):
        self.channel_id = channel_id
        self.target_duration = target_duration
        self.max_segments = max_segments

        self._lock = threading.Lock()
        self._running = False

        # Current segment state
        self._seg_index = 0
        self._seg_buffer = bytearray()
        self._seg_start_time: Optional[float] = None  # wall-clock when segment started
        self._seg_pkt_count = 0

        # In-memory segment storage (bounded)
        self._segments: deque[HLSSegment] = deque(maxlen=max_segments)
        self._media_sequence = 0
        self._playlist_ready = threading.Event()

        # Partial packet buffer (in case feed() gets non-188-aligned data)
        self._leftover = bytearray()

        # PCR-based timing
        self._last_pcr: Optional[float] = None
        self._seg_start_pcr: Optional[float] = None

    def is_running(self) -> bool:
        return self._running

    def get_playlist(self) -> str | None:
        """Return current M3U8 playlist string, or None if no segments yet."""
        with self._lock:
            if not self._segments:
                return None
            return self._generate_playlist()

    def get_segment(self, name: str) -> bytes | None:
        """Return segment data by name, or None if not found/evicted."""
        with self._lock:
            for seg in self._segments:
                if seg.name == name:
                    return seg.data
            return None

    def has_playlist(self) -> bool:
        """Return True if at least one segment has been finalized."""
        return self._playlist_ready.is_set()

    def wait_for_playlist(self, timeout: float) -> bool:
        """Block until first segment is ready, or timeout. Returns True if ready."""
        return self._playlist_ready.wait(timeout=timeout)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._seg_start_time = time.monotonic()
            logger.info("[HLS %s] Segmenter started (in-memory)", self.channel_id)

    def feed(self, data: bytes) -> None:
        """Feed raw MPEG-TS bytes.  Thread-safe."""
        if not self._running:
            return

        with self._lock:
            buf = self._leftover + data
            self._leftover = bytearray()

            pos = 0
            length = len(buf)

            while pos + TS_PACKET_SIZE <= length:
                # Re-sync if needed
                if buf[pos] != TS_SYNC_BYTE:
                    sync = buf.find(bytes([TS_SYNC_BYTE]), pos)
                    if sync == -1:
                        break
                    pos = sync
                    if pos + TS_PACKET_SIZE > length:
                        break

                packet = bytes(buf[pos:pos + TS_PACKET_SIZE])
                pos += TS_PACKET_SIZE

                # Extract PCR if present
                pcr = self._extract_pcr(packet)
                if pcr is not None:
                    self._last_pcr = pcr
                    if self._seg_start_pcr is None:
                        self._seg_start_pcr = pcr

                # Check for segment split: keyframe + enough duration
                seg_duration = self._current_seg_duration()
                if (
                    seg_duration >= self.target_duration
                    and _is_keyframe_packet(packet)
                    and len(self._seg_buffer) > 0
                ):
                    self._finalize_segment(seg_duration)

                self._seg_buffer.extend(packet)
                self._seg_pkt_count += 1

            # Save leftover bytes
            if pos < length:
                self._leftover = bytearray(buf[pos:])

    def _extract_pcr(self, packet: bytes) -> Optional[float]:
        """Extract PCR from adaptation field if present. Returns seconds."""
        if len(packet) < TS_PACKET_SIZE:
            return None
        afc = (packet[3] >> 4) & 0x03
        if afc not in (2, 3):
            return None
        af_len = packet[4]
        if af_len < 7:  # Need at least 1 flags + 6 PCR bytes
            return None
        af_flags = packet[5]
        if not (af_flags & 0x10):  # PCR_flag
            return None
        # PCR is 6 bytes at offset 6
        pcr_bytes = packet[6:12]
        pcr_base = (pcr_bytes[0] << 25) | (pcr_bytes[1] << 17) | (pcr_bytes[2] << 9) | (pcr_bytes[3] << 1) | (pcr_bytes[4] >> 7)
        pcr_ext = ((pcr_bytes[4] & 0x01) << 8) | pcr_bytes[5]
        pcr = pcr_base / 90000.0 + pcr_ext / 27000000.0
        return pcr

    def _current_seg_duration(self) -> float:
        """Estimate current segment duration using PCR or wall-clock.

        PCR discontinuities (e.g. when AIR switches content) cause the PCR
        to jump backwards or forwards by a large amount.  When detected,
        we reset the PCR baseline and fall back to wall-clock for the
        current segment to avoid emitting absurd durations.
        """
        if self._seg_start_pcr is not None and self._last_pcr is not None:
            dur = self._last_pcr - self._seg_start_pcr
            # Detect PCR discontinuity: negative or implausibly large (>60s for a 6s target)
            max_plausible = max(self.target_duration * 10, 120.0)
            if dur < 0 or dur > max_plausible:
                # PCR discontinuity — reset baseline, fall through to wall-clock
                logger.debug(
                    "[HLS %s] PCR discontinuity detected (dur=%.1fs), resetting to wall-clock",
                    self.channel_id, dur,
                )
                self._seg_start_pcr = self._last_pcr
                # Fall through to wall-clock
            else:
                return dur
        # Fallback: wall-clock
        if self._seg_start_time is not None:
            return time.monotonic() - self._seg_start_time
        return 0.0

    def _finalize_segment(self, duration: float) -> None:
        """Store current buffer as an in-memory segment."""
        seg_name = f"seg_{self._seg_index:05d}.ts"
        seg_data = bytes(self._seg_buffer)

        # deque(maxlen) auto-evicts leftmost on append when full;
        # increment media_sequence to track the first segment's sequence number
        if len(self._segments) == self._segments.maxlen:
            self._media_sequence += 1
        self._segments.append(HLSSegment(name=seg_name, duration=duration, data=seg_data))
        self._seg_index += 1

        if not self._playlist_ready.is_set():
            self._playlist_ready.set()

        logger.debug(
            "[HLS %s] Segment %s stored: %.2fs, %d bytes",
            self.channel_id, seg_name, duration, len(seg_data),
        )

        # Reset for next segment
        self._seg_buffer = bytearray()
        self._seg_pkt_count = 0
        self._seg_start_time = time.monotonic()
        self._seg_start_pcr = self._last_pcr

    def _generate_playlist(self) -> str:
        """Generate m3u8 string from in-memory segments. MUST be called with _lock held."""
        max_dur = max(seg.duration for seg in self._segments)
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{int(max_dur) + 1}",
            f"#EXT-X-MEDIA-SEQUENCE:{self._media_sequence}",
        ]
        for seg in self._segments:
            lines.append(f"#EXTINF:{seg.duration:.3f},")
            lines.append(seg.name)
        return "\n".join(lines) + "\n"

    def stop(self) -> None:
        """Stop segmenter. Pure teardown — discard in-flight buffer, release segments."""
        self._running = False
        with self._lock:
            self._seg_buffer = bytearray()
            self._seg_pkt_count = 0
            self._segments.clear()
            self._playlist_ready.clear()
        logger.info("[HLS %s] Segmenter stopped", self.channel_id)


class HLSManager:
    """Manages per-channel HLS segmenters.

    Two integration modes:

    1. **Tee mode** (preferred): ChannelStream reader calls
       ``hls_manager.feed(channel_id, chunk)`` on every TS chunk so the
       same FFmpeg process serves both raw-TS viewers and HLS.

    2. **Standalone mode**: When no raw-TS viewer is connected, the HLS
       endpoint starts the channel's FFmpeg itself and pipes output
       exclusively to the segmenter.  When a raw-TS viewer later
       connects, the standalone FFmpeg is killed and tee mode takes over.
    """

    def __init__(self):
        self._segmenters: dict[str, HLSSegmenter] = {}
        self._lock = threading.Lock()
        # Standalone FFmpeg processes (channel_id -> subprocess.Popen)
        self._standalone_procs: dict[str, "subprocess.Popen"] = {}  # type: ignore[name-defined]
        self._standalone_threads: dict[str, threading.Thread] = {}

    def get_or_create(self, channel_id: str) -> HLSSegmenter:
        """Get or create a segmenter for a channel."""
        with self._lock:
            if channel_id not in self._segmenters:
                seg = HLSSegmenter(channel_id)
                self._segmenters[channel_id] = seg
            return self._segmenters[channel_id]

    # Keep old name as alias for PD compatibility
    def get_writer(self, channel_id: str) -> HLSSegmenter:
        return self.get_or_create(channel_id)

    def feed(self, channel_id: str, data: bytes) -> None:
        """Feed TS data to a channel's segmenter (called from ChannelStream).

        If no segmenter exists for this channel, this is a no-op (cheap).
        """
        with self._lock:
            seg = self._segmenters.get(channel_id)
        if seg and seg.is_running():
            seg.feed(data)

    def start_standalone(
        self,
        channel_id: str,
        ffmpeg_cmd: list[str],
    ) -> HLSSegmenter:
        """Start a standalone FFmpeg→segmenter pipeline for HLS-only mode.

        ``ffmpeg_cmd`` should be the result of ``build_cmd(...)`` which outputs
        to ``pipe:1``.  We launch the process and read stdout into the segmenter.
        """
        import subprocess

        seg = self.get_or_create(channel_id)
        if not seg.is_running():
            seg.start()

        with self._lock:
            if channel_id in self._standalone_procs:
                proc = self._standalone_procs[channel_id]
                if proc.poll() is None:
                    return seg  # Already running

        logger.info("[HLS %s] Starting standalone FFmpeg for HLS-only", channel_id)
        proc = subprocess.Popen(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )

        def _reader():
            try:
                while proc.poll() is None:
                    chunk = proc.stdout.read(TS_PACKET_SIZE * 7)
                    if not chunk:
                        break
                    seg.feed(chunk)
            except Exception as e:
                logger.warning("[HLS %s] Standalone reader error: %s", channel_id, e)
            finally:
                logger.info("[HLS %s] Standalone FFmpeg exited (rc=%s)", channel_id, proc.returncode)

        def _stderr_drain():
            try:
                for line in proc.stderr:
                    msg = line.decode("utf-8", errors="replace").strip()
                    if msg and ("error" in msg.lower() or "warning" in msg.lower()):
                        logger.warning("[HLS %s] FFmpeg: %s", channel_id, msg)
            except Exception:
                pass

        t = threading.Thread(target=_reader, name=f"hls-standalone-{channel_id}", daemon=True)
        t.start()
        threading.Thread(target=_stderr_drain, daemon=True).start()

        with self._lock:
            self._standalone_procs[channel_id] = proc
            self._standalone_threads[channel_id] = t

        return seg

    def kill_standalone(self, channel_id: str) -> None:
        """Kill a standalone FFmpeg if running (e.g. when tee mode takes over)."""
        with self._lock:
            proc = self._standalone_procs.pop(channel_id, None)
            self._standalone_threads.pop(channel_id, None)
        if proc and proc.poll() is None:
            logger.info("[HLS %s] Killing standalone FFmpeg (tee mode taking over)", channel_id)
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop_channel(self, channel_id: str) -> None:
        """Stop segmenter and standalone process for a channel."""
        self.kill_standalone(channel_id)
        with self._lock:
            seg = self._segmenters.pop(channel_id, None)
        if seg:
            seg.stop()

    def stop_all(self) -> None:
        """Stop everything."""
        with self._lock:
            segmenters = list(self._segmenters.values())
            procs = list(self._standalone_procs.values())
            self._segmenters.clear()
            self._standalone_procs.clear()
            self._standalone_threads.clear()
        for proc in procs:
            try:
                proc.terminate()
            except Exception:
                pass
        for seg in segmenters:
            seg.stop()
