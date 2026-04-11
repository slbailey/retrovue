"""
Tests for the filename parser in the filesystem importer.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the pattern recognition and label extraction functionality
for various filename formats commonly used for media files.
"""


from retrovue.adapters.importers.filesystem_importer import FilesystemImporter


class TestFilenameParser:
    """Test cases for filename pattern recognition and label extraction."""

    def setup_method(self):
        """Set up test fixtures."""
        self.importer = FilesystemImporter()

    def test_tv_show_dot_format(self):
        """Test TV show format: Show.Name.S02E05.*"""
        filename = "Breaking.Bad.S02E05.720p.mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['title_guess'] == "Breaking Bad"
        assert labels['season'] == 2
        assert labels['episode'] == 5
        assert labels['type'] == 'tv'

    def test_tv_show_dash_format(self):
        """Test TV show format: Show Name - S2E5 - Episode Title.*"""
        filename = "Breaking Bad - S2E5 - Phoenix.mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['title_guess'] == "Breaking Bad"
        assert labels['season'] == 2
        assert labels['episode'] == 5
        assert labels['episode_title'] == "Phoenix"
        assert labels['type'] == 'tv'

    def test_movie_dot_format(self):
        """Test movie format: Movie.Name.1987.*"""
        filename = "The.Matrix.1999.1080p.mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['title_guess'] == "The Matrix"
        assert labels['year'] == 1999
        assert labels['type'] == 'movie'

    def test_tv_show_with_year(self):
        """Test TV show format: Show Name (Year) - S01E01.*"""
        filename = "Breaking Bad (2008) - S01E01.mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['title_guess'] == "Breaking Bad"
        assert labels['year'] == 2008
        assert labels['season'] == 1
        assert labels['episode'] == 1
        assert labels['type'] == 'tv'

    def test_movie_with_year(self):
        """Test movie format: Movie Name (Year).*"""
        filename = "The Matrix (1999).mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['title_guess'] == "The Matrix"
        assert labels['year'] == 1999
        assert labels['type'] == 'movie'

    def test_fallback_year_extraction(self):
        """Test fallback year extraction from filename."""
        filename = "Some Random Movie 2020 Quality.mkv"
        labels = self.importer._extract_filename_labels(filename)
        
        assert labels['year'] == 2020
        assert 'title_guess' in labels

    def test_confidence_scoring_tv_show(self):
        """Test confidence scoring for TV show with structured data."""
        # Create a mock DiscoveredItem-like object
        class MockDiscovered:
            def __init__(self, raw_labels, size=None, path_uri=None):
                self.raw_labels = raw_labels
                self.size = size
                self.path_uri = path_uri

        # Test TV show with all confidence factors
        discovered = MockDiscovered(
            raw_labels={
                'title_guess': 'Breaking Bad',
                'season': 2,
                'episode': 5,
                'type': 'tv'
            },
            size=500 * 1024 * 1024,  # 500MB
            path_uri='file:///path/to/Breaking.Bad.S02E05.H264.720p.mkv'
        )

        # Import the ingest service to test confidence calculation
        from retrovue.content_manager.ingest_service import IngestService
        service = IngestService(None)  # No DB needed for this test
        
        confidence = service._calculate_confidence(discovered)
        
        # Should get high confidence: 0.5 (base) + 0.4 (title) + 0.2 (season/episode) + 0.2 (size) + 0.2 (codec) + 0.1 (type) = 1.6 -> 1.0
        assert confidence >= 0.9

    def test_confidence_scoring_movie(self):
        """Test confidence scoring for movie with structured data."""
        class MockDiscovered:
            def __init__(self, raw_labels, size=None, path_uri=None):
                self.raw_labels = raw_labels
                self.size = size
                self.path_uri = path_uri

        # Test movie with good metadata
        discovered = MockDiscovered(
            raw_labels={
                'title_guess': 'The Matrix',
                'year': 1999,
                'type': 'movie'
            },
            size=200 * 1024 * 1024,  # 200MB
            path_uri='file:///path/to/The.Matrix.1999.H265.1080p.mkv'
        )

        from retrovue.content_manager.ingest_service import IngestService
        service = IngestService(None)
        
        confidence = service._calculate_confidence(discovered)
        
        # Should get good confidence: 0.5 (base) + 0.4 (title) + 0.2 (year) + 0.2 (size) + 0.2 (codec) + 0.1 (type) = 1.6 -> 1.0
        assert confidence >= 0.9

    def test_confidence_scoring_low_quality(self):
        """Test confidence scoring for low-quality filename."""
        class MockDiscovered:
            def __init__(self, raw_labels, size=None, path_uri=None):
                self.raw_labels = raw_labels
                self.size = size
                self.path_uri = path_uri

        # Test file with minimal metadata
        discovered = MockDiscovered(
            raw_labels={},  # No structured data
            size=10 * 1024 * 1024,  # 10MB (small)
            path_uri='file:///path/to/random_file.mp4'
        )

        from retrovue.content_manager.ingest_service import IngestService
        service = IngestService(None)
        
        confidence = service._calculate_confidence(discovered)
        
        # Should get low confidence: 0.5 (base) = 0.5
        assert confidence == 0.5

    def test_edge_cases(self):
        """Test edge cases and malformed filenames."""
        # Test empty filename
        labels = self.importer._extract_filename_labels("")
        assert labels == {}

        # Test filename with only extension - should extract the extension name
        labels = self.importer._extract_filename_labels(".mkv")
        assert labels == {'title_guess': 'mkv'}

        # Test filename with special characters
        labels = self.importer._extract_filename_labels("Show-Name_S01E01_2020.mkv")
        assert 'title_guess' in labels or 'year' in labels

    def test_case_insensitive_patterns(self):
        """Test that patterns work regardless of case."""
        # Test lowercase - should match the TV pattern
        labels = self.importer._extract_filename_labels("breaking.bad.s02e05.mkv")
        assert labels['title_guess'] == "breaking bad"
        assert labels['season'] == 2
        assert labels['episode'] == 5

        # Test mixed case - should match the TV pattern
        labels = self.importer._extract_filename_labels("Breaking.Bad.S02E05.mkv")
        assert labels['title_guess'] == "Breaking Bad"
        assert labels['season'] == 2
        assert labels['episode'] == 5
