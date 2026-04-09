"""Contract tests for tag canonical form — pool-level tag matching.

Validates that pool tag matching and catalog resolution work correctly
with canonical-form tags (`namespace.value`), including backward
compatibility with legacy colon-prefix and plain tag queries.

Reference: docs/contracts/tag_canonical_form.md (sections D, E)
Invariant: INV-TAG-CANONICAL-FORM-001
See also: test_inv_tag_canonical_form.py for canonicalize_tag() unit tests.
"""

from __future__ import annotations

import pytest

from retrovue.domain.tag_normalization import (
    canonicalize_tag,
    expand_tag_match_set,
)
from retrovue.runtime.asset_resolver import AssetMetadata
from retrovue.runtime.catalog_resolver import _CatalogEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(cid: str, tags: tuple[str, ...]) -> _CatalogEntry:
    """Build a catalog entry with canonical-form tags."""
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


# Catalog using canonical-form tags exclusively (post-migration state).
CANONICAL_CATALOG = [
    _entry("hbo-intro-1", ("tag.hbo", "tag.presentation", "tag.intros")),
    _entry("hbo-intro-2", ("tag.hbo", "tag.presentation", "tag.intros")),
    _entry("cbs-bumper-1", ("network.cbs", "tag.bumper")),
    _entry("comedy-clip-1", ("genre.comedy", "tag.hbo")),
    _entry("rated-r-1", ("rating.tv-ma", "tag.hbo")),
    _entry("generic-bumper", ("tag.bumper",)),
]


def _filter_by_tags_with_expand(
    catalog: list[_CatalogEntry],
    tags_cfg: str | list[str],
) -> list[str]:
    """Simulate pool tags filter using expand_tag_match_set for backward compat."""
    from retrovue.runtime.catalog_resolver import _normalize_tags_match

    required = _normalize_tags_match(tags_cfg)
    results = []
    for e in catalog:
        expanded = expand_tag_match_set(set(e.meta.tags))
        if all(t in expanded for t in required):
            results.append(e.canonical_id)
    return results


# ===========================================================================
# D. Backward Compatibility — pool matching with canonical-form catalog
# ===========================================================================


class TestPoolMatchingCanonicalCatalogD:
    """Contract §D: pool DSL queries in any historical form match canonical catalog."""

    @pytest.mark.contract
    def test_d1_plain_query_matches_canonical_tags(self):
        """D-1: Plain query 'hbo' matches canonical 'tag.hbo' via expand_tag_match_set."""
        results = _filter_by_tags_with_expand(CANONICAL_CATALOG, "hbo")
        matched_ids = set(results)
        assert "hbo-intro-1" in matched_ids
        assert "hbo-intro-2" in matched_ids
        assert "comedy-clip-1" in matched_ids
        assert "rated-r-1" in matched_ids
        assert "cbs-bumper-1" not in matched_ids

    @pytest.mark.contract
    def test_d1_colon_query_matches_canonical_tags(self):
        """D-1: Legacy colon query 'tag:hbo' matches canonical 'tag.hbo'."""
        results = _filter_by_tags_with_expand(CANONICAL_CATALOG, "tag:hbo")
        matched_ids = set(results)
        assert "hbo-intro-1" in matched_ids
        assert "hbo-intro-2" in matched_ids

    @pytest.mark.contract
    def test_d1_canonical_query_matches_canonical_tags(self):
        """D-1: Canonical query 'tag.hbo' matches directly."""
        results = _filter_by_tags_with_expand(CANONICAL_CATALOG, "tag.hbo")
        matched_ids = set(results)
        assert "hbo-intro-1" in matched_ids

    @pytest.mark.contract
    def test_d1_network_namespace_query_forms(self):
        """D-1: network.cbs, network:cbs, and cbs all match."""
        for query in ["network.cbs", "network:cbs", "cbs"]:
            results = _filter_by_tags_with_expand(CANONICAL_CATALOG, query)
            assert "cbs-bumper-1" in results, (
                f"Query '{query}' should match cbs-bumper-1"
            )

    @pytest.mark.contract
    def test_d1_multi_tag_and_query_all_forms_mixed(self):
        """D-1: Multi-tag AND query with mixed forms: plain + canonical."""
        results = _filter_by_tags_with_expand(
            CANONICAL_CATALOG, ["hbo", "tag.presentation"]
        )
        matched_ids = set(results)
        assert matched_ids == {"hbo-intro-1", "hbo-intro-2"}


# ===========================================================================
# Pool matching with canonical tags — namespace-aware filtering
# ===========================================================================


class TestPoolMatchingNamespaces:
    """Verify pool filtering respects namespaces in canonical tags."""

    @pytest.mark.contract
    def test_genre_namespace_filter(self):
        """genre.comedy matches only genre-tagged entries."""
        results = _filter_by_tags_with_expand(CANONICAL_CATALOG, "genre.comedy")
        assert "comedy-clip-1" in results
        assert "generic-bumper" not in results

    @pytest.mark.contract
    def test_rating_namespace_filter(self):
        """rating.tv-ma matches only rating-tagged entries."""
        results = _filter_by_tags_with_expand(CANONICAL_CATALOG, "rating.tv-ma")
        assert "rated-r-1" in results
        assert len(results) == 1

    @pytest.mark.contract
    def test_combined_namespace_filter(self):
        """Multi-namespace AND: tag.hbo AND rating.tv-ma."""
        results = _filter_by_tags_with_expand(
            CANONICAL_CATALOG, ["tag.hbo", "rating.tv-ma"]
        )
        assert results == ["rated-r-1"]


# ===========================================================================
# C-4. Migration deduplication in pool context
# ===========================================================================


class TestMigrationDeduplicationC4:
    """Contract §C-4: duplicate tags from migration must not cause false matches."""

    @pytest.mark.contract
    def test_c4_legacy_and_plain_collapse_to_single_canonical(self):
        """C-4: Both TAG:hbo and hbo canonicalize to single tag.hbo."""
        t1 = canonicalize_tag("TAG:hbo")
        t2 = canonicalize_tag("hbo")
        assert t1 == t2 == "tag.hbo"

    @pytest.mark.contract
    def test_c4_deduplicated_tags_in_expand(self):
        """C-4: Expanded set from deduplicated canonical tag covers all forms."""
        canonical_set = {canonicalize_tag("hbo"), canonicalize_tag("TAG:hbo")}
        assert len(canonical_set) == 1, "Migration must collapse to single canonical tag"
        expanded = expand_tag_match_set(canonical_set)
        assert "hbo" in expanded
        assert "tag.hbo" in expanded
        assert "tag:hbo" in expanded


# ===========================================================================
# B-1. Namespace rejection
# ===========================================================================


class TestNamespaceRejectionB1:
    """Contract §B-1: unrecognized namespace prefixes rejected."""

    @pytest.mark.contract
    def test_b1_unknown_colon_prefix_raises(self):
        """B-1: Legacy colon prefix with unknown namespace raises ValueError."""
        with pytest.raises(ValueError, match="Unrecognized"):
            canonicalize_tag("BADNS:value")

    @pytest.mark.contract
    @pytest.mark.parametrize("ns", ["tag", "network", "genre", "rating"])
    def test_b1_valid_namespaces_accepted(self, ns):
        """B-1: All controlled-vocabulary namespaces are accepted."""
        result = canonicalize_tag(f"{ns}.testval")
        assert result == f"{ns}.testval"
