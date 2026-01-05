"""
Unit tests for low latency streaming presets.
"""

from src.retrovue.presets.low_latency import apply_low_latency_audio, apply_low_latency_video


class TestLowLatencyVideo:
    """Test cases for apply_low_latency_video function."""
    
    def test_apply_low_latency_video_basic(self):
        """Test basic low latency video settings are applied."""
        args = ["ffmpeg", "-i", "input.mp4", "-c:v", "libx264"]
        gop = 30
        
        result = apply_low_latency_video(args, gop)
        
        # Check that all required low latency flags are present
        assert "-tune" in result
        assert "zerolatency" in result
        assert "-bf" in result
        assert "0" in result
        assert "-flags" in result
        assert "cgop" in result
        assert "-g" in result
        assert str(gop) in result
        assert "-keyint_min" in result
        assert "-sc_threshold" in result
        assert "0" in result
    
    def test_apply_low_latency_video_gop_values(self):
        """Test different GOP values are correctly applied."""
        args = ["ffmpeg", "-i", "input.mp4"]
        
        # Test with GOP = 60
        result_60 = apply_low_latency_video(args, 60)
        assert "-g" in result_60
        assert "60" in result_60
        assert "-keyint_min" in result_60
        
        # Test with GOP = 15
        result_15 = apply_low_latency_video(args, 15)
        assert "-g" in result_15
        assert "15" in result_15
        assert "-keyint_min" in result_15
    
    def test_apply_low_latency_video_no_mp4_flags(self):
        """Test that no MP4-specific flags are added."""
        args = ["ffmpeg", "-i", "input.mp4"]
        result = apply_low_latency_video(args, 30)
        
        # Ensure no MP4-specific flags are present
        mp4_flags = ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]
        for flag in mp4_flags:
            assert flag not in result, f"MP4-specific flag '{flag}' should not be present"
    
    def test_apply_low_latency_video_preserves_original_args(self):
        """Test that original arguments are preserved."""
        args = ["ffmpeg", "-i", "input.mp4", "-c:v", "libx264", "-preset", "fast"]
        original_length = len(args)
        
        result = apply_low_latency_video(args, 30)
        
        # Original args should still be present
        for arg in args:
            assert arg in result, f"Original argument '{arg}' should be preserved"
        
        # Result should be longer due to added flags
        assert len(result) > original_length
    
    def test_apply_low_latency_video_empty_args(self):
        """Test with empty arguments list."""
        args = []
        result = apply_low_latency_video(args, 30)
        
        # Should still add the low latency flags
        assert "-tune" in result
        assert "zerolatency" in result
        assert "-g" in result
        assert "30" in result


class TestLowLatencyAudio:
    """Test cases for apply_low_latency_audio function."""
    
    def test_apply_low_latency_audio_basic(self):
        """Test basic low latency audio settings are applied."""
        args = ["ffmpeg", "-i", "input.mp4", "-c:a", "aac"]
        
        result = apply_low_latency_audio(args)
        
        # Check that all required low latency audio flags are present
        assert "-ar" in result
        assert "48000" in result
        assert "-ac" in result
        assert "2" in result
        assert "-b:a" in result
        assert "128k" in result
    
    def test_apply_low_latency_audio_custom_bitrate(self):
        """Test custom audio bitrate is applied."""
        args = ["ffmpeg", "-i", "input.mp4"]
        custom_bitrate = "256k"
        
        result = apply_low_latency_audio(args, custom_bitrate)
        
        assert "-b:a" in result
        assert custom_bitrate in result
        assert "-ar" in result
        assert "48000" in result
        assert "-ac" in result
        assert "2" in result
    
    def test_apply_low_latency_audio_no_mp4_flags(self):
        """Test that no MP4-specific flags are added."""
        args = ["ffmpeg", "-i", "input.mp4"]
        result = apply_low_latency_audio(args)
        
        # Ensure no MP4-specific flags are present
        mp4_flags = ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]
        for flag in mp4_flags:
            assert flag not in result, f"MP4-specific flag '{flag}' should not be present"
    
    def test_apply_low_latency_audio_preserves_original_args(self):
        """Test that original arguments are preserved."""
        args = ["ffmpeg", "-i", "input.mp4", "-c:a", "aac", "-preset", "fast"]
        original_length = len(args)
        
        result = apply_low_latency_audio(args)
        
        # Original args should still be present
        for arg in args:
            assert arg in result, f"Original argument '{arg}' should be preserved"
        
        # Result should be longer due to added flags
        assert len(result) > original_length
    
    def test_apply_low_latency_audio_empty_args(self):
        """Test with empty arguments list."""
        args = []
        result = apply_low_latency_audio(args)
        
        # Should still add the low latency audio flags
        assert "-ar" in result
        assert "48000" in result
        assert "-ac" in result
        assert "2" in result
        assert "-b:a" in result
        assert "128k" in result
    
    def test_apply_low_latency_audio_different_bitrates(self):
        """Test various audio bitrate formats."""
        args = ["ffmpeg", "-i", "input.mp4"]
        
        # Test different bitrate formats
        bitrates = ["64k", "128k", "256k", "320k", "512k"]
        
        for bitrate in bitrates:
            result = apply_low_latency_audio(args, bitrate)
            assert "-b:a" in result
            assert bitrate in result


class TestLowLatencyIntegration:
    """Integration tests for both video and audio functions."""
    
    def test_combined_video_and_audio_settings(self):
        """Test applying both video and audio low latency settings."""
        args = ["ffmpeg", "-i", "input.mp4"]
        
        # Apply video settings first
        video_result = apply_low_latency_video(args, 30)
        
        # Then apply audio settings
        final_result = apply_low_latency_audio(video_result, "256k")
        
        # Check video settings are still present
        assert "-tune" in final_result
        assert "zerolatency" in final_result
        assert "-g" in final_result
        assert "30" in final_result
        
        # Check audio settings are present
        assert "-ar" in final_result
        assert "48000" in final_result
        assert "-ac" in final_result
        assert "2" in final_result
        assert "-b:a" in final_result
        assert "256k" in final_result
    
    def test_no_mp4_specific_flags_in_combined(self):
        """Test that combined settings don't include MP4-specific flags."""
        args = ["ffmpeg", "-i", "input.mp4"]
        
        video_result = apply_low_latency_video(args, 30)
        final_result = apply_low_latency_audio(video_result, "128k")
        
        # Ensure no MP4-specific flags are present
        mp4_flags = ["-movflags", "+faststart", "-pix_fmt", "yuv420p"]
        for flag in mp4_flags:
            assert flag not in final_result, f"MP4-specific flag '{flag}' should not be present"
