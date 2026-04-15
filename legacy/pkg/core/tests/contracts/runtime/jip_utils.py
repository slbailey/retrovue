"""
Test utility: JIP (Join-In-Progress) helper functions.

These are test-only utilities relocated from production modules.

- ``compute_jip_position`` was removed from ``channel_manager.py`` in
  PASS-OPT-02-PHASE-C3-C4-C5 because it is a deprecated legacy utility
  (pre-INV-EXEC-NO-STRUCTURE-001 era).  JIP is now computed within
  ``BlockPlanProducer._generate_next_block()`` using ScheduledBlock timing.
  This function remains here for backward-compatible contract tests only.

- ``_apply_jip_to_segments`` is NOT here — it remains in
  ``channel_manager.py`` because it is still called by live production
  code (``BlockPlanProducer._generate_next_block``).

Do NOT import these helpers from production modules in new code.
"""
from __future__ import annotations

from typing import Any


def compute_jip_position(
    playout_plan: list[dict[str, Any]],
    block_duration_ms: int,
    cycle_origin_utc_ms: int,
    now_utc_ms: int,
) -> tuple[int, int]:
    """
    Compute Join-In-Progress position within a cyclic playout plan.

    .. deprecated::
        Legacy utility from pre-INV-EXEC-NO-STRUCTURE-001 era. JIP is now
        computed within BlockPlanProducer._generate_next_block() using
        ScheduledBlock timing from the schedule service. This function
        remains only for backward-compatible contract tests. Do not use in
        new code.

    INV-JIP-BP-002: returned offset is in [0, entry_duration).
    INV-JIP-BP-003: deterministic for identical inputs.

    Args:
        playout_plan: Ordered cycle entries (each with optional duration_ms,
                      asset_path, asset_start_offset_ms).
        block_duration_ms: Default block duration when entry lacks duration_ms.
        cycle_origin_utc_ms: Wall-clock epoch (ms) anchoring cycle position 0.
        now_utc_ms: Current wall-clock time (ms since Unix epoch).

    Returns:
        (active_entry_index, block_offset_ms) where active_entry_index is the
        0-based plan entry, and block_offset_ms is in [0, entry_duration).
    """
    if not playout_plan:
        return (0, 0)

    durations = [
        entry.get("duration_ms", block_duration_ms) for entry in playout_plan
    ]
    cycle_length_ms = sum(durations)

    if cycle_length_ms <= 0:
        return (0, 0)

    elapsed_ms = (now_utc_ms - cycle_origin_utc_ms) % cycle_length_ms

    accumulated = 0
    for i, dur in enumerate(durations):
        if accumulated + dur > elapsed_ms:
            return (i, elapsed_ms - accumulated)
        accumulated += dur

    last = len(durations) - 1
    return (last, elapsed_ms - sum(durations[:last]))
