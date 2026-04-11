"""
Tests for asset hard delete guards and reference checking.

This module tests the hard delete functionality with proper guards
to prevent deletion of assets that are referenced by episodes.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")

from uuid import uuid4  # noqa: E402

from retrovue.content_manager.library_service import LibraryService  # noqa: E402
from retrovue.domain.entities import Asset, Episode, EpisodeAsset, Season, Title  # noqa: E402


class TestAssetHardDeleteGuards:
    """Test asset hard delete guards and reference checking."""

    def test_hard_delete_asset_without_references(self, db_session):
        """Test hard deleting an asset that has no references."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Hard delete the asset
        result = library_service.hard_delete_asset_by_uuid(asset.uuid, force=False)
        assert result is True
        
        # Verify asset is deleted from database
        deleted_asset = db_session.get(Asset, asset.id)
        assert deleted_asset is None

    def test_hard_delete_asset_with_episode_references_refused(self, db_session):
        """Test that hard delete is refused when asset is referenced by episodes."""
        # Create test entities
        title = Title(kind="SHOW", name="Test Show")
        season = Season(title_id=title.id, number=1)
        episode = Episode(
            title_id=title.id,
            season_id=season.id,
            number=1,
            name="Test Episode"
        )
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=asset.id)
        
        db_session.add_all([title, season, episode, asset, episode_asset])
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Try to hard delete the asset (should be refused)
        with pytest.raises(ValueError, match="is referenced by episodes"):
            library_service.hard_delete_asset_by_uuid(asset.uuid, force=False)

    def test_hard_delete_asset_with_episode_references_forced(self, db_session):
        """Test that hard delete succeeds when forced even with references."""
        # Create test entities
        title = Title(kind="SHOW", name="Test Show")
        season = Season(title_id=title.id, number=1)
        episode = Episode(
            title_id=title.id,
            season_id=season.id,
            number=1,
            name="Test Episode"
        )
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=asset.id)
        
        db_session.add_all([title, season, episode, asset, episode_asset])
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Hard delete the asset with force=True
        result = library_service.hard_delete_asset_by_uuid(asset.uuid, force=True)
        assert result is True
        
        # Verify asset is deleted from database
        deleted_asset = db_session.get(Asset, asset.id)
        assert deleted_asset is None

    def test_hard_delete_nonexistent_asset(self, db_session):
        """Test hard deleting a non-existent asset."""
        library_service = LibraryService(db_session)
        fake_uuid = uuid4()
        
        result = library_service.hard_delete_asset_by_uuid(fake_uuid, force=False)
        assert result is False

    def test_is_asset_referenced_by_episodes_true(self, db_session):
        """Test checking if an asset is referenced by episodes (true case)."""
        # Create test entities
        title = Title(kind="SHOW", name="Test Show")
        season = Season(title_id=title.id, number=1)
        episode = Episode(
            title_id=title.id,
            season_id=season.id,
            number=1,
            name="Test Episode"
        )
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=asset.id)
        
        db_session.add_all([title, season, episode, asset, episode_asset])
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Check if asset is referenced
        result = library_service.is_asset_referenced_by_episodes(asset.id)
        assert result is True

    def test_is_asset_referenced_by_episodes_false(self, db_session):
        """Test checking if an asset is referenced by episodes (false case)."""
        # Create test asset without references
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Check if asset is referenced
        result = library_service.is_asset_referenced_by_episodes(asset.id)
        assert result is False

    def test_hard_delete_cascade_behavior(self, db_session):
        """Test that hard delete properly handles cascade behavior."""
        # Create test entities
        title = Title(kind="SHOW", name="Test Show")
        season = Season(title_id=title.id, number=1)
        episode = Episode(
            title_id=title.id,
            season_id=season.id,
            number=1,
            name="Test Episode"
        )
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        episode_asset = EpisodeAsset(episode_id=episode.id, asset_id=asset.id)
        
        db_session.add_all([title, season, episode, asset, episode_asset])
        db_session.flush()
        
        # Store IDs for verification
        episode_asset_id = episode_asset.episode_id
        asset_id = asset.id
        
        library_service = LibraryService(db_session)
        
        # Hard delete the asset with force=True
        result = library_service.hard_delete_asset_by_uuid(asset.uuid, force=True)
        assert result is True
        
        # Verify asset is deleted
        deleted_asset = db_session.get(Asset, asset_id)
        assert deleted_asset is None
        
        # Verify episode_asset relationship is also deleted (CASCADE)
        deleted_episode_asset = db_session.query(EpisodeAsset).filter(
            EpisodeAsset.episode_id == episode_asset_id,
            EpisodeAsset.asset_id == asset_id
        ).first()
        assert deleted_episode_asset is None
