"""
Contract tests: Traffic DSL — INV-TRAFFIC-DSL-*

Validates that channel DSL traffic configuration enforces:
- Default profile required (INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001)
- Inventory asset_type recognized (INV-TRAFFIC-DSL-INVENTORY-TYPE-001)
- Profile references resolve (INV-TRAFFIC-DSL-PROFILE-REF-VALID-001)
- Programs carry no traffic policy (INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001)
- Placement from break detection only (INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001)
- Inventory resolution at planning time (INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001)
- Break config resolves to BreakConfig or None (INV-TRAFFIC-DSL-BREAK-CONFIG-001)

Contract: docs/contracts/traffic_dsl.md
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Recognized interstitial types (from traffic_dsl.md §Domain Objects)
# ---------------------------------------------------------------------------

RECOGNIZED_INTERSTITIAL_TYPES = frozenset({
    "commercial", "promo", "trailer", "station_id", "psa", "stinger", "bumper", "filler",
})

# Traffic policy fields that MUST NOT appear on program definitions
TRAFFIC_POLICY_FIELDS = frozenset({
    "allowed_types", "cooldown", "default_cooldown_ms",
    "type_cooldowns_ms", "max_plays_per_day", "traffic_profile",
})

# Break placement fields that MUST NOT appear in the DSL
BREAK_PLACEMENT_FIELDS = frozenset({
    "break_positions", "break_count", "break_interval_ms",
    "breaks_per_program", "break_timing",
})


# ---------------------------------------------------------------------------
# Helpers — minimal DSL dict constructors
# ---------------------------------------------------------------------------

def _channel_dsl(
    *,
    inventories: dict | None = None,
    profiles: dict | None = None,
    default_profile: str | None = None,
    programs: dict | None = None,
    schedule: dict | None = None,
) -> dict:
    """Build a minimal channel DSL dict for testing."""
    dsl: dict = {
        "channel": "test-channel",
        "name": "Test Channel",
        "channel_type": "network",
        "format": {"grid_minutes": 30},
        "pools": {
            "shows": {"match": {"type": "episode"}},
        },
        "programs": programs or {
            "show_30": {
                "pool": "shows",
                "grid_blocks": 1,
                "fill_mode": "single",
            },
        },
        "schedule": schedule or {
            "all_day": [
                {"start": "06:00", "slots": 48, "program": "show_30"},
            ],
        },
    }
    if inventories is not None or profiles is not None or default_profile is not None:
        traffic: dict = {}
        if inventories is not None:
            traffic["inventories"] = inventories
        if profiles is not None:
            traffic["profiles"] = profiles
        if default_profile is not None:
            traffic["default_profile"] = default_profile
        dsl["traffic"] = traffic
    return dsl


def _inventory(asset_type: str = "promo", **match_overrides) -> dict:
    """Build a single inventory entry."""
    match = {"type": asset_type}
    match.update(match_overrides)
    return {"match": match, "asset_type": asset_type}


def _profile(**overrides) -> dict:
    """Build a single profile entry."""
    defaults = {
        "allowed_types": ["promo", "station_id"],
        "default_cooldown_ms": 3_600_000,
        "max_plays_per_day": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Validation logic under test
#
# The traffic DSL validation may not be implemented yet. These tests define
# the contract interface: a validate_traffic_dsl(dsl) function that raises
# on invalid configuration. If the function doesn't exist yet, tests skip.
# ---------------------------------------------------------------------------

try:
    from retrovue.runtime.traffic_dsl import (
        validate_traffic_dsl,
        resolve_traffic_profile,
        resolve_inventory_types,
    )
except ImportError:
    # Production code not yet implemented — define stubs so tests are
    # collected and marked xfail rather than silently skipped.
    validate_traffic_dsl = None  # type: ignore[assignment]
    resolve_traffic_profile = None  # type: ignore[assignment]
    resolve_inventory_types = None  # type: ignore[assignment]

_not_implemented = pytest.mark.xfail(
    validate_traffic_dsl is None,
    reason="retrovue.runtime.traffic_dsl not yet implemented",
    strict=False,
)


# ===========================================================================
# INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001 — Channel must declare default profile
# ===========================================================================


@_not_implemented
class TestDefaultProfileRequired:
    """INV-TRAFFIC-DSL-DEFAULT-REQUIRED-001: Every channel with a traffic
    section must include a default_profile that resolves to an existing profile."""

    def test_missing_default_profile_rejected(self):
        """Traffic section with inventories but no default_profile is invalid."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            # default_profile deliberately omitted
        )
        with pytest.raises((ValueError, KeyError)):
            validate_traffic_dsl(dsl)

    def test_default_profile_references_nonexistent_rejected(self):
        """default_profile naming a profile not in traffic.profiles is invalid."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="does_not_exist",
        )
        with pytest.raises((ValueError, KeyError)):
            validate_traffic_dsl(dsl)

    def test_valid_default_profile_accepted(self):
        """default_profile referencing an existing profile passes validation."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
        )
        # Should not raise
        validate_traffic_dsl(dsl)


# ===========================================================================
# INV-TRAFFIC-DSL-INVENTORY-TYPE-001 — asset_type must be recognized
# ===========================================================================


@_not_implemented
class TestInventoryTypeRecognized:
    """INV-TRAFFIC-DSL-INVENTORY-TYPE-001: Inventory asset_type must be one
    of the recognized interstitial types."""

    @pytest.mark.parametrize("valid_type", sorted(RECOGNIZED_INTERSTITIAL_TYPES))
    def test_recognized_type_accepted(self, valid_type: str):
        """Each recognized interstitial type is accepted."""
        dsl = _channel_dsl(
            inventories={"items": _inventory(valid_type)},
            profiles={"default": _profile(allowed_types=[valid_type])},
            default_profile="default",
        )
        validate_traffic_dsl(dsl)

    @pytest.mark.parametrize("bad_type", ["unknown", "movie", "episode", "ad", ""])
    def test_unrecognized_type_rejected(self, bad_type: str):
        """Unrecognized asset_type is rejected at load time."""
        dsl = _channel_dsl(
            inventories={"items": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
        )
        dsl["traffic"]["inventories"]["items"]["asset_type"] = bad_type
        with pytest.raises(ValueError):
            validate_traffic_dsl(dsl)


# ===========================================================================
# INV-TRAFFIC-DSL-PROFILE-REF-VALID-001 — Profile references must resolve
# ===========================================================================


@_not_implemented
class TestProfileRefValid:
    """INV-TRAFFIC-DSL-PROFILE-REF-VALID-001: Every traffic_profile reference
    on a schedule block must name an existing profile."""

    def test_schedule_block_valid_profile_accepted(self):
        """Schedule block referencing an existing profile passes."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={
                "default": _profile(),
                "primetime": _profile(allowed_types=["promo"]),
            },
            default_profile="default",
            schedule={
                "all_day": [
                    {
                        "start": "20:00",
                        "slots": 4,
                        "program": "show_30",
                        "traffic_profile": "primetime",
                    },
                ],
            },
        )
        validate_traffic_dsl(dsl)

    def test_schedule_block_dangling_profile_rejected(self):
        """Schedule block referencing a nonexistent profile is rejected."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
            schedule={
                "all_day": [
                    {
                        "start": "20:00",
                        "slots": 4,
                        "program": "show_30",
                        "traffic_profile": "nonexistent",
                    },
                ],
            },
        )
        with pytest.raises((ValueError, KeyError)):
            validate_traffic_dsl(dsl)

    def test_default_profile_resolution(self):
        """Block without traffic_profile resolves to default_profile."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
            schedule={
                "all_day": [
                    {"start": "06:00", "slots": 48, "program": "show_30"},
                ],
            },
        )
        validate_traffic_dsl(dsl)
        profile = resolve_traffic_profile(dsl, dsl["schedule"]["all_day"][0])
        assert profile is not None


# ===========================================================================
# INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001 — Programs must not carry traffic
# ===========================================================================


@_not_implemented
class TestNoProgramPolicy:
    """INV-TRAFFIC-DSL-NO-PROGRAM-POLICY-001: Program definitions must not
    include traffic policy fields."""

    @pytest.mark.parametrize("field", sorted(TRAFFIC_POLICY_FIELDS))
    def test_program_with_traffic_field_rejected(self, field: str):
        """Program definition carrying a traffic policy field is rejected."""
        programs = {
            "show_30": {
                "pool": "shows",
                "grid_blocks": 1,
                "fill_mode": "single",
                field: "some_value",
            },
        }
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
            programs=programs,
        )
        with pytest.raises(ValueError):
            validate_traffic_dsl(dsl)

    def test_program_without_traffic_fields_accepted(self):
        """Clean program definition passes validation."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
        )
        validate_traffic_dsl(dsl)


# ===========================================================================
# INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001 — DSL must not declare breaks
# ===========================================================================


@_not_implemented
class TestPlacementFromBreaks:
    """INV-TRAFFIC-DSL-PLACEMENT-FROM-BREAKS-001: The DSL must not declare
    break positions, counts, or timing. Placement comes from break_detection."""

    @pytest.mark.parametrize("field", sorted(BREAK_PLACEMENT_FIELDS))
    def test_break_placement_field_in_schedule_rejected(self, field: str):
        """Schedule block with break placement field is rejected."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
            schedule={
                "all_day": [
                    {
                        "start": "06:00",
                        "slots": 48,
                        "program": "show_30",
                        field: 3,
                    },
                ],
            },
        )
        with pytest.raises(ValueError):
            validate_traffic_dsl(dsl)

    @pytest.mark.parametrize("field", sorted(BREAK_PLACEMENT_FIELDS))
    def test_break_placement_field_in_program_rejected(self, field: str):
        """Program definition with break placement field is rejected."""
        programs = {
            "show_30": {
                "pool": "shows",
                "grid_blocks": 1,
                "fill_mode": "single",
                field: 3,
            },
        }
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
            programs=programs,
        )
        with pytest.raises(ValueError):
            validate_traffic_dsl(dsl)


# ===========================================================================
# INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001 — Inventory at planning time
# ===========================================================================


@_not_implemented
class TestInventoryPlanningOnly:
    """INV-TRAFFIC-DSL-INVENTORY-PLANNING-ONLY-001: Inventory resolution is
    a planning-time operation. The resolved candidate list must be a
    materialized set passed to the traffic manager, not a runtime query."""

    def test_resolve_inventory_returns_materialized_list(self):
        """resolve_inventory_types returns a plain list, not a query/generator."""
        dsl = _channel_dsl(
            inventories={
                "promos": _inventory("promo"),
                "bumpers": _inventory("bumper"),
            },
            profiles={"default": _profile()},
            default_profile="default",
        )
        result = resolve_inventory_types(dsl)
        # Must be a concrete collection, not a lazy query
        assert isinstance(result, (list, set, frozenset, tuple))

    def test_resolve_inventory_contains_declared_types(self):
        """Resolved inventory types reflect declared asset_type values."""
        dsl = _channel_dsl(
            inventories={
                "promos": _inventory("promo"),
                "station_ids": _inventory("station_id"),
                "bumpers": _inventory("bumper"),
            },
            profiles={"default": _profile()},
            default_profile="default",
        )
        result = resolve_inventory_types(dsl)
        assert set(result) == {"promo", "station_id", "bumper"}


# ===========================================================================
# Omitted allowed_types defaults to union of inventory asset_types
# ===========================================================================


@_not_implemented
class TestAllowedTypesDefault:
    """When allowed_types is omitted from a profile, it resolves to the union
    of all asset_type values declared across the channel's inventories."""

    def test_omitted_allowed_types_uses_inventory_union(self):
        """Profile without allowed_types gets union of inventory types."""
        dsl = _channel_dsl(
            inventories={
                "promos": _inventory("promo"),
                "bumpers": _inventory("bumper"),
                "station_ids": _inventory("station_id"),
            },
            profiles={
                "default": {
                    # allowed_types deliberately omitted
                    "default_cooldown_ms": 3_600_000,
                    "max_plays_per_day": 0,
                },
            },
            default_profile="default",
        )
        validate_traffic_dsl(dsl)
        profile = resolve_traffic_profile(dsl, dsl["schedule"]["all_day"][0])
        # The resolved profile's allowed_types must be the union
        assert set(profile["allowed_types"]) == {"promo", "bumper", "station_id"}

    def test_explicit_allowed_types_not_overridden(self):
        """Profile with explicit allowed_types keeps its declaration."""
        dsl = _channel_dsl(
            inventories={
                "promos": _inventory("promo"),
                "bumpers": _inventory("bumper"),
            },
            profiles={
                "default": _profile(allowed_types=["promo"]),
            },
            default_profile="default",
        )
        validate_traffic_dsl(dsl)
        profile = resolve_traffic_profile(dsl, dsl["schedule"]["all_day"][0])
        assert profile["allowed_types"] == ["promo"]


# ===========================================================================
# INV-TRAFFIC-DSL-BREAK-CONFIG-001 — Break config resolves to BreakConfig or None
# ===========================================================================

try:
    from retrovue.runtime.traffic_dsl import resolve_break_config
    from retrovue.runtime.break_structure import BreakConfig
except ImportError:
    resolve_break_config = None  # type: ignore[assignment]
    BreakConfig = None  # type: ignore[assignment,misc]

_break_config_not_implemented = pytest.mark.xfail(
    resolve_break_config is None,
    reason="retrovue.runtime.traffic_dsl.resolve_break_config not yet implemented",
    strict=False,
)


def _channel_dsl_with_break_config(break_config: dict | None = None) -> dict:
    """Build a minimal channel DSL with optional break_config."""
    dsl = _channel_dsl(
        inventories={"promos": _inventory("promo")},
        profiles={"default": _profile()},
        default_profile="default",
    )
    if break_config is not None:
        dsl["traffic"]["break_config"] = break_config
    return dsl


@_break_config_not_implemented
class TestBreakConfigResolve:
    """INV-TRAFFIC-DSL-BREAK-CONFIG-001: traffic.break_config resolves to
    BreakConfig or None."""

    def test_break_config_present_resolves_to_break_config(self):
        """break_config in YAML produces BreakConfig with matching fields."""
        dsl = _channel_dsl_with_break_config({
            "to_break_bumper_ms": 3000,
            "from_break_bumper_ms": 3000,
            "station_id_ms": 5000,
        })
        result = resolve_break_config(dsl)
        assert isinstance(result, BreakConfig)
        assert result.to_break_bumper_ms == 3000
        assert result.from_break_bumper_ms == 3000
        assert result.station_id_ms == 5000

    def test_break_config_absent_returns_none(self):
        """No break_config in YAML produces None."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
        )
        result = resolve_break_config(dsl)
        assert result is None

    def test_break_config_empty_returns_zero_defaults(self):
        """Empty break_config produces BreakConfig(0, 0, 0)."""
        dsl = _channel_dsl_with_break_config({})
        result = resolve_break_config(dsl)
        assert isinstance(result, BreakConfig)
        assert result.to_break_bumper_ms == 0
        assert result.from_break_bumper_ms == 0
        assert result.station_id_ms == 0

    def test_break_config_partial_fields_default_to_zero(self):
        """Partial break_config defaults missing fields to 0."""
        dsl = _channel_dsl_with_break_config({
            "to_break_bumper_ms": 5000,
        })
        result = resolve_break_config(dsl)
        assert isinstance(result, BreakConfig)
        assert result.to_break_bumper_ms == 5000
        assert result.from_break_bumper_ms == 0
        assert result.station_id_ms == 0

    def test_no_traffic_section_returns_none(self):
        """Channel with no traffic section at all returns None."""
        dsl = {
            "channel": "test-channel",
            "name": "Test",
            "channel_type": "network",
            "format": {"grid_minutes": 30},
        }
        result = resolve_break_config(dsl)
        assert result is None


# ===========================================================================
# INV-TRAFFIC-DSL-BREAK-CONFIG-001 — Integration: break_config wired into fill
# ===========================================================================

try:
    from dataclasses import dataclass as _dataclass
    from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
    from retrovue.runtime.traffic_manager import fill_ad_blocks
    _fill_available = True
except ImportError:
    _fill_available = False

_fill_not_implemented = pytest.mark.xfail(
    not _fill_available,
    reason="retrovue.runtime.traffic_manager not available",
    strict=False,
)


@_dataclass
class _FakeFillerAsset:
    asset_uri: str
    asset_type: str
    duration_ms: int


class _FakeAssetLibrary:
    def __init__(self, assets):
        self._assets = assets

    def get_filler_assets(self, max_duration_ms=0, count=5):
        return [a for a in self._assets if a.duration_ms <= max_duration_ms][:count]


@_fill_not_implemented
class TestBreakConfigWiring:
    """INV-TRAFFIC-DSL-BREAK-CONFIG-001: break_config from YAML flows through
    resolve_break_config into fill_ad_blocks, producing structured fill."""

    def test_break_config_from_yaml_produces_structured_fill(self):
        """break_config present → structured fill with bumper segments."""
        dsl = _channel_dsl_with_break_config({
            "to_break_bumper_ms": 3000,
            "from_break_bumper_ms": 3000,
            "station_id_ms": 0,
        })
        bc = resolve_break_config(dsl)
        assert bc is not None

        lib = _FakeAssetLibrary([
            _FakeFillerAsset("bumper_in.ts", "bumper", 3000),
            _FakeFillerAsset("bumper_out.ts", "bumper", 3000),
            _FakeFillerAsset("promo1.ts", "promo", 20_000),
            _FakeFillerAsset("promo2.ts", "promo", 20_000),
        ])
        block = ScheduledBlock(
            block_id="blk-1",
            start_utc_ms=0,
            end_utc_ms=60_000,
            segments=(ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=60_000,
            ),),
        )
        result = fill_ad_blocks(
            block,
            filler_uri="/filler.ts",
            filler_duration_ms=30_000,
            asset_library=lib,
            break_config=bc,
        )
        bumpers = [s for s in result.segments if s.segment_type == "bumper"]
        assert len(bumpers) >= 1, "Structured fill must produce bumper segments"
        total = sum(s.segment_duration_ms for s in result.segments)
        assert total == 60_000

    def test_no_break_config_produces_legacy_flat_fill(self):
        """No break_config → legacy fill with no bumper segments."""
        dsl = _channel_dsl(
            inventories={"promos": _inventory("promo")},
            profiles={"default": _profile()},
            default_profile="default",
        )
        bc = resolve_break_config(dsl)
        assert bc is None

        lib = _FakeAssetLibrary([
            _FakeFillerAsset("bumper_in.ts", "bumper", 3000),
            _FakeFillerAsset("promo1.ts", "promo", 30_000),
        ])
        block = ScheduledBlock(
            block_id="blk-1",
            start_utc_ms=0,
            end_utc_ms=60_000,
            segments=(ScheduledSegment(
                segment_type="filler",
                asset_uri="",
                asset_start_offset_ms=0,
                segment_duration_ms=60_000,
            ),),
        )
        result = fill_ad_blocks(
            block,
            filler_uri="/filler.ts",
            filler_duration_ms=30_000,
            asset_library=lib,
            break_config=bc,
        )
        # No bumper segments in legacy flat fill
        bumpers = [s for s in result.segments if s.segment_type == "bumper"]
        assert len(bumpers) == 0
        total = sum(s.segment_duration_ms for s in result.segments)
        assert total == 60_000
