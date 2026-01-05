"""
Integration tests for MPEGTSWatchdog with real MPEGTSStreamer.

These tests verify that the watchdog works correctly with the actual
MPEGTSStreamer implementation.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retrovue.streaming.watchdog import MPEGTSWatchdog


class TestWatchdogIntegration:
    """Integration tests for MPEGTSWatchdog."""
    
    @pytest.mark.asyncio
    async def test_watchdog_with_test_source(self):
        """Test watchdog with FFmpeg test source (if available)."""
        # Check if ffmpeg is available
        try:
            subprocess.run(["ffmpeg", "-version"], 
                          capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("FFmpeg not available")
        
        # Create a simple test command
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "testsrc=duration=5:size=320x240:rate=1",
            "-f", "mpegts",
            "-"
        ]
        
        watchdog = MPEGTSWatchdog(cmd, stall_timeout=2.0)
        
        # Collect some chunks
        chunks = []
        start_time = asyncio.get_event_loop().time()
        
        try:
            async for chunk in watchdog.stream():
                chunks.append(chunk)
                
                # Stop after 10 seconds or 20 chunks
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > 10.0 or len(chunks) >= 20:
                    break
                    
        except asyncio.CancelledError:
            pass
        
        # Verify we got some data
        assert len(chunks) > 0
        assert watchdog.bytes_out > 0
        
        # Check metrics
        metrics = watchdog.get_metrics()
        assert metrics['bytes_out'] > 0
        assert metrics['running'] is False  # Should be stopped after stream ends
    
    @pytest.mark.asyncio
    async def test_watchdog_handles_invalid_command(self):
        """Test that watchdog handles invalid FFmpeg commands gracefully."""
        # Use an invalid command that will fail
        cmd = ["ffmpeg", "-invalid-option", "nonexistent.mp4", "-f", "mpegts", "-"]
        
        watchdog = MPEGTSWatchdog(cmd, stall_timeout=1.0)
        
        # Should handle the error and attempt restart
        chunks = []
        start_time = asyncio.get_event_loop().time()
        
        try:
            async for chunk in watchdog.stream():
                chunks.append(chunk)
                
                # Stop after 5 seconds
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > 5.0:
                    break
                    
        except asyncio.CancelledError:
            pass
        
        # Should have attempted restart due to command failure
        assert watchdog.restart_count > 0
        assert watchdog.last_restart_at is not None
    
    @pytest.mark.asyncio
    async def test_watchdog_metrics_accuracy(self):
        """Test that metrics are accurate during streaming."""
        # Check if ffmpeg is available
        try:
            subprocess.run(["ffmpeg", "-version"], 
                          capture_output=True, check=True, timeout=5)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pytest.skip("FFmpeg not available")
        
        cmd = [
            "ffmpeg",
            "-f", "lavfi", 
            "-i", "testsrc=duration=3:size=160x120:rate=1",
            "-f", "mpegts",
            "-"
        ]
        
        watchdog = MPEGTSWatchdog(cmd, stall_timeout=2.0)
        
        # Track chunks manually
        manual_bytes = 0
        chunks = []
        
        try:
            async for chunk in watchdog.stream():
                chunks.append(chunk)
                manual_bytes += len(chunk)
                
                # Stop after reasonable time
                if len(chunks) >= 10:
                    break
                    
        except asyncio.CancelledError:
            pass
        
        # Verify metrics match manual tracking
        metrics = watchdog.get_metrics()
        assert metrics['bytes_out'] == manual_bytes
        assert metrics['bytes_out'] > 0
