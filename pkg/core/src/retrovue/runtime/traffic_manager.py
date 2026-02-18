"""
Traffic Manager v2.

Fills empty filler slots in a ScheduledBlock with real interstitial
assets from the database, respecting channel policy (allowed types,
cooldowns, daily caps).

Falls back to the static filler file when no interstitials are available.

Leftover time within each ad break is distributed evenly as black pad
between spots (INV-BREAK-PAD-DISTRIBUTED-001).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

if TYPE_CHECKING:
    from retrovue.catalog.db_asset_library import DatabaseAssetLibrary


def fill_ad_blocks(
    block: ScheduledBlock,
    filler_uri: str,
    filler_duration_ms: int,
    asset_library: DatabaseAssetLibrary | None = None,
) -> ScheduledBlock:
    """
    Fill all empty filler placeholders in a ScheduledBlock.

    If asset_library is provided, selects real interstitials (commercials,
    promos, etc.) from the database, respecting channel policy. Any
    leftover time is distributed as evenly-spaced black pads between spots.

    If asset_library is None or returns no candidates, falls back to
    the static filler file (v1 behavior).

    Args:
        block: ScheduledBlock with empty filler placeholders.
        filler_uri: Path to the fallback filler video file.
        filler_duration_ms: Total duration of the fallback filler file in ms.
        asset_library: Optional DatabaseAssetLibrary for real interstitial selection.

    Returns:
        New ScheduledBlock with filled segments.
    """
    if filler_duration_ms <= 0:
        raise ValueError("filler_duration_ms must be positive")

    new_segments: list[ScheduledSegment] = []

    for seg in block.segments:
        if seg.segment_type == "filler" and seg.asset_uri == "":
            if asset_library is not None:
                filled = _fill_break_with_interstitials(
                    break_duration_ms=seg.segment_duration_ms,
                    asset_library=asset_library,
                )
                if filled:
                    new_segments.extend(filled)
                    continue

            # Fallback: static filler (v1 behavior)
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


def _fill_break_with_interstitials(
    break_duration_ms: int,
    asset_library: DatabaseAssetLibrary,
) -> list[ScheduledSegment] | None:
    """
    Fill a single ad break with interstitials from the asset library.

    Packs spots until the break is full (or no more fit), then distributes
    remaining time as evenly-spaced black pads between spots.

    Returns None if no interstitials were found (caller falls back to v1).
    """
    remaining_ms = break_duration_ms
    picks: list[tuple[str, int, str]] = []  # (uri, duration_ms, asset_type)

    while remaining_ms > 0:
        candidates = asset_library.get_filler_assets(
            max_duration_ms=remaining_ms, count=5
        )
        if not candidates:
            break
        pick = candidates[0]
        picks.append((pick.asset_uri, pick.duration_ms, pick.asset_type))
        remaining_ms -= pick.duration_ms

    if not picks:
        return None

    # Calculate gap and distribute evenly (INV-BREAK-PAD-DISTRIBUTED-001)
    filled_ms = sum(d for _, d, _ in picks)
    gap_ms = break_duration_ms - filled_ms
    num_items = len(picks)

    if gap_ms > 0 and num_items > 0:
        base_pad = gap_ms // num_items
        extra = gap_ms % num_items
        pad_sizes = [base_pad] * num_items
        for r in range(extra):
            pad_sizes[num_items - 1 - r] += 1
    else:
        pad_sizes = [0] * num_items

    # Build segments: [spot, pad, spot, pad, ...]
    segments: list[ScheduledSegment] = []
    for i, (uri, duration_ms, asset_type) in enumerate(picks):
        seg_type = asset_type if asset_type in ("filler", "promo", "ad", "commercial") else "filler"
        segments.append(ScheduledSegment(
            segment_type=seg_type,
            asset_uri=uri,
            asset_start_offset_ms=0,
            segment_duration_ms=duration_ms,
        ))
        if pad_sizes[i] > 0:
            segments.append(ScheduledSegment(
                segment_type="pad",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=pad_sizes[i],
            ))

    # Verify invariant: total must equal break duration
    total = sum(s.segment_duration_ms for s in segments)
    assert total == break_duration_ms, (
        f"INV-BREAK-PAD-EXACT-001 violated: {total}ms != {break_duration_ms}ms"
    )

    return segments
