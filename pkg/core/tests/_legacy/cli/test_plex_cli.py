"""
Tests for Plex CLI commands.

Tests the plex:verify, plex:get-episode, and plex:ingest-episode commands
with proper mocking and validation.
"""

import json
import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from retrovue.cli.commands.plex import app


class TestPlexVerify:
    """Test plex:verify command."""
    
    def test_verify_success(self, cli_runner, mock_db_session):
        """Test successful Plex server verification."""
        # Mock database session
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with patch('retrovue.cli.commands.plex.SourceService') as mock_source_service:
            mock_source_service.return_value.get_source_by_external_id.return_value = mock_source
            
            with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                mock_client_instance = Mock()
                mock_client_instance.get_libraries.return_value = [{"key": "1", "title": "Movies"}]
                mock_plex_client.return_value = mock_client_instance
                
                result = cli_runner.invoke(app, ["verify"])
                
                assert result.exit_code == 0
                assert "Connected to Plex server" in result.output
                assert "Libraries available: 1" in result.output
    
    def test_verify_json_output(self, cli_runner, mock_db_session):
        """Test verify command with JSON output."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with patch('retrovue.cli.commands.plex.SourceService') as mock_source_service:
            mock_source_service.return_value.get_source_by_external_id.return_value = mock_source
            
            with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                mock_client_instance = Mock()
                mock_client_instance.get_libraries.return_value = [{"key": "1", "title": "Movies"}]
                mock_plex_client.return_value = mock_client_instance
                
                result = cli_runner.invoke(app, ["verify", "--json"])
                
                assert result.exit_code == 0
                output_data = json.loads(result.output)
                assert "server_name" in output_data
                assert "base_url" in output_data
                assert "status" in output_data
    
    def test_verify_no_servers_configured(self, cli_runner, mock_db_session):
        """Test verify when no Plex servers are configured."""
        with patch('retrovue.cli.commands.plex.Source') as mock_source:
            mock_source.query.return_value.filter.return_value.all.return_value = []
            
            result = cli_runner.invoke(app, ["verify"])
            
            assert result.exit_code == 1
            assert "No Plex servers configured" in result.output


class TestPlexGetEpisode:
    """Test plex:get-episode command."""
    
    def test_get_episode_dry_run(self, cli_runner, mock_db_session):
        """Test get-episode command in dry-run mode."""
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
                    mock_client_instance.get_episode_metadata.return_value = {
                        "ratingKey": "12345",
                        "title": "Test Episode",
                        "grandparentTitle": "Test Series",
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
                            
                            result = cli_runner.invoke(app, ["get-episode", "--rating-key", "12345"])
                            
                            assert result.exit_code == 0
                            assert "Episode: Test Episode" in result.output
                            assert "Series: Test Series S01E01" in result.output
                            assert "Action: DRY_RUN" in result.output
        
        finally:
            # Clean up temporary file
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_get_episode_file_not_found(self, cli_runner, mock_db_session):
        """Test get-episode when resolved file doesn't exist."""
        mock_source = Mock()
        mock_source.name = "Test Plex Server"
        mock_source.config = {"base_url": "http://localhost:32400", "token": "test-token"}
        
        with patch('retrovue.cli.commands.plex.Source') as mock_source_class:
            mock_source_class.query.return_value.filter.return_value.all.return_value = [mock_source]
            
            with patch('retrovue.cli.commands.plex.PlexClient') as mock_plex_client:
                mock_client_instance = Mock()
                mock_client_instance.get_episode_metadata.return_value = {
                    "ratingKey": "12345",
                    "title": "Test Episode",
                    "grandparentTitle": "Test Series",
                    "parentIndex": "1",
                    "index": "1",
                    "Media": [{
                        "Part": [{"file": "/nonexistent/path/file.mkv"}],
                        "duration": "3600000"
                    }]
                }
                mock_plex_client.return_value = mock_client_instance
                
                with patch('retrovue.cli.commands.plex.PathMapping') as mock_path_mapping:
                    mock_mapping = Mock()
                    mock_mapping.plex_path = "/nonexistent/path"
                    mock_mapping.local_path = "/nonexistent/path"
                    mock_path_mapping.query.return_value.join.return_value.all.return_value = [mock_mapping]
                    
                    result = cli_runner.invoke(app, ["get-episode", "--rating-key", "12345"])
                    
                    assert result.exit_code == 1
                    assert "Resolved path does not exist" in result.output


class TestPlexIngestEpisode:
    """Test plex:ingest-episode command."""
    
    def test_ingest_episode_dry_run(self, cli_runner, mock_db_session):
        """Test ingest-episode command in dry-run mode."""
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
                    mock_client_instance.get_episode_metadata.return_value = {
                        "ratingKey": "12345",
                        "title": "Test Episode",
                        "grandparentTitle": "Test Series",
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
                            
                            result = cli_runner.invoke(app, ["ingest-episode", "--rating-key", "12345", "--dry-run"])
                            
                            assert result.exit_code == 0
                            assert "DRY RUN - No changes will be made" in result.output
                            assert "Would ingest: Test Episode" in result.output
        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    def test_ingest_episode_idempotent(self, cli_runner, mock_db_session):
        """Test that ingest-episode is idempotent."""
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
                    mock_client_instance.get_episode_metadata.return_value = {
                        "ratingKey": "12345",
                        "title": "Test Episode",
                        "grandparentTitle": "Test Series",
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
                                result1 = cli_runner.invoke(app, ["ingest-episode", "--rating-key", "12345"])
                                assert result1.exit_code == 0
                                assert "CREATED" in result1.output or "UPDATED" in result1.output
                                
                                # Second run - should update (idempotent)
                                result2 = cli_runner.invoke(app, ["ingest-episode", "--rating-key", "12345"])
                                assert result2.exit_code == 0
                                assert "UPDATED" in result2.output
        
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


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
