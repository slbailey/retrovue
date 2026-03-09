"""
Contract tests: Traffic DSL → TrafficPolicy bridge

Validates that resolve_traffic_policy() correctly maps DSL profile
declarations to runtime TrafficPolicy instances.

Contract: docs/contracts/traffic_dsl.md §Profile-to-Policy Mapping
"""

from __future__ import annotations

import pytest

from retrovue.runtime.traffic_dsl import resolve_traffic_policy
from retrovue.runtime.traffic_policy import TrafficPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _channel_dsl(
    *,
    inventories: dict | None = None,
    profiles: dict | None = None,
    default_profile: str = "default",
    schedule: dict | None = None,
) -> dict:
    dsl: dict = {
        "channel": "test-channel",
        "name": "Test Channel",
        "channel_type": "network",
        "format": {"grid_minutes": 30},
        "pools": {"shows": {"match": {"type": "episode"}}},
        "programs": {
            "show_30": {"pool": "shows", "grid_blocks": 1, "fill_mode": "single"},
        },
        "schedule": schedule or {
            "all_day": [{"start": "06:00", "slots": 48, "program": "show_30"}],
        },
        "traffic": {
            "inventories": inventories or {
                "promos": {"match": {"type": "promo"}, "asset_type": "promo"},
            },
            "profiles": profiles or {
                "default": {
                    "allowed_types": ["promo", "station_id"],
                    "default_cooldown_ms": 3_600_000,
                    "type_cooldowns_ms": {},
                    "max_plays_per_day": 0,
                },
            },
            "default_profile": default_profile,
        },
    }
    return dsl


def _block(**overrides) -> dict:
    defaults = {"start": "06:00", "slots": 48, "program": "show_30"}
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Return type
# ===========================================================================


class TestReturnsTrafficPolicy:
    """resolve_traffic_policy must return a TrafficPolicy instance."""

    def test_returns_traffic_policy_instance(self):
        dsl = _channel_dsl()
        result = resolve_traffic_policy(dsl, _block())
        assert isinstance(result, TrafficPolicy)


# ===========================================================================
# Default profile resolution
# ===========================================================================


class TestDefaultProfileResolution:
    """Block without traffic_profile uses the channel default_profile."""

    def test_default_profile_used(self):
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo"],
                    "default_cooldown_ms": 1_800_000,
                    "max_plays_per_day": 5,
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert policy.allowed_types == ["promo"]
        assert policy.default_cooldown_ms == 1_800_000
        assert policy.max_plays_per_day == 5


# ===========================================================================
# Block override
# ===========================================================================


class TestBlockOverride:
    """Block with traffic_profile overrides the channel default."""

    def test_block_override_produces_correct_policy(self):
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo", "station_id"],
                    "default_cooldown_ms": 3_600_000,
                    "max_plays_per_day": 0,
                },
                "primetime": {
                    "allowed_types": ["promo"],
                    "default_cooldown_ms": 900_000,
                    "max_plays_per_day": 12,
                },
            },
        )
        block = _block(traffic_profile="primetime")
        policy = resolve_traffic_policy(dsl, block)
        assert policy.allowed_types == ["promo"]
        assert policy.default_cooldown_ms == 900_000
        assert policy.max_plays_per_day == 12


# ===========================================================================
# allowed_types defaults to inventory union
# ===========================================================================


class TestAllowedTypesDefault:
    """When profile omits allowed_types, it defaults to the union of
    inventory asset_type values."""

    def test_omitted_allowed_types_uses_inventory_union(self):
        dsl = _channel_dsl(
            inventories={
                "promos": {"match": {"type": "promo"}, "asset_type": "promo"},
                "bumpers": {"match": {"type": "bumper"}, "asset_type": "bumper"},
                "station_ids": {"match": {"type": "station_id"}, "asset_type": "station_id"},
            },
            profiles={
                "default": {
                    "default_cooldown_ms": 3_600_000,
                    "max_plays_per_day": 0,
                    # allowed_types deliberately omitted
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert set(policy.allowed_types) == {"promo", "bumper", "station_id"}


# ===========================================================================
# type_cooldowns_ms preserved
# ===========================================================================


class TestTypeCooldowns:
    """Type cooldown overrides from the profile are preserved in the policy."""

    def test_type_cooldowns_preserved(self):
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo", "station_id"],
                    "default_cooldown_ms": 3_600_000,
                    "type_cooldowns_ms": {"station_id": 900_000},
                    "max_plays_per_day": 0,
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert policy.type_cooldowns_ms == {"station_id": 900_000}

    def test_empty_type_cooldowns(self):
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo"],
                    "default_cooldown_ms": 3_600_000,
                    "type_cooldowns_ms": {},
                    "max_plays_per_day": 0,
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert policy.type_cooldowns_ms == {}


# ===========================================================================
# Field mapping completeness
# ===========================================================================


class TestFieldMapping:
    """All TrafficPolicy fields match the DSL profile values."""

    def test_all_fields_mapped(self):
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["commercial", "promo", "bumper"],
                    "default_cooldown_ms": 7_200_000,
                    "type_cooldowns_ms": {"bumper": 300_000},
                    "max_plays_per_day": 10,
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert policy.allowed_types == ["commercial", "promo", "bumper"]
        assert policy.default_cooldown_ms == 7_200_000
        assert policy.type_cooldowns_ms == {"bumper": 300_000}
        assert policy.max_plays_per_day == 10

    def test_defaults_applied_for_missing_optional_fields(self):
        """Profile with only allowed_types gets TrafficPolicy defaults."""
        dsl = _channel_dsl(
            profiles={
                "default": {
                    "allowed_types": ["promo"],
                },
            },
        )
        policy = resolve_traffic_policy(dsl, _block())
        assert policy.allowed_types == ["promo"]
        assert policy.default_cooldown_ms == 3_600_000
        assert policy.type_cooldowns_ms == {}
        assert policy.max_plays_per_day == 0
