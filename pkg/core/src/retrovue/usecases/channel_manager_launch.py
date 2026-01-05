"""
Channel Manager usecase: Air process management.

Functions for launching and terminating Retrovue Air processes per channel.
Per ChannelManagerContract.md (Phase 8).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Type alias for subprocess.Process
ProcessHandle = subprocess.Popen[bytes]


def get_uds_socket_path(channel_id: str) -> Path:
    """
    Get the UDS socket path for a channel.
    
    Per Phase 9: /var/run/retrovue/air/channel_{channel_id}.sock
    
    Args:
        channel_id: Channel identifier
    
    Returns:
        Path to the UDS socket
    """
    socket_dir = Path("/var/run/retrovue/air")
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


def launch_air(
    *,
    playout_request: dict[str, Any],
    stdin: Any = subprocess.PIPE,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    ts_socket_path: str | Path | None = None,
) -> tuple[ProcessHandle, Path]:
    """
    Launch a Retrovue Air process for a channel.
    
    Per ChannelManagerContract.md (Phase 8) + Phase 9:
    - Launches Air as child process
    - Sends PlayoutRequest JSON via stdin
    - Closes stdin immediately after sending
    - Passes --ts-socket-path for Phase 9 UDS TS output
    
    Args:
        playout_request: PlayoutRequest dictionary (asset_path, start_pts, mode, channel_id, metadata)
        stdin: stdin pipe (default: subprocess.PIPE)
        stdout: stdout pipe (default: subprocess.PIPE)
        stderr: stderr pipe (default: subprocess.PIPE)
        ts_socket_path: UDS socket path for TS output (Phase 9). If None, auto-generated.
    
    Returns:
        Tuple of (process handle, socket path) for the launched Air process
    
    Example:
        ```python
        playout_request = {
            "asset_path": "/path/to/video.mp4",
            "start_pts": 0,
            "mode": "LIVE",
            "channel_id": "retro1",
            "metadata": {}
        }
        process, socket_path = launch_air(playout_request=playout_request)
        ```
    """
    # Build Air CLI command
    # Per PlayoutRequest.md: --channel-id <id> --mode live --request-json-stdin
    channel_id = playout_request.get("channel_id", "unknown")
    
    # Phase 9: Generate or use provided UDS socket path
    if ts_socket_path is None:
        socket_path = get_uds_socket_path(channel_id)
    else:
        socket_path = Path(ts_socket_path)
    
    # Ensure socket directory exists
    ensure_socket_dir_exists(socket_path)
    
    cmd = [
        "retrovue_air",  # TODO: Get actual Air command path from config
        "--channel-id", channel_id,
        "--mode", "live",
        "--request-json-stdin",
        "--ts-socket-path", str(socket_path),  # Phase 9: UDS output
    ]
    
    # Launch process
    process = subprocess.Popen(
        cmd,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        text=False,  # Binary mode for stdin/stdout/stderr
        bufsize=0,  # Unbuffered
    )
    
    # Send PlayoutRequest JSON via stdin
    # Per ChannelManagerContract.md: Send exactly one PlayoutRequest JSON, then close stdin
    if stdin == subprocess.PIPE and process.stdin:
        try:
            json_bytes = json.dumps(playout_request).encode("utf-8")
            process.stdin.write(json_bytes)
            process.stdin.flush()
            process.stdin.close()
        except Exception as e:
            # If stdin write fails, terminate process
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise RuntimeError(f"Failed to send PlayoutRequest to Air: {e}") from e
    
    return process, socket_path


def terminate_air(process: ProcessHandle) -> None:
    """
    Terminate a Retrovue Air process.
    
    Per ChannelManagerContract.md (Phase 8):
    - Terminates Air process when client_count drops to 0
    
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

