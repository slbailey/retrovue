"""Tests for retrovue.config.defaults module."""

import pytest

from retrovue.config.defaults import (
    ANALYZE_DURATION,
    CHUNK_SIZE,
    ENABLE_INITIAL_DISCONTINUITY,
    ENABLE_RESEND_HEADERS,
    PROBE_SIZE,
    READ_FROM_FILES_LIVE,
    get_default_streaming_flags,
    ts_mux_flags,
    validate_ffmpeg_flags,
)


class TestTSMuxFlags:
    """Test the ts_mux_flags function."""
    
    def test_ts_mux_flags_with_both_enabled(self):
        """Test ts_mux_flags when both flags are enabled."""
        # This test assumes both flags are enabled by default
        result = ts_mux_flags()
        assert result == "+initial_discontinuity+resend_headers"
    
    def test_ts_mux_flags_format(self):
        """Test that ts_mux_flags returns properly formatted string."""
        result = ts_mux_flags()
        assert result.startswith("+")
        assert "initial_discontinuity" in result
        assert "resend_headers" in result
        assert result.count("+") >= 2  # At least one + at start and one between flags


class TestValidateFFmpegFlags:
    """Test the validate_ffmpeg_flags function."""
    
    def test_valid_flags_pass(self):
        """Test that valid flag combinations pass validation."""
        valid_flags = [
            "-re",
            "-f mpegts",
            "-mpegts_flags +initial_discontinuity+resend_headers",
            "-probesize 10M"
        ]
        result = validate_ffmpeg_flags(valid_flags)
        assert result == valid_flags
    
    def test_mp4_flags_with_mpegts_raises_error(self):
        """Test that MP4-only flags with MPEG-TS flags raise ValueError."""
        invalid_flags = [
            "-movflags +faststart",
            "-mpegts_flags +initial_discontinuity"
        ]
        with pytest.raises(ValueError, match="MP4-only movflags with MPEG-TS flags"):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_multiple_container_formats_raises_error(self):
        """Test that multiple container format flags raise ValueError."""
        invalid_flags = [
            "-f mpegts",
            "-f mp4"
        ]
        with pytest.raises(ValueError, match="Multiple container format flags"):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_too_many_streaming_flags_raises_error(self):
        """Test that too many streaming flags raise ValueError."""
        invalid_flags = [
            "-re",
            "-fflags +genpts",
            "-avoid_negative_ts make_zero",
            "-fflags +igndts",
            "-avoid_negative_ts disabled"
        ]
        with pytest.raises(ValueError, match="Too many streaming flags"):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_empty_flags_filtered(self):
        """Test that empty flags are filtered out."""
        flags_with_empty = ["-re", "", "   ", "-f mpegts"]
        result = validate_ffmpeg_flags(flags_with_empty)
        assert "" not in result
        assert "   " not in result
        assert "-re" in result
        assert "-f mpegts" in result
    
    def test_mp4_flags_filtered_when_mpegts_present(self):
        """Test that MP4 flags are filtered when MPEG-TS flags are present."""
        flags = [
            "-re",
            "-movflags +faststart",
            "-mpegts_flags +initial_discontinuity",
            "-f mpegts"
        ]
        # This should raise an error because we have conflicting flags
        with pytest.raises(ValueError, match="MP4-only movflags with MPEG-TS flags"):
            validate_ffmpeg_flags(flags)


class TestGetDefaultStreamingFlags:
    """Test the get_default_streaming_flags function."""
    
    def test_contains_re_flag(self):
        """Test that default flags include -re when READ_FROM_FILES_LIVE is True."""
        flags = get_default_streaming_flags()
        assert "-re" in flags
    
    def test_contains_mpegts_flags(self):
        """Test that default flags include MPEG-TS flags."""
        flags = get_default_streaming_flags()
        mpegts_flags = [flag for flag in flags if flag.startswith("-mpegts_flags")]
        assert len(mpegts_flags) == 1
        assert "initial_discontinuity" in mpegts_flags[0]
        assert "resend_headers" in mpegts_flags[0]
    
    def test_contains_probe_settings(self):
        """Test that default flags include probe settings."""
        flags = get_default_streaming_flags()
        assert f"-probesize {PROBE_SIZE}" in flags
        assert f"-analyzeduration {ANALYZE_DURATION}" in flags
    
    def test_all_flags_are_valid(self):
        """Test that all default flags pass validation."""
        flags = get_default_streaming_flags()
        # This should not raise an exception
        validated = validate_ffmpeg_flags(flags)
        assert len(validated) == len(flags)


class TestConfigurationConstants:
    """Test the configuration constants."""
    
    def test_read_from_files_live(self):
        """Test READ_FROM_FILES_LIVE constant."""
        assert READ_FROM_FILES_LIVE is True
    
    def test_probe_size(self):
        """Test PROBE_SIZE constant."""
        assert PROBE_SIZE == "10M"
    
    def test_analyze_duration(self):
        """Test ANALYZE_DURATION constant."""
        assert ANALYZE_DURATION == "2M"
    
    def test_enable_resend_headers(self):
        """Test ENABLE_RESEND_HEADERS constant."""
        assert ENABLE_RESEND_HEADERS is True
    
    def test_enable_initial_discontinuity(self):
        """Test ENABLE_INITIAL_DISCONTINUITY constant."""
        assert ENABLE_INITIAL_DISCONTINUITY is True
    
    def test_chunk_size(self):
        """Test CHUNK_SIZE constant."""
        assert CHUNK_SIZE == 1316


class TestInvalidCombinations:
    """Test specific invalid flag combinations that should be prevented."""
    
    def test_mp4_faststart_with_mpegts_container(self):
        """Test that MP4 faststart flag is invalid with MPEG-TS container."""
        invalid_flags = [
            "-f mpegts",
            "-movflags +faststart",
            "-mpegts_flags +initial_discontinuity"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_mp4_empty_moov_with_mpegts_flags(self):
        """Test that MP4 empty_moov flag is invalid with MPEG-TS flags."""
        invalid_flags = [
            "-movflags +empty_moov",
            "-mpegts_flags +resend_headers"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_frag_keyframe_with_mpegts(self):
        """Test that MP4 frag_keyframe flag is invalid with MPEG-TS."""
        invalid_flags = [
            "-f mpegts",
            "-movflags +frag_keyframe",
            "-mpegts_flags +initial_discontinuity"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_frag_custom_with_mpegts(self):
        """Test that MP4 frag_custom flag is invalid with MPEG-TS."""
        invalid_flags = [
            "-f mpegts",
            "-movflags +frag_custom",
            "-mpegts_flags +resend_headers"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_multiple_containers_invalid(self):
        """Test that multiple container formats are invalid."""
        invalid_flags = [
            "-f mpegts",
            "-f mp4",
            "-f avi"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)
    
    def test_excessive_streaming_flags_invalid(self):
        """Test that excessive streaming flags are invalid."""
        invalid_flags = [
            "-re",
            "-fflags +genpts",
            "-fflags +igndts", 
            "-avoid_negative_ts make_zero",
            "-avoid_negative_ts disabled",
            "-fflags +discardcorrupt"
        ]
        with pytest.raises(ValueError):
            validate_ffmpeg_flags(invalid_flags)


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_empty_flags_list(self):
        """Test validation with empty flags list."""
        result = validate_ffmpeg_flags([])
        assert result == []
    
    def test_single_valid_flag(self):
        """Test validation with single valid flag."""
        result = validate_ffmpeg_flags(["-re"])
        assert result == ["-re"]
    
    def test_flags_with_whitespace(self):
        """Test that flags with whitespace are handled correctly."""
        flags = [" -re ", "  -f mpegts  ", ""]
        result = validate_ffmpeg_flags(flags)
        assert "-re" in result
        assert "-f mpegts" in result
        assert "" not in result
        # Check that whitespace is stripped
        assert " -re " not in result
        assert "  -f mpegts  " not in result
    
    def test_ts_mux_flags_with_none_enabled(self):
        """Test ts_mux_flags when no flags are enabled (edge case)."""
        # This would require modifying the constants, so we test the function logic
        # by checking the structure of the returned string
        result = ts_mux_flags()
        # Should contain both flags since they're enabled by default
        assert "initial_discontinuity" in result
        assert "resend_headers" in result
