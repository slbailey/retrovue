"""
Traffic DSL — Channel configuration validation and profile resolution.

Contract: docs/contracts/traffic_dsl.md

Validates declarative traffic configuration in channel YAML and resolves
traffic profiles for schedule blocks. Pure configuration logic — no database,
no asset catalog, no runtime queries.
"""

from __future__ import annotations

from retrovue.runtime.break_structure import BreakConfig
from retrovue.runtime.traffic_policy import TrafficPolicy


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECOGNIZED_INTERSTITIAL_TYPES = frozenset({
    "commercial", "promo", "trailer", "station_id", "psa", "stinger", "bumper", "filler",
})

_TRAFFIC_POLICY_FIELDS = frozenset({
    "allowed_types", "cooldown", "default_cooldown_ms",
    "type_cooldowns_ms", "max_plays_per_day", "traffic_profile",
})

_BREAK_PLACEMENT_FIELDS = frozenset({
    "break_positions", "break_count", "break_interval_ms",
    "breaks_per_program", "break_timing",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_traffic_dsl(channel_yaml: dict) -> None:
    """Validate traffic DSL invariants on a channel configuration dict.

    Raises ValueError on any violation.
    """
    traffic = channel_yaml.get("traffic")
    if traffic is None:
        return

    profiles = traffic.get("profiles", {})

    # INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001
    if "default_profile" not in traffic:
        raise ValueError(
            "INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001: traffic section must "
            "include default_profile"
        )
    default_name = traffic["default_profile"]
    if default_name not in profiles:
        raise ValueError(
            f"INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001: default_profile "
            f"'{default_name}' not found in traffic.profiles"
        )

    # INV-TRAFFIC-DSL-INVENTORY-TYPE-001
    for inv_name, inv in traffic.get("inventories", {}).items():
        asset_type = inv.get("asset_type", "")
        if asset_type not in RECOGNIZED_INTERSTITIAL_TYPES:
            raise ValueError(
                f"INV-TRAFFIC-DSL-INVENTORY-TYPE-001: inventory '{inv_name}' "
                f"has unrecognized asset_type '{asset_type}'"
            )

    # INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 + INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001
    for prog_name, prog in channel_yaml.get("programs", {}).items():
        for field in _TRAFFIC_POLICY_FIELDS:
            if field in prog:
                raise ValueError(
                    f"INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001: program "
                    f"'{prog_name}' must not contain traffic field '{field}'"
                )
        for field in _BREAK_PLACEMENT_FIELDS:
            if field in prog:
                raise ValueError(
                    f"INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001: program "
                    f"'{prog_name}' must not contain break placement field "
                    f"'{field}'"
                )

    # INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 + INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001
    for _day, blocks in channel_yaml.get("schedule", {}).items():
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            ref = block.get("traffic_profile")
            if ref is not None and ref not in profiles:
                raise ValueError(
                    f"INV-TRAFFIC-DSL-PROFILE-REF-VALID-001: schedule block "
                    f"references unknown traffic_profile '{ref}'"
                )
            for field in _BREAK_PLACEMENT_FIELDS:
                if field in block:
                    raise ValueError(
                        f"INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001: schedule "
                        f"block must not contain break placement field "
                        f"'{field}'"
                    )


def resolve_inventory_types(channel_yaml: dict) -> set[str]:
    """Return the set of asset_type values from traffic.inventories.

    INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001: returns a materialized set.
    """
    traffic = channel_yaml.get("traffic", {})
    return {
        inv["asset_type"]
        for inv in traffic.get("inventories", {}).values()
        if "asset_type" in inv
    }


def resolve_traffic_profile(channel_yaml: dict, block: dict) -> dict:
    """Resolve the traffic profile dict for a schedule block.

    Resolution order (traffic_dsl.md §Resolution Rules):
    1. block.traffic_profile → named profile
    2. traffic.default_profile → named profile

    When the resolved profile omits allowed_types, it defaults to the union
    of inventory asset_type values.
    """
    traffic = channel_yaml.get("traffic", {})
    profiles = traffic.get("profiles", {})

    ref = block.get("traffic_profile", traffic.get("default_profile"))
    profile = dict(profiles[ref])  # copy to avoid mutating config

    if "allowed_types" not in profile:
        profile["allowed_types"] = sorted(resolve_inventory_types(channel_yaml))

    return profile


def resolve_break_config(channel_yaml: dict) -> BreakConfig | None:
    """Resolve a BreakConfig from the channel YAML's traffic.break_config.

    INV-TRAFFIC-DSL-BREAK-CONFIG-001:
    - Present → BreakConfig with matching field values (missing fields default to 0).
    - Absent → None (legacy flat-fill behavior preserved).
    """
    traffic = channel_yaml.get("traffic")
    if traffic is None:
        return None

    bc = traffic.get("break_config")
    if bc is None:
        return None

    return BreakConfig(
        to_break_bumper_ms=bc.get("to_break_bumper_ms", 0),
        from_break_bumper_ms=bc.get("from_break_bumper_ms", 0),
        station_id_ms=bc.get("station_id_ms", 0),
    )


def resolve_traffic_policy(channel_yaml: dict, block: dict) -> TrafficPolicy:
    """Resolve a TrafficPolicy instance for a schedule block.

    Bridges the DSL profile dict to the runtime TrafficPolicy object.
    Field names are identical between the two (traffic_dsl.md §Profile-to-Policy
    Mapping). Defaults come from TrafficPolicy's dataclass definition.
    """
    profile = resolve_traffic_profile(channel_yaml, block)
    return TrafficPolicy(
        allowed_types=profile["allowed_types"],
        default_cooldown_ms=profile.get("default_cooldown_ms", 3_600_000),
        type_cooldowns_ms=profile.get("type_cooldowns_ms", {}),
        max_plays_per_day=profile.get("max_plays_per_day", 0),
    )
