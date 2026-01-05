"""
Tests for the library service.

This module tests all the business operations in the library service.
"""

import uuid

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")

from retrovue.content_manager.library_service import LibraryService  # noqa: E402
from retrovue.domain.entities import Episode  # noqa: E402
from retrovue.shared.types import ReviewStatus  # noqa: E402


class TestLibraryService:
    """Test cases for LibraryService."""

    def test_register_and_canonicalize_asset(
        self, library_service: LibraryService, sample_discovered_data: dict
    ):
        """Test asset registration and canonicalization."""
        # Register asset
        asset = library_service.register_asset_from_discovery(sample_discovered_data)

        assert asset is not None
        assert asset.uri == sample_discovered_data["path_uri"]
        assert asset.size == sample_discovered_data["size"]
        assert asset.hash_sha256 == sample_discovered_data["hash_sha256"]
        assert asset.canonical is False

        # Mark as canonical
        canonical_asset = library_service.mark_asset_canonical(asset.id)

        assert canonical_asset.canonical is True
        assert canonical_asset.id == asset.id

    def test_enrich_asset(
        self,
        library_service: LibraryService,
        sample_discovered_data: dict,
        sample_enrichment_data: dict,
    ):
        """Test asset enrichment."""
        # Register asset first
        asset = library_service.register_asset_from_discovery(sample_discovered_data)

        # Enrich asset
        enriched_asset = library_service.enrich_asset(asset.id, sample_enrichment_data)

        assert enriched_asset.duration_ms == sample_enrichment_data["duration_ms"]
        assert enriched_asset.video_codec == sample_enrichment_data["video_codec"]
        assert enriched_asset.audio_codec == sample_enrichment_data["audio_codec"]
        assert enriched_asset.container == sample_enrichment_data["container"]

    def test_link_asset_to_episode(
        self,
        library_service: LibraryService,
        sample_discovered_data: dict,
        temp_db_session,
    ):
        """Test linking asset to episode."""
        # Register asset
        asset = library_service.register_asset_from_discovery(sample_discovered_data)

        # Create a test episode
        from retrovue.domain.entities import Season, Title
        from retrovue.shared.types import TitleKind

        title = Title(kind=TitleKind.SHOW, name="Test Show", year=2025)
        temp_db_session.add(title)
        temp_db_session.flush()

        season = Season(title_id=title.id, number=1)
        temp_db_session.add(season)
        temp_db_session.flush()

        episode = Episode(title_id=title.id, season_id=season.id, number=1, name="Test Episode")
        temp_db_session.add(episode)
        temp_db_session.flush()

        # Link asset to episode
        episode_asset = library_service.link_asset_to_episode(asset.id, episode.id)

        assert episode_asset.asset_id == asset.id
        assert episode_asset.episode_id == episode.id

    def test_enqueue_review_and_list_assets(
        self, library_service: LibraryService, sample_discovered_data: dict
    ):
        """Test review queue and asset listing."""
        # Register asset
        asset = library_service.register_asset_from_discovery(sample_discovered_data)

        # Enqueue for review
        review = library_service.enqueue_review(asset.id, "Test review reason", 0.8)

        assert review.asset_id == asset.id
        assert review.reason == "Test review reason"
        assert review.confidence == 0.8
        assert review.status == ReviewStatus.PENDING

        # Test asset listing
        all_assets = library_service.list_assets()
        assert len(all_assets) == 1
        assert all_assets[0].id == asset.id

        # Test pending assets
        pending_assets = library_service.list_assets(status="pending")
        assert len(pending_assets) == 1
        assert pending_assets[0].id == asset.id

        # Mark as canonical and test canonical assets
        library_service.mark_asset_canonical(asset.id)
        canonical_assets = library_service.list_assets(status="canonical")
        assert len(canonical_assets) == 1
        assert canonical_assets[0].id == asset.id

    def test_register_asset_validation(self, library_service: LibraryService):
        """Test asset registration with invalid data."""
        # Test missing required fields
        with pytest.raises(KeyError):
            library_service.register_asset_from_discovery({})

        # Test with minimal valid data
        minimal_data = {"path_uri": "file:///test.mkv", "size": 1024}
        asset = library_service.register_asset_from_discovery(minimal_data)
        assert asset.uri == minimal_data["path_uri"]
        assert asset.size == minimal_data["size"]

    def test_enrich_asset_validation(self, library_service: LibraryService, temp_db_session):
        """Test asset enrichment validation."""
        # Register an asset first
        asset = library_service.register_asset_from_discovery(
            {"path_uri": "file:///test.mkv", "size": 1024}
        )
        temp_db_session.flush()  # Ensure the asset is persisted

        # Test enriching non-existent asset
        with pytest.raises(ValueError):
            library_service.enrich_asset(uuid.uuid4(), {"duration_ms": 1000})

        # Test enriching existing asset
        enrichment = {"duration_ms": 1000}
        enriched = library_service.enrich_asset(asset.id, enrichment)
        assert enriched.duration_ms == 1000

    def test_link_asset_validation(self, library_service: LibraryService):
        """Test asset linking validation."""
        # Register an asset
        asset = library_service.register_asset_from_discovery(
            {"path_uri": "file:///test.mkv", "size": 1024}
        )

        # Test linking to non-existent episode
        with pytest.raises(ValueError):
            library_service.link_asset_to_episode(asset.id, uuid.uuid4())

        # Test linking non-existent asset
        with pytest.raises(ValueError):
            library_service.link_asset_to_episode(uuid.uuid4(), uuid.uuid4())

    def test_review_queue_validation(self, library_service: LibraryService, temp_db_session):
        """Test review queue validation."""
        # Register an asset
        asset = library_service.register_asset_from_discovery(
            {"path_uri": "file:///test.mkv", "size": 1024}
        )
        temp_db_session.flush()  # Ensure the asset is persisted

        # Test invalid confidence scores
        with pytest.raises(ValueError):
            library_service.enqueue_review(asset.id, "reason", -0.1)

        with pytest.raises(ValueError):
            library_service.enqueue_review(asset.id, "reason", 1.1)

        # Test valid confidence scores
        review1 = library_service.enqueue_review(asset.id, "reason", 0.0)
        assert review1.confidence == 0.0

        review2 = library_service.enqueue_review(asset.id, "reason", 1.0)
        assert review2.confidence == 1.0

        # Test non-existent asset
        with pytest.raises(ValueError):
            library_service.enqueue_review(uuid.uuid4(), "reason", 0.5)

    def test_context_manager(self, temp_db_session):
        """Test service context manager."""
        with LibraryService() as service:
            asset = service.register_asset_from_discovery(
                {"path_uri": "file:///test.mkv", "size": 1024}
            )
            assert asset is not None

    def test_multiple_assets(self, library_service: LibraryService):
        """Test handling multiple assets."""
        # Register multiple assets
        assets = []
        for i in range(3):
            asset = library_service.register_asset_from_discovery(
                {"path_uri": f"file:///test{i}.mkv", "size": 1024 * (i + 1)}
            )
            assets.append(asset)

        # List all assets
        all_assets = library_service.list_assets()
        assert len(all_assets) == 3

        # Mark one as canonical
        library_service.mark_asset_canonical(assets[0].id)

        # Test filtering
        canonical_assets = library_service.list_assets(status="canonical")
        assert len(canonical_assets) == 1
        assert canonical_assets[0].id == assets[0].id

        pending_assets = library_service.list_assets(status="pending")
        assert len(pending_assets) == 2
