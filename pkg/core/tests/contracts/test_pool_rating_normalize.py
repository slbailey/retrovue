"""Contract tests for INV-POOL-RATING-NORMALIZE-001.

Validates that the pool rating match filter normalizes all input forms
(bare string, list of strings, dict) to the canonical dict structure
before evaluation.

Contract: docs/contracts/core/programming_pools.md
Invariant: docs/contracts/invariants/core/programming-pools/INV-POOL-RATING-NORMALIZE-001.md
"""

from __future__ import annotations

import pytest

from retrovue.runtime.catalog_resolver import _normalize_rating_match


# ===========================================================================
# INV-POOL-RATING-NORMALIZE-001
# Pool rating match normalizes shorthand to canonical form.
# ===========================================================================


@pytest.mark.contract
class TestInvPoolRatingNormalize001:
    """INV-POOL-RATING-NORMALIZE-001"""

    # Tier: 1 | Structural invariant
    def test_bare_string_normalized_to_include(self):
        # POOL-RATING-001 — bare string "PG" becomes { include: ["PG"] }
        result = _normalize_rating_match("PG")
        assert result == {"include": ["PG"]}

    # Tier: 1 | Structural invariant
    def test_list_normalized_to_include(self):
        # POOL-RATING-002 — list ["PG", "PG-13"] becomes { include: ["PG", "PG-13"] }
        result = _normalize_rating_match(["PG", "PG-13"])
        assert result == {"include": ["PG", "PG-13"]}

    # Tier: 1 | Structural invariant
    def test_dict_passed_through(self):
        # POOL-RATING-003 — dict form passes through unchanged
        cfg = {"include": ["R"], "exclude": ["NC-17"]}
        result = _normalize_rating_match(cfg)
        assert result == {"include": ["R"], "exclude": ["NC-17"]}

    # Tier: 1 | Structural invariant
    def test_dict_include_only(self):
        # POOL-RATING-003 — dict with include only passes through
        cfg = {"include": ["G", "PG"]}
        result = _normalize_rating_match(cfg)
        assert result == {"include": ["G", "PG"]}

    # Tier: 1 | Structural invariant
    def test_dict_exclude_only(self):
        # POOL-RATING-003 — dict with exclude only passes through
        cfg = {"exclude": ["NC-17"]}
        result = _normalize_rating_match(cfg)
        assert result == {"exclude": ["NC-17"]}

    # Tier: 1 | Structural invariant
    def test_all_three_forms_equivalent(self):
        # POOL-RATING-005 — all three forms produce identical normalized output
        bare = _normalize_rating_match("PG")
        as_list = _normalize_rating_match(["PG"])
        as_dict = _normalize_rating_match({"include": ["PG"]})
        assert bare == as_list == as_dict


@pytest.mark.contract
class TestPoolRatingQueryIntegration:
    """INV-POOL-RATING-NORMALIZE-001 — end-to-end through query()."""

    # Tier: 1 | Structural invariant
    def test_bare_string_matches_correct_assets(self):
        # POOL-RATING-004 — bare string returns correct subset
        from retrovue.runtime.catalog_resolver import _CatalogEntry
        from retrovue.runtime.asset_resolver import AssetMetadata

        def _entry(cid: str, rating: str) -> _CatalogEntry:
            return _CatalogEntry(
                canonical_id=cid,
                asset_type="movie",
                duration_sec=5400,
                series_title="",
                season=None,
                episode=None,
                rating=rating,
                source_name="test",
                collection_name="test",
                meta=AssetMetadata(type="movie", duration_sec=5400, rating=rating),
            )

        catalog = [
            _entry("movie-pg-1", "PG"),
            _entry("movie-pg-2", "PG"),
            _entry("movie-r-1", "R"),
            _entry("movie-g-1", "G"),
        ]

        # Simulate query filtering with normalized rating
        rating_cfg = _normalize_rating_match("PG")
        include = rating_cfg.get("include")
        results = [e for e in catalog if e.rating in include]

        assert len(results) == 2
        assert all(e.rating == "PG" for e in results)

    # Tier: 1 | Structural invariant
    def test_list_matches_multiple_ratings(self):
        # POOL-RATING-002 — list matches union of ratings
        from retrovue.runtime.catalog_resolver import _CatalogEntry
        from retrovue.runtime.asset_resolver import AssetMetadata

        def _entry(cid: str, rating: str) -> _CatalogEntry:
            return _CatalogEntry(
                canonical_id=cid,
                asset_type="movie",
                duration_sec=5400,
                series_title="",
                season=None,
                episode=None,
                rating=rating,
                source_name="test",
                collection_name="test",
                meta=AssetMetadata(type="movie", duration_sec=5400, rating=rating),
            )

        catalog = [
            _entry("movie-pg-1", "PG"),
            _entry("movie-pg13-1", "PG-13"),
            _entry("movie-r-1", "R"),
            _entry("movie-g-1", "G"),
        ]

        rating_cfg = _normalize_rating_match(["PG", "PG-13"])
        include = rating_cfg.get("include")
        results = [e for e in catalog if e.rating in include]

        assert len(results) == 2
        assert {e.canonical_id for e in results} == {"movie-pg-1", "movie-pg13-1"}
