"""
HLS Writer - Converts MPEG-TS stream to HLS segments.

Takes TS data from the existing ChannelStream fanout and remuxes to HLS
via an FFmpeg subprocess. Writes segments to /tmp/retrovue-hls/{channel_id}/.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HLS_BASE_DIR = Path("/tmp/retrovue-hls")


class HLSWriter:
    """Manages an FFmpeg process that remuxes piped MPEG-TS input to HLS output."""

    def __init__(self, channel_id: str):
        self.channel_id = channel_id
        self.output_dir = HLS_BASE_DIR / channel_id
        self._proc: Optional[subprocess.Popen] = None
        self._running = False
        self._lock = threading.Lock()
        self._restart_count = 0
        self._max_restarts = 10
        self._feed_thread: Optional[threading.Thread] = None

    @property
    def playlist_path(self) -> Path:
        return self.output_dir / "live.m3u8"

    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        """Start the HLS FFmpeg process. Feed data via write()."""
        with self._lock:
            if self._running:
                return
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._start_ffmpeg()
            self._running = True
            logger.info("[HLS %s] Writer started, output: %s", self.channel_id, self.output_dir)

    def _start_ffmpeg(self) -> None:
        """Launch the FFmpeg remux process."""
        cmd = [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel", "warning",
            "-fflags", "+genpts+discardcorrupt",
            "-f", "mpegts",
            "-i", "pipe:0",
            "-c:v", "copy",
            "-c:a", "copy",
            "-f", "hls",
            "-hls_time", "6",
            "-hls_list_size", "5",
            "-hls_flags", "delete_segments+append_list+omit_endlist",
            "-hls_segment_filename", str(self.output_dir / "seg_%05d.ts"),
            str(self.playlist_path),
        ]
        logger.info("[HLS %s] Starting FFmpeg: %s", self.channel_id, " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        # Monitor stderr in background
        t = threading.Thread(target=self._drain_stderr, daemon=True)
        t.start()

    def _drain_stderr(self) -> None:
        """Read FFmpeg stderr and log warnings/errors."""
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            for line in proc.stderr:
                msg = line.decode("utf-8", errors="replace").strip()
                if msg:
                    logger.warning("[HLS %s] FFmpeg: %s", self.channel_id, msg)
        except Exception:
            pass

    def write(self, data: bytes) -> bool:
        """Write TS data to FFmpeg stdin. Returns False if process died."""
        if not self._running:
            return False
        proc = self._proc
        if proc is None or proc.poll() is not None:
            # Process died, try restart
            return self._try_restart_and_write(data)
        try:
            proc.stdin.write(data)
            proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            logger.warning("[HLS %s] Broken pipe, attempting restart", self.channel_id)
            return self._try_restart_and_write(data)

    def _try_restart_and_write(self, data: bytes) -> bool:
        with self._lock:
            if self._restart_count >= self._max_restarts:
                logger.error("[HLS %s] Max restarts reached, giving up", self.channel_id)
                self._running = False
                return False
            self._restart_count += 1
            logger.info("[HLS %s] Restarting FFmpeg (attempt %d)", self.channel_id, self._restart_count)
            self._kill_proc()
            self._start_ffmpeg()
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
            return True
        except Exception:
            return False

    def _kill_proc(self) -> None:
        proc = self._proc
        if proc:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None

    def stop(self) -> None:
        """Stop the HLS writer and clean up."""
        self._running = False
        with self._lock:
            self._kill_proc()
        # Clean up segments
        try:
            if self.output_dir.exists():
                shutil.rmtree(self.output_dir, ignore_errors=True)
        except Exception as e:
            logger.warning("[HLS %s] Cleanup error: %s", self.channel_id, e)
        logger.info("[HLS %s] Writer stopped", self.channel_id)


class HLSManager:
    """
    Manages HLS writers for all channels.
    
    Integrates with ProgramDirector's fanout system to tap into existing
    TS streams and remux them to HLS.
    """

    def __init__(self):
        self._writers: dict[str, HLSWriter] = {}
        self._feed_threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def get_writer(self, channel_id: str) -> HLSWriter:
        """Get or create an HLS writer for a channel."""
        with self._lock:
            if channel_id not in self._writers:
                writer = HLSWriter(channel_id)
                self._writers[channel_id] = writer
            return self._writers[channel_id]

    def start_feeding(self, channel_id: str, fanout, session_id: str) -> HLSWriter:
        """
        Start feeding TS data from a fanout buffer subscription to the HLS writer.
        
        Args:
            channel_id: Channel ID
            fanout: ChannelStream fanout buffer
            session_id: Session ID for the subscription
        """
        writer = self.get_writer(channel_id)
        if not writer.is_running():
            writer.start()

        with self._lock:
            if channel_id in self._feed_threads and self._feed_threads[channel_id].is_alive():
                return writer

        client_queue = fanout.subscribe(session_id)

        def feed_loop():
            logger.info("[HLS %s] Feed thread started", channel_id)
            try:
                while writer._running:
                    try:
                        chunk = client_queue.get(timeout=2.0)
                        if chunk is None:
                            break
                        if not writer.write(chunk):
                            break
                    except Exception:
                        # queue.Empty timeout - continue
                        continue
            except Exception as e:
                logger.error("[HLS %s] Feed thread error: %s", channel_id, e)
            finally:
                logger.info("[HLS %s] Feed thread stopped", channel_id)
                fanout.unsubscribe(session_id)

        t = threading.Thread(target=feed_loop, name=f"hls-feed-{channel_id}", daemon=True)
        t.start()
        with self._lock:
            self._feed_threads[channel_id] = t

        return writer

    def stop_channel(self, channel_id: str) -> None:
        """Stop HLS writer for a channel."""
        with self._lock:
            writer = self._writers.pop(channel_id, None)
            self._feed_threads.pop(channel_id, None)
        if writer:
            writer.stop()

    def stop_all(self) -> None:
        """Stop all HLS writers."""
        with self._lock:
            writers = list(self._writers.values())
            self._writers.clear()
            self._feed_threads.clear()
        for w in writers:
            w.stop()
