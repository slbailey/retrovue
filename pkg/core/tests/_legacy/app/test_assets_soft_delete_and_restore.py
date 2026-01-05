"""
Tests for asset soft delete and restore functionality.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the soft delete and restore operations for assets,
ensuring that soft-deleted assets are excluded from queries by default
and can be restored properly.
"""

from datetime import datetime
from uuid import uuid4

from retrovue.content_manager.library_service import LibraryService
from retrovue.domain.entities import Asset


class TestAssetSoftDeleteAndRestore:
    """Test asset soft delete and restore operations."""

    def test_soft_delete_asset_by_uuid(self, db_session):
        """Test soft deleting an asset by UUID."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Verify asset is not deleted initially
        assert not asset.is_deleted
        assert asset.deleted_at is None
        
        # Soft delete the asset
        result = library_service.soft_delete_asset_by_uuid(asset.uuid)
        assert result is True
        
        # Verify asset is marked as deleted
        db_session.refresh(asset)
        assert asset.is_deleted is True
        assert asset.deleted_at is not None

    def test_soft_delete_asset_by_id(self, db_session):
        """Test soft deleting an asset by ID."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Soft delete the asset
        result = library_service.soft_delete_asset_by_id(asset.id)
        assert result is True
        
        # Verify asset is marked as deleted
        db_session.refresh(asset)
        assert asset.is_deleted is True
        assert asset.deleted_at is not None

    def test_soft_delete_nonexistent_asset(self, db_session):
        """Test soft deleting a non-existent asset."""
        library_service = LibraryService(db_session)
        fake_uuid = uuid4()
        
        result = library_service.soft_delete_asset_by_uuid(fake_uuid)
        assert result is False

    def test_soft_delete_already_deleted_asset(self, db_session):
        """Test soft deleting an already soft-deleted asset."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Soft delete the asset again (should be idempotent)
        result = library_service.soft_delete_asset_by_uuid(asset.uuid)
        assert result is True

    def test_restore_asset_by_uuid(self, db_session):
        """Test restoring a soft-deleted asset."""
        # Create test asset that is soft deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Restore the asset
        result = library_service.restore_asset_by_uuid(asset.uuid)
        assert result is True
        
        # Verify asset is restored
        db_session.refresh(asset)
        assert asset.is_deleted is False
        assert asset.deleted_at is None

    def test_restore_nonexistent_asset(self, db_session):
        """Test restoring a non-existent asset."""
        library_service = LibraryService(db_session)
        fake_uuid = uuid4()
        
        result = library_service.restore_asset_by_uuid(fake_uuid)
        assert result is False

    def test_restore_not_deleted_asset(self, db_session):
        """Test restoring an asset that is not soft deleted."""
        # Create test asset that is not deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=False
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Try to restore the asset
        result = library_service.restore_asset_by_uuid(asset.uuid)
        assert result is False

    def test_list_assets_excludes_soft_deleted(self, db_session):
        """Test that list_assets excludes soft-deleted assets by default."""
        # Create test assets
        active_asset = Asset(
            uri="/test/active.mp4",
            size=1000,
            canonical=False,
            is_deleted=False
        )
        deleted_asset = Asset(
            uri="/test/deleted.mp4",
            size=2000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add_all([active_asset, deleted_asset])
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # List assets (should exclude soft-deleted by default)
        assets = library_service.list_assets()
        assert len(assets) == 1
        assert assets[0].id == active_asset.id

    def test_list_assets_includes_deleted_when_requested(self, db_session):
        """Test that list_assets includes soft-deleted assets when requested."""
        # Create test assets
        active_asset = Asset(
            uri="/test/active.mp4",
            size=1000,
            canonical=False,
            is_deleted=False
        )
        deleted_asset = Asset(
            uri="/test/deleted.mp4",
            size=2000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add_all([active_asset, deleted_asset])
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # List assets including deleted
        assets = library_service.list_assets(include_deleted=True)
        assert len(assets) == 2
        asset_ids = {asset.id for asset in assets}
        assert active_asset.id in asset_ids
        assert deleted_asset.id in asset_ids

    def test_get_asset_by_id_excludes_soft_deleted(self, db_session):
        """Test that get_asset_by_id excludes soft-deleted assets by default."""
        # Create test asset that is soft deleted
        asset = Asset(
            uri="/test/deleted.mp4",
            size=1000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Get asset (should return None for soft-deleted by default)
        result = library_service.get_asset_by_id(asset.id)
        assert result is None

    def test_get_asset_by_id_includes_deleted_when_requested(self, db_session):
        """Test that get_asset_by_id includes soft-deleted assets when requested."""
        # Create test asset that is soft deleted
        asset = Asset(
            uri="/test/deleted.mp4",
            size=1000,
            canonical=False,
            is_deleted=True,
            deleted_at=datetime.utcnow()
        )
        db_session.add(asset)
        db_session.flush()
        
        library_service = LibraryService(db_session)
        
        # Get asset including deleted
        result = library_service.get_asset_by_id(asset.id, include_deleted=True)
        assert result is not None
        assert result.id == asset.id
        assert result.is_deleted is True
