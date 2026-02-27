#!/usr/bin/env python3
"""
Test harness for PlayoutSession - demonstrates seed/feed/execution/teardown flow.

This script:
1. Creates a mock ChannelStream to receive TS bytes
2. Starts a PlayoutSession
3. Seeds 2 blocks
4. Feeds 1 more block
5. Observes TS bytes flow
6. Stops on Ctrl+C

Usage:
    python -m retrovue.runtime.test_playout_session

Or from repo root:
    python pkg/core/src/retrovue/runtime/test_playout_session.py

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

# Add the src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from retrovue.runtime.playout_session import (
    BlockPlan,
    MockBlockPlanProvider,
    PlayoutSession,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class SimpleTsReceiver:
    """
    Simple UDS server that receives TS bytes from AIR.
    Demonstrates that bytes flow through the socket.
    """

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self.server_socket: socket.socket | None = None
        self.client_socket: socket.socket | None = None
        self.running = False
        self.bytes_received = 0
        self.chunks_received = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self):
        """Start the UDS server."""
        # Clean up existing socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Create socket directory
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Create server socket
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(str(self.socket_path))
        self.server_socket.listen(1)
        self.server_socket.settimeout(1.0)  # For clean shutdown

        self.running = True
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

        logger.info(f"[TsReceiver] Listening on {self.socket_path}")

    def _accept_loop(self):
        """Accept connections and read data."""
        while self.running:
            try:
                self.client_socket, _ = self.server_socket.accept()
                self.client_socket.settimeout(0.5)
                logger.info("[TsReceiver] Client connected")
                self._read_loop()
            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    logger.error(f"[TsReceiver] Accept error: {e}")
                break

    def _read_loop(self):
        """Read TS bytes from client."""
        while self.running and self.client_socket:
            try:
                data = self.client_socket.recv(65536)
                if not data:
                    logger.info("[TsReceiver] Client disconnected")
                    break

                with self._lock:
                    self.bytes_received += len(data)
                    self.chunks_received += 1

                # Log first few chunks and periodic progress
                if self.chunks_received <= 3:
                    # Check for TS sync byte
                    sync_ok = len(data) > 0 and data[0] == 0x47
                    logger.info(
                        f"[TsReceiver] Chunk {self.chunks_received}: "
                        f"{len(data)} bytes, sync={'OK' if sync_ok else 'MISSING'}"
                    )
                elif self.chunks_received % 100 == 0:
                    logger.info(
                        f"[TsReceiver] Progress: {self.chunks_received} chunks, "
                        f"{self.bytes_received:,} bytes"
                    )

            except socket.timeout:
                continue
            except OSError as e:
                if self.running:
                    logger.error(f"[TsReceiver] Read error: {e}")
                break

    def stop(self):
        """Stop the server."""
        self.running = False

        if self.client_socket:
            try:
                self.client_socket.close()
            except Exception:
                pass
            self.client_socket = None

        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # Clean up socket file
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception:
                pass

        logger.info(
            f"[TsReceiver] Stopped: {self.chunks_received} chunks, "
            f"{self.bytes_received:,} bytes total"
        )

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "bytes_received": self.bytes_received,
                "chunks_received": self.chunks_received,
            }


def main():
    """Run the test harness."""
    logger.info("=" * 60)
    logger.info("PlayoutSession Integration Test")
    logger.info("=" * 60)

    # Configuration
    channel_id = "test-blockplan"
    channel_id_int = 1
    socket_path = Path("/tmp/retrovue/air/test_blockplan.sock")

    program_format = {
        "video": {"width": 640, "height": 480, "frame_rate": {"num": 30, "den": 1}},
        "audio": {"sample_rate": 48000, "channels": 2},
    }

    # Signal handling for clean shutdown
    shutdown_event = threading.Event()

    def signal_handler(sig, frame):
        logger.info("\nShutdown requested...")
        shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create TS receiver
    receiver = SimpleTsReceiver(socket_path)
    receiver.start()

    # Create PlayoutSession
    from retrovue.runtime.clock import MasterClock
    session = PlayoutSession(
        channel_id=channel_id,
        channel_id_int=channel_id_int,
        ts_socket_path=socket_path,
        program_format=program_format,
        clock=MasterClock(),
        on_session_end=lambda reason: logger.info(f"Session ended: {reason}"),
    )

    # Create mock block provider
    provider = MockBlockPlanProvider(channel_id=channel_id_int)
    provider.reset(base_time_ms=0)

    try:
        # Step 1: Start session
        logger.info("\n--- Step 1: Starting AIR session ---")
        if not session.start(join_utc_ms=0):
            logger.error("Failed to start session")
            return 1

        # Step 2: Seed 2 blocks
        logger.info("\n--- Step 2: Seeding 2 blocks ---")
        blocks = provider.get_next_blocks(2)
        if len(blocks) < 2:
            logger.error("Provider didn't return 2 blocks")
            return 1

        logger.info(f"  Block A: {blocks[0].block_id} ({blocks[0].start_utc_ms}-{blocks[0].end_utc_ms}ms)")
        logger.info(f"  Block B: {blocks[1].block_id} ({blocks[1].start_utc_ms}-{blocks[1].end_utc_ms}ms)")

        if not session.seed(blocks[0], blocks[1]):
            logger.error("Failed to seed blocks")
            return 1

        # Step 3: Feed 1 more block
        logger.info("\n--- Step 3: Feeding block ---")
        next_block = provider.get_next_block()
        if next_block:
            logger.info(f"  Block C: {next_block.block_id} ({next_block.start_utc_ms}-{next_block.end_utc_ms}ms)")
            if not session.feed(next_block):
                logger.error("Failed to feed block")
                # Non-fatal, continue

        # Step 4: Wait and observe
        logger.info("\n--- Step 4: Observing TS flow (Ctrl+C to stop) ---")
        while not shutdown_event.is_set():
            time.sleep(1.0)
            stats = receiver.stats
            if stats["bytes_received"] > 0:
                logger.info(
                    f"  TS flow: {stats['chunks_received']} chunks, "
                    f"{stats['bytes_received']:,} bytes"
                )

    except Exception as e:
        logger.exception(f"Error: {e}")
        return 1

    finally:
        # Step 5: Teardown
        logger.info("\n--- Step 5: Teardown ---")
        session.stop("test_complete")
        receiver.stop()

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Test Summary")
        logger.info("=" * 60)
        stats = receiver.stats
        logger.info(f"  TS bytes received: {stats['bytes_received']:,}")
        logger.info(f"  TS chunks received: {stats['chunks_received']}")
        logger.info(f"  Blocks executed: {session.blocks_executed}")

        if stats["bytes_received"] > 0:
            logger.info("\n  RESULT: TS bytes flowed successfully!")
        else:
            logger.info("\n  RESULT: No TS bytes received (stub mode)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
