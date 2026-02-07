#!/usr/bin/env python3
"""
FIRST-ON-AIR End-to-End Verification Script.

This script verifies the complete end-to-end flow:
1. HTTP client → GET /channel/<channel_id>.ts
2. FastAPI streams actual TS bytes from AIR via BlockPlan session
3. Client receives valid MPEG-TS (0x47 sync byte)
4. Client disconnects → viewer_count goes to 0 → AIR terminates cleanly

Usage:
    # Terminal 1: Start the server
    source pkg/core/.venv/bin/activate
    python -m retrovue.runtime.verify_first_on_air --server

    # Terminal 2: Run verification
    source pkg/core/.venv/bin/activate
    python -m retrovue.runtime.verify_first_on_air --client

    # Or run with ffplay for visual verification:
    ffplay -fflags nobuffer -flags low_delay http://127.0.0.1:9999/channel/1.ts

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Add the src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("verify_first_on_air")


# =============================================================================
# Configuration
# =============================================================================

REPO_ROOT = Path("/opt/retrovue")
TEST_ASSET_A = REPO_ROOT / "assets" / "SampleA.mp4"
TEST_ASSET_B = REPO_ROOT / "assets" / "SampleB.mp4"
SERVER_HOST = "0.0.0.0"  # Bind to all interfaces
CLIENT_HOST = "127.0.0.1"  # Client connects to localhost
SERVER_PORT = 9999
CHANNEL_ID = "mock"


def run_server():
    """
    Run the ProgramDirector HTTP server.

    This starts the FastAPI server that serves /channel/{channel_id}.ts endpoints.
    Uses BlockPlanProducer for real AIR-backed playout.
    """
    import uvicorn
    from retrovue.runtime.program_director import ProgramDirector
    from retrovue.runtime.config import (
        ChannelConfig,
        ProgramFormat,
        InlineChannelConfigProvider,
    )

    logger.info("=" * 60)
    logger.info("FIRST-ON-AIR: Starting Verification Server")
    logger.info("=" * 60)

    # Create channel configuration
    program_format = ProgramFormat(
        video_width=640,
        video_height=480,
        frame_rate="30/1",
        audio_sample_rate=48000,
        audio_channels=2,
    )

    channel_config = ChannelConfig(
        channel_id=CHANNEL_ID,
        channel_id_int=1,
        name="Test Channel",
        program_format=program_format,
        schedule_source="mock",
        blockplan_only=True,  # INV-CANONICAL-BOOT: reject legacy paths
    )

    config_provider = InlineChannelConfigProvider([channel_config])

    logger.info(f"Configured channel: {CHANNEL_ID} (channel_id_int=1)")

    # Create ProgramDirector in embedded mode with mock schedule
    # This uses the internal ChannelManager registry
    director = ProgramDirector(
        channel_manager_provider=None,  # Embedded mode
        host=SERVER_HOST,
        port=SERVER_PORT,
        channel_config_provider=config_provider,
    )

    # Enable BlockPlan mode on the channel manager when it gets created
    # We do this by hooking into the manager creation
    from retrovue.runtime.channel_manager import BlockPlanProducer

    original_get_or_create = director._get_or_create_manager

    # Schedule service returning two assets for mid-asset seek verification:
    #   Block 0 (even): SampleA.mp4 from the start (offset=0)
    #   Block 1 (odd):  SampleB.mp4 starting 12 seconds in (offset=12000)
    class SimpleScheduleService:
        def get_playout_plan_now(self, channel_id: str, at_station_time):
            return [
                {
                    "asset_path": str(REPO_ROOT / "assets" / "SampleA.mp4"),
                    "asset_start_offset_ms": 0,
                    "segment_type": "content",
                },
                {
                    "asset_path": str(REPO_ROOT / "assets" / "SampleB.mp4"),
                    "asset_start_offset_ms": 12000,
                    "segment_type": "content",
                },
            ]
        def load_schedule(self, channel_id: str):
            return True, None

    simple_schedule = SimpleScheduleService()

    def get_or_create_with_blockplan(channel_id: str):
        manager = original_get_or_create(channel_id)
        # Enable BlockPlan mode if not already enabled
        if hasattr(manager, 'set_blockplan_mode') and not getattr(manager, '_blockplan_mode', False):
            manager.set_blockplan_mode(True)

            # Override schedule service to use SampleA.mp4
            manager.schedule_service = simple_schedule

            # Also need to override _build_producer_for_mode because ProgramDirector
            # overwrote it with a factory that uses Phase8AirProducer
            def build_blockplan_producer(mode: str, mgr=manager, ch_config=channel_config):
                logger.info(f"FIRST-ON-AIR: Building BlockPlanProducer for channel {channel_id}")
                return BlockPlanProducer(
                    channel_id=channel_id,
                    configuration={"block_duration_ms": 5000},  # 5 second blocks
                    channel_config=ch_config,
                    schedule_service=simple_schedule,
                    clock=mgr.clock,
                )

            manager._build_producer_for_mode = build_blockplan_producer
            logger.info(f"FIRST-ON-AIR: Enabled BlockPlan mode for channel {channel_id}")
        return manager

    director._get_or_create_manager = get_or_create_with_blockplan

    # Get the FastAPI app
    app = director.fastapi_app

    logger.info(f"Server listening on http://{SERVER_HOST}:{SERVER_PORT}")
    logger.info(f"Stream URL: http://<your-ip>:{SERVER_PORT}/channel/{CHANNEL_ID}.ts")
    logger.info("")
    logger.info("Block plan (5s blocks, round-robin):")
    logger.info(f"  Even blocks: {TEST_ASSET_A} offset=0ms")
    logger.info(f"  Odd  blocks: {TEST_ASSET_B} offset=12000ms")
    logger.info("")
    logger.info("To verify mid-asset seek with ffplay:")
    logger.info(f"  ffplay -fflags nobuffer -flags low_delay http://<your-ip>:{SERVER_PORT}/channel/{CHANNEL_ID}.ts")
    logger.info("")
    logger.info("Expected: 5s of SampleA (start) → 5s of SampleB (12s in) → repeat")
    logger.info("")
    logger.info("To verify with this script:")
    logger.info("  python -m retrovue.runtime.verify_first_on_air --client")
    logger.info("")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)

    # Run uvicorn
    uvicorn.run(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="warning",  # Reduce uvicorn noise
    )


def run_client():
    """
    Run the verification client.

    Connects to the server, receives TS bytes, verifies 0x47 sync byte,
    disconnects, and reports results.
    """
    import http.client
    import urllib.request

    logger.info("=" * 60)
    logger.info("FIRST-ON-AIR: Verification Client")
    logger.info("=" * 60)

    url = f"http://{CLIENT_HOST}:{SERVER_PORT}/channel/{CHANNEL_ID}.ts"
    logger.info(f"Connecting to: {url}")

    # Track results
    results = {
        "bytes_received": 0,
        "first_byte_is_0x47": False,
        "first_16_bytes_hex": "",
        "connect_time": 0.0,
        "first_byte_time": 0.0,
        "total_time": 0.0,
    }

    start_time = time.time()

    try:
        # Create connection
        conn = http.client.HTTPConnection(CLIENT_HOST, SERVER_PORT, timeout=30)
        conn.request("GET", f"/channel/{CHANNEL_ID}.ts")

        response = conn.getresponse()
        connect_time = time.time()
        results["connect_time"] = connect_time - start_time

        logger.info(f"Connected! Status: {response.status} {response.reason}")
        logger.info(f"Headers: {dict(response.headers)}")

        if response.status != 200:
            logger.error(f"Unexpected status code: {response.status}")
            return False

        # Read first chunk
        chunk_size = 188 * 10  # 10 TS packets
        first_chunk = response.read(chunk_size)
        first_byte_time = time.time()
        results["first_byte_time"] = first_byte_time - connect_time

        if not first_chunk:
            logger.error("No data received!")
            return False

        results["bytes_received"] = len(first_chunk)
        results["first_16_bytes_hex"] = first_chunk[:16].hex() if len(first_chunk) >= 16 else first_chunk.hex()
        results["first_byte_is_0x47"] = first_chunk[0] == 0x47

        # Log first chunk verification
        if results["first_byte_is_0x47"]:
            logger.info(f"✓ VERIFIED: First byte is 0x47 (MPEG-TS sync byte)")
        else:
            logger.error(f"✗ FAILED: First byte is 0x{first_chunk[0]:02x}, expected 0x47")

        logger.info(f"First 16 bytes: {results['first_16_bytes_hex']}")
        logger.info(f"Bytes received: {results['bytes_received']}")

        # Read more data to verify stream is flowing
        logger.info("Reading stream for 3 seconds...")
        read_until = time.time() + 3.0
        total_bytes = results["bytes_received"]

        while time.time() < read_until:
            try:
                chunk = response.read(chunk_size)
                if not chunk:
                    logger.warning("Stream ended unexpectedly")
                    break
                total_bytes += len(chunk)
            except Exception as e:
                logger.warning(f"Read error: {e}")
                break

        results["total_time"] = time.time() - start_time
        results["bytes_received"] = total_bytes

        # Close connection (this should trigger viewer_count 1→0)
        logger.info("Disconnecting (should trigger AIR termination)...")
        conn.close()

        # Give server time to clean up
        time.sleep(1.0)

        # Print summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("VERIFICATION RESULTS")
        logger.info("=" * 60)
        logger.info(f"Connect time:      {results['connect_time']*1000:.1f} ms")
        logger.info(f"First byte time:   {results['first_byte_time']*1000:.1f} ms")
        logger.info(f"Total stream time: {results['total_time']:.1f} s")
        logger.info(f"Bytes received:    {results['bytes_received']} ({results['bytes_received']/1024:.1f} KB)")
        logger.info(f"First 16 bytes:    {results['first_16_bytes_hex']}")
        logger.info(f"0x47 sync byte:    {'✓ PASS' if results['first_byte_is_0x47'] else '✗ FAIL'}")
        logger.info("=" * 60)

        if results["first_byte_is_0x47"]:
            logger.info("✓ FIRST-ON-AIR verification PASSED!")
            logger.info("")
            logger.info("Check server logs for:")
            logger.info("  - INV-VIEWER-LIFECYCLE-001: First viewer joined")
            logger.info("  - FIRST-ON-AIR: AIR connected to UDS socket")
            logger.info("  - FIRST-ON-AIR: First TS chunk verified (0x47 sync byte)")
            logger.info("  - INV-VIEWER-LIFECYCLE-002: Last viewer left")
            logger.info("  - FIRST-ON-AIR: AIR terminated cleanly")
            return True
        else:
            logger.error("✗ FIRST-ON-AIR verification FAILED!")
            return False

    except ConnectionRefusedError:
        logger.error(f"Connection refused. Is the server running on {CLIENT_HOST}:{SERVER_PORT}?")
        logger.info("Start the server first with: python -m retrovue.runtime.verify_first_on_air --server")
        return False
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(description="FIRST-ON-AIR End-to-End Verification")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--server", action="store_true", help="Run the verification server")
    group.add_argument("--client", action="store_true", help="Run the verification client")
    group.add_argument("--both", action="store_true", help="Run server in background, then client")

    args = parser.parse_args()

    if args.server:
        run_server()
    elif args.client:
        success = run_client()
        sys.exit(0 if success else 1)
    elif args.both:
        # Run server in background thread
        import multiprocessing

        server_proc = multiprocessing.Process(target=run_server)
        server_proc.start()

        # Wait for server to start
        logger.info("Waiting for server to start...")
        time.sleep(3.0)

        try:
            success = run_client()
        finally:
            # Stop server
            server_proc.terminate()
            server_proc.join(timeout=5.0)

        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
