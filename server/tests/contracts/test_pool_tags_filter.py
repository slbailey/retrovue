"""Contract tests for INV-POOL-TAGS-FILTER-001.

Validates that the pool tags match filter supports single and multi-tag
AND-combined filtering with case-insensitive comparison.

Contract: docs/contracts/core/programming_pools.md
Invariant: docs/contracts/invariants/core/programming-pools/INV-POOL-TAGS-FILTER-001.md
"""

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata
from retrovue.runtime.catalog_resolver import _CatalogEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(cid: str, tags: tuple[str, ...]) -> _CatalogEntry:
    return _CatalogEntry(
        canonical_id=cid,
        asset_type="bumper",
        duration_sec=30,
        series_title="",
        season=None,
        episode=None,
        rating=None,
        source_name="test",
        collection_name="test",
        meta=AssetMetadata(type="bumper", duration_sec=30, tags=tags),
    )


CATALOG = [
    _entry("hbo-intro-1", ("hbo", "presentation", "intros")),
    _entry("hbo-intro-2", ("hbo", "presentation", "intros")),
    _entry("hbo-rating-g-1", ("hbo", "presentation", "ratings_cards", "g")),
    _entry("hbo-rating-r-1", ("hbo", "presentation", "ratings_cards", "r")),
    _entry("showtime-intro-1", ("showtime", "presentation", "intros")),
    _entry("generic-bumper", ("bumper",)),
]


def _filter_by_tags(catalog: list[_CatalogEntry], tags_cfg) -> list[str]:
    """Simulate the tags filter that query() should implement."""
    from retrovue.runtime.catalog_resolver import _normalize_tags_match

    required = _normalize_tags_match(tags_cfg)
    results = []
    for e in catalog:
        entry_tags = {t.lower() for t in e.meta.tags}
        if all(t in entry_tags for t in required):
            results.append(e.canonical_id)
    return results


# ===========================================================================
# INV-POOL-TAGS-FILTER-001
# ===========================================================================


@pytest.mark.contract
class TestInvPoolTagsFilter001:
    """INV-POOL-TAGS-FILTER-001"""

    # Tier: 1 | Structural invariant
    def test_single_tag_matches(self):
        # POOL-TAGS-001 — single tag matches all assets with that tag
        results = _filter_by_tags(CATALOG, "hbo")
        assert set(results) == {
            "hbo-intro-1", "hbo-intro-2",
            "hbo-rating-g-1", "hbo-rating-r-1",
        }

    # Tier: 1 | Structural invariant
    def test_multi_tag_and_semantics(self):
        # POOL-TAGS-002 — multi-tag matches only assets with ALL tags
        results = _filter_by_tags(CATALOG, ["hbo", "presentation", "intros"])
        assert set(results) == {"hbo-intro-1", "hbo-intro-2"}

    # Tier: 1 | Structural invariant
    def test_missing_one_tag_excluded(self):
        # POOL-TAGS-003 — asset missing any required tag is excluded
        results = _filter_by_tags(CATALOG, ["hbo", "presentation", "intros"])
        # showtime-intro-1 has presentation + intros but not hbo
        assert "showtime-intro-1" not in results
        # generic-bumper has none of the required tags
        assert "generic-bumper" not in results

    # Tier: 1 | Structural invariant
    def test_case_insensitive(self):
        # POOL-TAGS-004 — tag comparison is case-insensitive
        results_lower = _filter_by_tags(CATALOG, ["hbo", "presentation"])
        results_upper = _filter_by_tags(CATALOG, ["HBO", "Presentation"])
        assert results_lower == results_upper

    # Tier: 1 | Structural invariant
    def test_bare_string_normalized(self):
        # POOL-TAGS-005 — bare string normalized to list
        results = _filter_by_tags(CATALOG, "presentation")
        assert len(results) == 5  # all except generic-bumper

    # Tier: 1 | Structural invariant
    def test_ratings_card_subset(self):
        # Practical: tags filter can isolate rating-specific bumpers
        results = _filter_by_tags(
            CATALOG, ["hbo", "presentation", "ratings_cards", "g"],
        )
        assert results == ["hbo-rating-g-1"]


@pytest.mark.contract
class TestNormalizeTagsMatch:
    """INV-POOL-TAGS-FILTER-001 — normalization helper"""

    # Tier: 1 | Structural invariant
    def test_str_to_list(self):
        from retrovue.runtime.catalog_resolver import _normalize_tags_match
        assert _normalize_tags_match("hbo") == ["hbo"]

    # Tier: 1 | Structural invariant
    def test_list_passthrough(self):
        from retrovue.runtime.catalog_resolver import _normalize_tags_match
        assert _normalize_tags_match(["hbo", "intros"]) == ["hbo", "intros"]

    # Tier: 1 | Structural invariant
    def test_lowercased(self):
        from retrovue.runtime.catalog_resolver import _normalize_tags_match
        result = _normalize_tags_match(["HBO", "Intros"])
        assert result == ["hbo", "intros"]
