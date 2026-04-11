"""
MPEG-TS Streaming for Retrovue.

Provides continuous MPEG-TS streaming for IPTV-style live playback with support for
segment-based commercial insertion. This module uses FFmpeg concat input format to
enable seamless insertion of interstitial content (commercials) into video streams.

For detailed documentation, see docs/streaming/mpegts-streaming.md
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

from retrovue.streaming.ffmpeg_cmd import validate_input_files

logger = logging.getLogger(__name__)


class MPEGTSStreamer:
    """
    Async MPEG-TS streamer for continuous IPTV-style streaming.

    This class generates endless MPEG-TS streams that can be served
    via HTTP for IPTV clients using asyncio subprocess execution.
    """

    def __init__(self, cmd: list[str], validate_inputs: bool = True):
        """
        Initialize the MPEG-TS streamer.

        Args:
            cmd: FFmpeg command as list of strings (from retrovue.streaming.ffmpeg_cmd.build_cmd)
            validate_inputs: Whether to validate input files before streaming
        """
        self.cmd = cmd
        self.proc: asyncio.subprocess.Process | None = None
        self._running = False
        self.validate_inputs = validate_inputs

    async def stream(self) -> AsyncIterator[bytes]:
        """
        Start the MPEG-TS stream and yield video data asynchronously.

        Yields:
            bytes: MPEG-TS video data chunks in 1316-byte chunks (7×188 bytes)

        Raises:
            asyncio.CancelledError: When the stream is cancelled
        """
        if self._running:
            logger.warning("Stream is already running")
            return

        self._running = True

        try:
            logger.info(f"Starting MPEG-TS stream with command: {' '.join(self.cmd)}")

            # Validate input files if requested
            if self.validate_inputs:
                # Extract concat path from command (look for -i argument)
                concat_path = None
                for i, arg in enumerate(self.cmd):
                    if arg == "-i" and i + 1 < len(self.cmd):
                        concat_path = self.cmd[i + 1].strip("\"'")
                        break

                if concat_path:
                    # Remove any quotes that might be around the path
                    concat_path = concat_path.strip("\"'")
                    logger.info(f"Validating input files from: {concat_path}")
                    validation = validate_input_files(concat_path)

                    if not validation["valid"]:
                        error_msg = f"Input validation failed: {'; '.join(validation['errors'])}"
                        logger.error(error_msg)
                        raise ValueError(error_msg)

                    logger.info(f"Input validation passed: {validation['files_found']} files found")
                    if validation["files_missing"]:
                        logger.warning(f"Missing files: {validation['files_missing']}")
                    if validation["files_invalid"]:
                        logger.warning(f"Invalid files: {validation['files_invalid']}")
                else:
                    logger.warning("Could not extract concat path from command for validation")

            # Launch FFmpeg process with stderr capture for debugging
            self.proc = await asyncio.create_subprocess_exec(
                *self.cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,  # Capture stderr for debugging
                stdin=asyncio.subprocess.DEVNULL,  # No stdin needed
            )

            logger.info(f"FFmpeg process started with PID: {self.proc.pid}")

            # Start background tasks to monitor stderr and process health
            stderr_task = asyncio.create_task(self._monitor_stderr())
            health_task = asyncio.create_task(self._monitor_process_health())

            # Read from stdout in 1316-byte chunks (7×188 bytes)
            CHUNK_SIZE = 1316  # 7 × 188 bytes

            try:
                while self._running and self.proc and self.proc.returncode is None:
                    if not self.proc.stdout:
                        break
                    chunk = await self.proc.stdout.read(CHUNK_SIZE)
                    if not chunk:
                        # EOF reached
                        logger.warning("FFmpeg stdout reached EOF")
                        break

                    # Ensure we only yield complete chunks
                    if len(chunk) == CHUNK_SIZE:
                        yield chunk
                    elif len(chunk) > 0:
                        # Handle partial chunks at the end
                        # Pad with zeros to maintain TS packet alignment
                        padded_chunk = chunk + b"\x00" * (CHUNK_SIZE - len(chunk))
                        yield padded_chunk

            except asyncio.CancelledError:
                logger.info("Stream cancelled, terminating FFmpeg process")
                raise
            except Exception as e:
                logger.error(f"Error reading from FFmpeg stdout: {e}")
                raise
            finally:
                # Cancel monitoring tasks
                stderr_task.cancel()
                health_task.cancel()
                try:
                    await stderr_task
                except asyncio.CancelledError:
                    pass
                try:
                    await health_task
                except asyncio.CancelledError:
                    pass

                # Check if process exited with error
                if self.proc and self.proc.returncode is not None and self.proc.returncode != 0:
                    logger.error(f"FFmpeg process exited with code {self.proc.returncode}")

        except asyncio.CancelledError:
            logger.info("Stream cancelled during setup")
            raise
        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            raise
        finally:
            await self._cleanup()

    async def _monitor_stderr(self) -> None:
        """Monitor FFmpeg stderr for errors and warnings."""
        if not self.proc or not self.proc.stderr:
            return

        try:
            while self._running and self.proc and self.proc.returncode is None:
                line = await self.proc.stderr.readline()
                if not line:
                    break

                # Decode and log the stderr output
                error_msg = line.decode("utf-8", errors="replace").strip()
                if error_msg:
                    # Log errors and warnings with appropriate levels
                    if any(
                        keyword in error_msg.lower()
                        for keyword in ["error", "failed", "invalid", "corrupt"]
                    ):
                        logger.error(f"FFmpeg error: {error_msg}")
                    elif any(keyword in error_msg.lower() for keyword in ["warning", "deprecated"]):
                        logger.warning(f"FFmpeg warning: {error_msg}")
                    else:
                        logger.debug(f"FFmpeg output: {error_msg}")

        except Exception as e:
            logger.error(f"Error monitoring FFmpeg stderr: {e}")

    async def _monitor_process_health(self) -> None:
        """Monitor FFmpeg process health and log status."""
        if not self.proc:
            return

        try:
            start_time = time.time()

            while self._running and self.proc and self.proc.returncode is None:
                await asyncio.sleep(5.0)  # Check every 5 seconds

                current_time = time.time()
                uptime = current_time - start_time

                # Log periodic status
                if int(uptime) % 30 == 0:  # Every 30 seconds
                    logger.info(f"FFmpeg process running for {int(uptime)}s (PID: {self.proc.pid})")

                # Check if process is still responsive
                if self.proc.returncode is not None:
                    logger.warning(
                        f"FFmpeg process terminated unexpectedly with code {self.proc.returncode}"
                    )
                    break

        except Exception as e:
            logger.error(f"Error monitoring FFmpeg process health: {e}")

    async def _cleanup(self) -> None:
        """Clean up the FFmpeg process gracefully."""
        self._running = False

        if self.proc:
            try:
                if self.proc.returncode is None:
                    # Process is still running, terminate it
                    self.proc.terminate()

                    # Wait for graceful termination
                    try:
                        await asyncio.wait_for(self.proc.wait(), timeout=5.0)
                    except TimeoutError:
                        # Force kill if it doesn't terminate gracefully
                        logger.warning("FFmpeg process didn't terminate gracefully, force killing")
                        self.proc.kill()
                        await self.proc.wait()

            except Exception as e:
                logger.error(f"Error cleaning up FFmpeg process: {e}")
            finally:
                self.proc = None
