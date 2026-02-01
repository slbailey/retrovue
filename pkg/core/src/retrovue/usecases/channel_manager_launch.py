"""
Air (playout engine) process management.

ChannelManager spawns Air processes to play video for the schedule. ChannelManager
must NOT spawn ProgramDirector or the main retrovue process; ProgramDirector
spawns ChannelManager when one doesn't exist for the requested channel. This
module is used by ChannelManager to launch and terminate Air processes.

Air logging (stdout/stderr):
  Air output is written to pkg/air/logs/<channel_id>-air.log (one file per channel).
  The log file is truncated on every launch so it does not grow without bound.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Type alias for subprocess.Process
ProcessHandle = subprocess.Popen[bytes]

# Air stdout/stderr go here: pkg/air/logs/<channel_id>-air.log
_AIR_LOG_DIR = Path(__file__).resolve().parents[5] / "pkg" / "air" / "logs"


def _air_log_path(channel_id: str) -> Path:
    """Path to the Air log file for this channel (same as subprocess redirect)."""
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel_id) or "unknown"
    return _AIR_LOG_DIR / f"{safe_id}-air.log"

# Import ChannelConfig for type hints
from retrovue.runtime.config import ChannelConfig, MOCK_CHANNEL_CONFIG


def _open_air_log(channel_id: str):
    """Open Air log file for this channel (truncate on open, line-buffered). Caller closes after Popen."""
    log_path = _air_log_path(channel_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return open(log_path, "w", buffering=1, encoding="utf-8", errors="replace")


def _find_air_binary() -> Path | None:
    """Locate retrovue_air executable. Returns None if not found."""
    # __file__ is .../pkg/core/src/retrovue/usecases/channel_manager_launch.py -> parents[5] = repo root
    repo_root = Path(__file__).resolve().parents[5]
    candidates = [
        Path(os.environ.get("RETROVUE_AIR_EXE", "")),
        repo_root / "pkg" / "air" / "build" / "retrovue_air",
        repo_root / "pkg" / "air" / "out" / "build" / "linux-debug" / "retrovue_air",
    ]
    for p in candidates:
        if p and p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def get_uds_socket_path(channel_id: str) -> Path:
    """
    Get the UDS socket path for a channel.
    
    Uses user-writable location:
    - XDG_RUNTIME_DIR/retrovue/air/ (if XDG_RUNTIME_DIR is set)
    - /tmp/retrovue/air/ (fallback)
    
    Args:
        channel_id: Channel identifier
    
    Returns:
        Path to the UDS socket
    """
    # Use XDG_RUNTIME_DIR if available (user-writable)
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        socket_dir = Path(runtime_dir) / "retrovue" / "air"
    else:
        # Fallback to /tmp (user-writable)
        socket_dir = Path("/tmp/retrovue/air")
    
    socket_path = socket_dir / f"channel_{channel_id}.sock"
    return socket_path


def ensure_socket_dir_exists(socket_path: Path) -> None:
    """
    Ensure the directory containing the UDS socket exists.
    
    Args:
        socket_path: Path to the UDS socket
    """
    socket_dir = socket_path.parent
    socket_dir.mkdir(parents=True, exist_ok=True)
    # Ensure directory has proper permissions
    os.chmod(socket_dir, 0o755)


def _get_playout_stubs() -> tuple[types.ModuleType, types.ModuleType]:
    """Load playout_pb2 and playout_pb2_grpc from pkg/core/core/proto/retrovue. Returns (playout_pb2, playout_pb2_grpc)."""
    _core_root = Path(__file__).resolve().parents[3]
    _proto_retrovue_dir = _core_root / "core" / "proto" / "retrovue"
    if not _proto_retrovue_dir.is_dir():
        raise RuntimeError(
            f"Proto stubs not found at {_proto_retrovue_dir}. "
            "Run scripts/air/generate_proto.sh or equivalent to generate playout_pb2(_grpc).py."
        )
    _spec_pb2 = importlib.util.spec_from_file_location(
        "playout_pb2", _proto_retrovue_dir / "playout_pb2.py"
    )
    _spec_grpc = importlib.util.spec_from_file_location(
        "playout_pb2_grpc", _proto_retrovue_dir / "playout_pb2_grpc.py"
    )
    if _spec_pb2 is None or _spec_grpc is None:
        raise RuntimeError("Failed to create spec for proto stubs")
    playout_pb2 = importlib.util.module_from_spec(_spec_pb2)
    playout_pb2_grpc = importlib.util.module_from_spec(_spec_grpc)
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


# Phase 8: ResultCode enum values (must match proto)
RESULT_CODE_UNSPECIFIED = 0
RESULT_CODE_OK = 1
RESULT_CODE_NOT_READY = 2
RESULT_CODE_REJECTED_BUSY = 3
RESULT_CODE_PROTOCOL_VIOLATION = 4  # Caller violated the protocol
RESULT_CODE_FAILED = 5


def log_core_intent_frame_range(
    *,
    channel_id: str,
    segment_id: str,
    asset_path: str,
    start_frame: int,
    end_frame: int,
    fps: float,
    CT_start_us: int,
    MT_start_us: int,
) -> None:
    """Emit structured CORE_INTENT_FRAME_RANGE probe (once per segment hand-off to AIR)."""
    import logging
    msg = (
        f"CORE_INTENT_FRAME_RANGE channel_id={channel_id} segment_id={segment_id} asset_path={asset_path} "
        f"start_frame={start_frame} end_frame={end_frame} fps={fps} CT_start_us={CT_start_us} MT_start_us={MT_start_us}"
    )
    logging.getLogger(__name__).info("%s", msg)
    # Also append to the channel's Air log so intent and AIR_AS_RUN appear together for comparison.
    try:
        log_path = _air_log_path(channel_id)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8", errors="replace") as f:
            f.write("[Core] " + msg + "\n")
    except OSError:
        pass  # Do not fail hand-off if log write fails


def air_load_preview(
    grpc_addr: str,
    channel_id_int: int,
    asset_path: str,
    start_frame: int,
    frame_count: int,
    fps_numerator: int,
    fps_denominator: int,
    timeout_s: int = 90,
) -> bool:
    """Call Air LoadPreview RPC with frame-indexed execution (INV-FRAME-001/002/003).

    Args:
        grpc_addr: gRPC address of Air engine (e.g. "127.0.0.1:50051")
        channel_id_int: Channel ID as integer
        asset_path: Fully-qualified path to media file
        start_frame: First frame index within asset (0-based, INV-FRAME-001)
        frame_count: Exact number of frames to play (INV-FRAME-002)
        fps_numerator: Frame rate numerator (e.g. 30000 for 29.97fps, INV-FRAME-003)
        fps_denominator: Frame rate denominator (e.g. 1001 for 29.97fps, INV-FRAME-003)
        timeout_s: RPC timeout in seconds

    Returns:
        True if preview loaded successfully, False otherwise.

    Raises:
        grpc.RpcError on connection/RPC error.

    Phase 8: If result_code is REJECTED_BUSY, logs at INFO level (expected when
    switch is armed) rather than WARNING.
    """
    import grpc
    import logging
    logger = logging.getLogger(__name__)

    # INV-FRAME-003: Fail fast if fps not provided
    if fps_denominator <= 0:
        logger.error("INV-FRAME-003 violation: fps_denominator must be > 0 (got %d)", fps_denominator)
        return False

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.LoadPreview(
            playout_pb2.LoadPreviewRequest(
                channel_id=channel_id_int,
                asset_path=asset_path,
                start_frame=start_frame,
                frame_count=frame_count,
                fps_numerator=fps_numerator,
                fps_denominator=fps_denominator,
            ),
            timeout=timeout_s,
        )

    # Phase 8: Treat REJECTED_BUSY as expected (switch is armed, LoadPreview forbidden)
    if not r.success:
        result_code = getattr(r, 'result_code', RESULT_CODE_UNSPECIFIED)
        if result_code == RESULT_CODE_REJECTED_BUSY:
            logger.info("LoadPreview rejected (switch armed): %s", r.message)
        else:
            logger.warning("LoadPreview failed: %s (result_code=%d)", r.message, result_code)

    return r.success


def air_switch_to_live(grpc_addr: str, channel_id_int: int, timeout_s: int = 30) -> tuple[bool, int]:
    """Call Air SwitchToLive RPC. Returns (success, result_code). Raises on connection/RPC error.

    Phase 8: Returns result_code so caller can distinguish NOT_READY (transient) from errors.
    """
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.SwitchToLive(
            playout_pb2.SwitchToLiveRequest(channel_id=channel_id_int),
            timeout=timeout_s,
        )
    result_code = getattr(r, 'result_code', RESULT_CODE_UNSPECIFIED)
    return (r.success, result_code)


def _launch_air_binary(
    *,
    air_bin: Path,
    asset_path: str,
    start_pts_ms: int,
    socket_path: Path,
    channel_id: str,
    channel_config: ChannelConfig,
    segment_id: str = "",
    segment_start_time_utc: str | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> tuple[ProcessHandle, Path, queue.Queue[Any], str]:
    """Start retrovue_air, drive gRPC (StartChannel, LoadPreview, SwitchToLive, AttachStream), return process, socket path, reader queue, and grpc_addr."""
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()

    reader_socket_queue: queue.Queue[Any] = queue.Queue()

    if socket_path.exists():
        socket_path.unlink()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)

    def accept_once() -> None:
        conn, _ = server.accept()
        reader_socket_queue.put(conn)
        try:
            server.close()  # Only Air should connect; viewers use HTTP (e.g. http://localhost:PORT/channel/ID.ts)
        except Exception:
            pass

    threading.Thread(target=accept_once, daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        grpc_port = s.getsockname()[1]

    # Redirect Air stdout/stderr to channel-specific log (truncated each run)
    air_log = _open_air_log(channel_id)
    try:
        proc = subprocess.Popen(
            [str(air_bin), "--port", str(grpc_port)],
            cwd=str(air_bin.parent),
            stdout=air_log,
            stderr=air_log,
            stdin=subprocess.DEVNULL,
        )
    finally:
        air_log.close()

    # Timeouts: Air can be slow on first start (decode init, file open). Override via env if needed.
    def _timeout_s(name: str, default: int) -> int:
        key = f"RETROVUE_AIR_TIMEOUT_{name}"
        val = os.environ.get(key, "")
        return int(val) if val.isdigit() else default

    _GRPC_READY_WAIT_S = _timeout_s("GRPC_READY_WAIT", 45)
    _GRPC_READY_POLL_S = _timeout_s("GRPC_READY_POLL", 5)
    _RPC_CONTROL_S = _timeout_s("RPC_CONTROL", 30)
    _RPC_LOAD_PREVIEW_S = _timeout_s("RPC_LOAD_PREVIEW", 90)
    _UDS_ACCEPT_S = _timeout_s("UDS_ACCEPT", 20)

    def _rpc(step: str, fn, timeout: int):
        try:
            return fn(timeout=timeout)
        except grpc.RpcError as e:
            d = getattr(e, "details", None)
            detail = d() if callable(d) else (d if isinstance(d, str) else str(e))
            raise RuntimeError(
                f"Air gRPC {step} timed out or failed (timeout={timeout}s): {detail}. "
                f"Check Air logs; increase timeout with RETROVUE_AIR_TIMEOUT_* env if needed."
            ) from e

    grpc_addr = f"127.0.0.1:{grpc_port}"
    for _ in range(max(1, int(_GRPC_READY_WAIT_S / 0.2))):
        try:
            with grpc.insecure_channel(grpc_addr) as ch:
                stub = playout_pb2_grpc.PlayoutControlStub(ch)
                stub.GetVersion(playout_pb2.ApiVersionRequest(), timeout=_GRPC_READY_POLL_S)
            break
        except grpc.RpcError:
            if proc.poll() is not None:
                raise RuntimeError(f"Air process exited with code {proc.returncode} before gRPC ready")
            time.sleep(0.2)
    else:
        proc.terminate()
        proc.wait(timeout=3)
        raise RuntimeError("Air gRPC server did not become ready")

    channel_id_int = channel_config.channel_id_int
    program_format_json = channel_config.program_format.to_json()
    # Air uses plan_handle as the initial asset URI (file path) for the producer; pass resolved path.
    plan_handle = asset_path if asset_path else "mock"
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = _rpc(
            "StartChannel",
            lambda timeout: stub.StartChannel(
                playout_pb2.StartChannelRequest(
                    channel_id=channel_id_int, plan_handle=plan_handle, port=0,
                    program_format_json=program_format_json
                ),
                timeout=timeout,
            ),
            _RPC_CONTROL_S,
        )
        if not r.success:
            raise RuntimeError(f"StartChannel failed: {r.message}")
        # Frame-indexed execution (INV-FRAME-001/002/003)
        # Convert start_pts_ms to start_frame using channel fps
        # Default to 30fps if not specified; channel_config provides authoritative fps
        fps_num = getattr(channel_config.program_format, 'frame_rate_num', 30)
        fps_den = getattr(channel_config.program_format, 'frame_rate_den', 1)
        fps = fps_num / fps_den if fps_den > 0 else 30.0
        start_frame = int((start_pts_ms / 1000.0) * fps) if fps > 0 else 0
        # frame_count = -1 means play until EOF (initial segment has no predetermined end)
        frame_count = -1
        r = _rpc(
            "LoadPreview",
            lambda timeout: stub.LoadPreview(
                playout_pb2.LoadPreviewRequest(
                    channel_id=channel_id_int,
                    asset_path=asset_path,
                    start_frame=start_frame,
                    frame_count=frame_count,
                    fps_numerator=fps_num,
                    fps_denominator=fps_den,
                ),
                timeout=timeout,
            ),
            _RPC_LOAD_PREVIEW_S,
        )
        if not r.success:
            raise RuntimeError(f"LoadPreview failed: {r.message}")
        # Contract-level observability: CORE_INTENT_FRAME_RANGE (once per segment)
        end_frame = start_frame + frame_count - 1 if frame_count >= 0 else -1
        MT_start_us = 0
        if segment_start_time_utc:
            try:
                dt = datetime.fromisoformat(segment_start_time_utc.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                MT_start_us = int(dt.timestamp() * 1_000_000)
            except (ValueError, TypeError):
                pass
        log_core_intent_frame_range(
            channel_id=channel_id,
            segment_id=segment_id or "",
            asset_path=asset_path,
            start_frame=start_frame,
            end_frame=end_frame,
            fps=fps,
            CT_start_us=0,
            MT_start_us=MT_start_us,
        )
        # AttachStream before SwitchToLive: Air must have the UDS fd in stream_writers_
        # so that SwitchToLive can start FfmpegLoop and write TS to that fd.
        r = _rpc(
            "AttachStream",
            lambda timeout: stub.AttachStream(
                playout_pb2.AttachStreamRequest(
                    channel_id=channel_id_int,
                    transport=playout_pb2.STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET,
                    endpoint=str(socket_path),
                    replace_existing=True,
                ),
                timeout=timeout,
            ),
            _RPC_CONTROL_S,
        )
        if not r.success:
            raise RuntimeError(f"AttachStream failed: {r.message}")
        # Phase 7/8: SwitchToLive may return NOT_READY if preview buffer isn't filled yet.
        # This is a transient state - retry with backoff until success or timeout.
        # Phase 8: Use result_code for reliable detection (no message parsing).
        _SWITCH_RETRY_ATTEMPTS = 20  # ~10 seconds total with backoff
        _SWITCH_RETRY_BACKOFF_MS = 500  # Start at 500ms between retries
        switch_ok = False
        last_message = ""
        first_not_ready_logged = False
        switch_start_time = time.monotonic()
        for attempt in range(_SWITCH_RETRY_ATTEMPTS):
            r = _rpc(
                "SwitchToLive",
                lambda timeout: stub.SwitchToLive(
                    playout_pb2.SwitchToLiveRequest(channel_id=channel_id_int),
                    timeout=timeout,
                ),
                _RPC_CONTROL_S,
            )
            if r.success:
                switch_ok = True
                elapsed_ms = (time.monotonic() - switch_start_time) * 1000
                import logging
                logging.getLogger(__name__).info(
                    "SwitchToLive succeeded after %d attempts (%.0fms)", attempt + 1, elapsed_ms
                )
                break
            last_message = r.message
            # Phase 8: Use result_code for reliable retry detection
            result_code = getattr(r, 'result_code', RESULT_CODE_UNSPECIFIED)
            is_retryable = (result_code == RESULT_CODE_NOT_READY)
            # Fallback to message parsing for backward compatibility
            if not is_retryable:
                msg_lower = r.message.lower()
                is_retryable = (
                    "not ready" in msg_lower or
                    "NOT_READY" in r.message or
                    "preparing" in msg_lower or
                    "transition started" in msg_lower or
                    "waiting for preview" in msg_lower or
                    "switch in progress" in msg_lower or
                    "awaiting buffer" in msg_lower
                )
            if is_retryable:
                if not first_not_ready_logged:
                    import logging
                    logging.getLogger(__name__).info(
                        "SwitchToLive NOT_READY (attempt 1): %s - retrying up to %d times",
                        r.message, _SWITCH_RETRY_ATTEMPTS
                    )
                    first_not_ready_logged = True
                time.sleep(_SWITCH_RETRY_BACKOFF_MS / 1000.0)
                continue
            # Other errors are fatal
            raise RuntimeError(f"SwitchToLive failed: {r.message}")
        if not switch_ok:
            elapsed_ms = (time.monotonic() - switch_start_time) * 1000
            raise RuntimeError(
                f"SwitchToLive timed out after {_SWITCH_RETRY_ATTEMPTS} attempts ({elapsed_ms:.0f}ms): {last_message}"
            )

    try:
        conn = reader_socket_queue.get(timeout=_UDS_ACCEPT_S)
    except queue.Empty:
        proc.terminate()
        proc.wait(timeout=3)
        raise RuntimeError(f"Air did not connect to UDS within {_UDS_ACCEPT_S}s")
    reader_socket_queue.put(conn)
    return proc, socket_path, reader_socket_queue, grpc_addr


def launch_air(
    *,
    playout_request: dict[str, Any],
    channel_config: ChannelConfig | None = None,
    stdin: Any = subprocess.PIPE,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    ts_socket_path: str | Path | None = None,
) -> tuple[ProcessHandle, Path, queue.Queue[Any], str]:
    """
    Launch the Air (C++) playout engine process for a channel.

    Air is the only playout engine. There is no ffmpeg fallback. If Air cannot be
    found, started, or attached, this function raises and the caller must return
    HTTP 503 (e.g. "Air playout engine unavailable").

    Returns:
        (process, socket_path, reader_socket_queue, grpc_addr). The reader_socket_queue
        receives the one accepted UDS connection from Air after AttachStream; the caller
        passes it to ChannelStream. grpc_addr (e.g. "127.0.0.1:port") is for later
        LoadPreview/SwitchToLive RPCs (clock-driven segment switching).

    Raises:
        RuntimeError: If Air binary not found, not executable, gRPC connect fails,
            or StartChannel/LoadPreview/AttachStream/SwitchToLive times out or fails.
    """
    channel_id = playout_request.get("channel_id", "unknown")
    asset_path = playout_request.get("asset_path", "")
    start_pts_ms = playout_request.get("start_pts", 0)

    # Use provided config or fall back to mock config for backwards compatibility
    config = channel_config if channel_config is not None else MOCK_CHANNEL_CONFIG

    if ts_socket_path is None:
        socket_path = get_uds_socket_path(channel_id)
    else:
        socket_path = Path(ts_socket_path)

    ensure_socket_dir_exists(socket_path)

    air_bin = _find_air_binary()
    if air_bin is None:
        raise RuntimeError(
            "Air playout engine unavailable: retrovue_air binary not found. "
            "Build pkg/air (retrovue_air target) or set RETROVUE_AIR_EXE."
        )

    proc, socket_path, reader_socket_queue, grpc_addr = _launch_air_binary(
        air_bin=air_bin,
        asset_path=asset_path,
        start_pts_ms=start_pts_ms,
        socket_path=socket_path,
        channel_id=channel_id,
        channel_config=config,
        segment_id=playout_request.get("segment_id", ""),
        segment_start_time_utc=playout_request.get("start_time_utc"),
        stdout=stdout,
        stderr=stderr,
    )
    return proc, socket_path, reader_socket_queue, grpc_addr


def _launch_ffmpeg_fallback(
    asset_path: str,
    start_pts_ms: int,
    socket_path: Path,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
) -> tuple[ProcessHandle, Path]:
    """FFmpeg fallback removed. Air is the only playout engine. Fail fast instead."""
    raise RuntimeError(
        "ffmpeg fallback removed. Air is the only playout engine. "
        "Build retrovue_air (pkg/air) or set RETROVUE_AIR_EXE. Do not use RETROVUE_USE_FFMPEG."
    )


def terminate_air(process: ProcessHandle) -> None:
    """
    Terminate the internal playout engine process.
    
    - Terminates playout engine process when client_count drops to 0
    
    Args:
        process: Process handle from launch_air()
    
    Example:
        ```python
        process = launch_air(...)
        # ... later ...
        terminate_air(process)
        ```
    """
    if process.poll() is None:  # Process still running
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


__all__ = [
    "launch_air",
    "terminate_air",
    "ProcessHandle",
    "get_uds_socket_path",
    "ensure_socket_dir_exists",
]

