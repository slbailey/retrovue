"""
Tests for CLI assets select command with series and sequential mode in JSON format.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the new assets select command when selecting from a series
with sequential mode, ensuring it returns the first episode (S01E01) when no history exists.
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app
from retrovue.domain.entities import Asset, Provider, ProviderRef
from retrovue.shared.types import EntityType as EntityTypeEnum


class TestCLIAssetsSelectSeriesSequentialJson:
    """Test CLI assets select with series and sequential mode in JSON format."""

    def test_select_series_sequential_json_first_episode(self, temp_db_session):
        """Test sequential selection returns first episode (S01E01) when no history exists."""
        runner = CliRunner()
        
        # Create test data - multiple episodes in order
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
                    "select", "Test Series", "--mode", "sequential", "--json"
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
                
                # Verify values - should be first episode
                assert output_data["title"] == "Episode 1"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "sequential"
                assert output_data["selection"]["criteria"]["series"] == "Test Series"

    def test_select_series_sequential_json_single_episode(self, temp_db_session):
        """Test sequential selection with only one episode."""
        runner = CliRunner()
        
        # Create test data - single episode
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
                "title": "The Only Episode",
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
                    "select", "Test Series", "--mode", "sequential", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify values - should be the single episode
                assert output_data["title"] == "The Only Episode"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "sequential"

    def test_select_series_sequential_json_multiple_seasons(self, temp_db_session):
        """Test sequential selection with multiple seasons."""
        runner = CliRunner()
        
        # Create test data - episodes from multiple seasons
        assets = []
        episodes_data = [
            (1, 1, "S01E01"),
            (1, 2, "S01E02"),
            (2, 1, "S02E01"),
            (2, 2, "S02E02"),
        ]
        
        for i, (season, episode, title) in enumerate(episodes_data):
            asset = Asset(
                id=i+1,
                uri=f"file:///test/{title}.mp4",
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
                    "title": title,
                    "grandparentTitle": "Test Series",
                    "parentIndex": season,
                    "index": episode,
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
                    "select", "Test Series", "--mode", "sequential", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify values - should be first episode (S01E01)
                assert output_data["title"] == "S01E01"
                assert output_data["series_title"] == "Test Series"
                assert output_data["season_number"] == 1
                assert output_data["episode_number"] == 1
                assert output_data["kind"] == "episode"
                assert output_data["selection"]["mode"] == "sequential"
