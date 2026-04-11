"""
Data contract tests for `retrovue assets delete` / `retrovue assets restore`.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This suite enforces the persistence guarantees in:
docs/contracts/resources/AssetsDeleteContract.md

These tests MUST use a real test database fixture (e.g. `db_session`)
and MUST assert on actual persisted state after running the CLI.

Rules enforced here include:
- soft delete sets is_deleted = True and is reversible
- hard delete actually removes the Asset
- restore flips is_deleted back to False
- operations return the correct exit code
"""

from unittest.mock import patch
from uuid import uuid4

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app
from retrovue.domain.entities import Asset


class TestAssetsDeleteDataContract:
    """Data contract tests for retrovue assets delete command."""

    def test_delete_asset_by_uuid_soft_delete(self, db_session):
        """Test soft delete sets is_deleted = True in database."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        original_id = asset.id
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(asset.uuid), "--yes"
            ])
            
            assert result.exit_code == 0
            
            # Refresh asset from database and check persistence
            db_session.refresh(asset)
            assert asset.is_deleted is True
            assert asset.id == original_id  # Asset still exists

    def test_delete_asset_by_id(self, db_session):
        """Test deleting an asset by ID sets is_deleted = True."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        original_id = asset.id
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--id", str(asset.id), "--yes"
            ])
            
            assert result.exit_code == 0
            
            # Refresh asset from database and check persistence
            db_session.refresh(asset)
            assert asset.is_deleted is True
            assert asset.id == original_id  # Asset still exists

    def test_delete_asset_hard_delete_with_existing_references(self, db_session):
        """Test hard delete refuses when asset is referenced by episodes."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        original_id = asset.id
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Mock the reference check to return True
            with patch('retrovue.content_manager.library_service.LibraryService.is_asset_referenced_by_episodes') as mock_ref:
                mock_ref.return_value = True
                
                result = runner.invoke(app, [
                    "delete", "--uuid", str(asset.uuid), "--hard"
                ])
                
                assert result.exit_code == 1
                
                # Refresh asset from database - should still exist and not be deleted
                db_session.refresh(asset)
                assert asset.is_deleted is False
                assert asset.id == original_id

    def test_delete_asset_hard_delete_with_force(self, db_session):
        """Test hard delete with force flag actually removes asset from database."""
        # Create test asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        asset_id = asset.id
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(asset.uuid), "--hard", "--force", "--yes"
            ])
            
            assert result.exit_code == 0
            
            # Check that asset is actually removed from database
            deleted_asset = db_session.get(Asset, asset_id)
            assert deleted_asset is None

    def test_delete_asset_nonexistent(self, db_session):
        """Test deleting non-existent asset returns error exit code."""
        fake_uuid = uuid4()
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(fake_uuid), "--yes"
            ])
            
            assert result.exit_code == 1

    def test_delete_asset_invalid_uuid(self, db_session):
        """Test deleting asset with invalid UUID returns error exit code."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", "invalid-uuid", "--yes"
            ])
            
            assert result.exit_code == 1


class TestAssetsRestoreDataContract:
    """Data contract tests for retrovue assets restore command."""

    def test_restore_asset_success(self, db_session):
        """Test restore sets is_deleted = False in database."""
        # Create test asset that is soft deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True
        )
        db_session.add(asset)
        db_session.flush()
        original_id = asset.id
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", str(asset.uuid)
            ])
            
            assert result.exit_code == 0
            
            # Refresh asset from database and check persistence
            db_session.refresh(asset)
            assert asset.is_deleted is False
            assert asset.id == original_id  # Asset still exists

    def test_restore_asset_nonexistent(self, db_session):
        """Test restoring non-existent asset returns error exit code."""
        fake_uuid = uuid4()
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", str(fake_uuid)
            ])
            
            assert result.exit_code == 1

    def test_restore_asset_invalid_uuid(self, db_session):
        """Test restoring asset with invalid UUID returns error exit code."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", "invalid-uuid"
            ])
            
            assert result.exit_code == 1

    def test_restore_asset_requires_soft_deleted_state(self, db_session):
        """Test restoring asset that is not soft-deleted returns error."""
        # Create test asset that is NOT soft deleted
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=False
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", str(asset.uuid)
            ])
            
            assert result.exit_code == 1
            
            # Refresh asset from database - should remain unchanged
            db_session.refresh(asset)
            assert asset.is_deleted is False
