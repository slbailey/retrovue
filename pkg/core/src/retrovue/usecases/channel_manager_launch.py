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
from pathlib import Path
from typing import Any

# Type alias for subprocess.Process
ProcessHandle = subprocess.Popen[bytes]

# Air stdout/stderr go here: pkg/air/logs/<channel_id>-air.log
_AIR_LOG_DIR = Path(__file__).resolve().parents[5] / "pkg" / "air" / "logs"

# Import ChannelConfig for type hints
from retrovue.runtime.config import ChannelConfig, MOCK_CHANNEL_CONFIG


def _open_air_log(channel_id: str):
    """Open Air log file for this channel (truncate on open, line-buffered). Caller closes after Popen."""
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel_id) or "unknown"
    log_path = _AIR_LOG_DIR / f"{safe_id}-air.log"
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


def air_load_preview(
    grpc_addr: str,
    channel_id_int: int,
    asset_path: str,
    start_offset_ms: int = 0,
    hard_stop_time_ms: int = 0,
    timeout_s: int = 90,
) -> bool:
    """Call Air LoadPreview RPC. Returns success. Raises on connection/RPC error."""
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.LoadPreview(
            playout_pb2.LoadPreviewRequest(
                channel_id=channel_id_int,
                asset_path=asset_path,
                start_offset_ms=start_offset_ms,
                hard_stop_time_ms=hard_stop_time_ms,
            ),
            timeout=timeout_s,
        )
    return r.success


def air_switch_to_live(grpc_addr: str, channel_id_int: int, timeout_s: int = 30) -> bool:
    """Call Air SwitchToLive RPC. Returns success. Raises on connection/RPC error."""
    import grpc

    playout_pb2, playout_pb2_grpc = _get_playout_stubs()
    with grpc.insecure_channel(grpc_addr) as ch:
        stub = playout_pb2_grpc.PlayoutControlStub(ch)
        r = stub.SwitchToLive(
            playout_pb2.SwitchToLiveRequest(channel_id=channel_id_int),
            timeout=timeout_s,
        )
    return r.success


def _launch_air_binary(
    *,
    air_bin: Path,
    asset_path: str,
    start_pts_ms: int,
    socket_path: Path,
    channel_id: str,
    channel_config: ChannelConfig,
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
        r = _rpc(
            "LoadPreview",
            lambda timeout: stub.LoadPreview(
                playout_pb2.LoadPreviewRequest(
                    channel_id=channel_id_int,
                    asset_path=asset_path,
                    start_offset_ms=start_pts_ms,
                    hard_stop_time_ms=0,
                ),
                timeout=timeout,
            ),
            _RPC_LOAD_PREVIEW_S,
        )
        if not r.success:
            raise RuntimeError(f"LoadPreview failed: {r.message}")
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
        # Phase 7: SwitchToLive may return NOT_READY if preview buffer isn't filled yet.
        # This is a transient state - retry with backoff until success or timeout.
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
            # NOT_READY variants are expected during buffer fill - retry
            if "not ready" in r.message.lower() or "NOT_READY" in r.message or "preparing" in r.message.lower():
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

