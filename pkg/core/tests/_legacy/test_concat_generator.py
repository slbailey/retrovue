"""
Unit tests for concat file generator.

Tests the generation of FFmpeg concat files with alternating episode segments
and advertisements, including validation and file management.
"""

import os
import tempfile

import pytest

from retrovue.concat.generator import (
    cleanup_concat_file,
    create_episode_with_ads,
    generate_concat_file,
    read_concat_file,
    validate_concat_file,
)


class TestConcatGenerator:
    """Test concat file generation functionality."""
    
    def test_generate_concat_file_basic(self):
        """Test basic concat file generation."""
        # Create dummy files
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy segment files
            segments = []
            for i in range(3):
                segment_path = os.path.join(temp_dir, f"segment_{i+1}.mp4")
                with open(segment_path, 'w') as f:
                    f.write(f"dummy segment {i+1}")
                segments.append(segment_path)
            
            # Create dummy ad files
            ads = []
            for i in range(2):
                ad_path = os.path.join(temp_dir, f"ad_{i+1}.mp4")
                with open(ad_path, 'w') as f:
                    f.write(f"dummy ad {i+1}")
                ads.append(ad_path)
            
            # Generate concat file
            concat_path = generate_concat_file(segments, ads)
            
            try:
                # Verify file was created
                assert os.path.exists(concat_path)
                
                # Read and verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                # Should have: seg1, ad1, seg2, ad2, seg3
                expected_lines = [
                    f"file '{segments[0]}'",
                    f"file '{ads[0]}'",
                    f"file '{segments[1]}'",
                    f"file '{ads[1]}'",
                    f"file '{segments[2]}'",
                ]
                
                assert len(lines) == 5
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                # Clean up
                cleanup_concat_file(concat_path)
    
    def test_generate_concat_file_no_ads(self):
        """Test concat file generation with no ads."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy segment files
            segments = []
            for i in range(3):
                segment_path = os.path.join(temp_dir, f"segment_{i+1}.mp4")
                with open(segment_path, 'w') as f:
                    f.write(f"dummy segment {i+1}")
                segments.append(segment_path)
            
            # Generate concat file with no ads
            concat_path = generate_concat_file(segments, [])
            
            try:
                # Read and verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                # Should have only segments: seg1, seg2, seg3
                expected_lines = [
                    f"file '{segments[0]}'",
                    f"file '{segments[1]}'",
                    f"file '{segments[2]}'",
                ]
                
                assert len(lines) == 3
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                cleanup_concat_file(concat_path)
    
    def test_generate_concat_file_more_ads_than_segments(self):
        """Test concat file generation with more ads than segments."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy segment files
            segments = []
            for i in range(2):
                segment_path = os.path.join(temp_dir, f"segment_{i+1}.mp4")
                with open(segment_path, 'w') as f:
                    f.write(f"dummy segment {i+1}")
                segments.append(segment_path)
            
            # Create more ads than segments
            ads = []
            for i in range(4):
                ad_path = os.path.join(temp_dir, f"ad_{i+1}.mp4")
                with open(ad_path, 'w') as f:
                    f.write(f"dummy ad {i+1}")
                ads.append(ad_path)
            
            # Generate concat file
            concat_path = generate_concat_file(segments, ads)
            
            try:
                # Read and verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                # Should have: seg1, ad1, seg2, ad2, ad3, ad4
                expected_lines = [
                    f"file '{segments[0]}'",
                    f"file '{ads[0]}'",
                    f"file '{segments[1]}'",
                    f"file '{ads[1]}'",
                    f"file '{ads[2]}'",
                    f"file '{ads[3]}'",
                ]
                
                assert len(lines) == 6
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                cleanup_concat_file(concat_path)
    
    def test_generate_concat_file_empty_segments(self):
        """Test that empty segments list raises ValueError."""
        with pytest.raises(ValueError, match="At least one episode segment is required"):
            generate_concat_file([], ["ad1.mp4"])
    
    def test_generate_concat_file_single_segment(self):
        """Test concat file generation with single segment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create single segment
            segment_path = os.path.join(temp_dir, "segment.mp4")
            with open(segment_path, 'w') as f:
                f.write("dummy segment")
            
            # Create ads
            ads = []
            for i in range(2):
                ad_path = os.path.join(temp_dir, f"ad_{i+1}.mp4")
                with open(ad_path, 'w') as f:
                    f.write(f"dummy ad {i+1}")
                ads.append(ad_path)
            
            # Generate concat file
            concat_path = generate_concat_file([segment_path], ads)
            
            try:
                # Read and verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                # Should have: seg1, ad1, ad2
                expected_lines = [
                    f"file '{segment_path}'",
                    f"file '{ads[0]}'",
                    f"file '{ads[1]}'",
                ]
                
                assert len(lines) == 3
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                cleanup_concat_file(concat_path)


class TestConcatValidation:
    """Test concat file validation functionality."""
    
    def test_validate_concat_file_success(self):
        """Test successful concat file validation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy files
            files = []
            for i in range(3):
                file_path = os.path.join(temp_dir, f"file_{i+1}.mp4")
                with open(file_path, 'w') as f:
                    f.write(f"dummy content {i+1}")
                files.append(file_path)
            
            # Create concat file
            concat_content = '\n'.join([f"file '{path}'" for path in files])
            concat_path = os.path.join(temp_dir, "concat.txt")
            with open(concat_path, 'w') as f:
                f.write(concat_content)
            
            # Validate
            assert validate_concat_file(concat_path) is True
    
    def test_validate_concat_file_missing_file(self):
        """Test concat file validation with missing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create concat file with non-existent file
            concat_content = "file '/nonexistent/file.mp4'"
            concat_path = os.path.join(temp_dir, "concat.txt")
            with open(concat_path, 'w') as f:
                f.write(concat_content)
            
            # Validate should fail
            assert validate_concat_file(concat_path) is False
    
    def test_validate_concat_file_nonexistent(self):
        """Test concat file validation with non-existent concat file."""
        assert validate_concat_file("/nonexistent/concat.txt") is False
    
    def test_validate_concat_file_invalid_format(self):
        """Test concat file validation with invalid format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create concat file with invalid format
            concat_content = "invalid line\nfile 'test.mp4'\nanother invalid line"
            concat_path = os.path.join(temp_dir, "concat.txt")
            with open(concat_path, 'w') as f:
                f.write(concat_content)
            
            # Should still validate if the valid lines reference existing files
            # (This test doesn't create the referenced file, so it should fail)
            assert validate_concat_file(concat_path) is False


class TestConcatFileOperations:
    """Test concat file reading and cleanup operations."""
    
    def test_read_concat_file(self):
        """Test reading concat file contents."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy files
            files = []
            for i in range(3):
                file_path = os.path.join(temp_dir, f"file_{i+1}.mp4")
                with open(file_path, 'w') as f:
                    f.write(f"dummy content {i+1}")
                files.append(file_path)
            
            # Create concat file
            concat_content = '\n'.join([f"file '{path}'" for path in files])
            concat_path = os.path.join(temp_dir, "concat.txt")
            with open(concat_path, 'w') as f:
                f.write(concat_content)
            
            # Read concat file
            read_files = read_concat_file(concat_path)
            
            # Verify contents
            assert len(read_files) == 3
            for i, file_path in enumerate(files):
                assert read_files[i] == file_path
    
    def test_read_concat_file_nonexistent(self):
        """Test reading non-existent concat file."""
        with pytest.raises(FileNotFoundError):
            read_concat_file("/nonexistent/concat.txt")
    
    def test_cleanup_concat_file(self):
        """Test concat file cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create concat file
            concat_path = os.path.join(temp_dir, "concat.txt")
            with open(concat_path, 'w') as f:
                f.write("file 'test.mp4'")
            
            # Verify file exists
            assert os.path.exists(concat_path)
            
            # Clean up
            cleanup_concat_file(concat_path)
            
            # Verify file is deleted
            assert not os.path.exists(concat_path)
    
    def test_cleanup_concat_file_nonexistent(self):
        """Test cleanup of non-existent concat file."""
        # Should not raise exception
        cleanup_concat_file("/nonexistent/concat.txt")


class TestConcatIntegration:
    """Integration tests for concat file workflow."""
    
    def test_complete_workflow(self):
        """Test complete concat file workflow."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy segments
            segments = []
            for i in range(3):
                segment_path = os.path.join(temp_dir, f"segment_{i+1}.mp4")
                with open(segment_path, 'w') as f:
                    f.write(f"dummy segment {i+1}")
                segments.append(segment_path)
            
            # Create dummy ads
            ads = []
            for i in range(2):
                ad_path = os.path.join(temp_dir, f"ad_{i+1}.mp4")
                with open(ad_path, 'w') as f:
                    f.write(f"dummy ad {i+1}")
                ads.append(ad_path)
            
            # Generate concat file
            concat_path = generate_concat_file(segments, ads)
            
            try:
                # Validate concat file
                assert validate_concat_file(concat_path) is True
                
                # Read and verify order
                file_paths = read_concat_file(concat_path)
                expected_order = [
                    segments[0], ads[0], segments[1], ads[1], segments[2]
                ]
                
                assert len(file_paths) == 5
                for i, expected_path in enumerate(expected_order):
                    assert file_paths[i] == expected_path
                    
            finally:
                # Clean up
                cleanup_concat_file(concat_path)
    
    def test_create_episode_with_ads(self):
        """Test create_episode_with_ads function."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create dummy episode
            episode_path = os.path.join(temp_dir, "episode.mp4")
            with open(episode_path, 'w') as f:
                f.write("dummy episode")
            
            # Create dummy ads
            ads = []
            for i in range(2):
                ad_path = os.path.join(temp_dir, f"ad_{i+1}.mp4")
                with open(ad_path, 'w') as f:
                    f.write(f"dummy ad {i+1}")
                ads.append(ad_path)
            
            # Create episode with ads
            break_points = [300.0, 600.0]
            concat_path = create_episode_with_ads(episode_path, ads, break_points)
            
            try:
                # Should create a valid concat file
                assert os.path.exists(concat_path)
                assert validate_concat_file(concat_path) is True
                
            finally:
                cleanup_concat_file(concat_path)


class TestConcatEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_generate_concat_file_with_spaces_in_paths(self):
        """Test concat file generation with spaces in file paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with spaces in names
            segment_path = os.path.join(temp_dir, "segment with spaces.mp4")
            with open(segment_path, 'w') as f:
                f.write("dummy segment")
            
            ad_path = os.path.join(temp_dir, "ad with spaces.mp4")
            with open(ad_path, 'w') as f:
                f.write("dummy ad")
            
            # Generate concat file
            concat_path = generate_concat_file([segment_path], [ad_path])
            
            try:
                # Verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                expected_lines = [
                    f"file '{segment_path}'",
                    f"file '{ad_path}'",
                ]
                
                assert len(lines) == 2
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                cleanup_concat_file(concat_path)
    
    def test_generate_concat_file_with_special_characters(self):
        """Test concat file generation with special characters in paths."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with special characters
            segment_path = os.path.join(temp_dir, "segment[1].mp4")
            with open(segment_path, 'w') as f:
                f.write("dummy segment")
            
            ad_path = os.path.join(temp_dir, "ad(2).mp4")
            with open(ad_path, 'w') as f:
                f.write("dummy ad")
            
            # Generate concat file
            concat_path = generate_concat_file([segment_path], [ad_path])
            
            try:
                # Verify content
                with open(concat_path) as f:
                    content = f.read().strip()
                    lines = content.split('\n')
                
                expected_lines = [
                    f"file '{segment_path}'",
                    f"file '{ad_path}'",
                ]
                
                assert len(lines) == 2
                for i, expected_line in enumerate(expected_lines):
                    assert lines[i] == expected_line
                    
            finally:
                cleanup_concat_file(concat_path)
