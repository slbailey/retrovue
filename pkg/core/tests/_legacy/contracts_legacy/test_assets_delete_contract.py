"""
Contract tests for `retrovue assets delete` and `retrovue assets restore`
(operator-facing behavior, prompts, flags, dry-run, JSON output, and exit codes).

This suite enforces the CLI contract defined in:
docs/contracts/resources/AssetsDeleteContract.md

Any change to CLI syntax, required flags, confirmation rules,
error messages, exit codes, or `--json` / `--dry-run` output
MUST update that contract first. Implementation must then change
to satisfy the updated tests.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")
from typer.testing import CliRunner  # noqa: E402

from retrovue.cli.commands.assets import app  # noqa: E402


class TestAssetsDeleteContract:
    """Contract tests for retrovue assets delete command."""

    def test_delete_asset_by_uuid_soft_delete_with_confirmation(self, db_session):
        """Test soft delete with confirmation flag enforcement."""
        # TODO: Update README.md to specify exact confirmation behavior
        pytest.skip("Confirmation behavior not yet implemented")

    def test_delete_asset_by_id(self, db_session):
        """Test deleting an asset by ID selector."""
        # Create test asset
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--id", str(asset.id), "--yes"
            ])
            
            assert result.exit_code == 0
            assert "soft deleted successfully" in result.output

    def test_delete_asset_partial_match_ambiguity(self, db_session):
        """Test error for non-unique title-based matches."""
        # TODO: Update README.md to specify title-based selector behavior
        pytest.skip("Title-based selectors not yet implemented")

    def test_delete_asset_by_uuid_dry_run(self, db_session):
        """Test dry run mode shows preview without making changes."""
        # Create test asset
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(asset.uuid), "--dry-run"
            ])
            
            assert result.exit_code == 0
            assert "Would soft delete asset" in result.output
            assert "referenced_by_episodes=false" in result.output

    def test_delete_asset_by_uuid_dry_run_json(self, db_session):
        """Test dry run mode with JSON output format."""
        # Create test asset
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(asset.uuid), "--dry-run", "--json"
            ])
            
            assert result.exit_code == 0
            assert '"action": "soft_delete"' in result.output
            assert '"uuid":' in result.output
            assert '"referenced": false' in result.output

    def test_delete_asset_invalid_uuid(self, db_session):
        """Test error handling for invalid UUID format."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", "invalid-uuid", "--yes"
            ])
            
            assert result.exit_code == 1
            assert "Invalid UUID format" in result.output

    def test_delete_asset_nonexistent(self, db_session):
        """Test error handling for non-existent asset UUID."""
        fake_uuid = uuid4()
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(fake_uuid), "--yes"
            ])
            
            assert result.exit_code == 1
            assert "Asset not found" in result.output

    def test_delete_asset_missing_selector(self, db_session):
        """Test error when no asset selector is provided."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--yes"
            ])
            
            assert result.exit_code == 1
            assert "Must specify one selector" in result.output

    def test_delete_asset_multiple_criteria_error(self, db_session):
        """Test error when multiple selectors are provided."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(uuid4()), "--id", "123", "--yes"
            ])
            
            assert result.exit_code == 1
            assert "Can only specify one selector" in result.output

    def test_delete_asset_hard_delete_with_existing_references(self, db_session):
        """Test hard delete blocked by episode references."""
        # Create test asset
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
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
                assert "referenced by episodes" in result.output

    def test_delete_asset_hard_delete_with_force(self, db_session):
        """Test hard delete with force flag bypasses reference checks."""
        # Create test asset
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "delete", "--uuid", str(asset.uuid), "--hard", "--force", "--yes"
            ])
            
            assert result.exit_code == 0
            assert "hard deleted successfully" in result.output

    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/contracts/resources/AssetsDeleteContract.md")
    def test_delete_asset_confirmation_prompt(self, db_session):
        """Test interactive confirmation when --yes is not provided."""
        # TODO: define and enforce exact interactive prompt text/behavior in AssetsDelete.md
        pass

    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/contracts/resources/AssetsDeleteContract.md")
    def test_delete_asset_confirmation_cancelled(self, db_session):
        """Test behavior when user cancels confirmation prompt."""
        # TODO: define and enforce exact interactive prompt text/behavior in AssetsDelete.md
        pass

    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/contracts/resources/AssetsDeleteContract.md")
    def test_delete_asset_mixed_selectors_error(self, db_session):
        """Test error when combining incompatible selectors (e.g., --uuid with --show)."""
        # TODO: define and enforce exact interactive prompt text/behavior in AssetsDelete.md
        pass

    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/contracts/resources/AssetsDeleteContract.md")
    def test_delete_asset_show_bulk_operation(self, db_session):
        """Test deletion of multiple assets for a TV show."""
        # TODO: define and enforce exact bulk operation behavior in AssetsDelete.md
        pass


class TestAssetsRestoreContract:
    """Contract tests for retrovue assets restore command."""

    def test_restore_asset_requires_soft_deleted_state(self, db_session):
        """Test restore only works for soft-deleted assets."""
        # Create test asset that is NOT soft deleted
        from retrovue.domain.entities import Asset
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
            assert "Asset not found or not soft-deleted" in result.output

    def test_restore_asset_partial_match_ambiguity(self, db_session):
        """Test ambiguity error if selector resolves to multiple possible assets."""
        # TODO: Update README.md to specify title-based selector behavior
        pytest.skip("Title-based selectors not yet implemented")

    def test_restore_asset_json_output(self, db_session):
        """Test restore command with JSON output format."""
        # Create test asset that is soft deleted
        from retrovue.domain.entities import Asset
        asset = Asset(
            uri="/test/path.mp4",
            size=1000,
            canonical=False,
            is_deleted=True
        )
        db_session.add(asset)
        db_session.flush()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", str(asset.uuid), "--json"
            ])
            
            assert result.exit_code == 0
            assert '"action": "restore"' in result.output
            assert '"status": "ok"' in result.output

    def test_restore_asset_invalid_uuid(self, db_session):
        """Test error handling for invalid UUID format in restore."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", "invalid-uuid"
            ])
            
            assert result.exit_code == 1
            assert "Invalid UUID format" in result.output

    def test_restore_asset_nonexistent(self, db_session):
        """Test error handling for non-existent asset UUID in restore."""
        fake_uuid = uuid4()
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = runner.invoke(app, [
                "restore", str(fake_uuid)
            ])
            
            assert result.exit_code == 1
            assert "Asset not found or not soft-deleted" in result.output

    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/contracts/resources/AssetsDeleteContract.md")
    def test_restore_asset_show_bulk_operation(self, db_session):
        """Test restoration of multiple soft-deleted assets for a TV show."""
        # TODO: Update README.md to specify bulk restore behavior
        pytest.skip("Bulk restore operations not yet implemented")
