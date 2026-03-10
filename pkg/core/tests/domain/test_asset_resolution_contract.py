# pkg/core/tests/domain/test_asset_resolution_contract.py
#
# Contract tests for the Asset Resolution domain.
#
# These tests enforce the invariants defined in:
#   docs/domains/AssetResolution.md
#
# Invariants under test:
#   INV-ASSET-RESOLUTION-NORMALIZE-001    — resolver always returns List[Asset]
#   INV-ASSET-RESOLUTION-COLLECTION-QUERY-001 — collection sources resolve via query()
#   INV-ASSET-RESOLUTION-POOL-QUERY-001   — pool sources resolve via resolve_pool()
#   INV-ASSET-RESOLUTION-EMPTY-FAIL-001   — zero-asset resolution is a hard failure
#   INV-ASSET-RESOLUTION-DISPATCH-001     — unknown source types are errors
#
# These tests target the SourceResolver interface which does NOT exist yet.
# All tests are expected to FAIL until the resolver implementation lands.

from __future__ import annotations

import pytest

from retrovue.runtime.asset_resolver import AssetMetadata


# ---------------------------------------------------------------------------
# Stub catalog — simulates the asset warehouse for resolver tests
# ---------------------------------------------------------------------------

def _build_catalog() -> dict[str, AssetMetadata]:
    """Return a small in-memory catalog for testing source resolution."""
    return {
        "intro-hbo-001": AssetMetadata(
            type="bumper",
            duration_sec=30,
            title="HBO Intro 1",
            tags=("hbo",),
            file_uri="/assets/hbo_intro_1.mpg",
        ),
        "intro-hbo-002": AssetMetadata(
            type="bumper",
            duration_sec=25,
            title="HBO Intro 2",
            tags=("hbo",),
            file_uri="/assets/hbo_intro_2.mpg",
        ),
        "intro-showtime-001": AssetMetadata(
            type="bumper",
            duration_sec=28,
            title="Showtime Intro",
            tags=("showtime",),
            file_uri="/assets/showtime_intro_1.mpg",
        ),
        "movie-001": AssetMetadata(
            type="movie",
            duration_sec=7200,
            title="Blade Runner",
            tags=("hbo", "scifi"),
            rating="R",
            file_uri="/assets/blade_runner.mkv",
        ),
        "movie-002": AssetMetadata(
            type="movie",
            duration_sec=6900,
            title="Alien",
            tags=("hbo", "scifi", "horror"),
            rating="R",
            file_uri="/assets/alien.mkv",
        ),
        "movie-003": AssetMetadata(
            type="movie",
            duration_sec=5400,
            title="Ghostbusters",
            tags=("hbo", "comedy"),
            rating="PG",
            file_uri="/assets/ghostbusters.mkv",
        ),
    }


# Collection membership: which assets belong to which collection
_COLLECTION_MEMBERSHIP: dict[str, list[str]] = {
    "Intros": ["intro-hbo-001", "intro-hbo-002", "intro-showtime-001"],
    "Movies": ["movie-001", "movie-002", "movie-003"],
    "Empty": [],
}

# Pool definitions: named queries with match criteria
_POOL_DEFINITIONS: dict[str, dict] = {
    "hbo_movies": {
        "match": {"type": "movie", "tags": ["hbo"]},
    },
    "empty_pool": {
        "match": {"type": "documentary"},  # no documentaries in catalog
    },
}


# ---------------------------------------------------------------------------
# Import the SourceResolver — this will fail until the implementation exists
# ---------------------------------------------------------------------------

def _import_source_resolver():
    """Attempt to import the SourceResolver class.

    Returns (SourceResolver_class, InvalidSourceTypeError_class) or raises
    ImportError/AttributeError if the module does not exist yet.
    """
    from retrovue.runtime.source_resolver import SourceResolver, InvalidSourceTypeError
    return SourceResolver, InvalidSourceTypeError


def _make_resolver():
    """Construct a SourceResolver wired to the test catalog.

    The SourceResolver is expected to accept:
      - catalog: dict[str, AssetMetadata]  (asset_id -> metadata)
      - collections: dict[str, list[str]]  (collection_name -> [asset_id, ...])
      - pools: dict[str, dict]             (pool_name -> pool definition)
    """
    SourceResolver, _ = _import_source_resolver()
    return SourceResolver(
        catalog=_build_catalog(),
        collections=_COLLECTION_MEMBERSHIP,
        pools=_POOL_DEFINITIONS,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve(resolver, source: dict) -> list[str]:
    """Call resolver.resolve(source) and return the result."""
    return resolver.resolve(source)


# ===========================================================================
# INV-ASSET-RESOLUTION-COLLECTION-QUERY-001
# Collection sources resolve via query by collection name.
# ===========================================================================

class TestCollectionSourceResolution:
    """Collection source resolves to the assets within that collection."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # The resolver always returns List[Asset], not a Collection object.
    # Tier: 2 | Scheduling logic invariant
    def test_collection_returns_list(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "collection", "name": "Intros"})
        assert isinstance(result, list), (
            "Resolver must return a list, got: " + type(result).__name__
        )

    # CONTRACT: INV-ASSET-RESOLUTION-COLLECTION-QUERY-001
    # Collection source returns all assets belonging to that collection.
    # Tier: 2 | Scheduling logic invariant
    def test_collection_returns_all_member_assets(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "collection", "name": "Intros"})
        assert set(result) == {"intro-hbo-001", "intro-hbo-002", "intro-showtime-001"}

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Every element in the result is an asset ID that exists in the catalog.
    # Tier: 2 | Scheduling logic invariant
    def test_collection_elements_are_asset_ids(self):
        resolver = _make_resolver()
        catalog = _build_catalog()
        result = _resolve(resolver, {"type": "collection", "name": "Intros"})
        for asset_id in result:
            assert asset_id in catalog, (
                f"Resolver returned '{asset_id}' which is not a valid asset ID"
            )

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # The resolver never returns a Collection object — only asset IDs.
    # Tier: 2 | Scheduling logic invariant
    def test_collection_result_contains_no_collection_objects(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "collection", "name": "Intros"})
        for item in result:
            assert isinstance(item, str), (
                f"Expected asset ID string, got {type(item).__name__}: {item}"
            )

    # CONTRACT: INV-ASSET-RESOLUTION-COLLECTION-QUERY-001
    # A different collection returns its own members, not another's.
    # Tier: 2 | Scheduling logic invariant
    def test_collection_movies_returns_movie_assets(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "collection", "name": "Movies"})
        assert set(result) == {"movie-001", "movie-002", "movie-003"}


# ===========================================================================
# INV-ASSET-RESOLUTION-POOL-QUERY-001
# Pool sources resolve via match criteria evaluation.
# ===========================================================================

class TestPoolSourceResolution:
    """Pool source evaluates match criteria and returns matching assets."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Pool resolution returns a list, not a Pool object.
    # Tier: 2 | Scheduling logic invariant
    def test_pool_returns_list(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "pool", "name": "hbo_movies"})
        assert isinstance(result, list), (
            "Resolver must return a list, got: " + type(result).__name__
        )

    # CONTRACT: INV-ASSET-RESOLUTION-POOL-QUERY-001
    # Pool match criteria are evaluated against the catalog.
    # Tier: 2 | Scheduling logic invariant
    def test_pool_returns_matching_assets(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "pool", "name": "hbo_movies"})
        # All three movies have the "hbo" tag
        assert len(result) >= 1
        catalog = _build_catalog()
        for asset_id in result:
            meta = catalog[asset_id]
            assert meta.type == "movie", (
                f"Pool hbo_movies returned non-movie asset: {asset_id}"
            )

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Pool result elements are asset ID strings.
    # Tier: 2 | Scheduling logic invariant
    def test_pool_elements_are_asset_ids(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "pool", "name": "hbo_movies"})
        for item in result:
            assert isinstance(item, str), (
                f"Expected asset ID string, got {type(item).__name__}: {item}"
            )


# ===========================================================================
# INV-ASSET-RESOLUTION-NORMALIZE-001 (asset source type)
# Direct asset reference resolves to a single-element list.
# ===========================================================================

class TestAssetSourceResolution:
    """Asset source type resolves a direct asset reference."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Even a direct asset reference returns List[Asset], not a bare asset.
    # Tier: 2 | Scheduling logic invariant
    def test_asset_returns_list(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "asset", "id": "intro-hbo-001"})
        assert isinstance(result, list)

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # Direct asset reference returns exactly one element.
    # Tier: 2 | Scheduling logic invariant
    def test_asset_returns_single_element(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "asset", "id": "intro-hbo-001"})
        assert len(result) == 1
        assert result[0] == "intro-hbo-001"

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Referencing a non-existent asset is a hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_asset_not_found_raises(self):
        resolver = _make_resolver()
        with pytest.raises(KeyError):
            _resolve(resolver, {"type": "asset", "id": "does-not-exist"})


# ===========================================================================
# INV-ASSET-RESOLUTION-DISPATCH-001
# Unknown source types are compile errors.
# ===========================================================================

class TestInvalidSourceType:
    """Unknown source types must raise InvalidSourceTypeError."""

    # CONTRACT: INV-ASSET-RESOLUTION-DISPATCH-001
    # The resolver rejects source types it does not recognize.
    # Tier: 2 | Scheduling logic invariant
    def test_unknown_type_raises(self):
        _, InvalidSourceTypeError = _import_source_resolver()
        resolver = _make_resolver()
        with pytest.raises(InvalidSourceTypeError):
            _resolve(resolver, {"type": "unknown", "name": "whatever"})

    # CONTRACT: INV-ASSET-RESOLUTION-DISPATCH-001
    # Missing type key is also an error.
    # Tier: 2 | Scheduling logic invariant
    def test_missing_type_raises(self):
        _, InvalidSourceTypeError = _import_source_resolver()
        resolver = _make_resolver()
        with pytest.raises(InvalidSourceTypeError):
            _resolve(resolver, {"name": "whatever"})

    # CONTRACT: INV-ASSET-RESOLUTION-DISPATCH-001
    # Empty source dict is an error.
    # Tier: 2 | Scheduling logic invariant
    def test_empty_source_raises(self):
        _, InvalidSourceTypeError = _import_source_resolver()
        resolver = _make_resolver()
        with pytest.raises(InvalidSourceTypeError):
            _resolve(resolver, {})


# ===========================================================================
# INV-ASSET-RESOLUTION-EMPTY-FAIL-001
# Zero-asset resolution is a hard failure.
# ===========================================================================

class TestEmptyResolution:
    """When a source resolves to zero assets, the resolver must fail explicitly."""

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Empty collection → hard failure, not an empty list or None.
    # Tier: 2 | Scheduling logic invariant
    def test_empty_collection_raises(self):
        resolver = _make_resolver()
        with pytest.raises(Exception) as exc_info:
            _resolve(resolver, {"type": "collection", "name": "Empty"})
        # The error must be informative
        assert "Empty" in str(exc_info.value) or "zero" in str(exc_info.value).lower()

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Pool that matches nothing → hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_empty_pool_raises(self):
        resolver = _make_resolver()
        with pytest.raises(Exception) as exc_info:
            _resolve(resolver, {"type": "pool", "name": "empty_pool"})
        assert "empty_pool" in str(exc_info.value) or "zero" in str(exc_info.value).lower()

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Unknown collection name → hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_unknown_collection_raises(self):
        resolver = _make_resolver()
        with pytest.raises(Exception):
            _resolve(resolver, {"type": "collection", "name": "NonExistent"})

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # Unknown pool name → hard failure.
    # Tier: 2 | Scheduling logic invariant
    def test_unknown_pool_raises(self):
        resolver = _make_resolver()
        with pytest.raises(KeyError):
            _resolve(resolver, {"type": "pool", "name": "no_such_pool"})

    # CONTRACT: INV-ASSET-RESOLUTION-EMPTY-FAIL-001
    # The resolver never returns None.
    # Tier: 2 | Scheduling logic invariant
    def test_resolver_never_returns_none(self):
        resolver = _make_resolver()
        result = _resolve(resolver, {"type": "collection", "name": "Intros"})
        assert result is not None, "Resolver must return a list, never None"


# ===========================================================================
# INV-ASSET-RESOLUTION-NORMALIZE-001 (structural guarantees)
# Cross-cutting: resolver output is always List[str] of asset IDs.
# ===========================================================================

class TestNormalizationGuarantees:
    """The resolver always produces List[str] regardless of source type."""

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # All source types produce the same output type.
    # Tier: 2 | Scheduling logic invariant
    @pytest.mark.parametrize("source", [
        {"type": "collection", "name": "Intros"},
        {"type": "pool", "name": "hbo_movies"},
        {"type": "asset", "id": "movie-001"},
    ])
    def test_all_source_types_return_list_of_strings(self, source):
        resolver = _make_resolver()
        result = _resolve(resolver, source)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, str)

    # CONTRACT: INV-ASSET-RESOLUTION-NORMALIZE-001
    # No result element is a dict, tuple, or complex object — only plain strings.
    # Tier: 2 | Scheduling logic invariant
    @pytest.mark.parametrize("source", [
        {"type": "collection", "name": "Movies"},
        {"type": "pool", "name": "hbo_movies"},
    ])
    def test_result_elements_are_not_complex_objects(self, source):
        resolver = _make_resolver()
        result = _resolve(resolver, source)
        for item in result:
            assert not isinstance(item, (dict, list, tuple, set)), (
                f"Result element must be a plain string asset ID, got {type(item).__name__}"
            )
