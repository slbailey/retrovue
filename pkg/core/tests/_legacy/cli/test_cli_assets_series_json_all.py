"""
Tests for CLI assets series command JSON output when listing all series.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the JSON format when no specific series is requested,
ensuring it returns {"series": [...]} format.
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app


class TestCLIAssetsSeriesJsonAll:
    """Test CLI assets series JSON output when listing all series."""

    def test_series_json_all_series_structure(self, temp_db_session):
        """Test that JSON output for all series returns correct format."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return a list of series
            with patch('retrovue.content_manager.library_service.LibraryService.list_series') as mock_list_series:
                mock_list_series.return_value = ["Series A", "Series B", "Series C"]
                
                result = runner.invoke(app, [
                    "series", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify structure
                assert "series" in output_data
                assert isinstance(output_data["series"], list)
                assert output_data["series"] == ["Series A", "Series B", "Series C"]

    def test_series_json_all_series_empty_list(self, temp_db_session):
        """Test that JSON output handles empty series list correctly."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return an empty list
            with patch('retrovue.content_manager.library_service.LibraryService.list_series') as mock_list_series:
                mock_list_series.return_value = []
                
                result = runner.invoke(app, [
                    "series", "--json"
                ])
                
                assert result.exit_code == 1  # Should exit with error for empty list
                assert "No series found" in result.output

    def test_series_json_all_series_single_series(self, temp_db_session):
        """Test that JSON output works with a single series."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return a single series
            with patch('retrovue.content_manager.library_service.LibraryService.list_series') as mock_list_series:
                mock_list_series.return_value = ["Single Series"]
                
                result = runner.invoke(app, [
                    "series", "--json"
                ])
                
                assert result.exit_code == 0
                
                # Parse JSON output
                output_data = json.loads(result.output)
                
                # Verify structure
                assert "series" in output_data
                assert isinstance(output_data["series"], list)
                assert output_data["series"] == ["Single Series"]
