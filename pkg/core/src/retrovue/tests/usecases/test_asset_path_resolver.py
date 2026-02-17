"""Tests for AssetPathResolver."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from retrovue.usecases.asset_path_resolver import AssetPathResolver


class TestToLocalPath:
    """Test _to_local_path static method."""

    def test_file_uri(self):
        assert AssetPathResolver._to_local_path("file:///mnt/data/movie.mkv") == "/mnt/data/movie.mkv"

    def test_bare_path(self):
        assert AssetPathResolver._to_local_path("/mnt/data/movie.mkv") == "/mnt/data/movie.mkv"

    def test_plex_uri_returns_none(self):
        assert AssetPathResolver._to_local_path("plex://12345") is None

    def test_empty_returns_none(self):
        assert AssetPathResolver._to_local_path("") is None

    def test_none_returns_none(self):
        assert AssetPathResolver._to_local_path(None) is None


class TestApplyPathMappings:
    """Test _apply_path_mappings method."""

    def test_longest_prefix_match(self):
        resolver = AssetPathResolver(path_mappings=[
            ("/media", "/mnt/data/media"),
            ("/media/retrotv", "/mnt/data/media/retrotv"),
        ])
        result = resolver._apply_path_mappings("/media/retrotv/Show/ep.mkv")
        assert result == str(Path("/mnt/data/media/retrotv/Show/ep.mkv"))

    def test_no_match_returns_none(self):
        resolver = AssetPathResolver(path_mappings=[("/media/tv", "/mnt/tv")])
        assert resolver._apply_path_mappings("/other/path/file.mkv") is None

    def test_empty_mappings_returns_none(self):
        resolver = AssetPathResolver(path_mappings=[])
        assert resolver._apply_path_mappings("/any/path") is None


class TestResolve:
    """Test the main resolve() method."""

    def test_cached_canonical_uri_used_when_exists(self, tmp_path):
        f = tmp_path / "movie.mkv"
        f.touch()
        resolver = AssetPathResolver()
        result = resolver.resolve(uri="plex://999", canonical_uri=str(f))
        assert result == str(f)

    def test_plex_uri_without_client_returns_none(self):
        resolver = AssetPathResolver()
        result = resolver.resolve(uri="plex://12345")
        assert result is None

    def test_plex_uri_resolves_via_api_and_mapping(self, tmp_path):
        episode_file = tmp_path / "retrotv" / "Show" / "ep.mkv"
        episode_file.parent.mkdir(parents=True)
        episode_file.touch()

        mock_client = MagicMock()
        mock_client.get_episode_metadata.return_value = {
            "Media": [{"Part": [{"file": "/media/retrotv/Show/ep.mkv"}]}]
        }

        resolver = AssetPathResolver(
            path_mappings=[("/media/retrotv", str(tmp_path / "retrotv"))],
            plex_client=mock_client,
        )
        result = resolver.resolve(uri="plex://21929")
        assert result == str(episode_file)
        mock_client.get_episode_metadata.assert_called_once_with(21929)

    def test_plex_uri_falls_back_to_collection_locations(self, tmp_path):
        episode_file = tmp_path / "retrotv" / "Show" / "ep.mkv"
        episode_file.parent.mkdir(parents=True)
        episode_file.touch()

        mock_client = MagicMock()
        mock_client.get_episode_metadata.return_value = {
            "Media": [{"Part": [{"file": "/external/RetroTV/Show/ep.mkv"}]}]
        }

        resolver = AssetPathResolver(
            path_mappings=[("/external/RetroTV", str(tmp_path / "retrotv"))],
            plex_client=mock_client,
            collection_locations=["/external/RetroTV"],
        )
        result = resolver.resolve(uri="plex://21929")
        assert result == str(episode_file)

    def test_bare_path_passes_through(self, tmp_path):
        f = tmp_path / "movie.mkv"
        f.touch()
        resolver = AssetPathResolver()
        result = resolver.resolve(uri=str(f))
        assert result == str(f)

    def test_file_uri_passes_through(self, tmp_path):
        f = tmp_path / "movie.mkv"
        f.touch()
        resolver = AssetPathResolver()
        result = resolver.resolve(uri=f"file://{f}")
        assert result == str(f)

    def test_invalid_rating_key_returns_none(self):
        resolver = AssetPathResolver(plex_client=MagicMock())
        result = resolver.resolve(uri="plex://not-a-number")
        assert result is None

    def test_plex_api_error_returns_none(self):
        mock_client = MagicMock()
        mock_client.get_episode_metadata.side_effect = Exception("connection refused")
        resolver = AssetPathResolver(plex_client=mock_client)
        result = resolver.resolve(uri="plex://12345")
        assert result is None
