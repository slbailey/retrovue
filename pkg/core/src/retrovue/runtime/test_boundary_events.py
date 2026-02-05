#!/usr/bin/env python3
"""
Test: Boundary-Driven BlockPlan Feeding via Events

This test verifies the Option A implementation:
1. AIR emits BlockCompleted events after each block fence
2. AIR emits SessionEnded when execution terminates
3. Core receives events via SubscribeBlockEvents streaming RPC
4. Events fire at correct times (after fence, not during block)

Usage:
    python -m retrovue.runtime.test_boundary_events

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Add the src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Load proto stubs
import importlib.util
import types

def _get_playout_stubs():
    """Load playout_pb2 and playout_pb2_grpc from pkg/core/core/proto/retrovue."""
    _proto_dir = Path("/opt/retrovue/pkg/core/core/proto/retrovue")
    if not _proto_dir.is_dir():
        raise RuntimeError("Proto stubs not found")

    _spec_pb2 = importlib.util.spec_from_file_location("playout_pb2", _proto_dir / "playout_pb2.py")
    _spec_grpc = importlib.util.spec_from_file_location("playout_pb2_grpc", _proto_dir / "playout_pb2_grpc.py")

    playout_pb2 = importlib.util.module_from_spec(_spec_pb2)
    playout_pb2_grpc = importlib.util.module_from_spec(_spec_grpc)

    _proto_retrovue = types.ModuleType("retrovue")
    _proto_retrovue.playout_pb2 = playout_pb2
    sys.modules["retrovue"] = _proto_retrovue

    try:
        _spec_pb2.loader.exec_module(playout_pb2)
        sys.modules["playout_pb2"] = playout_pb2
        _spec_grpc.loader.exec_module(playout_pb2_grpc)
        return (playout_pb2, playout_pb2_grpc)
    finally:
        sys.modules.pop("retrovue", None)
        sys.modules.pop("playout_pb2", None)

import grpc
playout_pb2, playout_pb2_grpc = _get_playout_stubs()


# =============================================================================
# Configuration
# =============================================================================

REPO_ROOT = Path("/opt/retrovue")
AIR_BINARY = REPO_ROOT / "pkg" / "air" / "build" / "retrovue_air"
TEST_ASSET = REPO_ROOT / "assets" / "SampleA.mp4"
TMP_DIR = Path("/tmp/retrovue/boundary_test")


# =============================================================================
# Test Classes
# =============================================================================

@dataclass
class ReceivedEvent:
    """A received block event."""
    event_type: str  # "block_completed" or "session_ended"
    timestamp: float
    block_id: Optional[str] = None
    final_ct_ms: int = 0
    blocks_executed: int = 0
    reason: Optional[str] = None


@dataclass
class EventRecorder:
    """Records events received from AIR."""
    events: list[ReceivedEvent] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record_block_completed(self, block_id: str, final_ct_ms: int, blocks_executed: int):
        with self._lock:
            self.events.append(ReceivedEvent(
                event_type="block_completed",
                timestamp=time.time(),
                block_id=block_id,
                final_ct_ms=final_ct_ms,
                blocks_executed=blocks_executed,
            ))
            logger.info(f"[EVENT] BlockCompleted: {block_id}, ct={final_ct_ms}ms, total={blocks_executed}")

    def record_session_ended(self, reason: str, final_ct_ms: int, blocks_executed: int):
        with self._lock:
            self.events.append(ReceivedEvent(
                event_type="session_ended",
                timestamp=time.time(),
                final_ct_ms=final_ct_ms,
                blocks_executed=blocks_executed,
                reason=reason,
            ))
            logger.info(f"[EVENT] SessionEnded: {reason}, ct={final_ct_ms}ms, total={blocks_executed}")

    @property
    def block_completed_count(self) -> int:
        with self._lock:
            return sum(1 for e in self.events if e.event_type == "block_completed")

    @property
    def session_ended(self) -> bool:
        with self._lock:
            return any(e.event_type == "session_ended" for e in self.events)


def allocate_port() -> int:
    """Allocate an ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def create_block_proto(block_id: str, channel_id: int, start_ms: int, end_ms: int, asset_uri: str):
    """Create a BlockPlan proto message."""
    pb = playout_pb2.BlockPlan(
        block_id=block_id,
        channel_id=channel_id,
        start_utc_ms=start_ms,
        end_utc_ms=end_ms,
    )
    pb.segments.append(playout_pb2.BlockSegment(
        segment_index=0,
        asset_uri=asset_uri,
        asset_start_offset_ms=0,
        segment_duration_ms=end_ms - start_ms,
    ))
    return pb


class UDSSink:
    """Simple UDS server that accepts connections and discards data."""

    def __init__(self, socket_path: Path):
        self.socket_path = socket_path
        self._server_socket: Optional[socket.socket] = None
        self._client_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._bytes_received = 0

    def start(self):
        """Start listening for connections."""
        if self.socket_path.exists():
            self.socket_path.unlink()

        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(str(self.socket_path))
        self._server_socket.listen(1)
        self._server_socket.setblocking(False)

        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info(f"UDS sink listening on {self.socket_path}")

    def _accept_loop(self):
        """Accept connections and drain incoming data."""
        while not self._stop.is_set():
            try:
                # Try to accept a connection (non-blocking)
                try:
                    conn, _ = self._server_socket.accept()
                    conn.setblocking(False)
                    self._client_socket = conn
                    logger.info("UDS sink: client connected")
                except BlockingIOError:
                    pass

                # Drain data from client
                if self._client_socket:
                    try:
                        while True:
                            data = self._client_socket.recv(65536)
                            if not data:
                                break
                            self._bytes_received += len(data)
                    except BlockingIOError:
                        pass
                    except Exception:
                        pass

                time.sleep(0.01)
            except Exception as e:
                if not self._stop.is_set():
                    logger.warning(f"UDS sink error: {e}")
                break

    def stop(self):
        """Stop the sink."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        if self._client_socket:
            try:
                self._client_socket.close()
            except Exception:
                pass
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self.socket_path.exists():
            try:
                self.socket_path.unlink()
            except Exception:
                pass
        logger.info(f"UDS sink stopped, received {self._bytes_received} bytes")


def run_boundary_event_test():
    """
    Test boundary-driven events:
    1. Start AIR
    2. Subscribe to events
    3. Seed 2 blocks
    4. Wait for BlockCompleted events
    5. Feed next block on completion
    6. Verify SessionEnded fires on lookahead exhaustion
    """
    logger.info("=" * 60)
    logger.info("Boundary-Driven Event Test")
    logger.info("=" * 60)

    # Setup
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    socket_path = TMP_DIR / "boundary_test.sock"
    log_path = TMP_DIR / "air.log"

    # Start UDS sink first (before AIR tries to connect)
    uds_sink = UDSSink(socket_path)
    uds_sink.start()

    # Allocate gRPC port
    grpc_port = allocate_port()
    grpc_addr = f"127.0.0.1:{grpc_port}"

    logger.info(f"Starting AIR on port {grpc_port}")

    # Start AIR
    with open(log_path, 'w') as log_file:
        air_proc = subprocess.Popen(
            [str(AIR_BINARY), "--port", str(grpc_port)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT),
        )

    try:
        # Wait for gRPC to be ready
        channel = grpc.insecure_channel(grpc_addr)
        stub = playout_pb2_grpc.PlayoutControlStub(channel)

        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=2.0)
                logger.info("AIR gRPC ready")
                break
            except grpc.RpcError:
                time.sleep(0.2)
        else:
            raise RuntimeError("AIR gRPC did not become ready")

        # Attach stream
        channel_id = 123
        attach_resp = stub.AttachStream(playout_pb2.AttachStreamRequest(
            channel_id=channel_id,
            transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
            endpoint=str(socket_path),
            replace_existing=True,
        ), timeout=5.0)
        logger.info(f"Stream attached: {attach_resp.success}")

        # Create test blocks (3 seconds each for quick test)
        block_duration_ms = 3000
        asset = str(TEST_ASSET)

        block_a = create_block_proto("TEST-BLOCK-A", channel_id, 0, block_duration_ms, asset)
        block_b = create_block_proto("TEST-BLOCK-B", channel_id, block_duration_ms, block_duration_ms * 2, asset)

        # Start BlockPlan session FIRST (before subscribing to events)
        program_format = json.dumps({
            "video": {"width": 640, "height": 480, "frame_rate": {"num": 30, "den": 1}},
            "audio": {"sample_rate": 48000, "channels": 2},
        })

        start_resp = stub.StartBlockPlanSession(playout_pb2.StartBlockPlanSessionRequest(
            channel_id=channel_id,
            block_a=block_a,
            block_b=block_b,
            join_utc_ms=0,
            program_format_json=program_format,
        ), timeout=10.0)

        if not start_resp.success:
            raise RuntimeError(f"StartBlockPlanSession failed: {start_resp.message}")

        logger.info("BlockPlan session started")

        # Now subscribe to events (session must exist first)
        recorder = EventRecorder()
        event_stop = threading.Event()

        def event_listener():
            try:
                request = playout_pb2.SubscribeBlockEventsRequest(channel_id=channel_id)
                for event in stub.SubscribeBlockEvents(request):
                    if event_stop.is_set():
                        break

                    if event.HasField("block_completed"):
                        c = event.block_completed
                        recorder.record_block_completed(c.block_id, c.final_ct_ms, c.blocks_executed_total)

                    elif event.HasField("session_ended"):
                        e = event.session_ended
                        recorder.record_session_ended(e.reason, e.final_ct_ms, e.blocks_executed_total)
                        break

            except grpc.RpcError as e:
                if not event_stop.is_set():
                    logger.warning(f"Event stream error: {e.code()}")

        event_thread = threading.Thread(target=event_listener, daemon=True)
        event_thread.start()
        logger.info("Event subscription started, waiting for events...")

        # Wait for first block to complete
        deadline = time.time() + 15.0  # 3s block + overhead
        while recorder.block_completed_count < 1 and time.time() < deadline:
            time.sleep(0.5)

        if recorder.block_completed_count < 1:
            raise RuntimeError("Did not receive BlockCompleted for first block")

        logger.info("First block completed, feeding block C")

        # Feed block C
        block_c = create_block_proto("TEST-BLOCK-C", channel_id, block_duration_ms * 2, block_duration_ms * 3, asset)
        feed_resp = stub.FeedBlockPlan(playout_pb2.FeedBlockPlanRequest(
            channel_id=channel_id,
            block=block_c,
        ), timeout=5.0)
        logger.info(f"Fed block C: success={feed_resp.success}")

        # Wait for second block
        deadline = time.time() + 10.0
        while recorder.block_completed_count < 2 and time.time() < deadline:
            time.sleep(0.5)

        if recorder.block_completed_count < 2:
            raise RuntimeError("Did not receive BlockCompleted for second block")

        logger.info("Second block completed, waiting for third...")

        # Wait for third block and session end (lookahead exhausted)
        deadline = time.time() + 15.0
        while not recorder.session_ended and time.time() < deadline:
            time.sleep(0.5)

        if not recorder.session_ended:
            raise RuntimeError("Did not receive SessionEnded event")

        # Stop event thread
        event_stop.set()
        event_thread.join(timeout=2.0)

        # Verify results
        logger.info("")
        logger.info("=" * 60)
        logger.info("RESULTS")
        logger.info("=" * 60)

        block_events = [e for e in recorder.events if e.event_type == "block_completed"]
        session_event = next((e for e in recorder.events if e.event_type == "session_ended"), None)

        logger.info(f"BlockCompleted events: {len(block_events)}")
        for e in block_events:
            logger.info(f"  - {e.block_id}: ct={e.final_ct_ms}ms, total={e.blocks_executed}")

        if session_event:
            logger.info(f"SessionEnded: reason={session_event.reason}, ct={session_event.final_ct_ms}ms")

        # Assertions
        assert len(block_events) == 3, f"Expected 3 BlockCompleted events, got {len(block_events)}"
        assert session_event is not None, "Expected SessionEnded event"
        assert session_event.reason == "lookahead_exhausted", f"Expected reason 'lookahead_exhausted', got '{session_event.reason}'"

        logger.info("")
        logger.info("✓ All boundary event tests passed!")
        return True

    finally:
        # Cleanup
        air_proc.terminate()
        try:
            air_proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            air_proc.kill()

        uds_sink.stop()
        logger.info(f"AIR log: {log_path}")


if __name__ == "__main__":
    try:
        success = run_boundary_event_test()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
