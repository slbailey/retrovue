"""Clock-driven frame selection for VFR inputs.

INV-CADENCE-INPUT-VFR-FORBIDDEN-001: VFR mode uses the output clock
as sole authority for frame selection. Source PTS timing is NOT used
to drive selection — only to identify the nearest content frame.
"""

from __future__ import annotations

from typing import List, Optional


def clock_driven_frame_select(
    output_time_us: int,
    decoded_frames: List[tuple[int, int]],
) -> Optional[int]:
    """Select a frame for the given output time using clock-driven strategy.

    Args:
        output_time_us: Current output clock time in microseconds (monotonic,
            derived from output frame rate, NOT from source PTS).
        decoded_frames: List of (source_frame_index, content_time_us) pairs.
            content_time_us is derived from accumulated source PTS deltas.

    Returns:
        source_frame_index of the frame whose content_time_us is the
        largest value not exceeding output_time_us, or None if no
        eligible frame exists.
    """
    best_index: Optional[int] = None
    best_ct = -1
    for frame_index, content_time_us in decoded_frames:
        if content_time_us <= output_time_us and content_time_us > best_ct:
            best_ct = content_time_us
            best_index = frame_index
    return best_index
