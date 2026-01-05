"""
End-to-end pipeline tests for the filesystem importer.
import pytest
pytestmark = pytest.mark.skip(reason="Legacy module quarantined in src_legacy/; do not depend on it.")


This module tests the complete pipeline from file discovery through
confidence scoring and asset registration.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

from retrovue.adapters.importers.filesystem_importer import FilesystemImporter
from retrovue.content_manager.ingest_service import IngestService


class TestFilesystemPipeline:
    """End-to-end tests for the filesystem importer pipeline."""

    def setup_method(self):
        """Set up test fixtures with temporary directory."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        
        # Create test media files with various naming patterns
        self._create_test_files()
        
        # Create importer for the test directory
        self.importer = FilesystemImporter(
            root_paths=[str(self.temp_path)],
            glob_patterns=["**/*.mp4", "**/*.mkv"],
            calculate_hash=False  # Skip hashing for faster tests
        )

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)

    def _create_test_files(self):
        """Create test media files with various naming patterns."""
        # TV show with structured format
        (self.temp_path / "Breaking.Bad.S01E01.720p.mkv").touch()
        (self.temp_path / "Breaking.Bad.S01E02.720p.mkv").touch()
        
        # TV show with dash format
        (self.temp_path / "Game of Thrones - S01E01 - Winter is Coming.mp4").touch()
        
        # Movie with year
        (self.temp_path / "The.Matrix.1999.1080p.mkv").touch()
        (self.temp_path / "Inception (2010).mp4").touch()
        
        # Low quality filename
        (self.temp_path / "random_file.mp4").touch()
        
        # Very poor filename with no structure
        (self.temp_path / "xyz.mp4").touch()

    def test_discovery_pipeline(self):
        """Test the complete discovery pipeline."""
        discovered_items = self.importer.discover()
        
        # Should find all test files
        assert len(discovered_items) == 7
        
        # Check that structured labels are extracted
        tv_items = [item for item in discovered_items if 'season' in (item.raw_labels or {})]
        movie_items = [item for item in discovered_items if item.raw_labels and item.raw_labels.get('type') == 'movie']
        
        assert len(tv_items) >= 3  # At least 3 TV episodes
        assert len(movie_items) >= 2  # At least 2 movies

    def test_confidence_scoring_pipeline(self):
        """Test confidence scoring for discovered items."""
        discovered_items = self.importer.discover()
        
        # Mock the ingest service to test confidence calculation
        mock_db = Mock()
        service = IngestService(mock_db)
        
        high_confidence_items = []
        low_confidence_items = []
        
        for item in discovered_items:
            confidence = service._calculate_confidence(item)
            if confidence >= 0.8:
                high_confidence_items.append(item)
            else:
                low_confidence_items.append(item)
        
        # Should have some high confidence items (structured filenames)
        assert len(high_confidence_items) > 0
        
        # Should have some low confidence items (poor filenames)
        assert len(low_confidence_items) > 0

    def test_structured_vs_unstructured_filenames(self):
        """Test that structured filenames get higher confidence than unstructured ones."""
        discovered_items = self.importer.discover()
        
        mock_db = Mock()
        service = IngestService(mock_db)
        
        # Calculate confidence for each item
        items_with_confidence = []
        for item in discovered_items:
            confidence = service._calculate_confidence(item)
            items_with_confidence.append((item, confidence))
        
        # Sort by confidence
        items_with_confidence.sort(key=lambda x: x[1], reverse=True)
        
        # The highest confidence items should be the structured ones
        highest_confidence_item = items_with_confidence[0][0]
        assert highest_confidence_item.raw_labels is not None
        
        # Check that structured items have higher confidence
        structured_items = [item for item, conf in items_with_confidence 
                           if item.raw_labels and ('season' in item.raw_labels or 'year' in item.raw_labels)]
        unstructured_items = [item for item, conf in items_with_confidence 
                             if not (item.raw_labels and ('season' in item.raw_labels or 'year' in item.raw_labels))]
        
        if structured_items and unstructured_items:
            structured_avg_conf = sum(service._calculate_confidence(item) for item in structured_items) / len(structured_items)
            unstructured_avg_conf = sum(service._calculate_confidence(item) for item in unstructured_items) / len(unstructured_items)
            
            assert structured_avg_conf > unstructured_avg_conf

    def test_canonicalization_threshold(self):
        """Test that items with confidence >= 0.8 are marked for canonicalization."""
        discovered_items = self.importer.discover()
        
        mock_db = Mock()
        service = IngestService(mock_db)
        
        canonical_items = []
        review_items = []
        
        for item in discovered_items:
            confidence = service._calculate_confidence(item)
            if confidence >= 0.8:
                canonical_items.append(item)
            else:
                review_items.append(item)
        
        # Should have some items marked for canonicalization
        assert len(canonical_items) > 0
        
        # Should have some items marked for review
        assert len(review_items) > 0

    def test_label_extraction_accuracy(self):
        """Test that label extraction is accurate for known patterns."""
        discovered_items = self.importer.discover()
        
        # Find the Breaking Bad episode
        breaking_bad_item = None
        for item in discovered_items:
            if item.raw_labels and 'Breaking Bad' in str(item.raw_labels.get('title_guess', '')):
                breaking_bad_item = item
                break
        
        assert breaking_bad_item is not None
        assert breaking_bad_item.raw_labels['title_guess'] == 'Breaking Bad'
        assert breaking_bad_item.raw_labels['season'] == 1
        assert breaking_bad_item.raw_labels['episode'] == 1
        assert breaking_bad_item.raw_labels['type'] == 'tv'

    def test_movie_extraction_accuracy(self):
        """Test that movie extraction is accurate for known patterns."""
        discovered_items = self.importer.discover()
        
        # Find The Matrix movie
        matrix_item = None
        for item in discovered_items:
            if item.raw_labels and 'Matrix' in str(item.raw_labels.get('title_guess', '')):
                matrix_item = item
                break
        
        assert matrix_item is not None
        assert matrix_item.raw_labels['title_guess'] == 'The Matrix'
        assert matrix_item.raw_labels['year'] == 1999
        assert matrix_item.raw_labels['type'] == 'movie'
