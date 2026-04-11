"""Tests for copy mode validation."""

import pytest
from src.retrovue.validation.copy_mode import CopyModeUnsupportedError, can_copy, validate_copy_mode


class TestCanCopy:
    """Test cases for the can_copy function."""
    
    def test_h264_aac_supported(self):
        """Test that H.264 + AAC is supported."""
        assert can_copy("h264", "aac") is True
        assert can_copy("H.264", "AAC") is True
        assert can_copy("avc", "aac") is True
        assert can_copy("x264", "aac") is True
    
    def test_h264_mp2_supported(self):
        """Test that H.264 + MP2 is supported."""
        assert can_copy("h264", "mp2") is True
        assert can_copy("H.264", "MP2") is True
        assert can_copy("avc", "mp2") is True
    
    def test_h265_not_supported(self):
        """Test that H.265 is not supported for copy mode."""
        assert can_copy("h265", "aac") is False
        assert can_copy("hevc", "aac") is False
        assert can_copy("H.265", "AAC") is False
        assert can_copy("h265", "mp2") is False
    
    def test_opus_not_supported(self):
        """Test that Opus audio is not supported for copy mode."""
        assert can_copy("h264", "opus") is False
        assert can_copy("h264", "Opus") is False
        assert can_copy("avc", "opus") is False
    
    def test_mp3_not_supported(self):
        """Test that MP3 audio is not supported for copy mode."""
        assert can_copy("h264", "mp3") is False
        assert can_copy("h264", "MP3") is False
        assert can_copy("avc", "mp3") is False
    
    def test_vp9_not_supported(self):
        """Test that VP9 video is not supported for copy mode."""
        assert can_copy("vp9", "aac") is False
        assert can_copy("VP9", "AAC") is False
        assert can_copy("vp9", "mp2") is False
    
    def test_av1_not_supported(self):
        """Test that AV1 video is not supported for copy mode."""
        assert can_copy("av1", "aac") is False
        assert can_copy("AV1", "AAC") is False
        assert can_copy("av1", "mp2") is False
    
    def test_unsupported_audio_codecs(self):
        """Test various unsupported audio codecs."""
        unsupported_audio = [
            "ac3", "eac3", "dts", "flac", "pcm", "wav", "ogg", "vorbis"
        ]
        
        for audio_codec in unsupported_audio:
            assert can_copy("h264", audio_codec) is False, f"Expected {audio_codec} to be unsupported"
    
    def test_unsupported_video_codecs(self):
        """Test various unsupported video codecs."""
        unsupported_video = [
            "mpeg2video", "mpeg4", "divx", "xvid", "wmv", "vc1", "prores"
        ]
        
        for video_codec in unsupported_video:
            assert can_copy(video_codec, "aac") is False, f"Expected {video_codec} to be unsupported"
    
    def test_case_insensitive(self):
        """Test that codec names are case insensitive."""
        assert can_copy("H264", "AAC") is True
        assert can_copy("h.264", "aac") is True
        assert can_copy("AVC", "MP2") is True
    
    def test_whitespace_handling(self):
        """Test that whitespace is handled correctly."""
        assert can_copy(" h264 ", " aac ") is True
        assert can_copy("\th264\t", "\taac\t") is True
        assert can_copy("h264\n", "aac\n") is True


class TestValidateCopyMode:
    """Test cases for the validate_copy_mode function."""
    
    def test_valid_h264_aac_passes(self):
        """Test that valid H.264 + AAC passes validation."""
        # Should not raise any exception
        validate_copy_mode("h264", "aac")
        validate_copy_mode("H.264", "AAC")
        validate_copy_mode("avc", "aac")
    
    def test_valid_h264_mp2_passes(self):
        """Test that valid H.264 + MP2 passes validation."""
        # Should not raise any exception
        validate_copy_mode("h264", "mp2")
        validate_copy_mode("H.264", "MP2")
        validate_copy_mode("avc", "mp2")
    
    def test_h265_raises_exception(self):
        """Test that H.265 raises CopyModeUnsupportedError."""
        with pytest.raises(CopyModeUnsupportedError) as exc_info:
            validate_copy_mode("h265", "aac")
        
        assert "Copy mode unsupported" in str(exc_info.value)
        assert "requires H.264 Annex-B + AAC/MP2" in str(exc_info.value)
        assert "h265" in str(exc_info.value)
        assert "aac" in str(exc_info.value)
    
    def test_opus_raises_exception(self):
        """Test that Opus audio raises CopyModeUnsupportedError."""
        with pytest.raises(CopyModeUnsupportedError) as exc_info:
            validate_copy_mode("h264", "opus")
        
        assert "Copy mode unsupported" in str(exc_info.value)
        assert "h264" in str(exc_info.value)
        assert "opus" in str(exc_info.value)
    
    def test_mp3_raises_exception(self):
        """Test that MP3 audio raises CopyModeUnsupportedError."""
        with pytest.raises(CopyModeUnsupportedError) as exc_info:
            validate_copy_mode("h264", "mp3")
        
        assert "Copy mode unsupported" in str(exc_info.value)
        assert "h264" in str(exc_info.value)
        assert "mp3" in str(exc_info.value)
    
    def test_vp9_raises_exception(self):
        """Test that VP9 video raises CopyModeUnsupportedError."""
        with pytest.raises(CopyModeUnsupportedError) as exc_info:
            validate_copy_mode("vp9", "aac")
        
        assert "Copy mode unsupported" in str(exc_info.value)
        assert "vp9" in str(exc_info.value)
        assert "aac" in str(exc_info.value)
    
    def test_hevc_opus_raises_exception(self):
        """Test that HEVC + Opus raises CopyModeUnsupportedError."""
        with pytest.raises(CopyModeUnsupportedError) as exc_info:
            validate_copy_mode("hevc", "opus")
        
        assert "Copy mode unsupported" in str(exc_info.value)
        assert "hevc" in str(exc_info.value)
        assert "opus" in str(exc_info.value)


class TestCopyModeUnsupportedError:
    """Test cases for the CopyModeUnsupportedError exception."""
    
    def test_exception_attributes(self):
        """Test that exception stores codec information correctly."""
        try:
            validate_copy_mode("h265", "opus")
        except CopyModeUnsupportedError as e:
            assert e.video_codec == "h265"
            assert e.audio_codec == "opus"
    
    def test_exception_message_format(self):
        """Test that exception message is properly formatted."""
        try:
            validate_copy_mode("vp9", "mp3")
        except CopyModeUnsupportedError as e:
            message = str(e)
            assert "Copy mode unsupported" in message
            assert "requires H.264 Annex-B + AAC/MP2" in message
            assert "got vp9 + mp3" in message
    
    def test_exception_inheritance(self):
        """Test that exception inherits from Exception."""
        error = CopyModeUnsupportedError("test_video", "test_audio")
        assert isinstance(error, Exception)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_strings(self):
        """Test behavior with empty strings."""
        assert can_copy("", "aac") is False
        assert can_copy("h264", "") is False
        assert can_copy("", "") is False
    
    def test_none_values(self):
        """Test behavior with None values."""
        with pytest.raises(AttributeError):
            can_copy(None, "aac")
        
        with pytest.raises(AttributeError):
            can_copy("h264", None)
    
    def test_very_long_strings(self):
        """Test behavior with very long codec names."""
        long_video = "h264" + "x" * 1000
        long_audio = "aac" + "y" * 1000
        
        assert can_copy(long_video, "aac") is False  # Should fail due to extra characters
        assert can_copy("h264", long_audio) is False  # Should fail for audio
    
    def test_special_characters(self):
        """Test behavior with special characters in codec names."""
        assert can_copy("h264!", "aac") is False
        assert can_copy("h264@", "aac") is False
        assert can_copy("h264#", "aac") is False
        assert can_copy("h264$", "aac") is False
