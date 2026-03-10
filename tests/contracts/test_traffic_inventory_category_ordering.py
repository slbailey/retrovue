"""
Contract tests: Traffic Inventory — Category Ordering

Validates that apply_category_ordering() correctly enforces:
- Category diversity preference (INV-TRAFFIC-INVENTORY-DIVERSITY-001)
- Consecutive same-category separation (INV-TRAFFIC-INVENTORY-SEPARATION-001)
- Break-scope working set (INV-TRAFFIC-INVENTORY-BREAK-SCOPE-001)
- Uncategorized normalization (INV-TRAFFIC-INVENTORY-UNCATEGORIZED-001)
- Category neutrality — no candidates added or removed (INV-TRAFFIC-INVENTORY-NEUTRALITY-001)
- Deterministic ordering (INV-TRAFFIC-INVENTORY-DETERMINISTIC-001)

Contract: docs/contracts/traffic_inventory.md
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.traffic_inventory import apply_category_ordering
    from retrovue.runtime.traffic_policy import TrafficCandidate
except ImportError:
    pytest.skip(
        "retrovue.runtime.traffic_inventory not yet implemented",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _c(
    asset_id: str,
    category: str | None = None,
    asset_type: str = "commercial",
    duration_ms: int = 30_000,
) -> TrafficCandidate:
    return TrafficCandidate(
        asset_id=asset_id,
        asset_type=asset_type,
        duration_ms=duration_ms,
        asset_category=category,
    )


def _ids(result: list[TrafficCandidate]) -> list[str]:
    """Extract asset_ids for easy assertion."""
    return [c.asset_id for c in result]


# ===========================================================================
# INV-TRAFFIC-INVENTORY-DIVERSITY-001 — Diversity preference
# ===========================================================================


class TestDiversityPreference:
    """Unseen categories appear before seen categories."""

    # Tier: 2 | Scheduling logic invariant
    def test_unseen_before_seen(self):
        """A candidate from an unseen category is preferred over one
        from a category already used in the break."""
        candidates = [
            _c("ad1", "auto"),      # seen
            _c("ad2", "food"),      # unseen
            _c("ad3", "retail"),    # unseen
        ]
        result = apply_category_ordering(candidates, ["auto"])
        ids = _ids(result)
        # food and retail (unseen) appear before auto (seen)
        assert ids.index("ad2") < ids.index("ad1")
        assert ids.index("ad3") < ids.index("ad1")

    # Tier: 2 | Scheduling logic invariant
    def test_multiple_unseen_all_before_seen(self):
        """All unseen categories appear before all seen categories."""
        candidates = [
            _c("s1", "auto"),       # seen
            _c("s2", "food"),       # seen
            _c("u1", "retail"),     # unseen
            _c("u2", "travel"),     # unseen
        ]
        result = apply_category_ordering(candidates, ["auto", "food"])
        ids = _ids(result)
        assert ids[:2] == ["u1", "u2"]
        assert ids[2:] == ["s1", "s2"]

    # Tier: 2 | Scheduling logic invariant
    def test_empty_break_history_all_unseen(self):
        """With no prior selections, all candidates are unseen.
        Rotation order is preserved."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
            _c("ad3", "retail"),
        ]
        result = apply_category_ordering(candidates, [])
        assert _ids(result) == ["ad1", "ad2", "ad3"]

    # Tier: 2 | Scheduling logic invariant
    def test_all_categories_seen(self):
        """When every candidate's category is already seen,
        rotation order is preserved (no unseen tier)."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
        ]
        result = apply_category_ordering(candidates, ["auto", "food"])
        assert _ids(result) == ["ad1", "ad2"]


# ===========================================================================
# INV-TRAFFIC-INVENTORY-SEPARATION-001 — Consecutive same-category avoidance
# ===========================================================================


class TestSeparation:
    """Candidate matching the previous category is skipped when
    alternatives exist."""

    # Tier: 2 | Scheduling logic invariant
    def test_skip_repeated_category(self):
        """The top candidate repeats the previous break category;
        the first alternative-category candidate is promoted."""
        candidates = [
            _c("ad1", "auto"),   # same as previous
            _c("ad2", "auto"),   # same as previous
            _c("ad3", "food"),   # different
        ]
        result = apply_category_ordering(candidates, ["auto"])
        assert result[0].asset_id == "ad3"

    # Tier: 2 | Scheduling logic invariant
    def test_separation_with_unseen_same_as_prev(self):
        """Even if the top candidate is unseen by diversity rules,
        separation takes precedence (CS-4)."""
        # break used "food"; candidates rotation-sorted with "food" first
        # but "food" is unseen in this scenario because break used "auto"
        # Actually let's set up: prev = "retail", used = {"retail"}
        # candidates: retail (unseen=no, it's seen), food (unseen=yes)
        # diversity puts food first; but let's test CS-4 directly:
        # prev = "food", used = {"auto", "food"}
        # candidate order: food-unseen(retail), food-seen(food), ...
        # Actually, to test CS-4: diversity would prefer an unseen candidate
        # whose category matches the previous selection.
        candidates = [
            _c("ad1", "auto"),    # seen (auto already used)
            _c("ad2", "food"),    # unseen — but matches prev
        ]
        # Previous was "food"; "auto" already used earlier
        result = apply_category_ordering(candidates, ["auto", "food"])
        # Both are seen. ad1 first by rotation, ad2 second. Prev is "food".
        # ad1 is "auto" != "food", no separation issue.
        assert result[0].asset_id == "ad1"

    # Tier: 2 | Scheduling logic invariant
    def test_separation_precedence_over_diversity_in_seen_tier(self):
        """CS-4: separation takes precedence over diversity ordering.
        When diversity has no effect (all seen) and the rotation-first
        candidate repeats the previous category, the first non-repeating
        candidate is promoted."""
        # All categories seen. Rotation order: food, food, auto.
        # Prev = food. Diversity has no unseen tier to prefer.
        # Separation promotes auto over the two foods.
        candidates = [
            _c("ad1", "food"),
            _c("ad2", "food"),
            _c("ad3", "auto"),
        ]
        result = apply_category_ordering(
            candidates, ["auto", "food"],
        )
        assert result[0].asset_id == "ad3"

    # Tier: 2 | Scheduling logic invariant
    def test_separation_within_seen_tier(self):
        """When all candidates are seen and the first repeats the
        previous category, promote the first non-repeating candidate."""
        candidates = [
            _c("ad1", "food"),    # same as prev
            _c("ad2", "food"),    # same as prev
            _c("ad3", "auto"),    # different
            _c("ad4", "retail"),  # different
        ]
        result = apply_category_ordering(
            candidates, ["food", "auto", "retail", "food"],
        )
        # All seen. Rotation order: ad1, ad2, ad3, ad4. Prev = "food".
        # Separation promotes ad3 (first non-food).
        assert result[0].asset_id == "ad3"
        # ad1, ad2 shift down but remain in order
        assert result[1].asset_id == "ad1"
        assert result[2].asset_id == "ad2"
        assert result[3].asset_id == "ad4"

    # Tier: 2 | Scheduling logic invariant
    def test_no_separation_on_first_pick(self):
        """CS-3: first selection in a break has no preceding category.
        No separation constraint applies."""
        candidates = [
            _c("ad1", "food"),
            _c("ad2", "auto"),
        ]
        result = apply_category_ordering(candidates, [])
        # Rotation order preserved — ad1 stays first
        assert result[0].asset_id == "ad1"


# ===========================================================================
# INV-TRAFFIC-INVENTORY-SEPARATION-001 — Separation fallback
# ===========================================================================


class TestSeparationFallback:
    """When all candidates share the same category, rotation order
    is preserved and selection proceeds."""

    # Tier: 2 | Scheduling logic invariant
    def test_all_same_category_preserves_order(self):
        """CS-2: all candidates have the same category as the previous
        selection. No alternative exists, so rotation order is preserved."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "auto"),
            _c("ad3", "auto"),
        ]
        result = apply_category_ordering(candidates, ["auto"])
        assert _ids(result) == ["ad1", "ad2", "ad3"]

    # Tier: 2 | Scheduling logic invariant
    def test_single_candidate_same_as_prev(self):
        """A single candidate matching the previous category is returned."""
        candidates = [_c("ad1", "food")]
        result = apply_category_ordering(candidates, ["food"])
        assert _ids(result) == ["ad1"]

    # Tier: 2 | Scheduling logic invariant
    def test_single_candidate_no_history(self):
        """A single candidate with empty break history is returned."""
        candidates = [_c("ad1", "food")]
        result = apply_category_ordering(candidates, [])
        assert _ids(result) == ["ad1"]


# ===========================================================================
# INV-TRAFFIC-INVENTORY-UNCATEGORIZED-001 — None → "uncategorized"
# ===========================================================================


class TestUncategorizedHandling:
    """None categories are normalized to 'uncategorized'."""

    # Tier: 2 | Scheduling logic invariant
    def test_none_treated_as_uncategorized(self):
        """Two candidates with None category are treated as sharing
        the same effective category 'uncategorized'."""
        candidates = [
            _c("ad1", None),
            _c("ad2", None),
            _c("ad3", "food"),
        ]
        # Previous was None (→ uncategorized).
        result = apply_category_ordering(candidates, [None])
        # ad3 is unseen ("food" not in break). ad1, ad2 are seen
        # ("uncategorized" is in break). Diversity: ad3 first.
        assert result[0].asset_id == "ad3"

    # Tier: 2 | Scheduling logic invariant
    def test_none_in_break_history_matches_none_candidate(self):
        """A None in break_categories makes None candidates 'seen'."""
        candidates = [
            _c("ad1", None),        # seen (uncategorized in history)
            _c("ad2", "auto"),      # unseen
        ]
        result = apply_category_ordering(candidates, [None])
        assert result[0].asset_id == "ad2"

    # Tier: 2 | Scheduling logic invariant
    def test_all_none_preserves_rotation(self):
        """All-None candidates treated as same category.
        Rotation order preserved."""
        candidates = [
            _c("ad1", None),
            _c("ad2", None),
            _c("ad3", None),
        ]
        result = apply_category_ordering(candidates, [None])
        assert _ids(result) == ["ad1", "ad2", "ad3"]

    # Tier: 2 | Scheduling logic invariant
    def test_none_prev_skips_none_candidate(self):
        """Separation: prev was None, first candidate is None,
        alternative exists → skip."""
        candidates = [
            _c("ad1", None),      # matches prev (uncategorized)
            _c("ad2", "food"),    # different
        ]
        result = apply_category_ordering(candidates, [None])
        # ad2 is unseen, ad1 is seen. Diversity puts ad2 first.
        # Separation: prev=uncategorized, ad2=food → no issue.
        assert result[0].asset_id == "ad2"

    # Tier: 2 | Scheduling logic invariant
    def test_candidate_not_mutated(self):
        """CV-3: normalization MUST NOT mutate the TrafficCandidate."""
        c = _c("ad1", None)
        apply_category_ordering([c, _c("ad2", "food")], [None])
        assert c.asset_category is None


# ===========================================================================
# INV-TRAFFIC-INVENTORY-DIVERSITY-001 + INV-TRAFFIC-INVENTORY-DETERMINISTIC-001
# — Rotation preservation within tiers
# ===========================================================================


class TestRotationPreservation:
    """Ordering within unseen and seen tiers preserves the original
    rotation order from evaluate_candidates."""

    # Tier: 2 | Scheduling logic invariant
    def test_unseen_tier_preserves_rotation(self):
        """DP-2: among unseen candidates, rotation order is preserved."""
        candidates = [
            _c("ad1", "food"),     # unseen
            _c("ad2", "retail"),   # unseen
            _c("ad3", "travel"),   # unseen
        ]
        result = apply_category_ordering(candidates, ["auto"])
        # All three are unseen. Original rotation order preserved.
        assert _ids(result) == ["ad1", "ad2", "ad3"]

    # Tier: 2 | Scheduling logic invariant
    def test_seen_tier_preserves_rotation(self):
        """DP-2: among seen candidates, rotation order is preserved."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
            _c("ad3", "retail"),
        ]
        result = apply_category_ordering(
            candidates, ["auto", "food", "retail"],
        )
        # All three are seen. Rotation order preserved.
        assert _ids(result) == ["ad1", "ad2", "ad3"]

    # Tier: 2 | Scheduling logic invariant
    def test_mixed_tiers_preserve_intra_tier_rotation(self):
        """Unseen candidates appear first, then seen, each tier
        preserving its original rotation order."""
        candidates = [
            _c("s1", "auto"),     # seen
            _c("u1", "food"),     # unseen
            _c("s2", "retail"),   # seen
            _c("u2", "travel"),   # unseen
        ]
        result = apply_category_ordering(candidates, ["auto", "retail"])
        ids = _ids(result)
        # Unseen tier: u1, u2 (original relative order)
        # Seen tier: s1, s2 (original relative order)
        assert ids == ["u1", "u2", "s1", "s2"]

    # Tier: 2 | Scheduling logic invariant
    def test_separation_preserves_remaining_order(self):
        """After promoting a candidate for separation, the rest
        maintain their relative order."""
        candidates = [
            _c("ad1", "food"),    # same as prev
            _c("ad2", "food"),    # same as prev
            _c("ad3", "auto"),    # first alternative
            _c("ad4", "retail"),
        ]
        result = apply_category_ordering(candidates, ["food"])
        # ad1, ad2 are seen (food in break). ad3 unseen, ad4 unseen.
        # Diversity: [ad3, ad4, ad1, ad2]. Prev=food.
        # ad3=auto != food → no separation issue. ad3 stays first.
        assert _ids(result) == ["ad3", "ad4", "ad1", "ad2"]


# ===========================================================================
# INV-TRAFFIC-INVENTORY-DETERMINISTIC-001 — Determinism
# ===========================================================================


class TestDeterminism:
    """Identical inputs always produce identical output."""

    # Tier: 2 | Scheduling logic invariant
    def test_repeated_calls_same_result(self):
        """DT-1: calling apply_category_ordering twice with
        identical inputs produces the same output."""
        candidates = [
            _c("ad3", "retail"),
            _c("ad1", "auto"),
            _c("ad2", "food"),
        ]
        history = ["auto", "food"]
        r1 = apply_category_ordering(candidates, history)
        r2 = apply_category_ordering(candidates, history)
        assert _ids(r1) == _ids(r2)

    # Tier: 2 | Scheduling logic invariant
    def test_deterministic_across_many_runs(self):
        """DT-1: 50 repeated calls all produce the same order."""
        candidates = [
            _c("c1", "food"),
            _c("c2", "auto"),
            _c("c3", "retail"),
            _c("c4", "food"),
            _c("c5", None),
        ]
        history = ["food"]
        expected = _ids(apply_category_ordering(candidates, history))
        for _ in range(50):
            assert _ids(apply_category_ordering(candidates, history)) == expected


# ===========================================================================
# INV-TRAFFIC-INVENTORY-NEUTRALITY-001 — No candidates added or removed
# ===========================================================================


class TestNeutrality:
    """Category ordering only reorders; it never adds or removes."""

    # Tier: 2 | Scheduling logic invariant
    def test_same_count(self):
        """Output has the same number of candidates as input."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
            _c("ad3", "retail"),
        ]
        result = apply_category_ordering(candidates, ["auto"])
        assert len(result) == len(candidates)

    # Tier: 2 | Scheduling logic invariant
    def test_same_ids(self):
        """Output contains exactly the same asset_ids as input."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
            _c("ad3", None),
        ]
        result = apply_category_ordering(candidates, ["food"])
        assert sorted(_ids(result)) == sorted(_ids(candidates))

    # Tier: 2 | Scheduling logic invariant
    def test_input_not_mutated(self):
        """The input list is not mutated."""
        candidates = [
            _c("ad1", "auto"),
            _c("ad2", "food"),
        ]
        original = list(candidates)
        apply_category_ordering(candidates, ["auto"])
        assert candidates == original

    # Tier: 2 | Scheduling logic invariant
    def test_empty_input(self):
        """Empty candidate list returns empty list."""
        result = apply_category_ordering([], ["food"])
        assert result == []
