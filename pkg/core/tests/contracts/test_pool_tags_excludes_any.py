"""Contract tests: tags.excludes_any operator for pool tag filtering.

INV-POOL-TAGS-FILTER-001 extension: the `excludes_any` operator rejects
assets that possess ANY of the specified tags. It is the dual of
`contains_all` (which requires ALL).

`contains_all` and `excludes_any` may be combined on the same field:
the asset must have all required tags AND have none of the excluded tags.

DSL syntax:
    tags:
      contains_all: [trailer]
      excludes_any: [anime, adult]
"""

from __future__ import annotations

import pytest

try:
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
    from retrovue.runtime.pool_dsl_normalize import normalize_pool_definition
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_resolver() -> StubAssetResolver:
    """Resolver with trailers: some anime, some not."""
    resolver = StubAssetResolver()

    resolver.add("trailer-action-1", AssetMetadata(
        type="trailer", duration_sec=120, title="Die Hard Trailer",
        tags=("trailer", "action", "hbo"),
    ))
    resolver.add("trailer-anime-1", AssetMetadata(
        type="trailer", duration_sec=90, title="Akira Trailer",
        tags=("trailer", "anime", "hbo"),
    ))
    resolver.add("trailer-anime-adult", AssetMetadata(
        type="trailer", duration_sec=100, title="Ghost in the Shell",
        tags=("trailer", "anime", "adult", "hbo"),
    ))
    resolver.add("trailer-comedy-1", AssetMetadata(
        type="trailer", duration_sec=110, title="Ghostbusters Trailer",
        tags=("trailer", "comedy", "hbo"),
    ))
    resolver.add("promo-hbo", AssetMetadata(
        type="promo", duration_sec=30, title="HBO Promo",
        tags=("hbo", "promo"),
    ))

    return resolver


# ===========================================================================
# DSL normalization: excludes_any → tags_exclude in match dict
# ===========================================================================


class TestDslNormalization:
    """select.where.tags with excludes_any must normalize to match dict."""

    # Tier: 1 | Structural invariant
    def test_excludes_any_normalizes(self):
        """tags: { excludes_any: [anime] } → match.tags_exclude = [anime]."""
        pool_def = {
            "select": {
                "where": {
                    "type": {"eq": "trailer"},
                    "tags": {"excludes_any": ["anime"]},
                },
            },
        }
        normalized = normalize_pool_definition(pool_def)
        assert "tags_exclude" in normalized["match"], (
            f"excludes_any must normalize to tags_exclude. Got: {normalized['match']}"
        )
        assert normalized["match"]["tags_exclude"] == ["anime"]

    # Tier: 1 | Structural invariant
    def test_contains_all_plus_excludes_any_normalizes(self):
        """Both operators on same field must normalize independently."""
        pool_def = {
            "select": {
                "where": {
                    "tags": {
                        "contains_all": ["trailer", "hbo"],
                        "excludes_any": ["anime", "adult"],
                    },
                },
            },
        }
        normalized = normalize_pool_definition(pool_def)
        match = normalized["match"]

        assert match.get("tags") == ["trailer", "hbo"], (
            f"contains_all must normalize to tags. Got: {match}"
        )
        assert match.get("tags_exclude") == ["anime", "adult"], (
            f"excludes_any must normalize to tags_exclude. Got: {match}"
        )

    # Tier: 1 | Structural invariant
    def test_excludes_any_only_valid_on_tags(self):
        """excludes_any on a non-tags field must be rejected."""
        pool_def = {
            "select": {
                "where": {
                    "type": {"excludes_any": ["movie"]},
                },
            },
        }
        with pytest.raises(ValueError, match="excludes_any"):
            normalize_pool_definition(pool_def)


# ===========================================================================
# Query filtering: tags_exclude rejects assets with any excluded tag
# ===========================================================================


class TestTagsExcludeFiltering:
    """StubAssetResolver.query must respect tags_exclude."""

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_anime_returns_non_anime_trailers(self):
        """Exclude anime: only non-anime trailers returned."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_exclude": ["anime"],
        })

        assert "trailer-action-1" in results
        assert "trailer-comedy-1" in results
        assert "trailer-anime-1" not in results
        assert "trailer-anime-adult" not in results

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_multiple_tags(self):
        """Exclude [anime, comedy]: only action trailer survives."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_exclude": ["anime", "comedy"],
        })

        assert results == ["trailer-action-1"]

    # Tier: 2 | Scheduling logic invariant
    def test_contains_all_plus_exclude(self):
        """Require [trailer, hbo] but exclude [anime]: 2 results."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags": ["trailer", "hbo"],
            "tags_exclude": ["anime"],
        })

        assert "trailer-action-1" in results
        assert "trailer-comedy-1" in results
        assert "trailer-anime-1" not in results
        assert len(results) == 2

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_nonexistent_tag_no_effect(self):
        """Excluding a tag no asset has removes nothing."""
        resolver = _make_resolver()
        all_trailers = resolver.query({"type": "trailer"})

        filtered = resolver.query({
            "type": "trailer",
            "tags_exclude": ["nonexistent"],
        })

        assert filtered == all_trailers

    # Tier: 2 | Scheduling logic invariant
    def test_exclude_without_include(self):
        """tags_exclude without tags (contains_all) filters all assets."""
        resolver = _make_resolver()
        results = resolver.query({
            "tags_exclude": ["anime"],
        })

        assert "trailer-anime-1" not in results
        assert "trailer-anime-adult" not in results
        # Non-anime assets survive
        assert "trailer-action-1" in results
        assert "promo-hbo" in results


# ===========================================================================
# Pool resolution: end-to-end with registered pool
# ===========================================================================


class TestPoolResolutionWithExclude:
    """Pools defined with excludes_any must filter correctly via resolve_pool."""

    # Tier: 2 | Scheduling logic invariant
    def test_pool_with_exclude_resolves_correctly(self):
        """Register pool with tags_exclude, resolve, verify filtered."""
        resolver = _make_resolver()
        resolver.register_pools({
            "non_anime_trailers": {
                "select": {
                    "where": {
                        "type": {"eq": "trailer"},
                        "tags": {
                            "contains_all": ["hbo"],
                            "excludes_any": ["anime"],
                        },
                    },
                },
            },
        })

        results = resolver.resolve_pool("non_anime_trailers")
        assert "trailer-action-1" in results
        assert "trailer-comedy-1" in results
        assert "trailer-anime-1" not in results
        assert len(results) == 2


# ===========================================================================
# Diagnostics: excluded tags reported
# ===========================================================================


class TestExcludeTagDiagnostics:
    """query_with_diagnostics must report excluded tags in reasons."""

    # Tier: 2 | Scheduling logic invariant
    def test_excluded_tag_appears_in_diagnostics(self):
        """Asset excluded by tags_exclude must have reason in diagnostics."""
        resolver = _make_resolver()
        _, diag = resolver.query_with_diagnostics({
            "type": "trailer",
            "tags_exclude": ["anime"],
        })

        assert "trailer-anime-1" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["trailer-anime-1"]
        assert any("excluded tag" in r.lower() or "anime" in r.lower() for r in reasons), (
            f"Expected exclusion reason mentioning 'anime', got: {reasons}"
        )
