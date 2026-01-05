"""
Tests for FilesystemImporter.

This module tests the filesystem importer functionality.
"""

import tempfile
from pathlib import Path

import pytest

from retrovue.adapters.importers.base import DiscoveredItem, ImporterError
from retrovue.adapters.importers.filesystem_importer import FilesystemImporter


class TestFilesystemImporter:
    """Test cases for FilesystemImporter."""
    
    def test_importer_creation(self):
        """Test creating a filesystem importer."""
        importer = FilesystemImporter()
        
        assert importer.name == "filesystem"
        assert importer.root_paths == ["."]
        assert importer.glob_patterns is not None
        assert len(importer.glob_patterns) > 0
    
    def test_importer_with_custom_config(self):
        """Test creating importer with custom configuration."""
        importer = FilesystemImporter(
            root_paths=["/test/path1", "/test/path2"],
            glob_patterns=["**/*.mp4", "**/*.mkv"],
            include_hidden=True,
            calculate_hash=False
        )
        
        assert importer.root_paths == ["/test/path1", "/test/path2"]
        assert importer.glob_patterns == ["**/*.mp4", "**/*.mkv"]
        assert importer.include_hidden is True
        assert importer.calculate_hash is False
    
    def test_discover_empty_directory(self):
        """Test discovering content from an empty directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            importer = FilesystemImporter(root_paths=[temp_dir])
            
            items = importer.discover()
            
            assert isinstance(items, list)
            assert len(items) == 0
    
    def test_discover_with_test_files(self):
        """Test discovering content with test files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create test files
            test_files = [
                "video1.mp4",
                "video2.mkv", 
                "video3.avi",
                "document.txt",  # Should be ignored
                "subdir/video4.mp4"
            ]
            
            for file_name in test_files:
                file_path = Path(temp_dir) / file_name
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text("test content")
            
            importer = FilesystemImporter(
                root_paths=[temp_dir],
                glob_patterns=["**/*.mp4", "**/*.mkv", "**/*.avi"]
            )
            
            items = importer.discover()
            
            assert len(items) >= 3  # At least 3 video files
            
            # Check that all items are DiscoveredItem instances
            for item in items:
                assert isinstance(item, DiscoveredItem)
                assert item.path_uri.startswith("file://")
                assert item.provider_key is not None
                assert item.raw_labels is not None
                assert item.last_modified is not None
                assert item.size is not None
    
    def test_discover_hidden_files(self):
        """Test discovering content including hidden files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create hidden file
            hidden_file = Path(temp_dir) / ".hidden_video.mp4"
            hidden_file.write_text("test content")
            
            # Test with include_hidden=True
            importer = FilesystemImporter(
                root_paths=[temp_dir],
                include_hidden=True
            )
            
            items = importer.discover()
            
            # Should find the hidden file
            hidden_uris = [item.path_uri for item in items]
            assert any(".hidden_video.mp4" in uri for uri in hidden_uris)
    
    def test_discover_exclude_hidden_files(self):
        """Test discovering content excluding hidden files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create hidden file
            hidden_file = Path(temp_dir) / ".hidden_video.mp4"
            hidden_file.write_text("test content")
            
            # Test with include_hidden=False (default)
            importer = FilesystemImporter(
                root_paths=[temp_dir],
                include_hidden=False
            )
            
            items = importer.discover()
            
            # Should not find the hidden file
            hidden_uris = [item.path_uri for item in items]
            assert not any(".hidden_video.mp4" in uri for uri in hidden_uris)
    
    def test_discover_nonexistent_path(self):
        """Test discovering from a nonexistent path."""
        importer = FilesystemImporter(root_paths=["/nonexistent/path"])
        
        with pytest.raises(ImporterError):  # Should raise an error
            importer.discover()
    
    def test_discover_file_not_directory(self):
        """Test discovering from a file instead of directory."""
        with tempfile.NamedTemporaryFile() as temp_file:
            importer = FilesystemImporter(root_paths=[temp_file.name])
            
            with pytest.raises(ImporterError):  # Should raise an error
                importer.discover()
    
    def test_extract_filename_labels(self):
        """Test extracting labels from filenames."""
        importer = FilesystemImporter()
        
        # Test various filename patterns
        test_cases = [
            ("movie.mp4", ["movie"]),
            ("TV.Show.S01E01.mp4", ["TV", "Show", "S01E01"]),
            ("Movie_Name_2023.mp4", ["Movie", "Name", "2023"]),
            ("show.s01e02.1080p.mkv", ["show", "s01e02", "1080p"]),
        ]
        
        for filename, expected_labels in test_cases:
            labels = importer._extract_filename_labels(filename)
            assert labels == expected_labels
    
    def test_calculate_file_hash(self):
        """Test calculating file hash."""
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file.flush()
            temp_file.close()  # Close the file handle
            
            try:
                importer = FilesystemImporter()
                file_path = Path(temp_file.name)
                
                hash_value = importer._calculate_file_hash(file_path)
                
                assert isinstance(hash_value, str)
                assert len(hash_value) == 64  # SHA-256 hex length
            finally:
                # Clean up the file
                Path(temp_file.name).unlink(missing_ok=True)
    
    def test_should_include_file(self):
        """Test file inclusion logic."""
        importer = FilesystemImporter()
        
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Create test files
            regular_file = temp_path / "regular.mp4"
            regular_file.write_text("content")
            
            hidden_file = temp_path / ".hidden.mp4"
            hidden_file.write_text("content")
            
            # Test regular file
            assert importer._should_include_file(regular_file) is True
            
            # Test hidden file with include_hidden=False
            assert importer._should_include_file(hidden_file) is False
            
            # Test hidden file with include_hidden=True
            importer.include_hidden = True
            assert importer._should_include_file(hidden_file) is True
    
    def test_create_discovered_item(self):
        """Test creating discovered item from file path."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file.flush()
            temp_file.close()  # Close the file handle
            
            try:
                importer = FilesystemImporter()
                file_path = Path(temp_file.name)
                
                item = importer._create_discovered_item(file_path)
                
                assert isinstance(item, DiscoveredItem)
                assert item.path_uri.startswith("file://")
                assert item.provider_key == str(file_path)
                assert item.raw_labels is not None
                assert item.last_modified is not None
                assert item.size is not None
                assert item.hash_sha256 is not None
            finally:
                # Clean up the file
                Path(temp_file.name).unlink(missing_ok=True)
    
    def test_create_discovered_item_without_hash(self):
        """Test creating discovered item without calculating hash."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_file.write(b"test content")
            temp_file.flush()
            temp_file.close()  # Close the file handle
            
            try:
                importer = FilesystemImporter(calculate_hash=False)
                file_path = Path(temp_file.name)
                
                item = importer._create_discovered_item(file_path)
                
                assert isinstance(item, DiscoveredItem)
                assert item.hash_sha256 is None
            finally:
                # Clean up the file
                Path(temp_file.name).unlink(missing_ok=True)
