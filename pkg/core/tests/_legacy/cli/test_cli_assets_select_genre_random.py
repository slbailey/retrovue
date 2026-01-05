"""
Tests for CLI assets select command with genre filtering.

This module tests the new assets select command when filtering by genre.
Note: Genre filtering is not yet implemented, so these tests verify the error handling.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.commands.assets import app


class TestCLIAssetsSelectGenreRandom:
    """Test CLI assets select with genre filtering."""

    def test_select_genre_not_implemented(self, temp_db_session):
        """Test that genre filtering returns appropriate error message."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "--genre", "horror", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Genre filtering not yet implemented" in result.output

    def test_select_genre_with_series_error(self, temp_db_session):
        """Test that providing both genre and series works (genre takes precedence)."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            # When both genre and series are provided, genre should be processed first
            # Since genre is not implemented, it should return the error
            result = runner.invoke(app, [
                "select", "Test Series", "--genre", "horror", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Genre filtering not yet implemented" in result.output

    def test_select_genre_only_no_series(self, temp_db_session):
        """Test that genre-only selection works (returns error for now)."""
        runner = CliRunner()
        
        with patch('retrovue.cli.commands.assets.session') as mock_session:
            mock_session.return_value.__enter__.return_value = temp_db_session
            
            result = runner.invoke(app, [
                "select", "--genre", "comedy", "--mode", "random", "--json"
            ])
            
            assert result.exit_code == 1
            assert "Genre filtering not yet implemented" in result.output
