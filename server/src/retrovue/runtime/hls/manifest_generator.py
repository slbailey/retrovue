"""
Manifest Generator — pure HLS playlist generation from a SegmentRing snapshot.

Converts a SegmentRing window into a valid HLS media playlist string.
No side effects, no system clock calls, no I/O.

Contracts enforced:
    INV-HLS-MANIFEST-LIVE-001           No EXT-X-ENDLIST; TARGETDURATION valid
    INV-HLS-MANIFEST-SEQUENCE-001       MEDIA-SEQUENCE = oldest index; ascending order
    INV-HLS-MANIFEST-PDT-001           PROGRAM-DATE-TIME from segment wall-clock
    INV-HLS-MANIFEST-CHANNEL-SCOPED-001 Identical for all clients
    INV-HLS-MANIFEST-DETERMINISTIC-001  Pure function of ring state
    INV-HLS-MANIFEST-VALID-PLAYLIST-001 Structurally valid HLS
    INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 Sequence never decreases
    INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 Manifest from single atomic snapshot
    INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 No system clock in PDT path
    INV-HLS-DISCONTINUITY-MARKER-001   Discontinuity tag propagation

Canonical contract: docs/contracts/delivery_hls.md §3
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from .segment_ring import LiveSegment, SegmentRing

logger = logging.getLogger(__name__)


def _format_pdt(wall_clock_start_utc_ms: int) -> str:
    """Format a wall-clock millisecond timestamp as ISO 8601 UTC with Z suffix.

    INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001: This function accepts only
    the segment's stored wall_clock_start_utc_ms. No system clock function
    is called.
    """
    dt = datetime.fromtimestamp(wall_clock_start_utc_ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class ManifestGenerator:
    """Generates HLS media playlists from SegmentRing snapshots.

    Pure function with one piece of mutable state: ``_last_emitted_sequence``
    for monotonicity enforcement (INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001).

    INV-HLS-MANIFEST-DETERMINISTIC-001: Given the same ring snapshot,
    ``generate()`` produces byte-identical output. No system clock,
    random, or global state is read.
    """

    def __init__(self, channel_id: str) -> None:
        self._channel_id = channel_id
        self._last_emitted_sequence: int | None = None

    def generate(self, ring: SegmentRing) -> str | None:
        """Generate an HLS media playlist from the ring's current window.

        Returns ``None`` if the ring is empty (caller should return HTTP 503).

        INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001: The manifest is built
        from a single atomic ``ring.window()`` snapshot.

        The manifest includes at most ``ring.manifest_window`` segments
        (the most recent ones).  Grace segments remain in the ring for
        fetch-after-eviction protection but do not appear in the playlist.
        """
        # Single atomic snapshot
        all_segments = ring.window()

        if not all_segments:
            return None

        # Show only the manifest_window most recent segments
        manifest_count = ring.manifest_window
        if len(all_segments) > manifest_count:
            segments = all_segments[-manifest_count:]
        else:
            segments = all_segments

        return self._build_playlist(segments)

    def _build_playlist(self, segments: list[LiveSegment]) -> str:
        """Build the playlist string from an ordered list of segments.

        INV-HLS-MANIFEST-VALID-PLAYLIST-001: Output contains all required tags.
        INV-HLS-MANIFEST-LIVE-001: No EXT-X-ENDLIST.
        INV-HLS-MANIFEST-SEQUENCE-001: Segments in ascending index order.
        """
        # INV-HLS-MANIFEST-SEQUENCE-001: MEDIA-SEQUENCE = oldest index
        media_sequence = segments[0].index

        # INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001: never decrease
        if self._last_emitted_sequence is not None and media_sequence < self._last_emitted_sequence:
            logger.error(
                "INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001: sequence would decrease "
                "from %d to %d for channel %s — clamping",
                self._last_emitted_sequence, media_sequence, self._channel_id,
            )
            media_sequence = self._last_emitted_sequence
        self._last_emitted_sequence = media_sequence

        # INV-HLS-MANIFEST-LIVE-001: TARGETDURATION >= ceil(max EXTINF)
        max_duration_s = max(seg.duration_ms / 1000.0 for seg in segments)
        target_duration = max(math.ceil(max_duration_s), 1)

        lines: list[str] = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target_duration}",
            f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
        ]

        for i, seg in enumerate(segments):
            # INV-HLS-DISCONTINUITY-MARKER-001: emit before discontinuous segments
            if seg.discontinuity:
                lines.append("#EXT-X-DISCONTINUITY")

            # INV-HLS-MANIFEST-PDT-001: PDT before first segment
            if i == 0:
                pdt = _format_pdt(seg.wall_clock_start_utc_ms)
                lines.append(f"#EXT-X-PROGRAM-DATE-TIME:{pdt}")

            # EXTINF + segment URI
            duration_s = seg.duration_ms / 1000.0
            lines.append(f"#EXTINF:{duration_s:.3f},")
            lines.append(f"seg_{seg.index:05d}.ts")

        # INV-HLS-MANIFEST-LIVE-001: no EXT-X-ENDLIST
        return "\n".join(lines) + "\n"
