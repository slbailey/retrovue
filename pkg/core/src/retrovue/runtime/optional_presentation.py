"""Optional Presentation Evaluation — second compilation pass (Tier 3).

Contract: docs/contracts/block_assembly_tiers.md (Tier 3)
Invariants:
    INV-TIER3-COMPILE-RESOLUTION-001
    INV-TIER3-NEXT-BLOCK-IDENTITY-001
    INV-ASSEMBLY-SEQUENCE-001
    INV-TIER3-POOL-DETERMINISTIC-001
    INV-TIER3-BUDGET-BEFORE-FILL-001
    INV-TIER3-TEMPLATE-DECLARED-001
    INV-TIER3-SUBTYPE-ORDER-001

Evaluates optional presentation elements (channel ident, network branding,
"coming up next") declared in template continuity.optional and inserts
Tier 3 segments into compiled_segments. This is a pure function: same
inputs always produce the same output.

The second pass operates on blocks already compiled by the first pass
(Tiers 0-1 resolved, break positions determined, Tier 2 obligations
inserted). It appends Tier 3 segments after content, adjusts
slot_duration_ms if needed, and reduces filler to maintain conservation.
"""

from __future__ import annotations

import copy
import hashlib


# Fixed sub-type ordering per INV-TIER3-SUBTYPE-ORDER-001
TIER3_SUBTYPE_ORDER = ("channel_ident", "network_branding", "coming_up_next")


def _tier3_seed(
    channel_id: str,
    broadcast_day: str,
    block_index: int,
    element_type: str,
) -> int:
    """Deterministic seed per INV-TIER3-POOL-DETERMINISTIC-001.

    Uses hashlib (not Python hash()) for cross-process stability,
    matching INV-SCHEDULE-SEED-DETERMINISTIC-001 approach.
    """
    raw = f"{channel_id}:{broadcast_day}:{block_index}:{element_type}"
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest(), 16) % (2**31)


def _select_asset_from_pool(
    pool: str,
    max_duration_ms: int,
    seed: int,
) -> tuple[str, int]:
    """Select an asset deterministically from a pool.

    INV-TIER3-POOL-DETERMINISTIC-001: No uncontrolled RNG.
    Returns (asset_id, duration_ms).

    When no external resolver is provided, produces a deterministic
    synthetic asset_id from the pool name and seed. Duration is
    the max_duration_ms (longest-fitting from pool, capped by filter).
    """
    asset_id = f"{pool}:{seed % 10000:04d}"
    duration_ms = max_duration_ms
    return asset_id, duration_ms


def evaluate_optional_presentation(
    *,
    blocks: list[dict],
    continuity: dict,
    broadcast_day: str,
    channel_id: str,
    features: dict | None = None,
) -> list[dict]:
    """Evaluate optional presentation and insert Tier 3 segments.

    INV-TIER3-COMPILE-RESOLUTION-001: Pure function, deterministic.
    INV-TIER3-TEMPLATE-DECLARED-001: Only declared elements are inserted.
    INV-TIER3-NEXT-BLOCK-IDENTITY-001: "Coming up next" reads next block title.
    INV-TIER3-SUBTYPE-ORDER-001: Fixed ordering within block.
    INV-ASSEMBLY-SEQUENCE-001: Tier 3 placed after content.
    INV-CUN-FEATURE-FLAG-001: CUN gated by features.coming_up_next.

    Args:
        blocks: List of block dicts with start_utc_ms, slot_duration_ms,
                compiled_segments, and title.
        continuity: Template continuity config with "optional" key containing
                    list of element declarations.
        broadcast_day: ISO date string (e.g. "2026-03-27").
        channel_id: Channel identifier for seed computation.
        features: Channel feature flags dict. When features.coming_up_next
                  is not True, CUN segments are suppressed.

    Returns:
        New list of block dicts with Tier 3 segments inserted.
        Original blocks are not mutated.
    """
    optional_elements = continuity.get("optional", [])
    if not optional_elements:
        return blocks

    # INV-CUN-FEATURE-FLAG-001: Filter out coming_up_next when feature flag
    # is not explicitly True. Default is off (no CUN).
    cun_enabled = (features or {}).get("coming_up_next", False) is True
    if not cun_enabled:
        optional_elements = [
            e for e in optional_elements if e["type"] != "coming_up_next"
        ]
        if not optional_elements:
            return blocks

    # Build lookup of declared element types
    declared: dict[str, dict] = {}
    for elem in optional_elements:
        declared[elem["type"]] = elem

    result = []
    for block_idx, block in enumerate(blocks):
        block_copy = copy.deepcopy(block)
        segs = block_copy["compiled_segments"]

        # Collect Tier 3 segments to insert, in fixed sub-type order
        tier3_segments: list[dict] = []

        for subtype in TIER3_SUBTYPE_ORDER:
            if subtype not in declared:
                continue

            elem = declared[subtype]

            # "Coming up next" requires next-block lookahead
            # INV-TIER3-NEXT-BLOCK-IDENTITY-001
            if subtype == "coming_up_next":
                if block_idx >= len(blocks) - 1:
                    # Last block: silently omit
                    continue
                next_title = blocks[block_idx + 1].get("title", "")

            pool = elem["pool"]
            max_duration_ms = elem.get("max_duration_ms", 10_000)
            seed = _tier3_seed(channel_id, broadcast_day, block_idx, subtype)
            asset_id, duration_ms = _select_asset_from_pool(
                pool, max_duration_ms, seed,
            )

            seg = {
                "segment_type": subtype,
                "asset_id": asset_id,
                "duration_ms": duration_ms,
                "pool": pool,
            }

            if subtype == "coming_up_next":
                seg["next_program_title"] = next_title

            tier3_segments.append(seg)

        if tier3_segments:
            # INV-ASSEMBLY-SEQUENCE-001: Tier 3 placed after content,
            # before trailing filler.
            segs = _insert_tier3_after_content(segs, tier3_segments)

            # INV-TIER3-BUDGET-BEFORE-FILL-001: Tier 3 duration deducted
            # from break budget. Adjust filler and slot_duration_ms.
            tier3_total_ms = sum(s["duration_ms"] for s in tier3_segments)
            segs = _adjust_filler_for_tier3(segs, tier3_total_ms)

            # INV-GRID-SIZING-STRUCTURAL-001: Ensure slot accommodates
            # structural total.
            structural_types = {
                "content", "presentation", "obligation",
                "channel_ident", "coming_up_next", "network_branding",
            }
            structural_total = sum(
                s["duration_ms"] for s in segs
                if s["segment_type"] in structural_types
            )
            if block_copy["slot_duration_ms"] < structural_total:
                block_copy["slot_duration_ms"] = structural_total

        block_copy["compiled_segments"] = segs
        result.append(block_copy)

    return result


def _insert_tier3_after_content(
    segs: list[dict],
    tier3_segments: list[dict],
) -> list[dict]:
    """Insert Tier 3 segments after the last content segment.

    INV-ASSEMBLY-SEQUENCE-001: Tier 3 optional presentation appears
    after Tier 0 content (with breaks interleaved), before trailing filler.
    """
    # Find the last content segment index
    last_content_idx = -1
    for i, seg in enumerate(segs):
        if seg["segment_type"] == "content":
            last_content_idx = i

    if last_content_idx < 0:
        # No content found — append at end before filler
        last_content_idx = len(segs) - 1

    # Insert after last content segment
    insert_pos = last_content_idx + 1
    new_segs = list(segs[:insert_pos])
    new_segs.extend(tier3_segments)
    new_segs.extend(segs[insert_pos:])
    return new_segs


def _adjust_filler_for_tier3(
    segs: list[dict],
    tier3_total_ms: int,
) -> list[dict]:
    """Reduce trailing filler to accommodate Tier 3 insertion.

    INV-TIER3-BUDGET-BEFORE-FILL-001: Tier 3 deducted from break budget.
    If filler is insufficient, it is reduced to zero (grid will grow).
    """
    # Find the last filler segment and reduce it
    for i in range(len(segs) - 1, -1, -1):
        if segs[i]["segment_type"] == "filler":
            remaining = tier3_total_ms
            filler_ms = segs[i]["duration_ms"]
            if filler_ms >= remaining:
                segs[i] = {**segs[i], "duration_ms": filler_ms - remaining}
                if segs[i]["duration_ms"] <= 0:
                    segs.pop(i)
                return segs
            else:
                remaining -= filler_ms
                segs.pop(i)
                # If there's still remaining, grid will grow
                return segs
    return segs
