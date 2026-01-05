"""
Tests for FFprobeEnricher.

This module tests the FFprobe enricher functionality.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from retrovue.adapters.enrichers.base import EnricherError
from retrovue.adapters.enrichers.ffprobe_enricher import FFprobeEnricher
from retrovue.adapters.importers.base import DiscoveredItem


class TestFFprobeEnricher:
    """Test cases for FFprobeEnricher."""
    
    def test_enricher_creation(self):
        """Test creating an FFprobe enricher."""
        enricher = FFprobeEnricher()
        
        assert enricher.name == "ffprobe"
        assert enricher.ffprobe_path == "ffprobe"
    
    def test_enricher_with_custom_path(self):
        """Test creating enricher with custom FFprobe path."""
        enricher = FFprobeEnricher(ffprobe_path="/custom/path/ffprobe")
        
        assert enricher.ffprobe_path == "/custom/path/ffprobe"
    
    def test_enrich_non_file_uri(self):
        """Test enriching a non-file URI (should return unchanged)."""
        enricher = FFprobeEnricher()
        
        original_item = DiscoveredItem(
            path_uri="plex://server/item",
            provider_key="test_key",
            raw_labels=["test_label"]
        )
        
        enriched_item = enricher.enrich(original_item)
        
        # Should return the same item unchanged
        assert enriched_item is original_item
    
    def test_enrich_nonexistent_file(self):
        """Test enriching a nonexistent file."""
        enricher = FFprobeEnricher()
        
        original_item = DiscoveredItem(
            path_uri="file:///nonexistent/file.mp4",
            provider_key="test_key",
            raw_labels=["test_label"]
        )
        
        with pytest.raises(EnricherError):  # Should raise an error
            enricher.enrich(original_item)
    
    @patch('subprocess.run')
    def test_enrich_successful_ffprobe(self, mock_run):
        """Test successful enrichment with mocked FFprobe output."""
        import tempfile
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_file:
            temp_file.write(b"fake video content")
            temp_file.flush()
            temp_file.close()
            
            try:
                # Mock FFprobe output
                mock_ffprobe_output = {
                    "format": {
                        "duration": "120.5",
                        "format_name": "mp4"
                    },
                    "streams": [
                        {
                            "codec_type": "video",
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 1080
                        },
                        {
                            "codec_type": "audio", 
                            "codec_name": "aac"
                        }
                    ],
                    "chapters": [
                        {"title": "Chapter 1"},
                        {"title": "Chapter 2"}
                    ]
                }
                
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = json.dumps(mock_ffprobe_output)
                mock_result.stderr = ""
                mock_run.return_value = mock_result
                
                enricher = FFprobeEnricher()
                
                original_item = DiscoveredItem(
                    path_uri=f"file://{temp_file.name}",
                    provider_key="test_key",
                    raw_labels=["original_label"]
                )
                
                enriched_item = enricher.enrich(original_item)
                
                # Check that FFprobe was called
                mock_run.assert_called_once()
                
                # Check enriched item
                assert enriched_item.path_uri == original_item.path_uri
                assert enriched_item.provider_key == original_item.provider_key
                assert enriched_item.last_modified == original_item.last_modified
                assert enriched_item.size == original_item.size
                assert enriched_item.hash_sha256 == original_item.hash_sha256
                
                # Check that new labels were added
                assert "original_label" in enriched_item.raw_labels
                assert "duration_ms:120500" in enriched_item.raw_labels
                assert "video_codec:h264" in enriched_item.raw_labels
                assert "audio_codec:aac" in enriched_item.raw_labels
                assert "container:mp4" in enriched_item.raw_labels
                assert "resolution:1920x1080" in enriched_item.raw_labels
                assert "chapters:2" in enriched_item.raw_labels
            finally:
                # Clean up the file
                from pathlib import Path
                Path(temp_file.name).unlink(missing_ok=True)
    
    @patch('subprocess.run')
    def test_enrich_ffprobe_failure(self, mock_run):
        """Test enrichment when FFprobe fails."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "FFprobe error"
        mock_run.return_value = mock_result
        
        enricher = FFprobeEnricher()
        
        original_item = DiscoveredItem(
            path_uri="file:///test/video.mp4",
            provider_key="test_key",
            raw_labels=["original_label"]
        )
        
        with pytest.raises(EnricherError):  # Should raise an error
            enricher.enrich(original_item)
    
    @patch('subprocess.run')
    def test_enrich_ffprobe_timeout(self, mock_run):
        """Test enrichment when FFprobe times out."""
        mock_run.side_effect = TimeoutError("FFprobe timed out")
        
        enricher = FFprobeEnricher()
        
        original_item = DiscoveredItem(
            path_uri="file:///test/video.mp4",
            provider_key="test_key",
            raw_labels=["original_label"]
        )
        
        with pytest.raises(EnricherError):  # Should raise an error
            enricher.enrich(original_item)
    
    @patch('subprocess.run')
    def test_enrich_invalid_json(self, mock_run):
        """Test enrichment with invalid JSON output from FFprobe."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "invalid json"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        
        enricher = FFprobeEnricher()
        
        original_item = DiscoveredItem(
            path_uri="file:///test/video.mp4",
            provider_key="test_key",
            raw_labels=["original_label"]
        )
        
        with pytest.raises(EnricherError):  # Should raise an error
            enricher.enrich(original_item)
    
    def test_run_ffprobe_success(self):
        """Test running FFprobe successfully."""
        with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
            temp_file.write(b"fake video content")
            temp_file.flush()
            
            enricher = FFprobeEnricher()
            
            # Mock the subprocess call
            with patch('subprocess.run') as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = json.dumps({
                    "format": {"duration": "60.0", "format_name": "mp4"},
                    "streams": [
                        {"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720},
                        {"codec_type": "audio", "codec_name": "aac"}
                    ]
                })
                mock_result.stderr = ""
                mock_run.return_value = mock_result
                
                metadata = enricher._run_ffprobe(Path(temp_file.name))
                
                assert "duration" in metadata
                assert "container" in metadata
                assert "video_codec" in metadata
                assert "audio_codec" in metadata
                assert "resolution" in metadata
    
    def test_run_ffprobe_failure(self):
        """Test running FFprobe with failure."""
        with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
            temp_file.write(b"fake video content")
            temp_file.flush()
            
            enricher = FFprobeEnricher()
            
            # Mock the subprocess call to fail
            with patch('subprocess.run') as mock_run:
                mock_result = MagicMock()
                mock_result.returncode = 1
                mock_result.stderr = "FFprobe error"
                mock_run.return_value = mock_result
                
                with pytest.raises(EnricherError):  # Should raise an error
                    enricher._run_ffprobe(Path(temp_file.name))
    
    def test_run_ffprobe_timeout(self):
        """Test running FFprobe with timeout."""
        with tempfile.NamedTemporaryFile(suffix=".mp4") as temp_file:
            temp_file.write(b"fake video content")
            temp_file.flush()
            
            enricher = FFprobeEnricher()
            
            # Mock the subprocess call to timeout
            with patch('subprocess.run') as mock_run:
                mock_run.side_effect = TimeoutError("FFprobe timed out")
                
                with pytest.raises(EnricherError):  # Should raise an error
                    enricher._run_ffprobe(Path(temp_file.name))
