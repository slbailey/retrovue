"""
Repository: Retrovue-playout
Component: PlayoutSession - BlockPlan-based playout orchestration
Purpose: Wraps AIR subprocess for BlockPlan 2-block window execution

This module provides the PlayoutSession class that orchestrates BlockPlan-based
playout without ChannelManager needing to reason about segments, preload timing,
or switching. All that logic is delegated to the AIR executor.

Usage:
    session = PlayoutSession(channel_id, channel_config, ts_socket_path)
    session.start(join_utc_ms)
    session.seed(block_a, block_b)
    session.feed(block_c)  # Call when slot available
    session.stop("last_viewer_left")

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import types
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import grpc


def _get_playout_stubs() -> tuple[types.ModuleType, types.ModuleType]:
    """Load playout_pb2 and playout_pb2_grpc from pkg/core/core/proto/retrovue."""
    # Try multiple paths for flexibility
    candidates = [
        Path(__file__).resolve().parents[3] / "core" / "proto" / "retrovue",
        Path(__file__).resolve().parents[4] / "core" / "proto" / "retrovue",
        Path("/opt/retrovue/pkg/core/core/proto/retrovue"),
    ]
    _proto_dir = None
    for p in candidates:
        if p.is_dir() and (p / "playout_pb2.py").exists():
            _proto_dir = p
            break

    if _proto_dir is None:
        raise RuntimeError(
            "Proto stubs not found. Run scripts/air/generate_proto.sh to generate playout_pb2(_grpc).py."
        )

    _spec_pb2 = importlib.util.spec_from_file_location(
        "playout_pb2", _proto_dir / "playout_pb2.py"
    )
    _spec_grpc = importlib.util.spec_from_file_location(
        "playout_pb2_grpc", _proto_dir / "playout_pb2_grpc.py"
    )
    if _spec_pb2 is None or _spec_grpc is None:
        raise RuntimeError("Failed to create spec for proto stubs")

    playout_pb2 = importlib.util.module_from_spec(_spec_pb2)
    playout_pb2_grpc = importlib.util.module_from_spec(_spec_grpc)

    # Temporarily inject retrovue.playout_pb2 so grpc stub can import it
    _retrovue_saved = sys.modules.get("retrovue")
    _playout_pb2_saved = sys.modules.get("playout_pb2")
    _proto_retrovue = types.ModuleType("retrovue")
    _proto_retrovue.playout_pb2 = playout_pb2
    sys.modules["retrovue"] = _proto_retrovue
    try:
        _spec_pb2.loader.exec_module(playout_pb2)
        sys.modules["playout_pb2"] = playout_pb2
        _spec_grpc.loader.exec_module(playout_pb2_grpc)
        return (playout_pb2, playout_pb2_grpc)
    finally:
        if _retrovue_saved is not None:
            sys.modules["retrovue"] = _retrovue_saved
        else:
            sys.modules.pop("retrovue", None)
        if _playout_pb2_saved is not None:
            sys.modules["playout_pb2"] = _playout_pb2_saved
        else:
            sys.modules.pop("playout_pb2", None)


# Load proto stubs
playout_pb2, playout_pb2_grpc = _get_playout_stubs()

logger = logging.getLogger(__name__)


@dataclass
class BlockPlan:
    """Python representation of a BlockPlan for the executor."""
    block_id: str
    channel_id: int
    start_utc_ms: int
    end_utc_ms: int
    segments: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BlockPlan":
        """Create BlockPlan from dictionary (e.g., loaded from JSON)."""
        return cls(
            block_id=d["block_id"],
            channel_id=d["channel_id"],
            start_utc_ms=d["start_utc_ms"],
            end_utc_ms=d["end_utc_ms"],
            segments=d.get("segments", []),
        )

    def to_proto(self) -> playout_pb2.BlockPlan:
        """Convert to protobuf message."""
        pb = playout_pb2.BlockPlan(
            block_id=self.block_id,
            channel_id=self.channel_id,
            start_utc_ms=self.start_utc_ms,
            end_utc_ms=self.end_utc_ms,
        )
        for seg in self.segments:
            pb.segments.append(playout_pb2.BlockSegment(
                segment_index=seg["segment_index"],
                asset_uri=seg["asset_uri"],
                asset_start_offset_ms=seg.get("asset_start_offset_ms", 0),
                segment_duration_ms=seg["segment_duration_ms"],
            ))
        return pb

    @property
    def duration_ms(self) -> int:
        return self.end_utc_ms - self.start_utc_ms


@dataclass
class SessionState:
    """Internal state tracking for PlayoutSession."""
    is_running: bool = False
    blocks_seeded: int = 0
    blocks_fed: int = 0
    blocks_executed: int = 0
    last_error: Optional[str] = None
    grpc_addr: Optional[str] = None
    air_process: Optional[subprocess.Popen] = None


class PlayoutSession:
    """
    Orchestrates BlockPlan-based playout through AIR.

    PlayoutSession manages the lifecycle of a BlockPlan execution session:
    - Launches AIR subprocess
    - Seeds the 2-block queue
    - Feeds blocks just-in-time when slots become available
    - Stops execution when viewer count hits 0

    ChannelManager uses this instead of directly managing segments/switches.
    """

    def __init__(
        self,
        channel_id: str,
        channel_id_int: int,
        ts_socket_path: Path,
        program_format: dict[str, Any],
        air_binary_path: Optional[Path] = None,
        on_block_complete: Optional[Callable[[str], None]] = None,
        on_session_end: Optional[Callable[[str], None]] = None,
    ):
        """
        Initialize PlayoutSession.

        Args:
            channel_id: String channel identifier (e.g., "cheers-24-7")
            channel_id_int: Integer channel ID for AIR
            ts_socket_path: UDS socket path where AIR writes TS bytes
            program_format: Video/audio format config (width, height, fps, etc.)
            air_binary_path: Path to retrovue_air binary (auto-detected if None)
            on_block_complete: Callback when a block completes (receives block_id)
            on_session_end: Callback when session ends (receives reason)
        """
        self.channel_id = channel_id
        self.channel_id_int = channel_id_int
        self.ts_socket_path = ts_socket_path
        self.program_format = program_format
        self.air_binary_path = air_binary_path or self._find_air_binary()
        self.on_block_complete = on_block_complete
        self.on_session_end = on_session_end

        self._state = SessionState()
        self._lock = threading.Lock()
        self._grpc_channel: Optional[grpc.Channel] = None
        self._stub: Optional[playout_pb2_grpc.PlayoutControlStub] = None
        self._event_thread: Optional[threading.Thread] = None
        self._event_stop = threading.Event()

        logger.info(f"[PlayoutSession:{channel_id}] Initialized, ts_socket={ts_socket_path}")

    def _find_air_binary(self) -> Path:
        """Find the AIR binary path."""
        # Try common locations
        candidates = [
            Path("pkg/air/build/retrovue_air"),
            Path("/opt/retrovue/pkg/air/build/retrovue_air"),
            Path.home() / "retrovue/pkg/air/build/retrovue_air",
        ]
        for p in candidates:
            if p.exists():
                return p
        raise FileNotFoundError("Could not find retrovue_air binary")

    def _allocate_grpc_port(self) -> int:
        """Allocate an ephemeral port for gRPC."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            return s.getsockname()[1]

    def start(self, join_utc_ms: int = 0) -> bool:
        """
        Start the AIR subprocess and prepare for BlockPlan execution.

        Args:
            join_utc_ms: Join time for mid-block join (0 = block start)

        Returns:
            True if AIR started successfully
        """
        with self._lock:
            if self._state.is_running:
                logger.warning(f"[PlayoutSession:{self.channel_id}] Already running")
                return False

            try:
                grpc_port = self._allocate_grpc_port()
                self._state.grpc_addr = f"127.0.0.1:{grpc_port}"

                # Launch AIR subprocess
                cmd = [
                    str(self.air_binary_path),
                    "--port", str(grpc_port),
                ]

                # Create log directory
                log_dir = Path("pkg/air/logs")
                log_dir.mkdir(parents=True, exist_ok=True)
                log_path = log_dir / f"{self.channel_id}-air.log"

                logger.info(f"[PlayoutSession:{self.channel_id}] Starting AIR: {' '.join(cmd)}")

                with open(log_path, 'w') as log_file:
                    self._state.air_process = subprocess.Popen(
                        cmd,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        cwd=str(Path.cwd()),
                    )

                # Wait for gRPC to be ready
                if not self._wait_for_grpc(timeout_s=10.0):
                    raise RuntimeError("AIR gRPC did not become ready")

                # Attach stream (UDS socket)
                if not self._attach_stream():
                    raise RuntimeError("Failed to attach stream")

                self._state.is_running = True
                logger.info(f"[PlayoutSession:{self.channel_id}] Started, grpc={self._state.grpc_addr}")
                return True

            except Exception as e:
                logger.error(f"[PlayoutSession:{self.channel_id}] Start failed: {e}")
                self._state.last_error = str(e)
                self._cleanup()
                return False

    def _wait_for_grpc(self, timeout_s: float) -> bool:
        """Wait for AIR gRPC to become ready."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                self._grpc_channel = grpc.insecure_channel(self._state.grpc_addr)
                self._stub = playout_pb2_grpc.PlayoutControlStub(self._grpc_channel)

                # Try GetVersion to check connectivity
                response = self._stub.GetVersion(
                    playout_pb2.ApiVersionRequest(),
                    timeout=2.0
                )
                logger.debug(f"[PlayoutSession:{self.channel_id}] AIR version: {response.version}")
                return True
            except grpc.RpcError:
                time.sleep(0.2)
        return False

    def _attach_stream(self) -> bool:
        """Attach the TS output stream to the UDS socket."""
        try:
            # Ensure socket directory exists
            self.ts_socket_path.parent.mkdir(parents=True, exist_ok=True)

            request = playout_pb2.AttachStreamRequest(
                channel_id=self.channel_id_int,
                transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                endpoint=str(self.ts_socket_path),
                replace_existing=True,
            )
            response = self._stub.AttachStream(request, timeout=5.0)

            if response.success:
                logger.info(f"[PlayoutSession:{self.channel_id}] Stream attached: {self.ts_socket_path}")
                return True
            else:
                logger.error(f"[PlayoutSession:{self.channel_id}] AttachStream failed: {response.message}")
                return False
        except grpc.RpcError as e:
            logger.error(f"[PlayoutSession:{self.channel_id}] AttachStream RPC error: {e}")
            return False

    def _subscribe_to_events(self) -> None:
        """Start background thread to receive block events from AIR."""
        def event_loop():
            try:
                request = playout_pb2.SubscribeBlockEventsRequest(
                    channel_id=self.channel_id_int,
                )
                # Use a streaming call that will block until events arrive or connection ends
                for event in self._stub.SubscribeBlockEvents(request):
                    if self._event_stop.is_set():
                        break

                    if event.HasField("block_completed"):
                        completed = event.block_completed
                        logger.info(
                            f"[PlayoutSession:{self.channel_id}] BlockCompleted: "
                            f"block_id={completed.block_id}, "
                            f"final_ct_ms={completed.final_ct_ms}, "
                            f"blocks_total={completed.blocks_executed_total}"
                        )
                        with self._lock:
                            self._state.blocks_executed = completed.blocks_executed_total
                        if self.on_block_complete:
                            try:
                                self.on_block_complete(completed.block_id)
                            except Exception as e:
                                logger.error(
                                    f"[PlayoutSession:{self.channel_id}] "
                                    f"on_block_complete callback error: {e}"
                                )

                    elif event.HasField("session_ended"):
                        ended = event.session_ended
                        logger.info(
                            f"[PlayoutSession:{self.channel_id}] SessionEnded: "
                            f"reason={ended.reason}, "
                            f"final_ct_ms={ended.final_ct_ms}, "
                            f"blocks_total={ended.blocks_executed_total}"
                        )
                        with self._lock:
                            self._state.blocks_executed = ended.blocks_executed_total
                            self._state.is_running = False
                        if self.on_session_end:
                            try:
                                self.on_session_end(ended.reason)
                            except Exception as e:
                                logger.error(
                                    f"[PlayoutSession:{self.channel_id}] "
                                    f"on_session_end callback error: {e}"
                                )
                        break  # Session ended, exit the event loop

            except grpc.RpcError as e:
                if not self._event_stop.is_set():
                    logger.warning(
                        f"[PlayoutSession:{self.channel_id}] Event stream error: {e.code()}"
                    )

        self._event_stop.clear()
        self._event_thread = threading.Thread(target=event_loop, daemon=True)
        self._event_thread.start()
        logger.debug(f"[PlayoutSession:{self.channel_id}] Event subscription started")

    def seed(self, block_a: BlockPlan, block_b: BlockPlan) -> bool:
        """
        Seed the executor with 2 initial blocks.

        Must be called after start() and before any feed() calls.
        Blocks must be contiguous (block_a.end_utc_ms == block_b.start_utc_ms).

        Args:
            block_a: First block (will start executing immediately)
            block_b: Second block (pending)

        Returns:
            True if seeding succeeded
        """
        with self._lock:
            if not self._state.is_running:
                logger.error(f"[PlayoutSession:{self.channel_id}] Cannot seed - not running")
                return False

            if self._state.blocks_seeded > 0:
                logger.error(f"[PlayoutSession:{self.channel_id}] Already seeded")
                return False

            # Validate contiguity
            if block_a.end_utc_ms != block_b.start_utc_ms:
                logger.error(
                    f"[PlayoutSession:{self.channel_id}] Blocks not contiguous: "
                    f"{block_a.block_id} ends at {block_a.end_utc_ms}, "
                    f"{block_b.block_id} starts at {block_b.start_utc_ms}"
                )
                return False

            try:
                request = playout_pb2.StartBlockPlanSessionRequest(
                    channel_id=self.channel_id_int,
                    block_a=block_a.to_proto(),
                    block_b=block_b.to_proto(),
                    join_utc_ms=block_a.start_utc_ms,  # Start at block beginning
                    program_format_json=json.dumps(self.program_format),
                )

                response = self._stub.StartBlockPlanSession(request, timeout=10.0)

                if response.success:
                    self._state.blocks_seeded = 2
                    logger.info(
                        f"[PlayoutSession:{self.channel_id}] Seeded: "
                        f"{block_a.block_id}, {block_b.block_id}"
                    )
                    # Start event subscription for boundary-driven feeding
                    self._subscribe_to_events()
                    return True
                else:
                    logger.error(
                        f"[PlayoutSession:{self.channel_id}] Seed failed: "
                        f"{response.message} (code={response.result_code})"
                    )
                    return False

            except grpc.RpcError as e:
                logger.error(f"[PlayoutSession:{self.channel_id}] Seed RPC error: {e}")
                return False

    def feed(self, block: BlockPlan) -> bool:
        """
        Feed the next block to the executor queue.

        Call this when a block completes to maintain the 2-block window.
        Block must be contiguous with the current pending block.

        Args:
            block: Next block to feed

        Returns:
            True if feeding succeeded
        """
        with self._lock:
            if not self._state.is_running:
                logger.error(f"[PlayoutSession:{self.channel_id}] Cannot feed - not running")
                return False

            try:
                request = playout_pb2.FeedBlockPlanRequest(
                    channel_id=self.channel_id_int,
                    block=block.to_proto(),
                )

                response = self._stub.FeedBlockPlan(request, timeout=5.0)

                if response.success:
                    self._state.blocks_fed += 1
                    logger.info(f"[PlayoutSession:{self.channel_id}] Fed: {block.block_id}")
                    return True
                else:
                    if response.queue_full:
                        logger.warning(
                            f"[PlayoutSession:{self.channel_id}] Feed skipped - queue full"
                        )
                    else:
                        logger.error(
                            f"[PlayoutSession:{self.channel_id}] Feed failed: "
                            f"{response.message} (code={response.result_code})"
                        )
                    return False

            except grpc.RpcError as e:
                logger.error(f"[PlayoutSession:{self.channel_id}] Feed RPC error: {e}")
                return False

    def stop(self, reason: str = "requested") -> bool:
        """
        Stop the BlockPlan session and terminate AIR.

        Args:
            reason: Reason for stopping (for logging)

        Returns:
            True if stopped successfully
        """
        with self._lock:
            if not self._state.is_running:
                logger.debug(f"[PlayoutSession:{self.channel_id}] Already stopped")
                return True

            logger.info(f"[PlayoutSession:{self.channel_id}] Stopping: {reason}")

            try:
                if self._stub:
                    request = playout_pb2.StopBlockPlanSessionRequest(
                        channel_id=self.channel_id_int,
                        reason=reason,
                    )
                    response = self._stub.StopBlockPlanSession(request, timeout=5.0)

                    if response.success:
                        self._state.blocks_executed = response.blocks_executed
                        logger.info(
                            f"[PlayoutSession:{self.channel_id}] Stopped: "
                            f"final_ct={response.final_ct_ms}ms, "
                            f"blocks_executed={response.blocks_executed}"
                        )
            except grpc.RpcError as e:
                logger.warning(f"[PlayoutSession:{self.channel_id}] Stop RPC error: {e}")

            self._cleanup()

            if self.on_session_end:
                self.on_session_end(reason)

            return True

    def _cleanup(self):
        """Clean up resources."""
        self._state.is_running = False

        # Signal event thread to stop
        self._event_stop.set()
        if self._event_thread and self._event_thread.is_alive():
            self._event_thread.join(timeout=2.0)
        self._event_thread = None

        if self._grpc_channel:
            try:
                self._grpc_channel.close()
            except Exception:
                pass
            self._grpc_channel = None
            self._stub = None

        if self._state.air_process:
            try:
                self._state.air_process.terminate()
                self._state.air_process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._state.air_process.kill()
            except Exception:
                pass
            self._state.air_process = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state.is_running

    @property
    def blocks_executed(self) -> int:
        with self._lock:
            return self._state.blocks_executed


class MockBlockPlanProvider:
    """
    Mock provider that returns fixture BlockPlans for testing.

    Returns 3 blocks in sequence, each 10 seconds long.
    """

    def __init__(self, channel_id: int = 1):
        self.channel_id = channel_id
        self._block_index = 0
        self._base_time_ms = 0

    def reset(self, base_time_ms: int = 0):
        """Reset provider to start from given time."""
        self._block_index = 0
        self._base_time_ms = base_time_ms

    def get_next_blocks(self, count: int = 2) -> list[BlockPlan]:
        """Get the next N blocks."""
        blocks = []
        for _ in range(count):
            block = self._create_block()
            if block:
                blocks.append(block)
        return blocks

    def get_next_block(self) -> Optional[BlockPlan]:
        """Get the next block, or None if exhausted."""
        return self._create_block()

    def _create_block(self) -> Optional[BlockPlan]:
        """Create the next block in sequence."""
        # We have 3 fixture blocks
        fixtures = [
            ("BLOCK-A", "assets/SampleA.mp4"),
            ("BLOCK-B", "assets/SampleB.mp4"),
            ("BLOCK-C", "assets/SampleC.mp4"),
        ]

        if self._block_index >= len(fixtures):
            return None

        block_id, asset = fixtures[self._block_index]
        duration_ms = 10000  # 10 seconds per block

        start_ms = self._base_time_ms + (self._block_index * duration_ms)
        end_ms = start_ms + duration_ms

        block = BlockPlan(
            block_id=block_id,
            channel_id=self.channel_id,
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            segments=[{
                "segment_index": 0,
                "asset_uri": asset,
                "asset_start_offset_ms": 0,
                "segment_duration_ms": duration_ms,
            }]
        )

        self._block_index += 1
        return block

    @property
    def has_more(self) -> bool:
        return self._block_index < 3
