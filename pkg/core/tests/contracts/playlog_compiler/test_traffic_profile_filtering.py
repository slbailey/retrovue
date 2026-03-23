"""INV-DSL-TRAFFIC-RESIDUAL-001: Traffic profile constraints must be enforced
during asset selection using pool-based filtering.

When a profile declares allowed_pools, asset eligibility is determined by
evaluating each pool's select.where query against asset editorial metadata.
This preserves full DSL semantics (type, tags, and any future criteria).

When only allowed_types is present (legacy), filtering falls back to
interstitial_type matching.
"""
from __future__ import annotations

import warnings

import pytest

from retrovue.catalog.db_asset_library import (
    DEFAULT_TRAFFIC_POLICY,
    _apply_traffic_config,
    _asset_matches_pool,
)


# ---------------------------------------------------------------------------
# _apply_traffic_config
# ---------------------------------------------------------------------------


class TestTrafficPolicyResolution:
    """Verify _apply_traffic_config resolves profile-level constraints."""

    def test_default_policy_allows_everything(self):
        """Without channel config, default policy allows all 7 types."""
        assert "commercial" in DEFAULT_TRAFFIC_POLICY["allowed_types"]
        assert "filler" in DEFAULT_TRAFFIC_POLICY["allowed_types"]
        assert len(DEFAULT_TRAFFIC_POLICY["allowed_types"]) >= 7

    def test_allowed_types_deprecated_but_works(self):
        """allowed_types on a profile still works but emits deprecation warning."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        traffic = {
            "profiles": {
                "premium": {
                    "allowed_types": ["trailer", "teaser"],
                    "default_cooldown_seconds": 7200,
                },
            },
            "default": "premium",
        }
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _apply_traffic_config(policy, traffic)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert len(deprecations) == 1
            assert "allowed_types" in str(deprecations[0].message)

        assert policy["allowed_types"] == ["trailer", "teaser"]
        assert policy["default_cooldown_seconds"] == 7200

    def test_allowed_pools_stores_pool_definitions(self):
        """allowed_pools on a profile stores pool defs for query-based filtering."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        traffic = {
            "profiles": {
                "premium": {
                    "allowed_pools": ["traffic_trailers", "traffic_teasers"],
                },
            },
            "default": "premium",
        }
        pools = {
            "traffic_trailers": {"select": {"where": {"type": {"eq": "trailer"}}}},
            "traffic_teasers": {"select": {"where": {"type": {"eq": "teaser"}}}},
        }
        _apply_traffic_config(policy, traffic, pools=pools)

        assert policy["allowed_pools"] == ["traffic_trailers", "traffic_teasers"]
        assert "traffic_trailers" in policy["pool_definitions"]
        assert "traffic_teasers" in policy["pool_definitions"]

    def test_missing_pool_raises_error(self):
        """allowed_pools referencing undefined pool must raise ValueError."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        traffic = {
            "profiles": {
                "sitcom": {"allowed_pools": ["nonexistent_pool"]},
            },
            "default": "sitcom",
        }
        pools = {"other_pool": {"select": {"where": {"type": {"eq": "promo"}}}}}

        with pytest.raises(ValueError, match="undefined pools.*nonexistent_pool"):
            _apply_traffic_config(policy, traffic, pools=pools)

    def test_missing_pool_no_pools_section_raises(self):
        """allowed_pools with no pools section at all must raise ValueError."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        traffic = {
            "profiles": {
                "sitcom": {"allowed_pools": ["commercials"]},
            },
            "default": "sitcom",
        }
        with pytest.raises(ValueError, match="undefined pools"):
            _apply_traffic_config(policy, traffic)

    def test_legacy_default_profile_key(self):
        """Legacy default_profile key also works."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        traffic = {
            "profiles": {"legacy": {"allowed_types": ["promo"]}},
            "default_profile": "legacy",
        }
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            _apply_traffic_config(policy, traffic)
        assert policy["allowed_types"] == ["promo"]

    def test_no_profiles_keeps_default(self):
        """If no profiles section, default policy is unchanged."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        original = list(policy["allowed_types"])
        _apply_traffic_config(policy, {"break_config": {}})
        assert policy["allowed_types"] == original

    def test_missing_default_keeps_default(self):
        """If profiles exist but no default, policy is unchanged."""
        policy = dict(DEFAULT_TRAFFIC_POLICY)
        original = list(policy["allowed_types"])
        _apply_traffic_config(policy, {"profiles": {"orphan": {"allowed_types": ["x"]}}})
        assert policy["allowed_types"] == original


# ---------------------------------------------------------------------------
# _asset_matches_pool — the core pool-based matching function
# ---------------------------------------------------------------------------


class TestAssetMatchesPool:
    """Verify _asset_matches_pool evaluates pool queries correctly."""

    # -- type matching --

    def test_type_eq_match(self):
        editorial = {"interstitial_type": "trailer"}
        pool = {"select": {"where": {"type": {"eq": "trailer"}}}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_type_eq_no_match(self):
        editorial = {"interstitial_type": "commercial"}
        pool = {"select": {"where": {"type": {"eq": "trailer"}}}}
        assert _asset_matches_pool(editorial, pool) is False

    def test_type_in_match(self):
        editorial = {"interstitial_type": "teaser"}
        pool = {"select": {"where": {"type": {"in": ["trailer", "teaser"]}}}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_type_in_no_match(self):
        editorial = {"interstitial_type": "commercial"}
        pool = {"select": {"where": {"type": {"in": ["trailer", "teaser"]}}}}
        assert _asset_matches_pool(editorial, pool) is False

    # -- tag matching --

    def test_tags_contains_all_match(self):
        editorial = {"interstitial_type": "bumper", "tags": ["hbo", "station_id", "2024"]}
        pool = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo", "station_id"]}}}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_tags_contains_all_no_match(self):
        editorial = {"interstitial_type": "bumper", "tags": ["nbc", "station_id"]}
        pool = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo", "station_id"]}}}}
        assert _asset_matches_pool(editorial, pool) is False

    def test_tags_contains_any_match(self):
        editorial = {"interstitial_type": "promo", "tags": ["horror"]}
        pool = {"select": {"where": {"tags": {"contains_any": ["comedy", "horror"]}}}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_tags_contains_any_no_match(self):
        editorial = {"interstitial_type": "promo", "tags": ["drama"]}
        pool = {"select": {"where": {"tags": {"contains_any": ["comedy", "horror"]}}}}
        assert _asset_matches_pool(editorial, pool) is False

    # -- combined criteria (AND) --

    def test_type_and_tags_both_must_match(self):
        """Type matches but tags don't → rejected."""
        editorial = {"interstitial_type": "bumper", "tags": ["nbc"]}
        pool = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo"]}}}}
        assert _asset_matches_pool(editorial, pool) is False

    def test_type_and_tags_both_match(self):
        editorial = {"interstitial_type": "bumper", "tags": ["hbo", "intros"]}
        pool = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo"]}}}}
        assert _asset_matches_pool(editorial, pool) is True

    # -- two pools same type different tags --

    def test_two_pools_same_type_different_tags(self):
        """Two pools with type=bumper but different tag requirements
        must produce different results for the same asset."""
        editorial = {"interstitial_type": "bumper", "tags": ["hbo", "station_id"]}
        pool_station = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo", "station_id"]}}}}
        pool_intros = {"select": {"where": {"type": {"eq": "bumper"}, "tags": {"contains_all": ["hbo", "intros"]}}}}

        assert _asset_matches_pool(editorial, pool_station) is True
        assert _asset_matches_pool(editorial, pool_intros) is False

    # -- legacy match syntax --

    def test_legacy_match_type(self):
        editorial = {"interstitial_type": "promo"}
        pool = {"match": {"type": "promo"}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_legacy_match_tags(self):
        editorial = {"interstitial_type": "bumper", "tags": ["hbo", "intros"]}
        pool = {"match": {"type": "bumper", "tags": ["hbo", "intros"]}}
        assert _asset_matches_pool(editorial, pool) is True

    def test_legacy_match_tags_missing(self):
        editorial = {"interstitial_type": "bumper", "tags": ["nbc"]}
        pool = {"match": {"type": "bumper", "tags": ["hbo"]}}
        assert _asset_matches_pool(editorial, pool) is False

    # -- edge cases --

    def test_empty_pool_def_matches_nothing(self):
        """Empty pool = invalid, matches nothing (not a wildcard)."""
        editorial = {"interstitial_type": "anything"}
        assert _asset_matches_pool(editorial, {}) is False

    def test_missing_tags_in_editorial(self):
        editorial = {"interstitial_type": "bumper"}
        pool = {"select": {"where": {"tags": {"contains_all": ["hbo"]}}}}
        assert _asset_matches_pool(editorial, pool) is False
