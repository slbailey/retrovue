"""
Tests for CLI assets series command JSON output for a specific series.

This module tests the new explicit tree structure JSON format when requesting
a specific series, ensuring correct numeric types and sorting.
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app
from retrovue.domain.entities import Asset, EntityType, ProviderRef


class TestCLIAssetsSeriesJsonSingle:
    """Test CLI assets series JSON output for a specific series."""

    def test_series_json_single_series_structure(self, temp_db_session):
        """Test that JSON output for a specific series matches the expected schema."""
        # Create test assets with provider refs
        asset1 = Asset(uri="/test/episode1.mp4", size=1000, duration_ms=1800000)
        asset2 = Asset(uri="/test/episode2.mp4", size=1000, duration_ms=1800000)
        asset3 = Asset(uri="/test/episode3.mp4", size=1000, duration_ms=1800000)
        
        temp_db_session.add_all([asset1, asset2, asset3])
        temp_db_session.flush()
        
        # Create provider refs with series data
        ref1 = ProviderRef(
            asset_id=asset1.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 1,
                'index': 1,
                'title': 'Episode 1',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '123'
            }
        )
        ref2 = ProviderRef(
            asset_id=asset2.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 1,
                'index': 2,
                'title': 'Episode 2',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '124'
            }
        )
        ref3 = ProviderRef(
            asset_id=asset3.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 2,
                'index': 1,
                'title': 'Episode 3',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '125'
            }
        )
        
        temp_db_session.add_all([ref1, ref2, ref3])
        temp_db_session.commit()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "series", "--series", "Test Series", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.output)
            
            # Verify top-level structure
            assert "series" in output_data
            assert "total_episodes" in output_data
            assert "seasons" in output_data
            
            # Verify series name
            assert output_data["series"] == "Test Series"
            
            # Verify total_episodes is numeric
            assert isinstance(output_data["total_episodes"], int)
            assert output_data["total_episodes"] == 3
            
            # Verify seasons is an array
            assert isinstance(output_data["seasons"], list)
            assert len(output_data["seasons"]) == 2  # Two seasons
            
            # Verify season structure
            season1 = output_data["seasons"][0]
            assert "season_number" in season1
            assert "episode_count" in season1
            assert "episodes" in season1
            
            # Verify season_number is numeric
            assert isinstance(season1["season_number"], int)
            assert season1["season_number"] == 1
            
            # Verify episode_count is numeric
            assert isinstance(season1["episode_count"], int)
            assert season1["episode_count"] == 2
            
            # Verify episodes array
            assert isinstance(season1["episodes"], list)
            assert len(season1["episodes"]) == 2
            
            # Verify episode structure
            episode = season1["episodes"][0]
            assert "id" in episode
            assert "uuid" in episode
            assert "title" in episode
            assert "season_number" in episode
            assert "episode_number" in episode
            assert "duration_sec" in episode
            assert "kind" in episode
            assert "source" in episode
            assert "source_rating_key" in episode
            
            # Verify numeric fields are numbers, not strings
            assert isinstance(episode["id"], int)
            assert isinstance(episode["season_number"], int)
            assert isinstance(episode["episode_number"], int)
            assert isinstance(episode["duration_sec"], int)
            
            # Verify string fields
            assert isinstance(episode["uuid"], str)
            assert isinstance(episode["title"], str)
            assert isinstance(episode["kind"], str)
            assert isinstance(episode["source"], str)
            assert isinstance(episode["source_rating_key"], str)

    def test_series_json_single_series_sorting(self, temp_db_session):
        """Test that seasons and episodes are sorted correctly."""
        # Create test assets with mixed season/episode numbers
        asset1 = Asset(uri="/test/episode1.mp4", size=1000, duration_ms=1800000)
        asset2 = Asset(uri="/test/episode2.mp4", size=1000, duration_ms=1800000)
        asset3 = Asset(uri="/test/episode3.mp4", size=1000, duration_ms=1800000)
        asset4 = Asset(uri="/test/episode4.mp4", size=1000, duration_ms=1800000)
        
        temp_db_session.add_all([asset1, asset2, asset3, asset4])
        temp_db_session.flush()
        
        # Create provider refs with mixed ordering
        ref1 = ProviderRef(
            asset_id=asset1.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 2,  # Season 2
                'index': 1,        # Episode 1
                'title': 'Season 2 Episode 1',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '123'
            }
        )
        ref2 = ProviderRef(
            asset_id=asset2.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 1,  # Season 1
                'index': 2,        # Episode 2
                'title': 'Season 1 Episode 2',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '124'
            }
        )
        ref3 = ProviderRef(
            asset_id=asset3.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 1,  # Season 1
                'index': 1,        # Episode 1
                'title': 'Season 1 Episode 1',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '125'
            }
        )
        ref4 = ProviderRef(
            asset_id=asset4.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 2,  # Season 2
                'index': 2,        # Episode 2
                'title': 'Season 2 Episode 2',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '126'
            }
        )
        
        temp_db_session.add_all([ref1, ref2, ref3, ref4])
        temp_db_session.commit()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "series", "--series", "Test Series", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.output)
            
            # Verify seasons are sorted by season_number
            seasons = output_data["seasons"]
            assert len(seasons) == 2
            assert seasons[0]["season_number"] == 1
            assert seasons[1]["season_number"] == 2
            
            # Verify episodes within each season are sorted by episode_number
            season1_episodes = seasons[0]["episodes"]
            assert len(season1_episodes) == 2
            assert season1_episodes[0]["episode_number"] == 1
            assert season1_episodes[0]["title"] == "Season 1 Episode 1"
            assert season1_episodes[1]["episode_number"] == 2
            assert season1_episodes[1]["title"] == "Season 1 Episode 2"
            
            season2_episodes = seasons[1]["episodes"]
            assert len(season2_episodes) == 2
            assert season2_episodes[0]["episode_number"] == 1
            assert season2_episodes[0]["title"] == "Season 2 Episode 1"
            assert season2_episodes[1]["episode_number"] == 2
            assert season2_episodes[1]["title"] == "Season 2 Episode 2"

    def test_series_json_single_series_positional_arg(self, temp_db_session):
        """Test that positional argument works the same as --series flag."""
        # Create test asset
        asset = Asset(uri="/test/episode1.mp4", size=1000, duration_ms=1800000)
        temp_db_session.add(asset)
        temp_db_session.flush()
        
        ref = ProviderRef(
            asset_id=asset.id,
            entity_type=EntityType.ASSET,
            raw={
                'grandparentTitle': 'Test Series',
                'parentIndex': 1,
                'index': 1,
                'title': 'Episode 1',
                'kind': 'episode',
                'source': 'plex',
                'ratingKey': '123'
            }
        )
        temp_db_session.add(ref)
        temp_db_session.commit()
        
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Test positional argument
            result = runner.invoke(app, [
                "series", "Test Series", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.output)
            
            # Verify structure is the same as with --series flag
            assert "series" in output_data
            assert "total_episodes" in output_data
            assert "seasons" in output_data
            assert output_data["series"] == "Test Series"
            assert output_data["total_episodes"] == 1
