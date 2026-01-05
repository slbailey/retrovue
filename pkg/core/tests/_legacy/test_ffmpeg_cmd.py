"""
Unit tests for FFmpeg command builder module.
"""

from retrovue.streaming.ffmpeg_cmd import build_cmd, get_cmd_summary, validate_cmd_args


class TestFFmpegCommandBuilder:
    """Test cases for FFmpeg command building."""
    
    def test_build_transcode_command_defaults(self):
        """Test building transcode command with default parameters."""
        cmd = build_cmd("/path/to/concat.txt", mode="transcode")
        
        # Check command structure
        assert cmd[0] == "ffmpeg"
        assert "-nostdin" in cmd
        assert "-hide_banner" in cmd
        assert "-nostats" in cmd
        assert "-loglevel" in cmd
        assert "error" in cmd
        
        # Check concat input
        assert "-f" in cmd
        assert "concat" in cmd
        assert "-safe" in cmd
        assert "0" in cmd
        assert "-protocol_whitelist" in cmd
        assert '"/path/to/concat.txt"' in cmd or '/path/to/concat.txt' in cmd
        
        # Check mapping
        assert "-map" in cmd
        assert "0:v:0" in cmd
        assert "0:a:0?" in cmd
        assert "-sn" in cmd
        assert "-dn" in cmd
        
        # Check video encoding
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-preset" in cmd
        assert "veryfast" in cmd
        assert "-tune" in cmd
        assert "zerolatency" in cmd
        
        # Check audio encoding
        assert "-c:a" in cmd
        assert "aac" in cmd
        assert "-b:a" in cmd
        assert "128k" in cmd
        assert "-ac" in cmd
        assert "2" in cmd
        assert "-ar" in cmd
        assert "48000" in cmd
        
        # Check TS muxing
        assert "-f" in cmd
        assert "mpegts" in cmd
        assert "-mpegts_flags" in cmd
        # The flags are combined in one argument
        mpegts_flags_idx = cmd.index("-mpegts_flags")
        mpegts_flags_value = cmd[mpegts_flags_idx + 1]
        assert "+initial_discontinuity" in mpegts_flags_value
        assert "+resend_headers" in mpegts_flags_value
        assert "pipe:1" in cmd
    
    def test_build_copy_command(self):
        """Test building copy command."""
        cmd = build_cmd("/path/to/concat.txt", mode="copy")
        
        # Should have copy codecs
        assert "-c:v" in cmd
        assert "copy" in cmd
        assert "-c:a" in cmd
        assert "copy" in cmd
        
        # Should have bitstream filter for H.264
        assert "-bsf:v" in cmd
        assert "h264_mp4toannexb" in cmd
        
        # Should NOT have transcoding parameters
        assert "libx264" not in cmd
        assert "-preset" not in cmd
        assert "-tune" not in cmd
        assert "aac" not in cmd
    
    def test_custom_parameters(self):
        """Test building command with custom parameters."""
        cmd = build_cmd(
            "/custom/concat.txt",
            mode="transcode",
            video_preset="fast",
            gop=120,
            audio_bitrate="256k",
            audio_rate=44100,
            stereo=False,
            probe_size="5M",
            analyze_duration="1M"
        )
        
        # Check custom video settings
        assert "fast" in cmd  # preset
        assert "120" in cmd   # gop
        
        # Check custom audio settings
        assert "256k" in cmd  # bitrate
        assert "44100" in cmd  # sample rate
        assert "1" in cmd     # mono (not stereo)
        
        # Check custom probe settings
        assert "5M" in cmd    # probe_size
        assert "1M" in cmd    # analyze_duration
    
    def test_stereo_parameter(self):
        """Test stereo parameter affects audio channels."""
        cmd_stereo = build_cmd("/path/concat.txt", stereo=True)
        cmd_mono = build_cmd("/path/concat.txt", stereo=False)
        
        # Find audio channel settings
        stereo_idx = cmd_stereo.index("-ac")
        mono_idx = cmd_mono.index("-ac")
        
        assert cmd_stereo[stereo_idx + 1] == "2"
        assert cmd_mono[mono_idx + 1] == "1"
    
    def test_command_validation(self):
        """Test command validation function."""
        cmd = build_cmd("/test/concat.txt", mode="transcode")
        validation = validate_cmd_args(cmd)
        
        # Should have all required components
        assert validation["has_global_flags"]
        assert validation["has_concat_input"]
        assert validation["has_protocol_whitelist"]
        assert validation["has_mapping"]
        assert validation["has_ts_mux"]
        assert validation["has_initial_discontinuity"]
        assert validation["has_resend_headers"]
        assert validation["outputs_to_stdout"]
        
        # Should not have MP4-specific flags
        assert not validation["has_mp4_flags"]
        
        # Should have transcoding flags
        assert validation["has_transcode_video"]
        assert validation["has_audio_encoding"]
        assert not validation["has_copy_video"]
        assert not validation["has_audio_copy"]
    
    def test_copy_command_validation(self):
        """Test validation for copy mode command."""
        cmd = build_cmd("/test/concat.txt", mode="copy")
        validation = validate_cmd_args(cmd)
        
        # Should have copy flags
        assert validation["has_copy_video"]
        assert validation["has_audio_copy"]
        assert validation["has_bsf_filter"]
        
        # Should not have transcoding flags
        assert not validation["has_transcode_video"]
        assert not validation["has_audio_encoding"]
    
    def test_no_mp4_flags(self):
        """Test that MP4-specific flags are excluded."""
        cmd = build_cmd("/test/concat.txt")
        cmd_str = " ".join(cmd)
        
        # Should not contain MP4-specific flags
        assert "-movflags" not in cmd_str
        assert "+faststart" not in cmd_str
        assert "mp4" not in cmd_str.lower()
    
    def test_argument_order(self):
        """Test that arguments appear in correct order."""
        cmd = build_cmd("/test/concat.txt", mode="transcode")
        
        # Global flags should come first
        assert cmd.index("-nostdin") < cmd.index("-f")
        
        # Input should come before mapping
        input_idx = cmd.index("-i")
        mapping_idx = cmd.index("-map")
        assert input_idx < mapping_idx
        
        # Mapping should come before codec settings
        codec_idx = cmd.index("-c:v")
        assert mapping_idx < codec_idx
        
        # Output format should come last (before pipe:1)
        mpegts_idx = cmd.index("mpegts")
        pipe_idx = cmd.index("pipe:1")
        assert mpegts_idx < pipe_idx
    
    def test_concat_path_quoting(self):
        """Test that concat path is handled correctly (no longer quoted)."""
        cmd = build_cmd("/path with spaces/concat.txt")
        
        # Find the input argument
        input_idx = cmd.index("-i")
        input_path = cmd[input_idx + 1]
        
        # Should not be quoted (we removed quoting to fix FFmpeg issues)
        assert not input_path.startswith('"')
        assert not input_path.endswith('"')
        assert input_path == "/path with spaces/concat.txt"
    
    def test_get_cmd_summary(self):
        """Test command summary generation."""
        cmd = build_cmd("/test/concat.txt", mode="transcode")
        summary = get_cmd_summary(cmd)
        
        assert "FFmpeg transcode command" in summary
        assert "libx264" in summary
        assert "aac" in summary
        assert "/test/concat.txt" in summary
    
    def test_copy_mode_summary(self):
        """Test summary for copy mode."""
        cmd = build_cmd("/test/concat.txt", mode="copy")
        summary = get_cmd_summary(cmd)
        
        assert "FFmpeg copy command" in summary
        assert "copy" in summary
    
    def test_invalid_mode_handling(self):
        """Test that invalid mode is handled gracefully."""
        # The function uses Literal type hints but doesn't validate at runtime
        # This test documents the current behavior
        cmd = build_cmd("/test/concat.txt", mode="invalid_mode")  # type: ignore
        # Should still produce a command, but it may not work as expected
        assert cmd[0] == "ffmpeg"
    
    def test_edge_case_parameters(self):
        """Test edge case parameter values."""
        # Very small GOP
        cmd = build_cmd("/test/concat.txt", gop=1)
        assert "1" in cmd
        
        # High bitrate
        cmd = build_cmd("/test/concat.txt", audio_bitrate="512k")
        assert "512k" in cmd
        
        # High sample rate
        cmd = build_cmd("/test/concat.txt", audio_rate=96000)
        assert "96000" in cmd
    
    def test_probe_size_variations(self):
        """Test different probe size formats."""
        sizes = ["1M", "10M", "100M", "1G"]
        for size in sizes:
            cmd = build_cmd("/test/concat.txt", probe_size=size)
            assert size in cmd
    
    def test_analyze_duration_variations(self):
        """Test different analyze duration formats."""
        durations = ["1M", "2M", "5M", "10M"]
        for duration in durations:
            cmd = build_cmd("/test/concat.txt", analyze_duration=duration)
            assert duration in cmd
    
    def test_audio_optional_default_behavior(self):
        """Test that audio_optional=True is the default behavior."""
        cmd = build_cmd("/test/concat.txt")
        
        # Should have optional audio mapping
        assert "-map" in cmd and "0:a:0?" in cmd
        assert not ("-map" in cmd and "0:a:0" in cmd and "0:a:0?" not in cmd)
    
    def test_audio_optional_explicit(self):
        """Test explicit audio_optional=True behavior."""
        cmd = build_cmd("/test/concat.txt", audio_optional=True, audio_required=False)
        
        # Should have optional audio mapping
        assert "-map" in cmd and "0:a:0?" in cmd
        assert not ("-map" in cmd and "0:a:0" in cmd and "0:a:0?" not in cmd)
    
    def test_audio_required_behavior(self):
        """Test audio_required=True behavior."""
        cmd = build_cmd("/test/concat.txt", audio_required=True)
        
        # Should have required audio mapping
        assert "-map" in cmd and "0:a:0" in cmd
        assert not ("-map" in cmd and "0:a:0?" in cmd and "0:a:0" not in cmd)
    
    def test_audio_required_overrides_optional(self):
        """Test that audio_required=True overrides audio_optional=True."""
        cmd = build_cmd("/test/concat.txt", audio_optional=True, audio_required=True)
        
        # Should have required audio mapping (audio_required takes precedence)
        assert "-map" in cmd and "0:a:0" in cmd
        assert not ("-map" in cmd and "0:a:0?" in cmd and "0:a:0" not in cmd)
    
    def test_no_audio_mapping_when_both_false(self):
        """Test behavior when both audio_optional and audio_required are False."""
        cmd = build_cmd("/test/concat.txt", audio_optional=False, audio_required=False)
        
        # Should not have any audio mapping
        assert not ("-map" in cmd and "0:a:0?" in cmd)
        assert not ("-map" in cmd and "0:a:0" in cmd)
        # But should still have video mapping
        assert "-map" in cmd and "0:v:0" in cmd
    
    def test_audio_mapping_with_different_modes(self):
        """Test audio mapping works with both transcode and copy modes."""
        # Test transcode mode
        transcode_cmd = build_cmd("/test/concat.txt", mode="transcode", audio_required=True)
        assert "-map" in transcode_cmd and "0:a:0" in transcode_cmd
        assert "libx264" in transcode_cmd
        
        # Test copy mode
        copy_cmd = build_cmd("/test/concat.txt", mode="copy", audio_required=True)
        assert "-map" in copy_cmd and "0:a:0" in copy_cmd
        assert "-c:v" in copy_cmd and "copy" in copy_cmd
    
    def test_audio_mapping_validation(self):
        """Test validation function with new audio mapping options."""
        # Test optional audio
        cmd_optional = build_cmd("/test/concat.txt", audio_optional=True, audio_required=False)
        validation_optional = validate_cmd_args(cmd_optional)
        assert validation_optional["has_optional_audio"]
        assert not validation_optional["has_required_audio"]
        
        # Test required audio
        cmd_required = build_cmd("/test/concat.txt", audio_required=True)
        validation_required = validate_cmd_args(cmd_required)
        assert validation_required["has_required_audio"]
        assert not validation_required["has_optional_audio"]
        
        # Test no audio
        cmd_no_audio = build_cmd("/test/concat.txt", audio_optional=False, audio_required=False)
        validation_no_audio = validate_cmd_args(cmd_no_audio)
        assert not validation_no_audio["has_optional_audio"]
        assert not validation_no_audio["has_required_audio"]
    
    def test_audio_mapping_parameter_combinations(self):
        """Test various combinations of audio mapping parameters."""
        # Default behavior (audio_optional=True, audio_required=False)
        cmd1 = build_cmd("/test/concat.txt")
        assert "-map" in cmd1 and "0:a:0?" in cmd1
        
        # Explicit optional
        cmd2 = build_cmd("/test/concat.txt", audio_optional=True, audio_required=False)
        assert "-map" in cmd2 and "0:a:0?" in cmd2
        
        # Required overrides optional
        cmd3 = build_cmd("/test/concat.txt", audio_optional=True, audio_required=True)
        assert "-map" in cmd3 and "0:a:0" in cmd3
        assert not ("-map" in cmd3 and "0:a:0?" in cmd3 and "0:a:0" not in cmd3)
        
        # No audio at all
        cmd4 = build_cmd("/test/concat.txt", audio_optional=False, audio_required=False)
        assert not ("-map" in cmd4 and "0:a:0?" in cmd4)
        assert not ("-map" in cmd4 and "0:a:0" in cmd4)


class TestFFmpegCommandIntegration:
    """Integration tests for FFmpeg command building."""
    
    def test_transcode_vs_copy_differences(self):
        """Test that transcode and copy modes produce different commands."""
        transcode_cmd = build_cmd("/test/concat.txt", mode="transcode")
        copy_cmd = build_cmd("/test/concat.txt", mode="copy")
        
        # Should be different
        assert transcode_cmd != copy_cmd
        
        # Transcode should have libx264, copy should not
        assert "libx264" in " ".join(transcode_cmd)
        assert "libx264" not in " ".join(copy_cmd)
        
        # Copy should have copy codecs, transcode should not
        assert "-c:v copy" in " ".join(copy_cmd)
        assert "-c:v copy" not in " ".join(transcode_cmd)
    
    def test_consistent_global_flags(self):
        """Test that global flags are consistent across modes."""
        transcode_cmd = build_cmd("/test/concat.txt", mode="transcode")
        copy_cmd = build_cmd("/test/concat.txt", mode="copy")
        
        # Both should have same global flags
        global_flags = ["-nostdin", "-hide_banner", "-nostats", "-loglevel", "error"]
        for flag in global_flags:
            assert flag in transcode_cmd
            assert flag in copy_cmd
    
    def test_consistent_output_format(self):
        """Test that output format is consistent across modes."""
        transcode_cmd = build_cmd("/test/concat.txt", mode="transcode")
        copy_cmd = build_cmd("/test/concat.txt", mode="copy")
        
        # Both should output MPEG-TS to stdout
        assert "mpegts" in " ".join(transcode_cmd)
        assert "mpegts" in " ".join(copy_cmd)
        assert "pipe:1" in transcode_cmd
        assert "pipe:1" in copy_cmd
    
    def test_audio_mapping_consistency_across_modes(self):
        """Test that audio mapping is consistent across transcode and copy modes."""
        # Test optional audio
        transcode_optional = build_cmd("/test/concat.txt", mode="transcode", audio_optional=True)
        copy_optional = build_cmd("/test/concat.txt", mode="copy", audio_optional=True)
        
        assert "-map" in transcode_optional and "0:a:0?" in transcode_optional
        assert "-map" in copy_optional and "0:a:0?" in copy_optional
        
        # Test required audio
        transcode_required = build_cmd("/test/concat.txt", mode="transcode", audio_required=True)
        copy_required = build_cmd("/test/concat.txt", mode="copy", audio_required=True)
        
        assert "-map" in transcode_required and "0:a:0" in transcode_required
        assert "-map" in copy_required and "0:a:0" in copy_required
    
    def test_audio_mapping_with_custom_parameters(self):
        """Test audio mapping works with custom audio parameters."""
        cmd = build_cmd(
            "/test/concat.txt",
            mode="transcode",
            audio_required=True,
            audio_bitrate="256k",
            audio_rate=44100,
            stereo=False
        )
        
        # Should have required audio mapping
        assert "-map" in cmd and "0:a:0" in cmd
        assert not ("-map" in cmd and "0:a:0?" in cmd and "0:a:0" not in cmd)
        
        # Should have custom audio settings
        assert "256k" in cmd
        assert "44100" in cmd
        assert "1" in cmd  # mono (not stereo)
    
    def test_audio_mapping_edge_cases(self):
        """Test edge cases for audio mapping parameters."""
        # Test that both False results in no audio mapping
        cmd_no_audio = build_cmd("/test/concat.txt", audio_optional=False, audio_required=False)
        assert not ("-map" in cmd_no_audio and "0:a:0?" in cmd_no_audio)
        assert not ("-map" in cmd_no_audio and "0:a:0" in cmd_no_audio)
        assert "-map" in cmd_no_audio and "0:v:0" in cmd_no_audio  # Video should still be mapped
        
        # Test that required takes precedence over optional
        cmd_override = build_cmd("/test/concat.txt", audio_optional=True, audio_required=True)
        assert "-map" in cmd_override and "0:a:0" in cmd_override
        assert not ("-map" in cmd_override and "0:a:0?" in cmd_override and "0:a:0" not in cmd_override)
