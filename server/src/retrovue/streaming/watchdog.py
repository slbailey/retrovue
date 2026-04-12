"""
Watchdog wrapper for MPEGTSStreamer with automatic restart and metrics.

Provides a robust wrapper around MPEGTSStreamer that automatically restarts
the FFmpeg process if it exits or stalls, with exponential backoff and jitter.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator

from .mpegts_stream import MPEGTSStreamer

logger = logging.getLogger(__name__)


class MPEGTSWatchdog:
    """
    Watchdog wrapper for MPEGTSStreamer with automatic restart capabilities.

    Monitors the underlying MPEGTSStreamer and automatically restarts it if:
    - The FFmpeg process exits unexpectedly
    - No bytes are received for a configurable timeout period

    Features:
    - Exponential backoff with jitter (max 20s)
    - Metrics tracking (restarts, last_restart_at, bytes_out)
    - Configurable stall timeout
    """

    def __init__(self, cmd: list[str], stall_timeout: float = 10.0):
        """
        Initialize the watchdog.

        Args:
            cmd: FFmpeg command as list of strings
            stall_timeout: Seconds to wait before considering stream stalled (default: 10.0)
        """
        self.cmd = cmd
        self.stall_timeout = stall_timeout
        self._streamer: MPEGTSStreamer | None = None
        self._running = False

        # Metrics
        self.restart_count = 0
        self.last_restart_at: float | None = None
        self.bytes_out = 0

        # Backoff state
        self._backoff_delay = 1.0  # Start with 1 second
        self._max_backoff = 20.0  # Maximum 20 seconds

    async def stream(self) -> AsyncIterator[bytes]:
        """
        Start the watched MPEG-TS stream with automatic restart.

        Yields:
            bytes: MPEG-TS video data chunks

        Raises:
            asyncio.CancelledError: When the stream is cancelled
        """
        if self._running:
            logger.warning("Watchdog stream is already running")
            return

        self._running = True

        try:
            while self._running:
                try:
                    # Create new streamer instance
                    self._streamer = MPEGTSStreamer(self.cmd)

                    logger.info(
                        f"Starting watched MPEG-TS stream (attempt #{self.restart_count + 1})"
                    )

                    # Track last byte received time
                    last_byte_time = time.time()

                    async for chunk in self._streamer.stream():
                        if not self._running:
                            break

                        # Update metrics
                        self.bytes_out += len(chunk)
                        last_byte_time = time.time()

                        yield chunk

                        # Check for stall condition
                        current_time = time.time()
                        if current_time - last_byte_time > self.stall_timeout:
                            logger.warning(f"Stream stalled for {self.stall_timeout}s, restarting")
                            break

                    # If we get here, the stream ended naturally or was stalled
                    if self._running:
                        logger.info("Stream ended, will restart")
                        await self._handle_restart()

                except asyncio.CancelledError:
                    logger.info("Watchdog stream cancelled")
                    raise
                except Exception as e:
                    logger.error(f"Stream error: {e}")
                    if self._running:
                        await self._handle_restart()

        except asyncio.CancelledError:
            logger.info("Watchdog stream cancelled during setup")
            raise
        finally:
            await self._cleanup()

    async def _handle_restart(self) -> None:
        """Handle restart with exponential backoff and jitter."""
        if not self._running:
            return

        # Update metrics
        self.restart_count += 1
        self.last_restart_at = time.time()

        # Calculate backoff delay with jitter
        jitter = random.uniform(0.1, 0.5)  # 0.1-0.5 seconds of jitter
        delay = min(self._backoff_delay + jitter, self._max_backoff)

        logger.info(
            f"Restarting in {delay:.1f}s (backoff: {self._backoff_delay:.1f}s, jitter: {jitter:.1f}s)"
        )

        # Wait for backoff period
        await asyncio.sleep(delay)

        # Exponential backoff for next time
        self._backoff_delay = min(self._backoff_delay * 2, self._max_backoff)

        # Clean up current streamer
        if self._streamer:
            await self._streamer._cleanup()
            self._streamer = None

    async def _cleanup(self) -> None:
        """Clean up the watchdog and underlying streamer."""
        self._running = False

        if self._streamer:
            try:
                await self._streamer._cleanup()
            except Exception as e:
                logger.error(f"Error cleaning up streamer: {e}")
            finally:
                self._streamer = None

    def get_metrics(self) -> dict:
        """
        Get current metrics.

        Returns:
            dict: Metrics including restart_count, last_restart_at, bytes_out
        """
        return {
            "restart_count": self.restart_count,
            "last_restart_at": self.last_restart_at,
            "bytes_out": self.bytes_out,
            "backoff_delay": self._backoff_delay,
            "running": self._running,
        }

    def reset_metrics(self) -> None:
        """Reset all metrics to initial state."""
        self.restart_count = 0
        self.last_restart_at = None
        self.bytes_out = 0
        self._backoff_delay = 1.0
