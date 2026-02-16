"""
Traffic Manager v1.

Fills empty filler slots in a ScheduledBlock with a filler asset.
Each ad break plays filler from offset 0 for exactly the break duration.
No looping, no state tracking — every break starts from the beginning.

Pure function — no DB writes, no globals.
"""

from __future__ import annotations

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


def fill_ad_blocks(
    block: ScheduledBlock,
    filler_uri: str,
    filler_duration_ms: int,
) -> ScheduledBlock:
    """
    Fill all empty filler placeholders in a ScheduledBlock.

    Each empty filler segment (asset_uri == "") is replaced with a single
    concrete filler segment starting at offset 0 for the break's duration.

    Args:
        block: ScheduledBlock with empty filler placeholders.
        filler_uri: Path to the filler video file.
        filler_duration_ms: Total duration of the filler file in ms.

    Returns:
        New ScheduledBlock with filled segments.

    Raises:
        ValueError: If filler_duration_ms <= 0 or a break exceeds filler length.
    """
    if filler_duration_ms <= 0:
        raise ValueError("filler_duration_ms must be positive")

    new_segments: list[ScheduledSegment] = []

    for seg in block.segments:
        if seg.segment_type == "filler" and seg.asset_uri == "":
            if seg.segment_duration_ms > filler_duration_ms:
                raise ValueError(
                    f"Ad break duration ({seg.segment_duration_ms}ms) exceeds "
                    f"filler duration ({filler_duration_ms}ms)"
                )
            new_segments.append(ScheduledSegment(
                segment_type="filler",
                asset_uri=filler_uri,
                asset_start_offset_ms=0,
                segment_duration_ms=seg.segment_duration_ms,
            ))
        else:
            new_segments.append(seg)

    return ScheduledBlock(
        block_id=block.block_id,
        start_utc_ms=block.start_utc_ms,
        end_utc_ms=block.end_utc_ms,
        segments=tuple(new_segments),
    )
