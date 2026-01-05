"""
Unit tests for MPEGTSWatchdog.

Tests the watchdog's restart logic, metrics tracking, and stall detection.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from src.retrovue.streaming.watchdog import MPEGTSWatchdog


class TestMPEGTSWatchdog:
    """Test cases for MPEGTSWatchdog."""
    
    @pytest.fixture
    def watchdog(self):
        """Create a watchdog instance for testing."""
        cmd = ["ffmpeg", "-i", "input.mp4", "-f", "mpegts", "-"]
        return MPEGTSWatchdog(cmd, stall_timeout=1.0)  # Short timeout for testing
    
    @pytest.mark.asyncio
    async def test_initial_metrics(self, watchdog):
        """Test that initial metrics are correct."""
        metrics = watchdog.get_metrics()
        
        assert metrics['restart_count'] == 0
        assert metrics['last_restart_at'] is None
        assert metrics['bytes_out'] == 0
        assert metrics['backoff_delay'] == 1.0
        assert metrics['running'] is False
    
    @pytest.mark.asyncio
    async def test_reset_metrics(self, watchdog):
        """Test that metrics can be reset."""
        # Set some initial values
        watchdog.restart_count = 5
        watchdog.last_restart_at = time.time()
        watchdog.bytes_out = 1000
        watchdog._backoff_delay = 10.0
        
        # Reset and verify
        watchdog.reset_metrics()
        metrics = watchdog.get_metrics()
        
        assert metrics['restart_count'] == 0
        assert metrics['last_restart_at'] is None
        assert metrics['bytes_out'] == 0
        assert metrics['backoff_delay'] == 1.0
    
    @pytest.mark.asyncio
    async def test_successful_streaming(self, watchdog):
        """Test normal streaming without any issues."""
        # Mock the MPEGTSStreamer to return some data
        mock_chunks = [b'chunk1', b'chunk2', b'chunk3']
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = async_generator(mock_chunks)
            mock_streamer_class.return_value = mock_streamer
            
            # Collect all chunks
            chunks = []
            async for chunk in watchdog.stream():
                chunks.append(chunk)
                if len(chunks) >= 3:  # Stop after 3 chunks
                    break
            
            # Verify chunks were received
            assert chunks == mock_chunks
            assert watchdog.bytes_out == sum(len(chunk) for chunk in mock_chunks)
            assert watchdog.restart_count == 0
    
    @pytest.mark.asyncio
    async def test_stall_detection_and_restart(self, watchdog):
        """Test that stalled streams are detected and restarted."""
        # Create a stream that stalls after first chunk
        async def stalling_stream():
            yield b'initial_chunk'
            # Simulate stall by not yielding anything for a long time
            await asyncio.sleep(2.0)  # Longer than stall_timeout
            yield b'stall_recovery_chunk'
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = stalling_stream()
            mock_streamer_class.return_value = mock_streamer
            
            # Start streaming and collect chunks
            chunks = []
            start_time = time.time()
            
            try:
                async for chunk in watchdog.stream():
                    chunks.append(chunk)
                    # Stop after reasonable time to avoid infinite loop
                    if time.time() - start_time > 5.0:
                        break
            except asyncio.CancelledError:
                pass  # Expected when we cancel
            
            # Should have detected stall and attempted restart
            assert len(chunks) >= 1  # At least the initial chunk
            assert watchdog.restart_count > 0
            assert watchdog.last_restart_at is not None
    
    @pytest.mark.asyncio
    async def test_process_exit_restart(self, watchdog):
        """Test restart when FFmpeg process exits."""
        # Mock a streamer that raises an exception (simulating process exit)
        async def failing_stream():
            yield b'first_chunk'
            raise Exception("Process exited")
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = failing_stream()
            mock_streamer_class.return_value = mock_streamer
            
            # Start streaming
            chunks = []
            start_time = time.time()
            
            try:
                async for chunk in watchdog.stream():
                    chunks.append(chunk)
                    # Stop after reasonable time
                    if time.time() - start_time > 3.0:
                        break
            except asyncio.CancelledError:
                pass  # Expected when we cancel
            
            # Should have attempted restart
            assert len(chunks) >= 1  # At least the first chunk
            assert watchdog.restart_count > 0
    
    @pytest.mark.asyncio
    async def test_exponential_backoff(self, watchdog):
        """Test that backoff delay increases exponentially."""
        # Mock multiple restarts
        restart_times = []
        
        async def track_restarts():
            while True:
                await asyncio.sleep(0.1)  # Small delay
                if watchdog.restart_count > 0:
                    restart_times.append(time.time())
                if len(restart_times) >= 3:  # Track 3 restarts
                    break
        
        # Start tracking in background
        tracker_task = asyncio.create_task(track_restarts())
        
        # Mock a streamer that always fails
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = async_generator([b'chunk'])
            mock_streamer_class.return_value = mock_streamer
            
            # Override _handle_restart to track delays
            original_handle_restart = watchdog._handle_restart
            
            async def tracked_handle_restart():
                if watchdog.restart_count > 0:
                    # Check that backoff delay is increasing
                    assert watchdog._backoff_delay >= 1.0
                await original_handle_restart()
            
            watchdog._handle_restart = tracked_handle_restart
            
            try:
                # Start streaming briefly
                async for _chunk in watchdog.stream():
                    await asyncio.sleep(0.1)
                    if watchdog.restart_count >= 3:
                        break
            except asyncio.CancelledError:
                pass
        
        # Cancel tracker
        tracker_task.cancel()
        
        # Verify backoff delay increased
        assert watchdog._backoff_delay > 1.0
    
    @pytest.mark.asyncio
    async def test_max_backoff_limit(self, watchdog):
        """Test that backoff delay is capped at maximum."""
        # Set a high backoff delay
        watchdog._backoff_delay = 30.0  # Above max
        
        # Simulate a restart
        await watchdog._handle_restart()
        
        # Should be capped at max_backoff
        assert watchdog._backoff_delay == watchdog._max_backoff
    
    @pytest.mark.asyncio
    async def test_cancellation(self, watchdog):
        """Test that the watchdog can be cancelled cleanly."""
        # Mock a long-running stream
        async def long_stream():
            while True:
                yield b'chunk'
                await asyncio.sleep(0.1)
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = long_stream()
            mock_streamer_class.return_value = mock_streamer
            
            # Start streaming
            stream_task = asyncio.create_task(watchdog.stream())
            
            # Let it run briefly
            await asyncio.sleep(0.5)
            
            # Cancel it
            stream_task.cancel()
            
            # Should handle cancellation gracefully
            with pytest.raises(asyncio.CancelledError):
                await stream_task
            
            # Should be cleaned up
            assert not watchdog._running
            assert watchdog._streamer is None
    
    @pytest.mark.asyncio
    async def test_metrics_tracking(self, watchdog):
        """Test that metrics are properly tracked during operation."""
        # Mock a stream that yields some data
        mock_chunks = [b'chunk1', b'chunk2', b'chunk3']
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = async_generator(mock_chunks)
            mock_streamer_class.return_value = mock_streamer
            
            # Collect chunks
            chunks = []
            async for chunk in watchdog.stream():
                chunks.append(chunk)
                if len(chunks) >= 3:
                    break
            
            # Check metrics
            metrics = watchdog.get_metrics()
            expected_bytes = sum(len(chunk) for chunk in mock_chunks)
            
            assert metrics['bytes_out'] == expected_bytes
            assert metrics['restart_count'] == 0  # No restarts in this test
            assert metrics['running'] is False  # Should be stopped after stream ends


def async_generator(items):
    """Helper to create an async generator from a list of items."""
    async def _gen():
        for item in items:
            yield item
    return _gen()


# Integration test for dead stdout simulation
class TestDeadStdoutSimulation:
    """Test cases that simulate dead stdout scenarios."""
    
    @pytest.mark.asyncio
    async def test_dead_stdout_detection(self):
        """Test detection of dead stdout (no bytes for N seconds)."""
        watchdog = MPEGTSWatchdog(["ffmpeg", "test"], stall_timeout=0.5)
        
        # Create a stream that stops producing data
        async def dead_stdout_stream():
            yield b'initial_data'
            # Then nothing for a long time (simulating dead stdout)
            await asyncio.sleep(2.0)
            yield b'never_reached'
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = dead_stdout_stream()
            mock_streamer_class.return_value = mock_streamer
            
            # Start streaming
            chunks = []
            start_time = time.time()
            
            try:
                async for chunk in watchdog.stream():
                    chunks.append(chunk)
                    # Stop after reasonable time
                    if time.time() - start_time > 3.0:
                        break
            except asyncio.CancelledError:
                pass
            
            # Should have detected the stall and attempted restart
            assert len(chunks) == 1  # Only the initial data
            assert watchdog.restart_count > 0
            assert watchdog.last_restart_at is not None
    
    @pytest.mark.asyncio
    async def test_immediate_restart_after_stall(self):
        """Test that restart happens immediately after stall detection."""
        watchdog = MPEGTSWatchdog(["ffmpeg", "test"], stall_timeout=0.2)
        
        restart_detected = False
        
        # Track when restart happens
        original_handle_restart = watchdog._handle_restart
        
        async def tracked_handle_restart():
            nonlocal restart_detected
            restart_detected = True
            await original_handle_restart()
        
        watchdog._handle_restart = tracked_handle_restart
        
        # Create a stream that stalls quickly
        async def quick_stall_stream():
            yield b'data'
            await asyncio.sleep(1.0)  # Longer than stall_timeout
            yield b'more_data'
        
        with patch('src.retrovue.streaming.watchdog.MPEGTSStreamer') as mock_streamer_class:
            mock_streamer = AsyncMock()
            mock_streamer.stream.return_value = quick_stall_stream()
            mock_streamer_class.return_value = mock_streamer
            
            # Start streaming briefly
            start_time = time.time()
            try:
                async for _chunk in watchdog.stream():
                    if time.time() - start_time > 2.0:
                        break
            except asyncio.CancelledError:
                pass
            
            # Should have detected stall and triggered restart
            assert restart_detected
            assert watchdog.restart_count > 0
