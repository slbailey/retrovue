"""Contract tests: tags.contains_any operator for pool tag filtering.

INV-POOL-TAGS-FILTER-001 extension: the `contains_any` operator matches
assets that possess AT LEAST ONE of the specified tags.  It is the
existential counterpart to `contains_all` (universal).

All three tag operators may be combined:
    tags:
      contains_all: [hbo]           # must have ALL of these
      contains_any: [action, comedy] # must have AT LEAST ONE of these
      excludes_any: [anime]          # must have NONE of these

DSL normalizes to match key `tags_any` in the legacy match dict.
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
    resolver = StubAssetResolver()

    resolver.add("trailer-action", AssetMetadata(
        type="trailer", duration_sec=120, title="Die Hard Trailer",
        tags=("hbo", "trailer", "action"),
    ))
    resolver.add("trailer-comedy", AssetMetadata(
        type="trailer", duration_sec=110, title="Ghostbusters Trailer",
        tags=("hbo", "trailer", "comedy"),
    ))
    resolver.add("trailer-drama", AssetMetadata(
        type="trailer", duration_sec=100, title="Shawshank Trailer",
        tags=("hbo", "trailer", "drama"),
    ))
    resolver.add("trailer-anime", AssetMetadata(
        type="trailer", duration_sec=90, title="Akira Trailer",
        tags=("hbo", "trailer", "anime", "action"),
    ))
    resolver.add("bumper-hbo", AssetMetadata(
        type="bumper", duration_sec=10, title="HBO Bumper",
        tags=("hbo", "bumper"),
    ))

    return resolver


# ===========================================================================
# DSL normalization
# ===========================================================================


class TestDslNormalization:
    """select.where.tags with contains_any must normalize correctly."""

    def test_contains_any_alone(self):
        """tags: { contains_any: [action, comedy] } → match.tags_any."""
        pool_def = {
            "select": {
                "where": {
                    "tags": {"contains_any": ["action", "comedy"]},
                },
            },
        }
        normalized = normalize_pool_definition(pool_def)
        assert normalized["match"]["tags_any"] == ["action", "comedy"]
        assert "tags" not in normalized["match"]

    def test_contains_any_plus_contains_all(self):
        """Both contains_all and contains_any on same field."""
        pool_def = {
            "select": {
                "where": {
                    "tags": {
                        "contains_all": ["hbo", "trailer"],
                        "contains_any": ["action", "comedy"],
                    },
                },
            },
        }
        normalized = normalize_pool_definition(pool_def)
        assert normalized["match"]["tags"] == ["hbo", "trailer"]
        assert normalized["match"]["tags_any"] == ["action", "comedy"]

    def test_all_three_combined(self):
        """contains_all + contains_any + excludes_any on same field."""
        pool_def = {
            "select": {
                "where": {
                    "tags": {
                        "contains_all": ["hbo"],
                        "contains_any": ["action", "comedy"],
                        "excludes_any": ["anime"],
                    },
                },
            },
        }
        normalized = normalize_pool_definition(pool_def)
        assert normalized["match"]["tags"] == ["hbo"]
        assert normalized["match"]["tags_any"] == ["action", "comedy"]
        assert normalized["match"]["tags_exclude"] == ["anime"]

    def test_contains_any_only_valid_on_tags(self):
        """contains_any on a non-tags field must be rejected."""
        pool_def = {
            "select": {
                "where": {
                    "type": {"contains_any": ["movie", "episode"]},
                },
            },
        }
        with pytest.raises(ValueError, match="contains_any"):
            normalize_pool_definition(pool_def)


# ===========================================================================
# Query filtering
# ===========================================================================


class TestContainsAnyFiltering:
    """StubAssetResolver.query must respect tags_any (OR semantics)."""

    def test_contains_any_action_or_comedy(self):
        """tags_any: [action, comedy] → assets with action OR comedy."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_any": ["action", "comedy"],
        })

        assert "trailer-action" in results
        assert "trailer-comedy" in results
        assert "trailer-anime" in results  # has "action" tag
        assert "trailer-drama" not in results  # has neither

    def test_contains_any_single_tag(self):
        """tags_any with one tag is equivalent to contains_all with one tag."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_any": ["drama"],
        })
        assert results == ["trailer-drama"]

    def test_contains_any_no_match(self):
        """tags_any with no matching tags → empty result."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_any": ["horror", "sci-fi"],
        })
        assert results == []

    def test_contains_all_plus_contains_any(self):
        """Require [hbo, trailer] AND at least one of [action, comedy]."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags": ["hbo", "trailer"],
            "tags_any": ["action", "comedy"],
        })

        assert "trailer-action" in results
        assert "trailer-comedy" in results
        assert "trailer-anime" in results  # has hbo + trailer + action
        assert "trailer-drama" not in results  # has hbo + trailer but no action/comedy

    def test_contains_any_plus_excludes_any(self):
        """At least one of [action, comedy] but not anime."""
        resolver = _make_resolver()
        results = resolver.query({
            "type": "trailer",
            "tags_any": ["action", "comedy"],
            "tags_exclude": ["anime"],
        })

        assert "trailer-action" in results
        assert "trailer-comedy" in results
        assert "trailer-anime" not in results  # has action but also anime
        assert "trailer-drama" not in results

    def test_all_three_operators_combined(self):
        """Require [hbo] AND one of [action, comedy] AND not [anime]."""
        resolver = _make_resolver()
        results = resolver.query({
            "tags": ["hbo"],
            "tags_any": ["action", "comedy"],
            "tags_exclude": ["anime"],
        })

        assert "trailer-action" in results
        assert "trailer-comedy" in results
        assert "trailer-anime" not in results  # excluded by anime
        assert "trailer-drama" not in results  # no action/comedy
        assert "bumper-hbo" not in results  # no action/comedy


# ===========================================================================
# Pool resolution end-to-end
# ===========================================================================


class TestPoolResolution:
    """Pools with contains_any resolve correctly via register_pools + resolve_pool."""

    def test_pool_with_contains_any(self):
        resolver = _make_resolver()
        resolver.register_pools({
            "fun_trailers": {
                "select": {
                    "where": {
                        "type": {"eq": "trailer"},
                        "tags": {
                            "contains_all": ["hbo"],
                            "contains_any": ["action", "comedy"],
                            "excludes_any": ["anime"],
                        },
                    },
                },
            },
        })

        results = resolver.resolve_pool("fun_trailers")
        assert sorted(results) == ["trailer-action", "trailer-comedy"]


# ===========================================================================
# Diagnostics
# ===========================================================================


class TestContainsAnyDiagnostics:
    """query_with_diagnostics reports contains_any failures."""

    def test_missing_any_tag_reported(self):
        resolver = _make_resolver()
        _, diag = resolver.query_with_diagnostics({
            "type": "trailer",
            "tags_any": ["horror", "sci-fi"],
        })

        # All trailers should be excluded
        assert diag.matched == 0
        # Every excluded trailer should have a reason
        assert "trailer-action" in diag.exclusion_reasons
        reasons = diag.exclusion_reasons["trailer-action"]
        assert any("none of required tags" in r.lower() or "tags_any" in r.lower() for r in reasons), (
            f"Expected contains_any exclusion reason, got: {reasons}"
        )
