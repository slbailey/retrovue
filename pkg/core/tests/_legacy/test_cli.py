"""
Tests for CLI functionality.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.retrovue.cli.main import app


class TestCLI:
    """Test cases for CLI functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = Path(self.temp_dir) / "test.json"

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_app_help(self):
        """Test that app help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert "Plex synchronization CLI" in result.output

    def test_libraries_command_help(self):
        """Test that libraries command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["libraries", "--help"])

        assert result.exit_code == 0
        assert "List Plex libraries" in result.output

    def test_preview_items_command_help(self):
        """Test that preview-items command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["preview-items", "--help"])

        assert result.exit_code == 0
        assert "Preview raw items returned by Plex" in result.output

    def test_resolve_path_command_help(self):
        """Test that resolve-path command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["resolve-path", "--help"])

        assert result.exit_code == 0
        assert "Resolve a Plex path to local path" in result.output

    def test_map_item_command_help(self):
        """Test that map-item command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["map-item", "--help"])

        assert result.exit_code == 0
        assert "Map one Plex item JSON to our model" in result.output

    def test_ingest_command_help(self):
        """Test that ingest command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["ingest", "--help"])

        assert result.exit_code == 0
        assert "Ingest: discover + map + upsert" in result.output

    def test_test_guid_command_help(self):
        """Test that test-guid command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["test-guid", "--help"])

        assert result.exit_code == 0
        assert "Test GUID parsing" in result.output

    def test_test_pathmap_command_help(self):
        """Test that test-pathmap command help works."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["test-pathmap", "--help"])

        assert result.exit_code == 0
        assert "Test path mapping functionality" in result.output

    def test_map_item_from_json(self):
        """Test map-item command with JSON file."""
        from typer.testing import CliRunner

        # Create test JSON file
        test_data = {
            "title": "Test Movie",
            "summary": "A test movie",
            "duration": 7200000,
            "contentRating": "PG-13",
            "ratingKey": "12345",
            "type": "movie",
            "year": 2023,
            "guid": "imdb://tt1234567",
            "Media": [
                {
                    "videoCodec": "h264",
                    "audioCodec": "aac",
                    "width": 1920,
                    "height": 1080,
                    "Part": [
                        {
                            "file": "/data/movies/test.mkv",
                            "size": 1000000000,
                            "container": "mkv",
                        }
                    ],
                }
            ],
        }

        with open(self.temp_file, "w") as f:
            json.dump(test_data, f)

        runner = CliRunner()
        result = runner.invoke(app, ["map-item", "--from-json", str(self.temp_file)])

        assert result.exit_code == 0
        assert "Test Movie" in result.output
        assert "movie" in result.output
        assert "PG-13" in result.output
        assert "imdb://tt1234567" in result.output

    def test_map_item_from_stdin(self):
        """Test map-item command with stdin."""
        from typer.testing import CliRunner

        test_data = {
            "title": "Test Episode",
            "summary": "A test episode",
            "duration": 1800000,
            "contentRating": "TV-PG",
            "ratingKey": "67890",
            "type": "episode",
            "parentIndex": 1,
            "index": 5,
            "guid": "tvdb://12345",
            "Media": [
                {
                    "videoCodec": "h264",
                    "audioCodec": "aac",
                    "width": 1920,
                    "height": 1080,
                    "Part": [
                        {
                            "file": "/data/tv/show/s01e05.mkv",
                            "size": 500000000,
                            "container": "mkv",
                        }
                    ],
                }
            ],
        }

        runner = CliRunner()
        result = runner.invoke(app, ["map-item", "--from-stdin"], input=json.dumps(test_data))

        assert result.exit_code == 0
        assert "Test Episode" in result.output
        assert "episode" in result.output
        assert "TV-PG" in result.output
        assert "tvdb://12345" in result.output
        assert "Season: 1" in result.output
        assert "Episode: 5" in result.output

    def test_map_item_no_input(self):
        """Test map-item command with no input specified."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["map-item"])

        assert result.exit_code == 1
        assert "Must specify either --from-json or --from-stdin" in result.output

    def test_test_guid_command(self):
        """Test test-guid command."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["test-guid", "--guid", "imdb://tt1234567"])

        assert result.exit_code == 0
        assert "tt1234567" in result.output
        assert "imdb://tt1234567" in result.output

    def test_test_guid_command_tvdb(self):
        """Test test-guid command with TVDB GUID."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["test-guid", "--guid", "tvdb://12345"])

        assert result.exit_code == 0
        assert "12345" in result.output
        assert "tvdb://12345" in result.output

    def test_test_guid_command_plex(self):
        """Test test-guid command with Plex GUID."""
        from typer.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(app, ["test-guid", "--guid", "plex://show/abc123"])

        assert result.exit_code == 0
        assert "abc123" in result.output
        assert "plex://abc123" in result.output

    @patch("cli.plex_sync.PlexClient")
    def test_libraries_command_success(self, mock_client_class):
        """Test libraries command with successful connection."""
        from typer.testing import CliRunner

        # Mock client
        mock_client = MagicMock()
        mock_client.test_connection.return_value = True
        mock_client.get_libraries.return_value = [
            MagicMock(key="1", title="Movies", type="movie", agent="com.plexapp.agents.imdb"),
            MagicMock(
                key="2",
                title="TV Shows",
                type="show",
                agent="com.plexapp.agents.thetvdb",
            ),
        ]
        mock_client_class.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "libraries",
                "--base-url",
                "http://127.0.0.1:32400",
                "--token",
                "test-token",
            ],
        )

        assert result.exit_code == 0
        assert "Movies" in result.output
        assert "TV Shows" in result.output

    @patch("cli.plex_sync.PlexClient")
    def test_libraries_command_connection_failure(self, mock_client_class):
        """Test libraries command with connection failure."""
        from typer.testing import CliRunner

        # Mock client
        mock_client = MagicMock()
        mock_client.test_connection.return_value = False
        mock_client_class.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "libraries",
                "--base-url",
                "http://127.0.0.1:32400",
                "--token",
                "test-token",
            ],
        )

        assert result.exit_code == 1
        assert "Failed to connect to Plex server" in result.output

    @patch("cli.plex_sync.PlexClient")
    def test_preview_items_command_success(self, mock_client_class):
        """Test preview-items command with successful connection."""
        from typer.testing import CliRunner

        # Mock client
        mock_client = MagicMock()
        mock_client.test_connection.return_value = True
        mock_client.get_library_items.return_value = [
            {
                "title": "Test Movie",
                "ratingKey": "12345",
                "type": "movie",
                "year": 2023,
                "duration": 7200000,
                "contentRating": "PG-13",
                "guid": "imdb://tt1234567",
                "Media": [
                    {
                        "videoCodec": "h264",
                        "audioCodec": "aac",
                        "width": 1920,
                        "height": 1080,
                        "Part": [{"file": "/data/movies/test.mkv"}],
                    }
                ],
            }
        ]
        mock_client_class.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "preview-items",
                "--base-url",
                "http://127.0.0.1:32400",
                "--token",
                "test-token",
                "--library-key",
                "1",
                "--kind",
                "movie",
                "--limit",
                "1",
            ],
        )

        assert result.exit_code == 0
        assert "Test Movie" in result.output
        assert "12345" in result.output
        assert "movie" in result.output
        assert "2023" in result.output
        assert "PG-13" in result.output
        assert "imdb://tt1234567" in result.output
        assert "h264" in result.output
        assert "aac" in result.output
        assert "1920x1080" in result.output
        assert "/data/movies/test.mkv" in result.output

    @patch("cli.plex_sync.PlexClient")
    def test_preview_items_command_no_items(self, mock_client_class):
        """Test preview-items command with no items."""
        from typer.testing import CliRunner

        # Mock client
        mock_client = MagicMock()
        mock_client.test_connection.return_value = True
        mock_client.get_library_items.return_value = []
        mock_client_class.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "preview-items",
                "--base-url",
                "http://127.0.0.1:32400",
                "--token",
                "test-token",
                "--library-key",
                "1",
                "--kind",
                "movie",
                "--limit",
                "1",
            ],
        )

        assert result.exit_code == 0
        assert "No items found" in result.output
