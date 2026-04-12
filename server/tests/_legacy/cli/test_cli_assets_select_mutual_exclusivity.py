"""
Tests for CLI assets select command mutual exclusivity validation.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests that the assets select command properly validates
mutual exclusivity between positional and flag arguments.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app


class TestCLIAssetsSelectMutualExclusivity:
    """Test CLI assets select mutual exclusivity validation."""

    def test_select_series_positional_and_flag_mutual_exclusivity(self, temp_db_session):
        """Test that providing both positional series and --series raises error."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "Test Series", "--series", "Another Series", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Provide either positional SERIES or --series, not both" in result.output

    def test_select_series_positional_and_flag_mutual_exclusivity_human_output(self, temp_db_session):
        """Test mutual exclusivity error in human output mode."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "Test Series", "--series", "Another Series", "--mode", "random"
            ])
            
            assert result.exit_code == 1
            assert "Provide either positional SERIES or --series, not both" in result.output

    def test_select_series_positional_only_works(self, temp_db_session):
        """Test that positional series argument works correctly."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (will cause error, but that's expected)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "select", "Test Series", "--mode", "random", "--json"
                ])
                
                # Should get "no episodes found" error, not mutual exclusivity error
                assert result.exit_code == 1
                assert "No episodes found for series" in result.output
                assert "Provide either positional SERIES or --series" not in result.output

    def test_select_series_flag_only_works(self, temp_db_session):
        """Test that --series flag works correctly."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # Mock the library service to return empty list (will cause error, but that's expected)
            with patch('retrovue.content_manager.library_service.LibraryService.list_episodes_by_series') as mock_list_episodes:
                mock_list_episodes.return_value = []
                
                result = runner.invoke(app, [
                    "select", "--series", "Test Series", "--mode", "random", "--json"
                ])
                
                # Should get "no episodes found" error, not mutual exclusivity error
                assert result.exit_code == 1
                assert "No episodes found for series" in result.output
                assert "Provide either positional SERIES or --series" not in result.output

    def test_select_no_filters_error(self, temp_db_session):
        """Test that providing no filters (series or genre) raises error."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Selection requires at least one filter: series or genre" in result.output

    def test_select_genre_only_error(self, temp_db_session):
        """Test that providing only genre (not implemented) raises error."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "--genre", "horror", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Genre filtering not yet implemented" in result.output
