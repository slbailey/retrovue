"""
Tests for GUID parsing functionality.
"""

from src.retrovue.shared.guid_parser import GUIDParser


class TestGuidParser:
    """Test cases for GuidParser."""

    def setup_method(self):
        """Set up test fixtures."""
        self.parser = GUIDParser()

    def test_parse_imdb_guid(self):
        """Test parsing IMDB GUID."""
        guid = "imdb://tt1234567"
        result = self.parser.parse_guid(guid)

        assert result.imdb == "tt1234567"
        assert result.plex is None
        assert result.tmdb is None
        assert result.tvdb is None
        assert result.raw == guid
        assert result.get_primary() == "imdb://tt1234567"

    def test_parse_tmdb_guid(self):
        """Test parsing TMDB GUID."""
        guid = "tmdb://12345"
        result = self.parser.parse_guid(guid)

        assert result.tmdb == "12345"
        assert result.imdb is None
        assert result.plex is None
        assert result.tvdb is None
        assert result.raw == guid
        assert result.get_primary() == "tmdb://12345"

    def test_parse_tvdb_guid(self):
        """Test parsing TVDB GUID."""
        guid = "tvdb://67890"
        result = self.parser.parse_guid(guid)

        assert result.tvdb == "67890"
        assert result.imdb is None
        assert result.plex is None
        assert result.tmdb is None
        assert result.raw == guid
        assert result.get_primary() == "tvdb://67890"

    def test_parse_plex_guid(self):
        """Test parsing Plex GUID."""
        guid = "plex://show/abc123"
        result = self.parser.parse_guid(guid)

        assert result.plex == "abc123"
        assert result.imdb is None
        assert result.tmdb is None
        assert result.tvdb is None
        assert result.raw == guid
        assert result.get_primary() == "plex://abc123"

    def test_parse_guid_list(self):
        """Test parsing list of GUIDs."""
        guid_list = ["imdb://tt1234567", "tmdb://12345", "tvdb://67890"]
        result = self.parser.parse_guid_list(guid_list)

        assert result.imdb == "tt1234567"
        assert result.tmdb == "12345"
        assert result.tvdb == "67890"
        assert result.raw == guid_list[0]
        assert result.get_primary() == "tvdb://67890"  # TVDB has priority

    def test_parse_plex_item(self):
        """Test parsing GUIDs from Plex item."""
        item = {"guid": "imdb://tt1234567", "ratingKey": "12345", "title": "Test Movie"}
        result = self.parser.parse_plex_item(item)

        assert result.imdb == "tt1234567"
        assert result.plex == "12345"
        assert result.raw == "imdb://tt1234567"

    def test_parse_plex_item_with_guids_list(self):
        """Test parsing GUIDs from Plex item with Guids list."""
        item = {
            "Guids": [{"id": "imdb://tt1234567"}, {"id": "tmdb://12345"}],
            "ratingKey": "12345",
            "title": "Test Movie",
        }
        result = self.parser.parse_plex_item(item)

        assert result.imdb == "tt1234567"
        assert result.tmdb == "12345"
        assert result.plex == "12345"

    def test_normalize_rating_system(self):
        """Test rating system normalization."""
        # TV ratings
        system, code = self.parser.normalize_rating_system("TV-PG")
        assert system == "TV"
        assert code == "TV-PG"

        # MPAA ratings
        system, code = self.parser.normalize_rating_system("PG-13")
        assert system == "MPAA"
        assert code == "PG-13"

        # Unknown ratings
        system, code = self.parser.normalize_rating_system("Unknown")
        assert system == "unknown"
        assert code == "Unknown"

        # Empty rating
        system, code = self.parser.normalize_rating_system("")
        assert system == "unknown"
        assert code == "unknown"

    def test_infer_kids_friendly(self):
        """Test kids-friendly inference."""
        # Kids-friendly ratings
        assert self.parser.infer_kids_friendly("G") is True
        assert self.parser.infer_kids_friendly("TV-Y") is True
        assert self.parser.infer_kids_friendly("TV-Y7") is True
        assert self.parser.infer_kids_friendly("TV-G") is True

        # Not kids-friendly ratings
        assert self.parser.infer_kids_friendly("PG-13") is False
        assert self.parser.infer_kids_friendly("R") is False
        assert self.parser.infer_kids_friendly("TV-MA") is False

        # Empty rating
        assert self.parser.infer_kids_friendly("") is False

    def test_parse_empty_guid(self):
        """Test parsing empty GUID."""
        result = self.parser.parse_guid("")
        assert result.raw == ""
        assert result.get_primary() is None

    def test_parse_none_guid(self):
        """Test parsing None GUID."""
        result = self.parser.parse_guid(None)
        assert result.raw is None
        assert result.get_primary() is None

    def test_parse_invalid_guid(self):
        """Test parsing invalid GUID format."""
        guid = "invalid://format"
        result = self.parser.parse_guid(guid)

        assert result.raw == guid
        assert result.get_primary() is None
        assert result.imdb is None
        assert result.tmdb is None
        assert result.tvdb is None
        assert result.plex is None
