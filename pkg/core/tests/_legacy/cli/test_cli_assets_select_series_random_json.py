"""
Tests for CLI assets select command with series and random mode in JSON format.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the new assets select command when selecting from a series
with random mode, ensuring it returns the correct JSON structure.
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app
from retrovue.domain.entities import Asset, Provider, ProviderRef
from retrovue.shared.types import EntityType as EntityTypeEnum


class TestCLIAssetsSelectSeriesRandomJson:
    """Test CLI assets select with series and random mode in JSON format."""

    def test_select_series_random_json_single_episode(self, temp_db_session):
        """Test random selection from a series with one episode."""
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
                    "select", "Test Series", "--mode", "random", "--json"
                ])
                
                if result.exit_code != 0:
                    print(f"Exit code: {result.exit_code}")
                    print(f"Output: {result.output}")
                    print(f"Exception: {result.exception}")
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify structure
                assert "uuid" in output_data
                assert "id" in output_data
                assert "title" in output_data
                assert "series_title" in output_data
                assert "season_number" in output_data
                assert "episode_number" in output_data
                assert "kind" in output_data
                assert "selection" in output_data
                
                # Verify data types
                assert isinstance(output_data["id"], int)
                assert isinstance(output_data["season_number"], int)
                assert isinstance(output_data["episode_number"], int)
                assert isinstance(output_data["selection"]["mode"], str)
                
                # Verify values
                assert output_data["title"] == "The Pilot"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "random"
                assert output_data["selection"]["criteria"]["series"] == "Test Series"

    def test_select_series_random_json_multiple_episodes(self, temp_db_session):
        """Test random selection from a series with multiple episodes."""
        runner = CliRunner()
        
        # Create test data - multiple episodes
        assets = []
        for i in range(3):
            asset = Asset(
                id=i+1,
                uri=f"file:///test/episode{i+1}.mp4",
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
                provider_key=f"1234{i}",
                raw={
                    "title": f"Episode {i+1}",
                    "grandparentTitle": "Test Series",
                    "parentIndex": 1,
                    "index": i+1,
                    "kind": "episode"
                }
            )
            temp_db_session.add(provider_ref)
            assets.append(asset)
        
        temp_db_session.commit()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = assets
                
                result = runner.invoke(app, [
                    "select", "Test Series", "--mode", "random", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify structure
                assert "uuid" in output_data
                assert "id" in output_data
                assert "title" in output_data
                assert "series_title" in output_data
                assert "season_number" in output_data
                assert "episode_number" in output_data
                assert "kind" in output_data
                assert "selection" in output_data
                
                # Verify data types
                assert isinstance(output_data["id"], int)
                assert isinstance(output_data["season_number"], int)
                assert isinstance(output_data["episode_number"], int)
                
                # Verify values
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "random"
                assert output_data["selection"]["criteria"]["series"] == "Test Series"
                
                # Should be one of the episodes (random selection)
                assert output_data["episode_number"] in [1, 2, 3]

    def test_select_series_random_json_no_episodes(self, temp_db_session):
        """Test random selection from a series with no episodes."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "select", "Non-existent Series", "--mode", "random", "--json"
                ])
                
                assert result.exit_code == 1
                assert "No episodes found for series" in result.output

    def test_select_series_random_json_mutual_exclusivity(self, temp_db_session):
        """Test that positional series and --series are mutually exclusive."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "Test Series", "--series", "Test Series", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Provide either positional SERIES or --series, not both" in result.output

    def test_select_series_random_json_no_filters(self, temp_db_session):
        """Test that at least one filter (series or genre) is required."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Selection requires at least one filter: series or genre" in result.output
