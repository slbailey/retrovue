# pkg/core/tests/domain/test_program_resolution_contract.py
#
# Contract tests for program source resolution.
#
# These tests enforce the invariants defined in:
#   docs/domains/AssetResolution.md  (v1.1)
#
# Invariants under test:
#   INV-ASSET-RESOLUTION-NORMALIZE-001        — resolver always returns List[Asset]
#   INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001  — program sources resolve via resolve_program()
#   INV-ASSET-RESOLUTION-PROGRAM-ORDER-001    — output ordered by (season, episode)
#   INV-ASSET-RESOLUTION-EMPTY-FAIL-001       — zero-asset resolution is a hard failure
#   INV-ASSET-RESOLUTION-DISPATCH-001         — program is a supported source type
#
# All tests target SourceResolver.resolve({type: program, ...}).
# Tests are expected to FAIL until the program resolution path is implemented.

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata


# ---------------------------------------------------------------------------
# Stub catalog — episode assets for a test program
# ---------------------------------------------------------------------------

def _build_catalog() -> dict[str, AssetMetadata]:
    """Catalog containing episode assets for Seinfeld and a standalone movie."""
    return {
        "seinfeld-s01e01": AssetMetadata(
            type="episode",
            duration_sec=1320,
            title="The Seinfeld Chronicles",
            tags=("seinfeld", "comedy"),
            file_uri="/assets/seinfeld_s01e01.mkv",
        ),
        "seinfeld-s01e02": AssetMetadata(
            type="episode",
            duration_sec=1380,
            title="The Stakeout",
            tags=("seinfeld", "comedy"),
            file_uri="/assets/seinfeld_s01e02.mkv",
        ),
        "seinfeld-s01e03": AssetMetadata(
            type="episode",
            duration_sec=1350,
            title="The Robbery",
            tags=("seinfeld", "comedy"),
            file_uri="/assets/seinfeld_s01e03.mkv",
        ),
        "seinfeld-s02e01": AssetMetadata(
            type="episode",
            duration_sec=1380,
            title="The Ex-Girlfriend",
            tags=("seinfeld", "comedy"),
            file_uri="/assets/seinfeld_s02e01.mkv",
        ),
        "seinfeld-s02e02": AssetMetadata(
            type="episode",
            duration_sec=1400,
            title="The Pony Remark",
            tags=("seinfeld", "comedy"),
            file_uri="/assets/seinfeld_s02e02.mkv",
        ),
        "movie-001": AssetMetadata(
            type="movie",
            duration_sec=7200,
            title="Blade Runner",
            tags=("scifi",),
            file_uri="/assets/blade_runner.mkv",
        ),
    }


# Program definitions: name -> ordered list of (season, episode, asset_id)
_PROGRAM_DEFINITIONS: dict[str, list[dict]] = {
    "Seinfeld": [
        {"season": 1, "episode": 1, "asset_id": "seinfeld-s01e01"},
        {"season": 1, "episode": 2, "asset_id": "seinfeld-s01e02"},
        {"season": 1, "episode": 3, "asset_id": "seinfeld-s01e03"},
        {"season": 2, "episode": 1, "asset_id": "seinfeld-s02e01"},
        {"season": 2, "episode": 2, "asset_id": "seinfeld-s02e02"},
    ],
    "EmptyShow": [],
}

# Minimal collection/pool data (programs don't use these, but constructor requires them)
_COLLECTIONS: dict[str, list[str]] = {}
_POOLS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _import_source_resolver():
    """Import SourceResolver and error classes."""
    from retrovue.runtime.source_resolver import (
        SourceResolver,
        InvalidSourceTypeError,
        AssetResolutionError,
    )
    return SourceResolver, InvalidSourceTypeError, AssetResolutionError


def _make_resolver():
    """Construct a SourceResolver wired to the test catalog and program data.

    The SourceResolver is expected to accept a `programs` kwarg:
      programs: dict[str, list[dict]]  (program_name -> episode list)
    Each episode dict has: season, episode, asset_id.
    """
    SourceResolver, _, _ = _import_source_resolver()
    return SourceResolver(
        catalog=_build_catalog(),
        collections=_COLLECTIONS,
        pools=_POOLS,
        programs=_PROGRAM_DEFINITIONS,
    )


def _resolve(resolver, source: dict) -> list[str]:
    """Call resolver.resolve(source) and return the result."""
    return resolver.resolve(source)


# ===========================================================================
# INV-ASSET-RESOLUTION-DISPATCH-001
# Program is a recognized source type.
# ===========================================================================

class TestProgramSourceAccepted:
    """The resolver accepts type: program as a valid source type."""

    # CONTRACT: INV-ASSET-RESOLUTION-DISPATCH-001
    # type: program must not raise InvalidSourceTypeError.
    # Tier: 2 | Scheduling logic invariant
    def test_program_type_is_accepted(self):
        _, InvalidSourceTypeError, _ = _import_source_resolver()
        resolver = _make_resolver()
        # Must not raise InvalidSourceTypeError
        try:
            _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        except InvalidSourceTypeError:
            pytest.fail("type: program must be a supported source type")

    # CONTRACT: INV-ASSET-RESOLUTION-DISPATCH-001
    # type: program dispatches to program resolution, not pool or collection.
    # Tier: 2 | Scheduling logic invariant
    def test_program_does_not_dispatch_to_pool(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        # Program result must contain episode assets, not pool evaluation results
        catalog = _build_catalog()
        for asset_id in result:
            assert catalog[asset_id].type == "episode", (
                f"Program resolved non-episode asset: {asset_id}"
            )


# ===========================================================================
# INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001
# Program sources resolve to their episodes' backing assets.
# ===========================================================================

class TestProgramSourceResolution:
    """Program source resolves to the ordered list of episode assets."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Program resolution returns a list.
    # Tier: 2 | Scheduling logic invariant
    def test_program_returns_list(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        assert isinstance(result, list), (
            "Resolver must return a list, got: " + type(result).__name__
        )

    # CONTRACT: INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001
    # All episodes in the program are present in the result.
    # Tier: 2 | Scheduling logic invariant
    def test_program_returns_all_episodes(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        expected = {
            "seinfeld-s01e01", "seinfeld-s01e02", "seinfeld-s01e03",
            "seinfeld-s02e01", "seinfeld-s02e02",
        }
        assert set(result) == expected

    # CONTRACT: INV-ASSET-RESOLUTION-PROGRAM-RESOLVE-001
    # Result has exactly as many elements as the program has episodes.
    # Tier: 2 | Scheduling logic invariant
    def test_program_returns_correct_count(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        assert len(result) == 5

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Every element is a valid asset ID string in the catalog.
    # Tier: 2 | Scheduling logic invariant
    def test_program_elements_are_asset_ids(self):
        resolver = _make_resolver()
        catalog = _build_catalog()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        for asset_id in result:
            assert isinstance(asset_id, str), (
                f"Expected string, got {type(asset_id).__name__}"
            )
            assert asset_id in catalog, (
                f"Resolver returned '{asset_id}' which is not in the catalog"
            )

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # The resolver never returns Program objects — only asset ID strings.
    # Tier: 2 | Scheduling logic invariant
    def test_program_result_contains_no_program_objects(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        for item in result:
            assert isinstance(item, str), (
                f"Expected asset ID string, got {type(item).__name__}: {item}"
            )
            assert not isinstance(item, (dict, list, tuple, set)), (
                f"Result element must be a plain string, got {type(item).__name__}"
            )


# ===========================================================================
# INV-ASSET-RESOLUTION-PROGRAM-ORDER-001
# Program output is ordered by (season_number, episode_number).
# ===========================================================================

class TestProgramResolutionOrder:
    """Program resolution must return assets in episode sequence order."""

    # CONTRACT: INV-ASSET-RESOLUTION-PROGRAM-ORDER-001
    # Episodes are ordered by (season, episode) ascending.
    # Tier: 2 | Scheduling logic invariant
    def test_program_order_matches_episode_sequence(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        expected_order = [
            "seinfeld-s01e01",
            "seinfeld-s01e02",
            "seinfeld-s01e03",
            "seinfeld-s02e01",
            "seinfeld-s02e02",
        ]
        assert result == expected_order, (
            f"Expected episode order {expected_order}, got {result}"
        )

    # CONTRACT: INV-ASSET-RESOLUTION-PROGRAM-ORDER-001
    # Season boundaries are respected: all S01 before all S02.
    # Tier: 2 | Scheduling logic invariant
    def test_program_season_order(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        # First three must be S01, last two must be S02
        s01_assets = {"seinfeld-s01e01", "seinfeld-s01e02", "seinfeld-s01e03"}
        s02_assets = {"seinfeld-s02e01", "seinfeld-s02e02"}
        assert set(result[:3]) == s01_assets
        assert set(result[3:]) == s02_assets

    # CONTRACT: INV-ASSET-RESOLUTION-PROGRAM-ORDER-001
    # Order is deterministic across invocations.
    # Tier: 2 | Scheduling logic invariant
    def test_program_order_is_deterministic(self):
        resolver = _make_resolver()
        result1 = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        result2 = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        assert result1 == result2, "Program resolution must be deterministic"


# ===========================================================================
# INV-ASSET-RESOLUTION-EMPTY-FAIL-001
# Program failure conditions.
# ===========================================================================

class TestProgramFailures:
    """Program resolution failures must be explicit."""

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Unknown program name is a hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_unknown_program_raises(self):
        resolver = _make_resolver()
        with pytest.raises(KeyError) as exc_info:
            _resolve(resolver, {"type": "program", "name": "UnknownShow"})
        assert "UnknownShow" in str(exc_info.value)

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Program with zero episodes is a hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_empty_program_raises(self):
        _, _, AssetResolutionError = _import_source_resolver()
        resolver = _make_resolver()
        with pytest.raises(AssetResolutionError) as exc_info:
            _resolve(resolver, {"type": "program", "name": "EmptyShow"})
        assert "EmptyShow" in str(exc_info.value) or "zero" in str(exc_info.value).lower()

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Program resolution never returns None.
    # Tier: 2 | Scheduling logic invariant
    def test_program_never_returns_none(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        assert result is not None, "Resolver must return a list, never None"

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Program with episode referencing non-existent asset is a hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_program_with_bad_asset_ref_raises(self):
        SourceResolver, _, AssetResolutionError = _import_source_resolver()
        bad_programs = {
            "BrokenShow": [
                {"season": 1, "episode": 1, "asset_id": "does-not-exist"},
            ],
        }
        resolver = SourceResolver(
            catalog=_build_catalog(),
            collections=_COLLECTIONS,
            pools=_POOLS,
            programs=bad_programs,
        )
        with pytest.raises((KeyError, AssetResolutionError)):
            _resolve(resolver, {"type": "program", "name": "BrokenShow"})


# ===========================================================================
# INV-ASSET-RESOLUTION-NORMALIZE-001 (cross-cutting with programs)
# Program source produces the same output shape as other source types.
# ===========================================================================

class TestProgramNormalizationGuarantees:
    """Program resolution satisfies the same normalization invariant as other types."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Program source returns List[str] just like collection and pool.
    # Tier: 2 | Scheduling logic invariant
    def test_program_returns_list_of_strings(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # No result element is a dict, tuple, or complex object.
    # Tier: 2 | Scheduling logic invariant
    def test_program_elements_are_not_complex_objects(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "program", "name": "Seinfeld"})
        for item in result:
            assert not isinstance(item, (dict, list, tuple, set)), (
                f"Result element must be a plain string asset ID, got {type(item).__name__}"
            )
