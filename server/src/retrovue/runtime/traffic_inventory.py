"""
Traffic Inventory — Category-aware ordering for interstitial selection.

Contract: docs/contracts/traffic_inventory.md

Reorders rotation-sorted candidates to promote category diversity within
a single break. Does not add or remove candidates — only reorders.
"""

from __future__ import annotations

import logging

from retrovue.runtime.traffic_policy import TrafficCandidate

logger = logging.getLogger(__name__)


def _effective_category(candidate: TrafficCandidate) -> str:
    """Return normalized category: None → 'uncategorized'."""
    return candidate.asset_category if candidate.asset_category is not None else "uncategorized"


def apply_category_ordering(
    candidates: list[TrafficCandidate],
    break_categories: list[str | None],
) -> list[TrafficCandidate]:
    """Reorder candidates for category diversity and separation.

    Operates on the rotation-sorted output of ``evaluate_candidates``.
    Does not mutate the input list.

    Rules (from traffic_inventory.md):

    1. Prefer candidates whose effective category has not yet appeared
       in *break_categories* (diversity — DP-1).
    2. Within the same diversity tier, preserve the incoming rotation
       order (DP-2).
    3. Never select a candidate whose effective category matches the
       immediately preceding selection when an alternative exists
       (separation — CS-1, CS-4 takes precedence over DP-1).
    4. When no alternative category exists, the candidate is still
       selectable (CS-2).
    """
    if len(candidates) <= 1:
        return list(candidates)

    if logger.isEnabledFor(logging.DEBUG):
        input_cats = [_effective_category(c) for c in candidates]
        break_cats = [c if c is not None else "uncategorized" for c in break_categories]
        logger.debug(
            "category_ordering input: candidates=%s break_working_set=%s",
            input_cats, break_cats,
        )

    # Normalize break history categories.
    used: set[str] = {
        (c if c is not None else "uncategorized") for c in break_categories
    }

    # The effective category of the immediately preceding selection.
    prev_category: str | None = None
    if break_categories:
        raw = break_categories[-1]
        prev_category = raw if raw is not None else "uncategorized"

    # Partition into two tiers preserving rotation order within each:
    #   tier 0 — unseen categories (not yet used in this break)
    #   tier 1 — seen categories (already used in this break)
    unseen: list[TrafficCandidate] = []
    seen: list[TrafficCandidate] = []
    for c in candidates:
        ec = _effective_category(c)
        if ec not in used:
            unseen.append(c)
        else:
            seen.append(c)

    # Merge: unseen first, then seen (DP-1), rotation order preserved
    # within each tier (DP-2).
    merged = unseen + seen

    # Apply separation: if the first candidate repeats the preceding
    # category and an alternative exists, move it down (CS-1, CS-4).
    if prev_category is not None and len(merged) > 1:
        first_ec = _effective_category(merged[0])
        if first_ec == prev_category:
            # Find the first candidate with a different category.
            for i in range(1, len(merged)):
                if _effective_category(merged[i]) != prev_category:
                    # Promote it to the front; shift others down.
                    promoted = merged[i]
                    merged = [promoted] + merged[:i] + merged[i + 1:]
                    break
            # If no alternative found (all same category), CS-2:
            # keep the original order — candidate is still selectable.

    if logger.isEnabledFor(logging.DEBUG):
        result_cats = [_effective_category(c) for c in merged]
        logger.debug("category_ordering result: %s", result_cats)

    return merged
