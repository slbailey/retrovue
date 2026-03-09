"""
Contract tests for INV-INTERSTITIAL-TYPE-STAMP-001.

Validates that the InterstitialTypeEnricher correctly maps filesystem
collection names to canonical interstitial types during ingest, and that
the traffic layer never references collection names.
"""

from __future__ import annotations

import pytest

try:
    from retrovue.adapters.enrichers.interstitial_type_enricher import (
        COLLECTION_TYPE_MAP,
        CANONICAL_INTERSTITIAL_TYPES,
        InterstitialTypeEnricher,
    )
except ImportError:
    pytestmark = pytest.mark.xfail(reason="interstitial_type_enricher not yet implemented")

from retrovue.adapters.importers.base import DiscoveredItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(editorial: dict | None = None) -> DiscoveredItem:
    """Build a minimal DiscoveredItem for testing."""
    return DiscoveredItem(
        path_uri="file:///mnt/data/Interstitials/commercials/spot1.mp4",
        provider_key="spot1.mp4",
        size=1024,
        editorial=editorial,
    )


# ---------------------------------------------------------------------------
# Known collection → canonical type mapping
# ---------------------------------------------------------------------------

class TestKnownCollectionMapping:
    """Each known collection maps to the correct canonical interstitial type."""

    @pytest.mark.parametrize("collection_name,expected_type", [
        ("bumpers", "bumper"),
        ("commercials", "commercial"),
        ("promos", "promo"),
        ("psas", "psa"),
        ("station_ids", "station_id"),
        ("trailers", "trailer"),
        ("teasers", "teaser"),
        ("shortform", "shortform"),
        ("oddities", "filler"),
    ])
    def test_collection_maps_to_canonical_type(self, collection_name: str, expected_type: str):
        enricher = InterstitialTypeEnricher(collection_name=collection_name)
        result = enricher.enrich(_item())

        assert result.editorial is not None
        assert result.editorial["interstitial_type"] == expected_type

    def test_all_canonical_types_have_at_least_one_collection(self):
        """Every canonical type must be reachable from at least one collection."""
        mapped_types = set(COLLECTION_TYPE_MAP.values())
        for canonical in CANONICAL_INTERSTITIAL_TYPES:
            assert canonical in mapped_types, (
                f"Canonical type '{canonical}' has no collection mapping"
            )


# ---------------------------------------------------------------------------
# Unknown collection → error
# ---------------------------------------------------------------------------

class TestUnknownCollectionRejection:
    """Unknown collection names must raise an error, never silently default."""

    def test_unknown_collection_raises_on_construction(self):
        with pytest.raises(Exception) as exc_info:
            InterstitialTypeEnricher(collection_name="random_garbage")
        assert "random_garbage" in str(exc_info.value)

    def test_empty_collection_name_raises(self):
        with pytest.raises(Exception):
            InterstitialTypeEnricher(collection_name="")

    def test_no_silent_filler_fallback(self):
        """The enricher must NOT silently assign 'filler' to unknown collections."""
        with pytest.raises(Exception):
            InterstitialTypeEnricher(collection_name="mystery_content")


# ---------------------------------------------------------------------------
# Editorial merge behavior
# ---------------------------------------------------------------------------

class TestEditorialMerge:
    """Enricher stamps interstitial_type without destroying existing editorial."""

    def test_preserves_existing_editorial_fields(self):
        original = {"title": "Cool Ad", "size": 5000, "interstitial_category": "auto"}
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        result = enricher.enrich(_item(editorial=original))

        assert result.editorial["title"] == "Cool Ad"
        assert result.editorial["size"] == 5000
        assert result.editorial["interstitial_category"] == "auto"
        assert result.editorial["interstitial_type"] == "commercial"

    def test_overwrites_incorrect_existing_type(self):
        """Collection-level type takes precedence over file-level inference."""
        original = {"interstitial_type": "filler"}  # wrong — it's a commercial
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        result = enricher.enrich(_item(editorial=original))

        assert result.editorial["interstitial_type"] == "commercial"

    def test_stamps_type_when_editorial_is_none(self):
        enricher = InterstitialTypeEnricher(collection_name="bumpers")
        result = enricher.enrich(_item(editorial=None))

        assert result.editorial is not None
        assert result.editorial["interstitial_type"] == "bumper"

    def test_stamps_type_when_editorial_is_empty(self):
        enricher = InterstitialTypeEnricher(collection_name="psas")
        result = enricher.enrich(_item(editorial={}))

        assert result.editorial["interstitial_type"] == "psa"


# ---------------------------------------------------------------------------
# Enricher contract compliance
# ---------------------------------------------------------------------------

class TestEnricherContract:
    """InterstitialTypeEnricher conforms to enricher protocol."""

    def test_has_name_attribute(self):
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        assert hasattr(enricher, "name")
        assert enricher.name == "interstitial-type"

    def test_has_ingest_scope(self):
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        assert enricher.scope == "ingest"

    def test_returns_discovered_item(self):
        enricher = InterstitialTypeEnricher(collection_name="promos")
        result = enricher.enrich(_item())
        assert isinstance(result, DiscoveredItem)

    def test_preserves_non_editorial_fields(self):
        item = _item()
        enricher = InterstitialTypeEnricher(collection_name="trailers")
        result = enricher.enrich(item)

        assert result.path_uri == item.path_uri
        assert result.provider_key == item.provider_key
        assert result.size == item.size


# ---------------------------------------------------------------------------
# Architectural boundary: traffic layer independence
# ---------------------------------------------------------------------------

class TestTrafficLayerIndependence:
    """TrafficManager and TrafficPolicy must never reference collection names."""

    def test_traffic_policy_uses_canonical_types_only(self):
        """TrafficPolicy.allowed_types must contain canonical types, not collection names."""
        from retrovue.runtime.traffic_policy import TrafficPolicy

        policy = TrafficPolicy(allowed_types=frozenset(["commercial", "promo", "bumper"]))
        # All allowed_types must be canonical
        for t in policy.allowed_types:
            assert t in CANONICAL_INTERSTITIAL_TYPES, (
                f"TrafficPolicy contains non-canonical type '{t}'"
            )

    def test_canonical_types_are_not_collection_names(self):
        """Canonical types and collection names must be distinct vocabularies."""
        collection_names = set(COLLECTION_TYPE_MAP.keys())
        # Types like 'shortform' and 'filler' appear in both, which is fine.
        # But plural collection names (bumpers, commercials, etc.) must NOT
        # be used as canonical types.
        plural_collections = {n for n in collection_names if n.endswith("s") and n != "shortform"}
        for plural in plural_collections:
            assert plural not in CANONICAL_INTERSTITIAL_TYPES, (
                f"Collection name '{plural}' must not be a canonical type"
            )


# ---------------------------------------------------------------------------
# DatabaseAssetLibrary: query by interstitial_type, not collection
# ---------------------------------------------------------------------------

class TestAssetLibraryQueriesByType:
    """INV-INTERSTITIAL-TYPE-STAMP-001 Architectural Boundary:

    DatabaseAssetLibrary queries assets by interstitial_type field.
    It MUST NOT query by collection name or collection UUID.
    """

    def test_get_filler_assets_does_not_use_collection_uuid_filter(self):
        """get_filler_assets() MUST NOT filter by collection_uuid.

        VIOLATION: The current implementation looks up a single Collection
        named 'Interstitials' and filters by Asset.collection_uuid == coll_uuid.
        This fails because no collection named 'Interstitials' exists — the
        interstitial assets are spread across per-type collections (bumpers,
        commercials, etc.). The contract requires filtering by
        editorial.interstitial_type instead.
        """
        import ast
        import inspect
        import textwrap

        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        tree = ast.parse(source)

        # Walk AST looking for any reference to 'collection_uuid'
        collection_uuid_refs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "collection_uuid":
                collection_uuid_refs.append(node.lineno)

        assert not collection_uuid_refs, (
            f"INV-INTERSTITIAL-TYPE-STAMP-001: DatabaseAssetLibrary.get_filler_assets() "
            f"references 'collection_uuid' at line(s) {collection_uuid_refs}. "
            f"The contract requires querying by editorial.interstitial_type, "
            f"NOT by collection UUID. Collection topology is invisible to the "
            f"traffic layer."
        )

    def test_get_filler_assets_does_not_call_collection_lookup(self):
        """get_filler_assets() MUST NOT call _get_interstitial_collection_uuid().

        The collection lookup method is a violation of the architectural
        boundary: the traffic layer must not reference storage topology.
        """
        import ast
        import inspect
        import textwrap

        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "_get_interstitial_collection_uuid":
                    pytest.fail(
                        "INV-INTERSTITIAL-TYPE-STAMP-001: get_filler_assets() calls "
                        "_get_interstitial_collection_uuid(). The contract requires "
                        "querying by editorial.interstitial_type, not by collection."
                    )

    def test_get_filler_assets_filters_by_interstitial_type(self):
        """get_filler_assets() MUST filter candidates by interstitial_type
        from editorial payload."""
        import ast
        import inspect
        import textwrap

        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))

        # The function must reference 'interstitial_type' — either in the
        # query filter or in the candidate filtering logic
        assert "interstitial_type" in source, (
            "INV-INTERSTITIAL-TYPE-STAMP-001: get_filler_assets() does not "
            "reference 'interstitial_type'. It MUST filter assets by the "
            "editorial.interstitial_type field stamped during ingest."
        )


# ---------------------------------------------------------------------------
# Re-enrichment: apply_enrichers_to_collection must auto-inject and persist
# ---------------------------------------------------------------------------

class TestReEnrichmentPath:
    """INV-INTERSTITIAL-TYPE-STAMP-001 requires ALL interstitial assets to
    have interstitial_type stamped. Assets ingested before the enricher
    existed MUST be fixable via `retrovue collection sync --enrich-only`,
    which calls apply_enrichers_to_collection().
    """

    def test_apply_enrichers_auto_injects_interstitial_type_enricher(self):
        """apply_enrichers_to_collection() MUST auto-inject
        InterstitialTypeEnricher for interstitial collections, just like
        the ingest path does.

        VIOLATION: The current implementation only runs enrichers from
        collection.config['enrichers']. It does not auto-inject
        InterstitialTypeEnricher, so `collection sync --enrich-only`
        on an interstitial collection silently skips the type stamp.
        """
        import inspect
        import textwrap

        from retrovue.usecases.collection_enrichers import (
            apply_enrichers_to_collection,
        )

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        assert "InterstitialTypeEnricher" in source, (
            "INV-INTERSTITIAL-TYPE-STAMP-001: apply_enrichers_to_collection() "
            "does not reference InterstitialTypeEnricher. It MUST auto-inject "
            "the enricher for interstitial collections, matching the ingest path."
        )

    def test_apply_enrichers_persists_editorial(self):
        """apply_enrichers_to_collection() MUST persist item.editorial into
        AssetEditorial.payload.

        VIOLATION: The current implementation maps enricher labels back to
        asset fields (duration_ms, codecs) but never persists item.editorial.
        InterstitialTypeEnricher stamps into item.editorial, so the type
        stamp is silently dropped.
        """
        import inspect
        import textwrap

        from retrovue.usecases.collection_enrichers import (
            apply_enrichers_to_collection,
        )

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        # Editorial persistence may be inline (AssetEditorial) or delegated
        # to enrich_asset() which handles it in the unified lifecycle.
        has_inline = "AssetEditorial" in source
        has_delegation = "enrich_asset" in source
        assert has_inline or has_delegation, (
            "INV-INTERSTITIAL-TYPE-STAMP-001: apply_enrichers_to_collection() "
            "does not persist item.editorial into AssetEditorial.payload "
            "(directly or via enrich_asset delegation). "
            "Enrichers that stamp editorial fields (like InterstitialTypeEnricher) "
            "will have their output silently dropped."
        )


# ---------------------------------------------------------------------------
# Mapping table completeness
# ---------------------------------------------------------------------------

class TestMappingCompleteness:
    """The mapping table covers the expected filesystem layout."""

    def test_all_interstitials_subdirs_mapped(self):
        """All known /mnt/data/Interstitials subdirectories with content have mappings."""
        expected_dirs = {
            "bumpers", "commercials", "promos", "psas", "station_ids",
            "trailers", "teasers", "shortform", "oddities",
        }
        for d in expected_dirs:
            assert d in COLLECTION_TYPE_MAP, (
                f"Directory '{d}' missing from COLLECTION_TYPE_MAP"
            )

    def test_mapped_types_are_all_canonical(self):
        """Every value in the mapping table must be a canonical type."""
        for collection, ctype in COLLECTION_TYPE_MAP.items():
            assert ctype in CANONICAL_INTERSTITIAL_TYPES, (
                f"Collection '{collection}' maps to non-canonical type '{ctype}'"
            )
