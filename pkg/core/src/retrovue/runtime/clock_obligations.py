"""Clock Obligation Evaluation — second compilation pass.

Contract: docs/contracts/block_assembly_tiers.md (Tier 2)
Invariant: INV-CLOCK-OBLIGATIONS-OVERRIDE-001

Evaluates clock-scoped obligations against absolute wall-clock time
and inserts obligation segments into compiled_segments. This is a
pure function: same inputs always produce the same output.

The second pass operates on blocks already compiled by the first pass
(Tiers 0-1 resolved, break positions determined). It inserts Tier 2
obligation segments, displacing Tier 4 fill when possible.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class ClockObligation:
    """A clock-scoped obligation from channel YAML configuration."""

    type: str  # "station_id" | "legal_id" | "daypart_transition"
    interval_minutes: int | None  # Trigger every N minutes from midnight
    trigger_times: list[str] | None  # Specific wall-clock trigger times (HH:MM)
    pool: str  # Asset pool for obligation content
    duration_ms: int  # Obligation segment duration
    mandatory: bool  # Cannot be suppressed by templates


def evaluate_clock_obligations(
    *,
    blocks: list[dict],
    obligations: list[ClockObligation],
    broadcast_day: str,
    template_participation: dict[str, bool] | None = None,
) -> list[dict]:
    """Evaluate clock obligations and insert into compiled_segments.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001: Pure function, deterministic.

    Args:
        blocks: List of block dicts with start_utc_ms, slot_duration_ms,
                and compiled_segments.
        obligations: Channel-level clock obligation config.
        broadcast_day: ISO date string (e.g. "2026-03-27").
        template_participation: Optional template opt-in/out map.
            Keys are obligation types, values are bool (True=participate).
            Mandatory obligations ignore this map.

    Returns:
        New list of block dicts with obligation segments inserted.
        Original blocks are not mutated.
    """
    if not obligations:
        return blocks

    result = []
    for block in blocks:
        block_copy = copy.deepcopy(block)
        start_ms = block_copy["start_utc_ms"]
        slot_ms = block_copy["slot_duration_ms"]
        end_ms = start_ms + slot_ms
        segs = block_copy["compiled_segments"]

        # Collect all trigger times for all obligations within this block
        insertions: list[tuple[int, ClockObligation]] = []

        for obl in obligations:
            # Check template participation (mandatory overrides)
            if not obl.mandatory and template_participation:
                if not template_participation.get(obl.type, True):
                    continue

            trigger_ms_list = _compute_trigger_times_ms(obl, broadcast_day)
            for trigger_ms in trigger_ms_list:
                if start_ms <= trigger_ms < end_ms:
                    insertions.append((trigger_ms, obl))

        # Sort by trigger time, then by declaration order (stable sort)
        insertions.sort(key=lambda x: x[0])

        # Insert obligations into segments
        for trigger_ms, obl in insertions:
            segs = _insert_obligation(segs, trigger_ms, start_ms, obl)

        block_copy["compiled_segments"] = segs
        result.append(block_copy)

    return result


def _compute_trigger_times_ms(
    obl: ClockObligation,
    broadcast_day: str,
) -> list[int]:
    """Compute absolute trigger times in ms for a given broadcast day."""
    from datetime import date as date_type

    bd = date_type.fromisoformat(broadcast_day)
    day_start = datetime(bd.year, bd.month, bd.day, 0, 0, 0, tzinfo=timezone.utc)
    day_start_ms = int(day_start.timestamp() * 1000)

    triggers: list[int] = []

    if obl.interval_minutes is not None and obl.interval_minutes > 0:
        interval_ms = obl.interval_minutes * 60 * 1000
        # Generate triggers from midnight through 48h (covers next-day spill)
        t = day_start_ms
        end = day_start_ms + 48 * 3600 * 1000
        while t < end:
            triggers.append(t)
            t += interval_ms

    if obl.trigger_times:
        for time_str in obl.trigger_times:
            parts = time_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            trigger_dt = datetime(
                bd.year, bd.month, bd.day, h, m, 0, tzinfo=timezone.utc,
            )
            triggers.append(int(trigger_dt.timestamp() * 1000))

    return sorted(triggers)


def _insert_obligation(
    segs: list[dict],
    trigger_ms: int,
    block_start_ms: int,
    obl: ClockObligation,
) -> list[dict]:
    """Insert an obligation segment at the correct position.

    Placement rules per INV-CLOCK-OBLIGATIONS-OVERRIDE-001:
    1. Trigger at block boundary → prepend before all segments
    2. Trigger within a filler → insert into filler, reduce filler duration
    3. Trigger within content → defer to nearest eligible point:
       (a) next filler/break in same block, or (b) block boundary
    """
    obl_seg = {
        "segment_type": "obligation",
        "asset_id": "",
        "duration_ms": obl.duration_ms,
        "obligation_type": obl.type,
        "pool": obl.pool,
    }

    # Calculate relative trigger position within block
    relative_trigger_ms = trigger_ms - block_start_ms

    # Case 1: Trigger at block boundary (relative_trigger_ms == 0)
    if relative_trigger_ms <= 0:
        return [obl_seg] + segs

    # Walk segments to find where the trigger falls
    cursor_ms = 0
    for i, seg in enumerate(segs):
        seg_start = cursor_ms
        seg_end = cursor_ms + seg["duration_ms"]

        if seg_start <= relative_trigger_ms < seg_end:
            # Trigger falls within this segment
            if seg["segment_type"] == "filler":
                return _insert_into_filler(segs, i, relative_trigger_ms, seg_start, obl_seg)
            elif seg["segment_type"] == "content":
                return _defer_obligation(segs, i, obl_seg)
            else:
                # Presentation or other structural — defer to after this segment
                new_segs = list(segs)
                new_segs.insert(i + 1, obl_seg)
                return new_segs

        cursor_ms = seg_end

    # Trigger past all segments — append at end
    return segs + [obl_seg]


def _insert_into_filler(
    segs: list[dict],
    filler_idx: int,
    trigger_ms: int,
    filler_start_ms: int,
    obl_seg: dict,
) -> list[dict]:
    """Insert obligation into a filler segment, reducing filler duration.

    INV-TIER-DISPLACEMENT-001: obligation displaces fill.
    """
    filler = segs[filler_idx]
    obl_duration = obl_seg["duration_ms"]

    # Split filler: before-trigger portion, obligation, after portion
    before_ms = trigger_ms - filler_start_ms
    after_ms = filler["duration_ms"] - before_ms - obl_duration

    new_segs = list(segs[:filler_idx])

    if before_ms > 0:
        new_segs.append({
            **filler,
            "duration_ms": before_ms,
        })

    new_segs.append(obl_seg)

    if after_ms > 0:
        new_segs.append({
            **filler,
            "duration_ms": after_ms,
        })

    new_segs.extend(segs[filler_idx + 1:])
    return new_segs


def _defer_obligation(
    segs: list[dict],
    content_idx: int,
    obl_seg: dict,
) -> list[dict]:
    """Defer an obligation that triggers within primary content.

    INV-CLOCK-OBLIGATIONS-OVERRIDE-001 rule 2: defer to the nearest
    eligible placement point. Eligible points in priority order:
      (a) next filler/break segment in the same block
      (b) block boundary (append after last segment)

    Content is NEVER split or interrupted.
    """
    # Search for the next filler segment after the content segment
    for j in range(content_idx + 1, len(segs)):
        if segs[j]["segment_type"] == "filler":
            # Insert obligation at the start of this filler
            new_segs = list(segs[:j])
            new_segs.append(obl_seg)
            # Reduce filler by obligation duration
            remaining_filler = segs[j]["duration_ms"] - obl_seg["duration_ms"]
            if remaining_filler > 0:
                new_segs.append({**segs[j], "duration_ms": remaining_filler})
            new_segs.extend(segs[j + 1:])
            return new_segs

    # No filler found after content — defer to block boundary
    return list(segs) + [obl_seg]
