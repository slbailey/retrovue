"""
Tests for Plex CLI series/season/episode lookup functionality.

Tests the new series/season/episode selectors with proper mocking and validation.
"""

import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from retrovue.cli.commands.plex import app


class TestPlexSSELookup:
    """Test series/season/episode lookup functionality."""
    
    def test_get_episode_by_sse_dry_run(self, cli_runner, mock_db_session):
        """Test get-episode command with series/season/episode selectors in dry-run mode."""
        # Mock database and file system
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(b"fake video content")
        
        try:
            with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
                mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
                
                with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                    mock_client_instance = Mock()
                    mock_client_instance.find_episode_by_sse.return_value = {
                        "ratingKey": "12345",
                        "title": "The Pilot",
                        "grandparentTitle": "Batman TAS",
                        "parentIndex": "1",
                        "index": "1",
                        "Media": [{
                            "Part": [{"file": temp_path}],
                            "duration": "3600000"
                        }]
                    }
                    mock_plex_client.return_value = mock_client_instance
                    
                    with patch('retrovue.cli.commands.plex.PathMapping') as mock_path_mapping:
                        mock_mapping = Mock()
                        mock_mapping.plex_path = "/"
                        mock_mapping.local_path = "/"
                        mock_path_mapping.query.return_value.join.return_value.all.return_value = [mock_mapping]
                        
                        with patch('retrovue.cli.commands.plex.FFprobeEnricher') as mock_ffprobe:
                            mock_enricher_instance = Mock()
                            mock_enricher_instance.enrich.return_value.raw_labels = [
                                "duration_ms:3600000",
                                "video_codec:h264",
                                "audio_codec:aac"
                            ]
                            mock_ffprobe.return_value = mock_enricher_instance
                            
                            result = cli_runner.invoke(app, [
                                "get-episode", 
                                "--series", "Batman TAS", 
                                "--season", "1", 
                                "--episode", "1"
                            ])
                            
                            assert result.exit_code == 0
                            assert "Episode: The Pilot" in result.output
                            assert "Series: Batman TAS S01E01" in result.output
                            assert "Action: DRY_RUN" in result.output
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_get_episode_by_sse_json_output(self, cli_runner, mock_db_session):
        """Test get-episode command with JSON output format."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(b"fake video content")
        
        try:
            with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
                mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
                
                with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                    mock_client_instance = Mock()
                    mock_client_instance.find_episode_by_sse.return_value = {
                        "ratingKey": "12345",
                        "title": "The Pilot",
                        "grandparentTitle": "Batman TAS",
                        "parentIndex": "1",
                        "index": "1",
                        "Media": [{
                            "Part": [{"file": temp_path}],
                            "duration": "3600000"
                        }]
                    }
                    mock_plex_client.return_value = mock_client_instance
                    
                    with patch('retrovue.cli.commands.plex.PathMapping') as mock_path_mapping:
                        mock_mapping = Mock()
                        mock_mapping.plex_path = "/"
                        mock_mapping.local_path = "/"
                        mock_path_mapping.query.return_value.join.return_value.all.return_value = [mock_mapping]
                        
                        with patch('retrovue.cli.commands.plex.FFprobeEnricher') as mock_ffprobe:
                            mock_enricher_instance = Mock()
                            mock_enricher_instance.enrich.return_value.raw_labels = [
                                "duration_ms:3600000",
                                "video_codec:h264",
                                "audio_codec:aac"
                            ]
                            mock_ffprobe.return_value = mock_enricher_instance
                            
                            result = cli_runner.invoke(app, [
                                "get-episode", 
                                "--series", "Batman TAS", 
                                "--season", "1", 
                                "--episode", "1",
                                "--json"
                            ])
                            
                            assert result.exit_code == 0
                            output_data = json.loads(result.output)
                            
                            # Verify the JSON structure matches the specification
                            assert "action" in output_data
                            assert "provenance" in output_data
                            assert "episode" in output_data
                            assert "file" in output_data
                            
                            assert output_data["action"] == "DRY_RUN"
                            assert output_data["provenance"]["source"] == "plex"
                            assert output_data["provenance"]["source_rating_key"] == "12345"
                            assert output_data["episode"]["series_title"] == "Batman TAS"
                            assert output_data["episode"]["season_number"] == 1
                            assert output_data["episode"]["episode_number"] == 1
                            assert output_data["episode"]["title"] == "The Pilot"
        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_ingest_by_sse_idempotent(self, cli_runner, mock_db_session):
        """Test that ingest-episode with series/season/episode is idempotent."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with tempfile.NamedTemporaryFile(suffix=".mkv", delete=False) as temp_file:
            temp_path = temp_file.name
            temp_file.write(b"fake video content")
        
        try:
            with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
                mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
                
                with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                    mock_client_instance = Mock()
                    mock_client_instance.find_episode_by_sse.return_value = {
                        "ratingKey": "12345",
                        "title": "The Pilot",
                        "grandparentTitle": "Batman TAS",
                        "parentIndex": "1",
                        "index": "1",
                        "Media": [{
                            "Part": [{"file": temp_path}],
                            "duration": "3600000"
                        }]
                    }
                    mock_plex_client.return_value = mock_client_instance
                    
                    with patch('retrovue.cli.commands.plex.PathMapping') as mock_path_mapping:
                        mock_mapping = Mock()
                        mock_mapping.plex_path = "/"
                        mock_mapping.local_path = "/"
                        mock_path_mapping.query.return_value.join.return_value.all.return_value = [mock_mapping]
                        
                        with patch('retrovue.cli.commands.plex.FFprobeEnricher') as mock_ffprobe:
                            mock_enricher_instance = Mock()
                            mock_enricher_instance.enrich.return_value.raw_labels = [
                                "duration_ms:3600000",
                                "video_codec:h264",
                                "audio_codec:aac"
                            ]
                            mock_ffprobe.return_value = mock_enricher_instance
                            
                            # Mock database entities
                            mock_asset = Mock()
                            mock_asset.id = "asset-123"
                            mock_asset.uri = f"file://{temp_path}"
                            
                            with patch('retrovue.cli.commands.plex.Asset') as mock_asset_class:
                                mock_asset_class.query.return_value.filter.return_value.first.return_value = mock_asset
                                
                                # First run - should create
                                result1 = cli_runner.invoke(app, [
                                    "ingest-episode", 
                                    "--series", "Batman TAS", 
                                    "--season", "1", 
                                    "--episode", "1"
                                ])
                                assert result1.exit_code == 0
                                assert "CREATED" in result1.output or "UPDATED" in result1.output
                                
                                # Second run - should update (idempotent)
                                result2 = cli_runner.invoke(app, [
                                    "ingest-episode", 
                                    "--series", "Batman TAS", 
                                    "--season", "1", 
                                    "--episode", "1"
                                ])
                                assert result2.exit_code == 0
                                assert "UPDATED" in result2.output
        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_lookup_ambiguity_multiple_series(self, cli_runner, mock_db_session):
        """Test error handling when multiple series match."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
            mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
            
            with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                mock_client_instance = Mock()
                mock_client_instance.find_episode_by_sse.side_effect = Exception("Multiple series found matching 'Batman': ['Batman TAS', 'Batman Beyond']. Please be more specific.")
                mock_plex_client.return_value = mock_client_instance
                
                result = cli_runner.invoke(app, [
                    "get-episode", 
                    "--series", "Batman", 
                    "--season", "1", 
                    "--episode", "1"
                ])
                
                assert result.exit_code == 1
                assert "Multiple series found" in result.output
    
    def test_lookup_episode_not_found(self, cli_runner, mock_db_session):
        """Test error handling when episode not found."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
            mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
            
            with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                mock_client_instance = Mock()
                mock_client_instance.find_episode_by_sse.side_effect = Exception("Episode 5 not found in season 1 of 'Batman TAS'. Available episodes: [1, 2, 3, 4]")
                mock_plex_client.return_value = mock_client_instance
                
                result = cli_runner.invoke(app, [
                    "get-episode", 
                    "--series", "Batman TAS", 
                    "--season", "1", 
                    "--episode", "5"
                ])
                
                assert result.exit_code == 1
                assert "Episode 5 not found" in result.output
    
    def test_validation_missing_parameters(self, cli_runner, mock_db_session):
        """Test validation when required parameters are missing."""
        result = cli_runner.invoke(app, [
            "get-episode", 
            "--series", "Batman TAS", 
            "--season", "1"
            # Missing --episode
        ])
        
        assert result.exit_code == 1
        assert "Either --rating-key or all of --series, --season, --episode must be provided" in result.output
    
    def test_validation_conflicting_parameters(self, cli_runner, mock_db_session):
        """Test validation when both rating-key and series/season/episode are provided."""
        result = cli_runner.invoke(app, [
            "get-episode", 
            "12345",  # rating-key
            "--series", "Batman TAS", 
            "--season", "1", 
            "--episode", "1"
        ])
        
        assert result.exit_code == 1
        assert "Cannot use both --rating-key and series/season/episode selectors" in result.output


@pytest.fixture
def cli_runner():
    """Create a CLI runner for testing."""
    from typer.testing import CliRunner
    return CliRunner()


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    with patch('retrovue.cli.commands.plex.session') as mock_session:
        mock_db = Mock()
        mock_session.return_value.__enter__.return_value = mock_db
        yield mock_db
