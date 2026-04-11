"""
HLS Segmenter — canonical MPEG-TS → HLS segment producer.

Consumes a continuous MPEG-TS byte stream and produces completed
LiveSegment objects for a SegmentRing.

Contracts enforced:
    INV-HLS-SEGMENT-IDENTITY-001       Monotonic channel-scoped indices
    INV-HLS-SEGMENT-IMMUTABLE-001      Completed segments are frozen
    INV-HLS-SEGMENT-KEYFRAME-001       Keyframe-aligned boundaries
    INV-HLS-SEGMENT-SELFCONTAINED-001  Structurally decodable (valid TS)
    INV-HLS-SEGMENT-WALLCLOCK-001      Editorial timeline from BlockPlan
    INV-HLS-SEGMENT-PTS-CONTINUITY-001 PTS continuity / discontinuity detection
    INV-HLS-SEGMENT-DURATION-BOUNDS-001 Duration within tolerance
    INV-HLS-SEGMENT-INDEX-GUARD-001    Index counter integrity
    INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 Timeline audit at completion
    INV-HLS-RESTART-DISCONTINUITY-001  Discontinuity on restart
    INV-HLS-PRODUCER-SEGMENT-FLOW-001  Stall visibility

Canonical contract: docs/contracts/delivery_hls.md §1
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from .segment_ring import LiveSegment, SegmentRing

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MPEG-TS constants
# ---------------------------------------------------------------------------
TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47

# H.264 NAL unit types indicating keyframe
_H264_IDR_NAL_TYPES = {5}
_H264_KEYFRAME_NAL_TYPES = _H264_IDR_NAL_TYPES | {7}  # IDR + SPS


# ---------------------------------------------------------------------------
# TS packet inspection helpers
# ---------------------------------------------------------------------------


def is_keyframe_packet(packet: bytes) -> bool:
    """Detect whether a 188-byte TS packet marks a keyframe boundary.

    Checks adaptation field random_access_indicator and, as fallback,
    PES payload for H.264 IDR/SPS NAL units.

    INV-HLS-SEGMENT-KEYFRAME-001: Segments must begin on keyframes.
    """
    if len(packet) < TS_PACKET_SIZE or packet[0] != TS_SYNC_BYTE:
        return False

    pusi = (packet[1] & 0x40) != 0
    afc = (packet[3] >> 4) & 0x03

    offset = 4
    has_adaptation = afc in (2, 3)
    has_payload = afc in (1, 3)

    if has_adaptation:
        af_len = packet[4]
        if af_len > 0 and len(packet) > 5:
            af_flags = packet[5]
            if af_flags & 0x40:  # random_access_indicator
                return True
        offset = 5 + af_len

    # Fallback: peek into PES for H.264 NAL types
    if pusi and has_payload and offset < len(packet) - 10:
        payload = packet[offset:]
        if payload[:3] == b"\x00\x00\x01":
            pes_header_data_len = payload[8] if len(payload) > 8 else 0
            es_start = 9 + pes_header_data_len
            es = payload[es_start:]
            for i in range(min(len(es) - 4, 32)):
                if es[i : i + 3] == b"\x00\x00\x01" or es[i : i + 4] == b"\x00\x00\x00\x01":
                    nal_offset = i + 3 if es[i : i + 3] == b"\x00\x00\x01" else i + 4
                    if nal_offset < len(es):
                        nal_type = es[nal_offset] & 0x1F
                        if nal_type in _H264_KEYFRAME_NAL_TYPES:
                            return True
    return False


def extract_pcr(packet: bytes) -> int | None:
    """Extract PCR from adaptation field. Returns 90kHz ticks or None.

    INV-HLS-SEGMENT-PTS-CONTINUITY-001: Integer arithmetic for timing.
    """
    if len(packet) < TS_PACKET_SIZE:
        return None
    afc = (packet[3] >> 4) & 0x03
    if afc not in (2, 3):
        return None
    af_len = packet[4]
    if af_len < 7:
        return None
    af_flags = packet[5]
    if not (af_flags & 0x10):  # PCR_flag
        return None
    # PCR base: 33 bits
    pcr_base = (
        (packet[6] << 25)
        | (packet[7] << 17)
        | (packet[8] << 9)
        | (packet[9] << 1)
        | (packet[10] >> 7)
    )
    return pcr_base  # 90kHz ticks


# ---------------------------------------------------------------------------
# HlsSegmenter
# ---------------------------------------------------------------------------


class HlsSegmenter:
    """Channel-scoped HLS segmenter.

    Consumes MPEG-TS bytes via ``feed()``, detects keyframe-aligned segment
    boundaries, and pushes completed ``LiveSegment`` objects to a ``SegmentRing``.

    Thread-safe: ``feed()`` may be called from one writer thread while the
    ``SegmentRing`` is read from N reader threads.
    """

    def __init__(
        self,
        channel_id: str,
        segment_ring: SegmentRing,
        target_duration_ms: int = 6000,
        max_gop_ms: int = 1000,
        starting_index: int = 0,
        log: logging.Logger | None = None,
        diagnostic_hook: Callable[..., None] | None = None,
    ) -> None:
        self._channel_id = channel_id
        self._ring = segment_ring
        self._target_duration_ms = target_duration_ms
        self._max_gop_ms = max_gop_ms
        self._log = log or logger
        self._diagnostic_hook = diagnostic_hook

        self._lock = threading.Lock()
        self._closed = False

        # --- Segment accumulation state ---
        self._seg_buffer = bytearray()
        self._seg_pkt_count = 0
        self._next_index = starting_index

        # Partial packet buffer for non-188-aligned feed chunks
        self._leftover = bytearray()

        # --- PCR tracking (90kHz integer ticks) ---
        self._last_pcr: int | None = None
        self._seg_start_pcr: int | None = None
        # PCR of last completed segment's end (for continuity check)
        self._prev_segment_end_pcr: int | None = None

        # --- Discontinuity ---
        self._pending_discontinuity = False
        # INV-HLS-RESTART-DISCONTINUITY-001: first segment is always discontinuous
        # (no prior PTS context). reset_for_restart sets this explicitly;
        # initial construction also starts discontinuous.
        self._force_next_discontinuity = True

        # --- BlockPlan timebase (editorial wall-clock) ---
        # Current (mutable) timebase — updated by set_blockplan_timebase().
        self._timebase_start_utc_ms: int = 0
        self._timebase_pcr_origin: int | None = None  # PCR at timebase start
        self._active_block_start_utc_ms: int = 0
        self._active_block_end_utc_ms: int = 0

        # --- INV-HLS-SEGMENT-EDITORIAL-TIMEBASE-IMMUTABILITY-001 ---
        # Per-segment snapshot: frozen when the segment begins accumulating.
        # _finalize_segment() uses these instead of the mutable fields above.
        self._snap_timebase_start_utc_ms: int = 0
        self._snap_timebase_pcr_origin: int | None = None
        self._snap_active_block_start_utc_ms: int = 0
        self._snap_active_block_end_utc_ms: int = 0

        # --- Stall detection ---
        self._last_completed_index: int | None = None
        self._last_completed_monotonic_ms: int | None = None

    def _diag(self, event: str, **fields) -> None:
        if self._diagnostic_hook is None:
            return
        try:
            self._diagnostic_hook(self._channel_id, event, **fields)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: bytes) -> None:
        """Ingest raw MPEG-TS bytes. Thread-safe.

        Tolerates arbitrary chunk boundaries. Only complete 188-byte packets
        are processed.
        """
        if self._closed:
            return

        with self._lock:
            buf = self._leftover + chunk
            self._leftover = bytearray()

            pos = 0
            length = len(buf)

            while pos + TS_PACKET_SIZE <= length:
                # Re-sync on lost alignment
                if buf[pos] != TS_SYNC_BYTE:
                    sync = buf.find(bytes([TS_SYNC_BYTE]), pos)
                    if sync == -1:
                        break
                    pos = sync
                    if pos + TS_PACKET_SIZE > length:
                        break

                packet = bytes(buf[pos : pos + TS_PACKET_SIZE])
                pos += TS_PACKET_SIZE

                self._process_packet(packet)

            # Save partial trailing bytes
            if pos < length:
                self._leftover = bytearray(buf[pos:])

    def close(self) -> None:
        """Stop accepting data. Idempotent."""
        self._closed = True

    def reset_for_restart(self, next_index: int) -> None:
        """Reset for a producer restart.

        INV-HLS-RESTART-DISCONTINUITY-001:
        - Resets PTS continuity tracking
        - Forces next segment to carry discontinuity=True
        - Continues numbering from next_index
        """
        with self._lock:
            self._seg_buffer = bytearray()
            self._seg_pkt_count = 0
            self._leftover = bytearray()
            self._last_pcr = None
            self._seg_start_pcr = None
            self._prev_segment_end_pcr = None
            self._pending_discontinuity = False
            self._force_next_discontinuity = True
            self._next_index = next_index
            self._closed = False
            self._timebase_pcr_origin = None
            self._snap_timebase_pcr_origin = None

    def set_blockplan_timebase(
        self,
        start_utc_ms: int,
        active_block_start_utc_ms: int,
        active_block_end_utc_ms: int,
    ) -> None:
        """Set the editorial wall-clock timebase from BlockPlan.

        INV-HLS-SEGMENT-WALLCLOCK-001: Segments derive wall-clock timestamps
        from this timebase, not from the system clock.

        ``start_utc_ms`` is the editorial air-time of the playout session origin.
        The segmenter maps PCR offsets from this origin to compute per-segment
        wall-clock timestamps.
        """
        with self._lock:
            self._timebase_start_utc_ms = start_utc_ms
            self._active_block_start_utc_ms = active_block_start_utc_ms
            self._active_block_end_utc_ms = active_block_end_utc_ms
            # Capture the current PCR as the origin point for this timebase
            self._timebase_pcr_origin = self._last_pcr

    def last_completed_index(self) -> int | None:
        """Return the index of the most recently completed segment, or None."""
        return self._last_completed_index

    def last_segment_completed_monotonic_ms(self) -> int | None:
        """Return monotonic ms timestamp of the last segment completion.

        INV-HLS-PRODUCER-SEGMENT-FLOW-001: Higher-level code uses this to
        detect stalls.
        """
        return self._last_completed_monotonic_ms

    def _snapshot_timebase(self) -> None:
        """Freeze the current timebase into per-segment snapshot fields.

        INV-HLS-SEGMENT-EDITORIAL-TIMEBASE-IMMUTABILITY-001:
        Once a segment begins accumulation, its editorial wallclock mapping
        is bound to the timebase active at segment start, regardless of
        later blockplan changes. Must be called with lock held.
        """
        self._snap_timebase_start_utc_ms = self._timebase_start_utc_ms
        self._snap_timebase_pcr_origin = self._timebase_pcr_origin
        self._snap_active_block_start_utc_ms = self._active_block_start_utc_ms
        self._snap_active_block_end_utc_ms = self._active_block_end_utc_ms

    # ------------------------------------------------------------------
    # Internal packet processing
    # ------------------------------------------------------------------

    def _process_packet(self, packet: bytes) -> None:
        """Process a single 188-byte TS packet. Must be called with lock held."""
        # Extract PCR if present
        pcr = extract_pcr(packet)
        if pcr is not None:
            # INV-HLS-SEGMENT-PTS-CONTINUITY-001: detect PCR discontinuity
            if self._last_pcr is not None:
                delta = pcr - self._last_pcr
                # Negative or implausibly large jump (>60s in 90kHz ticks)
                max_plausible_ticks = 60 * 90000
                if delta < 0 or delta > max_plausible_ticks:
                    self._pending_discontinuity = True
                    self._seg_start_pcr = pcr

            self._last_pcr = pcr

            if self._seg_start_pcr is None:
                self._seg_start_pcr = pcr
                self._snapshot_timebase()

            if self._timebase_pcr_origin is None:
                self._timebase_pcr_origin = pcr

        # Check for segment split
        seg_duration_ms = self._current_seg_duration_ms()
        if (
            seg_duration_ms >= self._target_duration_ms
            and is_keyframe_packet(packet)
            and len(self._seg_buffer) > 0
        ):
            self._finalize_segment(seg_duration_ms)

        self._seg_buffer.extend(packet)
        self._seg_pkt_count += 1

    def _current_seg_duration_ms(self) -> int:
        """Estimate current segment duration in integer ms from PCR.

        INV-HLS-SEGMENT-PTS-CONTINUITY-001: Integer arithmetic only.
        """
        if self._seg_start_pcr is not None and self._last_pcr is not None:
            delta_ticks = self._last_pcr - self._seg_start_pcr
            if delta_ticks < 0:
                return 0
            # Convert 90kHz ticks to ms: ticks * 1000 / 90000
            return (delta_ticks * 1000) // 90000
        return 0

    def _finalize_segment(self, duration_ms: int) -> None:
        """Complete the current segment and push to the ring.

        Must be called with lock held.
        """
        # INV-HLS-SEGMENT-DURATION-BOUNDS-001: reject zero-duration
        if duration_ms <= 0:
            self._log.error(
                "INV-HLS-SEGMENT-DURATION-BOUNDS-001: zero-duration segment "
                "rejected for channel %s (index=%d)",
                self._channel_id, self._next_index,
            )
            self._seg_buffer = bytearray()
            self._seg_pkt_count = 0
            self._seg_start_pcr = self._last_pcr
            self._snapshot_timebase()
            return

        seg_data = bytes(self._seg_buffer)

        # INV-HLS-SEGMENT-WALLCLOCK-001: derive wall-clock from BlockPlan timebase
        wall_clock_ms = self._compute_wall_clock_ms()

        # Determine discontinuity
        is_discontinuous = self._pending_discontinuity or self._force_next_discontinuity
        self._pending_discontinuity = False
        self._force_next_discontinuity = False

        # INV-HLS-SEGMENT-INDEX-GUARD-001: index increments by exactly 1
        index = self._next_index
        self._next_index += 1

        segment = LiveSegment(
            channel_id=self._channel_id,
            index=index,
            wall_clock_start_utc_ms=wall_clock_ms,
            duration_ms=duration_ms,
            byte_count=len(seg_data),
            data=seg_data,
            discontinuity=is_discontinuous,
        )

        # INV-HLS-RING-PUSH-ATOMIC-001: push to ring
        self._ring.push(segment)
        self._diag(
            "HLS_SEGMENT_META",
            index=index,
            wall_clock_ms=wall_clock_ms,
            duration_ms=duration_ms,
            byte_count=len(seg_data),
            discontinuity=is_discontinuous,
        )

        # INV-HLS-SEGMENT-BLOCK-ALIGNMENT-001: audit against the snapshot block
        # window (the block that was active when this segment started).
        if self._snap_active_block_end_utc_ms > 0:
            if not (self._snap_active_block_start_utc_ms <= wall_clock_ms < self._snap_active_block_end_utc_ms):
                self._log.warning(
                    "INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001: segment %d wall_clock %d "
                    "outside active block [%d, %d) for channel %s",
                    index, wall_clock_ms,
                    self._snap_active_block_start_utc_ms, self._snap_active_block_end_utc_ms,
                    self._channel_id,
                )
                self._diag(
                    "INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001",
                    index=index,
                    wall_clock_ms=wall_clock_ms,
                    active_block_start_utc_ms=self._snap_active_block_start_utc_ms,
                    active_block_end_utc_ms=self._snap_active_block_end_utc_ms,
                )

        # Update tracking state
        self._last_completed_index = index
        self._prev_segment_end_pcr = self._last_pcr

        # INV-HLS-PRODUCER-SEGMENT-FLOW-001: record completion time
        # Use a simple monotonic counter — actual monotonic clock injection
        # happens at integration time. For now, just record that it happened.
        import time
        self._last_completed_monotonic_ms = int(time.monotonic() * 1000)

        self._log.debug(
            "[HLS %s] Segment %d completed: %dms, %d bytes, disc=%s",
            self._channel_id, index, duration_ms, len(seg_data), is_discontinuous,
        )

        # Reset for next segment
        self._seg_buffer = bytearray()
        self._seg_pkt_count = 0
        self._seg_start_pcr = self._last_pcr
        self._snapshot_timebase()

    def _compute_wall_clock_ms(self) -> int:
        """Derive wall-clock timestamp from frozen per-segment timebase snapshot.

        INV-HLS-SEGMENT-WALLCLOCK-001: No system clock calls.
        INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001: Derived from editorial timebase.
        INV-HLS-SEGMENT-EDITORIAL-TIMEBASE-IMMUTABILITY-001: Uses the
        snapshot captured when the segment began, not the current mutable
        timebase.
        """
        if self._snap_timebase_pcr_origin is not None and self._seg_start_pcr is not None:
            pcr_offset_ticks = self._seg_start_pcr - self._snap_timebase_pcr_origin
            pcr_offset_ms = (pcr_offset_ticks * 1000) // 90000
            return self._snap_timebase_start_utc_ms + pcr_offset_ms

        # Fallback: use snapshot start directly (first segment case)
        return self._snap_timebase_start_utc_ms
