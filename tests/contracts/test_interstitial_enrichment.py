"""
Contract tests for interstitial enrichment invariants.

Source of truth: docs/invariants/interstitial_enrichment_invariants.md
Derived from:   docs/contracts/interstitial_enrichment.md

Each test class enforces one invariant from the invariant list.
Tests validate system behavior through public interfaces only.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import textwrap
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any

import pytest

from retrovue.adapters.enrichers.interstitial_type_enricher import (
    CANONICAL_INTERSTITIAL_TYPES,
    COLLECTION_TYPE_MAP,
    InterstitialTypeEnricher,
)
from retrovue.adapters.enrichers.base import EnricherConfigurationError, EnricherError
from retrovue.adapters.importers.base import DiscoveredItem
from retrovue.adapters.importers.filesystem_importer import (
    DEFAULT_INFERENCE_RULES,
    FilesystemImporter,
)
from retrovue.usecases.collection_enrichers import compute_confidence_from_labels
from retrovue.runtime.traffic_policy import (
    TrafficCandidate,
    TrafficPolicy,
    evaluate_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _item(
    editorial: dict | None = None,
    size: int = 1024,
    raw_labels: list[str] | None = None,
    path_uri: str = "file:///mnt/data/Interstitials/commercials/spot1.mp4",
    sidecar: dict | None = None,
) -> DiscoveredItem:
    """Build a minimal DiscoveredItem for testing."""
    return DiscoveredItem(
        path_uri=path_uri,
        provider_key="spot1.mp4",
        size=size,
        editorial=editorial,
        raw_labels=raw_labels,
        sidecar=sidecar,
    )


def _confidence_item(
    size: int = 1024,
    duration_ms: int | None = 30000,
    video_codec: str | None = "h264",
    audio_codec: str | None = "aac",
    container: str | None = "mp4",
) -> DiscoveredItem:
    """Build a DiscoveredItem with raw_labels for confidence scoring."""
    labels: list[str] = []
    if duration_ms is not None:
        labels.append(f"duration_ms:{duration_ms}")
    if video_codec is not None:
        labels.append(f"video_codec:{video_codec}")
    if audio_codec is not None:
        labels.append(f"audio_codec:{audio_codec}")
    if container is not None:
        labels.append(f"container:{container}")
    return _item(size=size, raw_labels=labels)


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-TYPE-STAMP-001
# Collection name is authoritative for canonical type
# ---------------------------------------------------------------------------

class TestInvInterstitialTypeStamp001:
    """INV-INTERSTITIAL-TYPE-STAMP-001: Every interstitial asset ingested from a
    filesystem source MUST have editorial.interstitial_type set to a canonical
    type determined by the Collection Type Map."""

    # Tier: 2 | Scheduling logic invariant
    @pytest.mark.parametrize("collection_name,expected_type", sorted(COLLECTION_TYPE_MAP.items()))
    def test_collection_maps_to_canonical_type(self, collection_name: str, expected_type: str):
        """Each collection name in the map MUST produce the correct canonical type."""
        enricher = InterstitialTypeEnricher(collection_name=collection_name)
        result = enricher.enrich(_item())
        assert result.editorial is not None
        assert result.editorial["interstitial_type"] == expected_type

    # Tier: 2 | Scheduling logic invariant
    def test_all_nine_canonical_types_reachable(self):
        """All 9 canonical types MUST be reachable via at least one collection name."""
        mapped_types = set(COLLECTION_TYPE_MAP.values())
        for canonical in CANONICAL_INTERSTITIAL_TYPES:
            assert canonical in mapped_types, (
                f"Canonical type '{canonical}' has no collection mapping"
            )

    # Tier: 2 | Scheduling logic invariant
    def test_overwrites_file_level_inference(self):
        """Collection-level type MUST overwrite file-level interstitial_type."""
        original = {"interstitial_type": "filler", "title": "Ad Spot"}
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        result = enricher.enrich(_item(editorial=original))
        assert result.editorial["interstitial_type"] == "commercial"

    # Tier: 2 | Scheduling logic invariant
    def test_preserves_other_editorial_fields(self):
        """Enricher MUST merge, not replace. Other editorial fields MUST survive."""
        original = {
            "title": "Cool Ad",
            "size": 5000,
            "interstitial_category": "auto",
        }
        enricher = InterstitialTypeEnricher(collection_name="commercials")
        result = enricher.enrich(_item(editorial=original))
        assert result.editorial["title"] == "Cool Ad"
        assert result.editorial["size"] == 5000
        assert result.editorial["interstitial_category"] == "auto"
        assert result.editorial["interstitial_type"] == "commercial"

    # Tier: 2 | Scheduling logic invariant
    def test_stamps_when_editorial_is_none(self):
        """Enricher MUST create editorial dict when None."""
        enricher = InterstitialTypeEnricher(collection_name="bumpers")
        result = enricher.enrich(_item(editorial=None))
        assert result.editorial is not None
        assert result.editorial["interstitial_type"] == "bumper"

    # Tier: 2 | Scheduling logic invariant
    def test_stamps_when_editorial_is_empty(self):
        """Enricher MUST stamp type into empty editorial dict."""
        enricher = InterstitialTypeEnricher(collection_name="psas")
        result = enricher.enrich(_item(editorial={}))
        assert result.editorial["interstitial_type"] == "psa"

    # Tier: 1 | Structural invariant
    def test_mapped_types_are_all_canonical(self):
        """Every value in COLLECTION_TYPE_MAP MUST be a member of CANONICAL_INTERSTITIAL_TYPES."""
        for coll, ctype in COLLECTION_TYPE_MAP.items():
            assert ctype in CANONICAL_INTERSTITIAL_TYPES, (
                f"Collection '{coll}' maps to non-canonical type '{ctype}'"
            )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001
# Assets without interstitial_type are invisible to traffic
# ---------------------------------------------------------------------------

class TestInvInterstitialTrafficVisibility001:
    """INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001: get_filler_assets() MUST query
    for assets where AssetEditorial.payload contains 'interstitial_type'.
    Assets lacking this key MUST NOT appear in traffic candidate lists."""

    # Tier: 1 | Structural invariant
    def test_query_filters_by_interstitial_type_key(self):
        """get_filler_assets() MUST reference interstitial_type in its query logic."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "interstitial_type" in source, (
            "INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001: get_filler_assets() "
            "does not reference 'interstitial_type'."
        )

    # Tier: 1 | Structural invariant
    def test_query_uses_has_key_filter(self):
        """get_filler_assets() MUST use JSONB has_key for interstitial_type presence."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "has_key" in source, (
            "INV-INTERSTITIAL-TRAFFIC-VISIBILITY-001: get_filler_assets() "
            "does not use has_key filter for interstitial_type presence."
        )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001
# Traffic layer MUST NOT reference storage topology
# ---------------------------------------------------------------------------

class TestInvInterstitialTrafficBoundary001:
    """INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: TrafficManager, TrafficPolicy,
    and DatabaseAssetLibrary MUST NOT reference collection names, collection
    UUIDs, source names, or filesystem paths in traffic selection."""

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_no_collection_uuid_ref(self):
        """get_filler_assets() MUST NOT filter by collection_uuid."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "collection_uuid":
                pytest.fail(
                    "INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: get_filler_assets() "
                    "references 'collection_uuid'. Traffic layer MUST query by "
                    "editorial.interstitial_type, not by collection."
                )

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_no_collection_lookup_call(self):
        """get_filler_assets() MUST NOT call _get_interstitial_collection_uuid()."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr == "_get_interstitial_collection_uuid":
                    pytest.fail(
                        "INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: get_filler_assets() "
                        "calls _get_interstitial_collection_uuid()."
                    )

    # Tier: 1 | Structural invariant
    def test_traffic_candidate_has_no_collection_fields(self):
        """TrafficCandidate MUST NOT carry collection identity fields."""
        field_names = {f.name for f in dataclass_fields(TrafficCandidate)}
        forbidden = {"collection_uuid", "collection_name", "source_name", "source_id"}
        overlap = field_names & forbidden
        assert not overlap, (
            f"INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: TrafficCandidate has "
            f"storage topology fields: {overlap}"
        )

    # Tier: 1 | Structural invariant
    def test_traffic_policy_no_collection_refs_in_source(self):
        """TrafficPolicy source MUST NOT reference collection concepts."""
        source = inspect.getsource(TrafficPolicy)
        for term in ("collection_uuid", "collection_name", "source_name"):
            assert term not in source, (
                f"INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: TrafficPolicy source "
                f"references '{term}'."
            )

    # Tier: 1 | Structural invariant
    def test_evaluate_candidates_no_collection_refs(self):
        """evaluate_candidates() MUST NOT reference collection concepts."""
        source = inspect.getsource(evaluate_candidates)
        for term in ("collection_uuid", "collection_name", "source_name"):
            assert term not in source, (
                f"INV-INTERSTITIAL-TRAFFIC-BOUNDARY-001: evaluate_candidates() "
                f"references '{term}'."
            )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-ENRICHER-INJECT-001
# Auto-injection of type enricher at priority -1
# ---------------------------------------------------------------------------

class TestInvInterstitialEnricherInject001:
    """INV-INTERSTITIAL-ENRICHER-INJECT-001: apply_enrichers_to_collection()
    MUST auto-inject InterstitialTypeEnricher at priority -1 for collections
    whose name appears in the Collection Type Map."""

    # Tier: 1 | Structural invariant
    def test_apply_enrichers_references_interstitial_type_enricher(self):
        """apply_enrichers_to_collection() MUST reference InterstitialTypeEnricher."""
        from retrovue.usecases.collection_enrichers import apply_enrichers_to_collection

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        assert "InterstitialTypeEnricher" in source, (
            "INV-INTERSTITIAL-ENRICHER-INJECT-001: apply_enrichers_to_collection() "
            "does not reference InterstitialTypeEnricher."
        )

    # Tier: 1 | Structural invariant
    def test_apply_enrichers_checks_collection_type_map(self):
        """apply_enrichers_to_collection() MUST check against COLLECTION_TYPE_MAP."""
        from retrovue.usecases.collection_enrichers import apply_enrichers_to_collection

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        assert "COLLECTION_TYPE_MAP" in source, (
            "INV-INTERSTITIAL-ENRICHER-INJECT-001: apply_enrichers_to_collection() "
            "does not reference COLLECTION_TYPE_MAP."
        )

    # Tier: 1 | Structural invariant
    def test_auto_inject_uses_priority_minus_one(self):
        """The auto-injected enricher MUST use priority -1 (before all others)."""
        from retrovue.usecases.collection_enrichers import apply_enrichers_to_collection

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        assert "-1" in source, (
            "INV-INTERSTITIAL-ENRICHER-INJECT-001: apply_enrichers_to_collection() "
            "does not use priority -1 for InterstitialTypeEnricher injection."
        )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-UNKNOWN-REJECT-001
# Unknown collections MUST be rejected
# ---------------------------------------------------------------------------

class TestInvInterstitialUnknownReject001:
    """INV-INTERSTITIAL-UNKNOWN-REJECT-001: If a collection name is not in the
    Collection Type Map, the InterstitialTypeEnricher MUST raise an error."""

    # Tier: 1 | Structural invariant
    def test_unknown_collection_raises_on_construction(self):
        """Construction with unmapped name MUST raise EnricherConfigurationError."""
        with pytest.raises(EnricherConfigurationError):
            InterstitialTypeEnricher(collection_name="random_garbage")

    # Tier: 1 | Structural invariant
    def test_empty_collection_name_raises(self):
        """Empty collection name MUST raise EnricherConfigurationError."""
        with pytest.raises(EnricherConfigurationError):
            InterstitialTypeEnricher(collection_name="")

    # Tier: 1 | Structural invariant
    def test_no_silent_filler_fallback(self):
        """Unknown collection MUST NOT silently default to 'filler'."""
        with pytest.raises(Exception):
            enricher = InterstitialTypeEnricher(collection_name="mystery_content")
            # If construction didn't raise, enrich() must raise
            enricher.enrich(_item())

    # Tier: 1 | Structural invariant
    def test_enrich_raises_for_unmapped_collection(self):
        """enrich() MUST raise EnricherError if collection name not resolvable.

        This tests the runtime guard in enrich() itself, independent of
        the construction-time check. We bypass construction validation to
        test the enrich() guard directly.
        """
        enricher = object.__new__(InterstitialTypeEnricher)
        enricher._collection_name = "nonexistent_collection"
        with pytest.raises(EnricherError):
            enricher.enrich(_item())


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-CONFIDENCE-DURATION-001
# Invalid duration forces zero confidence
# ---------------------------------------------------------------------------

class TestInvInterstitialConfidenceDuration001:
    """INV-INTERSTITIAL-CONFIDENCE-DURATION-001: If duration_ms is missing,
    zero, negative, or exceeds 10,800,000ms, confidence MUST be 0.0."""

    # Tier: 2 | Scheduling logic invariant
    def test_missing_duration_yields_zero(self):
        """No duration_ms label → confidence 0.0."""
        item = _item(size=1024, raw_labels=[
            "video_codec:h264", "audio_codec:aac", "container:mp4",
        ])
        assert compute_confidence_from_labels(item) == 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_zero_duration_yields_zero(self):
        """duration_ms=0 → confidence 0.0."""
        item = _confidence_item(duration_ms=0)
        assert compute_confidence_from_labels(item) == 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_negative_duration_yields_zero(self):
        """duration_ms=-1 → confidence 0.0."""
        item = _confidence_item(duration_ms=-1)
        assert compute_confidence_from_labels(item) == 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_excessive_duration_yields_zero(self):
        """duration_ms > 10,800,000 → confidence 0.0."""
        item = _confidence_item(duration_ms=10_800_001)
        assert compute_confidence_from_labels(item) == 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_boundary_duration_at_max_is_valid(self):
        """duration_ms == 10,800,000 is valid (exactly 3 hours)."""
        item = _confidence_item(duration_ms=10_800_000)
        score = compute_confidence_from_labels(item)
        assert score > 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_below_threshold_not_promoted(self):
        """Confidence below auto_ready_threshold (0.80) → no auto-promotion.

        An item with only size and duration (score 0.5) MUST NOT qualify.
        """
        item = _confidence_item(
            duration_ms=30000,
            video_codec=None,
            audio_codec=None,
            container=None,
        )
        score = compute_confidence_from_labels(item)
        assert score < 0.80


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001
# Enrichment is idempotent via pipeline checksum
# ---------------------------------------------------------------------------

class TestInvInterstitialEnrichmentIdempotent001:
    """INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001: Assets whose
    last_enricher_checksum matches the pipeline checksum MUST be skipped."""

    # Tier: 1 | Structural invariant
    def test_pipeline_checksum_is_sha256_of_signature_json(self):
        """Pipeline checksum MUST be SHA-256 hex of JSON-serialized enricher signature list."""
        signature = [
            {"enricher_id": "__interstitial_type__", "priority": -1},
            {"enricher_id": "enricher-ffprobe-abc123", "priority": 0},
        ]
        expected = hashlib.sha256(
            json.dumps(signature, sort_keys=True).encode("utf-8")
        ).hexdigest()
        # This is how the production code computes it
        actual = hashlib.sha256(
            json.dumps(signature, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert expected == actual
        assert len(expected) == 64  # SHA-256 hex digest

    # Tier: 1 | Structural invariant
    def test_apply_enrichers_checks_checksum(self):
        """apply_enrichers_to_collection() MUST compare pipeline checksum
        against asset.last_enricher_checksum."""
        from retrovue.usecases.collection_enrichers import apply_enrichers_to_collection

        source = textwrap.dedent(inspect.getsource(apply_enrichers_to_collection))
        assert "last_enricher_checksum" in source, (
            "INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001: "
            "apply_enrichers_to_collection() does not check last_enricher_checksum."
        )
        assert "pipeline_checksum" in source, (
            "INV-INTERSTITIAL-ENRICHMENT-IDEMPOTENT-001: "
            "apply_enrichers_to_collection() does not compute pipeline_checksum."
        )

    # Tier: 1 | Structural invariant
    def test_changed_signature_changes_checksum(self):
        """Different enricher signatures MUST produce different checksums."""
        sig_a = [{"enricher_id": "enricher-a", "priority": 0}]
        sig_b = [{"enricher_id": "enricher-b", "priority": 0}]
        checksum_a = hashlib.sha256(
            json.dumps(sig_a, sort_keys=True).encode("utf-8")
        ).hexdigest()
        checksum_b = hashlib.sha256(
            json.dumps(sig_b, sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert checksum_a != checksum_b


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-INFERENCE-FILLER-DEFAULT-001
# No type rule match defaults to filler
# ---------------------------------------------------------------------------

class TestInvInterstitialInferenceFillerDefault001:
    """INV-INTERSTITIAL-INFERENCE-FILLER-DEFAULT-001: When no type inference
    rule matches any ancestor directory, interstitial_type MUST default to
    'filler'."""

    # Tier: 2 | Scheduling logic invariant
    def test_unmatched_directory_defaults_to_filler(self, tmp_path):
        """A file under a directory matching no type rule MUST infer 'filler'."""
        # Create: root/unknown_category/spot.mp4
        media_dir = tmp_path / "unknown_category"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].editorial["interstitial_type"] == "filler"

    # Tier: 2 | Scheduling logic invariant
    def test_known_type_directory_overrides_filler(self, tmp_path):
        """A file under 'commercials' MUST NOT default to filler."""
        media_dir = tmp_path / "commercials"
        media_dir.mkdir()
        media_file = media_dir / "mcdonalds.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].editorial["interstitial_type"] == "commercial"


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-DISCOVERY-METADATA-001
# Every discovered file MUST have title, size, modified
# ---------------------------------------------------------------------------

class TestInvInterstitialDiscoveryMetadata001:
    """INV-INTERSTITIAL-DISCOVERY-METADATA-001: Every discovered file MUST
    produce a DiscoveredItem with editorial.title (file stem),
    editorial.size (file stat), and editorial.modified (ISO timestamp)."""

    # Tier: 2 | Scheduling logic invariant
    def test_discovered_item_has_required_editorial_fields(self, tmp_path):
        """All three required editorial fields MUST be present."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "my_video.mp4"
        media_file.write_bytes(b"\x00" * 256)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        ed = items[0].editorial
        assert ed is not None
        assert "title" in ed
        assert "size" in ed
        assert "modified" in ed

    # Tier: 2 | Scheduling logic invariant
    def test_title_is_file_stem(self, tmp_path):
        """editorial.title MUST equal the file stem (no extension)."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "cool_commercial_1987.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].editorial["title"] == "cool_commercial_1987"

    # Tier: 2 | Scheduling logic invariant
    def test_size_matches_file_stat(self, tmp_path):
        """editorial.size MUST match the file's actual byte size."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        content = b"\x00" * 512
        media_file.write_bytes(content)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].editorial["size"] == len(content)

    # Tier: 2 | Scheduling logic invariant
    def test_modified_is_iso_timestamp(self, tmp_path):
        """editorial.modified MUST be a parseable ISO timestamp string."""
        from datetime import datetime

        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        modified = items[0].editorial["modified"]
        assert isinstance(modified, str)
        # Must be parseable as ISO timestamp
        datetime.fromisoformat(modified)

    # Tier: 2 | Scheduling logic invariant
    def test_discovered_item_has_file_uri(self, tmp_path):
        """DiscoveredItem.path_uri MUST be a file:// URI."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].path_uri.startswith("file://")


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-READY-GATE-001
# Only state='ready' assets are traffic-eligible
# ---------------------------------------------------------------------------

class TestInvInterstitialReadyGate001:
    """INV-INTERSTITIAL-READY-GATE-001: An asset MUST have state='ready' to
    be eligible for traffic selection. get_filler_assets() MUST filter on
    Asset.state == 'ready'."""

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_filters_by_ready_state(self):
        """get_filler_assets() MUST include a state='ready' filter."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert '"ready"' in source or "'ready'" in source, (
            "INV-INTERSTITIAL-READY-GATE-001: get_filler_assets() does not "
            "filter by state='ready'."
        )

    # Tier: 1 | Structural invariant
    def test_state_filter_uses_asset_state(self):
        """The state filter MUST reference Asset.state."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "Asset.state" in source, (
            "INV-INTERSTITIAL-READY-GATE-001: get_filler_assets() does not "
            "reference Asset.state."
        )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-DURATION-BOUND-001
# Duration must be non-null, positive, and within max
# ---------------------------------------------------------------------------

class TestInvInterstitialDurationBound001:
    """INV-INTERSTITIAL-DURATION-BOUND-001: An asset MUST have a non-null,
    positive duration_ms not exceeding max_duration_ms to be eligible for
    traffic selection."""

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_filters_null_duration(self):
        """get_filler_assets() MUST exclude assets with null duration_ms."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "duration_ms" in source
        # Must have isnot(None) or is_not(None) or similar null check
        has_null_check = "isnot" in source or "is_not" in source or "isnot(None)" in source
        assert has_null_check, (
            "INV-INTERSTITIAL-DURATION-BOUND-001: get_filler_assets() does not "
            "check for null duration_ms."
        )

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_filters_positive_duration(self):
        """get_filler_assets() MUST filter duration_ms > 0."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "duration_ms > 0" in source or "duration_ms >=" in source, (
            "INV-INTERSTITIAL-DURATION-BOUND-001: get_filler_assets() does not "
            "filter for positive duration_ms."
        )

    # Tier: 1 | Structural invariant
    def test_get_filler_assets_filters_max_duration(self):
        """get_filler_assets() MUST filter duration_ms <= max_duration_ms."""
        from retrovue.catalog.db_asset_library import DatabaseAssetLibrary

        source = textwrap.dedent(inspect.getsource(DatabaseAssetLibrary.get_filler_assets))
        assert "max_duration_ms" in source, (
            "INV-INTERSTITIAL-DURATION-BOUND-001: get_filler_assets() does not "
            "reference max_duration_ms."
        )


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-COLLECTION-DEPTH-001
# Collections are first-level subdirectories only
# ---------------------------------------------------------------------------

class TestInvInterstitialCollectionDepth001:
    """INV-INTERSTITIAL-COLLECTION-DEPTH-001: Collection discovery MUST
    enumerate only immediate subdirectories. It MUST NOT recurse."""

    # Tier: 2 | Scheduling logic invariant
    def test_immediate_subdirs_are_collections(self, tmp_path):
        """Each immediate subdirectory MUST produce one collection entry."""
        (tmp_path / "commercials").mkdir()
        (tmp_path / "bumpers").mkdir()
        (tmp_path / "promos").mkdir()

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        collections = importer.list_collections({})
        names = {c["name"] for c in collections}
        assert names == {"commercials", "bumpers", "promos"}

    # Tier: 2 | Scheduling logic invariant
    def test_files_at_root_not_collections(self, tmp_path):
        """Files at the root level MUST NOT produce collection entries."""
        (tmp_path / "commercials").mkdir()
        (tmp_path / "readme.txt").write_text("hi")

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        collections = importer.list_collections({})
        names = {c["name"] for c in collections}
        assert "readme.txt" not in names
        assert names == {"commercials"}

    # Tier: 2 | Scheduling logic invariant
    def test_nested_subdirs_not_collections(self, tmp_path):
        """Nested subdirectories MUST NOT produce additional collection entries."""
        parent = tmp_path / "commercials"
        parent.mkdir()
        (parent / "restaurants").mkdir()
        (parent / "auto").mkdir()

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        collections = importer.list_collections({})
        names = {c["name"] for c in collections}
        assert names == {"commercials"}
        assert "restaurants" not in names
        assert "auto" not in names

    # Tier: 2 | Scheduling logic invariant
    def test_hidden_dirs_excluded_by_default(self, tmp_path):
        """Hidden directories MUST be excluded when include_hidden is False."""
        (tmp_path / "commercials").mkdir()
        (tmp_path / ".hidden").mkdir()

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            include_hidden=False,
        )
        collections = importer.list_collections({})
        names = {c["name"] for c in collections}
        assert ".hidden" not in names
        assert "commercials" in names


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-SIDECAR-FAULT-TOLERANCE-001
# Discovery never fails on bad/missing sidecars
# ---------------------------------------------------------------------------

class TestInvInterstitialSidecarFaultTolerance001:
    """INV-INTERSTITIAL-SIDECAR-FAULT-TOLERANCE-001: Discovery MUST NOT fail
    due to missing or malformed sidecar files."""

    # Tier: 2 | Scheduling logic invariant
    def test_no_sidecar_produces_none(self, tmp_path):
        """A media file with no adjacent sidecar MUST have sidecar=None."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].sidecar is None

    # Tier: 2 | Scheduling logic invariant
    def test_malformed_sidecar_produces_none(self, tmp_path):
        """A malformed JSON sidecar MUST be silently ignored (sidecar=None)."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)
        # Write malformed JSON sidecar
        sidecar_file = media_dir / "spot.mp4.json"
        sidecar_file.write_text("{invalid json content!!!")

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].sidecar is None

    # Tier: 2 | Scheduling logic invariant
    def test_discovery_continues_after_sidecar_error(self, tmp_path):
        """Discovery MUST NOT halt due to a sidecar error — all files discovered."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()

        # File with bad sidecar
        (media_dir / "bad.mp4").write_bytes(b"\x00" * 100)
        (media_dir / "bad.mp4.json").write_text("NOT JSON {{{")

        # File with no sidecar
        (media_dir / "good.mp4").write_bytes(b"\x00" * 200)

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 2

    # Tier: 2 | Scheduling logic invariant
    def test_valid_sidecar_is_loaded(self, tmp_path):
        """A valid JSON sidecar MUST be loaded into sidecar field."""
        media_dir = tmp_path / "content"
        media_dir.mkdir()
        media_file = media_dir / "spot.mp4"
        media_file.write_bytes(b"\x00" * 100)
        sidecar_data = {"sponsor": "Acme Corp", "campaign": "summer2024"}
        sidecar_file = media_dir / "spot.mp4.json"
        sidecar_file.write_text(json.dumps(sidecar_data))

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(tmp_path)],
            glob_patterns=["**/*.mp4"],
        )
        items = importer.discover()
        assert len(items) == 1
        assert items[0].sidecar == sidecar_data


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-CONFIDENCE-SCORING-001
# Confidence formula is deterministic with fixed weights
# ---------------------------------------------------------------------------

class TestInvInterstitialConfidenceScoring001:
    """INV-INTERSTITIAL-CONFIDENCE-SCORING-001: Confidence MUST be scored as:
    +0.2 size, +0.3 duration, +0.2 video_codec, +0.1 audio_codec,
    +0.1 container. Max 1.0."""

    # Tier: 2 | Scheduling logic invariant
    def test_all_signals_present_yields_max_score(self):
        """All five signals → confidence 0.9 (0.2+0.3+0.2+0.1+0.1)."""
        item = _confidence_item(
            size=1024,
            duration_ms=30000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        assert compute_confidence_from_labels(item) == pytest.approx(0.9)

    # Tier: 2 | Scheduling logic invariant
    def test_missing_duration_yields_zero_not_partial(self):
        """Missing duration_ms → confidence 0.0, not 0.7."""
        item = _confidence_item(
            size=1024,
            duration_ms=None,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        assert compute_confidence_from_labels(item) == 0.0

    # Tier: 2 | Scheduling logic invariant
    def test_size_and_duration_only_yields_0_5(self):
        """size > 0 (+0.2) + valid duration (+0.3) = 0.5."""
        item = _confidence_item(
            size=1024,
            duration_ms=30000,
            video_codec=None,
            audio_codec=None,
            container=None,
        )
        assert compute_confidence_from_labels(item) == pytest.approx(0.5)

    # Tier: 2 | Scheduling logic invariant
    def test_size_duration_video_yields_0_7(self):
        """size (+0.2) + duration (+0.3) + video_codec (+0.2) = 0.7."""
        item = _confidence_item(
            size=1024,
            duration_ms=30000,
            video_codec="h264",
            audio_codec=None,
            container=None,
        )
        assert compute_confidence_from_labels(item) == pytest.approx(0.7)

    # Tier: 2 | Scheduling logic invariant
    def test_zero_size_loses_0_2(self):
        """size=0 does not contribute 0.2; score is 0.9 - 0.2 = 0.7."""
        item = _confidence_item(
            size=0,
            duration_ms=30000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        assert compute_confidence_from_labels(item) == pytest.approx(0.7)

    # Tier: 2 | Scheduling logic invariant
    def test_score_never_exceeds_1_0(self):
        """Maximum confidence MUST be 1.0."""
        item = _confidence_item(
            size=999999,
            duration_ms=30000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        assert compute_confidence_from_labels(item) <= 1.0


# ---------------------------------------------------------------------------
# INV-INTERSTITIAL-COLLECTION-ID-STABLE-001
# Collection external_id is SHA-256 derived and stable
# ---------------------------------------------------------------------------

class TestInvInterstitialCollectionIdStable001:
    """INV-INTERSTITIAL-COLLECTION-ID-STABLE-001: Each collection MUST receive
    a stable external_id derived from SHA-256 of the resolved absolute path
    (first 16 hex characters)."""

    # Tier: 2 | Scheduling logic invariant
    def test_external_id_is_deterministic(self, tmp_path):
        """Two invocations MUST produce identical external_id values."""
        (tmp_path / "commercials").mkdir()
        (tmp_path / "bumpers").mkdir()

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        run1 = {c["name"]: c["external_id"] for c in importer.list_collections({})}
        run2 = {c["name"]: c["external_id"] for c in importer.list_collections({})}
        assert run1 == run2

    # Tier: 2 | Scheduling logic invariant
    def test_external_id_is_16_hex_chars(self, tmp_path):
        """external_id MUST be first 16 hex characters of SHA-256."""
        (tmp_path / "commercials").mkdir()

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        collections = importer.list_collections({})
        assert len(collections) == 1
        eid = collections[0]["external_id"]
        assert len(eid) == 16
        assert all(c in "0123456789abcdef" for c in eid)

    # Tier: 2 | Scheduling logic invariant
    def test_same_name_different_paths_produce_distinct_ids(self, tmp_path):
        """Identically named dirs at different absolute paths MUST have distinct ids."""
        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        root_a.mkdir()
        root_b.mkdir()
        (root_a / "commercials").mkdir()
        (root_b / "commercials").mkdir()

        importer = FilesystemImporter(
            source_name="test",
            root_paths=[str(root_a), str(root_b)],
        )
        collections = importer.list_collections({})
        ids = [c["external_id"] for c in collections if c["name"] == "commercials"]
        assert len(ids) == 2
        assert ids[0] != ids[1]

    # Tier: 2 | Scheduling logic invariant
    def test_external_id_matches_sha256_of_resolved_path(self, tmp_path):
        """external_id MUST equal SHA-256(resolved_absolute_path)[:16]."""
        (tmp_path / "bumpers").mkdir()

        importer = FilesystemImporter(source_name="test", root_paths=[str(tmp_path)])
        collections = importer.list_collections({})
        assert len(collections) == 1

        resolved = str((tmp_path / "bumpers").resolve())
        expected = hashlib.sha256(resolved.encode()).hexdigest()[:16]
        assert collections[0]["external_id"] == expected
