"""
Tests for CLI assets series command argument parsing.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the mutual exclusivity of positional and --series arguments,
and ensures proper error handling.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app


class TestCLIAssetsSeriesArgParsing:
    """Test CLI assets series argument parsing."""

    def test_series_both_positional_and_flag_error(self, temp_db_session):
        """Test that providing both positional and --series raises an error."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "series", "Test Series", "--series", "Another Series"
            ])
            
            assert result.exit_code == 1
            assert "Provide either positional SERIES or --series, not both" in result.output

    def test_series_positional_argument_works(self, temp_db_session):
        """Test that positional argument works correctly."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (series not found)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "series", "Test Series"
                ])
                
                assert result.exit_code == 1
                assert "No episodes found for series 'Test Series'" in result.output

    def test_series_flag_argument_works(self, temp_db_session):
        """Test that --series flag works correctly."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (series not found)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "series", "--series", "Test Series"
                ])
                
                assert result.exit_code == 1
                assert "No episodes found for series 'Test Series'" in result.output

    def test_series_no_arguments_lists_all(self, temp_db_session):
        """Test that no arguments lists all series."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return a list of series
            with patch('retrovue.content_manager.library_service.LibraryService.list_series') as mock_list_series:
                mock_list_series.return_value = ["Series A", "Series B"]
                
                result = runner.invoke(app, [
                    "series"
                ])
                
                assert result.exit_code == 0
                assert "Available series:" in result.output
                assert "Series A" in result.output
                assert "Series B" in result.output

    def test_series_positional_with_json(self, temp_db_session):
        """Test that positional argument works with --json flag."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (series not found)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "series", "Test Series", "--json"
                ])
                
                assert result.exit_code == 1
                assert "No episodes found for series 'Test Series'" in result.output

    def test_series_flag_with_json(self, temp_db_session):
        """Test that --series flag works with --json flag."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (series not found)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "series", "--series", "Test Series", "--json"
                ])
                
                assert result.exit_code == 1
                assert "No episodes found for series 'Test Series'" in result.output
