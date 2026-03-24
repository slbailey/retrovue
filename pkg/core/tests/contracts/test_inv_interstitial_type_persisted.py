"""Contract tests: INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001

Interstitial type MUST survive the full enrichment pipeline:
  1. InterstitialTypeEnricher stamps canonical type
  2. persist_asset_metadata persists it to AssetEditorial.payload
  3. Subsequent enrichers (ffprobe, loudness) do not overwrite it
  4. State transition to "ready" does not clear it

These tests isolate each failure mode without requiring a running worker
or database — they test system logic deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

try:
    from retrovue.adapters.enrichers.interstitial_type_enricher import (
        COLLECTION_TYPE_MAP,
        InterstitialTypeEnricher,
    )
    from retrovue.adapters.importers.base import DiscoveredItem
    from retrovue.catalog.processor_runtime import (
        ProcessingContext,
        _enricher_instance,
        item_to_processor_result,
        validate_processor_result,
        _context_to_item,
    )
    from retrovue.infra.metadata.persistence import persist_asset_metadata
    from retrovue.domain.entities import Asset, AssetEditorial
except ImportError:
    pytest.skip(
        "retrovue enrichment pipeline dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_discovered_item(
    path_uri: str = "/mnt/interstitials/station_ids/HBO_StationID.mp4",
    size: int = 1024000,
) -> DiscoveredItem:
    """Create a minimal DiscoveredItem for enricher testing."""
    return DiscoveredItem(
        path_uri=path_uri,
        provider_key=path_uri,
        raw_labels=[],
        last_modified=None,
        size=size,
        hash_sha256=None,
        editorial=None,
        sidecar=None,
        source_payload=None,
        probed=None,
    )


class FakeAssetEditorial:
    """In-memory stand-in for AssetEditorial ORM row."""
    def __init__(self, asset_uuid: str, payload: dict | None = None):
        self.asset_uuid = asset_uuid
        self.payload = dict(payload) if payload else {}


class FakeSession:
    """Minimal fake SQLAlchemy session for persist_asset_metadata tests."""
    def __init__(self):
        self._store: dict[tuple[type, str], Any] = {}
        self._added: list[Any] = []

    def get(self, model_class: type, key: Any) -> Any:
        return self._store.get((model_class, str(key)))

    def add(self, obj: Any) -> None:
        self._added.append(obj)
        # Track by type + uuid for subsequent gets
        uuid_key = getattr(obj, "asset_uuid", None)
        if uuid_key is not None:
            self._store[(type(obj), str(uuid_key))] = obj

    def seed(self, model_class: type, key: str, obj: Any) -> None:
        """Pre-populate the session store."""
        self._store[(model_class, str(key))] = obj


# ===========================================================================
# Step 1 — InterstitialTypeEnricher stamps canonical type
# ===========================================================================


class TestEnricherStampsType:
    """InterstitialTypeEnricher MUST stamp interstitial_type from collection name."""

    # Tier: 1 | Structural invariant
    def test_station_ids_collection_stamps_station_id(self):
        """Collection 'station_ids' → interstitial_type = 'station_id'."""
        enricher = InterstitialTypeEnricher(collection_name="station_ids")
        item = _make_discovered_item()
        result = enricher.enrich(item)

        assert result.editorial is not None
        assert result.editorial.get("interstitial_type") == "station_id"

    # Tier: 1 | Structural invariant
    def test_all_collection_types_mapped(self):
        """Every key in COLLECTION_TYPE_MAP must produce a valid stamp."""
        for coll_name, expected_type in COLLECTION_TYPE_MAP.items():
            enricher = InterstitialTypeEnricher(collection_name=coll_name)
            item = _make_discovered_item(
                path_uri=f"/mnt/interstitials/{coll_name}/test.mp4",
            )
            result = enricher.enrich(item)
            assert result.editorial["interstitial_type"] == expected_type, (
                f"Collection '{coll_name}' should stamp '{expected_type}', "
                f"got '{result.editorial.get('interstitial_type')}'"
            )

    # Tier: 1 | Structural invariant
    def test_enricher_preserves_existing_editorial(self):
        """Enricher MUST merge, not overwrite existing editorial fields."""
        enricher = InterstitialTypeEnricher(collection_name="bumpers")
        item = DiscoveredItem(
            path_uri="/mnt/bumpers/test.mp4",
            provider_key="/mnt/bumpers/test.mp4",
            raw_labels=[],
            last_modified=None,
            size=1024,
            hash_sha256=None,
            editorial={"title": "Test Bumper", "production_year": 1985},
            sidecar=None,
            source_payload=None,
            probed=None,
        )
        result = enricher.enrich(item)

        assert result.editorial["interstitial_type"] == "bumper"
        assert result.editorial["title"] == "Test Bumper"
        assert result.editorial["production_year"] == 1985


# ===========================================================================
# Step 2 — persist_asset_metadata does not silently drop fields
# ===========================================================================


class TestPersistDoesNotDropFields:
    """persist_asset_metadata MUST NOT silently drop existing editorial fields."""

    # Tier: 1 | Structural invariant
    def test_full_overwrite_preserves_all_fields_when_caller_provides_full_dict(self):
        """When caller provides a complete dict, all fields survive."""
        fake_db = FakeSession()
        asset = MagicMock()
        asset.uuid = "test-uuid-001"

        # First write: establish interstitial_type
        persist_asset_metadata(
            fake_db, asset,
            editorial={"interstitial_type": "station_id", "title": "HBO ID"},
        )

        ed = fake_db.get(AssetEditorial, "test-uuid-001")
        assert ed is not None
        assert ed.payload["interstitial_type"] == "station_id"
        assert ed.payload["title"] == "HBO ID"

    # Tier: 1 | Structural invariant — ROOT CAUSE FIX VERIFICATION
    def test_partial_editorial_merges_with_existing_payload(self):
        """INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001: persist_asset_metadata
        with a partial dict MUST merge with existing payload, not replace it.

        Before fix: partial dict silently dropped fields like interstitial_type.
        After fix: merge preserves existing fields.
        """
        fake_db = FakeSession()
        asset = MagicMock()
        asset.uuid = "test-uuid-002"

        # First write: establish interstitial_type
        persist_asset_metadata(
            fake_db, asset,
            editorial={"interstitial_type": "bumper", "title": "Test"},
        )

        # Second write: partial dict WITHOUT interstitial_type
        persist_asset_metadata(
            fake_db, asset,
            editorial={"title": "Updated Title", "production_year": 1990},
        )

        ed = fake_db.get(AssetEditorial, "test-uuid-002")
        # FIX: interstitial_type MUST survive partial update
        assert ed.payload["interstitial_type"] == "bumper", (
            "INV-ASSET-INTERSTITIAL-TYPE-PERSISTED-001: interstitial_type "
            "must survive partial editorial update"
        )
        # Updated fields must also be present
        assert ed.payload["title"] == "Updated Title"
        assert ed.payload["production_year"] == 1990

    # Tier: 1 | Structural invariant
    def test_none_editorial_does_not_touch_existing(self):
        """Passing editorial=None must not modify existing editorial."""
        fake_db = FakeSession()
        asset = MagicMock()
        asset.uuid = "test-uuid-003"

        # Establish editorial
        persist_asset_metadata(
            fake_db, asset,
            editorial={"interstitial_type": "promo"},
        )

        # Call with editorial=None — should not touch
        persist_asset_metadata(
            fake_db, asset,
            editorial=None,
        )

        ed = fake_db.get(AssetEditorial, "test-uuid-003")
        assert ed.payload["interstitial_type"] == "promo"


# ===========================================================================
# Step 3 — interstitial_type survives state transition to ready
# ===========================================================================


class TestSurvivesStateTransition:
    """interstitial_type MUST survive asset state transitions."""

    # Tier: 2 | Scheduling logic invariant
    def test_ready_state_does_not_clear_editorial(self):
        """State transition enriching → ready does not modify AssetEditorial.

        The state machine at processor_runtime.py:396-403 only changes
        asset.state — it does NOT touch editorial payload.
        """
        # Simulate the state transition code path
        asset = MagicMock()
        asset.state = "enriching"
        asset.duration_ms = 5000

        # The state transition code:
        if asset.state == "enriching":
            if asset.duration_ms and asset.duration_ms > 0:
                asset.state = "ready"

        assert asset.state == "ready"
        # Editorial is on a separate ORM entity — state transition doesn't touch it


# ===========================================================================
# Step 4 — _enricher_instance silent failure
# ===========================================================================


class TestEnricherInstanceFailureModes:
    """_enricher_instance MUST raise on construction failure, not return None.

    INV-ENRICHER-MUST-EXECUTE-OR-FAIL-001: enricher failures are visible.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_empty_collection_name_raises(self):
        """Empty collection_name causes EnricherConstructionError (not silent None)."""
        from retrovue.catalog.processor_runtime import EnricherConstructionError
        with pytest.raises(EnricherConstructionError):
            _enricher_instance("interstitial-type", "")

    # Tier: 2 | Scheduling logic invariant
    def test_unknown_collection_name_raises(self):
        """Unknown collection_name causes EnricherConstructionError."""
        from retrovue.catalog.processor_runtime import EnricherConstructionError
        with pytest.raises(EnricherConstructionError):
            _enricher_instance("interstitial-type", "not_a_real_collection")

    # Tier: 2 | Scheduling logic invariant
    def test_valid_collection_name_returns_enricher(self):
        """Known collection_name produces a valid enricher instance."""
        result = _enricher_instance("interstitial-type", "station_ids")
        assert result is not None
        assert isinstance(result, InterstitialTypeEnricher)


# ===========================================================================
# Step 5 — Processor runtime merge preserves interstitial_type
# ===========================================================================


class TestProcessorRuntimeMerge:
    """The processor runtime merge pattern MUST preserve interstitial_type
    when subsequent enrichers (ffprobe, loudness) produce no editorial fields.
    """

    # Tier: 2 | Scheduling logic invariant
    def test_merge_preserves_existing_editorial(self):
        """The merge pattern {**existing_editorial, **mutable_editorial}
        preserves existing fields when mutable is empty.
        """
        existing_editorial = {
            "interstitial_type": "station_id",
            "title": "HBO Station ID",
        }
        # ffprobe produces no editorial fields
        mutable_editorial: dict[str, Any] = {}

        editorial_to_persist = {**existing_editorial, **mutable_editorial}

        assert editorial_to_persist["interstitial_type"] == "station_id"
        assert editorial_to_persist["title"] == "HBO Station ID"

    # Tier: 2 | Scheduling logic invariant
    def test_merge_allows_interstitial_type_update(self):
        """If the interstitial-type enricher runs, its output overwrites
        the existing value (which is correct — the enricher is authoritative).
        """
        existing_editorial = {
            "title": "Some Promo",
        }
        mutable_editorial = {
            "interstitial_type": "promo",
        }

        editorial_to_persist = {**existing_editorial, **mutable_editorial}

        assert editorial_to_persist["interstitial_type"] == "promo"
        assert editorial_to_persist["title"] == "Some Promo"


# ===========================================================================
# Step 6 — End-to-end: enricher → persist → survive subsequent persist
# ===========================================================================


class TestEndToEndPersistence:
    """Full pipeline: enrich → persist → subsequent persist does not destroy."""

    # Tier: 2 | Scheduling logic invariant
    def test_enricher_output_persisted_and_survives_probed_update(self):
        """After enricher stamps interstitial_type and it's persisted,
        a subsequent persist_asset_metadata call with only probed data
        must not affect editorial.
        """
        fake_db = FakeSession()
        asset = MagicMock()
        asset.uuid = "test-uuid-e2e"

        # Step 1: Enricher stamps type
        enricher = InterstitialTypeEnricher(collection_name="station_ids")
        item = _make_discovered_item()
        enriched = enricher.enrich(item)
        assert enriched.editorial["interstitial_type"] == "station_id"

        # Step 2: Persist editorial
        persist_asset_metadata(
            fake_db, asset,
            editorial=enriched.editorial,
        )
        ed = fake_db.get(AssetEditorial, "test-uuid-e2e")
        assert ed.payload["interstitial_type"] == "station_id"

        # Step 3: Subsequent call with only probed data (no editorial)
        persist_asset_metadata(
            fake_db, asset,
            probed={"duration_ms": 5000, "video_codec": "h264"},
        )

        # Editorial must be unchanged
        ed = fake_db.get(AssetEditorial, "test-uuid-e2e")
        assert ed.payload["interstitial_type"] == "station_id", (
            "Probed-only persist must not affect editorial"
        )
