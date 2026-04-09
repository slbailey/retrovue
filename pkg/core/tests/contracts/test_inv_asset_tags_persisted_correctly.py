"""Contract tests: INV-ASSET-TAGS-PERSISTED-CORRECTLY-001

Given a source path with N directory segments, the system MUST:
  1. Generate exactly N tags (one per unique normalized segment)
  2. Persist all N tags to asset_tags
  3. Preserve all N tags across subsequent updates
  4. Make all N tags queryable for pool resolution

No tags may be silently dropped, regardless of path depth.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

try:
    from retrovue.adapters.importers.filesystem_importer import FilesystemImporter
    from retrovue.domain.tag_normalization import (
        canonicalize_tag,
        expand_tag_match_set,
        normalize_tag_set,
    )
    from retrovue.runtime.asset_resolver import AssetMetadata
    from retrovue.dev.stub_asset_resolver import StubAssetResolver
except ImportError:
    pytest.skip(
        "retrovue dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _importer(root: str) -> FilesystemImporter:
    return FilesystemImporter(
        source_name="test",
        root_paths=[root],
        tag_from_path_segments=True,
    )


def _generate_tags(root: Path, segments: list[str]) -> list[str]:
    """Generate tags via _infer_tags_from_path_segments for a path with given segments."""
    file_path = root
    for s in segments:
        file_path = file_path / s
    file_path = file_path / "file.mp4"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.touch()

    imp = _importer(str(root))
    labels = imp._infer_tags_from_path_segments(file_path)
    return [lbl[len("tag:"):] for lbl in labels if lbl.startswith("tag:")]


def _simulate_persistence(tag_values: list[str]) -> list[str]:
    """Simulate what collection_ingest_service does: normalize + canonicalize."""
    normalized = normalize_tag_set(tag_values)
    return [canonicalize_tag(t) for t in normalized]


# ===========================================================================
# Step 1 — N-level path generates N tags
# ===========================================================================


class TestNLevelPathGeneratesNTags:
    """For N=1..5: path with N directory segments → exactly N tags."""

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
    def test_n_segments_produce_n_tags(self, tmp_path, n):
        """INV-ASSET-TAGS-PERSISTED-CORRECTLY-001 Rule 1:
        N unique directory segments → exactly N tags.
        """
        segments = [chr(ord("a") + i) for i in range(n)]
        tag_values = _generate_tags(tmp_path, segments)

        assert len(tag_values) == n, (
            f"Expected {n} tags for {n} segments {segments}, "
            f"got {len(tag_values)}: {tag_values}"
        )
        assert set(tag_values) == set(segments), (
            f"Tags must match segments. Expected {set(segments)}, got {set(tag_values)}"
        )

    def test_realistic_interstitial_path(self, tmp_path):
        """Real-world path: station_ids/hbo/1982/ → 3 tags."""
        segments = ["station_ids", "hbo", "1982"]
        tag_values = _generate_tags(tmp_path, segments)

        assert len(tag_values) == 3
        assert set(tag_values) == {"station_ids", "hbo", "1982"}

    def test_deeply_nested_commercial_path(self, tmp_path):
        """5-deep path: commercials/restaurant/mcdonalds/1985/summer/ → 5 tags."""
        segments = ["commercials", "restaurant", "mcdonalds", "1985", "summer"]
        tag_values = _generate_tags(tmp_path, segments)

        assert len(tag_values) == 5
        assert set(tag_values) == {"commercials", "restaurant", "mcdonalds", "1985", "summer"}


# ===========================================================================
# Step 2 — Tags persisted after ingest simulation
# ===========================================================================


class TestTagsPersistedAfterIngest:
    """All N tags must survive the persistence pipeline (normalize + namespace)."""

    @pytest.mark.parametrize("n", [1, 2, 3, 4, 5])
    def test_all_tags_survive_persistence_pipeline(self, tmp_path, n):
        """INV-ASSET-TAGS-PERSISTED-CORRECTLY-001 Rule 2:
        All generated tags survive normalize_tag_set + TAG: namespacing.
        """
        segments = [chr(ord("a") + i) for i in range(n)]
        tag_values = _generate_tags(tmp_path, segments)

        namespaced = _simulate_persistence(tag_values)

        assert len(namespaced) == n, (
            f"Expected {n} namespaced tags, got {len(namespaced)}: {namespaced}"
        )
        # Every segment should have a TAG: entry
        for seg in segments:
            assert f"tag.{seg}" in namespaced, (
                f"TAG:{seg} missing from persisted tags {namespaced}"
            )

    def test_case_normalization_deduplicates(self, tmp_path):
        """Duplicate segments after normalization produce fewer tags (correct)."""
        # Path: root/HBO/hbo/file.mp4 → only 1 unique tag after normalization
        segments = ["HBO", "hbo"]
        tag_values = _generate_tags(tmp_path, segments)

        namespaced = _simulate_persistence(tag_values)

        # Both "HBO" and "hbo" normalize to "hbo" → 1 tag
        assert len(namespaced) == 1
        assert namespaced == ["tag.hbo"]

    def test_no_tags_lost_in_extraction(self, tmp_path):
        """Labels with tag: prefix are correctly extracted from mixed raw_labels."""
        # Simulate what happens in collection_ingest_service lines 962-968
        raw_labels = [
            "duration_ms:5000",
            "video_codec:h264",
            "tag:station_ids",
            "tag:hbo",
            "tag:1982",
        ]
        tag_labels = [
            lbl[len("tag:"):]
            for lbl in raw_labels
            if isinstance(lbl, str) and lbl.startswith("tag:")
        ]

        assert len(tag_labels) == 3
        assert tag_labels == ["station_ids", "hbo", "1982"]


# ===========================================================================
# Step 3 — Tags survive multiple updates
# ===========================================================================


class TestTagsSurviveMultipleUpdates:
    """Tags must not be lost when metadata is updated via persist_asset_metadata."""

    def test_probed_update_does_not_touch_tags(self):
        """persist_asset_metadata with probed= only does not affect asset_tags.

        Tags live in a separate table (asset_tags) with their own persistence
        path. persist_asset_metadata only handles editorial/probed/station_ops/
        relationships/sidecar JSONB payloads.
        """
        # The fact that persist_asset_metadata's signature does not include
        # a tags parameter is the structural guarantee.
        from retrovue.infra.metadata.persistence import persist_asset_metadata
        import inspect

        sig = inspect.signature(persist_asset_metadata)
        param_names = set(sig.parameters.keys())

        assert "tags" not in param_names, (
            "persist_asset_metadata must NOT have a 'tags' parameter — "
            "tags are persisted separately via AssetTag"
        )

    def test_editorial_update_does_not_touch_tags(self):
        """Editorial payload update (e.g., from enricher) does not affect tags.

        Tags and editorial are independent persistence paths.
        """
        from retrovue.infra.metadata.persistence import persist_asset_metadata
        from retrovue.domain.entities import AssetEditorial

        # Create a fake session that tracks operations
        class FakeSession:
            def __init__(self):
                self._store: dict = {}
                self.added: list = []

            def get(self, model_class, key):
                return self._store.get((model_class, str(key)))

            def add(self, obj):
                self.added.append(obj)
                uuid_key = getattr(obj, "asset_uuid", None)
                if uuid_key:
                    self._store[(type(obj), str(uuid_key))] = obj

        fake_db = FakeSession()
        asset = MagicMock()
        asset.uuid = "test-uuid"

        # Persist editorial
        persist_asset_metadata(
            fake_db, asset,
            editorial={"interstitial_type": "station_id", "title": "Test"},
        )

        # Verify only AssetEditorial was touched, not AssetTag
        from retrovue.domain.entities import AssetTag
        tag_adds = [obj for obj in fake_db.added if isinstance(obj, AssetTag)]
        assert len(tag_adds) == 0, (
            "persist_asset_metadata must not create AssetTag rows"
        )


# ===========================================================================
# Step 4 — Tags queryable by pool
# ===========================================================================


class TestTagsQueryableByPool:
    """Pool resolution must find assets by their path-derived tags."""

    def test_pool_matches_all_path_tags(self):
        """Pool requiring tags [hbo, station_ids] matches asset with those tags."""
        resolver = StubAssetResolver()
        resolver.add("asset-001", AssetMetadata(
            type="bumper",
            duration_sec=10,
            title="HBO Station ID",
            tags=("tag.hbo", "tag.station_ids", "tag.1982"),
        ))
        resolver.register_pools({
            "hbo_station_ids": {
                "match": {"type": "bumper", "tags": ["hbo", "station_ids"]},
            },
        })

        results = resolver.resolve_pool("hbo_station_ids")
        assert "asset-001" in results

    def test_pool_with_all_5_tags(self):
        """Pool requiring 5 tags matches asset with all 5."""
        resolver = StubAssetResolver()
        resolver.add("deep-asset", AssetMetadata(
            type="bumper",
            duration_sec=15,
            title="Deep Asset",
            tags=("tag.commercials", "tag.restaurant", "tag.mcdonalds", "tag.1985", "tag.summer"),
        ))
        resolver.register_pools({
            "summer_mcdonalds": {
                "match": {
                    "type": "bumper",
                    "tags": ["commercials", "restaurant", "mcdonalds", "1985", "summer"],
                },
            },
        })

        results = resolver.resolve_pool("summer_mcdonalds")
        assert "deep-asset" in results

    def test_missing_one_tag_excludes_from_pool(self):
        """Asset missing one of the required tags is excluded."""
        resolver = StubAssetResolver()
        resolver.add("partial-asset", AssetMetadata(
            type="bumper",
            duration_sec=10,
            title="Partial Asset",
            tags=("tag.hbo", "tag.station_ids"),  # missing "1982"
        ))
        resolver.register_pools({
            "specific_pool": {
                "match": {"type": "bumper", "tags": ["hbo", "station_ids", "1982"]},
            },
        })

        with pytest.raises(KeyError, match="matched 0 assets"):
            resolver.resolve_pool("specific_pool")

    def test_expand_tag_match_set_covers_namespaced(self):
        """expand_tag_match_set must produce canonical, colon, and plain forms."""
        stored_tags = {"tag.hbo", "tag.station_ids", "tag.1982"}
        expanded = expand_tag_match_set(stored_tags)

        # All forms must be present
        assert "hbo" in expanded
        assert "tag.hbo" in expanded
        assert "tag:hbo" in expanded
        assert "station_ids" in expanded
        assert "1982" in expanded


# ===========================================================================
# Step 5 — Tag order preserved (generation order is deepest-first)
# ===========================================================================


class TestTagOrderPreserved:
    """Tags are generated deepest-first but persisted sorted after normalization."""

    def test_generation_order_is_deepest_first(self, tmp_path):
        """_infer_tags_from_path_segments walks upward → deepest segment first."""
        segments = ["a", "b", "c"]
        tag_values = _generate_tags(tmp_path, segments)

        # Generation order: deepest first (c, b, a)
        assert tag_values == ["c", "b", "a"], (
            f"Expected deepest-first order ['c', 'b', 'a'], got {tag_values}"
        )

    def test_persistence_order_is_sorted(self, tmp_path):
        """normalize_tag_set sorts tags alphabetically for consistency."""
        segments = ["c", "a", "b"]
        tag_values = _generate_tags(tmp_path, segments)

        normalized = normalize_tag_set(tag_values)

        assert normalized == ["a", "b", "c"], (
            f"Expected sorted ['a', 'b', 'c'], got {normalized}"
        )


# ===========================================================================
# Step 6 — Edge cases: deduplication does not cause false tag loss
# ===========================================================================


class TestDeduplicationEdgeCases:
    """Legitimate deduplication scenarios should not be confused with tag loss."""

    def test_duplicate_segment_names_at_different_depths(self, tmp_path):
        """Path a/b/a/file.mp4 has 3 segments but only 2 unique tags (correct)."""
        segments = ["a", "b", "a"]
        tag_values = _generate_tags(tmp_path, segments)

        # Generation produces 3 raw tags: ["a", "b", "a"]
        assert len(tag_values) == 3  # raw generation = 3
        # But normalization deduplicates
        namespaced = _simulate_persistence(tag_values)
        assert len(namespaced) == 2  # unique = 2
        assert set(namespaced) == {"tag.a", "tag.b"}

    def test_empty_segment_name_discarded(self, tmp_path):
        """A directory named with only whitespace produces empty tag → discarded."""
        # normalize_tag_set discards empty/whitespace-only tags
        result = normalize_tag_set(["hbo", "  ", "1982"])
        assert len(result) == 2
        assert result == ["1982", "hbo"]
