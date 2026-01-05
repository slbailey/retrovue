"""
Tests for CLI assets series deprecation alias functionality.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests that the assets series command with a series name
prints a deprecation warning and delegates to assets select.
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app
from retrovue.domain.entities import Asset, Provider, ProviderRef
from retrovue.shared.types import EntityType as EntityTypeEnum


class TestCLIAssetsSeriesDeprecationAlias:
    """Test CLI assets series deprecation alias functionality."""

    def test_series_deprecation_warning_with_series(self, temp_db_session):
        """Test that assets series with a series name prints deprecation warning."""
        runner = CliRunner()
        
        # Create test data
        asset = Asset(
            id=1,
            uri="file:///test/episode1.mp4",
            size=1000000,
            canonical=True
        )
        temp_db_session.add(asset)
        temp_db_session.flush()
        
        provider_ref = ProviderRef(
            entity_type=EntityTypeEnum.ASSET,
            entity_id=asset.uuid,
            asset_id=asset.id,
            provider=Provider.PLEX,
            provider_key="12345",
            raw={
                "title": "The Pilot",
                "grandparentTitle": "Test Series",
                "parentIndex": 1,
                "index": 1,
                "kind": "episode"
            }
        )
        temp_db_session.add(provider_ref)
        temp_db_session.commit()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = [asset]
                
                result = runner.invoke(app, [
                    "series", "Test Series", "--json"
                ])
                
                if result.exit_code != 0:
                    print(f"Exit code: {result.exit_code}")
                    print(f"Output: {result.output}")
                    print(f"Stderr: {result.stderr}")
                    print(f"Exception: {result.exception}")
                
                assert result.exit_code == 0
                
                # Check that deprecation warning is printed to stderr
                assert "DEPRECATION: 'assets series <name>' is deprecated" in result.stderr
                assert "Use 'assets select <name>' to choose an episode" in result.stderr
                
                # Parse JSON output - should match assets select format
                print(f"Output to parse: {result.output}")
                
                # Extract JSON from output (skip deprecation warning)
                output_lines = result.output.strip().split('\n')
                json_start = -1
                for i, line in enumerate(output_lines):
                    if line.strip().startswith('{'):
                        json_start = i
                        break
                
                if json_start == -1:
                    raise ValueError("No JSON found in output")
                
                json_output = '\n'.join(output_lines[json_start:])
                output_data = json.loads(json_output)
                
                # Verify structure matches assets select
                assert "uuid" in output_data
                assert "id" in output_data
                assert "title" in output_data
                assert "series_title" in output_data
                assert "season_number" in output_data
                assert "episode_number" in output_data
                assert "kind" in output_data
                assert "selection" in output_data
                
                # Verify values
                assert output_data["title"] == "The Pilot"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "random"  # Default mode
                assert output_data["selection"]["criteria"]["series"] == "Test Series"

    def test_series_deprecation_warning_with_series_flag(self, temp_db_session):
        """Test that assets series with --series flag prints deprecation warning."""
        runner = CliRunner()
        
        # Create test data
        asset = Asset(
            id=1,
            uri="file:///test/episode1.mp4",
            size=1000000,
            canonical=True
        )
        temp_db_session.add(asset)
        temp_db_session.flush()
        
        provider_ref = ProviderRef(
            entity_type=EntityTypeEnum.ASSET,
            entity_id=asset.uuid,
            asset_id=asset.id,
            provider=Provider.PLEX,
            provider_key="12345",
            raw={
                "title": "The Pilot",
                "grandparentTitle": "Test Series",
                "parentIndex": 1,
                "index": 1,
                "kind": "episode"
            }
        )
        temp_db_session.add(provider_ref)
        temp_db_session.commit()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = [asset]
                
                result = runner.invoke(app, [
                    "series", "--series", "Test Series", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Check that deprecation warning is printed to stderr
                assert "DEPRECATION: 'assets series <name>' is deprecated" in result.stderr
                assert "Use 'assets select <name>' to choose an episode" in result.stderr
                
                # Parse JSON output - should match assets select format
                # Extract JSON from output (skip deprecation warning)
                output_lines = result.output.strip().split('\n')
                json_start = -1
                for i, line in enumerate(output_lines):
                    if line.strip().startswith('{'):
                        json_start = i
                        break
                
                if json_start == -1:
                    raise ValueError("No JSON found in output")
                
                json_output = '\n'.join(output_lines[json_start:])
                output_data = json.loads(json_output)
                
                # Verify structure matches assets select
                assert "uuid" in output_data
                assert "id" in output_data
                assert "title" in output_data
                assert "series_title" in output_data
                assert "season_number" in output_data
                assert "episode_number" in output_data
                assert "kind" in output_data
                assert "selection" in output_data
                
                # Verify values
                assert output_data["title"] == "The Pilot"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "random"  # Default mode
                assert output_data["selection"]["criteria"]["series"] == "Test Series"

    def test_series_no_deprecation_warning_without_series(self, temp_db_session):
        """Test that assets series without a series name does not print deprecation warning."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return series list
            with patch('retrovue.content_manager.library_service.LibraryService.list_series') as mock_list_series:
                mock_list_series.return_value = ["Series A", "Series B"]
                
                result = runner.invoke(app, [
                    "series", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Check that NO deprecation warning is printed
                assert "DEPRECATION" not in result.stderr
                assert "deprecated" not in result.stderr
                
                # Parse JSON output - should be the old format
                output_data = json.loads(result.output)
                
                # Verify structure matches old series list format
                assert "series" in output_data
                assert isinstance(output_data["series"], list)
                assert output_data["series"] == ["Series A", "Series B"]

    def test_series_deprecation_human_output(self, temp_db_session):
        """Test that assets series with series name works in human output mode."""
        runner = CliRunner()
        
        # Create test data
        asset = Asset(
            id=1,
            uri="file:///test/episode1.mp4",
            size=1000000,
            canonical=True
        )
        temp_db_session.add(asset)
        temp_db_session.flush()
        
        provider_ref = ProviderRef(
            entity_type=EntityTypeEnum.ASSET,
            entity_id=asset.uuid,
            asset_id=asset.id,
            provider=Provider.PLEX,
            provider_key="12345",
            raw={
                "title": "The Pilot",
                "grandparentTitle": "Test Series",
                "parentIndex": 1,
                "index": 1,
                "kind": "episode"
            }
        )
        temp_db_session.add(provider_ref)
        temp_db_session.commit()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = [asset]
                
                result = runner.invoke(app, [
                    "series", "Test Series"
                ])
                
                assert result.exit_code == 0
                
                # Check that deprecation warning is printed to stderr
                assert "DEPRECATION: 'assets series <name>' is deprecated" in result.stderr
                
                # Check human output format (same as assets select)
                assert "Test Series S01E01 \"The Pilot\"" in result.output
                assert str(asset.uuid) in result.output
